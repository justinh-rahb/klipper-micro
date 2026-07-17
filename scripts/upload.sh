#!/usr/bin/env bash
# Compatibility alias: native firmware is compiled and flashed as one image.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$REPO_ROOT/scripts/flash.sh" "${1:-/dev/tty.usbserial-3110}"
