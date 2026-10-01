"""Concurrent subscriptions must not lose channel members."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
import uuid

from test_connection_lifecycle import Peer


class ConcurrentSubscriptionTests(unittest.TestCase):
    def test_simultaneous_subscribers_all_receive_message(self):
        count = 8

        with ThreadPoolExecutor(max_workers=count) as workers:
            for attempt in range(25):
                peers = []
                channel = "/concurrent-" + uuid.uuid4().hex

                try:
                    for index in range(count):
                        peer = Peer()
                        peers.append(peer)
                        reply = peer.login("subscriber_" + uuid.uuid4().hex)
                        self.assertEqual(reply[0], "CONNECTED")

                    gate = threading.Barrier(count, timeout=5)

                    def subscribe(index):
                        peer = peers[index]
                        gate.wait()
                        peer.send("SUBSCRIBE", {
                            "destination": channel,
                            "id": str(index),
                            "receipt": "joined-" + str(index),
                        })
                        return peer.receive()

                    futures = [
                        workers.submit(subscribe, index)
                        for index in range(count)
                    ]

                    for index, future in enumerate(futures):
                        reply = future.result(timeout=10)
                        self.assertEqual(
                            reply[:2],
                            ("RECEIPT", {"receipt-id": "joined-" + str(index)}),
                            f"Attempt {attempt + 1}, subscriber {index}: {reply!r}",
                        )

                    # All subscription receipts arrived before publishing.
                    body = "Concurrent delivery " + uuid.uuid4().hex
                    peers[0].send("SEND", {"destination": channel}, body)

                    for index, peer in enumerate(peers):
                        try:
                            reply = peer.receive()
                        except (OSError, EOFError) as error:
                            self.fail(
                                f"Attempt {attempt + 1}: subscriber {index} "
                                f"did not receive a complete message: {error}"
                            )

                        self.assertEqual(reply[0], "MESSAGE")
                        self.assertEqual(reply[1].get("destination"), channel)
                        self.assertEqual(reply[1].get("subscription"), str(index))
                        self.assertEqual(reply[2], body)

                finally:
                    for peer in peers:
                        peer.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
