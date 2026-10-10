#!/usr/bin/env python3
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description="Start the local STOMP application")
    parser.add_argument("--mode", choices=["tpc", "reactor"], default="tpc")
    args = parser.parse_args()

    for port in (7777, 8080):
        if port_open(port):
            print(f"Port {port} is already in use. Stop the existing service first.")
            return 1

    if not (ROOT / "client/bin/StompEMIClient").is_file():
        print("Build the client first: make -C client")
        return 1

    server_class = ROOT / (
        "server/target/classes/io/github/adamabutoamy/"
        "stomp/protocol/StompServer.class"
    )
    if not server_class.is_file():
        print("Build Java first: mvn -f server/pom.xml compile")
        return 1

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    java = None
    dashboard = None

    with (log_dir / "server-console.log").open("a", encoding="utf-8") as output:
        try:
            java = subprocess.Popen(
                [
                    "java", "-cp", str(ROOT / "server/target/classes"),
                    "io.github.adamabutoamy.stomp.protocol.StompServer",
                    "7777", args.mode
                ],
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT
            )

            deadline = time.monotonic() + 15
            while True:
                if java.poll() is not None:
                    raise RuntimeError("Java stopped. See logs/server-console.log")
                if port_open(7777):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Server startup timed out. See logs/server-console.log")
                time.sleep(0.1)

            dashboard = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "dashboard/app.py")],
                cwd=ROOT
            )

            print(f"\nSTOMP mode: {args.mode.upper()}", flush=True)
            print("Open http://127.0.0.1:8080", flush=True)
            print("Ctrl+C stops the dashboard and Java server.\n", flush=True)

            while True:
                if java.poll() is not None:
                    raise RuntimeError("Java stopped. See logs/server-console.log")
                if dashboard.poll() is not None:
                    raise RuntimeError("Dashboard stopped. Check the terminal output.")
                time.sleep(0.3)

        except KeyboardInterrupt:
            print("\nStopping application...")
        except (OSError, RuntimeError) as error:
            print(f"Error: {error}")
            return 1
        finally:
            # SIGINT lets app.py clean up its C++ child before exiting.
            if dashboard is not None and dashboard.poll() is None:
                import signal
                dashboard.send_signal(signal.SIGINT)
                try:
                    dashboard.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    stop(dashboard)
            stop(java)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
