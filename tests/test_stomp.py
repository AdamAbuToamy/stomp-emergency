import socket
import unittest
import uuid


class StompTests(unittest.TestCase):
    def test_connect_and_subscribe(self):
        username = "test_" + uuid.uuid4().hex

        with socket.create_connection(("127.0.0.1", 7777), timeout=3) as connection:
            buffer = b""

            def read_frame():
                nonlocal buffer

                while b"\0" not in buffer:
                    chunk = connection.recv(4096)
                    if not chunk:
                        raise RuntimeError("Connection closed before a complete frame")
                    buffer += chunk

                frame, buffer = buffer.split(b"\0", 1)
                return frame.decode("utf-8")

            connect = (
                "CONNECT\n"
                "accept-version:1.2\n"
                "host:stomp.cs.bgu.ac.il\n"
                f"login:{username}\n"
                "passcode:demo123\n\n\0"
            )

            connection.sendall(connect.encode("utf-8"))
            self.assertEqual(read_frame(), "CONNECTED\nversion:1.2\n\n")

            subscribe = (
                "SUBSCRIBE\n"
                "destination:/test-alerts\n"
                "id:1\n"
                "receipt:sub-1\n\n\0"
            )

            connection.sendall(subscribe.encode("utf-8"))
            self.assertEqual(read_frame(), "RECEIPT\nreceipt-id:sub-1\n\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
