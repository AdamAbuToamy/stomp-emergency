"""Run the real C++ client without a server and verify EOF shutdown."""
from pathlib import Path
import os
import subprocess
import unittest


class ClientExitTests(unittest.TestCase):
    def test_eof_before_login_exits_cleanly(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            'STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient')
        )).resolve()
        self.assertTrue(binary.is_file(), f'Client binary not found: {binary}; build the client first')
        try:
            result = subprocess.run(
                [str(binary)],
                input='',
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(root / 'client'),
                timeout=3,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail(
                'Client did not exit within 3 seconds after stdin reached EOF '
                'before login. The test stopped the child process.'
            )
        self.assertEqual(
            result.returncode, 0,
            f'Client exited abnormally ({result.returncode}).\n'
            f'stdout:\n{result.stdout}\nstderr:\n{result.stderr}'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
