#!/usr/bin/env bash

# Wi-Fi Menu using Wofi and nmcli
# Designed for clean integration with Waybar

set -u

# Check if NetworkManager is running
if ! nmcli general status >/dev/null 2>&1; then
    notify-send "Wi-Fi Menu" "NetworkManager is not running." -i network-wireless
    exit 1
fi

# Find a Wi-Fi device
wifi_device=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2 == "wifi" {print $1; exit}')
if [ -z "$wifi_device" ]; then
    notify-send "Wi-Fi Menu" "No Wi-Fi adapter found." -i network-wireless
    exit 1
fi

# Function to manage saved networks
show_saved_networks() {
    local saved_connections
    saved_connections=$(nmcli -t -f NAME,TYPE connection show | awk -F: '$2 == "802-11-wireless" {print $1}')

    if [ -z "$saved_connections" ]; then
        wofi --dmenu --prompt "Saved Networks" --width 420 --height 120 <<< "No saved networks" >/dev/null
        return
    fi

    declare -A conn_map
    local menu_content=""

    while IFS= read -r conn; do
        [ -z "$conn" ] && continue
        local display_line="󰌆  $conn"
        conn_map["$display_line"]="$conn"
        menu_content+="$display_line"$'\n'
    done <<< "$saved_connections"

    local chosen
    chosen=$(wofi --dmenu --prompt "Saved Networks" --width 420 --height 400 <<< "$menu_content")
    [ -z "$chosen" ] && return

    local connection_name="${conn_map["$chosen"]:-}"
    [ -z "$connection_name" ] && return

    local action
    action=$(printf "%s\n" \
        "󰤨  Connect" \
        "󰌆  Show Password" \
        "󰏫  Edit Password" \
        "󰆴  Forget Network" \
        "󰁍  Back" | wofi --dmenu --prompt "$connection_name" --width 420 --height 300)

    case "$action" in
        "󰤨  Connect")
            notify-send "Wi-Fi" "Connecting to $connection_name..." -i network-wireless
            if nmcli connection up "$connection_name" >/dev/null 2>&1; then
                notify-send "Wi-Fi" "Connected to $connection_name" -i network-wireless
            else
                notify-send "Wi-Fi" "Failed to connect to $connection_name" -i network-wireless-error
            fi
            ;;
        "󰌆  Show Password")
            local password
            password=$(nmcli --show-secrets -g 802-11-wireless-security.psk connection show "$connection_name" 2>/dev/null)
            if [ -z "$password" ]; then
                password=$(nmcli --show-secrets -g 802-11-wireless-security.wep-key0 connection show "$connection_name" 2>/dev/null)
            fi

            if [ -n "$password" ]; then
                wofi --dmenu --prompt "Password" --width 420 --height 120 <<< "$password" >/dev/null
            else
                wofi --dmenu --prompt "Error" --width 420 --height 120 <<< "No password stored" >/dev/null
            fi
            ;;
        "󰏫  Edit Password")
            local new_password
            new_password=$(wofi --dmenu --password --prompt "New Password" --width 420 --height 120)
            [ -z "$new_password" ] && return

            if nmcli connection modify "$connection_name" 802-11-wireless-security.psk "$new_password" 2>/dev/null; then
                notify-send "Wi-Fi" "Password updated. Reconnecting..." -i network-wireless
                nmcli connection down "$connection_name" >/dev/null 2>&1 || true
                if nmcli connection up "$connection_name" >/dev/null 2>&1; then
                    notify-send "Wi-Fi" "Connected to $connection_name" -i network-wireless
                else
                    notify-send "Wi-Fi" "Failed to reconnect to $connection_name" -i network-wireless-error
                fi
            else
                notify-send "Wi-Fi" "Failed to update password" -i network-wireless-error
            fi
            ;;
        "󰆴  Forget Network")
            local confirm
            confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $connection_name?" --width 420 --height 150)
            if [ "$confirm" = "Yes" ]; then
                if nmcli connection delete "$connection_name" >/dev/null 2>&1; then
                    notify-send "Wi-Fi" "Forgot network $connection_name" -i network-wireless
                else
                    notify-send "Wi-Fi" "Failed to forget network" -i network-wireless-error
                fi
            fi
            ;;
        "󰁍  Back")
            show_saved_networks
            ;;
    esac
}

# Check Wi-Fi power state
wifi_state=$(nmcli radio wifi)

if [ "$wifi_state" = "disabled" ]; then
    chosen=$(printf "󰤮  Enable Wi-Fi\n󰌆  SAVED NETWORKS\n" | wofi --dmenu --prompt "Wi-Fi (Disabled)" --width 420 --height 180)
    case "$chosen" in
        "󰤮  Enable Wi-Fi")
            nmcli radio wifi on
            notify-send "Wi-Fi" "Wi-Fi enabled" -i network-wireless
            ;;
        "󰌆  SAVED NETWORKS")
            show_saved_networks
            ;;
    esac
    exit 0
fi

# Wi-Fi is enabled. Gather current connections and scan results.
saved_list=$(nmcli -t -f NAME,TYPE connection show | awk -F: '$2 == "802-11-wireless" {print $1}')

# Fetch scan results in multiline mode to parse SSID safely
wifi_list_output=$(nmcli -m multiline -f ACTIVE,SSID,SIGNAL,SECURITY device wifi list 2>/dev/null)

declare -A ssid_map
declare -A ssid_signal
declare -A ssid_security
declare -A ssid_active

active=""
ssid=""
signal=""
security=""

# Parse multiline output
while IFS= read -r line; do
    if [[ "$line" =~ ^ACTIVE:[[:space:]]*(.*) ]]; then
        active=$(echo "${BASH_REMATCH[1]}" | xargs)
    elif [[ "$line" =~ ^SSID:[[:space:]]*(.*) ]]; then
        ssid="${BASH_REMATCH[1]}" # keep exact trailing spaces/colons
    elif [[ "$line" =~ ^SIGNAL:[[:space:]]*(.*) ]]; then
        signal=$(echo "${BASH_REMATCH[1]}" | xargs)
    elif [[ "$line" =~ ^SECURITY:[[:space:]]*(.*) ]]; then
        security=$(echo "${BASH_REMATCH[1]}" | xargs)

        # Process the completed record block
        if [ -n "$ssid" ] && [ "$ssid" != "--" ]; then
            existing_sig="${ssid_signal["$ssid"]:-0}"
            if [ -z "$existing_sig" ] || [ "$signal" -ge "$existing_sig" ] || [ "$active" = "yes" ]; then
                ssid_signal["$ssid"]="$signal"
                ssid_security["$ssid"]="$security"
                ssid_active["$ssid"]="$active"
            fi
        fi
        active=""
        ssid=""
        signal=""
        security=""
    fi
done <<< "$wifi_list_output"

connected_line=""
available_lines=""

# Sort SSIDs by signal strength
sorted_ssids=$(for s in "${!ssid_signal[@]}"; do
    echo "${ssid_signal[$s]}|$s"
done | sort -rn | cut -d'|' -f2-)

while IFS= read -r ssid; do
    [ -z "$ssid" ] && continue

    signal="${ssid_signal["$ssid"]}"
    security="${ssid_security["$ssid"]}"
    active="${ssid_active["$ssid"]}"

    # Select signal icon
    if [ "$signal" -ge 75 ]; then
        icon="󰤨"
    elif [ "$signal" -ge 40 ]; then
        icon="󰤥"
    else
        icon="󰤟"
    fi

    if [ "$active" = "yes" ]; then
        connected_line="$icon  $ssid   Connected"
        ssid_map["$connected_line"]="$ssid"
    else
        # Filter out saved connections from available list to prevent clutter
        is_saved=false
        while IFS= read -r saved_name; do
            if [ "$saved_name" = "$ssid" ]; then
                is_saved=true
                break
            fi
        done <<< "$saved_list"

        if [ "$is_saved" = "false" ]; then
            display_line="$icon  $ssid  [$signal%]"
            available_lines+="$display_line"$'\n'
            ssid_map["$display_line"]="$ssid"
        fi
    fi
done <<< "$sorted_ssids"

# Build main menu contents
menu_content="󰂲  Disable Wi-Fi"$'\n'

if [ -n "$connected_line" ]; then
    menu_content+="CONNECTED"$'\n'
    menu_content+="$connected_line"$'\n'$'\n'
fi

if [ -n "$available_lines" ]; then
    menu_content+="AVAILABLE NETWORKS"$'\n'
    menu_content+="$available_lines"
fi

menu_content+="────────────────────────"$'\n'
menu_content+="󰌆  SAVED NETWORKS"

# Show main menu
chosen=$(wofi --dmenu --prompt "Wi-Fi" --width 420 --height 500 <<< "$menu_content")
[ -z "$chosen" ] && exit 0

# Handle static actions
if [ "$chosen" = "󰂲  Disable Wi-Fi" ]; then
    nmcli radio wifi off
    notify-send "Wi-Fi" "Wi-Fi disabled" -i network-wireless
    exit 0
elif [ "$chosen" = "󰌆  SAVED NETWORKS" ]; then
    show_saved_networks
    exit 0
elif [ "$chosen" = "CONNECTED" ] || [ "$chosen" = "AVAILABLE NETWORKS" ] || [ "$chosen" = "────────────────────────" ]; then
    exit 0
fi

# Get original SSID from map
ssid="${ssid_map["$chosen"]:-}"
[ -z "$ssid" ] && exit 0

# If selected connected network, offer management options
if [ "$chosen" = "$connected_line" ]; then
    action=$(printf "Disconnect\nForget Network\nBack\n" | wofi --dmenu --prompt "$ssid" --width 420 --height 220)
    case "$action" in
        "Disconnect")
            notify-send "Wi-Fi" "Disconnecting from $ssid..." -i network-wireless
            nmcli device disconnect "$wifi_device" >/dev/null 2>&1
            ;;
        "Forget Network")
            confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $ssid?" --width 420 --height 150)
            if [ "$confirm" = "Yes" ]; then
                if nmcli connection delete "$ssid" >/dev/null 2>&1; then
                    notify-send "Wi-Fi" "Forgot network $ssid" -i network-wireless
                else
                    notify-send "Wi-Fi" "Failed to forget network" -i network-wireless-error
                fi
            fi
            ;;
    esac
    exit 0
fi

# Connect to new network
security="${ssid_security["$ssid"]:-}"

if [ -n "$security" ] && [ "$security" != "--" ]; then
    password=$(wofi --dmenu --password --prompt "Password" --width 420 --height 120)
    [ -z "$password" ] && exit 0

    notify-send "Wi-Fi" "Connecting to $ssid..." -i network-wireless
    if nmcli device wifi connect "$ssid" password "$password" >/dev/null 2>&1; then
        notify-send "Wi-Fi" "Connected to $ssid" -i network-wireless
    else
        notify-send "Wi-Fi" "Failed to connect to $ssid" -i network-wireless-error
    fi
else
    notify-send "Wi-Fi" "Connecting to open network $ssid..." -i network-wireless
    if nmcli device wifi connect "$ssid" >/dev/null 2>&1; then
        notify-send "Wi-Fi" "Connected to $ssid" -i network-wireless
    else
        notify-send "Wi-Fi" "Failed to connect to $ssid" -i network-wireless-error
    fi
fi
