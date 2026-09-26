"""TCP byte-stream integration tests. Writes do not imply packet/read boundaries."""
import select
import unittest
import uuid
from test_connection_lifecycle import Peer, VHOST


def frame(command, headers=None, body=''):
    fields = ''.join(f'{k}:{v}\n' for k, v in (headers or {}).items())
    return f'{command}\n{fields}\n{body}\0'.encode('utf-8')


class TcpStreamTests(unittest.TestCase):
    def peer(self):
        peer = Peer()
        self.addCleanup(peer.close)
        return peer

    def connect_bytes(self):
        return frame('CONNECT', {'accept-version': '1.2', 'host': VHOST,
                                 'login': 'stream_' + uuid.uuid4().hex,
                                 'passcode': 'stream-demo'})

    def connected(self, peer):
        reply = peer.receive()
        self.assertEqual(reply[0], 'CONNECTED', repr(reply))
        self.assertEqual(reply[1].get('version'), '1.2')

    def receipt(self, peer, value):
        reply = peer.receive()
        self.assertEqual(reply[0], 'RECEIPT', repr(reply))
        self.assertEqual(reply[1].get('receipt-id'), value)

    def message(self, peer, channel, sub_id, body):
        reply = peer.receive()
        self.assertEqual(reply[0], 'MESSAGE', repr(reply))
        self.assertEqual(reply[1].get('destination'), channel)
        self.assertEqual(reply[1].get('subscription'), sub_id)
        self.assertEqual(reply[2], body)

    def test_connect_waits_for_terminator_across_writes(self):
        peer = self.peer()
        data = self.connect_bytes()
        for part in (data[:3], data[3:17], data[17:-1]):
            peer.socket.sendall(part)
        # Bounded observation: no premature reply while the frame is incomplete.
        readable, _, _ = select.select([peer.socket], [], [], 0.2)
        self.assertFalse(readable, 'Server replied or closed before the null terminator')
        peer.socket.sendall(data[-1:])
        self.connected(peer)

    def test_connect_subscribe_and_send_in_one_write(self):
        peer = self.peer()
        channel = '/batch-' + uuid.uuid4().hex
        body = 'first line\n\nsecond line: value'
        data = self.connect_bytes()
        data += frame('SUBSCRIBE', {'destination': channel, 'id': '10', 'receipt': 'joined'})
        data += frame('SEND', {'destination': channel, 'receipt': 'sent'}, body)
        peer.socket.sendall(data)
        self.connected(peer)
        self.receipt(peer, 'joined')
        self.message(peer, channel, '10', body)
        self.receipt(peer, 'sent')

    def test_large_utf8_body_survives_chunked_writes(self):
        sender, receiver = self.peer(), self.peer()
        channel = '/utf8-' + uuid.uuid4().hex
        for peer, sub_id in ((sender, '10'), (receiver, '20')):
            peer.socket.sendall(self.connect_bytes())
            self.connected(peer)
            peer.send('SUBSCRIBE', {'destination': channel, 'id': sub_id,
                                    'receipt': 'joined-' + sub_id})
            self.receipt(peer, 'joined-' + sub_id)
        body = 'بداية\n' + ('تقرير: مدينة باقة الغربية\n\n' * 1000) + 'النهاية'
        payload = frame('SEND', {'destination': channel, 'receipt': 'large-sent'}, body)
        self.assertGreater(len(payload), 8192)
        # Odd-sized byte chunks can split UTF-8 characters. TCP may regroup them.
        for offset in range(0, len(payload), 257):
            sender.socket.sendall(payload[offset:offset + 257])
        self.message(receiver, channel, '20', body)
        self.message(sender, channel, '10', body)
        self.receipt(sender, 'large-sent')


if __name__ == '__main__':
    unittest.main(verbosity=2)
