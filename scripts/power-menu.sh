#!/usr/bin/env bash

# Launch Python GTK3 Power & Battery profile selector popup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/power-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/power-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/power-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/power-menu.py" "$@"
fi

