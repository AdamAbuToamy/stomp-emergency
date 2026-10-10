import tempfile
import uuid
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
command_lock = threading.Lock()
client = None
uploads = tempfile.TemporaryDirectory(prefix="stomp-dashboard-")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>STOMP Dashboard</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0; background: #0c1220; color: #e7edf8;
  font: 16px system-ui, sans-serif;
}
main { max-width: 760px; margin: 60px auto; padding: 24px; }
h1 { margin-bottom: 6px; }
.subtitle { color: #9eacc4; margin-bottom: 28px; }
.card {
  background: #151e30; border: 1px solid #293650;
  border-radius: 16px; padding: 24px; margin-bottom: 20px;
}
.row { display: flex; gap: 16px; flex-wrap: wrap; }
label { display: block; flex: 1; min-width: 180px; margin-bottom: 18px; }
input {
  display: block; width: 100%; margin-top: 8px; padding: 12px;
  background: #0c1220; color: white; border: 1px solid #3a4964;
  border-radius: 8px; font: inherit;
}
button {
  padding: 12px 22px; border: 0; border-radius: 8px;
  background: #5ee0b5; color: #09251d; font: inherit;
  font-weight: 600; cursor: pointer;
}
button.secondary { background: #293650; color: white; margin-left: 8px; }
button:disabled { opacity: .45; cursor: default; }
#status { color: #5ee0b5; overflow-wrap: anywhere; }
pre {
  white-space: pre-wrap; overflow-wrap: anywhere;
  max-height: 300px; overflow: auto; color: #bac8df;
  font-size: 13px;
}
</style>
</head>
<body>
<main>
  <h1>STOMP Emergency</h1>
  <p class="subtitle">Local client dashboard · C++ / Java</p>
  <section class="card">
    <p id="status" role="status">Disconnected</p>
    <form id="loginForm">
      <div class="row">
        <label>Server IPv4
          <input id="host" value="127.0.0.1" required>
        </label>
        <label>Port
          <input id="port" type="number" min="1" max="65535"
                 value="7777" required>
        </label>
      </div>
      <label>Username
        <input id="username" autocomplete="username" required maxlength="100">
      </label>
      <label>Password
        <input id="password" type="password"
               autocomplete="current-password" required maxlength="100">
      </label>
      <button id="connect" type="submit">Connect</button>
      <button id="disconnect" class="secondary" type="button" disabled>
        Disconnect
      </button>
    </form>
  </section>
  <section class="card">
    <h2>Channels</h2>
    <label>Channel name
      <input id="channel" value="police" maxlength="100">
    </label>
    <button id="join" type="button" disabled>Join</button>
    <button id="leave" class="secondary" type="button" disabled>Leave</button>
    <p id="channelStatus" role="status">Connect first</p>
  </section>
  <section class="card">
    <h2>Reports</h2>
    <label>Report JSON file
      <input id="reportFile" type="file" accept=".json,application/json">
    </label>
    <button id="sendReport" type="button" disabled>Send report</button>
    <p id="reportStatus" role="status">Join the report's channel first</p>
    <div id="reports"></div>
  </section>
  <section class="card">
    <h2>Summary</h2>
    <div class="row">
      <label>Channel
        <input id="summaryChannel" value="police" maxlength="100">
      </label>
      <label>Report author
        <input id="summaryUser" placeholder="adam" maxlength="100">
      </label>
    </div>
    <button id="makeSummary" type="button" disabled>Generate summary</button>
    <button id="downloadSummary" class="secondary" type="button" disabled>
      Download .txt
    </button>
    <pre id="summaryText">No summary generated yet.</pre>
  </section>
  <section class="card">
    <h2>Server logs</h2>
    <p class="subtitle">Latest saved Java server events · timestamps in UTC</p>
    <label>Level
      <select id="logLevel">
        <option value="ALL">All</option>
        <option value="INFO">INFO</option>
        <option value="WARNING">WARNING</option>
        <option value="SEVERE">ERROR</option>
      </select>
    </label>
    <p id="serverLogStatus" role="status">Loading log file...</p>
    <pre id="serverLogs"></pre>
  </section>
  <section class="card">
    <h2>Client events</h2>
    <pre id="log">Waiting for events...</pre>
  </section>
</main>
<script>
const el = id => document.getElementById(id);
let connected = false;
const subscribedChannels = new Set();
let summaryContent = "";
const history = [];

function setState(value, message) {
  connected = value;
  if (!value) subscribedChannels.clear();
  el("status").textContent = message;
  el("connect").disabled = value;
  el("disconnect").disabled = !value;
  el("makeSummary").disabled = !value;
  if (!value) {
    summaryContent = "";
    el("downloadSummary").disabled = true;
    el("summaryText").textContent = "No summary generated yet.";
  }
  el("sendReport").disabled = !value;
  if (!value) {
    el("reports").replaceChildren();
    el("reportStatus").textContent = "Join the report's channel first";
  }
  el("join").disabled = !value;
  el("leave").disabled = !value;
  if (!value) el("channelStatus").textContent = "Connect first";
}

async function command(action, data = {}) {
  el("connect").disabled = true;
  el("disconnect").disabled = true;
  el("status").textContent = action === "login"
    ? "Connecting..." : "Disconnecting...";
  try {
    const response = await fetch("/command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-STOMP-UI": "1"
      },
      body: JSON.stringify({action, ...data})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
  } catch (error) {
    setState(connected, error.message);
  }
}

el("loginForm").addEventListener("submit", event => {
  event.preventDefault();
  command("login", {
    host: el("host").value.trim(),
    port: el("port").value,
    username: el("username").value,
    password: el("password").value
  });
});

el("disconnect").addEventListener("click", () => command("logout"));

async function channelCommand(action) {
  const channel = el("channel").value.trim();
  if (!channel) {
    el("channelStatus").textContent = "Enter a channel name";
    return;
  }

  el("channelStatus").textContent = "Sending request...";
  try {
    const response = await fetch("/command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-STOMP-UI": "1"
      },
      body: JSON.stringify({action, channel})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    el("channelStatus").textContent = "Request sent; waiting for confirmation";
  } catch (error) {
    el("channelStatus").textContent = error.message;
  }
}

el("join").addEventListener("click", () => channelCommand("join"));
el("leave").addEventListener("click", () => channelCommand("leave"));

el("sendReport").addEventListener("click", async () => {
  const file = el("reportFile").files[0];
  if (!file) {
    el("reportStatus").textContent = "Choose a JSON file first";
    return;
  }
  if (file.size > 200000) {
    el("reportStatus").textContent = "Maximum file size: 200 KB";
    return;
  }

  el("sendReport").disabled = true;
  try {
    const report = JSON.parse(await file.text());
    if (!report || typeof report !== "object" || Array.isArray(report)) {
      throw new Error("The report must be a JSON object.");
    }

    const destination = report.channel_name;
    if (typeof destination !== "string" || !destination) {
      throw new Error("The report is missing channel_name.");
    }

    if (!subscribedChannels.has(destination)) {
      throw new Error(
        'This report targets "' + destination +
        '". Join that channel before sending. Nothing was sent.'
      );
    }
    const response = await fetch("/command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-STOMP-UI": "1"
      },
      body: JSON.stringify({action: "report", report})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    el("reportStatus").textContent =
      "File passed to C++ client. Incoming reports appear below.";
  } catch (error) {
    el("reportStatus").textContent = error.message;
  } finally {
    el("sendReport").disabled = !connected;
  }
});

el("makeSummary").addEventListener("click", async () => {
  summaryContent = "";
  el("downloadSummary").disabled = true;
  el("summaryText").textContent = "Generating...";
  try {
    const response = await fetch("/command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-STOMP-UI": "1"
      },
      body: JSON.stringify({
        action: "summary",
        channel: el("summaryChannel").value.trim(),
        user: el("summaryUser").value.trim()
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
  } catch (error) {
    el("summaryText").textContent = error.message;
  }
});

el("downloadSummary").addEventListener("click", () => {
  const blob = new Blob([summaryContent], {
    type: "text/plain;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "stomp-summary.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

let serverLogLines = [];

function renderServerLogs() {
  const level = el("logLevel").value;
  const lines = serverLogLines.filter(line =>
    level === "ALL" || line.split(/\\s+/)[1] === level
  );
  el("serverLogs").textContent =
    lines.length ? lines.join("\\n") : "No matching events";
}

el("logLevel").addEventListener("change", renderServerLogs);

async function pollServerLogs() {
  try {
    const response = await fetch("/server-logs", {cache: "no-store"});
    if (!response.ok) throw new Error("Could not read server logs");
    const data = await response.json();
    serverLogLines = data.lines;
    el("serverLogStatus").textContent = data.message;
    renderServerLogs();
  } catch (error) {
    el("serverLogStatus").textContent = error.message;
  } finally {
    setTimeout(pollServerLogs, 1500);
  }
}
pollServerLogs();

async function poll() {
  try {
    const response = await fetch("/events", {cache: "no-store"});
    if (!response.ok) throw new Error("Dashboard unavailable");
    const items = await response.json();

    for (const event of items) {
      history.push(JSON.stringify(event));
      if (history.length > 100) history.shift();
      el("log").textContent = history.join("\\n");

      if (event.type === "report_received") {
        const card = document.createElement("article");
        card.className = "card";
        const title = document.createElement("h3");
        title.textContent = event.name;
        const metadata = document.createElement("p");
        metadata.textContent =
          event.channel + " · " + event.city + " · " + event.user;
        const description = document.createElement("p");
        description.textContent = event.description;
        card.append(title, metadata, description);
        el("reports").prepend(card);
        while (el("reports").children.length > 100) {
          el("reports").lastElementChild.remove();
        }
      }

      if (event.type === "summary_ready") {
        summaryContent = event.content;
        el("summaryText").textContent = summaryContent;
        el("downloadSummary").disabled = false;
      } else if (event.type === "summary_error") {
        summaryContent = "";
        el("summaryText").textContent = event.message;
        el("downloadSummary").disabled = true;
      }

      if (event.type === "subscription_receipt") {
        const message = event.message || "";
        if (message.startsWith("Joined channel ")) {
          subscribedChannels.add(message.slice("Joined channel ".length));
        } else if (message.startsWith("Exited channel ")) {
          subscribedChannels.delete(message.slice("Exited channel ".length));
        }
        el("channelStatus").textContent = event.message;
      }

      if (event.type === "login_success") {
        setState(true, "Connected as " + event.user);
        el("summaryUser").value = event.user;
        el("password").value = "";
        el("channelStatus").textContent = "Choose a channel, then press Join";
      } else if (event.type === "logout_success") {
        setState(false, "Disconnected");
      } else if ([
        "server_error", "connection_failed",
        "connection_closed", "client_stopped"
      ].includes(event.type)) {
        setState(false, event.message || event.type);
      }
    }
  } catch (error) {
    el("status").textContent = "Cannot reach the local dashboard";
  } finally {
    setTimeout(poll, 400);
  }
}
poll();
</script>
</body>
</html>
"""


def publish(event):
    with events_lock:
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