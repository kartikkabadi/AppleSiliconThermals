"""Independent OS-boundary checks using temporary files only.

No test invokes sudo, systemctl, or production sysfs writes. Ownership is mocked
only where necessary to exercise descriptor/locking behavior as a normal user.
"""
import importlib.machinery
import importlib.util
import contextlib
import copy
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('broker_review', str(ROOT / 'system/apple-silicon-fan-control'))
spec = importlib.util.spec_from_loader(loader.name, loader)
broker = importlib.util.module_from_spec(spec)
loader.exec_module(broker)


class OperatingSystemBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_register_write_repairs_owner_permission_without_group_or_world_write(self):
        path = self.directory / 'fan1_target'
        path.touch(mode=0o444)
        opened = []

        def fixture_open(target, writable=False):
            self.assertEqual(target, path)
            opened.append(writable)
            return os.open(target, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW)

        hardware = object.__new__(broker.Hardware)
        with mock.patch.object(broker, 'secure_regular', fixture_open):
            hardware.write(path, 4000)
        self.assertEqual(opened, [False, True])
        self.assertEqual(path.read_text(), '4000\n')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_secure_open_rejects_symbolic_link_before_touching_target(self):
        target = self.directory / 'sentinel'
        target.write_text('unchanged')
        alias = self.directory / 'alias'
        alias.symlink_to(target)
        with self.assertRaises(OSError):
            broker.secure_regular(alias, writable=True)
        self.assertEqual(target.read_text(), 'unchanged')

    def test_secure_open_rejects_unprivileged_owned_file(self):
        if os.getuid() == 0:
            self.skipTest('This check needs the normal unprivileged test account')
        path = self.directory / 'state'
        path.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'Insecure root-owned'):
            broker.secure_regular(path)

    def test_secure_open_rejects_fifo_without_blocking(self):
        fifo = self.directory / 'fifo'
        os.mkfifo(fifo)
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            broker.secure_regular(fifo)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_real_flock_serializes_concurrent_commands(self):
        # Actual flock/open/close syscalls operate solely on this scratch lock.
        original_fstat = os.fstat

        def fixture_root_stat(fd):
            info = original_fstat(fd)
            fields = list(info)
            fields[4] = 0
            return os.stat_result(fields)

        barrier = threading.Barrier(8)
        measurements = {'active': 0, 'maximum': 0, 'count': 0}
        failures = []

        def contender():
            try:
                barrier.wait(timeout=2)
                with broker.locked():
                    measurements['active'] += 1
                    measurements['maximum'] = max(measurements['maximum'], measurements['active'])
                    time.sleep(0.01)
                    measurements['count'] += 1
                    measurements['active'] -= 1
            except Exception as error:
                failures.append(error)

        with mock.patch.object(broker, 'RUNTIME', self.directory), \
                mock.patch.object(broker, 'secure_runtime', lambda create=False: None), \
                mock.patch.object(broker.os, 'fstat', fixture_root_stat):
            threads = [threading.Thread(target=contender, daemon=True) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, repr(failures))
        self.assertEqual(measurements['count'], 8)
        self.assertEqual(measurements['maximum'], 1)

    def test_atomic_preference_write_syncs_file_before_rename_and_directory_after(self):
        destination = self.directory / 'preference.json'
        events = []
        real_sync = os.fsync
        real_replace = os.replace
        def sync(fd):
            events.append('directory-sync' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file-sync')
            return real_sync(fd)
        def replace(source, target):
            events.append('rename')
            return real_replace(source, target)
        with mock.patch.object(broker.os, 'fsync', sync), mock.patch.object(broker.os, 'replace', replace):
            broker.atomic_json(destination, {'mode': 'auto'})
        self.assertEqual(events, ['file-sync', 'rename', 'directory-sync'])
        self.assertEqual(destination.read_text().strip(), '{"mode":"auto"}')

    def test_failed_atomic_serialization_preserves_previous_file_and_removes_temp(self):
        destination = self.directory / 'preference.json'
        destination.write_text('{"mode":"auto"}')
        with self.assertRaises(ValueError):
            broker.atomic_json(destination, {'rpm': float('nan')})
        self.assertEqual(destination.read_text(), '{"mode":"auto"}')
        self.assertEqual([path.name for path in self.directory.iterdir()], ['preference.json'])


class PersistentIntentSafetyTests(unittest.TestCase):
    """Real temporary /run and /var/lib data, with hardware operations mocked."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'run'
        self.persistence = self.root / 'var/lib'
        self.runtime.mkdir()
        self.persistence.mkdir(parents=True)
        self.now = 100.0
        self.current_boot = 'boot-A'
        self.temperature = 45000
        self.events = []
        self.observed = [{'index': 1, 'target': 4000}, {'index': 2, 'target': 4000}]
        self.hardware = mock.Mock()
        self.hardware.automatic.side_effect = self.automatic
        self.hardware.manual.side_effect = self.manual
        self.hardware.reacquire.side_effect = self.reacquire
        self.hardware.check_temperatures.side_effect = self.check_temperatures
        self.hardware.observed_targets.side_effect = lambda: copy.deepcopy(self.observed)
        matches = broker.Hardware.matches
        self.hardware.matches.side_effect = lambda requested, observed: matches(None, requested, observed)
        self.hardware.target_diagnostic.side_effect = broker.Hardware.target_diagnostic
        for name, value in (
            ('RUNTIME', self.runtime), ('PERSISTENCE', self.persistence),
            ('clock', lambda: self.now), ('boot_id', lambda: self.current_boot),
            ('locked', contextlib.nullcontext), ('Hardware', lambda: self.hardware),
            ('secure_runtime', lambda create=False: None),
            ('secure_persistence', lambda create=False: None),
            ('secure_regular', self.fixture_open),
        ):
            patcher = mock.patch.object(broker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.preference = {'schema_version': 1, 'mode': 'manual', 'rpm': 4000,
                           'owner_uid': 1000, 'generation': 'a' * 32}
        broker.save_preference(self.preference)
        state = broker.state_default()
        state.update(mode='manual', owner_uid=1000, generation='a' * 32,
                     requested_rpm=4000, targets=copy.deepcopy(self.observed))
        broker.save(state)
        broker.atomic_json(self.runtime / 'watchdog.json', {'boot_id': self.current_boot, 'updated_at': self.now})

    def fixture_open(self, path, writable=False):
        self.assertTrue(Path(path).resolve().is_relative_to(self.root))
        return os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK)

    def automatic(self):
        saved, _ = broker.load_preference()
        self.events.append(('auto', saved['mode']))

    def manual(self, rpm):
        self.check_temperatures()
        self.observed = [{'index': 1, 'target': min(5779, max(1200, rpm))},
                         {'index': 2, 'target': min(6241, max(1200, rpm))}]
        self.events.append(('manual', rpm))
        return copy.deepcopy(self.observed)

    def reacquire(self, targets):
        self.events.append(('repair', copy.deepcopy(targets)))
        self.observed = copy.deepcopy(targets)

    def check_temperatures(self, limit=80000):
        if self.temperature >= limit:
            raise broker.ThermalFault('Temperature at/above limit')

    def profile_bytes(self):
        return (self.persistence / 'preference.json').read_bytes()

    def test_fresh_boot_empty_runtime_restores_saved_manual_without_ui(self):
        before = self.profile_bytes()
        for path in self.runtime.iterdir():
            path.unlink()
        self.now = 0
        self.current_boot = 'boot-B'
        broker.reset()  # Production watchdog startup establishes Auto first.
        broker.watchdog_tick()
        state = broker.load_state()
        self.assertEqual(state['mode'], 'manual')
        self.assertEqual(state['requested_rpm'], 4000)
        self.assertEqual(state['owner_uid'], 1000)
        self.assertEqual(state['boot_id'], 'boot-B')
        self.assertEqual(self.events[:2], [('auto', 'manual'), ('manual', 4000)])
        self.assertEqual(self.profile_bytes(), before)

    def test_manual_setting_survives_hours_without_any_heartbeat(self):
        before = self.profile_bytes()
        self.now += 7200
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.events, [])
        self.assertEqual(self.profile_bytes(), before)

    def test_internal_release_preserves_intent_and_next_tick_restores_it(self):
        before = self.profile_bytes()
        broker.command('release')
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertEqual(self.profile_bytes(), before)
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_explicit_auto_is_durable_before_hardware_release(self):
        broker.command('auto')
        self.assertEqual(self.events[0], ('auto', 'auto'))
        saved, error = broker.load_preference()
        self.assertIsNone(error)
        self.assertEqual(saved['mode'], 'auto')
        broker.watchdog_tick()
        self.assertFalse(any(event[0] == 'manual' for event in self.events))

    def test_failed_auto_storage_does_not_reactivate_old_manual_on_next_tick_or_restart(self):
        before = self.profile_bytes()
        with mock.patch.object(broker, 'save_preference', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'Auto could not be saved'):
                broker.command('auto')
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertEqual(self.profile_bytes(), before)
        broker.watchdog_tick()
        self.now += 3600
        broker.reset()  # Same-boot watchdog restart must retain the safety block.
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertFalse(any(event[0] == 'manual' for event in self.events))
        broker.command('auto')  # A successful explicit choice clears the fault.
        broker.watchdog_tick()
        self.assertEqual(broker.load_preference()[0]['mode'], 'auto')

    def test_failed_new_manual_save_cannot_clear_a_previous_failed_auto_restore_block(self):
        with mock.patch.object(broker, 'save_preference', side_effect=OSError('disk full')):
            with self.assertRaises(RuntimeError):
                broker.command('auto')
            with mock.patch.object(broker, 'owner_uid', return_value=1000):
                with self.assertRaises(RuntimeError):
                    broker.command('3500')
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertEqual([event for event in self.events if event[0] == 'manual'], [('manual', 3500)])
        self.assertEqual(broker.load_preference()[0]['rpm'], 4000)

    def test_stop_restart_release_does_not_erase_saved_manual(self):
        before = self.profile_bytes()
        broker.reset()  # finally/ExecStopPost release
        broker.reset()  # daemon startup
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_corrupt_preference_fails_auto_without_destroying_evidence(self):
        path = self.persistence / 'preference.json'
        path.write_text('{bad json')
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertIn('invalid', broker.load_state()['error'])
        self.assertEqual(path.read_text(), '{bad json')
        self.assertFalse(any(event[0] == 'manual' for event in self.events))

    def test_corrupt_preference_and_hardware_fault_respect_retry_cooldown(self):
        (self.persistence / 'preference.json').write_text('{bad json')
        self.hardware.automatic.side_effect = OSError('hardware offline')
        broker.watchdog_tick()
        self.assertEqual(self.hardware.automatic.call_count, 1)
        self.now += 1
        broker.watchdog_tick()
        self.assertEqual(self.hardware.automatic.call_count, 1)
        self.now += broker.RETRY_SECONDS + 1
        broker.watchdog_tick()
        self.assertEqual(self.hardware.automatic.call_count, 2)

    def test_preference_symlink_cannot_be_followed_or_overwritten(self):
        path = self.persistence / 'preference.json'
        path.unlink()
        sentinel = self.root / 'sentinel'
        sentinel.write_text('unchanged')
        path.symlink_to(sentinel)
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertIn('invalid', broker.load_state()['error'])
        with self.assertRaises(OSError):
            broker.save_preference(self.preference)
        self.assertTrue(path.is_symlink())
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_hot_pause_retains_intent_until_cooldown_and_hysteresis_satisfied(self):
        before = self.profile_bytes()
        self.temperature = 85000
        broker.watchdog_tick()
        state = broker.load_state()
        self.assertEqual(state['mode'], 'auto')
        self.assertTrue(state['thermal_paused'])
        self.temperature = 74000
        self.now += broker.RETRY_SECONDS - 1
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.temperature = 76000
        self.now += 2
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.temperature = 74000
        self.now += broker.RETRY_SECONDS + 1
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_sleep_blocks_restoration_until_resume_preserving_saved_preference(self):
        before = self.profile_bytes()
        broker.command('sleep')
        broker.watchdog_tick()
        self.assertTrue(broker.load_state()['inhibited'])
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertFalse(any(event[0] == 'manual' for event in self.events))
        broker.command('resume')
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_failed_resume_recovers_when_hardware_returns_without_ui(self):
        before = self.profile_bytes()
        broker.command('sleep')
        with mock.patch.object(self.hardware, 'automatic', side_effect=OSError('hardware offline')):
            with self.assertRaises(RuntimeError):
                broker.command('resume')
        self.assertFalse(broker.load_state()['inhibited'])
        self.assertEqual(broker.load_state()['mode'], 'unknown')
        broker.watchdog_tick()
        self.assertFalse(any(event[0] == 'manual' for event in self.events))
        self.now += broker.RETRY_SECONDS + 1
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_third_drift_pauses_then_retries_saved_intent_after_cooldown(self):
        before = self.profile_bytes()
        for _ in range(3):
            self.observed[0]['target'] = 3000
            broker.watchdog_tick()
            self.now += 1
        state = broker.load_state()
        self.assertEqual(state['mode'], 'auto')
        self.assertEqual(sum(event[0] == 'repair' for event in self.events), 2)
        self.assertGreater(state['retry_at'], self.now)
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.now = state['retry_at'] + 1
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual(self.profile_bytes(), before)

    def test_repair_keeps_durable_owner_generation_and_target_intent(self):
        before = self.profile_bytes()
        self.observed[0]['target'] = 3000
        broker.watchdog_tick()
        state = broker.load_state()
        self.assertEqual(state['mode'], 'manual')
        self.assertEqual(state['owner_uid'], 1000)
        self.assertEqual(state['generation'], 'a' * 32)
        self.assertEqual(state['requested_rpm'], 4000)
        self.assertEqual(self.profile_bytes(), before)


if __name__ == '__main__':
    unittest.main()
