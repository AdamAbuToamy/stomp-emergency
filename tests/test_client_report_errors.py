"""Real client report error recovery; requires Java server on 127.0.0.1:7777."""
from pathlib import Path
import os
import selectors
import subprocess
import tempfile
import time
import unittest
import uuid


class ClientReportErrorTests(unittest.TestCase):
    def wait_for(self, process, marker, output):
        deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            start = len(output)
            while marker not in output[start:]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.fail(f'Client did not print {marker!r}.\n' + output.decode(errors='replace'))
                if not selector.select(remaining):
                    continue
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    self.fail('Client stopped unexpectedly:\n' + output.decode(errors='replace'))
                output.extend(chunk)
                if len(output) > 1024 * 1024:
                    self.fail('Unexpectedly large client output')

    def check_report_error(self, report_path):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get('STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient'))).resolve()
        self.assertTrue(binary.is_file(), f'Build the client first: {binary}')
        process = subprocess.Popen([str(binary)], cwd=str(root / 'client'),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, bufsize=0)
        output = bytearray()
        try:
            username = 'report_error_' + uuid.uuid4().hex
            process.stdin.write(f'login 127.0.0.1:7777 {username} demo123\n'.encode())
            process.stdin.flush()
            self.wait_for(process, b'Login successful', output)
            # A second command proves the keyboard loop survived the report error.
            process.stdin.write(f'report {report_path}\nreport_error_probe\n'.encode())
            process.stdin.flush()
            self.wait_for(process, b'Unknown command: report_error_probe', output)
            self.assertIn('Report error:', output.decode(errors='replace'))
            try:
                tail, _ = process.communicate(input=b'', timeout=3)
            except subprocess.TimeoutExpired:
                self.fail('Client did not exit after EOF following a report error')
            output.extend(tail)
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_missing_report_file_is_recoverable(self):
        with tempfile.TemporaryDirectory(prefix='stomp-report-') as folder:
            self.check_report_error(Path(folder) / 'missing.json')

    def test_malformed_json_is_recoverable(self):
        with tempfile.TemporaryDirectory(prefix='stomp-report-') as folder:
            path = Path(folder) / 'broken.json'
            path.write_text('{this is not valid JSON', encoding='utf-8')
            self.check_report_error(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
