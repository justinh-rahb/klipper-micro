#!/usr/bin/env bash
# Copy the upstream Klipper files we use as-is (or with thin adapters) from
# vendor/klipper into src/proto/. Run after `git submodule update`.
#
# The destination files are gitignored — the submodule pin in .gitmodules is
# the source of truth for which Klipper revision we're tracking.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$REPO_ROOT/vendor/klipper/klippy"
DEST="$REPO_ROOT/src/proto"

if [ ! -d "$VENDOR" ]; then
    echo "error: vendor/klipper not found — run 'git submodule update --init'" >&2
    exit 1
fi

mkdir -p "$DEST"

# msgproto.py is used verbatim — pure Python, runs on MicroPython.
cp "$VENDOR/msgproto.py" "$DEST/msgproto.py"

# clocksync.py is wrapped by our adapter in src/proto/clocksync.py. We copy it
# under a _vendor_ prefix so the adapter can import the regression math
# without touching upstream.
cp "$VENDOR/clocksync.py" "$DEST/_vendor_clocksync.py"

echo "synced from $(git -C "$REPO_ROOT/vendor/klipper" rev-parse --short HEAD)"
