#!/usr/bin/env bash

# Toggle between Fixed and Autohide Waybar modes
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
STATE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/waybar-mode"
mkdir -p "$(dirname "$STATE_FILE")"

CURRENT_MODE="fixed"
if [ -f "$STATE_FILE" ]; then
    CURRENT_MODE=$(cat "$STATE_FILE")
fi

if [ "$CURRENT_MODE" = "fixed" ]; then
    echo "autohide" > "$STATE_FILE"
    pkill -x waybar
    sleep 0.2
    setsid -f waybar -c "$CONFIG_DIR/config-autohide.jsonc" -s "$CONFIG_DIR/style-autohide.css" >/dev/null 2>&1
    notify-send -a "Waybar" -i "preferences-desktop-display" "Waybar: Autohide Mode" "Hover near top edge to reveal bar"
else
    echo "fixed" > "$STATE_FILE"
    pkill -x waybar
    sleep 0.2
    setsid -f waybar -c "$CONFIG_DIR/config.jsonc" -s "$CONFIG_DIR/style.css" >/dev/null 2>&1
    notify-send -a "Waybar" -i "preferences-desktop-display" "Waybar: Fixed Mode" "Bar docked to top"
fi
