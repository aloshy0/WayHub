#!/usr/bin/env bash

# Toggle Waybar visibility on/off manually (no autohide on hover)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"

# Stop autohide daemon if running so it won't auto-reveal on edge hover
pkill -f "autohide-daemon.py" 2>/dev/null || true

# If waybar isn't running, launch it; otherwise send SIGUSR1 to toggle hide/show
if ! pgrep -x waybar >/dev/null 2>&1; then
    if [ -f "$CONFIG_DIR/launch.sh" ]; then
        setsid -f "$CONFIG_DIR/launch.sh" >/dev/null 2>&1
    else
        setsid -f "$(dirname "$(readlink -f "$0")")/launch.sh" >/dev/null 2>&1
    fi
else
    pkill -SIGUSR1 -x waybar 2>/dev/null || killall -SIGUSR1 waybar 2>/dev/null
fi
