"""Sequential account/session tests; concurrency is tested separately."""
import unittest
import uuid
from test_connection_lifecycle import Peer, VHOST


class AuthenticationTests(unittest.TestCase):
    def name(self):
        return 'auth_' + uuid.uuid4().hex

    def peer(self):
        peer = Peer()
        self.addCleanup(peer.close)
        return peer

    def login(self, peer, name, password='original-password'):
        peer.send('CONNECT', {'accept-version': '1.2', 'host': VHOST,
                              'login': name, 'passcode': password})
        return peer.receive()

    def assert_closed(self, peer):
        self.assertEqual(peer.buffer, b'', 'Unexpected extra frame before close')
        self.assertEqual(peer.socket.recv(1), b'', 'Expected connection to close')

    def logout(self, peer):
        peer.send('DISCONNECT', {'receipt': 'logout'})
        reply = peer.receive()
        self.assertEqual(reply[0], 'RECEIPT', repr(reply))
        self.assertEqual(reply[1].get('receipt-id'), 'logout')
        self.assert_closed(peer)

    def test_wrong_password_does_not_replace_original_password(self):
        name = self.name()
        original = self.peer()
        self.assertEqual(self.login(original, name)[0], 'CONNECTED')
        self.logout(original)
        wrong = self.peer()
        reply = self.login(wrong, name, 'wrong-password')
        self.assertEqual(reply[0], 'ERROR', repr(reply))
        self.assert_closed(wrong)
        correct = self.peer()
        reply = self.login(correct, name)
        self.assertEqual(reply[0], 'CONNECTED', repr(reply))
        self.logout(correct)

    def test_duplicate_login_does_not_disconnect_original_user(self):
        name = self.name()
        original, duplicate = self.peer(), self.peer()
        self.assertEqual(self.login(original, name)[0], 'CONNECTED')
        reply = self.login(duplicate, name)
        self.assertEqual(reply[0], 'ERROR', repr(reply))
        self.assert_closed(duplicate)
        # Original connection must remain authenticated and usable.
        original.send('SUBSCRIBE', {'destination': '/auth-' + uuid.uuid4().hex,
                                     'id': '1', 'receipt': 'still-connected'})
        reply = original.receive()
        self.assertEqual(reply[0], 'RECEIPT', repr(reply))
        self.assertEqual(reply[1].get('receipt-id'), 'still-connected')
        self.logout(original)
        replacement = self.peer()
        self.assertEqual(self.login(replacement, name)[0], 'CONNECTED')
        self.logout(replacement)

    def test_second_connect_with_same_user_is_rejected(self):
        peer = self.peer()
        name = self.name()
        self.assertEqual(self.login(peer, name)[0], 'CONNECTED')
        reply = self.login(peer, name)
        self.assertEqual(reply[0], 'ERROR', repr(reply))
        self.assert_closed(peer)

    def test_second_connect_cannot_switch_identity(self):
        peer = self.peer()
        self.assertEqual(self.login(peer, self.name())[0], 'CONNECTED')
        reply = self.login(peer, self.name())
        self.assertEqual(reply[0], 'ERROR',
                         f'An authenticated connection cannot log in again: {reply!r}')
        self.assert_closed(peer)


if __name__ == '__main__':
    unittest.main(verbosity=2)
