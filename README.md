# Apple Silicon Thermals

An Omarchy bar widget for Apple Silicon Macs running Linux. It reads fan speeds,
component temperatures and system power directly from `macsmc_hwmon`. Monitoring
requires no administrator permissions. Manual fan control is an optional,
supervised hardware override.

This fork builds on [LukasMoriarty/AppleSiliconThermals](https://github.com/LukasMoriarty/AppleSiliconThermals)
and retains its MIT license. Version 2 replaces the original shell telemetry and
unbounded manual override with validated JSON and supervised fan control.
Version 2.5 remembers both your Linked speed and your Separate fan speeds.
Switching layouts restores the settings saved for that layout. Both profiles
and the active layout survive bar restarts and reboot. Older saved settings
migrate without losing the active choice. Version 2.5.1 adds installation-path
checks, sleep/helper failure recovery, and explicit screen-reader controls.

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
plugin files. When upgrading to a version with new QML components, run `omarchy restart shell` once
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

Setup and uninstall check root ownership and permissions along every installed
path before elevation, including physical symlink targets. Unsafe existing paths
are refused with a diagnostic; existing directory ownership is not silently
changed. This prevents a writable executable parent from weakening the bounded
sudo policy.

The installer requires Python, systemd and a regex-capable sudoers parser.
Installation can fail after creating root files, for example if hardware reset
fails; the account permission is granted only after the service is ready.
Resolve the reported error before retrying, or use the uninstall procedure.

### Remembered mode and RPM

Manual mode offers **Linked** and **Separate** controls. Linked is the default
for new manual settings: one slider and Quiet/Balanced/Max presets adjust both
fans, clamped to each fan's hardware limits. Choose Separate for an individual
slider and presets on each fan card. Adjusting one fan preserves the others.
Each layout has its own remembered settings. Switching to Linked restores your
last Linked speed; switching to Separate restores the last individual targets
you saved. Editing either layout preserves the other profile. A restored speed
can be lower than the speed used in the other layout.

On first use, Linked starts from the highest current fan target, and Separate
starts from the current per-fan targets. The root service saves both profiles
and your selected layout across shell restart and reboot. Auto retains both
manual profiles. Returning to Manual restores the remembered Linked speed.

The root control service maintains these settings independently of the widget
and restores the active choice after service
restart, shell restart, login and reboot. Closing the popup or disabling the
widget does not change the saved choice. Choose **Auto** to save automatic
firmware control instead. A reboot begins with an automatic reset, then applies
the saved manual setting after validating the available hardware and sensors.

The preference is an atomic, root-owned JSON file at:

```text
/var/lib/apple-silicon-fan-control/preference.json
```

The file records mode, active targets, both remembered profiles, and the
requesting account. It does not contain executable code or arbitrary paths. Writes include file and directory
synchronization so an acknowledged choice is durable. Runtime state under
`/run` is separate; discarding runtime state does not discard your preference.
The popup distinguishes your saved choice from the current hardware mode. A
safety pause retains the choice and explains why it is temporarily inactive.

### Upgrading existing saved settings

Version 2.1–2.4 preferences migrate on read without rewriting their files.
An older active Linked speed seeds the Linked profile; an older active Separate
map seeds the Separate profile. Version 2.4 Separate memory is retained.
History that older versions did not save starts empty. Schema 4 writes happen
only after an explicit user setting change.
The first individual adjustment captures the detected fan inventory and the
other fans' desired, clamped targets, then saves the complete independent map.
Numeric `helper.sh set <RPM>` remains available as a shared compatibility action;
`helper.sh set-fan <index> <RPM>` changes one channel.
`helper.sh set-linked` and `helper.sh set-separate` restore the corresponding
remembered profile in one verified transaction. The root
interface accepts only indices 1–64 and bounded numeric RPM, never paths or executable arguments.

Independent maps must match the detected inventory exactly. Missing or newly
appeared fans pause the saved setting rather than applying another channel's
RPM. Select Auto, then configure the available fans again after a hardware
inventory change. Changing hardware limits replans the actual clamp while
retaining the originally requested RPM in the saved preference. An inactive
Separate profile with a different fan inventory does not disrupt Linked control;
restoring it is refused instead of applying its speeds to different channels.
From Linked or Auto, an explicit `set-fan` edit starts a new map from the current
fan inventory if you need to replace an obsolete Separate profile.

### Hardware control and recovery

- Requests are four-digit RPM values from 1000 through 7999. Each fan is clamped
  to its own hardware range. Each separate slider and Max preset uses that fan's own
  minimum and maximum. The linked slider uses the widest detected range; its
  shared target is clamped independently on each channel.
- These are fixed RPM settings, not temperature curves. Quiet and Balanced are
  25% and 50% of the maximum, clamped to the range (per fan in Separate;
  the highest fan maximum in Linked).
- The broker serializes all writes and validates all channels before a change.
  A write journal marks incomplete changes as unknown so interrupted requests
  trigger recovery rather than leaving a false success state.
- Initial manual application forces a known driver-mode transition and verifies
  target readback. Physical fan RPM can take a few seconds to reach the target.
  A healthy one-fan adjustment does not rewrite unchanged fan registers. Rapid
  changes to different sliders are queued independently; pending changes to the
  same fan coalesce to its latest value, and Auto cancels pending manual changes.
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
- Sleep inhibits new requests and releases control. A post-only system-sleep
  hook records a root-owned wake event without waiting for fan-operation locks
  held by a frozen user session. The supervisor consumes that event after wake,
  even if pre-sleep release failed or timed out. Old events cannot clear a later
  sleep inhibit. Restoration waits for the outer sleep target and any queued job
  to finish, including suspend-then-hibernate intermediate wakes. A failure-only
  service cleanup signal also covers aborted sleep attempts which run no hook.
  The normal resume action remains as an idempotent fallback.
  Resume retries any failed automatic reset; the service restores a saved
  manual preference only after cooling is in a known, eligible state. Internal
  release, sleep and shutdown never overwrite your choice.
- If a UI helper cannot start or hangs, child processes are terminated and late
  results are ignored. A queued Auto request is retained and retried after a
  successful periodic telemetry read, rather than stalling or retrying in a loop.
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
grants bounded user actions; internal `watchdog`, `release`, `sleep`, `resume`,
`wake-signal` and `sleep-failed` actions remain root-only. Status reads require no sudo. Older lease-based control
services must be upgraded before this widget enables numeric manual controls.

## Settings and accessibility

Set `"spinIcon": false` in this widget's `bar.layout` entry in
`~/.config/omarchy/shell.json` to disable the fan animation. The animation also
follows Omarchy's reduce-motion preference. The fan glyph is 4% larger without
changing the bar slot, and turns at a constant rate instead of changing speed
with each RPM reading. The popup scrolls to fit smaller
screens; it supports Escape and focusable controls. Buttons expose names,
selected states and guarded press actions to assistive technology. Fan cards distinguish
current RPM from target RPM, while gauges show speed relative to each fan maximum.
One Auto/Manual selector controls the overall mode. A Linked/Separate selector
chooses a shared slider or individual fan controls; component details can be expanded when needed. English strings are in
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
services, verifies Auto again, and removes the root helper, policy, service files,
the post-wake hook, and saved preference. It refuses to remove the
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
sh -n system/apple-silicon-fan-wake
python3 -m py_compile thermal.py system/apple-silicon-fan-control system/install-path-safety.py
```

Python tests use isolated temporary sysfs/runtime fixtures and do not require
root or write host fan settings. JavaScript tests validate the QML parser,
malformed data and markup neutralization. CI runs these on Ubuntu 22.04/24.04.
The same Python command also runs headless QML integration and rendered-motion
tests when Omarchy UI modules and Quickshell are installed; otherwise they skip.

See [VALIDATION.md](VALIDATION.md) for completed physical checks on the M1 Pro,
including maximum writes and watchdog recovery. Earlier lease-expiry checks
there describe version 2.0; version 2.1 deliberately owns manual control in the
service rather than requiring UI heartbeats. Real
suspend/resume and other models remain separate hardware checks. Passing fixtures or a read-only smoke test is not proof that every Mac,
kernel and desktop configuration works. Report the model, kernel, Omarchy/Qt
versions, broker status and relevant service logs when filing an issue; do not
include credentials or private environment dumps.
