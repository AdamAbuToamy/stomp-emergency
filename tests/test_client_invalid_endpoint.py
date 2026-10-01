"""Invalid endpoints must not crash or stop command processing."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get(
    "STOMP_CLIENT_BIN", str(ROOT / "client/bin/StompEMIClient")
)).resolve()


class InvalidEndpointTests(unittest.TestCase):
    def test_invalid_endpoints_are_recoverable(self):
        endpoints = [
            "127.0.0.1",
            ":7777",
            "127.0.0.1:",
            "127.0.0.1:abc",
            "127.0.0.1:0",
            "127.0.0.1:-1",
            "127.0.0.1:65536",
            "127.0.0.1:99999999999999999999999",
            "127.0.0.1:7777:8888",
        ]

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                commands = (
                    f"login {endpoint} demo password\n"
                    "endpoint_error_probe\n"
                )
                result = subprocess.run(
                    [str(BINARY)],
                    input=commands,
                    text=True,
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
                output = result.stdout + result.stderr

                self.assertEqual(result.returncode, 0, output)
                self.assertIn("Login error:", output)
                self.assertIn("Unknown command: endpoint_error_probe", output)
                self.assertNotIn("Starting connect to", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
