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


class DriftRepairSafetyTests(unittest.TestCase):
    """Exercise watchdog policy independently from sysfs/ownership fixtures."""
    def setUp(self):
        self.now = 100.0
        self.reacquisitions = []
        self.auto_resets = 0
        self.hot = False
        self.repair_duration = 0
        self.requested = [{'index': 1, 'target': 4000}, {'index': 2, 'target': 4500}]
        self.observed = [{'index': 1, 'target': 3000}, {'index': 2, 'target': 3000}]
        self.state = {
            'schema_version': 1, 'mode': 'manual', 'owner_uid': 1000,
            'expires_at': 112.0, 'boot_id': 'fixture-boot', 'generation': 'a' * 32,
            'targets': copy.deepcopy(self.requested), 'repairs': [],
            'inhibited': False, 'error': None,
        }
        self.hardware = mock.Mock()
        self.hardware.check_temperatures.side_effect = self.check_temperatures
        self.hardware.observed_targets.side_effect = lambda: copy.deepcopy(self.observed)
        # Save references before replacing Hardware with a factory.
        self.matches = broker.Hardware.matches
        self.diagnostic = broker.Hardware.target_diagnostic
        self.hardware.matches.side_effect = lambda requested, observed: self.matches(None, requested, observed)
        self.hardware.target_diagnostic.side_effect = self.diagnostic
        self.hardware.reacquire.side_effect = self.reacquire
        self.hardware.automatic.side_effect = self.automatic
        for name, value in (
            ('clock', lambda: self.now), ('boot_id', lambda: 'fixture-boot'),
            ('locked', contextlib.nullcontext), ('Hardware', lambda: self.hardware),
            ('load_state', lambda: copy.deepcopy(self.state)),
            ('save', self.save), ('atomic_json', lambda *_args: None),
        ):
            patcher = mock.patch.object(broker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, state):
        self.state = copy.deepcopy(state)

    def check_temperatures(self):
        if self.hot:
            raise RuntimeError('Temperature invalid or at/above 80 C')

    def reacquire(self, targets):
        self.reacquisitions.append(copy.deepcopy(targets))
        self.observed = copy.deepcopy(targets)
        self.now += self.repair_duration

    def automatic(self):
        self.auto_resets += 1

    def drift(self):
        self.observed[0]['target'] = 3000

    def test_repair_preserves_uid_generation_expiry_and_requested_fans(self):
        before = copy.deepcopy(self.state)
        broker.watchdog_tick()
        self.assertEqual(self.state['mode'], 'manual')
        for field in ('owner_uid', 'generation', 'expires_at', 'targets', 'boot_id'):
            self.assertEqual(self.state[field], before[field], field)
        self.assertEqual(self.reacquisitions, [self.requested])
        self.assertEqual(self.state['repairs'], [100.0])
        self.assertEqual(self.auto_resets, 0)

    def test_expired_or_hot_lease_is_released_without_attempting_repair(self):
        for expiry, hot in ((99, False), (112, True)):
            with self.subTest(expiry=expiry, hot=hot):
                self.state.update(mode='manual', expires_at=expiry, repairs=[])
                self.hot = hot
                self.reacquisitions.clear()
                broker.watchdog_tick()
                self.assertEqual(self.state['mode'], 'auto')
                self.assertEqual(self.reacquisitions, [])

    def test_third_drift_in_window_releases_instead_of_fighting_indefinitely(self):
        for _ in range(2):
            broker.watchdog_tick()
            self.now += 1
            self.drift()
        self.assertEqual(len(self.reacquisitions), 2)
        broker.watchdog_tick()
        self.assertEqual(len(self.reacquisitions), 2)
        self.assertEqual(self.state['mode'], 'auto')
        self.assertIn('repeatedly overridden', self.state['error'])
        self.assertIn('requested', self.state['error'])
        self.assertIn('observed', self.state['error'])

    def test_sliding_window_retains_recent_repair_budget(self):
        self.state['expires_at'] = 1000
        self.state['repairs'] = [70.0, 99.0]
        broker.watchdog_tick()
        self.assertEqual(self.state['repairs'], [99.0, 100.0])
        self.now = 101
        self.drift()
        broker.watchdog_tick()
        self.assertEqual(self.state['mode'], 'auto')
        self.assertEqual(len(self.reacquisitions), 1)

    def test_repair_crossing_lease_deadline_is_not_published_manual(self):
        self.repair_duration = 13
        broker.watchdog_tick()
        self.assertEqual(self.state['mode'], 'auto')
        self.assertIn('expired', self.state['error'])
        self.assertEqual(self.auto_resets, 1)

    def test_heat_appearing_during_repair_releases_before_publishing_manual(self):
        original = self.reacquire
        def heats_during_repair(targets):
            original(targets)
            self.hot = True
        self.hardware.reacquire.side_effect = heats_during_repair
        broker.watchdog_tick()
        self.assertEqual(self.state['mode'], 'auto')
        self.assertIn('80 C', self.state['error'])
        self.assertEqual(self.auto_resets, 1)

    def test_failed_reacquisition_releases_instead_of_republishing_manual(self):
        self.hardware.reacquire.side_effect = RuntimeError('Manual target did not hold')
        broker.watchdog_tick()
        self.assertEqual(self.state['mode'], 'auto')
        self.assertIn('did not hold', self.state['error'])


if __name__ == '__main__':
    unittest.main()
