#!/usr/bin/env bash

# Launch Python GTK3 Clipboard History popup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/clipboard-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/clipboard-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/clipboard-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/clipboard-menu.py" "$@"
fi

