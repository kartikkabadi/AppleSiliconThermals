#!/usr/bin/env bash
# Run as your normal desktop user, never as `sudo ./setup.sh`.
set -euo pipefail
export PATH=/usr/bin:/bin

if (( EUID == 0 )); then
  echo 'Run setup.sh as the intended desktop user, without sudo.' >&2
  exit 1
fi
if [[ $# -ne 1 || "$1" != --enable-manual-control ]]; then
  echo 'Usage: ./setup.sh --enable-manual-control' >&2
  echo 'Monitoring needs no root setup. Manual control is an optional hardware override.' >&2
  exit 64
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
account=$(id -un)
if [[ ! "$account" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo 'This account name requires a manually escaped sudoers policy; refusing to guess.' >&2
  exit 1
fi
for tool in python3 systemctl install visudo sudo; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done
if [[ ! -d /run/systemd/system ]]; then
  echo 'Optional manual control requires systemd as PID 1.' >&2
  exit 1
fi

# sudo -n first; only an authentication failure is eligible for desktop auth.
# Failures from a command that actually ran must never be executed a second time.
elevate() {
  if [[ -t 0 && -t 1 ]]; then
    sudo -- "$@"
    return $?
  fi
  local diagnostic result
  diagnostic=$(mktemp)
  if LC_ALL=C sudo -n -- "$@" 2>"$diagnostic"; then
    cat "$diagnostic" >&2
    rm -f -- "$diagnostic"
    return 0
  else
    result=$?
  fi
  cat "$diagnostic" >&2
  if grep -Eq '^sudo: (a password is required|a terminal is required|no tty present and no askpass program specified)' "$diagnostic"; then
    rm -f -- "$diagnostic"
    command -v pkexec >/dev/null || { echo 'Desktop authentication needs pkexec and a polkit agent.' >&2; return "$result"; }
    pkexec "$@"
  else
    rm -f -- "$diagnostic"
    return "$result"
  fi
}

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
sed "s/@USER@/$account/" "$source_dir/system/apple-silicon-fan-control.sudoers" > "$scratch/policy"
chmod 600 "$scratch/policy"
visudo -c -f "$scratch/policy"
python3 -m py_compile "$source_dir/system/apple-silicon-fan-control"
python3 -I - "$source_dir/system/apple-silicon-fan-control" <<'PYTHON'
import runpy
import sys
namespace = runpy.run_path(sys.argv[1], run_name='preflight')
hardware = namespace['Hardware']()
for _, register in hardware.fans:
    hardware.bounds(register)
# Heat/telemetry faults must not prevent upgrading the recovery service.
# The supervisor keeps Auto and postpones saved manual restoration until healthy.
store = namespace['PERSISTENCE']
if store.exists() or store.is_symlink():
    namespace['secure_persistence']()
    profile = store / 'preference.json'
    if profile.exists() or profile.is_symlink():
        import os
        descriptor = namespace['secure_regular'](profile)
        os.close(descriptor)
PYTHON

echo 'Installing persistent manual fan control for this account only.'
echo 'Saved settings survive shell restarts and reboot; the root supervisor handles recovery.'
# Preserve existing acknowledged intent before upgrading any installed component.
if [[ -f /var/lib/apple-silicon-fan-control/preference.json ]]; then
  backup_path="/var/lib/apple-silicon-fan-control/backups/preference.$(date -u +%Y%m%dT%H%M%S).$$.json"
  elevate /usr/bin/install -o root -g root -m 700 -d /var/lib/apple-silicon-fan-control/backups
  elevate /usr/bin/install -o root -g root -m 600 /var/lib/apple-silicon-fan-control/preference.json "$backup_path"
  echo "Saved existing preference backup: $backup_path"
fi
# Revoke a legacy ALL-user policy before replacing its executable. New
# permission is granted only after the supervisor establishes a known cooling state.
elevate /usr/bin/rm -f /etc/sudoers.d/apple-silicon-fan-control
# install copies data to root-owned destinations; no checkout code runs as root.
elevate /usr/bin/install -o root -g root -m 644 -D "$source_dir/system/apple-silicon-fan-watchdog.service" /etc/systemd/system/apple-silicon-fan-watchdog.service
elevate /usr/bin/install -o root -g root -m 644 -D "$source_dir/system/apple-silicon-fan-sleep.service" /etc/systemd/system/apple-silicon-fan-sleep.service
# Load release-only lifecycle actions before replacing a legacy executable.
# Otherwise a previously loaded ExecStopPost=auto could erase saved intent.
elevate /usr/bin/systemctl daemon-reload
elevate /usr/bin/install -o root -g root -m 755 -D "$source_dir/system/apple-silicon-fan-control" /usr/local/libexec/apple-silicon-fan-control
# Start the independent safety service before reporting setup success.
elevate /usr/bin/systemctl enable apple-silicon-fan-watchdog.service apple-silicon-fan-sleep.service
elevate /usr/bin/systemctl restart apple-silicon-fan-watchdog.service
for attempt in {1..20}; do
  if /usr/local/libexec/apple-silicon-fan-control status | python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("ready") and s.get("mode") in ("auto","manual") and s.get("separate_memory") is True and s.get("linked_memory") is True else 1)'; then
    break
  fi
  sleep 0.5
done
/usr/local/libexec/apple-silicon-fan-control status | python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("ready") and s.get("mode") in ("auto","manual") and s.get("separate_memory") is True and s.get("linked_memory") is True else "Supervisor did not establish a compatible known cooling state; no permission was granted")'
elevate /usr/bin/install -o root -g root -m 440 -D "$scratch/policy" /etc/sudoers.d/apple-silicon-fan-control
# Remove the obsolete boot-time unlock only after the supervised setup is ready.
elevate /usr/bin/rm -f /etc/tmpfiles.d/macsmc-fan.conf
echo 'Installed. The supervisor owns saved settings independently of the widget.'
/usr/local/libexec/apple-silicon-fan-control status
