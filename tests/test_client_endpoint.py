"""The C++ client must use the port provided in the login command."""
import os
from pathlib import Path
import socket
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get(
    "STOMP_CLIENT_BIN", str(ROOT / "client/bin/StompEMIClient")
)).resolve()


class ClientEndpointTests(unittest.TestCase):
    def test_login_uses_requested_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            port = listener.getsockname()[1]

            process = subprocess.Popen(
                [str(BINARY)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                process.stdin.write(
                    f"login 127.0.0.1:{port} endpoint_user demo123\n".encode()
                )
                process.stdin.flush()

                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    self.fail(
                        f"Client did not connect to requested port {port}. "
                        "It may still be using the hard-coded port 7777."
                    )

                with connection:
                    connection.settimeout(3)
                    data = b""
                    while b"\0" not in data:
                        chunk = connection.recv(4096)
                        if not chunk:
                            self.fail("Client closed before sending CONNECT.")
                        data += chunk
                        if len(data) > 65536:
                            self.fail("CONNECT exceeded the test size limit.")

                    self.assertTrue(data.startswith(b"CONNECT\n"), repr(data))
                    self.assertIn(b"login:endpoint_user\n", data)
                    connection.sendall(b"CONNECTED\nversion:1.2\n\n\0")

                    output, _ = process.communicate(input=b"", timeout=3)
                    self.assertEqual(
                        process.returncode, 0,
                        output.decode(errors="replace"),
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
