"""Real C++ report -> Java broker -> same C++ client -> summary file.
Requires a Java server on 127.0.0.1:7777. No fixed sleeps for delivery.
"""
from pathlib import Path
import json
import os
import selectors
import subprocess
import tempfile
import time
import unittest
import uuid


class ReportSummaryTests(unittest.TestCase):
    def wait_for(self, process, marker, output):
        start = len(output)
        deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while marker not in output[start:]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.fail(f'Timed out waiting for {marker!r}:\n' + output.decode(errors='replace'))
                if not selector.select(remaining):
                    continue
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    self.fail('Client stopped unexpectedly:\n' + output.decode(errors='replace'))
                output.extend(chunk)
                if len(output) > 1024 * 1024:
                    self.fail('Client produced too much output')

    def test_reports_reach_summary_with_correct_fields_and_order(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get('STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient'))).resolve()
        self.assertTrue(binary.is_file(), f'Build the client first: {binary}')
        channel = 'report_' + uuid.uuid4().hex
        barrier = 'barrier_' + uuid.uuid4().hex
        user = 'summary_' + uuid.uuid4().hex
        reports = {'channel_name': channel, 'events': [
            {'event_name': 'Later report', 'city': 'Test City:North',
             'date_time': 1700000100, 'description': 'Later: keep clear.',
             'general_information': {'active': True, 'forces_arrival_at_scene': False}},
            {'event_name': 'Earlier report', 'city': 'Baqa',
             'date_time': 1700000000, 'description': 'Earlier: road clear.',
             'general_information': {'active': False, 'forces_arrival_at_scene': True}}
        ]}
        with tempfile.TemporaryDirectory(prefix='stomp-summary-') as folder:
            report_path = Path(folder) / 'reports.json'
            summary_path = Path(folder) / 'summary.txt'
            report_path.write_text(json.dumps(reports), encoding='utf-8')
            process = subprocess.Popen([str(binary)], cwd=str(root / 'client'),
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, bufsize=0)
            output = bytearray()
            def command(text):
                process.stdin.write((text + '\n').encode())
                process.stdin.flush()
            try:
                command(f'login 127.0.0.1:7777 {user} demo123')
                self.wait_for(process, b'Login successful', output)
                command(f'join {channel}')
                self.wait_for(process, f'Joined channel {channel}'.encode(), output)
                command(f'report {report_path}')
                # SENDs precede SUBSCRIBE on this connection. The broker queues
                # self-delivered MESSAGEs before the later subscription receipt.
                command(f'join {barrier}')
                self.wait_for(process, f'Joined channel {barrier}'.encode(), output)
                command(f'summary {channel} {user} {summary_path}')
                command('summary_finished_probe')
                self.wait_for(process, b'Unknown command: summary_finished_probe', output)
                self.assertTrue(summary_path.is_file(), output.decode(errors='replace'))
                summary = summary_path.read_text(encoding='utf-8')
                lines = summary.splitlines()
                for expected in (f'Channel {channel}', 'Total: 2', 'active: 1',
                                 'forces arrival at scene: 1', 'city: Test City:North',
                                 'city: Baqa', 'event name: Earlier report',
                                 'event name: Later report',
                                 'summary: Earlier: road clear.', 'summary: Later: keep clear.'):
                    self.assertIn(expected, lines, summary)
                self.assertLess(summary.index('event name: Earlier report'),
                                summary.index('event name: Later report'), summary)
                self.assertEqual(sum(line.startswith('Report_') for line in lines), 2, summary)
                try:
                    tail, _ = process.communicate(input=b'', timeout=3)
                except subprocess.TimeoutExpired:
                    self.fail('Client did not exit after generating the summary')
                output.extend(tail)
                self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
