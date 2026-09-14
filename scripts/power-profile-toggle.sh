#!/usr/bin/env bash

# Toggle Eco Mode (power-saver) on click
# If already in power-saver, toggles back to balanced

set -u

# Check current active profile
current=$(busctl get-property net.hadess.PowerProfiles /net/hadess/PowerProfiles net.hadess.PowerProfiles ActiveProfile 2>/dev/null | awk '{print $2}' | tr -d '"' || echo "")

if [ -z "$current" ] && [ -f /sys/firmware/acpi/platform_profile ]; then
    sys_prof=$(cat /sys/firmware/acpi/platform_profile 2>/dev/null || echo "")
    if [ "$sys_prof" = "low-power" ] || [ "$sys_prof" = "power-saver" ]; then
        current="power-saver"
    else
        current="$sys_prof"
    fi
fi

if [ "$current" = "power-saver" ]; then
    target="balanced"
else
    target="power-saver"
fi

# Apply profile change and signal Waybar upon completion
(
    busctl set-property net.hadess.PowerProfiles /net/hadess/PowerProfiles net.hadess.PowerProfiles ActiveProfile s "$target" >/dev/null 2>&1 || \
    powerprofilesctl set "$target" >/dev/null 2>&1
    
    pkill -RTMIN+8 waybar 2>/dev/null || true
) &
