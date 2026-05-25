#!/usr/bin/env bash
# Flash MicroPython firmware onto an ESP32 CYD and install the runtime deps
# our code needs (zlib + logging from micropython-lib).
#
# Usage:
#   ./scripts/flash.sh [PORT]
#
# Defaults to /dev/tty.usbserial-3110. By default this flashes the tested
# LVGL-enabled CYD image. Set MP_FIRMWARE_FLAVOR=stock to use upstream stock
# MicroPython, or set MP_FIRMWARE to use a specific local file.

set -euo pipefail

PORT="${1:-/dev/tty.usbserial-3110}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$REPO_ROOT/firmware/cache"

DEFAULT_FW_FLAVOR="${MP_FIRMWARE_FLAVOR:-lvgl}"
case "$DEFAULT_FW_FLAVOR" in
    lvgl)
        DEFAULT_FW_URL="https://raw.githubusercontent.com/de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL/main/lvgl9_firmwares/lvgl_micropy_ESP32_GENERIC-4.bin"
        DEFAULT_FW_NAME="lvgl_micropy_ESP32_GENERIC-4.bin"
        ;;
    stock)
        DEFAULT_FW_URL="https://micropython.org/resources/firmware/ESP32_GENERIC-20250911-v1.26.1.bin"
        DEFAULT_FW_NAME="ESP32_GENERIC-20250911-v1.26.1.bin"
        ;;
    *)
        echo "error: unsupported MP_FIRMWARE_FLAVOR '$DEFAULT_FW_FLAVOR' (use 'lvgl' or 'stock')" >&2
        exit 1
        ;;
esac

if [ -n "${MP_FIRMWARE:-}" ]; then
    FW_PATH="$MP_FIRMWARE"
    FW_URL="${MP_FIRMWARE_URL:-}"
else
    FW_PATH="$CACHE/$DEFAULT_FW_NAME"
    FW_URL="$DEFAULT_FW_URL"
fi

if [ ! -f "$FW_PATH" ]; then
    if [ -z "${FW_URL:-}" ]; then
        echo "error: firmware file not found at $FW_PATH" >&2
        echo "set MP_FIRMWARE_URL to download it automatically, or place the file there first" >&2
        exit 1
    fi
    echo "downloading firmware to $FW_PATH"
    mkdir -p "$CACHE"
    curl -fsSL -o "$FW_PATH" "$FW_URL"
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
