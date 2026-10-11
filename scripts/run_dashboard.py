#!/usr/bin/env python3
"""Run the authenticated dashboard and a loopback-only Java server."""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
from auth import Store


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
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["tpc", "reactor"], default="tpc")
    args = parser.parse_args()
    port = int(os.environ.get("PORT", "8080"))
    stomp_port = int(os.environ.get("STOMP_PORT", "7777"))
    for candidate in (stomp_port, 7778, port):
        if port_open(candidate):
            print(f"Port {candidate} is occupied. Stop the existing service first.")
            return 1
    if not (ROOT / "client/bin/StompEMIClient").is_file():
        print("Run make -C client first.")
        return 1
    store = Store(os.environ.get("STOMP_DATA_DIR", str(ROOT / "data")))
    env = dict(os.environ, STOMP_BRIDGE_SECRET=store.bridge_key, STOMP_BIND="127.0.0.1")
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    java = web = None
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with (log_dir / "server-console.log").open("w") as output:
        try:
            java = subprocess.Popen([
                "java", "-cp", str(ROOT / "server/target/classes"),
                "io.github.adamabutoamy.stomp.protocol.StompServer", str(stomp_port), args.mode
            ], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 15
            while not port_open(stomp_port):
                if java.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Java startup failed. See logs/server-console.log")
                time.sleep(0.1)
            web = subprocess.Popen([sys.executable, "-u", str(ROOT / "dashboard/app.py")],
                                   cwd=ROOT, env=env, start_new_session=True)
            print(f"STOMP mode: {args.mode.upper()}. Ctrl+C stops the application.", flush=True)
            while web.poll() is None and java.poll() is None:
                time.sleep(0.3)
            raise RuntimeError("A service stopped. Check the logs above and logs/server-console.log")
        except KeyboardInterrupt:
            print("Stopping application...")
        except (RuntimeError, OSError) as error:
            print(error)
            return 1
        finally:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            stop(web)
            stop(java)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
