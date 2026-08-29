#!/usr/bin/env bash

# Installer for Waybar & Wofi status bar configurations
# Safely backups configurations and handles dependencies on Arch Linux

set -u

# Define colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================="
echo -e "   Waybar & Wofi Configurations Installer"
echo -e "==========================================${NC}\n"

# 1. Dependency checks
dependencies=("waybar" "wofi" "nmcli" "bluetoothctl")
pkg_names=("waybar" "wofi" "networkmanager" "bluez-utils")
missing_deps=()
missing_pkgs=()

for i in "${!dependencies[@]}"; do
    dep="${dependencies[$i]}"
    pkg="${pkg_names[$i]}"
    if ! command -v "$dep" >/dev/null 2>&1; then
        missing_deps+=("$dep")
        missing_pkgs+=("$pkg")
    fi
done

if [ ${#missing_deps[@]} -ne 0 ]; then
    echo -e "${YELLOW}Detected missing dependencies:${NC}"
    for dep in "${missing_deps[@]}"; do
        echo -e "  - $dep"
    done
    echo

    # Check if we are on Arch Linux
    if [ -f /etc/arch-release ] || command -v pacman >/dev/null 2>&1; then
        read -r -p "Would you like to install the missing packages (${missing_pkgs[*]}) using pacman now? [y/N]: " choice
        case "$choice" in
            [yY][eE][sS]|[yY])
                echo -e "${YELLOW}Installing missing packages...${NC}"
                if sudo pacman -S --needed --noconfirm "${missing_pkgs[@]}"; then
                    echo -e "${GREEN}Dependencies installed successfully!${NC}\n"
                else
                    echo -e "${RED}Failed to install packages. Please install them manually.${NC}"
                    exit 1
                fi
                ;;
            *)
                echo -e "${RED}Installation aborted. Please install the required dependencies first.${NC}"
                exit 1
                ;;
        esac
    else
        echo -e "${RED}Please install the following packages manually before running this installer:${NC}"
        echo -e "  ${missing_pkgs[*]}"
        exit 1
    fi
fi

# Ensure target directories exist
mkdir -p "$HOME/.config/waybar"
mkdir -p "$HOME/.config/wofi"

# Helper function to backup and copy
safe_install() {
    local src="$1"
    local dest="$2"
    local dest_dir
    dest_dir=$(dirname "$dest")

    # If destination exists and is different from source, back it up
    if [ -f "$dest" ]; then
        if ! cmp -s "$src" "$dest"; then
            local backup_file="${dest}.$(date +%Y%m%d_%H%M%S).bak"
            echo -e "${YELLOW}Backing up existing $(basename "$dest") to $(basename "$backup_file")${NC}"
            cp "$dest" "$backup_file"
        else
            echo -e "No changes in $(basename "$dest"). Skipping backup."
        fi
    fi

    # Copy new file
    cp "$src" "$dest"
}

# 2. Install Waybar files
echo -e "${YELLOW}Installing Waybar files...${NC}"
safe_install "waybar/config.jsonc" "$HOME/.config/waybar/config.jsonc"
safe_install "waybar/style.css" "$HOME/.config/waybar/style.css"

# 3. Install scripts
echo -e "${YELLOW}Installing helper scripts...${NC}"
safe_install "scripts/wifi-menu.sh" "$HOME/.config/waybar/wifi-menu.sh"
safe_install "scripts/bluetooth-menu.sh" "$HOME/.config/waybar/bluetooth-menu.sh"
chmod +x "$HOME/.config/waybar/wifi-menu.sh"
chmod +x "$HOME/.config/waybar/bluetooth-menu.sh"

# 4. Install Wofi files
echo -e "${YELLOW}Installing Wofi files...${NC}"
safe_install "wofi/config" "$HOME/.config/wofi/config"
safe_install "wofi/style.css" "$HOME/.config/wofi/style.css"

echo -e "\n${GREEN}Files installed successfully!${NC}"

# 5. Reload/restart Waybar if running
if pgrep -x waybar >/dev/null 2>&1; then
    echo -e "${YELLOW}Detected active Waybar process. Sending reload signal (SIGUSR2)...${NC}"
    killall -USR2 waybar
    echo -e "${GREEN}Waybar reloaded successfully!${NC}"
else
    echo -e "${YELLOW}Waybar is not currently running. Start it to see changes.${NC}"
fi

echo -e "\n${GREEN}Installation Complete!${NC}"
