#!/usr/bin/env bash
# Upload the full klipper-micro app to a CYD running MicroPython.
# Idempotent: running it repeatedly just overwrites the files.
#
# Usage:
#   ./scripts/upload.sh [PORT]
#
# Strategy
# --------
# Once LVGL is running the FreeRTOS task handler intercepts Ctrl+C, so
# mpremote cannot enter raw REPL through the normal path.  To work around
# this, the script hard-resets the board via DTR toggle, then connects with
# a single mpremote session during the 3-second boot window that main.py
# provides before calling display.init().  All file operations happen in
# that one session so we never have to reconnect while LVGL is alive.
#
# After a successful upload the board is soft-reset so the new code runs
# immediately; the GUI appears a few seconds after the script exits.

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

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

cd "$REPO_ROOT"

# Sync vendor files if needed.
if [ ! -f "src/proto/msgproto.py" ]; then
    echo "syncing vendor files first..."
    ./scripts/sync_vendor.sh
fi

# ---------------------------------------------------------------------------
# Hard-reset the board via DTR toggle so we start from a clean boot.
# ---------------------------------------------------------------------------
echo "resetting board..."
"$PYTHON" - <<PYEOF
import serial, time, sys
try:
    s = serial.Serial("$PORT", 115200)
    s.dtr = False
    time.sleep(0.05)
    s.dtr = True
    time.sleep(0.05)
    s.close()
except Exception as e:
    print("DTR reset failed:", e, file=sys.stderr)
PYEOF

# Give MicroPython ~1 s to start and enter the boot window.
sleep 1

# ---------------------------------------------------------------------------
# All file operations in a single mpremote session.
# Directories are created via exec (idempotent — ignores EEXIST).
# ---------------------------------------------------------------------------
echo "=== uploading to $PORT ==="

"$MPREMOTE" connect "port:$PORT" \
    exec "import os
for d in ['proto','ui','ui/screens']:
    try: os.mkdir(d)
    except: pass" \
    + cp src/boot.py                    :boot.py \
    + cp src/main.py                    :main.py \
    + cp src/wifi.py                    :wifi.py \
    + cp src/config.py                  :config.py \
    + cp src/proto/__init__.py          :proto/__init__.py \
    + cp src/proto/msgproto.py          :proto/msgproto.py \
    + cp src/proto/transport.py         :proto/transport.py \
    + cp src/proto/queue.py             :proto/queue.py \
    + cp src/proto/clocksync.py         :proto/clocksync.py \
    + cp src/proto/handshake.py         :proto/handshake.py \
    + cp src/ui/__init__.py             :ui/__init__.py \
    + cp src/ui/display.py              :ui/display.py \
    + cp src/ui/manager.py              :ui/manager.py \
    + cp src/ui/mock_state.py           :ui/mock_state.py \
    + cp src/ui/theme.py                :ui/theme.py \
    + cp src/ui/screens/__init__.py     :ui/screens/__init__.py \
    + cp src/ui/screens/main.py         :ui/screens/main.py \
    + cp src/ui/screens/settings.py     :ui/screens/settings.py \
    + cp src/ui/screens/wifi.py         :ui/screens/wifi.py \
    + cp src/ui/screens/setpoint.py     :ui/screens/setpoint.py \
    + reset

echo "=== upload complete — board restarting ==="
echo "The GUI should appear in ~5 seconds (3s boot window + display init)."
