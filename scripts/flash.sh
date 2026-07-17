#!/usr/bin/env bash
# Build and flash the native ESP-IDF image with PlatformIO.

set -euo pipefail

PORT="${1:-/dev/tty.usbserial-3110}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"
exec pio run -e cyd -t upload --upload-port "$PORT"
