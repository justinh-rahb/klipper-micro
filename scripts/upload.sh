#!/usr/bin/env bash
# Upload the full klipper-micro app to a CYD running MicroPython.
# Idempotent: running it repeatedly just overwrites the files.
#
# Usage:
#   ./scripts/upload.sh [PORT]
#
# After a successful upload the board auto-starts main.py on the next reset.
# The script soft-resets the board at the end so the new code runs immediately.

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
    echo "syncing vendor files first..."
    ./scripts/sync_vendor.sh
fi

# Helper: copy a local file to the device, printing progress.
_cp() {
    local src="$1" dst="$2"
    echo "  cp $src -> :$dst"
    "$MPREMOTE" connect "port:$PORT" cp "$src" ":$dst"
}

# Helper: ensure a directory exists on the device (idempotent).
_mkdir() {
    "$MPREMOTE" connect "port:$PORT" mkdir "$1" >/dev/null 2>&1 || true
}

echo "=== uploading to $PORT ==="

# --- Root files ---
echo "[boot + main]"
_cp src/boot.py boot.py
_cp src/main.py main.py

# --- proto/ ---
echo "[proto]"
_mkdir proto
_cp src/proto/__init__.py    proto/__init__.py
_cp src/proto/msgproto.py    proto/msgproto.py
_cp src/proto/transport.py   proto/transport.py
_cp src/proto/queue.py       proto/queue.py
_cp src/proto/clocksync.py   proto/clocksync.py
_cp src/proto/handshake.py   proto/handshake.py

# --- ui/ ---
echo "[ui]"
_mkdir ui
_cp src/ui/__init__.py    ui/__init__.py
_cp src/ui/display.py     ui/display.py
_cp src/ui/manager.py     ui/manager.py
_cp src/ui/mock_state.py  ui/mock_state.py
_cp src/ui/theme.py       ui/theme.py

echo "[ui/screens]"
_mkdir ui/screens
_cp src/ui/screens/__init__.py  ui/screens/__init__.py
_cp src/ui/screens/main.py      ui/screens/main.py
_cp src/ui/screens/settings.py  ui/screens/settings.py

echo "=== upload complete — resetting board ==="
# Soft-reset so main.py runs immediately without unplugging the cable.
"$MPREMOTE" connect "port:$PORT" reset
echo "Board is restarting. The GUI should appear within a few seconds."
