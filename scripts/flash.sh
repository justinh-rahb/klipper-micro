#!/usr/bin/env bash
# Flash MicroPython firmware onto an ESP32 CYD and install the runtime deps
# our code needs (zlib + logging from micropython-lib).
#
# Usage:
#   ./scripts/flash.sh [PORT]
#
# Defaults to /dev/tty.usbserial-3110. Set MP_FIRMWARE to use a non-default
# image (e.g. an LVGL-enabled build for Phase 4 UI work).

set -euo pipefail

PORT="${1:-/dev/tty.usbserial-3110}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$REPO_ROOT/firmware/cache"
DEFAULT_FW_URL="https://micropython.org/resources/firmware/ESP32_GENERIC-20250911-v1.26.1.bin"
DEFAULT_FW_NAME="ESP32_GENERIC-20250911-v1.26.1.bin"
FW_PATH="${MP_FIRMWARE:-$CACHE/$DEFAULT_FW_NAME}"

if [ ! -f "$FW_PATH" ]; then
    echo "downloading MicroPython firmware to $FW_PATH"
    mkdir -p "$CACHE"
    curl -fsSL -o "$FW_PATH" "$DEFAULT_FW_URL"
fi

if ! command -v esptool >/dev/null 2>&1; then
    echo "error: esptool not found on PATH" >&2
    exit 1
fi

if ! command -v mpremote >/dev/null 2>&1; then
    if [ -x "$REPO_ROOT/.venv/bin/mpremote" ]; then
        MPREMOTE="$REPO_ROOT/.venv/bin/mpremote"
    else
        echo "error: mpremote not found (try: .venv/bin/pip install mpremote)" >&2
        exit 1
    fi
else
    MPREMOTE="$(command -v mpremote)"
fi

echo "erasing flash on $PORT..."
esptool --port "$PORT" --baud 460800 erase-flash

echo "writing $FW_PATH..."
esptool --port "$PORT" --baud 460800 write-flash 0x1000 "$FW_PATH"

# Give the chip time to reboot into MicroPython
sleep 2

echo "installing runtime deps (zlib, logging) via mip..."
"$MPREMOTE" connect "port:$PORT" mip install zlib
"$MPREMOTE" connect "port:$PORT" mip install logging

echo "done. Now run scripts/upload.sh $PORT to push the app."
