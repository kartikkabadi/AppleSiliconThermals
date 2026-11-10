#!/usr/bin/python3
"""Read-only SMC telemetry. Fixture paths are injectable in tests, never the CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

BROKER = Path('/usr/local/libexec/apple-silicon-fan-control')
ACTION = re.compile(r'(?:auto|[1-7][0-9]{3})\Z')


def read_text(path: Path) -> str | None:
    try:
        with path.open('rb') as stream:
            value = stream.read(4097)
        if len(value) > 4096:
            return None
        return value.decode('utf-8', errors='replace').replace('\x00', '').strip()
    except (OSError, ValueError):
        return None


def read_number(path: Path, low: int, high: int) -> int | None:
    value = read_text(path)
    if value is None or not re.fullmatch(r'-?[0-9]{1,15}', value):
        return None
    number = int(value)
    return number if low <= number <= high else None


def trusted_broker(path: Path = BROKER) -> bool:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            return False
        if info.st_mode & 0o022 or not os.access(path, os.X_OK):
            return False
        for parent in path.parents:
            info = parent.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                return False
        return True
    except OSError:
        return False


def command_result(command: list[str], timeout: float) -> dict:
    """Bound child execution time and output. Broker output is small and trusted."""
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(command, stdout=output, stderr=output,
                                    timeout=timeout, check=False,
                                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
            output.seek(0)
            raw = output.read(16385)
        if len(raw) > 16384:
            return {'ok': False, 'error': 'Control helper returned too much output.'}
        message = raw.decode('utf-8', errors='replace').strip()
        if result.returncode:
            return {'ok': False, 'error': message[:1024] or 'Control command failed.', 'exit_code': result.returncode}
        try:
            data = json.loads(message)
        except (ValueError, TypeError):
            return {'ok': False, 'error': 'Control helper returned invalid JSON.'}
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'Control helper returned invalid data.'}
        return {'ok': True, 'data': data}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Control helper timed out.'}
    except OSError:
        return {'ok': False, 'error': 'Control helper could not be started.'}


def broker_status() -> dict:
    unavailable = {'mode': 'unknown', 'ready': False, 'permitted': False, 'error': None}
    if not trusted_broker():
        return {**unavailable, 'error': 'Installed control helper has unsafe ownership or permissions.'} if BROKER.exists() else unavailable
    response = command_result([str(BROKER), 'status'], 1.5)
    if not response['ok']:
        return {**unavailable, 'error': response['error']}
    data = response['data']
    mode = data.get('mode')
    ready = data.get('ready') is True
    if data.get('schema_version') != 1 or mode not in ('auto', 'manual', 'unknown'):
        return {**unavailable, 'error': 'Control service protocol is incompatible.'}
    try:
        permitted = subprocess.run(
            ['/usr/bin/sudo', '-n', '-l', str(BROKER), 'heartbeat', '0' * 32],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=1, check=False,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        permitted = False
    error = data.get('error')
    if not ready and not error:
        error = 'Manual-control watchdog is not ready.'
    if ready and not permitted:
        error = 'This user is not authorized for manual control.'
    return {**data, 'mode': mode if ready else 'unknown', 'ready': ready,
            'permitted': permitted, 'error': str(error)[:1024] if error else None}


class Telemetry:
    def __init__(self, sys_root: Path = Path('/sys'), proc_root: Path = Path('/proc')):
        self.sys_root = sys_root
        self.proc_root = proc_root

    def hwmon(self) -> Path | None:
        try:
            for path in sorted((self.sys_root / 'class/hwmon').iterdir()):
                if re.fullmatch(r'hwmon[0-9]+', path.name) and read_text(path / 'name') == 'macsmc_hwmon':
                    return path
        except OSError:
            pass
        return None

    def get(self, control: dict | None = None) -> dict:
        directory = self.hwmon()
        model = (read_text(self.proc_root / 'device-tree/model') or
                 read_text(self.sys_root / 'firmware/devicetree/base/model'))
        compatible = read_text(self.proc_root / 'device-tree/compatible') or ''
        apple = bool(directory or (model and model.startswith('Apple')) or 'apple,' in compatible)
        control = control or {'mode': 'unknown', 'ready': False, 'permitted': False}
        available = control.get('ready') is True and control.get('permitted') is True
        mode = control.get('mode') if control.get('ready') is True else 'unknown'
        if mode not in ('auto', 'manual', 'unknown'):
            mode = 'unknown'
        data = {
            'schema_version': 2, 'timestamp_ms': int(time.time() * 1000),
            'is_apple_silicon': apple, 'device_model': (model or ('Apple Silicon Mac' if apple else 'Non-Apple hardware'))[:256],
            'has_fan': False, 'fan_count': 0, 'fans': [], 'fan_rpm': None,
            'fan_min': None, 'fan_max': None, 'fan_target': None,
            'mode': mode, 'manual_mode': mode == 'manual',
            'control_available': available, 'fan_control_enabled': False,
            'lease_owned': mode == 'manual' and control.get('owner_uid') == os.getuid(),
            'broker_generation': str(control.get('generation') or '')[:128],
            'control_error': control.get('error'),
            'max_temp': None, 'power_watts': None,
            'sensors': dict.fromkeys(('nand', 'battery', 'regulator', 'wifi')),
            'error': None, 'error_message': None, 'warnings': [],
        }
        if not apple:
            data.update(error='unsupported_hardware', error_message='Apple Silicon hardware was not found.')
            return data
        if directory is None:
            data.update(error='macsmc_hwmon_missing', error_message='The macsmc_hwmon driver is unavailable.')
            return data
        try:
            files = list(directory.iterdir())
        except OSError:
            data.update(error='sensor_read_failed', error_message='The hardware sensor directory cannot be read.')
            return data
        indices = sorted({int(m.group(1)) for path in files
                          if (m := re.fullmatch(r'fan([0-9]{1,3})_input', path.name))})
        if len(indices) > 32:
            data.update(error='unsupported_fan_count', error_message='More than 32 fan channels are not supported.')
            return data
        for index in indices:
            stem = directory / f'fan{index}'
            fan = {'index': index, 'label': (read_text(Path(f'{stem}_label')) or f'Fan {index}')[:128]}
            for key, attribute in (('rpm', 'input'), ('min', 'min'), ('max', 'max'), ('target', 'target')):
                fan[key] = read_number(Path(f'{stem}_{attribute}'), 0, 100000)
            fan['limits_valid'] = (fan['min'] is not None and fan['max'] is not None and
                                   0 < fan['min'] <= fan['max'] < 8000)
            if fan['rpm'] is None:
                data['warnings'].append(f'Fan {index} speed is unavailable.')
            if not fan['limits_valid']:
                data['warnings'].append(f'Fan {index} control limits are unavailable or unsupported.')
            data['fans'].append(fan)
        fans = data['fans']
        data.update(has_fan=bool(fans), fan_count=len(fans))
        for key, fan_key, aggregate in (('fan_rpm', 'rpm', max), ('fan_target', 'target', max),
                                        ('fan_min', 'min', min), ('fan_max', 'max', max)):
            values = [f[fan_key] for f in fans if f[fan_key] is not None]
            data[key] = aggregate(values) if values else None
        data['fan_control_enabled'] = bool(available and fans and all(f['limits_valid'] for f in fans))
        for path in sorted(files):
            match = re.fullmatch(r'temp([0-9]{1,3})_label', path.name)
            if not match:
                continue
            label = (read_text(path) or '').lower()
            raw = read_number(directory / f'temp{match.group(1)}_input', -100000, 250000)
            key = next((key for text, key in (('nand', 'nand'), ('battery', 'battery'),
                                             ('regulator', 'regulator'), ('wifi', 'wifi'), ('bt', 'wifi'))
                        if text in label), None)
            if key:
                value = round(raw / 1000, 1) if raw is not None else None
                previous = data['sensors'][key]
                if value is not None and (previous is None or value > previous):
                    data['sensors'][key] = value
                if value is None:
                    data['warnings'].append(f'{key} temperature is unavailable.')
        temperatures = [v for v in data['sensors'].values() if v is not None]
        data['max_temp'] = max(temperatures) if temperatures else None
        for path in sorted(files):
            match = re.fullmatch(r'power([0-9]{1,3})_label', path.name)
            if match and (read_text(path) or '').lower() == 'total system power':
                raw = read_number(directory / f'power{match.group(1)}_input', 0, 10**10)
                data['power_watts'] = round(raw / 1000000, 2) if raw is not None else None
                break
        if not temperatures and not any(f['rpm'] is not None for f in fans) and data['power_watts'] is None:
            data.update(error='sensor_read_failed', error_message='No valid hardware readings are available.')
        return data


def main(argv: list[str]) -> int:
    if not argv or argv == ['get']:
        print(json.dumps(Telemetry().get(broker_status()), ensure_ascii=True, allow_nan=False, separators=(',', ':')))
        return 0
    is_set = len(argv) == 2 and argv[0] == 'set' and ACTION.fullmatch(argv[1])
    is_heartbeat = len(argv) == 2 and argv[0] == 'heartbeat' and re.fullmatch(r'[0-9a-f]{32}', argv[1])
    if is_set or is_heartbeat:
        if not trusted_broker():
            print(json.dumps({'ok': False, 'error': 'The trusted manual-control service is not installed.'}))
            return 1
        arguments = [argv[1]] if is_set else ['heartbeat', argv[1]]
        response = command_result(['/usr/bin/sudo', '-n', str(BROKER), *arguments], 3.5)
        if response['ok']:
            print(json.dumps(response['data'], allow_nan=False))
            return 0
        print(json.dumps({'ok': False, 'error': response['error']}, ensure_ascii=True))
        return 1
    print(json.dumps({'ok': False, 'error': 'Usage: helper.sh get | set <auto|4-digit RPM> | heartbeat <lease-id>'}))
    return 64


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'error': 'helper_failed', 'error_message': str(exc)[:512]}))
        raise SystemExit(1)
