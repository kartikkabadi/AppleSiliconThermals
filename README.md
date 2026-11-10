# Apple Silicon Thermals

An Omarchy bar widget for Apple Silicon Macs running Linux. It reads fan speeds,
component temperatures and system power directly from `macsmc_hwmon`. Monitoring
requires no administrator permissions. Manual fan control is an optional,
supervised hardware override.

This fork builds on [LukasMoriarty/AppleSiliconThermals](https://github.com/LukasMoriarty/AppleSiliconThermals)
and retains its MIT license. Version 2 replaces the original shell telemetry and
unbounded manual override with validated JSON and expiring control leases.

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
plugin files. An existing legacy root helper must be upgraded separately using
the optional setup below; installing the bar widget does not execute root code.

Use the popup to view each fan's actual speed, target and hardware limits.
Monitoring-only installations display the fan mode as **unknown** because the
kernel does not expose the SMC mode. A positive target RPM is not evidence of
manual operation. The supervised service reports its last successful Auto reset
or its own active manual lease; it cannot prove what an unrelated fan tool does
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
watchdog, verifies that an automatic reset succeeded, then grants only the
installing account passwordless access to the bounded broker actions. Other
local accounts do not receive this permission. Interactive terminals use sudo;
noninteractive callers first try `sudo -n`, then use `pkexec` only when sudo
requires authentication. A command that ran and failed is not retried.

The installer requires Python, systemd and a regex-capable sudoers parser.
Installation can fail after creating root files, for example if hardware reset
fails; the account permission is granted only after the service is ready.
Resolve the reported error before retrying, or use the uninstall procedure.

### How manual control works

- Numeric requests are limited to four-digit RPM values from 1000 through 7999.
  The broker clamps the request separately to each fan's hardware minimum and
  maximum. The UI disables manual controls for incompatible/missing limits.
- This is a fixed target, **not a temperature-driven curve**. Quiet and Regular
  derive from 25%/50% of the highest detected fan maximum; each fan is clamped
  independently. Maximum uses the real detected maximum.
- The root broker serializes all operations with a lock and validates all fans
  before a manual write. A partial failure attempts automatic recovery for all
  fans. If recovery fails, state remains unknown and further manual requests
  are refused until recovery succeeds.
- Each manual request creates a new 12-second lease tied to the caller UID and
  a random generation ID. Only the initiating widget renews that exact lease,
  every 3 seconds. Removing the widget, shell failure, read failure or a stale
  generation stops renewal.
- A separate root watchdog checks every 2 seconds. It releases expired leases,
  invalid or hot component readings (80 C), and changed hardware targets.
  Firmware/another tool changing targets is treated as an override, not fought
  with repeated low-speed writes.
- systemd monitors the watchdog with an 8-second watchdog timeout and restarts
  it after failure. Stop/failure handling attempts Auto. This cannot guarantee
  recovery if the kernel, systemd or hardware itself is unresponsive.
- A sleep guard inhibits requests before suspend and attempts Auto. Resume
  must successfully restore Auto before new manual requests are accepted.
  Lease expiry uses a boot-specific clock that includes time spent suspended.
- Auto first writes a valid per-fan maximum, then zero, to force the kernel's
  cached mode through a known transition. This can briefly increase fan speed.
  The workaround has fixture coverage; real suspend/resume testing is still
  required on each kernel/model.

Root paths are fixed. The privileged program accepts no alternate sysfs roots
or executable paths from arguments/environment. Status reads root-owned state
without sudo. The policy grants no `watchdog`, `sleep` or `resume` actions to the
user. Runtime JSON is bounded and published atomically under `/run`.

## Settings and accessibility

Set `"spinIcon": false` in this widget's `bar.layout` entry in
`~/.config/omarchy/shell.json` to disable the fan animation. The animation also
follows Omarchy's reduce-motion preference. The popup scrolls to fit smaller
screens; it supports Escape and focusable controls. English strings are in
`i18n/en.json`; the selected Omarchy language falls back to English until its
catalog is supplied. Sensor/model names are displayed as plain text.

## Recovery after a failed sleep reset

If a hardware error prevents the sleep guard from restoring Auto, it deliberately
keeps manual requests inhibited. After fixing the cause, an administrator can
retry the protected recovery:

```bash
sudo /usr/local/libexec/apple-silicon-fan-control resume
```

It restores Auto before clearing the guard. Ordinary user Auto cannot clear the
sleep guard because that would reopen the race with an in-progress suspend.

## Remove

If optional control was installed, **release cooling before removing the
widget or its broker**:

```bash
./uninstall.sh
```

This restores Auto, stops/disables the services, restores Auto again and then
removes the root helper, policy and service files. It refuses to remove the
helper if the release command fails. It does not remove the bar widget itself.
If Auto fails, retain the helper, inspect the error and restore known-good
cooling before removing the control mechanism.

Then:

```bash
omarchy plugin disable io.github.lukasmoriarty.applesiliconthermals
omarchy plugin remove io.github.lukasmoriarty.applesiliconthermals
```

For a monitoring-only install, only the two Omarchy commands are necessary.

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
The same Python command also runs two headless QML integration tests when
Omarchy UI modules and Quickshell are installed; otherwise those two tests skip.

See [VALIDATION.md](VALIDATION.md) for completed physical checks on the M1 Pro,
including maximum writes, lease expiry and watchdog crash recovery. Real
suspend/resume and other models remain separate hardware checks. Passing fixtures or a read-only smoke test is not proof that every Mac,
kernel and desktop configuration works. Report the model, kernel, Omarchy/Qt
versions, broker status and relevant service logs when filing an issue; do not
include credentials or private environment dumps.
