#!/usr/bin/python3
"""Workspace-only fake hardware; never invokes sudo or accesses sysfs."""
import json
from pathlib import Path
import sys
import time

root = Path(__file__).parent
statefile = root / 'state.json'
data = {'is_apple_silicon': True, 'has_fan': True, 'fan_count': 2,
        'fan_min': 1200, 'fan_max': 6241, 'fan_rpm': 2400, 'fan_target': 2500,
        'fans': [{'index': 1, 'label': '<img src="https://invalid/track">',
                  'rpm': 2400, 'target': 2300, 'min': 1200, 'max': 5779},
                 {'index': 2, 'label': 'Fan 2', 'rpm': 2500, 'target': 2500, 'min': 1200, 'max': 6241}],
        'mode': 'auto', 'broker_generation': '0' * 32, 'lease_owned': False,
        'persistent': True, 'per_fan_control': True, 'saved_mode': 'auto',
        'saved_control_mode': 'auto', 'saved_rpm': None, 'saved_fans': [],
        'separate_memory': True, 'saved_separate_fans': [],
        'fan_control_enabled': True, 'control_available': True,
        'max_temp': 0, 'power_watts': 0,
        'sensors': {'nand': 0, 'battery': None, 'regulator': 45.5, 'wifi': 41}}
if statefile.exists():
    data.update(json.loads(statefile.read_text()))
action = sys.argv[1]
if action == 'get':
    counter_file = root / 'reads.txt'
    count = int(counter_file.read_text()) + 1 if counter_file.exists() else 1
    counter_file.write_text(str(count))
    data['fans'][0]['rpm'] += count
    if data['mode'] == 'auto':
        data['fans'][0]['target'] += count * 50
    print(json.dumps(data))
else:
    arguments = sys.argv[2:]
    with (root / 'actions.log').open('a') as log:
        log.write(' '.join([action, *arguments]) + '\n')
    time.sleep(0.15)
    if arguments and arguments[-1] in ('4999', '5050'):
        print(json.dumps({'error': 'fixture command failure <img src="invalid">'}))
        sys.exit(9)
    if arguments and arguments[-1] == '5100':
        reply = {key: data[key] for key in ('mode', 'persistent', 'per_fan_control', 'saved_mode', 'saved_control_mode', 'saved_rpm', 'saved_fans', 'separate_memory', 'saved_separate_fans')}
        reply['saved_fans'] = [{'index': fan['index'], 'rpm': 5150 if fan['index'] == 1 else fan['rpm']} for fan in data['saved_fans']]
        print(json.dumps(reply))
        sys.exit(0)
    if action == 'set':
        target = arguments[0]
        data['mode'] = 'auto' if target == 'auto' else 'manual'
        data['saved_mode'] = data['mode']
        data['saved_control_mode'] = 'auto' if target == 'auto' else 'shared'
        data['saved_rpm'] = None if target == 'auto' else int(target)
        data['saved_fans'] = []
        if target != 'auto':
            for fan in data['fans']:
                fan['target'] = max(fan['min'], min(fan['max'], int(target)))
    elif action == 'set-fan':
        channel, rpm = map(int, arguments)
        targets = {fan['index']: fan['target'] for fan in data['fans']}
        if data['saved_control_mode'] == 'individual':
            targets.update({fan['index']: fan['rpm'] for fan in data['saved_fans']})
        for fan in data['fans']:
            if fan['index'] == channel:
                targets[channel] = max(fan['min'], min(fan['max'], rpm))
            fan['target'] = targets[fan['index']]
        data['mode'] = data['saved_mode'] = 'manual'
        data['saved_control_mode'] = 'individual'
        data['saved_rpm'] = None
        data['saved_fans'] = [{'index': index, 'rpm': target} for index, target in sorted(targets.items())]
        data['saved_separate_fans'] = list(data['saved_fans'])
    elif action == 'set-separate':
        targets = {fan['index']: fan['rpm'] for fan in data['saved_separate_fans']}
        if not targets:
            targets = {fan['index']: max(fan['min'], min(fan['max'], fan['target'])) for fan in data['fans']}
        for fan in data['fans']:
            fan['target'] = max(fan['min'], min(fan['max'], targets[fan['index']]))
        data['mode'] = data['saved_mode'] = 'manual'
        data['saved_control_mode'] = 'individual'
        data['saved_rpm'] = None
        data['saved_fans'] = [{'index': index, 'rpm': rpm} for index, rpm in sorted(targets.items())]
        data['saved_separate_fans'] = list(data['saved_fans'])
    else:
        sys.exit(3)
    data['broker_generation'] = 'a' * 32
    data['lease_owned'] = data['mode'] == 'manual'
    statefile.write_text(json.dumps(data))
    print(json.dumps({key: data[key] for key in ('mode', 'persistent', 'per_fan_control', 'saved_mode',
                                                'saved_control_mode', 'saved_rpm', 'saved_fans', 'separate_memory', 'saved_separate_fans')}))
