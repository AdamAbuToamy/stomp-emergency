import socket
import unittest
import uuid


class Client:
    def __init__(self):
        self.socket = socket.create_connection(("127.0.0.1", 7777), timeout=3)
        self.buffer = b""

    def send(self, frame):
        self.socket.sendall((frame + "\0").encode("utf-8"))

    def receive(self):
        while b"\0" not in self.buffer:
            chunk = self.socket.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed before a complete frame")
            self.buffer += chunk

        frame, self.buffer = self.buffer.split(b"\0", 1)
        return frame.decode("utf-8")

    def close(self):
        self.socket.close()


class DeliveryTests(unittest.TestCase):
    def test_message_reaches_subscriber(self):
        sender = Client()
        self.addCleanup(sender.close)

        receiver = Client()
        self.addCleanup(receiver.close)

        channel = "/test-" + uuid.uuid4().hex

        for client, subscription_id in [(sender, "10"), (receiver, "20")]:
            username = "user_" + uuid.uuid4().hex

            client.send(
                "CONNECT\n"
                "accept-version:1.2\n"
                "host:stomp.cs.bgu.ac.il\n"
                f"login:{username}\n"
                "passcode:demo123\n\n"
            )
            self.assertEqual(client.receive(), "CONNECTED\nversion:1.2\n\n")

            client.send(
                "SUBSCRIBE\n"
                f"destination:{channel}\n"
                f"id:{subscription_id}\n"
                f"receipt:joined-{subscription_id}\n\n"
            )
            self.assertEqual(
                client.receive(),
                f"RECEIPT\nreceipt-id:joined-{subscription_id}\n\n"
            )

        sender.send(f"SEND\ndestination:{channel}\n\nHello from Python!")

        message = receiver.receive()
        print("\nReceived:", repr(message))

        header_text, body = message.split("\n\n", 1)
        lines = header_text.split("\n")
        headers = dict(line.split(":", 1) for line in lines[1:])

        self.assertEqual(lines[0], "MESSAGE")
        self.assertEqual(body, "Hello from Python!")
        self.assertEqual(headers["destination"], channel)
        self.assertEqual(headers["subscription"], "20")


if __name__ == "__main__":
    unittest.main(verbosity=2)
