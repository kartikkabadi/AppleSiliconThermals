"""Headless integration tests; skip cleanly when Omarchy/Quickshell is absent."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')
AVAILABLE = shutil.which('quickshell') and (SHELL / 'Ui/PopupCard.qml').exists()


@unittest.skipUnless(AVAILABLE, 'requires installed Omarchy UI modules and Quickshell')
class WidgetIntegrationTests(unittest.TestCase):
    def run_widget(self, script, delayed_helper=False):
        with tempfile.TemporaryDirectory(prefix='thermals-qml-') as temporary:
            root = Path(temporary)
            plugin = root / 'Plugin'
            plugin.mkdir()
            for source in [*REPO.glob('*.qml'), REPO / 'Telemetry.js']:
                shutil.copy2(source, plugin / source.name)
            shutil.copytree(REPO / 'i18n', plugin / 'i18n')
            for name in ('Ui', 'Commons'):
                (root / name).symlink_to(SHELL / name, target_is_directory=True)
            shutil.copy2(REPO / 'tests/qml' / script, root / 'shell.qml')
            helper = plugin / 'helper.sh'
            if not delayed_helper:
                shutil.copy2(REPO / 'tests/qml/helper.py', helper)
                helper.chmod(0o755)
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            with subprocess.Popen(['quickshell', '-p', str(root / 'shell.qml'), '--no-color'],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, env=environment) as process:
                if delayed_helper:
                    time.sleep(5.6)
                    shutil.copy2(REPO / 'tests/qml/helper.py', helper)
                    helper.chmod(0o755)
                try:
                    output, _ = process.communicate(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    output, _ = process.communicate()
                    self.fail('QML test timed out:\n' + output)
            self.assertIn('WIDGET TEST PASSED', output, output)
            self.assertNotIn('ASSERT FAILED', output, output)
            self.assertNotIn('Unable to assign', output, output)
            self.assertNotIn('Failed to load configuration', output, output)
            return (plugin / 'actions.log').read_text() if (plugin / 'actions.log').exists() else ''

    def test_telemetry_command_queue_and_saved_intent(self):
        actions = self.run_widget('smoke.qml').splitlines()
        self.assertEqual(actions[:2], ['set-fan 1 4000', 'set auto'])
        self.assertEqual(actions.count('set-fan 2 3000'), 0)
        self.assertNotIn('set-fan 2 5000', actions)
        self.assertEqual(actions[2:5], ['set-fan 1 4000', 'set-fan 1 4500', 'set-fan 2 3500'])
        self.assertIn('set-fan 1 5050', actions)
        self.assertFalse(any('set-fan 64 ' in action for action in actions))

    def test_saved_manual_choice_survives_widget_recreation_without_heartbeat(self):
        actions = self.run_widget('restart.qml').splitlines()
        self.assertEqual(actions, ['set-fan 1 4000', 'set-fan 2 3000'])

    def test_linked_separate_switches_are_durable_and_cancel_other_layout_edits(self):
        actions = self.run_widget('control-modes.qml').splitlines()
        self.assertEqual(actions[:2], ['set 2500', 'set-fan 1 2500'])
        self.assertEqual(actions.count('set 2502'), 1)
        self.assertEqual(actions.count('set-fan 1 2502'), 1)
        self.assertNotIn('set-fan 2 1200', actions)
        self.assertEqual(actions[:actions.index('set auto')].count('set 5000'), 1)

    def test_missing_executable_recovers_after_install(self):
        self.run_widget('recovery.qml', delayed_helper=True)

    def test_sensor_refresh_does_not_recreate_interactive_fan_cards(self):
        self.run_widget('stable-cards.qml')


if __name__ == '__main__':
    unittest.main()
