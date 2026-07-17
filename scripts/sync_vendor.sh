#!/usr/bin/env bash
# Verify that the pinned Klipper submodule is available. Native sources use it
# in place, so there is nothing to generate or copy.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -d "$REPO_ROOT/vendor/klipper/.git" ] && \
   [ ! -f "$REPO_ROOT/vendor/klipper/.git" ]; then
    echo "error: vendor/klipper is missing; run git submodule update --init" >&2
    exit 1
fi

echo "native build uses vendor/klipper in place; nothing to sync"
