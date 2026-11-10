#!/bin/bash
# Isolated Python: no user site packages, PYTHONPATH, eval, or shell interpolation.
set -euo pipefail
exec /usr/bin/python3 -I -B "$(dirname -- "$(readlink -f -- "$0")")/thermal.py" "$@"
