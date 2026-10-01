"""Build and test both server modes on Linux/WSL."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 7777


def stop_group(process):
    # Only stop processes started by this script.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run(command, env=None, timeout=180):
    print("\n>>> " + " ".join(map(str, command)), flush=True)
    process = subprocess.Popen(
        list(map(str, command)), cwd=ROOT, env=env,
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=timeout)
        if code:
            raise RuntimeError(f"Command failed with exit code {code}")
    finally:
        stop_group(process)


def require_free_port():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, PORT))
        except OSError as error:
            raise RuntimeError(
                "Port 7777 is unavailable. Stop your existing server first."
            ) from error


def wait_for_server(process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Server exited before becoming ready.")
        try:
            with socket.create_connection((HOST, PORT), timeout=0.2):
                pass
            if process.poll() is not None:
                raise RuntimeError("Server exited during startup.")
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Server did not become ready within 10 seconds.")


def main():
    require_free_port()

    run(["mvn", "-B", "-f", "server/pom.xml", "compile"])
    run(["make", "-C", "client"])

    with tempfile.TemporaryDirectory(prefix="stomp-parser-") as folder:
        executable = Path(folder) / "test_event_parser"
        run([
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Iclient/include",
            "tests/cpp/test_event_parser.cpp", "client/src/event.cpp",
            "-o", executable,
        ])
        run([executable])

    # Use this build and the local server, regardless of old shell overrides.
    env = os.environ.copy()
    env.update({
        "STOMP_CLIENT_BIN": str(ROOT / "client/bin/StompEMIClient"),
        "STOMP_TEST_HOST": HOST,
        "STOMP_TEST_PORT": str(PORT),
        "STOMP_TEST_VHOST": "stomp.cs.bgu.ac.il",
    })

    logs = Path(tempfile.mkdtemp(prefix="stomp-test-logs-"))
    print(f"\nServer logs: {logs}", flush=True)

    for mode in ("tpc", "reactor"):
        require_free_port()
        log_path = logs / f"{mode}.log"
        print(f"\n=== Testing {mode.upper()} ===", flush=True)

        with log_path.open("w") as log:
            server = subprocess.Popen([
                "java", "-cp", "server/target/classes",
                "bgu.spl.net.impl.stomp.StompServer", str(PORT), mode,
            ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)

            try:
                wait_for_server(server)
                run([
                    sys.executable, "-m", "unittest",
                    "discover", "-s", "tests", "-v",
                ], env=env)
                if server.poll() is not None:
                    raise RuntimeError("Server exited unexpectedly during tests.")
            except Exception:
                print(f"\nCheck server log: {log_path}", flush=True)
                raise
            finally:
                stop_group(server)

    print("\nPASS: C++ parser checks and Python suites on TPC and Reactor.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        sys.exit(1)
