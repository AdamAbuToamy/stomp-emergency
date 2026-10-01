"""Check summary consistency while the client receives a report burst."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

import test_client_report_summary as support


class SummarySnapshotTests(unittest.TestCase):
    wait_for = support.ReportSummaryTests.wait_for

    def test_summaries_remain_consistent_during_report_burst(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            "STOMP_CLIENT_BIN", str(root / "client/bin/StompEMIClient")
        )).resolve()
        channel = "snapshot_" + uuid.uuid4().hex
        user = "snapshot_user_" + uuid.uuid4().hex
        barrier = "snapshot_barrier_" + uuid.uuid4().hex
        count = 500

        def verify(path, expected=None):
            lines = path.read_text(encoding="utf-8").splitlines()

            def value(prefix):
                matches = [line for line in lines if line.startswith(prefix)]
                self.assertEqual(len(matches), 1, str(path))
                return int(matches[0][len(prefix):])

            total = value("Total: ")
            self.assertGreaterEqual(total, 0)
            self.assertLessEqual(total, count)
            self.assertEqual(value("active: "), total)
            self.assertEqual(value("forces arrival at scene: "), 0)
            self.assertEqual(
                sum(line.startswith("Report_") for line in lines), total
            )

            names = [
                line[len("event name: "):]
                for line in lines if line.startswith("event name: ")
            ]
            self.assertEqual(len(names), total)
            self.assertEqual(
                names, [f"Event {index}" for index in range(total)]
            )

            if expected is not None:
                self.assertEqual(total, expected)

        with tempfile.TemporaryDirectory(prefix="stomp-snapshot-") as folder:
            folder = Path(folder)
            reports = folder / "reports.json"
            reports.write_text(json.dumps({
                "channel_name": channel,
                "events": [
                    {
                        "event_name": f"Event {index}",
                        "city": "Test City",
                        "date_time": 1700000000 + index,
                        "description": "Snapshot consistency check.",
                        "general_information": {
                            "active": True,
                            "forces_arrival_at_scene": False,
                        },
                    }
                    for index in range(count)
                ],
            }), encoding="utf-8")

            process = subprocess.Popen(
                [str(binary)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0,
            )
            output = bytearray()

            def command(text):
                process.stdin.write((text + "\n").encode())
                process.stdin.flush()

            try:
                command(f"login 127.0.0.1:7777 {user} demo123")
                self.wait_for(process, b"Login successful", output)
                command(f"join {channel}")
                self.wait_for(
                    process, f"Joined channel {channel}".encode(), output
                )

                command(f"report {reports}")
                for index in range(12):
                    snapshot = folder / f"snapshot-{index}.txt"
                    marker = f"snapshot_done_{index}"
                    command(f"summary {channel} {user} {snapshot}")
                    command(marker)
                    self.wait_for(
                        process, f"Unknown command: {marker}".encode(), output
                    )
                    verify(snapshot)

                # On this connection, report SENDs precede this SUBSCRIBE.
                # Its receipt follows the self-delivered report messages.
                command(f"join {barrier}")
                self.wait_for(
                    process, f"Joined channel {barrier}".encode(), output
                )

                final = folder / "final.txt"
                command(f"summary {channel} {user} {final}")
                command("final_snapshot_done")
                self.wait_for(
                    process, b"Unknown command: final_snapshot_done", output
                )
                verify(final, expected=count)

                tail, _ = process.communicate(input=b"", timeout=5)
                output.extend(tail)
                self.assertEqual(
                    process.returncode, 0, output.decode(errors="replace")
                )
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
