#!/usr/bin/env bash
# Native code references the pinned Klipper submodule in place; no generated
# Python copies are required anymore. Keep this command as a harmless check for
# existing developer muscle memory.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -d "$REPO_ROOT/vendor/klipper/.git" ] && \
   [ ! -f "$REPO_ROOT/vendor/klipper/.git" ]; then
    echo "error: vendor/klipper is missing; run git submodule update --init" >&2
    exit 1
fi

echo "native build uses vendor/klipper in place; nothing to sync"
