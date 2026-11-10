# Validation: 10 November 2026

Implementation commit: `97b5e83` (version 2.0.0).

## Automated checks

- 68 Python tests passed locally, including 2 headless QML integration tests.
- 16 JavaScript validator/security cases passed with Node's test runner.
- Shell syntax, Python compilation, Omarchy manifest validation and diff checks passed.
- Both systemd units passed structural verification with the executable path
  substituted in temporary files; after installation the real units loaded.
- GitHub Actions succeeded on Ubuntu 22.04 and Ubuntu 24.04. QML tests skip on
  runners without the installed Omarchy UI modules.

Coverage includes fanless/unsupported/missing-driver states, sparse sensors,
zero/subzero and invalid readings, multiple fans with unequal limits, malformed
JSON, markup-shaped labels, missing executables, process recovery, command
serialization and Auto priority, generation-bound heartbeats, root ownership,
symlinks/FIFOs, actual flock contention, interrupted writes, partial failures,
watchdog expiry, hot sensors, external target changes and sleep inhibition.

## Physical machine checks

Tested on a 14-inch 2021 M1 Pro MacBook Pro, Arch Linux ARM kernel
7.2.11-14-1-ARCH, Omarchy 4.5.0, Qt 6.12 and Quickshell 0.3.2.

- Installed the root-owned broker, per-account sudoers and both service units.
  Setup established Auto before granting the per-account permission.
- The service started and reported ready/Auto without errors.
- A bounded maximum request was clamped to fan 1's 5779 RPM and fan 2's 6241 RPM.
- A generation-bound heartbeat renewed that lease. With no more heartbeats,
  the service restored Auto after 14 seconds (12-second TTL plus watchdog tick).
- The live bar widget's Max button successfully entered manual mode and renewed
  its own lease for longer than 12 seconds. Both displays showed the widget.
- Killed only the watchdog's main process with SIGKILL during that maximum-speed
  request. systemd restarted it and restored ready/Auto with a new PID after
  2 seconds. The widget stopped renewing the obsolete generation.
- The popup displayed both fans, correct hardware limits and component readings
  without the previous Qt color errors. The Auto and Close buttons worked.
- Final state: ready=true, mode=auto, inhibited=false, error=null; popup closed.
  The watchdog and pre-sleep guard remain enabled for subsequent use.

## Limits

Real machine suspend/resume, reboot, logout/login, unplugged-monitor transitions,
other Mac models and other kernel/Omarchy versions were not physically tested.
Sleep inhibition, stale generations, reboot identity and failed recovery have
fixture coverage, which is distinct from physical testing. The source and
kernel design do not expose CPU/GPU die temperatures or independently attest
mode changes made by other fan controllers. The watchdog is software recovery,
not a guarantee against kernel/hardware failure or overheating.
