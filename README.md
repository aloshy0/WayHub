# Waybar & Wofi Network/Bluetooth Menus

A polished, open-source status bar customization suite for Arch Linux and Hyprland. This repository provides a unified visual experience, bridging Waybar modules with custom graphical Wofi menus to control Wi-Fi and Bluetooth using NetworkManager and BlueZ.

![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)

## Features

### 󰤨 Wi-Fi Menu (`wifi-menu.sh`)
- **Interactive State**: Toggle Wi-Fi power (Enable/Disable) directly from the menu.
- **Connection Isolation**: Shows currently connected Wi-Fi network at the top.
- **Polished Sorting**: Lists available networks sorted by signal strength.
- **De-cluttered Interface**: Saved networks are grouped into a sub-menu to keep the main list clean.
- **Saved Connection Manager**: Connect, Show Password, Edit Password, and Forget Network.
- **Open Networks Support**: Connects to open networks instantly without password prompts.
- **Robust Parsing**: Built using safe Bash associative mapping, supporting SSIDs with spaces, colons, or special characters.

### 󰂯 Bluetooth Menu (`bluetooth-menu.sh`)
- **Interactive Power**: Turn Bluetooth on/off from the menu.
- **Fast Load**: Instant menu loading using known/cached devices (no startup scan delay).
- **Asynchronous Scan**: A "Scan for Devices" utility runs an active scan in the background for 5 seconds and notifies you via `notify-send`.
- **Discoverability Control**: Toggle the computer's discoverability state directly.
- **Device Options Sub-menu**: Connect, Disconnect, Trust, Untrust, Pair (with agent support), and Remove/Forget.
- **Process Cleanup**: Active background scans are safely cleaned up on exit using Bash traps.

---

## Requirements

The installer checks for and handles the following dependencies on Arch Linux:
- `waybar` (Status bar)
- `wofi` (Menu launcher)
- `networkmanager` (Provides `nmcli` for Wi-Fi management)
- `bluez` & `bluez-utils` (Provides `bluetoothd` and `bluetoothctl`)
- `bash`
- `libnotify` (Provides `notify-send` for desktop notifications)
- A Nerd Font (e.g., **JetBrainsMono Nerd Font** for glyph support)

---

## Installation

```bash
git clone https://github.com/aloshy0/hyprland-custom-waybar.git
cd hyprland-custom-waybar
chmod +x install.sh
./install.sh
```

---

## Usage

### Waybar Interactions
- **Wi-Fi Module**:
  - **Left-Click**: Opens the Wofi Wi-Fi menu.
  - **Right-Click**: Fast-toggles Wi-Fi power state on/off.
- **Bluetooth Module**:
  - **Left-Click**: Opens the Wofi Bluetooth menu.
  - **Right-Click**: Quick power off.
  - **Middle-Click**: Quick power on.

### Password Management & Security
- Passwords are **never** stored in plain text files or written to logs.
- Connecting to a new secured network prompts for the password using Wofi's secure input field.
- "Show Password" retrieves credentials on-demand from NetworkManager using the secure `nmcli --show-secrets` mechanism.
- "Edit Password" modifies the NetworkManager connection profile directly.

---

## File Structure

```
hyprland-custom-waybar/
│
├── README.md             # This documentation file
├── LICENSE               # MIT License details
├── install.sh            # Setup & configuration script
├── uninstall.sh          # System rollback utility
├── .gitignore            # Git ignore rules
│
├── waybar/
│   ├── config.jsonc      # Customized Waybar layout config
│   └── style.css         # Waybar styling with interactive hover states
│
├── wofi/
│   ├── config            # Wofi layout configuration
│   └── style.css         # Glassmorphism/modern dark Wofi theme
│
├── scripts/
│   ├── wifi-menu.sh      # Wofi Wi-Fi manager script
│   └── bluetooth-menu.sh # Wofi Bluetooth manager script
│
├── assets/
│   └── screenshots/      # Screenshots directory
│
└── docs/
    └── configuration.md  # Detailed customization guidelines
```

---

## Configuration

You can customize layouts, sizing, padding, and coloring by modifying files in their installed directories:
- **Waybar Configuration**: `~/.config/waybar/config.jsonc` & `style.css`
- **Wofi Configuration**: `~/.config/wofi/config` & `style.css`

*Refer to [docs/configuration.md](file:///home/michael/Projects/waybar/docs/configuration.md) for a detailed styling guide.*

---

## Troubleshooting

### Waybar not displaying changes
Make sure the Waybar configuration is reloaded. The installer automatically sends a `SIGUSR2` signal to active Waybar instances, but you can also reload it manually:
```bash
killall -USR2 waybar
```

### Bluetooth agent issues
If pairing fails, verify that the Bluetooth agent is running or try running:
```bash
systemctl status bluetooth
```
Make sure your user has permissions to access the D-Bus system.

### Icons not displaying correctly
Verify that you have installed a Nerd Font. On Arch Linux:
```bash
sudo pacman -S ttf-jetbrains-mono-nerd
```

### NetworkManager not running
If the Wi-Fi menu displays a "NetworkManager is not running" notification, check the service status:
```bash
sudo systemctl enable --now NetworkManager
```

---

## License

This project is licensed under the [MIT License](file:///home/michael/Projects/waybar/LICENSE).
Waybar and Wofi are third-party projects and are subject to their own upstream licensing.
