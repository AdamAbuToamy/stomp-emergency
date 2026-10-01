"""Check receipt tracking during bursts of client commands."""
import os
from pathlib import Path
import subprocess
import unittest
import uuid

import test_client_report_summary as support


class ClientReceiptTests(unittest.TestCase):
    wait_for = support.ReportSummaryTests.wait_for

    def test_join_exit_burst_confirms_every_command_once(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            "STOMP_CLIENT_BIN", str(root / "client/bin/StompEMIClient")
        )).resolve()
        prefix = "receipts_" + uuid.uuid4().hex
        channels = [f"{prefix}_{index}" for index in range(40)]

        process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        output = bytearray()

        def commands(lines):
            process.stdin.write(("\n".join(lines) + "\n").encode())
            process.stdin.flush()

        try:
            commands([f"login 127.0.0.1:7777 {prefix} demo123"])
            self.wait_for(process, b"Login successful", output)

            commands([f"join {channel}" for channel in channels])
            self.wait_for(
                process,
                f"Joined channel {channels[-1]}\n".encode(),
                output,
            )

            commands([f"exit {channel}" for channel in channels])
            self.wait_for(
                process,
                f"Exited channel {channels[-1]}\n".encode(),
                output,
            )

            commands([
                f"exit {channels[0]}",
                "receipt_test_finished",
            ])
            self.wait_for(
                process,
                b"Unknown command: receipt_test_finished\n",
                output,
            )

            tail, _ = process.communicate(input=b"", timeout=5)
            output.extend(tail)
            text = output.decode(errors="replace")
            self.assertEqual(process.returncode, 0, text)

            lines = text.splitlines()
            for channel in channels:
                self.assertEqual(
                    lines.count(f"Joined channel {channel}"), 1, text
                )
                self.assertEqual(
                    lines.count(f"Exited channel {channel}"), 1, text
                )

            self.assertIn(f"Not subscribed to {channels[0]}", lines)
            self.assertNotIn("Server error:", text)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
