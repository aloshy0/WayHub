#!/usr/bin/env python3
"""
Waybar Display & Brightness Control Center Popup
A modern, dark-themed Display control center built with GTK3 & GtkLayerShell.
"""

import os
import sys
import socket
import threading
import subprocess
import time
import math

import cairo

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

SOCKET_PATH = f"/tmp/waybar_brightness_menu_{os.getuid()}.sock"

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

.bright-window {
    background-color: rgba(27, 34, 42, 0.98);
    border: 1px solid #334050;
    border-radius: 16px;
    padding: 18px 20px;
    color: #e2e8f0;
}

/* Header */
.header-box {
    margin-bottom: 14px;
}

.bright-icon-large {
    font-size: 28px;
    color: #ffffff;
    min-width: 36px;
    margin-right: 12px;
}

.bright-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.bright-subtitle {
    font-size: 9.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.6px;
}

/* Switches */
switch {
    background-color: #1e252f;
    border: 1px solid #3a4758;
    border-radius: 16px;
    min-width: 46px;
    min-height: 24px;
    padding: 2px;
    color: transparent;
    font-size: 0px;
    text-shadow: none;
    outline: none;
}

switch:checked {
    background-color: #384656;
    border-color: #4f6176;
}

switch slider {
    background-color: #e2d9c8;
    border-radius: 50%;
    min-width: 20px;
    min-height: 20px;
    margin: 1px;
}

switch:checked slider {
    background-color: #e2d9c8;
}

/* Section Titles */
.section-title {
    font-size: 10px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.6px;
}

.section-value {
    font-size: 11.5px;
    font-weight: 600;
    color: #94a3b8;
}

/* Sliders / Scales */
scale {
    min-height: 24px;
}

scale trough {
    background-color: #313d4d;
    border-radius: 3px;
    min-height: 4px;
    min-width: 4px;
}

scale highlight {
    background-color: #e2d9c8;
    border-radius: 3px;
    min-height: 4px;
}

scale slider {
    background-color: #e2d9c8;
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
    margin: -5px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
}

scale slider:hover {
    background-color: #ffffff;
}

/* Preset Buttons */
.preset-btn {
    background-color: #202834;
    border: 1px solid #2d3848;
    border-radius: 8px;
    padding: 8px 10px;
    color: #c5cdd9;
    font-size: 12px;
    font-weight: 600;
    transition: all 120ms ease;
}

.preset-btn:hover {
    background-color: #2b3547;
    border-color: #3e4c63;
    color: #ffffff;
}

.preset-btn.active {
    background-color: #2b3547;
    border-color: #4a5c78;
    color: #ffffff;
}

/* Separator */
.divider {
    background-color: #2c3645;
    min-height: 1px;
    margin: 10px 0;
}
"""


class BrightnessControlCenter(Gtk.Window):
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

        self.updating_ui = False
        self.current_brightness = 50
        self.device_name = "amdgpu_bl2"
        self.max_brightness = 62451

        self.init_ui()
        self.apply_css()

        # Initial data poll
        self.refresh_state()

        # Auto refresh timer
        GLib.timeout_add(2000, self.refresh_state)

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
        self.card.get_style_context().add_class("bright-window")
        self.card.set_halign(Gtk.Align.END)
        self.card.set_valign(Gtk.Align.START)
        self.card.set_margin_top(36)
        self.card.set_margin_end(12)
        self.card.set_size_request(410, -1)
        align_box.pack_start(self.card, False, False, 0)

        main_box = self.card

        # 1. Header Box
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.get_style_context().add_class("header-box")
        main_box.pack_start(header_box, False, False, 0)

        self.header_icon = Gtk.Label(label="󰃠")
        self.header_icon.get_style_context().add_class("bright-icon-large")
        self.header_icon.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(self.header_icon, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(label="Display", xalign=0)
        self.lbl_title.get_style_context().add_class("bright-title")
        self.lbl_subtitle = Gtk.Label(label="INTERNAL BACKLIGHT", xalign=0)
        self.lbl_subtitle.get_style_context().add_class("bright-subtitle")
        title_box.pack_start(self.lbl_title, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Power / Dim Switch
        self.power_switch = Gtk.Switch()
        self.power_switch.set_active(True)
        self.power_switch.set_valign(Gtk.Align.CENTER)
        self.power_switch.connect("state-set", self.on_power_switch_toggled)
        header_box.pack_end(self.power_switch, False, False, 0)

        # Separator
        div0 = Gtk.Box()
        div0.get_style_context().add_class("divider")
        main_box.pack_start(div0, False, False, 2)

        # 2. BRIGHTNESS SLIDER SECTION
        bright_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_br_title = Gtk.Label(label="BRIGHTNESS", xalign=0)
        lbl_br_title.get_style_context().add_class("section-title")
        self.lbl_br_val = Gtk.Label(label="44%", xalign=1)
        self.lbl_br_val.get_style_context().add_class("section-value")
        bright_hdr.pack_start(lbl_br_title, True, True, 0)
        bright_hdr.pack_end(self.lbl_br_val, False, False, 0)
        main_box.pack_start(bright_hdr, False, False, 0)

        self.scale_bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.scale_bright.set_draw_value(False)
        self.scale_bright.connect("value-changed", self.on_bright_changed)
        main_box.pack_start(self.scale_bright, False, False, 4)

        # Separator
        div1 = Gtk.Box()
        div1.get_style_context().add_class("divider")
        main_box.pack_start(div1, False, False, 4)

        # 3. QUICK PRESETS
        lbl_pre_title = Gtk.Label(label="PRESETS", xalign=0)
        lbl_pre_title.get_style_context().add_class("section-title")
        main_box.pack_start(lbl_pre_title, False, False, 2)

        presets_grid = Gtk.Grid()
        presets_grid.set_column_spacing(8)
        presets_grid.set_row_spacing(8)
        presets_grid.set_hexpand(True)
        main_box.pack_start(presets_grid, False, False, 4)

        presets = [
            ("󰃞 25%", 25, 0, 0),
            ("󰃟 50%", 50, 1, 0),
            ("󰃠 75%", 75, 0, 1),
            ("󰃡 100%", 100, 1, 1),
        ]

        self.preset_btns = {}
        for label, val, col, row in presets:
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("preset-btn")
            btn.set_hexpand(True)
            btn.connect("clicked", lambda w, v=val: self.set_preset_brightness(v))
            presets_grid.attach(btn, col, row, 1, 1)
            self.preset_btns[val] = btn

    def on_power_switch_toggled(self, switch, state):
        if self.updating_ui:
            return
        if not state:
            # Dim down to min (5%)
            subprocess.run(["brightnessctl", "set", "5%"], check=False)
            self.refresh_state()
        else:
            # Restore to 50%
            subprocess.run(["brightnessctl", "set", "50%"], check=False)
            self.refresh_state()
        return False

    def on_bright_changed(self, scale):
        if self.updating_ui:
            return
        val = int(scale.get_value())
        self.lbl_br_val.set_label(f"{val}%")
        subprocess.run(["brightnessctl", "set", f"{val}%"], check=False)
        self.update_header_icon(val)

    def set_preset_brightness(self, val):
        subprocess.run(["brightnessctl", "set", f"{val}%"], check=False)
        self.refresh_state()

    def update_header_icon(self, val):
        if val <= 33:
            self.header_icon.set_label("󰃞")
        elif val <= 66:
            self.header_icon.set_label("󰃟")
        else:
            self.header_icon.set_label("󰃠")

    def refresh_state(self):
        def worker():
            pct = 50
            dev = "amdgpu_bl2"
            max_steps = 62451
            try:
                b_out = subprocess.check_output(["brightnessctl", "-m"], text=True, stderr=subprocess.DEVNULL).strip()
                parts = b_out.split(",")
                if len(parts) >= 5:
                    dev = parts[0]
                    pct = int(parts[3].replace("%", ""))
                    max_steps = int(parts[4])
            except Exception:
                pass
            GLib.idle_add(self.update_ui, pct, dev, max_steps)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def update_ui(self, pct, dev, max_steps):
        self.updating_ui = True
        self.current_brightness = pct
        self.device_name = dev
        self.max_brightness = max_steps

        self.scale_bright.set_value(pct)
        self.lbl_br_val.set_label(f"{pct}%")
        self.lbl_subtitle.set_label(f"{dev.upper()} • {pct}%")

        self.power_switch.set_active(pct > 5)
        self.update_header_icon(pct)

        # Highlight preset if exact match
        for p_val, btn in self.preset_btns.items():
            if abs(p_val - pct) <= 2:
                btn.get_style_context().add_class("active")
            else:
                btn.get_style_context().remove_class("active")

        self.updating_ui = False


# -----------------------------------------------------------------------------
# Single Instance IPC Server & Client
# -----------------------------------------------------------------------------
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

    win = BrightnessControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
