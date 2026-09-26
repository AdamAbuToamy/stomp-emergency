"""Input validation before login; no Java server is needed."""
from pathlib import Path
import os
import subprocess
import unittest


class ClientCommandTests(unittest.TestCase):
    def run_client(self, commands):
        root = Path(__file__).resolve().parents[1]
        binary = Path(os.environ.get(
            'STOMP_CLIENT_BIN', str(root / 'client/bin/StompEMIClient')
        )).resolve()
        self.assertTrue(binary.is_file(), f'Build the client first: {binary}')
        try:
            result = subprocess.run(
                [str(binary)], input=commands, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(root / 'client'), timeout=3, check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail('Client did not exit after input ended; the test stopped it.')
        self.assertEqual(result.returncode, 0,
                         f'Client crashed or exited with an error ({result.returncode}).\n'
                         f'stdout:\n{result.stdout}\nstderr:\n{result.stderr}')
        return result.stdout + result.stderr

    def test_incomplete_login_prints_usage_without_crashing(self):
        for command in ('login', 'login 127.0.0.1:7777',
                        'login 127.0.0.1:7777 demo_user'):
            with self.subTest(command=command):
                output = self.run_client(command + '\n')
                # The CLI contract: an incomplete login explains its syntax.
                self.assertIn('Usage: login ', output)

    def test_unknown_command_reports_error_without_crashing(self):
        output = self.run_client('unknown_test_command\n')
        self.assertIn('Unknown command', output)

    def test_blank_lines_are_ignored(self):
        self.run_client('\n   \n\t\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
