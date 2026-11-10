"""Headless integration tests; skip cleanly when Omarchy/Quickshell is absent."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SHELL = Path('/usr/share/omarchy/shell')
AVAILABLE = shutil.which('quickshell') and (SHELL / 'Ui/PopupCard.qml').exists()


@unittest.skipUnless(AVAILABLE, 'requires installed Omarchy UI modules and Quickshell')
class WidgetIntegrationTests(unittest.TestCase):
    def run_widget(self, script, delayed_helper=False, helper_gap=False, hanging_read=False):
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
            if helper_gap:
                import json
                (plugin / 'state.json').write_text(json.dumps({'mode': 'manual', 'saved_mode': 'manual',
                    'saved_control_mode': 'shared', 'saved_rpm': 3000, 'saved_fans': [], 'saved_linked_rpm': 3000}))
            if hanging_read:
                marker = plugin / 'hang-read'
                marker.touch()
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            with subprocess.Popen(['quickshell', '-p', str(root / 'shell.qml'), '--no-color'],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, env=environment) as process:
                if hanging_read:
                    # Confirm the first child installed its SIGTERM handler;
                    # later reads are healthy while that exact child hangs.
                    started = plugin / 'hang-read-started'
                    deadline = time.monotonic() + 3
                    while not started.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(started.exists(), 'Hanging-reader fixture did not start')
                    marker.unlink()
                if delayed_helper:
                    time.sleep(5.6)
                    shutil.copy2(REPO / 'tests/qml/helper.py', helper)
                    helper.chmod(0o755)
                try:
                    if helper_gap:
                        kill_timer = threading.Timer(12, process.kill)
                        kill_timer.start()
                        collected = []
                        restore_timer = None
                        try:
                            for line in process.stdout:
                                collected.append(line)
                                if 'READY_REMOVE_HELPER' in line:
                                    helper.unlink()
                                elif 'RESTORE_HELPER' in line:
                                    def restore():
                                        shutil.copy2(REPO / 'tests/qml/helper.py', helper)
                                        helper.chmod(0o755)
                                    restore_timer = threading.Timer(.2, restore)
                                    restore_timer.start()
                            process.wait(timeout=1)
                            output = ''.join(collected)
                        finally:
                            kill_timer.cancel()
                            if restore_timer:
                                restore_timer.join(timeout=1)
                    else:
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
        self.assertEqual(actions[:3], ['set-linked', 'set 3000', 'set-separate'])
        before_auto = actions[:actions.index('set auto')]
        self.assertEqual(before_auto.count('set 2502'), 0)
        self.assertGreaterEqual(actions.count('set-linked'), 5)
        self.assertEqual(actions.count('set-fan 1 2502'), 0)
        self.assertGreaterEqual(actions.count('set-separate'), 4)
        self.assertNotIn('set-fan 2 1200', actions)
        self.assertEqual(actions.count('set 5000'), 0)
        self.assertIn('set 4200', before_auto)
        self.assertEqual(actions.count('set-fan 2 3500'), 1)

    def test_missing_executable_recovers_after_install(self):
        self.run_widget('recovery.qml', delayed_helper=True)

    def test_queued_auto_recovers_after_failed_start_and_helper_restoration(self):
        actions = self.run_widget('auto-recovery.qml', helper_gap=True).splitlines()
        self.assertEqual(actions, ['set auto'])

    def test_timed_out_child_cannot_block_or_complete_the_later_auto_request(self):
        actions = self.run_widget('auto-timeout.qml').splitlines()
        self.assertEqual(actions, ['set 4300', 'set auto'])

    def test_timed_out_reader_is_killed_before_fresh_poll(self):
        self.run_widget('read-timeout.qml', hanging_read=True)

    def test_sensor_refresh_does_not_recreate_interactive_fan_cards(self):
        self.run_widget('stable-cards.qml')

    def test_accessibility_semantics_keyboard_and_real_control_actions(self):
        actions = self.run_widget('accessibility.qml').splitlines()
        self.assertEqual(actions, ['set-linked', 'set-separate'])


if __name__ == '__main__':
    unittest.main()
