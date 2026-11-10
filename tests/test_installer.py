"""Exercise elevation routing with shell functions; no real elevation occurs."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ElevationTests(unittest.TestCase):
    def function(self, filename):
        text = (ROOT / filename).read_text()
        start = text.index('elevate() {')
        return text[start:text.index('\n}\n', start) + 3]

    def run_route(self, filename, sudo_body):
        script = '\n'.join([
            'set -u',
            'sudo() { ' + sudo_body + '; }',
            'pkexec() { printf "PKEXEC_ARG:%s\\n" "$@"; }',
            self.function(filename),
            'elevate /usr/bin/install -m 755 source /usr/local/libexec/example',
        ])
        return subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True)

    def test_authentication_failure_uses_pkexec_without_unsupported_separator(self):
        for filename in ('setup.sh', 'uninstall.sh'):
            with self.subTest(filename=filename):
                result = self.run_route(filename, 'printf "sudo: a password is required\\n" >&2; return 1')
                self.assertEqual(result.returncode, 0, result.stderr)
                args = [line.removeprefix('PKEXEC_ARG:') for line in result.stdout.splitlines()]
                self.assertEqual(args, ['/usr/bin/install', '-m', '755', 'source', '/usr/local/libexec/example'])

    def test_executed_command_failure_is_not_retried_with_pkexec(self):
        for filename in ('setup.sh', 'uninstall.sh'):
            with self.subTest(filename=filename):
                result = self.run_route(filename, 'printf "install: cannot create destination\\n" >&2; return 42')
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertNotIn('PKEXEC_ARG:', result.stdout)

    def test_successful_sudo_does_not_invoke_pkexec(self):
        for filename in ('setup.sh', 'uninstall.sh'):
            with self.subTest(filename=filename):
                result = self.run_route(filename, 'printf "SUDO_ARG:%s\\n" "$@"; return 0')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('SUDO_ARG:-n', result.stdout)
                self.assertNotIn('PKEXEC_ARG:', result.stdout)


if __name__ == '__main__':
    unittest.main()
