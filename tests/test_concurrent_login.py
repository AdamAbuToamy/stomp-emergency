"""Concurrent login invariant. A passing run does not prove absence of races."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
import uuid
from test_connection_lifecycle import Peer


class ConcurrentLoginTests(unittest.TestCase):
    def test_only_one_connection_can_claim_the_same_username(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            for attempt in range(25):
                peers = []
                try:
                    peers.append(Peer())
                    peers.append(Peer())
                    name = 'race_' + uuid.uuid4().hex
                    gate = threading.Barrier(2, timeout=5)
                    def login(peer):
                        gate.wait()
                        return peer.login(name)
                    futures = [workers.submit(login, peer) for peer in peers]
                    # Do not close either peer until BOTH replies have arrived.
                    replies = [future.result(timeout=8) for future in futures]
                    commands = [reply[0] for reply in replies]
                    self.assertCountEqual(
                        commands, ['CONNECTED', 'ERROR'],
                        f'Attempt {attempt + 1}: exactly one login must succeed; replies={replies!r}'
                    )
                    winner = peers[commands.index('CONNECTED')]
                    winner.send('SUBSCRIBE', {
                        'destination': '/race-' + uuid.uuid4().hex,
                        'id': '1', 'receipt': 'winner-still-active'})
                    reply = winner.receive()
                    self.assertEqual(reply[:2], ('RECEIPT', {'receipt-id': 'winner-still-active'}),
                                     f'Winning connection lost its session: {reply!r}')
                    winner.send('DISCONNECT', {'receipt': 'bye'})
                    self.assertEqual(winner.receive()[:2], ('RECEIPT', {'receipt-id': 'bye'}))
                finally:
                    for peer in peers:
                        peer.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
