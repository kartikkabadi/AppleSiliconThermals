"""Fixture-only broker tests. Never request root or access the host fan devices."""
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import time
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'system/apple-silicon-fan-control'
loader = importlib.machinery.SourceFileLoader('fan_broker', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
broker = importlib.util.module_from_spec(spec)
loader.exec_module(broker)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hw = self.root / 'sys/devices/macsmc/hwmon/hwmon3'
        self.hw.mkdir(parents=True)
        self.runtime = self.root / 'run'
        self.runtime.mkdir()
        (self.root / 'sys/class/hwmon').mkdir(parents=True)
        (self.root / 'sys/class/hwmon/hwmon3').symlink_to(self.hw)
        self.param = self.root / 'sys/module/macsmc_hwmon/parameters/fan_control'
        self.param.parent.mkdir(parents=True)
        self.param.write_text('N\n')
        (self.hw / 'name').write_text('macsmc_hwmon\n')
        for index, maximum in ((1, 5779), (2, 6241)):
            for suffix, value in (('min', 1200), ('max', maximum), ('target', 2400), ('input', 2400)):
                (self.hw / ('fan%d_%s' % (index, suffix))).write_text(str(value) + '\n')
        (self.hw / 'temp1_input').write_text('45000\n')
        self.now = 100.0
        self.writes = []
        self._patch('SYSFS', self.root / 'sys')
        self._patch('RUNTIME', self.runtime)
        self._patch('clock', lambda: self.now)
        self._patch('boot_id', lambda: 'fixture-boot')
        self._patch('secure_runtime', lambda create=False: None)
        self._patch('secure_regular', self.open_fixture)
        self._patch('locked', self.fixture_lock)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(broker.Hardware, 'write', lambda hardware, path, value: self.write_fixture(hardware, path, value)).start()
        mock.patch.object(broker.Hardware, 'enable', lambda hardware: self.param.write_text('1\n')).start()
        self.health()
        state = broker.state_default()
        state["mode"] = "auto"
        broker.save(state)

    def _patch(self, name, value):
        mock.patch.object(broker, name, value).start()

    @contextlib.contextmanager
    def fixture_lock(self):
        yield

    def open_fixture(self, path, writable=False):
        # Explicit fixture-only redirection; production has no test-root argument.
        self.assertTrue(Path(path).resolve().is_relative_to(self.root))
        return os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW)

    def write_fixture(self, hardware, path, value):
        self.assertTrue(path.is_relative_to(self.hw))
        self.writes.append((path.name, value))
        path.write_text(str(value) + '\n')

    def health(self):
        broker.atomic_json(self.runtime / 'watchdog.json', {'boot_id': 'fixture-boot', 'updated_at': self.now})

    def test_manual_clamps_each_hardware_limit(self):
        with mock.patch.dict(os.environ, {'SUDO_UID': '1000'}):
            broker.command('7999')
        self.assertEqual(self.writes, [('fan1_target', 5779), ('fan2_target', 6241)])
        state = broker.status()
        self.assertEqual((state['mode'], state['owner_uid'], state['expires_in']), ('manual', 1000, 12))

    def test_manual_clamps_below_minimum(self):
        broker.command('1000')
        self.assertEqual(self.writes, [('fan1_target', 1200), ('fan2_target', 1200)])

    def test_auto_primes_max_then_zero_for_every_fan(self):
        broker.command('auto')
        self.assertEqual(self.writes, [('fan1_target', 5779), ('fan1_target', 0), ('fan2_target', 6241), ('fan2_target', 0)])
        self.assertEqual(broker.status()['mode'], 'auto')

    def test_failure_on_one_reset_still_attempts_other_fans(self):
        original = self.write_fixture
        def failing(hardware, path, value):
            if path.name == 'fan1_target' and value == 5779:
                raise OSError('fixture I/O failure')
            original(hardware, path, value)
        with mock.patch.object(broker.Hardware, 'write', failing):
            with self.assertRaisesRegex(RuntimeError, 'Could not restore'):
                broker.command('auto')
        self.assertIn(('fan1_target', 0), self.writes)
        self.assertIn(('fan2_target', 0), self.writes)
        self.assertEqual(broker.status()['mode'], 'unknown')

    def test_failed_partial_manual_request_recovers_every_fan(self):
        original = self.write_fixture
        def failing(hardware, path, value):
            if path.name == 'fan2_target' and value == 4000:
                raise OSError('fixture I/O failure')
            original(hardware, path, value)
        with mock.patch.object(broker.Hardware, 'write', failing):
            with self.assertRaisesRegex(RuntimeError, 'attempted automatic recovery'):
                broker.command('4000')
        self.assertEqual(self.writes[-1], ('fan2_target', 0))
        self.assertIn(('fan1_target', 0), self.writes)
        self.assertEqual(broker.status()['mode'], 'auto')

    def test_state_journal_failure_prevents_hardware_change(self):
        with mock.patch.object(broker, 'save', side_effect=OSError('state disk full')), mock.patch.object(broker.Hardware, 'manual') as manual:
            with self.assertRaises(OSError):
                broker.command('4000')
            manual.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_interrupted_manual_journal_is_recovered_by_watchdog(self):
        broker.save(broker.state_default('Manual fan change in progress'))
        (self.hw / 'fan1_target').write_text('4000')
        broker.watchdog_tick()
        self.assertEqual(broker.status()['mode'], 'auto')
        self.assertEqual(self.writes[-1], ('fan2_target', 0))

    def test_interrupted_auto_is_journaled_unknown_and_retried(self):
        def interrupted(_hardware):
            self.assertEqual(broker.load_state()['mode'], 'unknown')
            raise SystemExit('fixture interruption after prime')
        with mock.patch.object(broker.Hardware, 'automatic', interrupted):
            with self.assertRaises(SystemExit):
                broker.command('auto')
        self.assertEqual(broker.status()['mode'], 'unknown')
        broker.watchdog_tick()
        self.assertEqual(broker.status()['mode'], 'auto')

    def test_auto_journal_failure_does_not_prevent_hardware_release(self):
        with mock.patch.object(broker, 'save', side_effect=OSError('state disk full')), mock.patch.object(broker.Hardware, 'automatic') as automatic, contextlib.redirect_stderr(__import__('io').StringIO()):
            with self.assertRaises(OSError):
                broker.reset()
            automatic.assert_called_once()

    def test_bad_second_fan_limit_causes_no_manual_writes(self):
        (self.hw / 'fan2_max').write_text('bad\n')
        with self.assertRaises(RuntimeError):
            broker.Hardware().manual(4000)
        self.assertEqual(self.writes, [])

    def test_missing_target_refuses_manual(self):
        (self.hw / 'fan2_target').unlink()
        with self.assertRaisesRegex(RuntimeError, 'no controllable target'):
            broker.Hardware().manual(4000)
        self.assertEqual(self.writes, [])

    def test_hot_sensor_refuses_manual(self):
        (self.hw / 'temp1_input').write_text('80000\n')
        with self.assertRaisesRegex(RuntimeError, '80 C'):
            broker.Hardware().manual(4000)
        self.assertEqual(self.writes, [])

    def test_missing_and_invalid_sensor_refuse_manual(self):
        for raw in ('not a number', '-41000', '99999999'):
            (self.hw / 'temp1_input').write_text(raw)
            with self.assertRaises(RuntimeError):
                broker.Hardware().manual(4000)
        (self.hw / 'temp1_input').unlink()
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            broker.Hardware().manual(4000)

    def test_stale_watchdog_refuses_manual(self):
        self.now += 7
        with self.assertRaisesRegex(RuntimeError, 'watchdog is not running'):
            broker.command('4000')
        self.assertFalse(broker.status()['ready'])
        self.assertEqual(self.writes, [])

    def test_heartbeat_requires_owner_and_unexpired_lease(self):
        with mock.patch.dict(os.environ, {'SUDO_UID': '1000'}):
            broker.command('4000')
        with mock.patch.dict(os.environ, {'SUDO_UID': '1001'}):
            with self.assertRaisesRegex(RuntimeError, 'belongs to this user'):
                broker.command('heartbeat', broker.load_state()['generation'])
            with self.assertRaisesRegex(RuntimeError, 'Another user'):
                broker.command('4500')
        self.now += 3
        self.health()
        with mock.patch.dict(os.environ, {'SUDO_UID': '1000'}):
            broker.command('heartbeat', broker.load_state()['generation'])
        self.assertEqual(broker.load_state()['expires_at'], 115)
        self.now = 116
        self.health()
        self.assertEqual(broker.status()['mode'], 'unknown')
        with mock.patch.dict(os.environ, {'SUDO_UID': '1000'}):
            with self.assertRaisesRegex(RuntimeError, 'No active manual lease'):
                broker.command('heartbeat', broker.load_state()['generation'])

    def test_boot_mismatch_cannot_extend_lease(self):
        broker.command('4000')
        with mock.patch.object(broker, 'boot_id', return_value='different-boot'):
            self.assertEqual(broker.load_state()['mode'], 'unknown')
            self.assertFalse(broker.watchdog_ready())

    def test_firmware_override_detection(self):
        broker.command('4000')
        hardware = broker.Hardware()
        targets = broker.load_state()['targets']
        self.assertTrue(hardware.matches(targets))
        (self.hw / 'fan1_target').write_text('5779\n')
        self.assertFalse(hardware.matches(targets))

    def test_register_symlink_escape_refused(self):
        path = self.hw / 'fan1_target'
        path.unlink()
        path.symlink_to(self.param)
        with self.assertRaisesRegex(RuntimeError, 'escapes'):
            broker.Hardware()

    def test_missing_hardware(self):
        (self.hw / 'name').write_text('unrelated\n')
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            broker.Hardware()

    def test_ambiguous_hardware(self):
        second = self.root / 'sys/devices/other'
        second.mkdir()
        (second / 'name').write_text('macsmc_hwmon\n')
        (self.root / 'sys/class/hwmon/hwmon4').symlink_to(second)
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            broker.Hardware()

    def test_malformed_json_state_becomes_unknown(self):
        (self.runtime / 'state.json').write_text('bad JSON')
        self.assertEqual(broker.status()['mode'], 'unknown')

    def test_watchdog_expires_manual_lease_and_releases_all_fans(self):
        broker.command('4000')
        self.now += 13
        broker.watchdog_tick()
        state = broker.status()
        self.assertEqual(state['mode'], 'auto')
        self.assertIn('expired', state['error'])
        self.assertEqual(self.writes[-1], ('fan2_target', 0))

    def test_watchdog_releases_hot_or_overridden_fans(self):
        broker.command('4000')
        (self.hw / 'temp1_input').write_text('85000')
        broker.watchdog_tick()
        self.assertEqual(broker.status()['mode'], 'auto')
        (self.hw / 'temp1_input').write_text('45000')
        broker.command('4000')
        (self.hw / 'fan1_target').write_text('5779')
        broker.watchdog_tick()
        self.assertIn('another controller', broker.status()['error'])
        self.assertEqual(broker.status()['mode'], 'auto')

    def test_unknown_recovery_state_refuses_numeric_request(self):
        broker.save(broker.state_default('Could not restore automatic cooling'))
        with mock.patch.object(broker.Hardware, 'manual') as manual:
            with self.assertRaisesRegex(RuntimeError, 'has not been established'):
                broker.command('4000')
            manual.assert_not_called()

    def test_sleep_inhibits_reacquisition_until_successful_resume(self):
        broker.command('4000')
        generation = broker.load_state()['generation']
        broker.command('sleep')
        self.assertFalse(broker.status()['ready'])
        for action in ('4000', 'heartbeat'):
            with self.assertRaisesRegex(RuntimeError, 'inhibited'):
                broker.command(action, generation)
        broker.watchdog_tick()
        self.assertTrue(broker.load_state()['inhibited'])
        broker.command('resume')
        self.assertTrue(broker.status()['ready'])
        self.assertEqual(broker.status()['mode'], 'auto')

    def test_failed_resume_keeps_manual_inhibited(self):
        broker.command('sleep')
        with mock.patch.object(broker.Hardware, 'automatic', side_effect=OSError('I/O failure')):
            with self.assertRaises(RuntimeError):
                broker.command('resume')
        self.assertTrue(broker.load_state()['inhibited'])
        self.assertFalse(broker.status()['ready'])

    def test_stale_generation_cannot_renew_new_manual_request(self):
        broker.command('4000')
        old_generation = broker.load_state()['generation']
        broker.command('4500')
        self.now += 3
        self.health()
        with self.assertRaisesRegex(RuntimeError, 'No active manual lease'):
            broker.command('heartbeat', old_generation)
        self.assertEqual(broker.load_state()['expires_at'], 112)

    def test_corrupt_state_fields_become_unknown(self):
        broker.command('4000')
        state = broker.load_state()
        for changes in ({'expires_at': float('nan')}, {'targets': []}, {'owner_uid': '1000'},
                        {'targets': [{'index': 1, 'target': '4000'}]}, {'generation': '../bad'},
                        {'inhibited': 'false'}):
            with self.subTest(changes=changes):
                (self.runtime / 'state.json').write_text(json.dumps({**state, **changes}))
                self.assertEqual(broker.status()['mode'], 'unknown')

    def test_enable_failure_still_attempts_every_automatic_write(self):
        with mock.patch.object(broker.Hardware, 'enable', side_effect=OSError('enable failure')):
            with self.assertRaises(RuntimeError):
                broker.command('auto')
        self.assertEqual(self.writes, [('fan1_target', 5779), ('fan1_target', 0), ('fan2_target', 6241), ('fan2_target', 0)])



class Security(unittest.TestCase):
    def test_invalid_arguments_never_touch_hardware(self):
        for action in ('999', '9999', 'auto;id', '4000 extra', '--sysfs=/tmp', 'heartbeat', 'AUTO', ''):
            with self.subTest(action=action), mock.patch.object(broker.sys, 'argv', ['broker', action]), mock.patch.object(broker, 'Hardware') as hardware:
                with self.assertRaises(RuntimeError):
                    broker.main()
                hardware.assert_not_called()

    def test_extra_argument_rejected(self):
        with mock.patch.object(broker.sys, 'argv', ['broker', 'auto', 'extra']):
            with self.assertRaises(RuntimeError):
                broker.main()

    def test_nonroot_cannot_change_fans(self):
        with mock.patch.object(broker.sys, 'argv', ['broker', 'auto']), mock.patch.object(broker.os, 'geteuid', return_value=1000), mock.patch.object(broker, 'Hardware') as hardware:
            with self.assertRaisesRegex(RuntimeError, 'require'):
                broker.main()
            hardware.assert_not_called()

    def test_unprivileged_status_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(broker, 'RUNTIME', Path(root) / 'missing'):
            self.assertFalse(broker.status()['ready'])
            self.assertFalse((Path(root) / 'missing').exists())

    def test_symlink_state_refused(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'target'
            target.write_text('{}')
            link = Path(root) / 'link'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                broker.secure_regular(link)

    def test_fifo_state_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as root:
            fifo = Path(root) / 'fifo'
            os.mkfifo(fifo)
            started = time.monotonic()
            with self.assertRaises(RuntimeError):
                broker.secure_regular(fifo)
            self.assertLess(time.monotonic() - started, 1)

    def test_fifo_lock_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(broker, 'RUNTIME', Path(root)), mock.patch.object(broker, 'secure_runtime'):
            os.mkfifo(Path(root) / 'lock')
            started = time.monotonic()
            with self.assertRaises(RuntimeError):
                with broker.locked():
                    self.fail('An invalid lock was accepted')
            self.assertLess(time.monotonic() - started, 1)

    def test_runtime_symlink_refused(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'real'
            directory.mkdir()
            link = Path(root) / 'link'
            link.symlink_to(directory, target_is_directory=True)
            with mock.patch.object(broker, 'RUNTIME', link):
                with self.assertRaisesRegex(RuntimeError, 'runtime'):
                    broker.secure_runtime()

    def test_low_level_write_uses_root_owned_canonical_register(self):
        # Run the production write method on a regular fixture attribute. Only
        # ownership metadata is stubbed; open/fchmod/fdopen/close all run for real.
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'fan1_target'
            path.write_text('')
            path.chmod(0o444)
            real_fstat = os.fstat
            def root_metadata(fd):
                actual = real_fstat(fd)
                return types.SimpleNamespace(st_uid=0, st_mode=actual.st_mode)
            with mock.patch.object(broker.os, 'fstat', side_effect=root_metadata):
                hardware = broker.Hardware.__new__(broker.Hardware)
                hardware.write(path, 4000)
            self.assertEqual(path.read_text(), '4000\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    @unittest.skipIf(os.getuid() == 0, 'Requires an unprivileged test runner')
    def test_user_owned_state_refused(self):
        with tempfile.NamedTemporaryFile() as stream:
            with self.assertRaisesRegex(RuntimeError, 'Insecure'):
                broker.secure_regular(Path(stream.name))


if __name__ == '__main__':
    unittest.main()
