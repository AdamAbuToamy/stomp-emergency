"""One real C++ process per authenticated browser session."""
import json
import os
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

FATAL = {"server_error", "connection_failed", "connection_closed", "client_stopped"}


class Bridge:
    def __init__(self, root, name, ticket, port):
        self.name = name
        self.lock = threading.Condition(threading.RLock())
        self.commands = threading.Lock()
        self.events = deque(maxlen=300)
        self.reports = deque(maxlen=100)
        self.channels = {}
        self.summary = None
        self.seq = 0
        self.connected = False
        self.closed = False
        self.failure = None
        self.received = 0
        self.last_used = time.monotonic()
        self.uploads = tempfile.TemporaryDirectory(prefix="stomp-session-")
        self.process = subprocess.Popen(
            [str(root / "client/bin/StompEMIClient"), "--ui"], cwd=root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, start_new_session=True)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        try:
            self.execute(f"login 127.0.0.1:{port} {name} {ticket}", "login_success")
        except Exception:
            self.close()
            raise

    def publish(self, event):
        with self.lock:
            kind = event.get("type")
            if kind == "login_success":
                self.connected = True
            elif kind in FATAL:
                self.connected = False
                self.failure = event.get("message", "STOMP connection closed")
            elif kind == "subscription_receipt":
                msg = event.get("message", "")
                if msg.startswith("Joined channel "):
                    self.channels[msg[len("Joined channel "):]] = event
                elif msg.startswith("Exited channel "):
                    self.channels.pop(msg[len("Exited channel "):], None)
            elif kind == "report_received":
                self.reports.append(event)
                self.received += 1
            elif kind == "summary_ready":
                self.summary = event
            self.seq += 1
            self.events.append((self.seq, event))
            self.lock.notify_all()

    def read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 500000:
                    break
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        self.publish(event)
                        if self.received >= 2000:
                            self.process.terminate()
                            break
                except (ValueError, TypeError):
                    continue
        finally:
            self.publish({"type": "connection_closed", "message":
                          "Session connection ended. Sign in again."})

    def execute(self, command, expected, timeout=8):
        # Caller serializes user commands. Login is serialized by construction.
        with self.lock:
            if self.closed or self.failure:
                raise RuntimeError("STOMP connection unavailable. Sign out and sign in again.")
            start = self.seq
            try:
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise RuntimeError("STOMP client stopped.") from None
            end = time.monotonic() + timeout
            while True:
                for seq, event in self.events:
                    if seq <= start:
                        continue
                    if event.get("type") in FATAL | {"command_error", "summary_error"}:
                        raise RuntimeError(event.get("message", "STOMP command failed"))
                    if event.get("type") == expected:
                        return event
                remaining = end - time.monotonic()
                if remaining <= 0:
                    # Do not accept another command after an ambiguous timeout.
                    self.failure = "STOMP response timed out. Sign out and sign in again."
                    self.process.terminate()
                    raise RuntimeError(self.failure)
                self.lock.wait(remaining)

    def snapshot(self):
        with self.lock:
            result = []
            if self.connected:
                result = [{"type": "login_success", "user": self.name}]
                result += list(self.channels.values()) + list(self.reports)
                if self.summary:
                    result.append(self.summary)
            elif self.failure:
                result.append({"type": "connection_closed", "message": self.failure})
            return {"events": result, "cursor": self.seq}

    def since(self, cursor):
        with self.lock:
            if self.events and cursor < self.events[0][0] - 1:
                return {"resync": True, "events": [], "cursor": self.seq}
            return {"events": [e for n, e in self.events if n > cursor], "cursor": self.seq}

    def close(self):
        with self.commands:
            if self.closed:
                return
            self.closed = True
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.reader.join(timeout=2)
            self.process.stdin.close()
            self.process.stdout.close()
            self.uploads.cleanup()
