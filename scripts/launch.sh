#!/usr/bin/env bash

# Launch Waybar in standard mode (exclusive top space reservation)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"

# Ensure Bluetooth is powered off by default on startup
bluetoothctl power off >/dev/null 2>&1 &

# Stop any running autohide daemon and waybar
pkill -f "autohide-daemon.py" 2>/dev/null || true
pkill -x waybar 2>/dev/null || true
sleep 0.2

if [ -f "$CONFIG_DIR/config.jsonc" ]; then
    nohup waybar -c "$CONFIG_DIR/config.jsonc" -s "$CONFIG_DIR/style.css" >/dev/null 2>&1 &
else
    DIR="$(dirname "$(readlink -f "$0")")"
    nohup waybar -c "$DIR/../waybar/config.jsonc" -s "$DIR/../waybar/style.css" >/dev/null 2>&1 &
fi

