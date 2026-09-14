#!/usr/bin/env bash

# Launch Waybar based on saved mode state (fixed vs autohide)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
STATE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/waybar-mode"

CURRENT_MODE="fixed"
if [ -f "$STATE_FILE" ]; then
    CURRENT_MODE=$(cat "$STATE_FILE")
fi

pkill -x waybar
sleep 0.2

if [ "$CURRENT_MODE" = "autohide" ]; then
    setsid -f waybar -c "$CONFIG_DIR/config-autohide.jsonc" -s "$CONFIG_DIR/style-autohide.css" >/dev/null 2>&1
else
    setsid -f waybar -c "$CONFIG_DIR/config.jsonc" -s "$CONFIG_DIR/style.css" >/dev/null 2>&1
fi
