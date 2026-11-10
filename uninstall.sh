#!/usr/bin/env bash
# Run as your normal desktop user. Refuse removal unless cooling is released.
set -euo pipefail
export PATH=/usr/bin:/bin
if (( EUID == 0 )); then
  echo 'Run uninstall.sh without sudo.' >&2
  exit 1
fi
if [[ $# -ne 0 ]]; then
  echo 'Usage: ./uninstall.sh' >&2
  exit 64
fi

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
    pkexec -- "$@"
  else
    rm -f -- "$diagnostic"
    return "$result"
  fi
}

broker=/usr/local/libexec/apple-silicon-fan-control
if [[ ! -x "$broker" ]]; then
  echo 'No installed broker found. No root files were removed.'
  exit 0
fi
# All account permissions are removed only after a successful hardware release.
elevate "$broker" auto
elevate /usr/bin/systemctl disable --now apple-silicon-fan-watchdog.service apple-silicon-fan-sleep.service
# This second release also covers older services whose stop path differed.
elevate "$broker" auto
elevate /usr/bin/rm -f /etc/sudoers.d/apple-silicon-fan-control /etc/tmpfiles.d/macsmc-fan.conf /etc/systemd/system/apple-silicon-fan-watchdog.service /etc/systemd/system/apple-silicon-fan-sleep.service /usr/local/libexec/apple-silicon-fan-control
elevate /usr/bin/systemctl daemon-reload
echo 'Removed optional manual fan control. Firmware automatic cooling was restored.'
