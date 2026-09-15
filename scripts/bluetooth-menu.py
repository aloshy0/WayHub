#!/usr/bin/env python3
"""
Waybar Bluetooth Control Center Popup
A modern, dark-themed Bluetooth control center built with GTK3 & GtkLayerShell.
"""

import os
import sys
import re
import socket
import threading
import subprocess
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell, cairo

SOCKET_PATH = f"/tmp/waybar_bluetooth_menu_{os.getuid()}.sock"

CSS_STYLE = """
* {
    all: unset;
    font-family: 'JetBrainsMono Nerd Font', 'JetBrains Mono', 'Inter', -apple-system, sans-serif;
}

window {
    background-color: transparent;
    background: transparent;
}

.backdrop {
    background-color: transparent;
    background: transparent;
}

.bt-window {
    background-color: rgba(18, 21, 28, 0.98);
    border: 1px solid #2b3240;
    border-radius: 16px;
    padding: 18px 20px;
    color: #e2e8f0;
}

/* Header */
.header-box {
    margin-bottom: 12px;
}

.bt-icon-large {
    font-size: 28px;
    color: #ffffff;
    min-width: 36px;
}

.bt-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.bt-subtitle {
    font-size: 9.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.6px;
}

.icon-button {
    background-color: #1a1e27;
    border: 1px solid #2d3544;
    border-radius: 8px;
    padding: 6px 10px;
    color: #c5cdd9;
    font-size: 14px;
    transition: all 150ms ease;
}

.icon-button:hover {
    background-color: #262d3a;
    border-color: #3e485b;
    color: #ffffff;
}

.flat-icon-btn {
    background-color: transparent;
    border: none;
    padding: 2px 4px;
    color: #657082;
    font-size: 13px;
    transition: color 150ms ease;
}

.flat-icon-btn:hover {
    background-color: transparent;
    color: #ffffff;
}

/* Switch */
switch {
    background-color: #1e2430;
    border: 1px solid #333d4f;
    border-radius: 16px;
    min-width: 46px;
    min-height: 24px;
    padding: 2px;
}

switch:checked {
    background-color: #2b3547;
    border-color: #4a576e;
}

switch slider {
    background-color: #e2e8f0;
    border-radius: 50%;
    min-width: 20px;
    min-height: 20px;
    margin: 1px;
}

switch:checked slider {
    background-color: #ffffff;
}

/* Stats Grid */
.stats-grid {
    margin-top: 6px;
    margin-bottom: 14px;
}

.stat-label {
    font-size: 11.5px;
    color: #727c8e;
    font-weight: 500;
}

.stat-value {
    font-size: 12px;
    font-weight: 600;
    color: #e2e8f0;
}

/* Section Title */
.section-title {
    font-size: 10px;
    font-weight: 800;
    color: #657082;
    letter-spacing: 1.4px;
    margin-top: 10px;
    margin-bottom: 8px;
}

/* Controller Mode Buttons */
.mode-btn {
    background-color: #171b23;
    border: 1px solid #282f3d;
    border-radius: 8px;
    padding: 7px 12px;
    color: #b0bac8;
    font-size: 11.5px;
    font-weight: 600;
    transition: all 150ms ease;
}

.mode-btn:hover {
    background-color: #212733;
    border-color: #3b4557;
    color: #ffffff;
}

.mode-btn.active {
    background-color: #232a37;
    border: 1px solid #4d5a71;
    color: #ffffff;
    font-weight: 700;
}

/* Action Run Button */
.scan-run-btn {
    background-color: #171b23;
    border: 1px solid #282f3d;
    border-radius: 8px;
    padding: 4px 14px;
    color: #c5cdd9;
    font-size: 11.5px;
    font-weight: 600;
    transition: all 150ms ease;
}

.scan-run-btn:hover {
    background-color: #212733;
    border-color: #3b4557;
    color: #ffffff;
}

/* Device Card */
.device-card {
    background-color: #1f242e;
    border: 1px solid #2e3747;
    border-radius: 10px;
    transition: all 150ms ease;
}

.device-card:hover {
    background-color: #262d3a;
    border-color: #3d495d;
}

.device-card .dev-icon {
    font-size: 17px;
    color: #ffffff;
}

.device-card .dev-name {
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
}

.device-card .dev-status {
    font-size: 10.5px;
    color: #7d8799;
}

.device-card .dev-badge {
    font-size: 12px;
    color: #657082;
}

/* Device Row */
.device-row {
    border-radius: 8px;
    transition: all 120ms ease;
}

.device-row:hover {
    background-color: #1b202a;
}

.device-row .dev-icon {
    font-size: 15px;
    color: #929db0;
}

.device-row .dev-name {
    font-size: 12.5px;
    font-weight: 500;
    color: #c7d0dc;
}

.device-row:hover .dev-name {
    color: #ffffff;
}

.device-row:hover .dev-icon {
    color: #ffffff;
}

/* Overlay Dialog */
.card-overlay {
    background-color: #181c25;
    border: 1px solid #30394a;
    border-radius: 12px;
    padding: 16px;
    margin-top: 10px;
}

.action-btn {
    background-color: #202632;
    border: 1px solid #313b4c;
    border-radius: 8px;
    padding: 6px 12px;
    color: #c5cdd9;
    font-size: 11.5px;
    font-weight: 600;
}

.action-btn:hover {
    background-color: #2c3546;
    color: #ffffff;
}

.action-btn.danger {
    background-color: #3b1e24;
    border-color: #5a2730;
    color: #f87171;
}

.action-btn.danger:hover {
    background-color: #4c222b;
    color: #fca5a5;
}

/* Scroll Area */
scrollbar slider {
    background-color: #2b3342;
    border-radius: 4px;
    min-width: 4px;
}

scrollbar trough {
    background-color: transparent;
}
"""

def get_device_glyph(icon_name, dev_class=""):
    icon_name = (icon_name or "").lower()
    if "headset" in icon_name or "headphones" in icon_name or "audio" in icon_name:
        return "󰋋"
    elif "keyboard" in icon_name:
        return "󰌌"
    elif "mouse" in icon_name or "gaming" in icon_name:
        return "󰍽"
    elif "phone" in icon_name:
        return "󰄜"
    elif "computer" in icon_name or "laptop" in icon_name:
        return "󰌢"
    elif "watch" in icon_name:
        return "󰟾"
    return "󰂯"


class BluetoothControlCenter(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        self.connect("draw", self.on_window_draw)
        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", Gtk.main_quit)

        # Controller state variables
        self.bt_powered = False
        self.bt_discoverable = False
        self.bt_pairable = False
        self.bt_discovering = False
        self.controller_mac = ""
        self.controller_alias = ""
        self.primary_connected = ""
        self.scanning_active = False

        self.init_ui()
        self.apply_css()

        # Initial state poll
        self.poll_controller_state()
        self.poll_devices()

        # Auto refresh timers
        GLib.timeout_add(2000, self.poll_controller_state)
        GLib.timeout_add(4000, self.poll_devices)

    def on_window_draw(self, widget, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        return False

    def on_backdrop_clicked(self, widget, event):
        alloc = self.card.get_allocation()
        if alloc.x <= event.x <= alloc.x + alloc.width and alloc.y <= event.y <= alloc.y + alloc.height:
            return False
        self.close()
        return True

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE.encode())
        screen = Gdk.Screen.get_default()
        style_ctx = self.get_style_context()
        style_ctx.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def init_ui(self):
        # Fullscreen Backdrop EventBox
        self.backdrop = Gtk.EventBox()
        self.backdrop.get_style_context().add_class("backdrop")
        self.backdrop.set_above_child(False)
        self.backdrop.connect("button-press-event", self.on_backdrop_clicked)
        self.add(self.backdrop)

        align_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.backdrop.add(align_box)

        # Outer Card Container
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("bt-window")
        self.card.set_halign(Gtk.Align.END)
        self.card.set_valign(Gtk.Align.START)
        self.card.set_margin_top(36)
        self.card.set_margin_end(12)
        self.card.set_size_request(410, -1)
        align_box.pack_start(self.card, False, False, 0)

        main_box = self.card

        # 1. Header Box
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header_box.get_style_context().add_class("header-box")
        main_box.pack_start(header_box, False, False, 0)

        # Large Bluetooth Icon
        self.header_icon = Gtk.Label(label="")
        self.header_icon.get_style_context().add_class("bt-icon-large")
        self.header_icon.set_size_request(36, 36)
        self.header_icon.set_halign(Gtk.Align.CENTER)
        self.header_icon.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(self.header_icon, False, False, 0)

        # Title + Subtitle Box
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(label="Bluetooth", xalign=0)
        self.lbl_title.get_style_context().add_class("bt-title")
        self.lbl_subtitle = Gtk.Label(label="DISCOVERABLE: OFF", xalign=0)
        self.lbl_subtitle.get_style_context().add_class("bt-subtitle")
        title_box.pack_start(self.lbl_title, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Right Action Box (Discoverable + Switch)
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions_box.set_valign(Gtk.Align.CENTER)
        header_box.pack_end(actions_box, False, False, 0)

        # Discoverable Quick Button
        self.disc_btn = Gtk.Button(label="󰂰")
        self.disc_btn.get_style_context().add_class("icon-button")
        self.disc_btn.set_tooltip_text("Toggle Discoverability")
        self.disc_btn.connect("clicked", self.toggle_discoverability)
        actions_box.pack_start(self.disc_btn, False, False, 0)

        # Bluetooth Power Switch
        self.bt_switch = Gtk.Switch()
        self.bt_switch.connect("state-set", self.on_switch_toggled)
        actions_box.pack_start(self.bt_switch, False, False, 0)

        # Modal/Overlay Container for action dialogs
        self.overlay_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.pack_start(self.overlay_container, False, False, 0)

        # 2. Stats Grid (4 rows x 2 cols)
        stats_grid = Gtk.Grid()
        stats_grid.get_style_context().add_class("stats-grid")
        stats_grid.set_row_spacing(6)
        stats_grid.set_column_spacing(16)
        stats_grid.set_hexpand(True)
        main_box.pack_start(stats_grid, False, False, 0)

        # Column 1
        l_ctrl = Gtk.Label(label="Controller", xalign=0)
        l_ctrl.get_style_context().add_class("stat-label")
        self.v_ctrl = Gtk.Label(label="hci0", xalign=1)
        self.v_ctrl.get_style_context().add_class("stat-value")

        l_disc = Gtk.Label(label="Discoverable", xalign=0)
        l_disc.get_style_context().add_class("stat-label")
        self.v_disc = Gtk.Label(label="No", xalign=1)
        self.v_disc.get_style_context().add_class("stat-value")

        l_conn = Gtk.Label(label="Connected", xalign=0)
        l_conn.get_style_context().add_class("stat-label")
        self.v_conn = Gtk.Label(label="0 Devices", xalign=1)
        self.v_conn.get_style_context().add_class("stat-value")

        l_addr = Gtk.Label(label="Address", xalign=0)
        l_addr.get_style_context().add_class("stat-label")
        self.v_addr = Gtk.Label(label="--:--:--:--:--:--", xalign=1)
        self.v_addr.get_style_context().add_class("stat-value")

        # Column 2
        l_state = Gtk.Label(label="State", xalign=0)
        l_state.get_style_context().add_class("stat-label")
        self.v_state = Gtk.Label(label="Off", xalign=1)
        self.v_state.get_style_context().add_class("stat-value")

        l_pair = Gtk.Label(label="Pairable", xalign=0)
        l_pair.get_style_context().add_class("stat-label")
        self.v_pair = Gtk.Label(label="No", xalign=1)
        self.v_pair.get_style_context().add_class("stat-value")

        l_paired = Gtk.Label(label="Paired", xalign=0)
        l_paired.get_style_context().add_class("stat-label")
        self.v_paired = Gtk.Label(label="0 Devices", xalign=1)
        self.v_paired.get_style_context().add_class("stat-value")

        l_alias = Gtk.Label(label="Alias", xalign=0)
        l_alias.get_style_context().add_class("stat-label")
        self.v_alias = Gtk.Label(label="Host", xalign=1)
        self.v_alias.get_style_context().add_class("stat-value")

        # Attach
        stats_grid.attach(l_ctrl, 0, 0, 1, 1)
        stats_grid.attach(self.v_ctrl, 1, 0, 1, 1)
        stats_grid.attach(l_state, 2, 0, 1, 1)
        stats_grid.attach(self.v_state, 3, 0, 1, 1)

        stats_grid.attach(l_disc, 0, 1, 1, 1)
        stats_grid.attach(self.v_disc, 1, 1, 1, 1)
        stats_grid.attach(l_pair, 2, 1, 1, 1)
        stats_grid.attach(self.v_pair, 3, 1, 1, 1)

        stats_grid.attach(l_conn, 0, 2, 1, 1)
        stats_grid.attach(self.v_conn, 1, 2, 1, 1)
        stats_grid.attach(l_paired, 2, 2, 1, 1)
        stats_grid.attach(self.v_paired, 3, 2, 1, 1)

        stats_grid.attach(l_addr, 0, 3, 1, 1)
        stats_grid.attach(self.v_addr, 1, 3, 1, 1)
        stats_grid.attach(l_alias, 2, 3, 1, 1)
        stats_grid.attach(self.v_alias, 3, 3, 1, 1)

        stats_grid.get_child_at(1, 0).set_hexpand(True)
        stats_grid.get_child_at(3, 0).set_hexpand(True)

        # 3. Controller Modes Section
        modes_title = Gtk.Label(label="CONTROLLER MODES", xalign=0)
        modes_title.get_style_context().add_class("section-title")
        main_box.pack_start(modes_title, False, False, 0)

        modes_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        modes_box.set_homogeneous(True)
        main_box.pack_start(modes_box, False, False, 0)

        self.btn_mode_disc = Gtk.Button(label="Discoverable")
        self.btn_mode_disc.get_style_context().add_class("mode-btn")
        self.btn_mode_disc.connect("clicked", lambda w: self.toggle_controller_mode("discoverable"))
        modes_box.pack_start(self.btn_mode_disc, True, True, 0)

        self.btn_mode_pair = Gtk.Button(label="Pairable")
        self.btn_mode_pair.get_style_context().add_class("mode-btn")
        self.btn_mode_pair.connect("clicked", lambda w: self.toggle_controller_mode("pairable"))
        modes_box.pack_start(self.btn_mode_pair, True, True, 0)

        self.btn_mode_scan = Gtk.Button(label="Scan (8s)")
        self.btn_mode_scan.get_style_context().add_class("mode-btn")
        self.btn_mode_scan.connect("clicked", lambda w: self.run_active_scan())
        modes_box.pack_start(self.btn_mode_scan, True, True, 0)

        self.btn_mode_agent = Gtk.Button(label="Auto Agent")
        self.btn_mode_agent.get_style_context().add_class("mode-btn")
        self.btn_mode_agent.connect("clicked", lambda w: self.launch_bt_agent())
        modes_box.pack_start(self.btn_mode_agent, True, True, 0)

        # 4. Paired Devices Section
        self.paired_title = Gtk.Label(label="PAIRED & CONNECTED DEVICES", xalign=0)
        self.paired_title.get_style_context().add_class("section-title")
        main_box.pack_start(self.paired_title, False, False, 0)

        self.paired_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        main_box.pack_start(self.paired_container, False, False, 0)

        # 5. Discovered / Available Devices Section
        avail_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.avail_title = Gtk.Label(label="AVAILABLE DEVICES", xalign=0)
        self.avail_title.get_style_context().add_class("section-title")
        avail_header.pack_start(self.avail_title, True, True, 0)

        self.rescan_btn = Gtk.Button(label="󰑐")
        self.rescan_btn.get_style_context().add_class("flat-icon-btn")
        self.rescan_btn.set_valign(Gtk.Align.CENTER)
        self.rescan_btn.set_tooltip_text("Rescan Bluetooth devices")
        self.rescan_btn.connect("clicked", lambda w: self.run_active_scan())
        avail_header.pack_end(self.rescan_btn, False, False, 0)
        main_box.pack_start(avail_header, False, False, 0)

        # Scrollable area
        self.scroll_win = Gtk.ScrolledWindow()
        self.scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll_win.set_min_content_height(80)
        self.scroll_win.set_max_content_height(200)
        self.scroll_win.set_propagate_natural_height(True)
        main_box.pack_start(self.scroll_win, True, True, 0)

        self.avail_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scroll_win.add(self.avail_container)

    # -------------------------------------------------------------
    # State Polling
    # -------------------------------------------------------------
    def poll_controller_state(self):
        def worker():
            try:
                out = subprocess.check_output(["bluetoothctl", "show"], text=True, stderr=subprocess.DEVNULL)
                mac = ""
                alias = ""
                powered = False
                disc = False
                pairable = False
                discovering = False

                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("Controller"):
                        parts = line.split()
                        if len(parts) >= 2:
                            mac = parts[1]
                    elif line.startswith("Alias:"):
                        alias = line.split(":", 1)[1].strip()
                    elif line.startswith("Powered:"):
                        powered = ("yes" in line.lower())
                    elif line.startswith("Discoverable:"):
                        disc = ("yes" in line.lower())
                    elif line.startswith("Pairable:"):
                        pairable = ("yes" in line.lower())
                    elif line.startswith("Discovering:"):
                        discovering = ("yes" in line.lower())

                GLib.idle_add(self._update_controller_ui, mac, alias, powered, disc, pairable, discovering)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _update_controller_ui(self, mac, alias, powered, disc, pairable, discovering):
        self.controller_mac = mac
        self.controller_alias = alias
        self.bt_powered = powered
        self.bt_discoverable = disc
        self.bt_pairable = pairable
        self.bt_discovering = discovering

        self.v_addr.set_text(mac or "--:--:--:--:--:--")
        self.v_alias.set_text(alias or "Host")
        self.v_state.set_text("Powered On" if powered else "Powered Off")
        self.v_disc.set_text("Yes" if disc else "No")
        self.v_pair.set_text("Yes" if pairable else "No")

        # Update switch without triggering signals
        self.bt_switch.handler_block_by_func(self.on_switch_toggled)
        self.bt_switch.set_active(powered)
        self.bt_switch.handler_unblock_by_func(self.on_switch_toggled)

        # Update button active styles
        if disc:
            self.btn_mode_disc.get_style_context().add_class("active")
        else:
            self.btn_mode_disc.get_style_context().remove_class("active")

        if pairable:
            self.btn_mode_pair.get_style_context().add_class("active")
        else:
            self.btn_mode_pair.get_style_context().remove_class("active")

        # Subtitle
        disc_str = "ON" if disc else "OFF"
        pair_str = "ON" if pairable else "OFF"
        self.lbl_subtitle.set_text(f"DISCOVERABLE: {disc_str} • PAIRABLE: {pair_str}")

        if not powered:
            self.lbl_title.set_text("Bluetooth Disabled")
            self.header_icon.set_text("󰂲")
        elif not self.primary_connected:
            self.lbl_title.set_text("Bluetooth Ready")
            self.header_icon.set_text("")

    def on_switch_toggled(self, switch, state):
        def worker():
            cmd = ["bluetoothctl", "power", "on" if state else "off"]
            subprocess.run(cmd, check=False)
            time.sleep(0.5)
            self.poll_controller_state()
            self.poll_devices()
        threading.Thread(target=worker, daemon=True).start()
        return True

    def toggle_discoverability(self, widget):
        new_state = "off" if self.bt_discoverable else "on"
        def worker():
            subprocess.run(["bluetoothctl", "discoverable", new_state], check=False)
            self.poll_controller_state()
        threading.Thread(target=worker, daemon=True).start()

    def toggle_controller_mode(self, mode):
        current = self.bt_discoverable if mode == "discoverable" else self.bt_pairable
        new_state = "off" if current else "on"
        def worker():
            subprocess.run(["bluetoothctl", mode, new_state], check=False)
            self.poll_controller_state()
        threading.Thread(target=worker, daemon=True).start()

    def launch_bt_agent(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        agent_path = os.path.join(script_dir, "bt-agent.py")
        if not os.path.exists(agent_path):
            agent_path = os.path.expanduser("~/.config/waybar/bt-agent.py")

        def worker():
            if os.path.exists(agent_path):
                subprocess.Popen(["python3", agent_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Auto-Agent Active", "Listening for incoming pairing requests..."], check=False)
        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------
    # Devices Polling & Scanning
    # -------------------------------------------------------------
    def poll_devices(self):
        def worker():
            paired_devices = []
            available_devices = []
            connected_count = 0

            try:
                # 1. Get paired devices
                p_out = subprocess.check_output(["bluetoothctl", "devices", "Paired"], text=True, stderr=subprocess.DEVNULL)
                paired_macs = set()
                for line in p_out.splitlines():
                    parts = line.strip().split(maxsplit=2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        mac, name = parts[1], parts[2]
                        paired_macs.add(mac)
                        info = self._get_device_info(mac)
                        info["name"] = name
                        info["mac"] = mac
                        if info.get("connected"):
                            connected_count += 1
                        paired_devices.append(info)

                # 2. Get all discovered devices
                a_out = subprocess.check_output(["bluetoothctl", "devices"], text=True, stderr=subprocess.DEVNULL)
                for line in a_out.splitlines():
                    parts = line.strip().split(maxsplit=2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        mac, name = parts[1], parts[2]
                        if mac not in paired_macs:
                            info = self._get_device_info(mac)
                            info["name"] = name
                            info["mac"] = mac
                            available_devices.append(info)

                GLib.idle_add(self._render_devices, paired_devices, available_devices, connected_count)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _get_device_info(self, mac):
        info = {
            "connected": False, "paired": False,
            "trusted": False, "icon": "", "battery": ""
        }
        try:
            out = subprocess.check_output(["bluetoothctl", "info", mac], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Connected:"):
                    info["connected"] = ("yes" in line.lower())
                elif line.startswith("Paired:"):
                    info["paired"] = ("yes" in line.lower())
                elif line.startswith("Trusted:"):
                    info["trusted"] = ("yes" in line.lower())
                elif line.startswith("Icon:"):
                    info["icon"] = line.split(":", 1)[1].strip()
                elif line.startswith("Battery Percentage:"):
                    m = re.search(r"\((\d+)\)", line)
                    if m:
                        info["battery"] = f"{m.group(1)}%"
        except Exception:
            pass
        return info

    def _render_devices(self, paired_devices, available_devices, connected_count):
        self.v_conn.set_text(f"{connected_count} Device{'s' if connected_count != 1 else ''}")
        self.v_paired.set_text(f"{len(paired_devices)} Device{'s' if len(paired_devices) != 1 else ''}")

        # Update Primary connected title
        connected_devs = [d for d in paired_devices if d.get("connected")]
        if connected_devs:
            self.primary_connected = connected_devs[0]["name"]
            self.lbl_title.set_text(self.primary_connected)
            self.header_icon.set_text("󰂱")
        elif self.bt_powered:
            self.primary_connected = ""
            self.lbl_title.set_text("Bluetooth Ready")
            self.header_icon.set_text("")

        # 1. Render Paired Devices
        for child in self.paired_container.get_children():
            self.paired_container.remove(child)

        if not paired_devices:
            self.paired_title.hide()
        else:
            self.paired_title.show()
            for dev in paired_devices:
                card = Gtk.EventBox()
                card.get_style_context().add_class("device-card")
                card_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                card_box.set_margin_start(14)
                card_box.set_margin_end(14)
                card_box.set_margin_top(10)
                card_box.set_margin_bottom(10)
                card.add(card_box)

                # Device icon
                glyph = get_device_glyph(dev.get("icon"))
                icon_lbl = Gtk.Label(label=glyph)
                icon_lbl.get_style_context().add_class("dev-icon")
                icon_lbl.set_size_request(24, 24)
                icon_lbl.set_valign(Gtk.Align.CENTER)
                icon_lbl.set_halign(Gtk.Align.CENTER)
                card_box.pack_start(icon_lbl, False, False, 0)

                # Info
                info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                info_box.set_valign(Gtk.Align.CENTER)
                lbl_name = Gtk.Label(label=dev["name"], xalign=0)
                lbl_name.get_style_context().add_class("dev-name")
                
                status_parts = []
                if dev.get("connected"):
                    status_parts.append("Connected")
                else:
                    status_parts.append("Paired")
                if dev.get("battery"):
                    status_parts.append(f"• {dev['battery']} 󰁹")

                lbl_stat = Gtk.Label(label=" ".join(status_parts), xalign=0)
                lbl_stat.get_style_context().add_class("dev-status")
                info_box.pack_start(lbl_name, False, False, 0)
                info_box.pack_start(lbl_stat, False, False, 0)
                card_box.pack_start(info_box, True, True, 0)

                # Status Badge
                if dev.get("connected"):
                    badge = Gtk.Label(label="")
                    badge.get_style_context().add_class("dev-badge")
                    badge.set_valign(Gtk.Align.CENTER)
                    card_box.pack_end(badge, False, False, 0)

                card.connect("button-press-event", self.on_device_card_clicked, dev)
                self.paired_container.pack_start(card, False, False, 0)

            self.paired_container.show_all()

        # 2. Render Available Devices
        for child in self.avail_container.get_children():
            self.avail_container.remove(child)

        if not self.bt_powered:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(12)
            empty_box.set_margin_bottom(12)
            lbl = Gtk.Label(label="Bluetooth is turned off")
            lbl.get_style_context().add_class("stat-label")
            empty_box.pack_start(lbl, False, False, 0)
            self.avail_container.pack_start(empty_box, False, False, 0)
        elif not available_devices:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(12)
            empty_box.set_margin_bottom(12)
            lbl = Gtk.Label(label="No other Bluetooth devices in range")
            lbl.get_style_context().add_class("stat-label")
            empty_box.pack_start(lbl, False, False, 0)
            self.avail_container.pack_start(empty_box, False, False, 0)
        else:
            for dev in available_devices:
                row = Gtk.EventBox()
                row.get_style_context().add_class("device-row")
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row_box.set_margin_start(10)
                row_box.set_margin_end(10)
                row_box.set_margin_top(7)
                row_box.set_margin_bottom(7)
                row.add(row_box)

                glyph = get_device_glyph(dev.get("icon"))
                icon_lbl = Gtk.Label(label=glyph)
                icon_lbl.get_style_context().add_class("dev-icon")
                icon_lbl.set_size_request(24, 24)
                icon_lbl.set_valign(Gtk.Align.CENTER)
                row_box.pack_start(icon_lbl, False, False, 0)

                name_lbl = Gtk.Label(label=dev["name"], xalign=0)
                name_lbl.get_style_context().add_class("dev-name")
                name_lbl.set_valign(Gtk.Align.CENTER)
                row_box.pack_start(name_lbl, True, True, 0)

                row.connect("button-press-event", self.on_available_row_clicked, dev)
                self.avail_container.pack_start(row, False, False, 0)

        self.scroll_win.show_all()
        self.avail_container.show_all()

    # -------------------------------------------------------------
    # Active Bluetooth Scan
    # -------------------------------------------------------------
    def run_active_scan(self):
        if self.scanning_active:
            return
        self.scanning_active = True
        self.rescan_btn.set_sensitive(False)
        self.btn_mode_scan.set_label("Scanning...")

        def worker():
            subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Bluetooth Scan", "Scanning nearby devices (8s)..."], check=False)
            subprocess.run(["bluetoothctl", "--timeout", "8", "scan", "on"], stderr=subprocess.DEVNULL)
            self.scanning_active = False
            GLib.idle_add(self._finish_active_scan)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_active_scan(self):
        self.rescan_btn.set_sensitive(True)
        self.btn_mode_scan.set_label("Scan (8s)")
        self.poll_devices()

    # -------------------------------------------------------------
    # Device Management Actions
    # -------------------------------------------------------------
    def on_device_card_clicked(self, widget, event, dev):
        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card-overlay")

        title = Gtk.Label(label=f"Manage '{dev['name']}'", xalign=0)
        title.get_style_context().add_class("bt-title")
        card.pack_start(title, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        is_connected = dev.get("connected", False)
        btn_action = Gtk.Button(label="Disconnect" if is_connected else "Connect")
        btn_action.get_style_context().add_class("action-btn")

        btn_forget = Gtk.Button(label="Forget")
        btn_forget.get_style_context().add_class("action-btn")
        btn_forget.get_style_context().add_class("danger")

        btn_close = Gtk.Button(label="Back")
        btn_close.get_style_context().add_class("action-btn")

        mac = dev["mac"]
        name = dev["name"]

        def do_toggle_connect(w):
            self.clear_overlay()
            def worker():
                if is_connected:
                    subprocess.run(["bluetoothctl", "disconnect", mac], check=False)
                    subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Disconnected", f"Disconnected from {name}"], check=False)
                else:
                    subprocess.run(["bluetoothctl", "connect", mac], check=False)
                    subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Connected", f"Connected to {name}"], check=False)
                GLib.idle_add(self.poll_devices)
            threading.Thread(target=worker, daemon=True).start()

        def do_forget(w):
            self.clear_overlay()
            def worker():
                subprocess.run(["bluetoothctl", "remove", mac], check=False)
                subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Device Removed", f"Forgot {name}"], check=False)
                GLib.idle_add(self.poll_devices)
            threading.Thread(target=worker, daemon=True).start()

        btn_action.connect("clicked", do_toggle_connect)
        btn_forget.connect("clicked", do_forget)
        btn_close.connect("clicked", lambda w: self.clear_overlay())

        btn_box.pack_start(btn_action, True, True, 0)
        btn_box.pack_start(btn_forget, True, True, 0)
        btn_box.pack_start(btn_close, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()

    def on_available_row_clicked(self, widget, event, dev):
        mac = dev["mac"]
        name = dev["name"]

        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card-overlay")

        title = Gtk.Label(label=f"Pair with '{name}'?", xalign=0)
        title.get_style_context().add_class("bt-title")
        card.pack_start(title, False, False, 0)

        lbl = Gtk.Label(label=f"Address: {mac}", xalign=0)
        lbl.get_style_context().add_class("stat-label")
        card.pack_start(lbl, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_pair = Gtk.Button(label="Pair & Connect")
        btn_pair.get_style_context().add_class("action-btn")
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.get_style_context().add_class("action-btn")

        def do_pair(w):
            self.clear_overlay()
            def worker():
                subprocess.run(["notify-send", "-a", "Bluetooth", "-i", "bluetooth", "Pairing", f"Pairing with {name}..."], check=False)
                subprocess.run(["bluetoothctl", "trust", mac], check=False)
                subprocess.run(["bluetoothctl", "pair", mac], check=False)
                subprocess.run(["bluetoothctl", "connect", mac], check=False)
                GLib.idle_add(self.poll_devices)
            threading.Thread(target=worker, daemon=True).start()

        btn_pair.connect("clicked", do_pair)
        btn_cancel.connect("clicked", lambda w: self.clear_overlay())

        btn_box.pack_start(btn_pair, True, True, 0)
        btn_box.pack_start(btn_cancel, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()

    def clear_overlay(self):
        for child in self.overlay_container.get_children():
            self.overlay_container.remove(child)


def start_ipc_server(win):
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_sock.bind(SOCKET_PATH)
    server_sock.listen(5)

    def listen_loop():
        while True:
            try:
                conn, _ = server_sock.accept()
                msg = conn.recv(1024).decode().strip()
                conn.close()
                if msg in ("toggle", "close", "quit"):
                    GLib.idle_add(win.close)
                    break
            except Exception:
                break

    threading.Thread(target=listen_loop, daemon=True).start()


def try_toggle_existing():
    if os.path.exists(SOCKET_PATH):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(SOCKET_PATH)
            client.sendall(b"toggle\n")
            client.close()
            return True
        except Exception:
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
    return False


def main():
    if try_toggle_existing():
        sys.exit(0)

    win = BluetoothControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
