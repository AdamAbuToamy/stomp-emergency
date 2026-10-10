import tempfile
import uuid
import urllib.request
import ipaddress
import json
import subprocess
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client/bin/StompEMIClient"
HOST = "127.0.0.1"
PORT = 8080

events = deque(maxlen=200)
events_lock = threading.Lock()
session_snapshot = {
    "login": None,
    "channels": {},
    "reports": deque(maxlen=100),
    "summary": None
}
command_lock = threading.Lock()
client = None
uploads = tempfile.TemporaryDirectory(prefix="stomp-dashboard-")


PAGE = (Path(__file__).resolve().parent / "index.html").read_text(encoding="utf-8")


def publish(event):
    with events_lock:
        kind = event.get("type")

        if kind in (
            "login_success", "logout_success", "server_error",
            "connection_failed", "connection_closed", "client_stopped"
        ):
            session_snapshot["login"] = None
            session_snapshot["channels"].clear()
            session_snapshot["reports"].clear()
            session_snapshot["summary"] = None

        if kind == "login_success":
            session_snapshot["login"] = event
        elif kind == "subscription_receipt":
            message = event.get("message", "")
            if message.startswith("Joined channel "):
                name = message[len("Joined channel "):]
                session_snapshot["channels"][name] = event
            elif message.startswith("Exited channel "):
                name = message[len("Exited channel "):]
                session_snapshot["channels"].pop(name, None)
        elif kind == "report_received":
            session_snapshot["reports"].append(event)
        elif kind == "summary_ready":
            session_snapshot["summary"] = event

        events.append(event)


def read_client():
    for line in client.stdout:
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                publish(event)
        except json.JSONDecodeError:
            print("Unexpected non-JSON client output:", line.rstrip())

    publish({
        "type": "client_stopped",
        "message": "C++ client stopped. Restart the dashboard."
    })


def credential(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError("Username and password must contain 1–100 characters")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127
           for char in value):
        raise ValueError("Username and password cannot contain spaces or controls")
    return value


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value, content_type="application/json"):
        if content_type == "application/json":
            body = json.dumps(value).encode("utf-8")
        else:
            body = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        expected = f"{HOST}:{PORT}"
        origin = self.headers.get("Origin")
        if self.headers.get("Host") != expected:
            self.respond(403, {"error": "Use the printed local dashboard URL"})
            return False
        if origin is not None and origin != f"http://{expected}":
            self.respond(403, {"error": "Origin not allowed"})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        if self.path == "/":
            self.respond(200, PAGE, "text/html")
        elif self.path == "/server-logs":
            logfile = ROOT / "logs/stomp-server-0.log"
            try:
                with logfile.open("rb") as handle:
                    handle.seek(0, 2)
                    size = handle.tell()
                    start = max(0, size - 65536)
                    handle.seek(start)
                    chunk = handle.read(65536)
                if start:
                    chunk = chunk.partition(b"\n")[2]
                lines = chunk.decode("utf-8", errors="replace").splitlines()
                self.respond(200, {
                    "lines": lines[-200:],
                    "message": "Latest saved events; this does not indicate server availability."
                })
            except FileNotFoundError:
                self.respond(200, {
                    "lines": [],
                    "message": "No log file yet. Start Java from the project folder and connect."
                })
            except OSError:
                self.respond(503, {"error": "Cannot read server log file"})
        elif self.path == "/session":
            with events_lock:
                snapshot = []
                login = session_snapshot["login"]
                if login is not None:
                    snapshot.append(login)
                    snapshot.extend(session_snapshot["channels"].values())
                    snapshot.extend(session_snapshot["reports"])
                    if session_snapshot["summary"] is not None:
                        snapshot.append(session_snapshot["summary"])
                # Single-tab dashboard: snapshot replaces pending UI events.
                events.clear()
            self.respond(200, snapshot)
        elif self.path == "/server-status":
            try:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({})
                )
                with opener.open(
                    "http://127.0.0.1:7778/status", timeout=1
                ) as response:
                    status = json.loads(response.read(8192))
                if not isinstance(status, dict):
                    raise ValueError("Invalid monitor response")
                self.respond(200, {"available": True, "status": status})
            except (OSError, ValueError):
                self.respond(200, {"available": False})
        elif self.path == "/events":
            with events_lock:
                batch = list(events)
                events.clear()
            self.respond(200, batch)
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self.local_request():
            return
        if self.path != "/command":
            self.respond(404, {"error": "Not found"})
            return
        if self.headers.get("X-STOMP-UI") != "1":
            self.respond(403, {"error": "Missing UI header"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1500000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")

            if data.get("action") == "login":
                host = str(ipaddress.IPv4Address(data.get("host", "")))
                port = int(data.get("port", 0))
                if not 1 <= port <= 65535:
                    raise ValueError("Port must be between 1 and 65535")
                user = credential(data.get("username"))
                password = credential(data.get("password"))
                command = f"login {host}:{port} {user} {password}\n"
            elif data.get("action") in ("join", "leave"):
                channel = credential(data.get("channel"))
                if not all(c.isascii() and (c.isalnum() or c in "_-/")
                           for c in channel):
                    raise ValueError("Invalid channel name")
                operation = "join" if data["action"] == "join" else "exit"
                command = f"{operation} {channel}\n"
            elif data.get("action") == "report":
                report = data.get("report")
                if not isinstance(report, dict):
                    raise ValueError("Expected a report object")
                channel = report.get("channel_name")
                if not isinstance(channel, str) or not channel:
                    raise ValueError("Missing channel_name")
                if not isinstance(report.get("events"), list):
                    raise ValueError("Missing events list")
                serialized = json.dumps(report, ensure_ascii=False)
                if len(serialized.encode("utf-8")) > 200000:
                    raise ValueError("Report too large")
                filename = Path(uploads.name) / (uuid.uuid4().hex + ".json")
                filename.write_text(serialized, encoding="utf-8")
                command = f"report {filename}\n"
            elif data.get("action") == "summary":
                channel = credential(data.get("channel"))
                user = credential(data.get("user"))
                filename = Path(uploads.name) / (uuid.uuid4().hex + ".txt")
                command = f"summary {channel} {user} {filename}\n"
            elif data.get("action") == "logout":
                command = "logout\n"
            else:
                raise ValueError("Unknown action")

            with command_lock:
                if client.poll() is not None:
                    raise BrokenPipeError()
                client.stdin.write(command)
                client.stdin.flush()

            # Accepted for processing; success comes from the C++ event.
            self.respond(202, {"accepted": True})
        except (ValueError, TypeError):
            self.respond(400, {
                "error": "Check your inputs. Channel names support letters, numbers, _, - and /."
            })
        except (BrokenPipeError, OSError):
            self.respond(503, {"error": "C++ client unavailable; restart dashboard"})

    def log_message(self, format, *args):
        # Do not log requests or credentials.
        pass


def main():
    global client

    if not CLIENT.is_file():
        raise SystemExit("Build the client first: make -C client")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        client = subprocess.Popen(
            [str(CLIENT), "--ui"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # stderr stays visible in this terminal.
            text=True,
            encoding="utf-8",
            bufsize=1
        )
        threading.Thread(target=read_client, daemon=True).start()
        print(f"Open http://{HOST}:{PORT}")
        print("One browser tab for this first version. Ctrl+C to stop.")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        # Finish cleanup even if the launcher sends another interrupt.
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        server.server_close()
        if client is not None:
            if client.poll() is None:
                client.terminate()
                try:
                    client.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    client.kill()
                    client.wait()
            client.stdin.close()
            client.stdout.close()


if __name__ == "__main__":
    main()