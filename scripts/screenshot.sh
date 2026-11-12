#!/usr/bin/env bash
set -euo pipefail

SCREENSHOT_DIR="$HOME/Pictures/Screenshots"
RETENTION_SECONDS=$((10 * 24 * 3600))

prune_expired() {
    mkdir -p "$SCREENSHOT_DIR"
    python3 - "$SCREENSHOT_DIR" "$RETENTION_SECONDS" <<'PY'
import os
import sys
import time

target_dir = sys.argv[1]
ttl = float(sys.argv[2])
now = time.time()

for name in os.listdir(target_dir):
    path = os.path.join(target_dir, name)
    if not os.path.isfile(path) or os.path.islink(path):
        continue
    try:
        if (now - os.stat(path).st_mtime) >= ttl:
            os.unlink(path)
    except OSError:
        pass
PY
}

mode="${1:-area}"

case "$mode" in
    --prune|prune)
        prune_expired
        exit 0
        ;;
    area)
        mkdir -p "$SCREENSHOT_DIR"
        geom="$(slurp 2>/dev/null)" || exit 0
        [ -n "$geom" ] || exit 0
        out="$SCREENSHOT_DIR/screenshot_$(date +%Y-%m-%d_%H-%M-%S).png"
        grim -g "$geom" - | tee "$out" | wl-copy
        prune_expired
        notify-send -a "Screenshot" -i "$out" -t 2000 "Screenshot Saved" "$out" >/dev/null 2>&1 || true
        ;;
    full)
        mkdir -p "$SCREENSHOT_DIR"
        out="$SCREENSHOT_DIR/screenshot_$(date +%Y-%m-%d_%H-%M-%S).png"
        grim - | tee "$out" | wl-copy
        prune_expired
        notify-send -a "Screenshot" -i "$out" -t 2000 "Screenshot Saved" "$out" >/dev/null 2>&1 || true
        ;;
    *)
        echo "Usage: $0 [area|full|--prune]" >&2
        exit 1
        ;;
esac

