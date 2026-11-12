#!/usr/bin/env bash

# Toggle Eco Mode (power-saver) <-> balanced and sync display refresh rate
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/battery.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/battery.py" --toggle-eco
elif [ -f "$HOME/.config/waybar/battery.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/battery.py" --toggle-eco
fi
