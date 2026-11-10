import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('thermal', ROOT / 'thermal.py')
thermal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thermal)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sys = self.root / 'sys'
        self.proc = self.root / 'proc'
        self.hw = self.sys / 'class/hwmon/hwmon7'
        self.hw.mkdir(parents=True)
        self.write(self.hw / 'name', 'macsmc_hwmon')
        self.write(self.proc / 'device-tree/model', 'Apple MacBook Pro\x00')
        self.reader = thermal.Telemetry(self.sys, self.proc)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text))

    def fan(self, index=1, minimum=1200, maximum=5779, target=2300, rpm=2298):
        for key, value in {'min': minimum, 'max': maximum, 'target': target, 'input': rpm, 'label': f'Fan {index}'}.items():
            self.write(self.hw / f'fan{index}_{key}', value)

    def sensor(self, index, label, value):
        self.write(self.hw / f'temp{index}_label', label)
        self.write(self.hw / f'temp{index}_input', value)

    def control(self, mode='auto'):
        return {'mode': mode, 'ready': True, 'permitted': True, 'owner_uid': os.getuid()}

    def test_two_fans_have_independent_limits(self):
        self.fan()
        self.fan(2, maximum=6241, rpm=2500, target=2502)
        result = self.reader.get(self.control())
        self.assertEqual(result['fan_count'], 2)
        self.assertEqual(result['fan_max'], 6241)
        self.assertEqual(result['fans'][0]['max'], 5779)
        self.assertTrue(result['fan_control_enabled'])

    def test_positive_firmware_target_is_not_manual_mode(self):
        self.fan()
        self.assertEqual(self.reader.get()['mode'], 'unknown')
        self.assertFalse(self.reader.get()['manual_mode'])
        self.assertEqual(self.reader.get(self.control())['mode'], 'auto')
        self.assertTrue(self.reader.get(self.control('manual'))['manual_mode'])

    def test_stale_watchdog_cannot_claim_manual(self):
        self.fan()
        result = self.reader.get({**self.control('manual'), 'ready': False})
        self.assertEqual(result['mode'], 'unknown')
        self.assertFalse(result['fan_control_enabled'])

    def test_no_authorization_disables_controls(self):
        self.fan()
        result = self.reader.get({**self.control(), 'permitted': False})
        self.assertFalse(result['control_available'])

    def test_missing_or_invalid_fan_limits_disable_numeric_control(self):
        self.fan()
        for value in ['missing', 'NaN', '-1', '1000000000000000000', '10000']:
            with self.subTest(value=value):
                self.write(self.hw / 'fan1_max', value)
                result = self.reader.get(self.control())
                self.assertFalse(result['fan_control_enabled'])
                self.assertTrue(result['control_available'])

    def test_missing_fan_reading_is_not_zero(self):
        self.fan(rpm='broken')
        result = self.reader.get()
        self.assertIsNone(result['fan_rpm'])
        self.assertTrue(result['warnings'])

    def test_sparse_sensors_and_subzero_and_zero_temperatures(self):
        self.sensor(2, 'Battery Hotspot', 0)
        self.sensor(8, 'NAND Flash Temperature', -12500)
        result = self.reader.get()
        self.assertEqual(result['sensors']['battery'], 0)
        self.assertEqual(result['sensors']['nand'], -12.5)
        self.assertEqual(result['max_temp'], 0)
        self.assertIsNone(result['sensors']['wifi'])
        self.assertFalse(result['has_fan'])
        self.assertIsNone(result['error'])

    def test_duplicate_sensor_classes_keep_hottest(self):
        self.sensor(1, 'Battery Hotspot', 45000)
        self.sensor(2, 'Battery Sensor', 35000)
        self.assertEqual(self.reader.get()['sensors']['battery'], 45)

    def test_system_power_found_by_label(self):
        self.write(self.hw / 'power1_label', 'AC Input Power')
        self.write(self.hw / 'power1_input', 50000000)
        self.write(self.hw / 'power4_label', 'Total System Power')
        self.write(self.hw / 'power4_input', 12345000)
        self.assertEqual(self.reader.get()['power_watts'], 12.35)

    def test_unknown_power_is_not_assumed_system_power(self):
        self.write(self.hw / 'power1_input', 50000000)
        self.assertIsNone(self.reader.get()['power_watts'])

    def test_model_and_label_json_roundtrip(self):
        model = 'Apple "Mac" \\ test\n<img src="https://example.invalid">'
        self.write(self.proc / 'device-tree/model', model)
        self.fan()
        self.write(self.hw / 'fan1_label', 'Fan "A"\\\n<b>bold</b>')
        result = self.reader.get()
        self.assertEqual(json.loads(json.dumps(result))['device_model'], model)
        self.assertIn('<b>', result['fans'][0]['label'])

    def test_missing_driver_is_error_not_fanless(self):
        self.write(self.hw / 'name', 'nvme')
        result = self.reader.get()
        self.assertEqual(result['error'], 'macsmc_hwmon_missing')
        self.assertIsNone(result['max_temp'])

    def test_non_apple_is_explicit(self):
        self.write(self.hw / 'name', 'nvme')
        self.write(self.proc / 'device-tree/model', 'Generic ARM VM')
        result = self.reader.get()
        self.assertFalse(result['is_apple_silicon'])
        self.assertEqual(result['error'], 'unsupported_hardware')

    def test_compatible_detects_apple_without_model(self):
        (self.proc / 'device-tree/model').unlink()
        self.write(self.hw / 'name', 'nvme')
        self.write(self.proc / 'device-tree/compatible', 'apple,j314\x00apple,t6000\x00')
        self.assertTrue(self.reader.get()['is_apple_silicon'])

    def test_empty_hwmon_is_error(self):
        self.assertEqual(self.reader.get()['error'], 'sensor_read_failed')

    def test_hwmon_renumbering(self):
        self.fan()
        renamed = self.hw.with_name('hwmon29')
        self.hw.rename(renamed)
        self.assertEqual(self.reader.get()['fan_count'], 1)

    def test_excessive_fan_count_is_explicit_error(self):
        for index in range(1, 34):
            self.fan(index)
        self.assertEqual(self.reader.get()['error'], 'unsupported_fan_count')

    def test_oversized_and_injected_numbers_rejected(self):
        for value in ['1; system("touch pwned")', 'NaN', 'inf', '1e6', '9' * 5000]:
            with self.subTest(value=value[:20]):
                self.sensor(1, 'Battery Hotspot', value)
                self.assertIsNone(self.reader.get()['sensors']['battery'])

    def test_mutating_cli_rejects_extra_args_and_shell_payloads(self):
        for argv in [['set', 'auto', 'extra'], ['set', '9999'], ['set', '1200;id'],
                     ['heartbeat', 'extra'], ['--sys-root', '/tmp']]:
            with self.subTest(argv=argv), patch('builtins.print'):
                self.assertEqual(thermal.main(argv), 64)

    def test_control_command_errors_and_invalid_json(self):
        for program in ['print("not json")', 'print("[]")', 'raise SystemExit(2)', 'print("x"*20000)']:
            with self.subTest(program=program):
                self.assertFalse(thermal.command_result(['/usr/bin/python3', '-c', program], 1)['ok'])

    def test_control_command_timeout(self):
        result = thermal.command_result(['/usr/bin/python3', '-c', 'import time;time.sleep(2)'], .05)
        self.assertFalse(result['ok'])
        self.assertIn('timed out', result['error'])

    def test_user_writable_broker_rejected(self):
        path = self.root / 'broker'
        self.write(path, '#!/bin/false')
        path.chmod(0o755)
        self.assertFalse(thermal.trusted_broker(path))


if __name__ == '__main__':
    unittest.main()
