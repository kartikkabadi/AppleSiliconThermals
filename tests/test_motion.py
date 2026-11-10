"""Render the production fan icon to detect RPM-driven animation restarts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')
AVAILABLE = shutil.which('quickshell') and (SHELL / 'Ui/OpticalGlyph.qml').exists()


@unittest.skipUnless(AVAILABLE, 'requires installed Omarchy UI modules and Quickshell')
class MotionTests(unittest.TestCase):
    def test_constant_motion_size_pause_and_upright_warning(self):
        with tempfile.TemporaryDirectory(prefix='thermals-motion-') as temporary:
            root = Path(temporary)
            (root / 'Plugin').mkdir()
            shutil.copy2(REPO / 'FanIcon.qml', root / 'Plugin/FanIcon.qml')
            shutil.copy2(REPO / 'tests/qml/motion.qml', root / 'shell.qml')
            for name in ('Ui', 'Commons'):
                (root / name).symlink_to(SHELL / name, target_is_directory=True)
            result = subprocess.run(['quickshell', '-p', str(root / 'shell.qml'), '--no-color'],
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                                    capture_output=True, text=True, timeout=8)
            output = result.stdout + result.stderr
            self.assertIn('MOTION TEST PASSED', output, output)
            self.assertNotIn('ASSERT FAILED', output, output)
            self.assertNotIn('Unable to assign', output, output)


if __name__ == '__main__':
    unittest.main()
