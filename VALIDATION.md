# Version 2.1 persistence and UI validation — 10 November 2026

Implementation: `f47c4f3`, authentication fix `ade5c71`, readability `cde2e97`.

- 110 Python tests and 18 JavaScript tests pass locally. Python coverage includes
  three headless QML cases. Both Ubuntu CI targets pass (QML skips when Omarchy
  modules are not present).
- Independent fixtures simulate a new boot ID and empty runtime directory while
  retaining the durable preference; manual RPM is restored without a widget.
- Additional checks cover long operation without UI heartbeats, internal release
  preserving intent, explicit Auto transaction ordering, interrupted/failed saves,
  restoration blocks, corrupted and insecure preferences, parent-directory fsync,
  thermal hysteresis, pause/retry cooldowns, and restart/resume recovery.
- Installer elevation routing is tested with mocks: sudo authentication failures
  use pkexec without an unsupported separator; commands that ran and failed are
  never executed again through pkexec.
- Installed the persistent supervisor and root-owned preference on the M1 Pro.
  The prior shared request of 6241 RPM was saved, with per-fan targets 5779/6241.
- A real supervisor restart changed its process PID and restored that saved
  manual request. A real Omarchy shell restart left the same preference and
  manual control active. No UI heartbeat is required by version 2.1.
- The popup was inspected on the live desktop: fan RPM/target cards, percent
  bars, temperature/power cards, mode selector and remembered presets rendered.
  Numeric readouts were increased after inspection for better readability.
- New QML types did not replace an already compiled older widget during the
  first hot update. A full shell restart loaded the new UI; README documents
  this one-time upgrade requirement. Persistent fan control is independent of it.

The machine was not rebooted or suspended during this work. Reboot restoration
is covered by isolated cold-start fixtures; service and shell restarts were
physically tested. Other Mac models/kernels remain unverified. Hardware faults
can temporarily pause manual control while preserving the saved choice.

---

Earlier version 2.0 checks follow for history. Their lease-expiry behavior was
intentionally replaced by service-owned persistent settings in version 2.1.

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
