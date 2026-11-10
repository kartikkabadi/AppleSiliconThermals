#!/usr/bin/python3
"""Workspace-only fake hardware; never invokes sudo or accesses sysfs."""
import json
from pathlib import Path
import sys
import time

root = Path(__file__).parent
statefile = root / 'state.json'
data = {'is_apple_silicon': True, 'has_fan': True, 'fan_count': 2,
        'fan_min': 1200, 'fan_max': 6241, 'fan_rpm': 2400, 'fan_target': 2300,
        'fans': [{'index': 1, 'label': '<img src="https://invalid/track">',
                  'rpm': 2400, 'target': 2300, 'min': 1200, 'max': 5779},
                 {'index': 2, 'label': 'Fan 2', 'rpm': 2500, 'target': 2500, 'min': 1200, 'max': 6241}],
        'mode': 'auto', 'broker_generation': '0' * 32, 'lease_owned': False,
        'persistent': True, 'saved_mode': 'auto', 'saved_rpm': None,
        'fan_control_enabled': True, 'control_available': True,
        'max_temp': 0, 'power_watts': 0,
        'sensors': {'nand': 0, 'battery': None, 'regulator': 45.5, 'wifi': 41}}
if statefile.exists():
    data.update(json.loads(statefile.read_text()))
action = sys.argv[1]
if action == 'get':
    print(json.dumps(data))
else:
    target = sys.argv[2]
    with (root / 'actions.log').open('a') as log:
        log.write(f'{action} {target}\n')
    if action == 'set':
        time.sleep(0.15)
        if target == '4999':
            print(json.dumps({'error': 'fixture command failure <img src="invalid">'}))
            sys.exit(9)
        data['mode'] = 'auto' if target == 'auto' else 'manual'
        data['saved_mode'] = data['mode']
        data['saved_rpm'] = None if target == 'auto' else int(target)
        data['broker_generation'] = 'a' * 32
        data['lease_owned'] = target != 'auto'
        statefile.write_text(json.dumps(data))
    elif action == 'heartbeat' and target != data['broker_generation']:
        sys.exit(1)
    print(json.dumps({'mode': data['mode'], 'generation': data['broker_generation'], 'persistent': True,
                      'saved_mode': data['saved_mode'], 'saved_rpm': data['saved_rpm']}))
