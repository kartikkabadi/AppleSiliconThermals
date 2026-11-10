"""Independent OS-boundary checks using temporary files only.

No test invokes sudo, systemctl, or production sysfs writes. Ownership is mocked
only where necessary to exercise descriptor/locking behavior as a normal user.
"""
import importlib.machinery
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
