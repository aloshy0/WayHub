#!/usr/bin/env bash

# Check if Python GTK3 Audio & Brightness popup is available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/audio-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/audio-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/audio-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/audio-menu.py" "$@"
fi

# Fallback: pavucontrol or toggle mute
if command -v pavucontrol >/dev/null 2>&1; then
    pavucontrol &
else
    wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
fi
