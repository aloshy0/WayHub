#!/usr/bin/env bash

# Uninstaller for Waybar & Wofi status bar configurations
# Safely removes the installed configurations and leaves backups intact

set -u

# Define colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${RED}=========================================="
echo -e "   Waybar & Wofi Configurations Uninstaller"
echo -e "==========================================${NC}\n"

files_to_remove=(
    "$HOME/.config/waybar/config.jsonc"
    "$HOME/.config/waybar/style.css"
    "$HOME/.config/waybar/wifi-menu.sh"
    "$HOME/.config/waybar/bluetooth-menu.sh"
    "$HOME/.config/wofi/config"
    "$HOME/.config/wofi/style.css"
)

# Check which files exist
existing_files=()
for file in "${files_to_remove[@]}"; do
    if [ -f "$file" ]; then
        existing_files+=("$file")
    fi
done

if [ ${#existing_files[@]} -eq 0 ]; then
    echo -e "${GREEN}No installed files were found. Nothing to do!${NC}"
    exit 0
fi

echo -e "${YELLOW}The following files will be removed:${NC}"
for file in "${existing_files[@]}"; do
    echo "  - $file"
done
echo

read -r -p "Are you sure you want to proceed with the uninstallation? [y/N]: " choice
case "$choice" in
    [yY][eE][sS]|[yY])
        echo -e "\n${YELLOW}Removing files...${NC}"
        for file in "${existing_files[@]}"; do
            if rm "$file"; then
                echo -e "Removed: $(basename "$file")"
            else
                echo -e "${RED}Failed to remove: $file${NC}"
            fi
        done
        
        echo -e "\n${GREEN}Uninstallation complete!${NC}"
        echo -e "${YELLOW}Note: Any backups (*.bak) created during installation have been preserved.${NC}"
        
        # Reload Waybar if running to reflect changes
        if pgrep -x waybar >/dev/null 2>&1; then
            echo -e "\n${YELLOW}Reloading Waybar...${NC}"
            killall -USR2 waybar
            echo -e "${GREEN}Waybar reloaded!${NC}"
        fi
        ;;
    *)
        echo -e "${GREEN}Uninstallation canceled.${NC}"
        exit 0
        ;;
esac
