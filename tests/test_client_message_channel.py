"""A report body must not override the MESSAGE destination header.
Requires Java server on 127.0.0.1:7777 and the real C++ client.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import uuid
from test_connection_lifecycle import Peer
import test_client_report_summary as summary_support


class MessageChannelTests(unittest.TestCase):
    wait_for = summary_support.ReportSummaryTests.wait_for

    def test_message_destination_controls_summary_channel(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get('STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient'))).resolve()
        self.assertTrue(binary.is_file(), f'Build the client first: {binary}')
        channel = 'correct_' + uuid.uuid4().hex
        misleading_channel = 'body_' + uuid.uuid4().hex
        barrier = 'barrier_' + uuid.uuid4().hex
        owner = 'sender_' + uuid.uuid4().hex
        receiver_name = 'receiver_' + uuid.uuid4().hex
        sender = Peer()
        self.addCleanup(sender.close)
        self.assertEqual(sender.login(owner)[0], 'CONNECTED')
        sender.send('SUBSCRIBE', {'destination': channel, 'id': '10', 'receipt': 'joined'})
        self.assertEqual(sender.receive()[:2], ('RECEIPT', {'receipt-id': 'joined'}))
        with tempfile.TemporaryDirectory(prefix='stomp-channel-') as folder:
            summary_path = Path(folder) / 'summary.txt'
            process = subprocess.Popen([str(binary)], cwd=str(root / 'client'),
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, bufsize=0)
            output = bytearray()
            def command(text):
                process.stdin.write((text + '\n').encode())
                process.stdin.flush()
            try:
                command(f'login 127.0.0.1:7777 {receiver_name} demo123')
                self.wait_for(process, b'Login successful', output)
                command(f'join {channel}')
                self.wait_for(process, f'Joined channel {channel}'.encode(), output)
                body = (f'destination:{misleading_channel}\n'
                        f'user:{owner}\ncity:Test City\nevent name:Channel check\n'
                        'date time:1700000000\ngeneral information:\n'
                        '\tactive:true\n\tforces_arrival_at_scene:false\n'
                        'description:\nChannel must stay correct.\n')
                sender.send('SEND', {'destination': channel, 'receipt': 'sent'}, body)
                own_copy = sender.receive()
                self.assertEqual(own_copy[0], 'MESSAGE')
                self.assertEqual(own_copy[1].get('destination'), channel)
                self.assertEqual(own_copy[2], body)
                self.assertEqual(sender.receive()[:2], ('RECEIPT', {'receipt-id': 'sent'}))
                command(f'join {barrier}')
                self.wait_for(process, f'Joined channel {barrier}'.encode(), output)
                command(f'summary {channel} {owner} {summary_path}')
                command('channel_check_finished')
                self.wait_for(process, b'Unknown command: channel_check_finished', output)
                self.assertTrue(summary_path.is_file(), output.decode(errors='replace'))
                summary = summary_path.read_text(encoding='utf-8')
                self.assertIn('Total: 1', summary.splitlines(),
                              'The body must not move the event to another channel.\n' + summary)
                self.assertIn('event name: Channel check', summary.splitlines())
                try:
                    tail, _ = process.communicate(input=b'', timeout=3)
                except subprocess.TimeoutExpired:
                    self.fail('Client did not exit after EOF')
                output.extend(tail)
                self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
