#!/usr/bin/env bash
# Run portable protocol tests and the ESP-IDF cross-build.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
./scripts/test-native.sh
pio run -e cyd
