#!/usr/bin/env python3
"""
Waybar Power & Battery Profile Selector Popup.
Built with GTK3 & GtkLayerShell to match the other Waybar control center popups.
"""

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
        "color": "#ff9f43",
    },
    {
        "id": "balanced",
        "icon": "󰾅",
        "name": "Balanced",
        "color": "#55e6a5",
    },
    {
        "id": "performance",
        "icon": "󰓅",
        "name": "Performance",
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

.hz-value {
    font-size: 12px;
    font-weight: 700;
    color: #55e6a5;
}

.hz-value.hz-60 {
    color: #cbd5e1;
}

.hz-value.hz-locked {
    color: #ff9f43;
}

.hz-caption {
    font-size: 8.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.1px;
}

.hz-caption.hz-locked {
    color: #ff9f43;
}

switch,
switch trough {
    background-color: #1e252f;
    border: 1px solid #3a4758;
    border-radius: 16px;
    min-width: 44px;
    min-height: 22px;
    padding: 2px;
    color: transparent;
    font-size: 0px;
    text-shadow: none;
    outline: none;
    box-shadow: none;
}

switch:checked,
switch:checked trough {
    background-color: #203b35;
    border-color: #55e6a5;
}

switch slider {
    background-color: #cbd5e1;
    border-radius: 50%;
    min-width: 18px;
    min-height: 18px;
    margin: 1px;
    border: none;
    box-shadow: none;
}

switch:checked slider {
    background-color: #55e6a5;
}

switch:disabled,
switch:disabled trough {
    background-color: #192029;
    border-color: #2a3340;
    opacity: 0.45;
}

switch:disabled slider {
    background-color: #64748b;
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

.profile-btn:disabled {
    background-color: #192029;
    border-color: #252e3b;
    opacity: 0.45;
}

.profile-btn:disabled:hover {
    background-color: #192029;
    border-color: #252e3b;
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

.profile-eta {
    font-size: 12.5px;
    font-weight: 700;
    color: #cbd5e1;
}

.profile-meta {
    font-size: 10px;
    font-weight: 600;
    color: #7d8799;
}

.profile-btn:disabled .profile-name,
.profile-btn:disabled .profile-eta {
    color: #566173;
}

.profile-btn.active-power-saver {
    background-color: #2d2721;
    border-color: #ff9f43;
}

.profile-btn.active-power-saver .profile-icon,
.profile-btn.active-power-saver .profile-eta {
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
.profile-btn.active-balanced .profile-eta {
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
.profile-btn.active-performance .profile-eta {
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

        self.updating_ui = False
        self.active_profile = "balanced"
        self.current_cap = None
        self.current_energy_wh = None
        self.current_hz = 144
        self.last_base_compute_w = battery_helper.DEFAULT_BASE_COMPUTE_W
        self.last_live_watts = None
        self.last_is_discharging = False
        self.pending_profile = None
        self.pending_until = 0.0
        self.pending_hz = None
        self.pending_hz_until = 0.0
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
        self.card.set_size_request(420, -1)
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

        # Refresh Rate Switcher (right side of header)
        hz_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hz_box.set_valign(Gtk.Align.CENTER)
        hz_label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        hz_label_box.set_valign(Gtk.Align.CENTER)
        self.lbl_hz = Gtk.Label(label="144 Hz", xalign=1)
        self.lbl_hz.get_style_context().add_class("hz-value")
        self.lbl_hz_sub = Gtk.Label(label="MAX RATE", xalign=1)
        self.lbl_hz_sub.get_style_context().add_class("hz-caption")
        hz_label_box.pack_start(self.lbl_hz, False, False, 0)
        hz_label_box.pack_start(self.lbl_hz_sub, False, False, 0)
        hz_box.pack_start(hz_label_box, False, False, 0)

        self.hz_switch = Gtk.Switch()
        self.hz_switch.set_valign(Gtk.Align.CENTER)
        self.hz_switch.set_active(True)
        self.hz_switch.connect("state-set", self.on_hz_switch_toggled)
        hz_box.pack_start(self.hz_switch, False, False, 0)
        header_box.pack_start(hz_box, False, False, 0)

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

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            icon_lbl = Gtk.Label(label=prof["icon"])
            icon_lbl.get_style_context().add_class("profile-icon")
            icon_lbl.set_valign(Gtk.Align.CENTER)
            row.pack_start(icon_lbl, False, False, 0)

            name_lbl = Gtk.Label(label=prof["name"], xalign=0)
            name_lbl.get_style_context().add_class("profile-name")
            name_lbl.set_valign(Gtk.Align.CENTER)
            row.pack_start(name_lbl, True, True, 0)

            right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            right_box.set_valign(Gtk.Align.CENTER)
            eta_lbl = Gtk.Label(label="--", xalign=1)
            eta_lbl.get_style_context().add_class("profile-eta")
            meta_lbl = Gtk.Label(label="", xalign=1)
            meta_lbl.get_style_context().add_class("profile-meta")
            right_box.pack_start(eta_lbl, False, False, 0)
            right_box.pack_start(meta_lbl, False, False, 0)
            row.pack_start(right_box, False, False, 0)

            btn.add(row)
            profiles_box.pack_start(btn, False, False, 0)
            self.profile_widgets[prof["id"]] = (btn, eta_lbl, meta_lbl)

        self.lbl_footer = Gtk.Label(label="", xalign=0)
        self.lbl_footer.get_style_context().add_class("footer-stats")
        self.card.pack_start(self.lbl_footer, False, False, 0)

    def on_profile_clicked(self, profile_id):
        if profile_id == "performance" and not battery_helper.is_performance_allowed(self.current_cap):
            return

        self.pending_profile = profile_id
        self.pending_until = time.monotonic() + 2.0
        target_hz = (
            60
            if (profile_id == "power-saver" or not battery_helper.is_high_refresh_allowed(self.current_cap))
            else 144
        )
        self.pending_hz = target_hz
        self.pending_hz_until = time.monotonic() + 2.0
        self.apply_profile_visuals(profile_id)
        self.apply_hz_visuals(target_hz)

        def worker():
            ok = set_system_power_profile(profile_id)
            if not ok:
                self.pending_profile = None
                self.pending_hz = None
            GLib.idle_add(self.refresh_state)

        threading.Thread(target=worker, daemon=True).start()

    def on_hz_switch_toggled(self, switch, state):
        if self.updating_ui:
            return False

        target_hz = 144 if state else 60
        if target_hz > 60 and not battery_helper.is_high_refresh_allowed(self.current_cap):
            self.updating_ui = True
            switch.set_active(False)
            self.updating_ui = False
            self.apply_hz_visuals(60)
            return True

        self.pending_hz = target_hz
        self.pending_hz_until = time.monotonic() + 2.0
        self.apply_hz_visuals(target_hz)

        def worker():
            ok = battery_helper.set_manual_refresh_rate(
                target_hz, notify_waybar=True, cap=self.current_cap
            )
            if not ok:
                self.pending_hz = None
            GLib.idle_add(self.refresh_state)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def apply_hz_visuals(self, refresh_hz):
        hz_allowed = battery_helper.is_high_refresh_allowed(self.current_cap)
        val_ctx = self.lbl_hz.get_style_context()
        sub_ctx = self.lbl_hz_sub.get_style_context()
        for ctx in (val_ctx, sub_ctx):
            ctx.remove_class("hz-60")
            ctx.remove_class("hz-locked")

        self.updating_ui = True
        if not hz_allowed:
            self.current_hz = 60
            self.hz_switch.set_sensitive(False)
            self.hz_switch.set_active(False)
            self.lbl_hz.set_label("60 Hz 󰌾")
            self.lbl_hz_sub.set_label(f"LOCKED <{battery_helper.REFRESH_LOCK_THRESHOLD}%")
            val_ctx.add_class("hz-locked")
            sub_ctx.add_class("hz-locked")
        else:
            self.hz_switch.set_sensitive(True)
            is_high = refresh_hz is not None and refresh_hz > 75
            hz_display = refresh_hz if refresh_hz else (144 if is_high else 60)
            self.current_hz = hz_display
            self.hz_switch.set_active(is_high)
            self.lbl_hz.set_label(f"{hz_display} Hz")
            self.lbl_hz_sub.set_label("MAX RATE" if is_high else "POWER SAVE")
            if not is_high:
                val_ctx.add_class("hz-60")
        self.updating_ui = False
        self.update_prediction_labels()

    def apply_profile_visuals(self, profile_id):
        self.active_profile = profile_id

        header_ctx = self.header_icon.get_style_context()
        for cls in ("power-saver", "balanced", "performance"):
            header_ctx.remove_class(cls)
        if profile_id in ("power-saver", "balanced", "performance"):
            header_ctx.add_class(profile_id)

        perf_allowed = battery_helper.is_performance_allowed(self.current_cap)
        for pid, (btn, _eta_lbl, _meta_lbl) in self.profile_widgets.items():
            ctx = btn.get_style_context()
            active_cls = f"active-{pid}"
            if pid == "performance" and not perf_allowed:
                btn.set_sensitive(False)
                btn.set_tooltip_text(f"Unavailable below {battery_helper.PERFORMANCE_MIN_CHARGE}% battery")
                ctx.remove_class(active_cls)
                continue

            btn.set_sensitive(True)
            btn.set_tooltip_text(None)
            if pid == profile_id:
                ctx.add_class(active_cls)
            else:
                ctx.remove_class(active_cls)

        self.update_prediction_labels()

    def update_prediction_labels(self):
        preds = battery_helper.compute_mode_predictions(
            self.last_base_compute_w,
            self.active_profile,
            self.current_hz,
            self.current_cap,
            self.current_energy_wh,
        )
        perf_allowed = battery_helper.is_performance_allowed(self.current_cap)
        for pid, (_btn, eta_lbl, meta_lbl) in self.profile_widgets.items():
            if pid == "performance" and not perf_allowed:
                eta_lbl.set_label("--")
                meta_lbl.set_label(f"LOCKED <{battery_helper.PERFORMANCE_MIN_CHARGE}%")
                continue
            pred = preds.get(pid)
            if not pred:
                eta_lbl.set_label("--")
                meta_lbl.set_label("")
                continue
            eta_str = pred.get("eta")
            eta_lbl.set_label(eta_str if eta_str and eta_str != "N/A" else "--")
            active_prefix = "ACTIVE • " if pid == self.active_profile else ""
            meta_lbl.set_label(f"{active_prefix}{pred['watts']:.1f} W • {pred['hz']} Hz")

    def _on_poll_timer(self):
        self.refresh_state()
        return True

    def refresh_state(self):
        def worker():
            status, cap, estimated, energy_now, energy_full, cycles = battery_helper.read_battery_summary()
            profile = battery_helper.get_power_profile()
            refresh_hz = battery_helper.get_current_refresh_hz()
            estimates = battery_helper.estimate_mode_runtimes(
                profile, refresh_hz, cap=cap, energy_now=energy_now, persist=False
            )
            GLib.idle_add(
                self.update_ui,
                profile,
                cap,
                estimated,
                status,
                energy_now,
                energy_full,
                cycles,
                refresh_hz,
                estimates,
            )

        threading.Thread(target=worker, daemon=True).start()
        return False

    def update_ui(self, profile, cap, estimated, status, energy_now, energy_full, cycles, refresh_hz, estimates=None):
        self.current_cap = cap
        if estimates:
            self.last_base_compute_w = estimates["base_compute_w"]
            self.last_live_watts = estimates["live_watts"]
            self.last_is_discharging = estimates["is_discharging"]
            self.current_energy_wh = estimates["energy_wh"]
        elif energy_now is not None:
            self.current_energy_wh = energy_now / 1_000_000
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
        if self.last_is_discharging and self.last_live_watts is not None:
            footer_parts.append(f"{self.last_live_watts:.1f} W live")
        else:
            footer_parts.append(f"~{self.last_base_compute_w:.1f} W strategy")
        if cycles is not None and cycles > 0:
            footer_parts.append(f"{cycles} cycles")
        if refresh_hz:
            footer_parts.append(f"{refresh_hz} Hz")
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

        effective_hz = (
            self.pending_hz
            if self.pending_hz and now < self.pending_hz_until
            else refresh_hz
        )
        if refresh_hz is not None and self.pending_hz is not None and abs(refresh_hz - self.pending_hz) <= 1:
            self.pending_hz = None
        self.apply_hz_visuals(effective_hz)
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
