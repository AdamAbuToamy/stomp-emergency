"""Routing regressions. Run against both server modes with unittest discovery."""
import unittest
import uuid
from test_connection_lifecycle import Peer


class RoutingTests(unittest.TestCase):
    def unique(self, prefix):
        return prefix + uuid.uuid4().hex

    def peer(self):
        peer = Peer()
        self.addCleanup(peer.close)
        reply = peer.login(self.unique('routing_'))
        self.assertEqual(reply[0], 'CONNECTED', repr(reply))
        return peer

    def receipt(self, peer, receipt):
        reply = peer.receive()
        self.assertEqual(reply[0], 'RECEIPT', repr(reply))
        self.assertEqual(reply[1].get('receipt-id'), receipt)

    def subscribe(self, peer, channel, subscription):
        receipt = self.unique('join_')
        peer.send('SUBSCRIBE', {'destination': channel, 'id': subscription,
                                'receipt': receipt})
        self.receipt(peer, receipt)

    def message(self, peer, channel, subscription, body):
        reply = peer.receive()
        self.assertEqual(reply[0], 'MESSAGE', repr(reply))
        self.assertEqual(reply[1].get('destination'), channel)
        self.assertEqual(reply[1].get('subscription'), subscription)
        self.assertTrue(reply[1].get('message-id'))
        self.assertEqual(reply[2], body)

    def publish(self, sender, channel, body):
        # This project requires the sender to subscribe, so it receives a copy.
        receipt = self.unique('sent_')
        sender.send('SEND', {'destination': channel, 'receipt': receipt}, body)
        self.message(sender, channel, '10', body)
        self.receipt(sender, receipt)

    def barrier(self, peer):
        # Called AFTER sender's receipt. A wrongly delivered message would be
        # ahead of this receipt in the recipient's output queue.
        # This checks this completed send, not unlimited future behavior.
        self.subscribe(peer, self.unique('/barrier-'), '999')

    def test_each_recipient_gets_its_own_subscription_id(self):
        channel = self.unique('/fanout-')
        sender, first, second = self.peer(), self.peer(), self.peer()
        self.subscribe(sender, channel, '10')
        self.subscribe(first, channel, '20')
        self.subscribe(second, channel, '30')
        self.publish(sender, channel, 'one message for both')
        self.message(first, channel, '20', 'one message for both')
        self.message(second, channel, '30', 'one message for both')
        self.barrier(first)
        self.barrier(second)

    def test_other_channel_and_unsubscribed_client_receive_nothing(self):
        channel = self.unique('/target-')
        sender, other, idle = self.peer(), self.peer(), self.peer()
        self.subscribe(sender, channel, '10')
        self.subscribe(other, self.unique('/other-'), '20')
        self.publish(sender, channel, 'private to this channel')
        self.barrier(other)
        self.barrier(idle)

    def test_unsubscribe_stops_delivery(self):
        channel = self.unique('/leave-')
        sender, receiver = self.peer(), self.peer()
        self.subscribe(sender, channel, '10')
        self.subscribe(receiver, channel, '20')
        receiver.send('UNSUBSCRIBE', {'id': '20', 'receipt': 'left'})
        self.receipt(receiver, 'left')
        self.publish(sender, channel, 'after leaving')
        self.barrier(receiver)

    def test_rejoin_uses_new_subscription_id(self):
        channel = self.unique('/rejoin-')
        sender, receiver = self.peer(), self.peer()
        self.subscribe(sender, channel, '10')
        self.subscribe(receiver, channel, '20')
        receiver.send('UNSUBSCRIBE', {'id': '20', 'receipt': 'left'})
        self.receipt(receiver, 'left')
        self.subscribe(receiver, channel, '30')
        self.publish(sender, channel, 'after rejoining')
        self.message(receiver, channel, '30', 'after rejoining')
        self.barrier(receiver)

    def test_active_subscription_id_cannot_be_reused(self):
        peer = self.peer()
        self.subscribe(peer, self.unique('/original-'), '20')
        peer.send('SUBSCRIBE', {'destination': self.unique('/duplicate-'),
                                'id': '20', 'receipt': 'duplicate'})
        reply = peer.receive()
        self.assertEqual(reply[0], 'ERROR',
                         f'An active subscription ID must be unique per connection: {reply!r}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
