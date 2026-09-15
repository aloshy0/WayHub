#!/usr/bin/env python3
"""
Waybar Audio & Brightness Control Center Popup
A modern, dark-themed Audio & Display control center built with GTK3 & GtkLayerShell.
"""

import os
import sys
import json
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

SOCKET_PATH = f"/tmp/waybar_audio_menu_{os.getuid()}.sock"

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

.audio-window {
    background-color: #1b222a;
    background: #1b222a;
    border: 1px solid #334050;
    border-radius: 16px;
    padding: 18px 20px;
    color: #e2e8f0;
}

/* Header */
.header-box {
    margin-bottom: 14px;
}

.audio-icon-large {
    font-size: 28px;
    color: #ffffff;
    min-width: 36px;
    margin-right: 12px;
}

.audio-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.audio-subtitle {
    font-size: 9.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.6px;
}

/* Switches */
switch,
switch trough {
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
    box-shadow: none;
}

switch:checked,
switch:checked trough {
    background-color: #384656;
    border-color: #4f6176;
}

switch slider {
    background-color: #e2d9c8;
    border-radius: 50%;
    min-width: 20px;
    min-height: 20px;
    margin: 1px;
    border: none;
    box-shadow: none;
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

/* Device Lists */
.device-row {
    background-color: transparent;
    border-radius: 8px;
    padding: 7px 10px;
    margin: 1px 0;
    transition: all 120ms ease;
    color: #94a3b8;
}

.device-row:hover {
    background-color: rgba(255, 255, 255, 0.04);
    color: #e2e8f0;
}

.device-row-selected {
    background-color: #2b3547;
    border: 1px solid #3d4b63;
    border-radius: 8px;
    padding: 7px 10px;
    margin: 1px 0;
    color: #ffffff;
    font-weight: 600;
}

.device-icon {
    font-size: 14px;
    margin-right: 10px;
}

.device-label {
    font-size: 12.5px;
}

/* App Stream Card */
.app-card {
    background-color: #202834;
    border: 1px solid #2d3848;
    border-radius: 8px;
    padding: 8px 10px;
    margin: 3px 0;
}

.app-name {
    font-size: 12px;
    font-weight: 600;
    color: #e2e8f0;
}

.app-vol {
    font-size: 10.5px;
    color: #7d8799;
}

/* Separator */
.divider {
    background-color: #2c3645;
    min-height: 1px;
    margin: 10px 0;
}

/* Scrollable */
scrolledwindow undershoot.top,
scrolledwindow undershoot.bottom {
    background: none;
}
"""


class AudioControlCenter(Gtk.Window):
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

        # State suppression flags to avoid recursive callbacks
        self.updating_ui = False
        self.default_sink = ""
        self.default_source = ""
        self.output_muted = False
        self.input_muted = False

        self.init_ui()
        self.apply_css()

        # Initial data poll
        self.refresh_all_state()

        # Auto refresh timer
        GLib.timeout_add(1800, self.refresh_all_state)

    def on_window_draw(self, widget, cr):
        # 1. Clear fullscreen backdrop to transparent
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()

        # 2. Paint 100% solid opaque card with Cairo
        if hasattr(self, 'card'):
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

                # Solid dark card background #1b222a
                cr.set_source_rgb(27 / 255.0, 34 / 255.0, 42 / 255.0)
                cr.fill_preserve()

                # Border #334050
                cr.set_source_rgb(51 / 255.0, 64 / 255.0, 80 / 255.0)
                cr.set_line_width(1.0)
                cr.stroke()

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
        self.card.get_style_context().add_class("audio-window")
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

        self.header_icon = Gtk.Label(label="")
        self.header_icon.get_style_context().add_class("audio-icon-large")
        self.header_icon.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(self.header_icon, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        self.lbl_title = Gtk.Label(label="Audio", xalign=0)
        self.lbl_title.get_style_context().add_class("audio-title")
        self.lbl_subtitle = Gtk.Label(label="DEFAULT SINK", xalign=0)
        self.lbl_subtitle.get_style_context().add_class("audio-subtitle")
        title_box.pack_start(self.lbl_title, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Master Power/Mute Switch
        self.master_switch = Gtk.Switch()
        self.master_switch.set_active(True)
        self.master_switch.set_valign(Gtk.Align.CENTER)
        self.master_switch.connect("state-set", self.on_master_switch_toggled)
        header_box.pack_end(self.master_switch, False, False, 0)

        # Separator
        div0 = Gtk.Box()
        div0.get_style_context().add_class("divider")
        main_box.pack_start(div0, False, False, 2)

        # 2. OUTPUT SECTION (Speakers / Headphones)
        out_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_out_title = Gtk.Label(label="OUTPUT", xalign=0)
        lbl_out_title.get_style_context().add_class("section-title")
        self.lbl_out_val = Gtk.Label(label="100%", xalign=1)
        self.lbl_out_val.get_style_context().add_class("section-value")
        out_hdr.pack_start(lbl_out_title, True, True, 0)
        out_hdr.pack_end(self.lbl_out_val, False, False, 0)
        main_box.pack_start(out_hdr, False, False, 0)

        # Output Volume Slider
        self.scale_out = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.scale_out.set_draw_value(False)
        self.scale_out.connect("value-changed", self.on_output_volume_changed)
        main_box.pack_start(self.scale_out, False, False, 2)

        # Output Devices Container
        self.out_devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        main_box.pack_start(self.out_devices_box, False, False, 2)

        # Separator
        div2 = Gtk.Box()
        div2.get_style_context().add_class("divider")
        main_box.pack_start(div2, False, False, 4)

        # 4. INPUT SECTION (Microphone)
        in_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_in_title = Gtk.Label(label="INPUT", xalign=0)
        lbl_in_title.get_style_context().add_class("section-title")
        self.lbl_in_val = Gtk.Label(label="100%", xalign=1)
        self.lbl_in_val.get_style_context().add_class("section-value")
        in_hdr.pack_start(lbl_in_title, True, True, 0)
        in_hdr.pack_end(self.lbl_in_val, False, False, 0)
        main_box.pack_start(in_hdr, False, False, 0)

        # Input Volume Slider
        self.scale_in = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale_in.set_draw_value(False)
        self.scale_in.connect("value-changed", self.on_input_volume_changed)
        main_box.pack_start(self.scale_in, False, False, 2)

        # Input Devices Container
        self.in_devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        main_box.pack_start(self.in_devices_box, False, False, 2)

        # 5. SOURCES / STREAMS SECTION (App volumes)
        self.streams_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        main_box.pack_start(self.streams_container, False, False, 0)

    # -------------------------------------------------------------------------
    # UI Callbacks (Sliders & Switches)
    # -------------------------------------------------------------------------
    def on_master_switch_toggled(self, switch, state):
        if self.updating_ui:
            return
        target_mute = "0" if state else "1"
        try:
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", target_mute], check=False)
            self.output_muted = not state
            self.update_header_icon()
        except Exception:
            pass
        return False

    def on_output_volume_changed(self, scale):
        if self.updating_ui:
            return
        val = int(scale.get_value())
        self.lbl_out_val.set_label(f"{val}%")
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{val}%"], check=False)
        self.update_header_icon()

    def on_input_volume_changed(self, scale):
        if self.updating_ui:
            return
        val = int(scale.get_value())
        self.lbl_in_val.set_label(f"{val}%")
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{val}%"], check=False)

    def on_app_volume_changed(self, scale, stream_idx, lbl_val):
        if self.updating_ui:
            return
        val = int(scale.get_value())
        lbl_val.set_label(f"{val}%")
        subprocess.run(["pactl", "set-sink-input-volume", str(stream_idx), f"{val}%"], check=False)

    def select_output_sink(self, sink_name):
        try:
            subprocess.run(["pactl", "set-default-sink", sink_name], check=False)
            self.refresh_all_state()
        except Exception:
            pass

    def select_input_source(self, source_name):
        try:
            subprocess.run(["pactl", "set-default-source", source_name], check=False)
            self.refresh_all_state()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Audio State Polling
    # -------------------------------------------------------------------------
    def refresh_all_state(self):
        def worker():
            # 1. Defaults
            def_sink, def_source = "", ""
            try:
                out = subprocess.check_output(["pactl", "info"], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if line.startswith("Default Sink:"):
                        def_sink = line.split(":", 1)[1].strip()
                    elif line.startswith("Default Source:"):
                        def_source = line.split(":", 1)[1].strip()
            except Exception:
                pass

            # 2. Sinks
            sinks = []
            try:
                raw_sinks = subprocess.check_output(["pactl", "-f", "json", "list", "sinks"], text=True, stderr=subprocess.DEVNULL)
                sinks = json.loads(raw_sinks)
            except Exception:
                pass

            # 3. Sources
            sources = []
            try:
                raw_sources = subprocess.check_output(["pactl", "-f", "json", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
                sources = [s for s in json.loads(raw_sources) if not s.get("name", "").endswith(".monitor")]
            except Exception:
                pass

            # 4. App Streams
            streams = []
            try:
                raw_streams = subprocess.check_output(["pactl", "-f", "json", "list", "sink-inputs"], text=True, stderr=subprocess.DEVNULL)
                streams = json.loads(raw_streams)
            except Exception:
                pass

            GLib.idle_add(self.update_ui_state, def_sink, def_source, sinks, sources, streams)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def update_ui_state(self, def_sink, def_source, sinks, sources, streams):
        self.updating_ui = True
        self.default_sink = def_sink
        self.default_source = def_source

        # 1. Find Active Sink
        active_sink = None
        for s in sinks:
            if s.get("name") == def_sink:
                active_sink = s
                break
        if not active_sink and sinks:
            active_sink = sinks[0]

        if active_sink:
            vol_obj = active_sink.get("volume", {})
            vol_pct = 100
            for ch in vol_obj.values():
                val_p = ch.get("value_percent", "100%").replace("%", "")
                try:
                    vol_pct = int(val_p)
                    break
                except ValueError:
                    pass

            is_muted = active_sink.get("mute", False)
            self.output_muted = is_muted
            self.scale_out.set_value(vol_pct)
            self.lbl_out_val.set_label(f"{vol_pct}%")
            self.master_switch.set_active(not is_muted)

            desc = active_sink.get("description") or "Default Speaker"
            self.lbl_subtitle.set_label(desc.upper())
            self.update_header_icon()

        # Render Output Sinks List
        for child in self.out_devices_box.get_children():
            self.out_devices_box.remove(child)

        for s in sinks:
            s_name = s.get("name", "")
            s_desc = s.get("description", s_name)
            is_active = (s_name == def_sink)

            btn = Gtk.Button()
            btn.get_style_context().add_class("device-row-selected" if is_active else "device-row")
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            
            icon_glyph = "󰓃"
            lower_desc = s_desc.lower()
            if "headphone" in lower_desc or "headset" in lower_desc:
                icon_glyph = "󰋋"
            elif "hdmi" in lower_desc or "displayport" in lower_desc:
                icon_glyph = "󰍹"
            elif "speaker" in lower_desc:
                icon_glyph = "󰓃"

            lbl_ico = Gtk.Label(label=icon_glyph)
            lbl_ico.get_style_context().add_class("device-icon")
            btn_box.pack_start(lbl_ico, False, False, 0)

            lbl_dev = Gtk.Label(label=s_desc, xalign=0)
            lbl_dev.get_style_context().add_class("device-label")
            btn_box.pack_start(lbl_dev, True, True, 0)

            if is_active:
                lbl_check = Gtk.Label(label="")
                btn_box.pack_end(lbl_check, False, False, 0)

            btn.add(btn_box)
            btn.connect("clicked", lambda w, name=s_name: self.select_output_sink(name))
            self.out_devices_box.pack_start(btn, False, False, 0)

        # 3. Find Active Source (Mic)
        active_source = None
        for s in sources:
            if s.get("name") == def_source:
                active_source = s
                break
        if not active_source and sources:
            active_source = sources[0]

        if active_source:
            vol_obj = active_source.get("volume", {})
            vol_pct = 100
            for ch in vol_obj.values():
                val_p = ch.get("value_percent", "100%").replace("%", "")
                try:
                    vol_pct = int(val_p)
                    break
                except ValueError:
                    pass

            self.scale_in.set_value(vol_pct)
            self.lbl_in_val.set_label(f"{vol_pct}%")

        # Render Input Sources List
        for child in self.in_devices_box.get_children():
            self.in_devices_box.remove(child)

        for s in sources:
            s_name = s.get("name", "")
            s_desc = s.get("description", s_name)
            is_active = (s_name == def_source)

            btn = Gtk.Button()
            btn.get_style_context().add_class("device-row-selected" if is_active else "device-row")
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            icon_glyph = "󰍬"
            lower_desc = s_desc.lower()
            if "cam" in lower_desc or "webcam" in lower_desc:
                icon_glyph = "󰢴"
            elif "headset" in lower_desc:
                icon_glyph = "󰋎"

            lbl_ico = Gtk.Label(label=icon_glyph)
            lbl_ico.get_style_context().add_class("device-icon")
            btn_box.pack_start(lbl_ico, False, False, 0)

            lbl_dev = Gtk.Label(label=s_desc, xalign=0)
            lbl_dev.get_style_context().add_class("device-label")
            btn_box.pack_start(lbl_dev, True, True, 0)

            if is_active:
                lbl_check = Gtk.Label(label="")
                btn_box.pack_end(lbl_check, False, False, 0)

            btn.add(btn_box)
            btn.connect("clicked", lambda w, name=s_name: self.select_input_source(name))
            self.in_devices_box.pack_start(btn, False, False, 0)

        # 4. Render App Streams (Sources Section)
        for child in self.streams_container.get_children():
            self.streams_container.remove(child)

        if streams:
            div_s = Gtk.Box()
            div_s.get_style_context().add_class("divider")
            self.streams_container.pack_start(div_s, False, False, 4)

            src_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl_s_title = Gtk.Label(label="SOURCES", xalign=0)
            lbl_s_title.get_style_context().add_class("section-title")
            src_hdr.pack_start(lbl_s_title, True, True, 0)
            self.streams_container.pack_start(src_hdr, False, False, 0)

            for stream in streams:
                s_idx = stream.get("index")
                props = stream.get("properties", {})
                app_name = props.get("application.name") or props.get("media.name") or "Application Stream"
                
                vol_obj = stream.get("volume", {})
                vol_pct = 100
                for ch in vol_obj.values():
                    val_p = ch.get("value_percent", "100%").replace("%", "")
                    try:
                        vol_pct = int(val_p)
                        break
                    except ValueError:
                        pass

                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                card.get_style_context().add_class("app-card")

                top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                ico = Gtk.Label(label="󰓃")
                top_row.pack_start(ico, False, False, 0)

                name_lbl = Gtk.Label(label=app_name, xalign=0)
                name_lbl.get_style_context().add_class("app-name")
                top_row.pack_start(name_lbl, True, True, 0)

                v_lbl = Gtk.Label(label=f"{vol_pct}%", xalign=1)
                v_lbl.get_style_context().add_class("app-vol")
                top_row.pack_end(v_lbl, False, False, 0)
                card.pack_start(top_row, False, False, 0)

                s_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
                s_scale.set_draw_value(False)
                s_scale.set_value(vol_pct)
                s_scale.connect("value-changed", self.on_app_volume_changed, s_idx, v_lbl)
                card.pack_start(s_scale, False, False, 0)

                self.streams_container.pack_start(card, False, False, 2)

        self.card.show_all()
        self.updating_ui = False

    def update_header_icon(self):
        if self.output_muted:
            self.header_icon.set_label("󰝟")
        else:
            val = int(self.scale_out.get_value())
            if val == 0:
                self.header_icon.set_label("󰝟")
            elif val < 33:
                self.header_icon.set_label("")
            elif val < 66:
                self.header_icon.set_label("")
            else:
                self.header_icon.set_label("")


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

    win = AudioControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
