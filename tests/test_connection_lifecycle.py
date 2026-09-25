"""Stage 1: black-box connection tests. Start the Java server before running."""
import os
import socket
import time
import unittest
import uuid

HOST = os.environ.get('STOMP_TEST_HOST', '127.0.0.1')
PORT = int(os.environ.get('STOMP_TEST_PORT', '7777'))
VHOST = os.environ.get('STOMP_TEST_VHOST', 'stomp.cs.bgu.ac.il')
TIMEOUT = 3.0


class Peer:
    def __init__(self):
        self.socket = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
        self.buffer = b''

    def send(self, command, headers=None, body=''):
        fields = ''.join(f'{key}:{value}\n' for key, value in (headers or {}).items())
        self.socket.sendall(f'{command}\n{fields}\n{body}\0'.encode('utf-8'))

    def receive(self):
        deadline = time.monotonic() + TIMEOUT
        while b'\0' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('No complete frame within 3 seconds')
            self.socket.settimeout(remaining)
            chunk = self.socket.recv(4096)
            if not chunk:
                raise EOFError('Server closed the connection before a complete reply')
            self.buffer += chunk
            if len(self.buffer) > 1024 * 1024:
                raise ValueError('Reply exceeds the test reader limit of 1 MiB')
        frame, self.buffer = self.buffer.split(b'\0', 1)
        head, body = frame.decode('utf-8').lstrip('\r\n').split('\n\n', 1)
        lines = head.split('\n')
        return lines[0], dict(line.split(':', 1) for line in lines[1:]), body

    def login(self, name):
        self.send('CONNECT', {'accept-version': '1.2', 'host': VHOST,
                              'login': name, 'passcode': 'stage01-demo'})
        return self.receive()

    def close(self):
        if self.socket.fileno() != -1:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()


class ConnectionLifecycleTests(unittest.TestCase):
    def peer(self):
        peer = Peer()
        self.addCleanup(peer.close)
        return peer

    def name(self):
        return 'lifecycle_' + uuid.uuid4().hex

    def login(self, peer, name):
        reply = peer.login(name)
        self.assertEqual(reply[0], 'CONNECTED', f'Login reply: {reply!r}')
        self.assertEqual(reply[1].get('version'), '1.2')

    def subscribe(self, peer):
        peer.send('SUBSCRIBE', {'destination': '/stage01-' + uuid.uuid4().hex,
                                'id': '20', 'receipt': 'joined'})
        reply = peer.receive()
        self.assertEqual(reply[:2], ('RECEIPT', {'receipt-id': 'joined'}))

    def test_01_valid_login(self):
        self.login(self.peer(), self.name())

    def test_02_subscribe_requires_login(self):
        peer = self.peer()
        peer.send('SUBSCRIBE', {'destination': '/stage01-' + uuid.uuid4().hex,
                                'id': '20', 'receipt': 'unauthenticated'})
        reply = peer.receive()
        self.assertEqual(reply[0], 'ERROR',
                         f'Subscription before login must be rejected; got {reply!r}')

    def test_03_disconnect_without_subscription(self):
        peer = self.peer()
        name = self.name()
        self.login(peer, name)
        peer.send('DISCONNECT', {'receipt': 'bye'})
        reply = peer.receive()
        self.assertEqual(reply[:2], ('RECEIPT', {'receipt-id': 'bye'}),
                         f'Logout without joining a channel must succeed: {reply!r}')
        self.login(self.peer(), name)

    def check_reconnect_after_transport_close(self, subscribe):
        original = self.peer()
        name = self.name()
        self.login(original, name)
        if subscribe:
            self.subscribe(original)
        # Close TCP without sending STOMP DISCONNECT. This simulates EOF,
        # not a power failure or a TCP RST.
        original.close()
        deadline = time.monotonic() + 2.0
        last_reply = None
        while True:
            candidate = self.peer()
            last_reply = candidate.login(name)
            if last_reply[0] == 'CONNECTED':
                return
            candidate.close()
            if last_reply[0] != 'ERROR':
                self.fail(f'Unexpected reconnect reply: {last_reply!r}')
            if time.monotonic() >= deadline:
                self.fail(f'Username was not released within 2 seconds: {last_reply!r}')
            time.sleep(0.05)

    def test_04_reconnect_after_tcp_close_without_subscription(self):
        self.check_reconnect_after_transport_close(subscribe=False)

    def test_05_reconnect_after_tcp_close_with_subscription(self):
        self.check_reconnect_after_transport_close(subscribe=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
