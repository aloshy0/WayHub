# Waybar & Wofi Network/Bluetooth Menus

A polished, open-source status bar customization suite for Arch Linux and Hyprland. This repository provides a unified visual experience, bridging Waybar modules with custom graphical Wofi menus to control Wi-Fi and Bluetooth using NetworkManager and BlueZ.

![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/dcf66aea-f802-498a-860e-f58b4151be1d" />


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

The installer automatically checks for and handles the following dependencies on Arch Linux:
- `waybar` (Status bar)
- `wofi` (Menu launcher)
- `networkmanager` (Provides `nmcli` for Wi-Fi management)
- `bluez` & `bluez-utils` (Provides `bluetoothd` and `bluetoothctl` for Bluetooth control)
- `python` (Python 3 interpreter)
- `python-dbus` (Python D-Bus bindings for the automated pairing agent)
- `python-gobject` (PyGObject GLib bindings for the automated pairing agent)
- `bash`
- `libnotify` (Provides `notify-send` for desktop notifications)
- A Nerd Font (e.g., **JetBrainsMono Nerd Font** for icon/glyph support)

---

## Installation

To download, install, and apply the customization suite, run the following commands in your terminal:

```bash
# Clone the repository
git clone https://github.com/aloshy0/WayHub.git

# Navigate to the cloned directory
cd WayHub

# Mark the installer as executable
chmod +x install.sh

# Run the installer
./install.sh
```

### What the installer does:
1. **Verifies Dependencies**: Scans your system for all required tools and libraries (such as `waybar`, `wofi`, `networkmanager`, `bluez`, `python-dbus`, etc.), and asks for permission to install missing ones using `pacman`.
2. **Backs Up Existing Configurations**: If you already have configurations or scripts in `~/.config/waybar/` or `~/.config/wofi/`, the installer automatically creates safe, timestamped backups (e.g., `config.jsonc.YYYYMMDD_HHMMSS.bak`) before proceeding.
3. **Installs Configurations & Scripts**: Copies the custom config files and scripts (including the Wi-Fi/Bluetooth menu scripts and the background Bluetooth agent helper) to your config directory and marks the scripts as executable.
4. **Reloads Waybar**: Sends a `SIGUSR2` signal to active instances of Waybar, updating your status bar styling immediately without requiring a system reboot.

---

## Uninstallation

If you ever wish to remove the configurations and restore/cleanup your setup, run the included rollback utility:

```bash
# Navigate to the repository directory
cd WayHub

# Run the uninstaller
./uninstall.sh
```
This utility removes the installed configurations and helper scripts, while leaving your original backup files (`*.bak`) intact so you can easily restore them if needed.

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
WayHub/
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
Our custom automated pairing agent (`bt-agent.py`) runs dynamically in the background during pairing attempts to automatically accept PIN/passcode confirmations. If pairing fails:
- Check that the Bluetooth service is active:
  ```bash
  systemctl status bluetooth
  ```
- Ensure you have `python-dbus` and `python-gobject` installed so the helper script can run.
- Make sure Bluetooth is not blocked by rfkill:
  ```bash
  rfkill list
  rfkill unblock bluetooth
  ```

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

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/c31f263a-8f6f-40a2-9817-4a8e73d953af" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/02da32a6-6989-4d21-9e51-274cef8a4bf1" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/6204a553-ff3f-4c47-b261-44ed27b6bece" />


