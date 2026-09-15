#!/usr/bin/env bash
set -u

# Check if Python GTK3 Bluetooth popup is available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/bluetooth-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/bluetooth-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/bluetooth-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/bluetooth-menu.py" "$@"
fi

# Fallback Bluetooth Menu using Wofi and bluetoothctl

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

# Notification helper using Dunst stack tagging for clean replacement
bt_notify() {
    local text="$1"
    local urgency="${2:-normal}" # normal, low, critical
    local timeout="${3:-3500}"
    local icon="bluetooth"
    [ "$urgency" = "critical" ] && icon="dialog-error"
    notify-send -a "Bluetooth" -u "$urgency" -i "$icon" -t "$timeout" -h string:x-dunst-stack-tag:bluetooth "Bluetooth" "$text"
}

# Helper function to scan for nearby devices reliably
scan_devices() {
    bt_notify "Scanning for nearby devices (8s)..." normal 3000
    bluetoothctl pairable on </dev/null >/dev/null 2>&1 || true
    bluetoothctl discoverable on </dev/null >/dev/null 2>&1 || true
    bluetoothctl --timeout 8 scan on </dev/null >/dev/null 2>&1 || true
    bt_notify "Scan complete. Device list refreshed." normal 2500
}

# Connect helper verifying actual connection state
bt_connect() {
    local mac="$1"
    local name="$2"
    bt_notify "Connecting to $name..." normal 6000

    local out
    out=$(bluetoothctl --timeout 10 connect "$mac" </dev/null 2>&1)
    
    local info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    if echo "$info" | grep -q "Connected: yes"; then
        bt_notify "Connected to $name" normal 3000
    else
        local reason
        reason=$(echo "$out" | grep -iE "failed|error|not available|refused|timeout|abort" | head -n 1)
        [ -z "$reason" ] && reason="Connection failed (device unreachable or off)"
        bt_notify "Could not connect to $name ($reason)" critical 4500
    fi
}

# Disconnect helper
bt_disconnect() {
    local mac="$1"
    local name="$2"
    bt_notify "Disconnecting from $name..." normal 3000

    bluetoothctl --timeout 5 disconnect "$mac" </dev/null >/dev/null 2>&1
    local info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    if ! echo "$info" | grep -q "Connected: yes"; then
        bt_notify "Disconnected from $name" normal 3000
    else
        bt_notify "Failed to disconnect from $name" critical 4000
    fi
}

# Pair helper with auto-accept agent and connection handshake
bt_pair() {
    local mac="$1"
    local name="$2"
    bt_notify "Pairing with $name..." normal 12000
    
    # Start auto-accept agent in background
    local script_dir
    script_dir=$(dirname "$0")
    local agent_pid=""
    if [ -f "$script_dir/bt-agent.py" ]; then
        python3 "$script_dir/bt-agent.py" </dev/null >/dev/null 2>&1 &
        agent_pid=$!
        sleep 0.5
    fi

    # Trust first to streamline connection
    bluetoothctl trust "$mac" </dev/null >/dev/null 2>&1 || true

    local pair_out
    pair_out=$(bluetoothctl --timeout 15 pair "$mac" </dev/null 2>&1)
    
    local info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    local is_paired
    is_paired=$(echo "$info" | grep -q "Paired: yes" && echo yes || echo no)

    if [ "$is_paired" = "yes" ]; then
        bt_notify "$name paired! Connecting..." normal 4000
        # Allow audio / input services a brief moment to register
        sleep 0.8
        bluetoothctl --timeout 10 connect "$mac" </dev/null >/dev/null 2>&1
        info=$(bluetoothctl info "$mac" 2>/dev/null)
        if echo "$info" | grep -q "Connected: yes"; then
            bt_notify "$name paired and connected successfully!" normal 3500
        else
            bt_notify "$name paired successfully." normal 3500
        fi
    else
        # Try direct connection in case pair returned error on already-paired state
        bluetoothctl --timeout 8 connect "$mac" </dev/null >/dev/null 2>&1
        info=$(bluetoothctl info "$mac" 2>/dev/null)
        if echo "$info" | grep -q "Connected: yes"; then
            bt_notify "$name connected successfully!" normal 3500
        else
            local reason
            reason=$(echo "$pair_out" | grep -iE "failed|error|not available|canceled|timeout|refused|auth" | head -n 1)
            [ -z "$reason" ] && reason="Pairing timed out or rejected by device"
            bt_notify "Pairing failed for $name ($reason)" critical 5000
            bluetoothctl untrust "$mac" </dev/null >/dev/null 2>&1 || true
        fi
    fi

    # Clean up agent
    if [ -n "$agent_pid" ]; then
        kill "$agent_pid" 2>/dev/null || true
        wait "$agent_pid" 2>/dev/null || true
    fi
}

# Fetch controller state
controller_info=$(bluetoothctl show 2>/dev/null)
if [ -z "$controller_info" ]; then
    bt_notify "No Bluetooth controller found." critical
    exit 1
fi

power_status=$(echo "$controller_info" | grep -E "^\s*Powered:" | awk '{print $2}')

if [ "$power_status" = "no" ]; then
    chosen=$(printf "󰂯  Enable Bluetooth\n" | wofi --dmenu --prompt "Bluetooth (Disabled)" --width 420 --height 120)
    if [ "$chosen" = "󰂯  Enable Bluetooth" ]; then
        bluetoothctl power on </dev/null >/dev/null 2>&1
        bluetoothctl pairable on </dev/null >/dev/null 2>&1 || true
        bt_notify "Bluetooth enabled" normal 2500
        sleep 1
        exec "$0"
    fi
    exit 0
fi

# Ensure controller is pairable and discoverable
bluetoothctl pairable on </dev/null >/dev/null 2>&1 || true

# Bluetooth is powered on
discoverable_status=$(echo "$controller_info" | grep -E "^\s*Discoverable:" | awk '{print $2}')

# Load devices from bluetoothctl
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
    raw_name=$(echo "$dev" | cut -d' ' -f3-)

    # Get device info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    [ -z "$info" ] && continue

    alias_name=$(echo "$info" | grep -E "^\s*Alias:" | sed -e 's/^[[:space:]]*Alias:[[:space:]]*//')
    dev_name=$(echo "$info" | grep -E "^\s*Name:" | sed -e 's/^[[:space:]]*Name:[[:space:]]*//')
    
    name="${alias_name:-${dev_name:-${raw_name:-$mac}}}"

    connected=$(echo "$info" | grep -q "Connected: yes" && echo yes || echo no)
    paired=$(echo "$info" | grep -q "Paired: yes" && echo yes || echo no)
    trusted=$(echo "$info" | grep -q "Trusted: yes" && echo yes || echo no)
    icon_type=$(echo "$info" | grep -E "^\s*Icon:" | awk '{print $2}')

    case "$icon_type" in
        audio-card|audio-headset|audio-headphones)
            dev_icon="󰋋"
            ;;
        input-keyboard)
            dev_icon="󰌌"
            ;;
        input-mouse|input-gaming)
            dev_icon="󰍽"
            ;;
        phone)
            dev_icon="󰏲"
            ;;
        *)
            dev_icon="󰂰"
            ;;
    esac

    if [ "$connected" = "yes" ]; then
        display_line="●  $dev_icon  $name   Connected"
        connected_lines+="$display_line"$'\n'
        mac_map["$display_line"]="$mac"
        dev_state["$mac"]="connected|paired|$trusted|$name"
    elif [ "$paired" = "yes" ]; then
        display_line="◆  $dev_icon  $name"
        paired_lines+="$display_line"$'\n'
        mac_map["$display_line"]="$mac"
        dev_state["$mac"]="disconnected|paired|$trusted|$name"
    else
        display_line="○  $dev_icon  $name"
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

menu_content+="󰂰  Scan for Nearby Devices (8s)"$'\n'

has_any_device=0

if [ -n "$connected_lines" ]; then
    menu_content+="CONNECTED"$'\n'
    menu_content+="$connected_lines"$'\n'
    has_any_device=1
fi

if [ -n "$paired_lines" ]; then
    menu_content+="PREVIOUSLY CONNECTED DEVICES"$'\n'
    menu_content+="$paired_lines"$'\n'
    has_any_device=1
fi

if [ -n "$available_lines" ]; then
    menu_content+="AVAILABLE DEVICES"$'\n'
    menu_content+="$available_lines"$'\n'
    has_any_device=1
fi

if [ "$has_any_device" -eq 0 ]; then
    menu_content+="────────────────────────"$'\n'
    menu_content+="○  No devices found (Put device in pairing mode & click 'Scan')"$'\n'
fi

# Show main menu
chosen=$(wofi --dmenu --prompt "Bluetooth" --width 420 --height 500 <<< "$menu_content")
[ -z "$chosen" ] && exit 0

# Handle static actions
case "$chosen" in
    "󰂲  Disable Bluetooth")
        bluetoothctl power off </dev/null >/dev/null 2>&1
        bt_notify "Bluetooth disabled" normal 2000
        exit 0
        ;;
    "󰚦  Disable Discoverability (Currently: On)")
        bluetoothctl discoverable off </dev/null >/dev/null 2>&1
        bt_notify "Discoverability disabled" normal 2000
        exit 0
        ;;
    "󰂰  Enable Discoverability (Currently: Off)")
        bluetoothctl discoverable on </dev/null >/dev/null 2>&1
        bt_notify "Discoverability enabled" normal 2000
        exit 0
        ;;
    "󰂰  Scan for Nearby Devices (8s)"|"󰂰  Scan for Nearby Devices"|"󰂰  Refresh Devices")
        scan_devices
        exec "$0"
        ;;
    "CONNECTED"|"PREVIOUSLY CONNECTED DEVICES"|"AVAILABLE DEVICES"|"────────────────────────"|"○  No devices found (Put device in pairing mode & click 'Scan')")
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
        bt_connect "$mac" "$name"
        ;;
    "󰂲  Disconnect")
        bt_disconnect "$mac" "$name"
        ;;
    "󰌆  Pair")
        bt_pair "$mac" "$name"
        ;;
    "󰌆  Trust Device")
        bluetoothctl trust "$mac" </dev/null >/dev/null 2>&1
        bt_notify "$name is now trusted" normal 2500
        ;;
    "󰌆  Untrust Device")
        bluetoothctl untrust "$mac" </dev/null >/dev/null 2>&1
        bt_notify "$name is no longer trusted" normal 2500
        ;;
    "󰆴  Remove / Forget device")
        confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $name?" --width 420 --height 150)
        if [ "$confirm" = "Yes" ]; then
            bluetoothctl disconnect "$mac" </dev/null >/dev/null 2>&1 || true
            if bluetoothctl remove "$mac" </dev/null >/dev/null 2>&1; then
                bt_notify "Removed device $name" normal 2500
            else
                bt_notify "Failed to remove device" critical 3500
            fi
        fi
        ;;
    "󰁍  Back")
        exec "$0"
        ;;
esac
