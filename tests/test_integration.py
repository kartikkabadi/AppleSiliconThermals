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
PRODUCTION_HARDWARE = broker.Hardware


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
        self.hardware.planned_targets.side_effect = self.planned_targets
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
                     requested_rpm=4000, targets=copy.deepcopy(self.observed),
                     control_mode='shared', requested_fans=[])
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

    def planned_targets(self, rpm=None, fans=None):
        requested = {item['index']: item['rpm'] for item in fans} if fans is not None else {1: rpm, 2: rpm}
        return [{'index': index, 'target': min(maximum, max(1200, requested[index]))}
                for index, maximum in ((1, 5779), (2, 6241))]

    def reacquire(self, targets):
        self.events.append(('repair', copy.deepcopy(targets)))
        self.observed = copy.deepcopy(targets)

    def check_temperatures(self, limit=80000):
        if self.temperature >= limit:
            raise broker.ThermalFault('Temperature at/above limit')

    def profile_bytes(self):
        return (self.persistence / 'preference.json').read_bytes()

    def use_real_fixture_hardware(self):
        """Keep real planning/readback logic, redirect only physical writes."""
        self.hw = self.root / 'sys/devices/macsmc/hwmon/hwmon3'
        self.hw.mkdir(parents=True)
        links = self.root / 'sys/class/hwmon'
        links.mkdir(parents=True)
        (links / 'hwmon3').symlink_to(self.hw)
        parameter = self.root / 'sys/module/macsmc_hwmon/parameters/fan_control'
        parameter.parent.mkdir(parents=True)
        parameter.write_text('Y\n')
        (self.hw / 'name').write_text('macsmc_hwmon\n')
        (self.hw / 'temp1_input').write_text('45000\n')
        for index, maximum in ((1, 5779), (2, 6241)):
            for suffix, value in (('min', 1200), ('max', maximum), ('target', 4000), ('input', 4000)):
                (self.hw / f'fan{index}_{suffix}').write_text(str(value))
        self.real_writes = []
        def fixture_write(hardware, path, value):
            self.assertTrue(path.resolve().is_relative_to(self.hw))
            self.real_writes.append((path.name, value))
            path.write_text(str(value))
        for name, value in (('SYSFS', self.root / 'sys'), ('Hardware', PRODUCTION_HARDWARE)):
            patcher = mock.patch.object(broker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(PRODUCTION_HARDWARE, 'write', fixture_write)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(broker, 'time', mock.Mock(sleep=lambda _seconds: None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def individual_preference(self, first=1600, second=5000):
        return {'schema_version': 2, 'mode': 'manual', 'control_mode': 'individual',
                'rpm': None, 'fans': [{'index': 1, 'rpm': first}, {'index': 2, 'rpm': second}],
                'owner_uid': 1000, 'generation': 'b' * 32}

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

    def test_fresh_boot_restores_unequal_individual_targets_by_index(self):
        self.use_real_fixture_hardware()
        preference = self.individual_preference()
        preference['fans'].reverse()  # Persisted map order is not channel identity.
        broker.save_preference(preference)
        before = self.profile_bytes()
        for path in self.runtime.iterdir():
            path.unlink()
        self.current_boot = 'boot-B'
        self.now = 0
        broker.reset()
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'manual')
        self.assertEqual((self.hw / 'fan1_target').read_text(), '1600')
        self.assertEqual((self.hw / 'fan2_target').read_text(), '5000')
        self.assertEqual(self.profile_bytes(), before)

    def test_two_rapid_independent_commands_preserve_both_updates(self):
        self.use_real_fixture_hardware()
        mutex = threading.Lock()
        barrier = threading.Barrier(2)
        failures = []
        original_load = broker.load_preference
        def delayed_load():
            value = original_load()
            time.sleep(0.01)  # Exposes lost-update bugs if read leaves the lock.
            return value
        def edit(index, rpm):
            try:
                barrier.wait(timeout=2)
                broker.command('fan', fan_index=index, fan_rpm=rpm)
            except Exception as error:
                failures.append(error)
        with mock.patch.object(broker, 'locked', lambda: mutex), \
                mock.patch.object(broker, 'owner_uid', return_value=1000), \
                mock.patch.object(broker, 'load_preference', delayed_load):
            threads = [threading.Thread(target=edit, args=(1, 1600), daemon=True),
                       threading.Thread(target=edit, args=(2, 5000), daemon=True)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, repr(failures))
        preference, error = broker.load_preference()
        self.assertIsNone(error)
        self.assertEqual(preference['fans'], [{'index': 1, 'rpm': 1600}, {'index': 2, 'rpm': 5000}])
        self.assertEqual((self.hw / 'fan1_target').read_text(), '1600')
        self.assertEqual((self.hw / 'fan2_target').read_text(), '5000')

    def test_editing_one_healthy_manual_fan_does_not_write_the_other(self):
        self.use_real_fixture_hardware()
        with mock.patch.object(broker, 'owner_uid', return_value=1000):
            broker.command('fan', fan_index=1, fan_rpm=1600)
        self.assertEqual(broker.load_preference()[0]['fans'], [{'index': 1, 'rpm': 1600}, {'index': 2, 'rpm': 4000}])
        self.assertFalse(any(name == 'fan2_target' for name, _value in self.real_writes))

    def test_changed_hardware_bounds_clamp_actual_targets_without_rewriting_desired_map(self):
        self.use_real_fixture_hardware()
        broker.save_preference(self.individual_preference(first=6241, second=6500))
        before = self.profile_bytes()
        (self.hw / 'fan2_max').write_text('5000')
        broker.reset()
        broker.watchdog_tick()
        self.assertEqual((self.hw / 'fan1_target').read_text(), '5779')
        self.assertEqual((self.hw / 'fan2_target').read_text(), '5000')
        self.assertEqual(self.profile_bytes(), before)

    def test_live_hardware_limit_drop_cannot_keep_a_target_above_the_new_maximum(self):
        self.use_real_fixture_hardware()
        broker.apply_manual(self.individual_preference(), persist=True)
        before = self.profile_bytes()
        (self.hw / 'fan2_max').write_text('4000')
        broker.watchdog_tick()
        self.assertLessEqual(int((self.hw / 'fan2_target').read_text()), 4000)
        self.assertEqual(self.profile_bytes(), before)

    def test_new_or_missing_channel_pauses_individual_map_without_index_reinterpretation(self):
        self.use_real_fixture_hardware()
        broker.save_preference(self.individual_preference())
        before = self.profile_bytes()
        for suffix in ('min', 'max', 'target', 'input'):
            (self.hw / f'fan2_{suffix}').rename(self.hw / f'fan3_{suffix}')
        broker.reset()
        broker.watchdog_tick()
        self.assertEqual(broker.load_state()['mode'], 'auto')
        self.assertEqual((self.hw / 'fan3_target').read_text(), '0')
        self.assertEqual(self.profile_bytes(), before)
        self.assertIn('inventory', broker.load_state()['error'])

    def test_concurrent_shared_and_separate_mode_commands_keep_the_remembered_map(self):
        self.use_real_fixture_hardware()
        with mock.patch.object(broker, 'owner_uid', return_value=1000):
            broker.command('fan', fan_index=1, fan_rpm=1600)
            broker.command('fan', fan_index=2, fan_rpm=5000)
        memory = [{'index': 1, 'rpm': 1600}, {'index': 2, 'rpm': 5000}]
        mutex = threading.Lock()
        barrier = threading.Barrier(2)
        failures = []
        original_load = broker.load_preference
        def delayed_load():
            preference = original_load()
            time.sleep(0.01)
            return preference
        def choose(action):
            try:
                barrier.wait(timeout=2)
                broker.command(action)
            except Exception as error:
                failures.append(error)
        with mock.patch.object(broker, 'locked', lambda: mutex), \
                mock.patch.object(broker, 'owner_uid', return_value=1000), \
                mock.patch.object(broker, 'load_preference', delayed_load):
            threads = [threading.Thread(target=choose, args=(action,), daemon=True)
                       for action in ('4500', 'separate')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, repr(failures))
        preference, error = broker.load_preference()
        self.assertIsNone(error)
        self.assertEqual(preference['separate_fans'], memory)
        if preference['control_mode'] == 'individual':
            self.assertEqual(preference['fans'], memory)
            self.assertEqual((self.hw / 'fan1_target').read_text(), '1600')
            self.assertEqual((self.hw / 'fan2_target').read_text(), '5000')
        else:
            self.assertEqual(preference['control_mode'], 'shared')
            self.assertEqual(preference['rpm'], 4500)
            self.assertEqual((self.hw / 'fan1_target').read_text(), '4500')
            self.assertEqual((self.hw / 'fan2_target').read_text(), '4500')

    def test_schema1_reads_migrate_without_modifying_the_legacy_file(self):
        import json
        path = self.persistence / 'preference.json'
        path.write_text(json.dumps(self.preference))
        before = path.read_bytes()
        preference, error = broker.load_preference()
        self.assertIsNone(error)
        self.assertEqual(preference['schema_version'], 3)
        self.assertEqual(preference['control_mode'], 'shared')
        self.assertEqual(preference['rpm'], 4000)
        self.assertEqual(preference['fans'], [])
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
