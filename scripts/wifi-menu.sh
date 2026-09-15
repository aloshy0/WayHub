#!/usr/bin/env bash

# Check if Python GTK3 Wi-Fi popup is available
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/wifi-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/wifi-menu.py" "$@"
elif [ -f "$HOME/.config/waybar/wifi-menu.py" ] && command -v python3 >/dev/null 2>&1; then
    exec python3 "$HOME/.config/waybar/wifi-menu.py" "$@"
fi

# Fallback Wi-Fi Menu using Wofi and nmcli

# Check if NetworkManager is running
if ! nmcli general status >/dev/null 2>&1; then
    wifi_notify "NetworkManager is not running." critical 5000
    exit 1
fi

# Find a Wi-Fi device
wifi_device=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2 == "wifi" {print $1; exit}')
if [ -z "$wifi_device" ]; then
    wifi_notify "No Wi-Fi adapter found." critical 5000
    exit 1
fi

# Ensure Wi-Fi adapter allows automatic connections
nmcli device set "$wifi_device" autoconnect yes >/dev/null 2>&1 || true

# Gather saved Wi-Fi connection profiles (mapping SSID -> Profile Name)
declare -A saved_conn_map

while IFS=: read -r name uuid type autoconnect; do
    if [ "$type" = "802-11-wireless" ]; then
        ssid_val=$(nmcli -g 802-11-wireless.ssid connection show "$uuid" 2>/dev/null)
        [ -z "$ssid_val" ] && ssid_val="$name"
        saved_conn_map["$ssid_val"]="$name"
    fi
done < <(nmcli -t -f NAME,UUID,TYPE,AUTOCONNECT connection show 2>/dev/null)

# Helper function to manage saved networks
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
            wifi_notify "Connecting to $connection_name..." normal 5000
            if nmcli connection up id "$connection_name" >/dev/null 2>&1 || nmcli connection up "$connection_name" >/dev/null 2>&1; then
                nmcli connection modify "$connection_name" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
                wifi_notify "Connected to $connection_name" normal 3000
            else
                wifi_notify "Failed to connect to $connection_name" critical 4000
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
                wifi_notify "Password updated. Reconnecting..." normal 4000
                nmcli connection down "$connection_name" >/dev/null 2>&1 || true
                if nmcli connection up "$connection_name" >/dev/null 2>&1; then
                    nmcli connection modify "$connection_name" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
                    wifi_notify "Connected to $connection_name" normal 3000
                else
                    wifi_notify "Failed to reconnect to $connection_name" critical 4000
                fi
            else
                wifi_notify "Failed to update password" critical 4000
            fi
            ;;
        "󰆴  Forget Network")
            local confirm
            confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $connection_name?" --width 420 --height 150)
            if [ "$confirm" = "Yes" ]; then
                if nmcli connection delete "$connection_name" >/dev/null 2>&1; then
                    wifi_notify "Forgot network $connection_name" normal 3000
                else
                    wifi_notify "Failed to forget network" critical 4000
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
    chosen=$(printf "󰤨  Turn On Wi-Fi\n󰌆  SAVED NETWORKS\n" | wofi --dmenu --prompt "Wi-Fi (Off)" --width 420 --height 180)
    case "$chosen" in
        "󰤨  Turn On Wi-Fi")
            nmcli radio wifi on
            wifi_notify "Wi-Fi turned on" normal 2500
            ;;
        "󰌆  SAVED NETWORKS")
            show_saved_networks
            ;;
    esac
    exit 0
fi

# Wi-Fi is enabled. Gather scan results (no rescan on open for fast menu response)
wifi_list_output=$(nmcli -m multiline -f ACTIVE,SSID,SIGNAL,SECURITY device wifi list --rescan no 2>/dev/null)

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
connected_ssid=""
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
        connected_ssid="$ssid"
        ssid_map["$connected_line"]="$ssid"
    else
        # Check if this SSID is already in saved connections
        if [ -n "${saved_conn_map["$ssid"]:-}" ]; then
            display_line="$icon  $ssid  [$signal%]  󰌆 Saved"
        elif [ -n "$security" ] && [ "$security" != "--" ]; then
            display_line="$icon  $ssid  [$signal%]  󰌾"
        else
            display_line="$icon  $ssid  [$signal%]"
        fi
        available_lines+="$display_line"$'\n'
        ssid_map["$display_line"]="$ssid"
    fi
done <<< "$sorted_ssids"

# Build main menu contents
menu_content="󰤮  Turn Off Wi-Fi"$'\n'
menu_content+="󰂰  Refresh Networks"$'\n'

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
if [ "$chosen" = "󰤮  Turn Off Wi-Fi" ]; then
    nmcli radio wifi off
    wifi_notify "Wi-Fi turned off" normal 2500
    exit 0
elif [ "$chosen" = "󰂰  Refresh Networks" ]; then
    wifi_notify "Refreshing network list..." normal 2500
    nmcli device wifi rescan >/dev/null 2>&1 || nmcli device wifi list --rescan yes >/dev/null 2>&1 || true
    sleep 1
    exec "$0"
elif [ "$chosen" = "󰌆  SAVED NETWORKS" ]; then
    show_saved_networks
    exit 0
elif [ "$chosen" = "CONNECTED" ] || [ "$chosen" = "AVAILABLE NETWORKS" ] || [ "$chosen" = "────────────────────────" ]; then
    exit 0
fi

# Get original SSID from map
ssid="${ssid_map["$chosen"]:-}"
[ -z "$ssid" ] && exit 0

# If selected the currently connected network, offer management options
if [ "$chosen" = "$connected_line" ]; then
    action=$(printf "󰤮  Disconnect\n󰌆  Show Password\n󰆴  Forget Network\n󰁍  Back\n" | wofi --dmenu --prompt "$ssid" --width 420 --height 240)
    case "$action" in
        "󰤮  Disconnect")
            wifi_notify "Disconnecting from $ssid..." normal 3000
            conn_name="${saved_conn_map["$ssid"]:-$ssid}"
            nmcli connection down "$conn_name" >/dev/null 2>&1 || nmcli device disconnect "$wifi_device" >/dev/null 2>&1
            # Keep device autoconnect enabled so auto-reconnect works on future connections
            nmcli device set "$wifi_device" autoconnect yes >/dev/null 2>&1 || true
            wifi_notify "Disconnected from $ssid" normal 2500
            ;;
        "󰌆  Show Password")
            conn_name="${saved_conn_map["$ssid"]:-$ssid}"
            password=$(nmcli --show-secrets -g 802-11-wireless-security.psk connection show "$conn_name" 2>/dev/null)
            if [ -z "$password" ]; then
                password=$(nmcli --show-secrets -g 802-11-wireless-security.wep-key0 connection show "$conn_name" 2>/dev/null)
            fi

            if [ -n "$password" ]; then
                wofi --dmenu --prompt "Password" --width 420 --height 120 <<< "$password" >/dev/null
            else
                wofi --dmenu --prompt "Error" --width 420 --height 120 <<< "No password stored" >/dev/null
            fi
            ;;
        "󰆴  Forget Network")
            confirm=$(printf "Yes\nNo\n" | wofi --dmenu --prompt "Forget $ssid?" --width 420 --height 150)
            if [ "$confirm" = "Yes" ]; then
                conn_name="${saved_conn_map["$ssid"]:-$ssid}"
                if nmcli connection delete "$conn_name" >/dev/null 2>&1; then
                    wifi_notify "Forgot network $ssid" normal 3000
                else
                    wifi_notify "Failed to forget network" critical 4000
                fi
            fi
            ;;
    esac
    exit 0
fi

# Connect to selected network
saved_name="${saved_conn_map["$ssid"]:-}"

if [ -n "$saved_name" ]; then
    # Network is already saved: connect directly without prompting for password
    wifi_notify "Connecting to $ssid..." normal 5000
    if nmcli connection up id "$saved_name" >/dev/null 2>&1 || nmcli connection up "$saved_name" >/dev/null 2>&1; then
        nmcli connection modify "$saved_name" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
        wifi_notify "Connected to $ssid" normal 3000
    else
        wifi_notify "Saved connection failed. Please enter password." critical 3500
        password=$(wofi --dmenu --password --prompt "Password for $ssid" --width 420 --height 120)
        [ -z "$password" ] && exit 0

        wifi_notify "Connecting to $ssid..." normal 6000
        if nmcli device wifi connect "$ssid" password "$password" >/dev/null 2>&1; then
            nmcli connection modify "$ssid" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
            wifi_notify "Connected to $ssid" normal 3000
        else
            wifi_notify "Failed to connect to $ssid" critical 4500
        fi
    fi
else
    # Network is not saved: check if security is required
    security="${ssid_security["$ssid"]:-}"

    if [ -n "$security" ] && [ "$security" != "--" ]; then
        password=$(wofi --dmenu --password --prompt "Password for $ssid" --width 420 --height 120)
        [ -z "$password" ] && exit 0

        wifi_notify "Connecting to $ssid..." normal 6000
        if nmcli device wifi connect "$ssid" password "$password" >/dev/null 2>&1; then
            nmcli connection modify "$ssid" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
            wifi_notify "Connected to $ssid" normal 3000
        else
            wifi_notify "Failed to connect to $ssid" critical 4500
        fi
    else
        wifi_notify "Connecting to open network $ssid..." normal 5000
        if nmcli device wifi connect "$ssid" >/dev/null 2>&1; then
            nmcli connection modify "$ssid" connection.autoconnect yes connection.autoconnect-retries 0 2>/dev/null || true
            wifi_notify "Connected to $ssid" normal 3000
        else
            wifi_notify "Failed to connect to $ssid" critical 4500
        fi
    fi
fi
