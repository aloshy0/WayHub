#!/usr/bin/env bash

# Check if Python GTK3 Brightness popup is available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/brightness-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/brightness-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/brightness-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/brightness-menu.py" "$@"
fi
