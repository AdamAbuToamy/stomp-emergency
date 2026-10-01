"""The same C++ process must support multiple login sessions."""
import os
from pathlib import Path
import subprocess
import unittest
import uuid

import test_client_report_summary as support


class ClientReloginTests(unittest.TestCase):
    wait_for = support.ReportSummaryTests.wait_for

    def test_logout_then_relogin_and_rejoin_same_channel(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            "STOMP_CLIENT_BIN", str(root / "client/bin/StompEMIClient")
        )).resolve()

        suffix = uuid.uuid4().hex
        channel = "relogin_" + suffix
        first_user = "first_" + suffix
        second_user = "second_" + suffix

        process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        output = bytearray()

        def command(text):
            process.stdin.write((text + "\n").encode())
            process.stdin.flush()

        try:
            for session, user in enumerate(
                [first_user, first_user, second_user], start=1
            ):
                with self.subTest(session=session, user=user):
                    command(f"login 127.0.0.1:7777 {user} demo123")
                    self.wait_for(process, b"Login successful\n", output)

                    command(f"join {channel}")
                    self.wait_for(
                        process,
                        f"Joined channel {channel}\n".encode(),
                        output,
                    )

                    # Leave the subscription active when logging out.
                    # The next session must be able to subscribe again.
                    command("logout")
                    self.wait_for(process, b"Logout successful\n", output)

            tail, _ = process.communicate(input=b"", timeout=5)
            output.extend(tail)
            text = output.decode(errors="replace")
            self.assertEqual(process.returncode, 0, text)

            lines = text.splitlines()
            self.assertEqual(lines.count("Login successful"), 3, text)
            self.assertEqual(lines.count("Logout successful"), 3, text)
            self.assertEqual(
                lines.count(f"Joined channel {channel}"), 3, text
            )
            self.assertNotIn("Already subscribed", text)
            self.assertNotIn("Server error:", text)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
