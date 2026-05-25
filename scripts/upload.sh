#!/usr/bin/env bash
# Upload src/proto/ (and other modules as they're added) to a CYD running
# MicroPython. Idempotent: running it repeatedly just overwrites the files.
#
# Usage:
#   ./scripts/upload.sh [PORT]

set -euo pipefail

PORT="${1:-/dev/tty.usbserial-3110}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -x "$REPO_ROOT/.venv/bin/mpremote" ]; then
    MPREMOTE="$REPO_ROOT/.venv/bin/mpremote"
elif command -v mpremote >/dev/null 2>&1; then
    MPREMOTE="$(command -v mpremote)"
else
    echo "error: mpremote not found" >&2
    exit 1
fi

cd "$REPO_ROOT"

# Make sure msgproto.py + clocksync.py are synced from the submodule first.
if [ ! -f "src/proto/msgproto.py" ]; then
    ./scripts/sync_vendor.sh
fi

# Ensure proto/ exists on the device. mkdir is idempotent under mpremote
# (returns silently if the dir is already there).
"$MPREMOTE" connect "port:$PORT" mkdir proto >/dev/null 2>&1 || true

for f in src/proto/__init__.py src/proto/msgproto.py src/proto/transport.py \
         src/proto/queue.py src/proto/clocksync.py src/proto/handshake.py; do
    echo "cp $f -> :proto/$(basename "$f")"
    "$MPREMOTE" connect "port:$PORT" cp "$f" ":proto/$(basename "$f")"
done

echo "done. Run scripts/selftest.sh $PORT to validate."
