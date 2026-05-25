#!/usr/bin/env bash
# Run src/device_selftest.py on the CYD and stream its output.
#
# Usage:
#   ./scripts/selftest.sh [PORT]

set -euo pipefail

PORT="${1:-/dev/tty.usbserial-3110}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -x "$REPO_ROOT/.venv/bin/mpremote" ]; then
    MPREMOTE="$REPO_ROOT/.venv/bin/mpremote"
else
    MPREMOTE="$(command -v mpremote)"
fi

exec "$MPREMOTE" connect "port:$PORT" run "$REPO_ROOT/src/device_selftest.py"
