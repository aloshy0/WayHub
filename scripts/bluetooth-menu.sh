#!/usr/bin/env bash

# Bluetooth Menu using Wofi and bluetoothctl
# Designed for clean integration with Waybar

set -u

# Check if bluetoothctl is available
if ! command -v bluetoothctl >/dev/null 2>&1; then
    notify-send "Bluetooth Menu" "bluetoothctl is not installed." -i bluetooth
    exit 1
fi

# Check if Bluetooth service is active
if ! systemctl is-active --quiet bluetooth; then
    notify-send "Bluetooth Menu" "Bluetooth system service is not running." -i bluetooth
    exit 1
fi

# Helper function to run commands in a single bluetoothctl session
run_btctl() {
    printf "%b\n" "$@" | bluetoothctl >/dev/null 2>&1
}

# Scan for nearby devices
scan_devices() {
    notify-send "Bluetooth" "Refreshing Bluetooth device list..." -i bluetooth

    # Start scan in background
    bluetoothctl scan on >/dev/null 2>&1 &
    local scan_pid=$!

    # Clean up scan on script termination/exit
    trap 'kill "$scan_pid" 2>/dev/null; bluetoothctl scan off >/dev/null 2>&1' EXIT INT TERM

    # Scan for 5 seconds
    sleep 5

    # Terminate background scan
    kill "$scan_pid" 2>/dev/null || true
    bluetoothctl scan off >/dev/null 2>&1 || true

    notify-send "Bluetooth" "Device list refreshed." -i bluetooth
}

# Fetch controller state
controller_info=$(bluetoothctl show 2>/dev/null)
if [ -z "$controller_info" ]; then
    notify-send "Bluetooth Menu" "No Bluetooth controller found." -i bluetooth
    exit 1
fi

power_status=$(echo "$controller_info" | grep "Powered:" | awk '{print $2}')

if [ "$power_status" = "no" ]; then
    chosen=$(printf "󰂯  Enable Bluetooth\n" | wofi --dmenu --prompt "Bluetooth (Disabled)" --width 420 --height 120)
    if [ "$chosen" = "󰂯  Enable Bluetooth" ]; then
        bluetoothctl power on >/dev/null 2>&1
        notify-send "Bluetooth" "Bluetooth enabled" -i bluetooth
        sleep 1
        exec "$0"
    fi
    exit 0
fi

# Bluetooth is powered on
discoverable_status=$(echo "$controller_info" | grep "Discoverable:" | awk '{print $2}')

# Start a quick scan to discover nearby devices automatically
notify-send "Bluetooth" "Scanning for nearby devices..." -i bluetooth -t 1500
bluetoothctl scan on >/dev/null 2>&1 &
scan_pid=$!
sleep 1.5
kill "$scan_pid" 2>/dev/null || true
bluetoothctl scan off >/dev/null 2>&1 || true

# Load devices
device_list=$(bluetoothctl devices 2>/dev/null)

declare -A mac_map
declare -A dev_state

connected_lines=""
paired_lines=""
available_lines=""

# Loop through found/known devices
while IFS= read -r dev; do
    [ -z "$dev" ] && continue

    # Parse Device MAC Name
    mac=$(echo "$dev" | awk '{print $2}')
    name=$(echo "$dev" | cut -d' ' -f3-)
    [ -z "$name" ] && name="$mac"

    # Get device info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    [ -z "$info" ] && continue

    connected=$(echo "$info" | grep -q "Connected: yes" && echo yes || echo no)
    paired=$(echo "$info" | grep -q "Paired: yes" && echo yes || echo no)
    trusted=$(echo "$info" | grep -q "Trusted: yes" && echo yes || echo no)

    if [ "$connected" = "yes" ]; then
        display_line="●  $name   Connected"
        connected_lines+="$display_line"$'\n'
        mac_map["$display_line"]="$mac"
        dev_state["$mac"]="connected|paired|$trusted|$name"
    elif [ "$paired" = "yes" ]; then
        display_line="◆  $name"
        paired_lines+="$display_line"$'\n'
        mac_map["$display_line"]="$mac"
        dev_state["$mac"]="disconnected|paired|$trusted|$name"
    else
        display_line="○  $name"
        available_lines+="$display_line"$'\n'
        mac_map["$display_line"]="$mac"
        dev_state["$mac"]="disconnected|unpaired|$trusted|$name"
    fi
done <<< "$device_list"

# Construct menu options
menu_content="󰂲  Disable Bluetooth"$'\n'

if [ "$discoverable_status" = "yes" ]; then
    menu_content+="󰚦  Disable Discoverability (Currently: On)"$'\n'
else
    menu_content+="󰂰  Enable Discoverability (Currently: Off)"$'\n'
fi

menu_content+="󰂰  Refresh Devices"$'\n'

if [ -n "$connected_lines" ]; then
    menu_content+="CONNECTED"$'\n'
    menu_content+="$connected_lines"$'\n'
fi

if [ "$paired_lines" != "" ]; then
    menu_content+="PREVIOUSLY CONNECTED DEVICES"$'\n'
    menu_content+="$paired_lines"$'\n'
fi

if [ -n "$available_lines" ]; then
    menu_content+="AVAILABLE DEVICES"$'\n'
    menu_content+="$available_lines"
fi

# Show main menu
chosen=$(wofi --dmenu --prompt "Bluetooth" --width 420 --height 500 <<< "$menu_content")
[ -z "$chosen" ] && exit 0

# Handle static actions
case "$chosen" in
    "󰂲  Disable Bluetooth")
        bluetoothctl power off >/dev/null 2>&1
        notify-send "Bluetooth" "Bluetooth disabled" -i bluetooth
        exit 0
        ;;
    "󰚦  Disable Discoverability (Currently: On)")
        bluetoothctl discoverable off >/dev/null 2>&1
        notify-send "Bluetooth" "Discoverability disabled" -i bluetooth
        exit 0
        ;;
    "󰂰  Enable Discoverability (Currently: Off)")
        bluetoothctl discoverable on >/dev/null 2>&1
        notify-send "Bluetooth" "Discoverability enabled" -i bluetooth
        exit 0
        ;;
    "󰂰  Refresh Devices")
        scan_devices
        # Re-run menu script to show newly scanned devices
        exec "$0"
        ;;
    "CONNECTED"|"PREVIOUSLY CONNECTED DEVICES"|"AVAILABLE DEVICES")
        exit 0
        ;;
esac

# Retrieve MAC address for selected device
mac="${mac_map["$chosen"]:-}"
[ -z "$mac" ] && exit 0

# Parse device state attributes
IFS='|' read -r conn paired trusted name <<< "${dev_state["$mac"]}"

# Device action submenu
action_prompt="$name"
action_menu=""

if [ "$conn" = "connected" ]; then
    action_menu+="󰂲  Disconnect"$'\n'
else
    action_menu+="󰂰  Connect"$'\n'
fi

if [ "$paired" = "unpaired" ]; then
    action_menu+="󰌆  Pair"$'\n'
fi

if [ "$trusted" = "yes" ]; then
    action_menu+="󰌆  Untrust Device"$'\n'
else
    action_menu+="󰌆  Trust Device"$'\n'
fi

action_menu+="󰆴  Remove / Forget device"$'\n'
action_menu+="󰁍  Back"

action_chosen=$(wofi --dmenu --prompt "$action_prompt" --width 420 --height 280 <<< "$action_menu")
[ -z "$action_chosen" ] && exit 0

case "$action_chosen" in
    "󰂰  Connect")
        notify-send "Bluetooth" "Connecting to $name..." -i bluetooth
        if bluetoothctl connect "$mac" >/dev/null 2>&1; then
            notify-send "Bluetooth" "Connected to $name" -i bluetooth
        else
            notify-send "Bluetooth" "Could not connect to $name" -i bluetooth
        fi
        ;;
    "󰂲  Disconnect")
        notify-send "Bluetooth" "Disconnecting from $name..." -i bluetooth
        if bluetoothctl disconnect "$mac" >/dev/null 2>&1; then
            notify-send "Bluetooth" "Disconnected from $name" -i bluetooth
        else
            notify-send "Bluetooth" "Could not disconnect from $name" -i bluetooth
        fi
        ;;
    "󰌆  Pair")
        notify-send "Bluetooth" "Pairing with $name..." -i bluetooth
        
        # Start our custom auto-accept agent in the background
        script_dir=$(dirname "$0")
        python3 "$script_dir/bt-agent.py" >/dev/null 2>&1 &
        agent_pid=$!
        sleep 0.5

        # Trust first to facilitate the connection
        bluetoothctl trust "$mac" >/dev/null 2>&1

        # Attempt pairing (which will query the running agent for confirmations)
        if bluetoothctl pair "$mac" >/dev/null 2>&1; then
            notify-send "Bluetooth" "$name paired successfully" -i bluetooth
            bluetoothctl connect "$mac" >/dev/null 2>&1 || true
        else
            # Try connecting directly in case it succeeded but pair command exited with non-zero
            if bluetoothctl connect "$mac" >/dev/null 2>&1; then
                notify-send "Bluetooth" "$name connected successfully" -i bluetooth
            else
                notify-send "Bluetooth" "Pairing failed for $name" -i bluetooth
                # Untrust if pairing failed
                bluetoothctl untrust "$mac" >/dev/null 2>&1 || true
            fi
        fi

        # Clean up the background agent
        kill "$agent_pid" 2>/dev/null || true
        wait "$agent_pid" 2>/dev/null || true
        ;;
    "󰌆  Trust Device")
        if bluetoothctl trust "$mac" >/dev/null 2>&1; then
            notify-send "Bluetooth" "$name is now trusted" -i bluetooth
        fi
        ;;
    "󰌆  Untrust Device")
        if bluetoothctl untrust "$mac" >/dev/null 2>&1; then
            notify-send "Bluetooth" "$name is no longer trusted" -i bluetooth
        fi
        ;;
    "󰆴  Remove / Forget device")
        confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $name?" --width 420 --height 150)
        if [ "$confirm" = "Yes" ]; then
            bluetoothctl disconnect "$mac" >/dev/null 2>&1 || true
            if bluetoothctl remove "$mac" >/dev/null 2>&1; then
                notify-send "Bluetooth" "Removed device $name" -i bluetooth
            else
                notify-send "Bluetooth" "Failed to remove device" -i bluetooth
            fi
        fi
        ;;
    "󰁍  Back")
        exec "$0"
        ;;
esac
