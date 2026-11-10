# Apple Silicon Thermals

An Omarchy bar widget for Apple Silicon Macs running Linux. It reads fan speeds,
component temperatures and system power directly from `macsmc_hwmon`. Monitoring
requires no administrator permissions. Manual fan control is an optional,
supervised hardware override.

This fork builds on [LukasMoriarty/AppleSiliconThermals](https://github.com/LukasMoriarty/AppleSiliconThermals)
and retains its MIT license. Version 2 replaces the original shell telemetry and
unbounded manual override with validated JSON and supervised fan control.
Version 2.1 remembers your selected mode and RPM across bar restarts and reboot.

## Requirements and support

- Linux with the `macsmc_hwmon` driver and Python 3.10 or newer at `/usr/bin/python3`.
- Omarchy's Quickshell shell, with `qs.Ui.PopupCard`, `OpticalGlyph`,
  `Commons.Translations` and `Commons.I18n`. Tested on Omarchy 4.5.0, Quickshell
  0.3.2 and Qt 6.12, on a 14-inch 2021 M1 Pro MacBook Pro.
- Optional manual control additionally needs systemd, sudo 1.9.10 or newer
  (argument regular expressions), root-owned sysfs controls, and a functioning
  desktop authentication agent when installing without a terminal.

M1/M2 hardware with this driver is the intended platform. Fanless Macs show
sensor readings without fan controls. Single/multiple fans, different per-fan
limits, hwmon renumbering, missing sensors and unsupported machines have fixture
coverage. Other physical models and earlier Omarchy releases have not been
hardware-tested; missing controls fail closed instead of guessing RPM limits.

The shown temperatures are NAND, battery hotspot, charge regulator and Wi-Fi/BT
component readings. They are **not CPU/GPU die temperatures**, and can lag load.
The maximum is explicitly the maximum of the available component readings.
Missing readings display as unavailable; zero is a valid reading.

## Install monitoring

Install from this fork after reviewing its source:

```bash
omarchy plugin add https://github.com/kartikkabadi/AppleSiliconThermals.git --enable
```

For a local checkout, copy or clone the complete repository to:

```text
~/.config/omarchy/plugins/io.github.lukasmoriarty.applesiliconthermals/
```

Then run:

```bash
omarchy plugin enable io.github.lukasmoriarty.applesiliconthermals --section right
```

Do not install both upstream and this fork: the plugin ID is intentionally the
same so an existing installation can be upgraded. Back up the existing checkout
and `~/.config/omarchy/shell.json` before replacing it. The shell hot-reloads
plugin files. When upgrading from 2.0 to 2.1, run `omarchy restart shell` once
after updating: Quickshell can retain older compiled widget components during
a hot update that adds new QML types. The persistent control service keeps the
saved fan setting independently of that restart. An existing legacy root helper must be upgraded separately using
the optional setup below; installing the bar widget does not execute root code.

Use the popup to view each fan's actual speed, target and hardware limits.
Monitoring-only installations display the fan mode as **unknown** because the
kernel does not expose the SMC mode. A positive target RPM is not evidence of
manual operation. The supervised service reports its last successful Auto reset
or its own active manual setting; it cannot prove what an unrelated fan tool does
later. Run only one fan-control system at a time.

## Optional manual control

The Linux kernel marks manual fan control unsafe: a safe overheating outcome
cannot be guaranteed for every failure. The safeguards here reduce particular
failure modes; they do not make peripheral sensors a substitute for processor
thermal management. Keep automatic firmware cooling for normal use.

From the reviewed checkout, run **as your normal desktop user**:

```bash
./setup.sh --enable-manual-control
```

Do not use `sudo ./setup.sh`. The installer copies the broker and service units
into root-owned locations with standard `install` commands. It starts the
watchdog, verifies that cooling control is ready, then grants only the
installing account passwordless access to the bounded broker actions. Other
local accounts do not receive this permission. Interactive terminals use sudo;
noninteractive callers first try `sudo -n`, then use `pkexec` only when sudo
requires authentication. A command that ran and failed is not retried.

The installer requires Python, systemd and a regex-capable sudoers parser.
Installation can fail after creating root files, for example if hardware reset
fails; the account permission is granted only after the service is ready.
Resolve the reported error before retrying, or use the uninstall procedure.

### Remembered mode and RPM

Choosing Manual, a preset, or the slider saves your chosen RPM. The root control
service maintains it independently of the widget and restores it after service
restart, shell restart, login and reboot. Closing the popup or disabling the
widget does not change the saved choice. Choose **Auto** to save automatic
firmware control instead. A reboot begins with an automatic reset, then applies
the saved manual setting after validating the available hardware and sensors.

The preference is an atomic, root-owned JSON file at:

```text
/var/lib/apple-silicon-fan-control/preference.json
```

The file records mode, requested RPM and the requesting account. It does not
contain executable code or arbitrary paths. Writes include file and directory
synchronization so an acknowledged choice is durable. Runtime state under
`/run` is separate; discarding runtime state does not discard your preference.
The popup distinguishes your saved choice from the current hardware mode. A
safety pause retains the choice and explains why it is temporarily inactive.

### Hardware control and recovery

- Requests are four-digit RPM values from 1000 through 7999. Each fan is clamped
  to its own hardware range. Maximum uses the real highest detected maximum;
  the other fan may have a lower limit. The shared slider controls both fans.
- These are fixed RPM settings, not temperature curves. Quiet and Balanced are
  25% and 50% of the highest maximum, clamped per fan.
- The broker serializes all writes and validates all channels before a change.
  A write journal marks incomplete changes as unknown so interrupted requests
  trigger recovery rather than leaving a false success state.
- Initial manual application forces a known driver-mode transition and verifies
  target readback. Physical fan RPM can take a few seconds to reach the target.
- The service checks hardware every 2 seconds. Transient target drift gets at
  most two verified repairs within 30 seconds. Repeated refusal pauses manual
  control with the requested and observed values; a cooldown prevents continuous
  attempts to fight firmware or another controller.
- Invalid/missing/hot component readings temporarily release to firmware. The
  saved manual choice remains. Restoration requires healthy readings below the
  lower resume threshold and a cooldown, preventing rapid mode oscillation.
- systemd supervises the service with an 8-second watchdog deadline. If it
  crashes or stalls, stop handling attempts firmware control; the restarted
  service then validates and reapplies the saved choice. If the kernel or
  hardware is unresponsive, software recovery cannot guarantee cooling.
- Sleep inhibits new requests and releases control. Resume marks the system
  awake and retries any failed automatic reset; the service restores a saved
  manual preference only after cooling is in a known, eligible state. Internal release, sleep and shutdown never overwrite your choice.
- Explicit user Auto is saved before hardware release. A crash during that
  release therefore cannot resurrect an older manual preference. A numeric
  choice is committed only after successful target application and verification.
- Corrupt or insecure preference data fails closed to Auto with a diagnostic.
  It is not executed, silently trusted, or treated as a valid manual setting.

The temperatures exposed here are peripheral/component readings, not processor
die temperatures. The kernel marks manual fan control unsafe because a safe
outcome under every overheating failure cannot be proven. Mechanical RPM bounds
and software recovery are useful protections, not a hardware safety guarantee.

Root paths are fixed. Privileged actions cannot accept alternate sysfs roots or
executables through arguments/environment. The single-account sudo policy only
grants bounded user actions; internal `watchdog`, `release`, `sleep` and `resume`
actions remain root-only. Status reads require no sudo. Older lease-based control
services must be upgraded before this widget enables numeric manual controls.

## Settings and accessibility

Set `"spinIcon": false` in this widget's `bar.layout` entry in
`~/.config/omarchy/shell.json` to disable the fan animation. The animation also
follows Omarchy's reduce-motion preference. The popup scrolls to fit smaller
screens; it supports Escape and focusable controls. Fan cards distinguish
current RPM from target RPM, while gauges show speed relative to each fan maximum.
A single Auto/Manual selector replaces duplicate actions; preset cards show
their target RPM and component details can be expanded when needed. English strings are in
`i18n/en.json`; the selected Omarchy language falls back to English until its
catalog is supplied. Sensor/model names are displayed as plain text.

## Saved settings during a safety pause

If a sensor or hardware error prevents manual control, the saved setting stays
visible while actual control temporarily returns to firmware. The service retries
after a cooldown and restores the saved target only when readings are healthy.
Repeated firmware refusals are not retried continuously. Choose Auto to replace
the saved manual choice; choosing another manual target saves the new value only
after verification.

A failed attempt to save Auto is reported explicitly and blocks restoration of
the older manual setting in runtime state. If storage cannot accept a durable
write, the last acknowledged file is still the reboot preference; resolve the
save error rather than treating the failed request as remembered.

## Remove

If optional control was installed, **release cooling before removing the
widget or its broker**:

```bash
./uninstall.sh
```

This verifies a hardware release, explicitly saves Auto, stops/disables the
services, verifies Auto again, and removes the root helper, policy, service files
and saved preference. It refuses to remove the
helper if the release command fails. It does not remove the bar widget itself.
If Auto fails, retain the helper, inspect the error and restore known-good
cooling before removing the control mechanism.

Then:

```bash
omarchy plugin disable io.github.lukasmoriarty.applesiliconthermals
omarchy plugin remove io.github.lukasmoriarty.applesiliconthermals
```

For a monitoring-only install, only the two Omarchy commands are necessary.
With persistent control installed, removing only the widget intentionally leaves
the service and your saved fan setting running; uninstall control first when
you want to return permanently to firmware management.

## Development and verification

No Python packages or downloaded runtime binaries are needed.

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_telemetry.cjs
bash -n helper.sh setup.sh uninstall.sh
python3 -m py_compile thermal.py system/apple-silicon-fan-control
```

Python tests use isolated temporary sysfs/runtime fixtures and do not require
root or write host fan settings. JavaScript tests validate the QML parser,
malformed data and markup neutralization. CI runs these on Ubuntu 22.04/24.04.
The same Python command also runs three headless QML integration tests when
Omarchy UI modules and Quickshell are installed; otherwise those three tests skip.

See [VALIDATION.md](VALIDATION.md) for completed physical checks on the M1 Pro,
including maximum writes and watchdog recovery. Earlier lease-expiry checks
there describe version 2.0; version 2.1 deliberately owns manual control in the
service rather than requiring UI heartbeats. Real
suspend/resume and other models remain separate hardware checks. Passing fixtures or a read-only smoke test is not proof that every Mac,
kernel and desktop configuration works. Report the model, kernel, Omarchy/Qt
versions, broker status and relevant service logs when filing an issue; do not
include credentials or private environment dumps.
