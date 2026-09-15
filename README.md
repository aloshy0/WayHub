# Waybar & Wofi Network/Bluetooth Menus

A polished, open-source status bar customization suite for Arch Linux and Hyprland. This repository provides a unified visual experience, bridging Waybar modules with custom graphical Wofi menus to control Wi-Fi and Bluetooth using NetworkManager and BlueZ.

![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/dcf66aea-f802-498a-860e-f58b4151be1d" />


## Features

### 󰤨 Wi-Fi Control Center (`wifi-menu.py` & `wifi-menu.sh`)
- **Modern GTK3 & Layer Shell Interface**: Sleek, glassmorphic dark-mode popup anchored directly beneath the Waybar Wi-Fi module.
- **Live Network Statistics**: Real-time traffic monitoring (`Receiving` / `Sending` KB/s & MB/s), cumulative data transferred (`Downloaded` / `Uploaded`), `Ping` latency, `Packet Loss`, `IP Address`, and `Gateway`.
- **DNS Provider Switching**: 1-click toggling between `DHCP`, `Cloudflare` (1.1.1.1), `Google` (8.8.8.8), and `Custom` DNS providers with automatic NetworkManager application.
- **Integrated Speed Test**: On-demand network speed & throughput benchmark with live status feedback.
- **Wi-Fi QR Code Sharing**: Generate a scannable mobile QR code with SSID and security password in one click.
- **Power Switch & Single-Instance Toggle**: Toggle Wi-Fi radio on/off and smoothly toggle the menu open/closed from Waybar.
- **Known & Nearby Networks**: Manage current connections (Disconnect, View Password, Forget) and easily connect to nearby SSIDs with inline password entry.

### 󰂯 Bluetooth Control Center (`bluetooth-menu.py` & `bluetooth-menu.sh`)
- **Matching Modern GTK3 & Layer Shell Design**: Consistent dark-mode popup interface anchored right under the Waybar Bluetooth module.
- **Live Controller & Device Metrics**: Real-time stats for adapter state, discoverability, pairable mode, device address, host alias, and active connection counts.
- **Controller Modes & Quick Actions**: 1-click toggling for `Discoverable`, `Pairable`, active `Scan (8s)`, and `Auto-Agent` listener.
- **Paired Device Cards**: Visual cards with contextual device icons (headsets, mice, keyboards, phones), connection status, and real-time battery percentages (`• 80% 󰁹`).
- **Device Management**: Click any device to connect/disconnect, trust/untrust, pair, or forget.
- **Available Devices Scanner**: Discovers nearby Bluetooth devices in range with a flat `󰑐` rescan button and one-click pairing.
- **Power Switch & Single-Instance Toggle**: Toggle Bluetooth radio power and toggle the popup open/closed smoothly from Waybar.

### 󱈑 Battery & Power Profiles (`battery.py` & `power-profile-toggle.sh`)
- **Dynamic Battery State**: Accurately tracks charge percentage, charging status, and battery health via UPower/sysfs.
- **Power Profile Switching**: Left-click the battery pill to seamlessly cycle through power profiles (`performance` 󰓅, `balanced` 󰾅, `power-saver` / `eco` 󰌪).
- **Eco Mode Highlighting**: Automatically changes pill colors to emerald green during Power Saver mode for clear visual feedback.

###  Flexible Display Modes & Proper Autohide
- **Fixed Mode**: The bar is docked to the top (`exclusive: true`), reserving space for tiled windows.
- **Autohide Mode**: Uses a sub-millisecond Hyprland socket daemon (`autohide-daemon.py`) to reveal the bar when hovering the top edge (`y <= 2px`) and hide when cursor leaves.
- **Clean Click-Through**: Unmaps layer input when hidden, completely eliminating invisible ghost clicks over browser tabs, editor headers, and window buttons.
- **Multi-Monitor Support**: Works seamlessly across all outputs, scaling factors, and multi-monitor setups.

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
3. **Installs Configurations & Scripts**: Copies the custom config files and scripts (including the Wi-Fi/Bluetooth menu scripts, battery helper, and autohide daemon) to your config directory and marks the scripts as executable.
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

## Usage & Shortcuts

### Desktop Shortcuts (Hyprland)
| Shortcut | Action | Description |
| :--- | :--- | :--- |
| **`Super + Shift + W`** | **Manual Hide / Show** | Instantly toggles the topbar visibility on/off across all desktop windows. When hidden, windows expand full-screen and the bar stays hidden (no mouse-hover auto-popup). |
| **`Super + W`** | **Toggle Autohide Mode** | Switches between Fixed mode (permanently docked) and Autohide mode (reveals when cursor touches screen top edge). |

### Waybar Interactions
- **Wi-Fi Module**:
  - **Left-Click**: Opens the Wofi Wi-Fi menu.
  - **Right-Click**: Fast-toggles Wi-Fi power state on/off.
- **Bluetooth Module**:
  - **Left-Click**: Opens the Wofi Bluetooth menu.
  - **Right-Click**: Quick power off.
  - **Middle-Click**: Quick power on.
- **Battery Module**:
  - **Left-Click**: Cycles power profiles (Performance / Balanced / Power Saver).
- **Launcher Module (``)**:
  - **Left-Click**: Toggles application menu.

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
│   ├── config.jsonc          # Fixed mode Waybar layout config
│   ├── config-autohide.jsonc # Autohide mode Waybar layout config
│   ├── style.css             # Fixed mode styling
│   └── style-autohide.css    # Autohide mode styling
│
├── wofi/
│   ├── config                # Wofi layout configuration
│   └── style.css             # Glassmorphism/modern dark Wofi theme
│
├── scripts/
│   ├── wifi-menu.sh          # Wofi Wi-Fi manager script
│   ├── bluetooth-menu.sh     # Wofi Bluetooth manager script
│   ├── bt-agent.py           # Automated Bluetooth pairing agent
│   ├── battery.py            # Custom battery status and profile indicator
│   ├── power-profile-toggle.sh # Power profile cycle toggle script
│   ├── autohide-daemon.py    # Edge-trigger hover autohide watcher daemon
│   ├── toggle-mode.sh        # Mode switcher (Fixed <-> Autohide)
│   ├── toggle-visibility.sh  # Manual visibility toggle (No autohide)
│   └── launch.sh             # Desktop autostart helper script
│
├── assets/
│   └── screenshots/          # Screenshots directory
│
└── docs/
    └── configuration.md      # Detailed customization guidelines
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

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/491be5e7-c369-4768-97a3-6ba84e07ac64" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/18b553dd-391b-415d-8d82-2c0f2e7484ca" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/69837d82-2931-4afa-bb09-e208227b9e4e" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/4978039b-1449-4684-a32f-e273d5cd70fa" />

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/bffe9a57-a082-4f27-a464-aa5f6e01d4c0" />




