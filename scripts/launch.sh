#!/usr/bin/env bash

# Launch Waybar based on saved mode state (fixed vs autohide)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
STATE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/waybar-mode"

CURRENT_MODE="fixed"
if [ -f "$STATE_FILE" ]; then
    CURRENT_MODE=$(cat "$STATE_FILE")
fi

# Ensure Bluetooth is powered off by default on startup
bluetoothctl power off >/dev/null 2>&1 &

# Stop any running autohide daemon and waybar
pkill -f "autohide-daemon.py" 2>/dev/null || true
pkill -x waybar 2>/dev/null || true
sleep 0.2

if [ "$CURRENT_MODE" = "autohide" ]; then
    nohup waybar -c "$CONFIG_DIR/config-autohide.jsonc" -s "$CONFIG_DIR/style-autohide.css" >/dev/null 2>&1 &
    DAEMON_SCRIPT="$CONFIG_DIR/autohide-daemon.py"
    if [ -f "$DAEMON_SCRIPT" ]; then
        nohup python3 "$DAEMON_SCRIPT" >/dev/null 2>&1 &
    fi
else
    nohup waybar -c "$CONFIG_DIR/config.jsonc" -s "$CONFIG_DIR/style.css" >/dev/null 2>&1 &
fi

