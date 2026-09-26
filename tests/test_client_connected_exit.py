"""Real C++ client + Java server: EOF after confirmed login must exit cleanly.
Start the Java server on 127.0.0.1:7777 before running this test.
"""
from pathlib import Path
import os
import selectors
import subprocess
import time
import unittest
import uuid


class ClientConnectedExitTests(unittest.TestCase):
    def test_eof_after_login_exits_cleanly(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            'STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient')
        )).resolve()
        self.assertTrue(binary.is_file(), f'Build the C++ client first: {binary}')
        process = subprocess.Popen(
            [str(binary)], cwd=str(root / 'client'),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
        )
        output = bytearray()
        try:
            username = 'cpp_eof_' + uuid.uuid4().hex
            process.stdin.write(
                f'login 127.0.0.1:7777 {username} demo123\n'.encode()
            )
            process.stdin.flush()
            deadline = time.monotonic() + 5
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while b'Login successful' not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.fail('Login was not confirmed. Check the Java server on port 7777.\n'
                                  + output.decode(errors='replace'))
                    ready = selector.select(remaining)
                    if not ready:
                        continue
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        self.fail('Client stopped before confirming login.\n'
                                  + output.decode(errors='replace'))
                    output.extend(chunk)
                    if len(output) > 1024 * 1024:
                        self.fail('Unexpectedly large client output during login')
            # communicate closes stdin, delivering EOF after confirmed login.
            try:
                remaining_output, _ = process.communicate(input=b'', timeout=3)
            except subprocess.TimeoutExpired:
                self.fail('Login succeeded, but the client did not exit within 3 seconds '
                          'after EOF. The test will stop it.')
            output.extend(remaining_output)
            self.assertEqual(process.returncode, 0,
                             'Client exited abnormally:\n' + output.decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
