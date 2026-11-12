#!/usr/bin/env python3
"""
Waybar Power & Battery Profile Selector Popup.
Built with GTK3 & GtkLayerShell to match the other Waybar control center popups.
"""

import glob
import math
import os
import signal
import socket
import sys
import threading
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

import battery as battery_helper

SOCKET_PATH = f"/tmp/waybar_power_menu_{os.getuid()}.sock"

PROFILES = [
    {
        "id": "power-saver",
        "icon": "󰌪",
        "name": "Eco (Power Saver)",
        "desc": "Lower power draw & cooler operation",
        "color": "#ff9f43",
    },
    {
        "id": "balanced",
        "icon": "󰾅",
        "name": "Balanced",
        "desc": "Adaptive performance & battery efficiency",
        "color": "#55e6a5",
    },
    {
        "id": "performance",
        "icon": "󰓅",
        "name": "Performance",
        "desc": "Maximum CPU boost & thermal headroom",
        "color": "#ff5c5c",
    },
]

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

.power-window {
    background-color: #1b222a;
    background: #1b222a;
    border: 1px solid #334050;
    border-radius: 16px;
    padding: 18px 20px;
    color: #e2e8f0;
}

.header-box {
    margin-bottom: 12px;
}

.power-icon-large {
    font-size: 26px;
    color: #55e6a5;
    min-width: 34px;
    margin-right: 12px;
}

.power-icon-large.power-saver {
    color: #ff9f43;
}

.power-icon-large.balanced {
    color: #55e6a5;
}

.power-icon-large.performance {
    color: #ff5c5c;
}

.power-title {
    font-size: 15.5px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.power-subtitle {
    font-size: 9.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.4px;
}

.divider {
    background-color: #2c3645;
    min-height: 1px;
    margin: 8px 0 10px 0;
}

.section-title {
    font-size: 10px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.6px;
    margin-bottom: 4px;
}

.profile-btn {
    background-color: #202834;
    border: 1px solid #2d3848;
    border-radius: 10px;
    padding: 10px 12px;
    transition: all 120ms ease;
}

.profile-btn:hover {
    background-color: #293444;
    border-color: #3e4c63;
}

.profile-icon {
    font-size: 18px;
    min-width: 24px;
    color: #94a3b8;
    margin-right: 10px;
}

.profile-name {
    font-size: 13px;
    font-weight: 700;
    color: #e2e8f0;
}

.profile-desc {
    font-size: 10.5px;
    color: #8492a6;
}

.profile-badge {
    font-size: 11px;
    font-weight: 700;
    color: transparent;
    min-width: 18px;
}

.profile-btn.active-power-saver {
    background-color: #2d2721;
    border-color: #ff9f43;
}

.profile-btn.active-power-saver .profile-icon,
.profile-btn.active-power-saver .profile-badge {
    color: #ff9f43;
}

.profile-btn.active-power-saver .profile-name {
    color: #ffffff;
}

.profile-btn.active-balanced {
    background-color: #1f302c;
    border-color: #55e6a5;
}

.profile-btn.active-balanced .profile-icon,
.profile-btn.active-balanced .profile-badge {
    color: #55e6a5;
}

.profile-btn.active-balanced .profile-name {
    color: #ffffff;
}

.profile-btn.active-performance {
    background-color: #312126;
    border-color: #ff5c5c;
}

.profile-btn.active-performance .profile-icon,
.profile-btn.active-performance .profile-badge {
    color: #ff5c5c;
}

.profile-btn.active-performance .profile-name {
    color: #ffffff;
}

.footer-stats {
    margin-top: 8px;
    font-size: 10.5px;
    color: #7d8799;
}
"""


def set_system_power_profile(profile_id):
    """Apply active power profile via shared battery helper."""
    return battery_helper.set_power_profile(profile_id, notify_waybar=True)


class PowerControlCenter(Gtk.Window):
    """Floating LayerShell popup for switching Waybar battery power profiles."""

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

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

        self.active_profile = "balanced"
        self.pending_profile = None
        self.pending_until = 0.0
        self.profile_widgets = {}

        self.init_ui()
        self.apply_css()

        self.refresh_state()
        GLib.timeout_add(2000, self._on_poll_timer)

    def on_window_draw(self, widget, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()

        if hasattr(self, "card"):
            alloc = self.card.get_allocation()
            if alloc.width > 1 and alloc.height > 1:
                cr.set_operator(cairo.OPERATOR_OVER)
                radius = 16.0
                x = float(alloc.x)
                y = float(alloc.y)
                w = float(alloc.width)
                h = float(alloc.height)

                cr.new_sub_path()
                cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
                cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
                cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
                cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
                cr.close_path()

                cr.set_source_rgb(27 / 255.0, 34 / 255.0, 42 / 255.0)
                cr.fill_preserve()

                cr.set_source_rgb(51 / 255.0, 64 / 255.0, 80 / 255.0)
                cr.set_line_width(1.0)
                cr.stroke()

        return False

    def on_backdrop_clicked(self, widget, event):
        alloc = self.card.get_allocation()
        if (
            alloc.x <= event.x <= alloc.x + alloc.width
            and alloc.y <= event.y <= alloc.y + alloc.height
        ):
            return False
        self.close()
        return True

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def init_ui(self):
        self.backdrop = Gtk.EventBox()
        self.backdrop.get_style_context().add_class("backdrop")
        self.backdrop.set_above_child(False)
        self.backdrop.connect("button-press-event", self.on_backdrop_clicked)
        self.add(self.backdrop)

        align_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.backdrop.add(align_box)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("power-window")
        self.card.set_halign(Gtk.Align.END)
        self.card.set_valign(Gtk.Align.START)
        self.card.set_margin_top(38)
        self.card.set_margin_end(12)
        self.card.set_size_request(365, -1)
        align_box.pack_start(self.card, False, False, 0)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.get_style_context().add_class("header-box")
        self.card.pack_start(header_box, False, False, 0)

        self.header_icon = Gtk.Label(label="󰁹")
        self.header_icon.get_style_context().add_class("power-icon-large")
        self.header_icon.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(self.header_icon, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(label="Power & Battery", xalign=0)
        self.lbl_title.get_style_context().add_class("power-title")
        self.lbl_subtitle = Gtk.Label(label="LOADING...", xalign=0)
        self.lbl_subtitle.get_style_context().add_class("power-subtitle")
        title_box.pack_start(self.lbl_title, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        div = Gtk.Box()
        div.get_style_context().add_class("divider")
        self.card.pack_start(div, False, False, 0)

        lbl_section = Gtk.Label(label="POWER PROFILE", xalign=0)
        lbl_section.get_style_context().add_class("section-title")
        self.card.pack_start(lbl_section, False, False, 2)

        profiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.card.pack_start(profiles_box, False, False, 4)

        for prof in PROFILES:
            btn = Gtk.Button()
            btn.get_style_context().add_class("profile-btn")
            btn.connect("clicked", lambda _w, pid=prof["id"]: self.on_profile_clicked(pid))

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            icon_lbl = Gtk.Label(label=prof["icon"])
            icon_lbl.get_style_context().add_class("profile-icon")
            icon_lbl.set_valign(Gtk.Align.CENTER)
            row.pack_start(icon_lbl, False, False, 0)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name_lbl = Gtk.Label(label=prof["name"], xalign=0)
            name_lbl.get_style_context().add_class("profile-name")
            desc_lbl = Gtk.Label(label=prof["desc"], xalign=0)
            desc_lbl.get_style_context().add_class("profile-desc")
            text_box.pack_start(name_lbl, False, False, 0)
            text_box.pack_start(desc_lbl, False, False, 0)
            row.pack_start(text_box, True, True, 0)

            badge_lbl = Gtk.Label(label="●", xalign=1)
            badge_lbl.get_style_context().add_class("profile-badge")
            badge_lbl.set_valign(Gtk.Align.CENTER)
            row.pack_start(badge_lbl, False, False, 0)

            btn.add(row)
            profiles_box.pack_start(btn, False, False, 0)
            self.profile_widgets[prof["id"]] = (btn, badge_lbl)

        self.lbl_footer = Gtk.Label(label="", xalign=0)
        self.lbl_footer.get_style_context().add_class("footer-stats")
        self.card.pack_start(self.lbl_footer, False, False, 0)

    def on_profile_clicked(self, profile_id):
        self.pending_profile = profile_id
        self.pending_until = time.monotonic() + 2.0
        self.apply_profile_visuals(profile_id)

        def worker():
            set_system_power_profile(profile_id)
            GLib.idle_add(self.refresh_state)

        threading.Thread(target=worker, daemon=True).start()

    def apply_profile_visuals(self, profile_id):
        self.active_profile = profile_id

        header_ctx = self.header_icon.get_style_context()
        for cls in ("power-saver", "balanced", "performance"):
            header_ctx.remove_class(cls)
        if profile_id in ("power-saver", "balanced", "performance"):
            header_ctx.add_class(profile_id)

        for pid, (btn, badge) in self.profile_widgets.items():
            ctx = btn.get_style_context()
            active_cls = f"active-{pid}"
            if pid == profile_id:
                ctx.add_class(active_cls)
                badge.set_label("ACTIVE")
            else:
                ctx.remove_class(active_cls)
                badge.set_label("")

    def _on_poll_timer(self):
        self.refresh_state()
        return True

    def refresh_state(self):
        def worker():
            bat_paths = sorted(glob.glob("/sys/class/power_supply/BAT*"))
            bat_path = bat_paths[0] if bat_paths else "/sys/class/power_supply/BAT0"
            status = battery_helper._read_sysfs(os.path.join(bat_path, "status")) or "Unknown"
            cap, estimated, energy_now, energy_full = battery_helper._compute_capacity(bat_path)
            cycles = battery_helper._read_int(os.path.join(bat_path, "cycle_count"))
            profile = battery_helper.get_power_profile()
            GLib.idle_add(self.update_ui, profile, cap, estimated, status, energy_now, energy_full, cycles)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def update_ui(self, profile, cap, estimated, status, energy_now, energy_full, cycles):
        icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
        if status == "Charging":
            self.header_icon.set_label("󰂄")
        elif cap is None:
            self.header_icon.set_label("󰂑")
        else:
            self.header_icon.set_label(icons[min(9, max(0, cap // 10))])

        cap_label = "?%" if cap is None else (f"~{cap}%" if estimated else f"{cap}%")
        self.lbl_subtitle.set_label(f"{cap_label} • {status.upper()}")

        footer_parts = []
        if energy_now is not None and energy_full:
            footer_parts.append(f"{energy_now / 1_000_000:.1f} / {energy_full / 1_000_000:.1f} Wh")
        if cycles is not None and cycles > 0:
            footer_parts.append(f"{cycles} cycles")
        self.lbl_footer.set_label(" • ".join(footer_parts))
        self.lbl_footer.set_visible(bool(footer_parts))

        now = time.monotonic()
        effective_profile = (
            self.pending_profile
            if self.pending_profile and now < self.pending_until
            else profile
        )
        if profile == self.pending_profile:
            self.pending_profile = None
        self.apply_profile_visuals(effective_profile)
        return False


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
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if try_toggle_existing():
        sys.exit(0)

    win = PowerControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
