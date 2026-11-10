"""Validate bounded sudo authorization without installing or executing it."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupPolicyTests(unittest.TestCase):
    def policy(self):
        return (ROOT / 'system/apple-silicon-fan-control.sudoers').read_text().replace('@USER@', 'fixture_user')

    def test_exact_separate_action_and_other_valid_actions(self):
        pattern = re.compile('^' + self.policy().split(' ^', 1)[1].strip())
        for action in ('auto', 'linked', 'separate', '1000', '7999', 'fan 1 1200', 'fan 64 7999', 'heartbeat ' + 'a' * 32):
            with self.subTest(action=action):
                self.assertIsNotNone(pattern.fullmatch(action))
        for action in ('linked extra', ' linked', 'linked ', 'linked;id', 'set-linked', 'separate extra', ' separate', 'separate ', 'separate;id', 'separate\nextra', 'fan 65 4000', 'fan 01 4000', '9999', 'status', 'watchdog'):
            with self.subTest(action=action):
                self.assertIsNone(pattern.fullmatch(action))
        self.assertNotIn('ALL ALL=', self.policy())
        self.assertNotIn('@USER@', self.policy())

    @unittest.skipUnless(shutil.which('visudo'), 'visudo is unavailable')
    def test_rendered_single_account_policy_passes_visudo(self):
        with tempfile.TemporaryDirectory(prefix='thermals-policy-') as directory:
            path = Path(directory) / 'policy'
            path.write_text(self.policy())
            result = subprocess.run(['visudo', '-c', '-f', str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
