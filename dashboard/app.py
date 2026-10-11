"""Authenticated local/HTTPS-proxied dashboard. One process; SQLite persistence."""
import ipaddress
import json
import os
import re
import secrets
import signal
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from auth import Store, username
from bridge import Bridge
from incidents import Incidents, AccessDenied, Conflict

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("STOMP_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
ORIGIN = os.environ.get("STOMP_ORIGIN", f"http://127.0.0.1:{PORT}").rstrip("/")
DATA = Path(os.environ.get("STOMP_DATA_DIR", str(ROOT / "data")))
STOMP_PORT = int(os.environ.get("STOMP_PORT", "7777"))
COOKIE = "stomp_session"
SECURE = ORIGIN.startswith("https://")
CHANNEL = re.compile(r"[A-Za-z0-9_/-]{1,64}\Z")
MAX_SESSIONS = 24


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Application:
    def __init__(self):
        self.store = Store(DATA)
        self.incidents = Incidents(self.store)
        self.policy_lock = threading.RLock()
        self.lock = threading.RLock()
        self.runtimes = {}
        self.limits = defaultdict(deque)
        self.hash_gate = threading.BoundedSemaphore(1)
        self.stopping = threading.Event()
        threading.Thread(target=self.reaper, daemon=True).start()

    def rate(self, key, limit, period=60):
        now = time.monotonic()
        with self.lock:
            # Drop unused keys; cap metadata growth for arbitrary usernames/IPs.
            if len(self.limits) > 4000:
                self.limits = defaultdict(deque, {k:v for k,v in self.limits.items()
                                                   if v and v[-1] > now - period})
                if len(self.limits) > 4000:
                    raise Problem(429, "Too many requests. Try later.")
            queue = self.limits[key]
            while queue and queue[0] <= now - period:
                queue.popleft()
            if len(queue) >= limit:
                raise Problem(429, "Too many requests. Please wait a minute.")
            queue.append(now)

    def runtime(self, session):
        with self.lock:
            digest = session["digest"]
            with self.store.connect() as db:
                valid = db.execute("SELECT 1 FROM sessions WHERE digest=? AND expires>?",
                                   (digest, time.time())).fetchone()
            if not valid:
                raise Problem(401, "Session expired. Sign in again.")
            if digest not in self.runtimes:
                if len(self.runtimes) >= MAX_SESSIONS:
                    raise Problem(503, "Server is at capacity. Try again later.")
                self.runtimes[digest] = Bridge(ROOT, session["username"],
                                              self.store.ticket(session["username"]), STOMP_PORT)
            bridge = self.runtimes[digest]
            bridge.last_used = time.monotonic()
            return bridge

    def drop(self, digest):
        self.store.revoke(digest)
        with self.lock:
            bridge = self.runtimes.pop(digest, None)
        if bridge:
            bridge.close()

    def reaper(self):
        while not self.stopping.wait(30):
            with self.store.connect() as db:
                alive = {r[0] for r in db.execute("SELECT digest FROM sessions WHERE expires>?", (time.time(),))}
            with self.lock:
                expired = [k for k,b in self.runtimes.items()
                           if k not in alive or time.monotonic() - b.last_used > 1800]
            for digest in expired:
                self.drop(digest)

    def close(self):
        self.stopping.set()
        with self.lock:
            bridges = list(self.runtimes.values())
            self.runtimes.clear()
        for bridge in bridges:
            bridge.close()


def channel(value):
    if not isinstance(value, str) or not CHANNEL.fullmatch(value):
        raise ValueError("Channel: 1–64 letters, numbers, _, - or /.")
    return value


def report_data(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a report object.")
    destination = channel(value.get("channel_name"))
    rows = value.get("events")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError("A report file must contain 1–20 events.")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid event.")
        result = {}
        for key, length in (("event_name", 120), ("city", 100), ("description", 5000)):
            val = row.get(key)
            if not isinstance(val, str) or not val.strip() or len(val) > length:
                raise ValueError(f"Invalid {key}.")
            if any(ord(c) < 32 and not (key == "description" and c in '\n\t') for c in val):
                raise ValueError("Control characters are not allowed in report fields.")
            result[key] = val
        stamp = row.get("date_time")
        if type(stamp) is not int or not 0 <= stamp <= 2147483647:
            raise ValueError("Invalid report timestamp.")
        info = row.get("general_information")
        if not isinstance(info, dict) or any(type(info.get(k)) is not bool for k in ("active", "forces_arrival_at_scene")):
            raise ValueError("Report status fields must be true or false.")
        result["date_time"] = stamp
        result["general_information"] = {k: info[k] for k in ("active", "forces_arrival_at_scene")}
        clean.append(result)
    return {"channel_name": destination, "events": clean}


class Handler(BaseHTTPRequestHandler):
    server_version = "STOMP-Dashboard"

    @property
    def app(self):
        return self.server.app

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def respond(self, status, value, kind="application/json", cookie=None):
        body = json.dumps(value).encode() if kind == "application/json" else value.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if SECURE:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if cookie is not None:
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age={43200 if cookie else 0}" + ("; Secure" if SECURE else ""))
        self.end_headers()
        self.wfile.write(body)

    def guard(self, post=False):
        if self.headers.get("Host") != urllib.parse.urlsplit(ORIGIN).netloc:
            raise Problem(403, "Host not allowed.")
        origin = self.headers.get("Origin")
        if origin is not None and origin != ORIGIN:
            raise Problem(403, "Origin not allowed.")
        if post and (origin != ORIGIN or self.headers.get("X-STOMP-UI") != "1"):
            raise Problem(403, "Invalid request origin.")

    def session(self, required=True):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie[COOKIE].value if COOKIE in cookie else ""
        except Exception:
            token = ""
        session = self.app.store.session(token) if len(token) <= 100 else None
        if required and not session:
            raise Problem(401, "Please sign in.")
        return session

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        try:
            self.guard(post)
            if post:
                self.post()
            else:
                self.get()
        except Problem as error:
            self.respond(error.status, {"error": error.message})
        except AccessDenied as error:
            self.respond(403, {"error": str(error)})
        except Conflict as error:
            self.respond(409, {"error": str(error)})
        except (ValueError, TypeError) as error:
            self.respond(400, {"error": str(error)})
        except (RuntimeError, OSError):
            try:
                self.respond(503, {"error": "Messaging service unavailable. Sign out and try again."})
            except OSError:
                pass

    def get(self):
        route = urllib.parse.urlsplit(self.path)
        assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                  "/style.css": ("style.css", "text/css")}
        if route.path in assets:
            name, kind = assets[route.path]
            self.respond(200, (ROOT / "dashboard" / name).read_text(), kind)
            return
        if route.path == "/health":
            self.respond(200, {"status": "ok"})
            return
        session = self.session(required=route.path != "/session")
        if route.path == "/session":
            if not session:
                self.respond(200, {"user": None, "events": [], "cursor": 0})
                return
            snapshot = self.app.runtime(session).snapshot()
            snapshot["user"] = {"name": session["username"], "role": session["role"]}
            self.respond(200, snapshot)
        elif route.path == "/incidents":
            query = {k: v[0] for k,v in urllib.parse.parse_qs(route.query).items()}
            self.respond(200, self.app.incidents.list(session, query))
        elif route.path.startswith("/incidents/"):
            self.respond(200, self.app.incidents.detail(session, int(route.path.rsplit("/",1)[1])))
        elif route.path == "/access":
            if session["role"] != "admin":
                raise AccessDenied("Administrator access required.")
            self.respond(200, self.app.incidents.admin_state())
        elif route.path == "/events":
            cursor = int(urllib.parse.parse_qs(route.query).get("after", ["0"])[0])
            self.respond(200, self.app.runtime(session).since(max(cursor, 0)))
        elif route.path in ("/server-logs", "/server-status"):
            if session["role"] != "admin":
                raise Problem(403, "Administrator access required.")
            if route.path == "/server-status":
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open("http://127.0.0.1:7778/status", timeout=1) as response:
                        data = json.loads(response.read(8192))
                    self.respond(200, {"available": True, "status": data})
                except (OSError, ValueError):
                    self.respond(200, {"available": False})
            else:
                try:
                    with (ROOT / "logs/stomp-server-0.log").open("rb") as stream:
                        stream.seek(0, 2)
                        start = max(0, stream.tell() - 65536)
                        stream.seek(start)
                        chunk = stream.read(65536)
                    if start:
                        chunk = chunk.partition(b'\n')[2]
                    lines = chunk.decode(errors="replace").splitlines()[-200:]
                except FileNotFoundError:
                    lines = []
                self.respond(200, {"lines": lines, "message": "Local server logs · UTC"})
        else:
            raise Problem(404, "Not found.")

    def post(self):
        if self.headers.get("Transfer-Encoding"):
            raise Problem(400, "Unsupported request encoding.")
        limit = 1500000 if self.path == "/command" else 4096
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= limit:
            raise Problem(413, "Request is too large or empty.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        self.app.rate(("ip", self.client_address[0]), 120)
        if self.path in ("/auth/register", "/auth/login"):
            name = username(data.get("username"))
            self.app.rate(("auth-ip", self.client_address[0]), 20)
            self.app.rate(("auth-user", name), 8)
            if not self.app.hash_gate.acquire(blocking=False):
                raise Problem(429, "Another sign-in is being processed. Try again shortly.")
            try:
                if self.path == "/auth/register":
                    self.app.store.register(name, data.get("password"))
                elif not self.app.store.verify(name, data.get("password")):
                    raise Problem(401, "Incorrect username or password.")
                # One active browser session per account. New login revokes the old one.
                with self.app.lock:
                    old = [k for k,b in self.app.runtimes.items() if b.name == name]
                    for digest in old:
                        self.app.drop(digest)
                    token, digest = self.app.store.issue(name)
                    try:
                        session = self.app.store.session(token)
                        self.app.runtime(session)
                    except Exception:
                        self.app.drop(digest)
                        raise
                self.respond(201 if self.path == "/auth/register" else 200, {"signed_in": True}, cookie=token)
            finally:
                self.app.hash_gate.release()
            return
        session = self.session()
        if self.path == "/auth/password":
            self.app.rate(("password", session["username"]), 5)
            if data.get("new_password") != data.get("confirm_password"):
                raise ValueError("New passwords do not match.")
            if not self.app.hash_gate.acquire(blocking=False):
                raise Problem(429, "Another sign-in is being processed. Try again shortly.")
            try:
                with self.app.policy_lock, self.app.lock:
                    session = self.session()
                    self.app.store.change_password(session["username"], data.get("current_password"),
                                                   data.get("new_password"), session["digest"])
                    for digest, runtime in list(self.app.runtimes.items()):
                        if runtime.name == session["username"]:
                            self.app.drop(digest)
                self.respond(200, {"password_changed": True}, cookie="")
            finally:
                self.app.hash_gate.release()
            return
        if self.path == "/auth/logout":
            self.app.drop(session["digest"])
            self.respond(200, {"signed_out": True}, cookie="")
            return
        if self.path == "/incidents/update":
            with self.app.policy_lock:
                self.app.incidents.update(self.session(), data)
            self.respond(200, {"saved": True})
            return
        if self.path == "/access":
            # Serialize policy changes with commands. Revoke affected active sessions
            # so existing STOMP subscriptions cannot outlive channel authorization.
            with self.app.policy_lock:
                session = self.session()
                self.app.incidents.administer(session, data)
                with self.app.lock:
                    for digest, runtime in list(self.app.runtimes.items()):
                        affected = (data.get("action") == "channel" or runtime.name == data.get("username"))
                        if affected and digest != session["digest"]:
                            self.app.drop(digest)
            self.respond(200, {"saved": True})
            return
        if self.path != "/command":
            raise Problem(404, "Not found.")
        self.app.rate(("commands", session["digest"]), 60)
        bridge = self.app.runtime(session)
        with self.app.policy_lock, bridge.commands:
            session = self.session()
            action = data.get("action")
            if action in ("join", "leave"):
                destination = channel(data.get("channel"))
                if action == "join":
                    self.app.incidents.require(session, destination)
                with bridge.lock:
                    exists = destination in bridge.channels
                    if action == "join" and len(bridge.channels) >= 30 and not exists:
                        raise ValueError("Maximum 30 channels per session.")
                if (action == "join") == exists:
                    raise ValueError("Already joined." if exists else "You have not joined that channel.")
                operation = "join" if action == "join" else "exit"
                bridge.execute(f"{operation} {destination}", "subscription_receipt")
            elif action in ("report", "summary"):
                if action == "report":
                    report = report_data(data.get("report"))
                    destination = report["channel_name"]
                    with bridge.lock:
                        if destination not in bridge.channels:
                            raise ValueError(f'Join "{destination}" before sending. Nothing was sent.')
                    batch, ids, fresh, delivery = self.app.incidents.create(session, report, data.get("request_id"))
                    if not fresh:
                        self.respond(200, {"accepted": True, "incident_ids": ids, "delivery": delivery})
                        return
                    filename = Path(bridge.uploads.name) / (secrets.token_hex(16) + ".json")
                    command, expected = f"report {filename}", "report_submitted"
                else:
                    destination = channel(data.get("channel"))
                    self.app.incidents.require(session, destination)
                    author = username(data.get("user"))
                    filename = Path(bridge.uploads.name) / (secrets.token_hex(16) + ".txt")
                    command, expected = f"summary {destination} {author} {filename}", "summary_ready"
                try:
                    if action == "report":
                        filename.write_text(json.dumps(report), encoding="utf-8")
                    bridge.execute(command, expected)
                    if action == "report":
                        self.app.incidents.delivery(batch, "submitted")
                except (RuntimeError, OSError):
                    if action == "report":
                        self.app.incidents.delivery(batch, "unknown")
                        self.respond(200, {"accepted": True, "incident_ids": ids, "delivery": "unknown"})
                        return
                    raise
                finally:
                    filename.unlink(missing_ok=True)
            else:
                raise ValueError("Unknown action.")
        self.respond(200, {"accepted": True, **({"incident_ids": ids, "delivery": "submitted"} if action == "report" else {})})

    def log_message(self, *_):
        pass


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    if HOST not in ("127.0.0.1", "localhost") and not SECURE:
        raise SystemExit("Public binding requires STOMP_ORIGIN=https://your-domain and an HTTPS proxy.")
    if not (ROOT / "client/bin/StompEMIClient").is_file():
        raise SystemExit("Build the C++ client first.")
    app = Application()
    server = WebServer((HOST, PORT), Handler)
    server.app = app
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        print(f"Open {ORIGIN}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
