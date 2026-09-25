"""Lifecycle regressions to run against BOTH TPC and Reactor."""
import socket
import unittest
import uuid
from test_connection_lifecycle import Peer, VHOST


class TransportLifecycleTests(unittest.TestCase):
    def peer(self):
        peer = Peer()
        self.addCleanup(peer.close)
        return peer

    def test_error_reply_then_server_accepts_another_client(self):
        for _ in range(5):
            rejected = self.peer()
            rejected.send('SUBSCRIBE', {
                'destination': '/rejected-' + uuid.uuid4().hex,
                'id': '1', 'receipt': 'reject-me'})
            self.assertEqual(rejected.receive()[0], 'ERROR')
            self.assertEqual(rejected.buffer, b'')
            self.assertEqual(rejected.socket.recv(1), b'',
                             'Server must close after delivering ERROR')
            healthy = self.peer()
            self.assertEqual(healthy.login('healthy_' + uuid.uuid4().hex)[0], 'CONNECTED')
            healthy.close()

    def test_reply_is_flushed_after_client_finishes_sending(self):
        peer = self.peer()
        peer.send('CONNECT', {
            'accept-version': '1.2',
            'host': VHOST,
            'login': 'halfclose_' + uuid.uuid4().hex,
            'passcode': 'stage01-demo'})
        # TCP half-close: no more input, but client still reads the response.
        peer.socket.shutdown(socket.SHUT_WR)
        self.assertEqual(peer.receive()[0], 'CONNECTED')
        self.assertEqual(peer.buffer, b'')
        self.assertEqual(peer.socket.recv(1), b'')


if __name__ == '__main__':
    unittest.main(verbosity=2)
