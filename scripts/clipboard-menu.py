#!/usr/bin/env python3
"""
Waybar Clipboard History Popup
Dark-themed GTK3 & GtkLayerShell clipboard manager backed by cliphist and wl-clipboard.
"""

import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango

SOCKET_PATH = f"/tmp/waybar_clipboard_menu_{os.getuid()}.sock"
STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
CLIPBOARD_TS_FILE = os.path.join(STATE_DIR, "waybar-clipboard-timestamps.json")
CLIPBOARD_TTL_SECONDS = 24 * 3600
MAX_VISIBLE_ITEMS = 80
WATCHER_TYPES = ("text", "image")

CSS_STYLE = """
* {
    all: unset;
    font-family: 'JetBrainsMono Nerd Font', 'JetBrains Mono', 'Inter', -apple-system, sans-serif;
}

window,
.backdrop {
    background-color: transparent;
    background: transparent;
}

.clipboard-window {
    background-color: #1b222a;
    background: #1b222a;
    border: 1px solid #334050;
    border-radius: 16px;
    padding: 16px 18px;
    color: #e2e8f0;
}

.header-box {
    margin-bottom: 10px;
}

.header-icon {
    font-size: 22px;
    color: #67e8f9;
    min-width: 28px;
    margin-right: 10px;
}

.header-title {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.header-subtitle {
    font-size: 9.5px;
    font-weight: 700;
    color: #7d8799;
    letter-spacing: 1.2px;
}

.clear-btn {
    background-color: #272228;
    border: 1px solid #59333c;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
    color: #f38ba8;
}

.clear-btn:hover {
    background-color: #3a242c;
    border-color: #ff5c5c;
    color: #ffffff;
}

.clear-btn:disabled {
    opacity: 0.4;
}

.confirm-bar {
    background-color: #2a2126;
    border: 1px solid #6b323d;
    border-radius: 10px;
    padding: 8px 10px;
    margin-bottom: 10px;
}

.confirm-label {
    font-size: 11.5px;
    font-weight: 600;
    color: #fecdd3;
}

.confirm-yes-btn {
    background-color: #dc2626;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    color: #ffffff;
}

.confirm-yes-btn:hover {
    background-color: #ef4444;
}

.confirm-no-btn {
    background-color: #242d37;
    border: 1px solid #3c4a5a;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    color: #cbd5e1;
}

.confirm-no-btn:hover {
    background-color: #2e3946;
}

.search-box {
    background-color: #141920;
    border: 1px solid #2e3846;
    border-radius: 10px;
    padding: 6px 10px;
    margin-bottom: 8px;
}

.search-icon {
    font-size: 13px;
    color: #67e8f9;
    margin-right: 8px;
}

.search-entry {
    font-size: 12.5px;
    color: #f1f5f9;
}

.search-clear-btn {
    font-size: 11px;
    color: #7d8799;
    padding: 2px 6px;
    border-radius: 6px;
}

.search-clear-btn:hover {
    background-color: #252f3a;
    color: #ffffff;
}

.filter-row {
    margin-bottom: 10px;
}

.filter-btn {
    background-color: #222a34;
    border: 1px solid #2f3a48;
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
}

.filter-btn:hover {
    background-color: #2a3441;
    color: #e2e8f0;
}

.filter-btn.active {
    background-color: #1a3340;
    border-color: #67e8f9;
    color: #67e8f9;
}

scrollbar slider {
    background-color: #364354;
    border-radius: 4px;
    min-width: 5px;
}

.clip-row {
    background-color: #222a34;
    border: 1px solid #2e3846;
    border-radius: 10px;
    padding: 6px 8px;
    margin-bottom: 5px;
}

.clip-row:hover {
    background-color: #27323f;
    border-color: #4b5e73;
}

.clip-copy-btn {
    padding: 2px 4px;
}

.clip-type-icon {
    font-size: 15px;
    color: #67e8f9;
    min-width: 24px;
    margin-right: 8px;
}

.clip-type-icon.image {
    color: #a78bfa;
}

.clip-thumb {
    border-radius: 6px;
    margin-right: 10px;
}

.clip-preview {
    font-size: 12px;
    font-weight: 500;
    color: #e2e8f0;
}

.clip-meta {
    font-size: 10px;
    font-weight: 600;
    color: #7d8799;
}

.clip-del-btn {
    border-radius: 7px;
    padding: 6px 8px;
    font-size: 13px;
    color: #64748b;
}

.clip-del-btn:hover {
    background-color: #3a242c;
    color: #f38ba8;
}

.empty-label {
    font-size: 12px;
    color: #7d8799;
    padding: 28px 12px;
}

.footer-hint {
    margin-top: 6px;
    font-size: 10px;
    color: #64748b;
}
"""


def parse_cliphist_line(raw_line):
    """Parse one `cliphist list` line into id, preview, image flag, and metadata."""
    if not raw_line or "\t" not in raw_line:
        return None
    entry_id, preview = raw_line.split("\t", 1)
    entry_id = entry_id.strip()
    if not entry_id:
        return None
    is_image = preview.startswith("[[ binary data ")
    image_info = ""
    if is_image:
        m = re.match(r"^\[\[ binary data (.+?) \]\]$", preview.strip())
        image_info = m.group(1) if m else "binary data"
    return {
        "id": entry_id,
        "preview": preview,
        "is_image": is_image,
        "image_info": image_info,
        "raw": raw_line,
    }


def load_cliphist_entries():
    """Return parsed entries from `cliphist list`, newest first."""
    if not shutil.which("cliphist"):
        return []
    try:
        proc = subprocess.run(
            ["cliphist", "list"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
        )
        if proc.returncode != 0:
            return []
        entries = []
        for line in proc.stdout.splitlines():
            parsed = parse_cliphist_line(line)
            if parsed:
                entries.append(parsed)
        return entries
    except Exception:
        return []


def filter_entries(entries, query="", mode="all"):
    """Filter entries by type (`all` | `text` | `images`) and case-insensitive substring."""
    q = (query or "").strip().lower()
    result = []
    for entry in entries:
        if mode == "text" and entry["is_image"]:
            continue
        if mode == "images" and not entry["is_image"]:
            continue
        if q and q not in entry["preview"].lower():
            continue
        result.append(entry)
    return result


def ensure_clipboard_watchers():
    """Ensure wl-paste text and image watchers are running to populate cliphist."""
    if not shutil.which("wl-paste") or not shutil.which("cliphist"):
        return
    uid = str(os.getuid())
    for media_type in WATCHER_TYPES:
        pattern = f"wl-paste --type {media_type} --watch cliphist store"
        try:
            res = subprocess.run(
                ["pgrep", "-u", uid, "-f", pattern],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                continue
        except Exception:
            continue
        try:
            subprocess.Popen(
                ["wl-paste", "--type", media_type, "--watch", "cliphist", "store"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def copy_cliphist_entry(entry_id):
    """Decode entry bytes from cliphist and push them onto the Wayland clipboard."""
    if not entry_id or not shutil.which("cliphist") or not shutil.which("wl-copy"):
        return False
    try:
        dec = subprocess.Popen(
            ["cliphist", "decode", str(entry_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # wl-copy forks into the background holding stdout/stderr unless redirected to DEVNULL.
        cp = subprocess.Popen(
            ["wl-copy"],
            stdin=dec.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if dec.stdout:
            dec.stdout.close()
        dec_rc = dec.wait(timeout=3)
        cp_rc = cp.wait(timeout=3)
        return dec_rc == 0 and cp_rc == 0
    except Exception:
        return False


def delete_cliphist_entry(raw_line):
    """Delete a specific entry from cliphist."""
    if not raw_line or not shutil.which("cliphist"):
        return False
    try:
        proc = subprocess.run(
            ["cliphist", "delete"],
            input=raw_line + "\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return proc.returncode == 0
    except Exception:
        return False


def wipe_cliphist():
    """Remove all saved entries from cliphist and clear recorded timestamps."""
    ok = False
    if shutil.which("cliphist"):
        try:
            proc = subprocess.run(
                ["cliphist", "wipe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            ok = proc.returncode == 0
        except Exception:
            ok = False
    if ok:
        save_clipboard_timestamps({})
        if shutil.which("wl-copy"):
            try:
                subprocess.run(
                    ["wl-copy", "--clear"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass
    return ok


def load_clipboard_timestamps():
    """Return {entry_id: created_unix_ts} from persistent state."""
    try:
        with open(CLIPBOARD_TS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_clipboard_timestamps(ts_map):
    """Atomically persist {entry_id: created_unix_ts} state."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp_path = f"{CLIPBOARD_TS_FILE}.tmp.{os.getpid()}"
        with open(tmp_path, "w") as f:
            json.dump(ts_map, f)
        os.replace(tmp_path, CLIPBOARD_TS_FILE)
    except OSError:
        pass


def prune_expired_clipboard_entries(ttl_seconds=CLIPBOARD_TTL_SECONDS, now_ts=None):
    """Delete cliphist entries older than ttl_seconds and sync timestamps; return (kept, removed_count)."""
    now = float(now_ts if now_ts is not None else time.time())
    entries = load_cliphist_entries()
    ts_map = load_clipboard_timestamps()

    kept = []
    new_ts_map = {}
    removed_count = 0

    for entry in entries:
        eid = entry["id"]
        created_ts = ts_map.get(eid)
        if not isinstance(created_ts, (int, float)):
            created_ts = now
        if (now - float(created_ts)) >= ttl_seconds:
            if delete_cliphist_entry(entry["raw"]):
                removed_count += 1
                continue
        entry["created_ts"] = float(created_ts)
        kept.append(entry)
        new_ts_map[eid] = float(created_ts)

    if new_ts_map != ts_map:
        save_clipboard_timestamps(new_ts_map)

    if removed_count > 0 and not kept and shutil.which("wl-copy"):
        try:
            subprocess.run(
                ["wl-copy", "--clear"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except Exception:
            pass

    return kept, removed_count


def decode_thumbnail_pixbuf(entry_id, max_w=96, max_h=44):
    """Decode an image entry from cliphist and return a scaled GdkPixbuf, or None."""
    try:
        proc = subprocess.run(
            ["cliphist", "decode", str(entry_id)],
            capture_output=True,
            timeout=2.5,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        loader = GdkPixbuf.PixbufLoader()
        loader.write(proc.stdout)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            return None
        w = pixbuf.get_width()
        h = pixbuf.get_height()
        if w <= 0 or h <= 0:
            return None
        scale = min(max_w / w, max_h / h, 1.0)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        return pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        return None


class ClipboardPopup(Gtk.Window):
    """Layer-shell popup window displaying searchable clipboard history."""

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

        self.all_entries = []
        self.visible_entries = []
        self.filter_mode = "all"
        self.search_query = ""
        self._render_gen = 0
        self._thumb_cache = {}
        self.first_copy_btn = None

        self.init_ui()
        self.apply_css()
        GLib.idle_add(self._initial_load)

    def _initial_load(self):
        ensure_clipboard_watchers()
        self.reload_entries()
        self.search_entry.grab_focus()
        return False

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

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.confirm_bar.get_visible():
                self.confirm_bar.set_visible(False)
                return True
            self.close()
            return True
        return False

    def apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS_STYLE.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def init_ui(self):
        self.backdrop = Gtk.EventBox()
        self.backdrop.get_style_context().add_class("backdrop")
        self.backdrop.set_above_child(False)
        self.backdrop.connect("button-press-event", self.on_backdrop_clicked)
        self.add(self.backdrop)

        align_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.backdrop.add(align_box)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("clipboard-window")
        self.card.set_halign(Gtk.Align.END)
        self.card.set_valign(Gtk.Align.START)
        self.card.set_margin_top(38)
        self.card.set_margin_end(12)
        self.card.set_size_request(440, -1)
        align_box.pack_start(self.card, False, False, 0)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.get_style_context().add_class("header-box")
        self.card.pack_start(header_box, False, False, 0)

        icon_lbl = Gtk.Label(label="󰅌")
        icon_lbl.get_style_context().add_class("header-icon")
        icon_lbl.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(icon_lbl, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        title_lbl = Gtk.Label(label="Clipboard History", xalign=0)
        title_lbl.get_style_context().add_class("header-title")
        self.lbl_subtitle = Gtk.Label(label="LOADING...", xalign=0)
        self.lbl_subtitle.get_style_context().add_class("header-subtitle")
        title_box.pack_start(title_lbl, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        self.clear_all_btn = Gtk.Button(label="Clear All")
        self.clear_all_btn.get_style_context().add_class("clear-btn")
        self.clear_all_btn.set_valign(Gtk.Align.CENTER)
        self.clear_all_btn.connect("clicked", self.on_clear_all_clicked)
        header_box.pack_end(self.clear_all_btn, False, False, 0)

        # Inline clear confirmation strip
        self.confirm_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.confirm_bar.get_style_context().add_class("confirm-bar")
        self.confirm_bar.set_no_show_all(True)
        self.confirm_bar.set_visible(False)

        confirm_lbl = Gtk.Label(label="Delete all saved items?", xalign=0)
        confirm_lbl.get_style_context().add_class("confirm-label")
        self.confirm_bar.pack_start(confirm_lbl, True, True, 0)

        yes_btn = Gtk.Button(label="Yes, Clear")
        yes_btn.get_style_context().add_class("confirm-yes-btn")
        yes_btn.connect("clicked", self.on_confirm_wipe_clicked)
        no_btn = Gtk.Button(label="Cancel")
        no_btn.get_style_context().add_class("confirm-no-btn")
        no_btn.connect("clicked", lambda _w: self.confirm_bar.set_visible(False))
        self.confirm_bar.pack_start(yes_btn, False, False, 0)
        self.confirm_bar.pack_start(no_btn, False, False, 0)
        self.card.pack_start(self.confirm_bar, False, False, 0)

        # Search input
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        search_box.get_style_context().add_class("search-box")
        search_icon = Gtk.Label(label="󰍉")
        search_icon.get_style_context().add_class("search-icon")
        search_box.pack_start(search_icon, False, False, 0)

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search clipboard history...")
        self.search_entry.get_style_context().add_class("search-entry")
        self.search_entry.connect("changed", self.on_search_changed)
        self.search_entry.connect("activate", self.on_search_activate)
        self.search_entry.connect("key-press-event", self.on_search_key_press)
        search_box.pack_start(self.search_entry, True, True, 0)

        self.search_clear_btn = Gtk.Button(label="✕")
        self.search_clear_btn.get_style_context().add_class("search-clear-btn")
        self.search_clear_btn.set_no_show_all(True)
        self.search_clear_btn.set_visible(False)
        self.search_clear_btn.connect("clicked", lambda _w: self.search_entry.set_text(""))
        search_box.pack_end(self.search_clear_btn, False, False, 0)
        self.card.pack_start(search_box, False, False, 0)

        # Filter chips
        filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_row.get_style_context().add_class("filter-row")
        self.filter_buttons = {}
        for fid, label in (("all", "All"), ("text", "Text"), ("images", "Images")):
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("filter-btn")
            if fid == self.filter_mode:
                btn.get_style_context().add_class("active")
            btn.connect("clicked", self.on_filter_clicked, fid)
            filter_row.pack_start(btn, False, False, 0)
            self.filter_buttons[fid] = btn
        self.card.pack_start(filter_row, False, False, 0)

        # Scrollable list of clipboard entries
        self.scroll_win = Gtk.ScrolledWindow()
        self.scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll_win.set_min_content_height(120)
        self.scroll_win.set_max_content_height(390)
        self.scroll_win.set_propagate_natural_height(True)
        self.card.pack_start(self.scroll_win, True, True, 0)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.scroll_win.add(self.list_box)

        self.lbl_footer = Gtk.Label(label="", xalign=0)
        self.lbl_footer.get_style_context().add_class("footer-hint")
        self.card.pack_start(self.lbl_footer, False, False, 0)

    def on_search_changed(self, entry):
        self.search_query = entry.get_text()
        self.search_clear_btn.set_visible(bool(self.search_query))
        self.render_entries()

    def on_search_activate(self, entry):
        if self.visible_entries:
            self.on_entry_copy_clicked(None, self.visible_entries[0])

    def on_search_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Down and self.first_copy_btn:
            self.first_copy_btn.grab_focus()
            return True
        return False

    def on_filter_clicked(self, widget, mode):
        if self.filter_mode == mode:
            return
        self.filter_mode = mode
        for fid, btn in self.filter_buttons.items():
            ctx = btn.get_style_context()
            if fid == mode:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        self.render_entries()

    def on_clear_all_clicked(self, widget):
        self.confirm_bar.set_visible(not self.confirm_bar.get_visible())

    def on_confirm_wipe_clicked(self, widget):
        self.confirm_bar.set_visible(False)
        wipe_cliphist()
        self._thumb_cache.clear()
        self.all_entries = []
        self.render_entries()

    def reload_entries(self):
        self.all_entries, _ = prune_expired_clipboard_entries()
        self.render_entries()

    def render_entries(self):
        self._render_gen += 1
        gen = self._render_gen
        self.first_copy_btn = None

        for child in self.list_box.get_children():
            self.list_box.remove(child)

        matched = filter_entries(self.all_entries, self.search_query, self.filter_mode)
        self.visible_entries = matched[:MAX_VISIBLE_ITEMS]

        total = len(self.all_entries)
        self.clear_all_btn.set_sensitive(total > 0)
        if self.search_query or self.filter_mode != "all":
            self.lbl_subtitle.set_label(f"{len(matched)} OF {total} ITEMS • 24H AUTO-CLEAR")
        else:
            self.lbl_subtitle.set_label(f"{total} SAVED ITEMS • 24H AUTO-CLEAR")

        if not self.visible_entries:
            msg = "No matching clipboard entries" if total > 0 else "Clipboard history is empty"
            empty_lbl = Gtk.Label(label=msg)
            empty_lbl.get_style_context().add_class("empty-label")
            self.list_box.pack_start(empty_lbl, False, False, 0)
            self.lbl_footer.set_label("Enter: copy top result • Esc: close")
            self.list_box.show_all()
            return

        pending_thumbs = []
        for idx, entry in enumerate(self.visible_entries):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.get_style_context().add_class("clip-row")

            copy_btn = Gtk.Button()
            copy_btn.get_style_context().add_class("clip-copy-btn")
            copy_btn.connect("clicked", self.on_entry_copy_clicked, entry)
            if idx == 0:
                self.first_copy_btn = copy_btn

            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            if entry["is_image"]:
                cached_pb = self._thumb_cache.get(entry["id"])
                if cached_pb:
                    thumb = Gtk.Image.new_from_pixbuf(cached_pb)
                    thumb.get_style_context().add_class("clip-thumb")
                    inner.pack_start(thumb, False, False, 0)
                else:
                    icon = Gtk.Label(label="󰋩")
                    icon.get_style_context().add_class("clip-type-icon")
                    icon.get_style_context().add_class("image")
                    icon.set_valign(Gtk.Align.CENTER)
                    thumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                    thumb_box.pack_start(icon, False, False, 0)
                    inner.pack_start(thumb_box, False, False, 0)
                    pending_thumbs.append((entry["id"], thumb_box))
            else:
                icon = Gtk.Label(label="󰈙")
                icon.get_style_context().add_class("clip-type-icon")
                icon.set_valign(Gtk.Align.CENTER)
                inner.pack_start(icon, False, False, 0)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_valign(Gtk.Align.CENTER)
            if entry["is_image"]:
                title_text = "Image snippet"
                meta_text = entry["image_info"] or f"#{entry['id']}"
            else:
                collapsed = " ".join(entry["preview"].split())
                title_text = collapsed or "(whitespace)"
                meta_text = f"Text • {len(entry['preview'])} chars"

            prev_lbl = Gtk.Label(label=title_text, xalign=0)
            prev_lbl.get_style_context().add_class("clip-preview")
            prev_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            prev_lbl.set_single_line_mode(True)
            prev_lbl.set_max_width_chars(34)

            meta_lbl = Gtk.Label(label=meta_text, xalign=0)
            meta_lbl.get_style_context().add_class("clip-meta")
            meta_lbl.set_ellipsize(Pango.EllipsizeMode.END)

            text_box.pack_start(prev_lbl, False, False, 0)
            text_box.pack_start(meta_lbl, False, False, 0)
            inner.pack_start(text_box, True, True, 0)

            copy_btn.add(inner)
            row.pack_start(copy_btn, True, True, 0)

            del_btn = Gtk.Button(label="󰆴")
            del_btn.get_style_context().add_class("clip-del-btn")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.set_tooltip_text("Delete entry")
            del_btn.connect("clicked", self.on_entry_delete_clicked, entry)
            row.pack_end(del_btn, False, False, 0)

            self.list_box.pack_start(row, False, False, 0)

        if len(matched) > MAX_VISIBLE_ITEMS:
            self.lbl_footer.set_label(
                f"Showing {MAX_VISIBLE_ITEMS} of {len(matched)} matches • Enter copies top match"
            )
        else:
            self.lbl_footer.set_label("Click or Enter to copy • Esc to close")

        self.list_box.show_all()
        if pending_thumbs:
            self._load_thumbnails_async(gen, pending_thumbs)

    def _load_thumbnails_async(self, gen, pending_thumbs):
        def worker():
            for entry_id, container in pending_thumbs:
                if gen != self._render_gen:
                    return
                pixbuf = decode_thumbnail_pixbuf(entry_id)
                if pixbuf and gen == self._render_gen:
                    self._thumb_cache[entry_id] = pixbuf
                    GLib.idle_add(self._apply_thumbnail, gen, container, pixbuf)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_thumbnail(self, gen, container, pixbuf):
        if gen != self._render_gen:
            return False
        for child in container.get_children():
            container.remove(child)
        thumb = Gtk.Image.new_from_pixbuf(pixbuf)
        thumb.get_style_context().add_class("clip-thumb")
        container.pack_start(thumb, False, False, 0)
        container.show_all()
        return False

    def on_entry_copy_clicked(self, widget, entry):
        if copy_cliphist_entry(entry["id"]):
            label = "Image copied to clipboard" if entry["is_image"] else "Copied to clipboard"
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "Clipboard", "-i", "edit-paste", "-t", "1500", "Clipboard", label],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        self.close()

    def on_entry_delete_clicked(self, widget, entry):
        delete_cliphist_entry(entry["raw"])
        ts_map = load_clipboard_timestamps()
        if entry["id"] in ts_map:
            ts_map.pop(entry["id"], None)
            save_clipboard_timestamps(ts_map)
        self._thumb_cache.pop(entry["id"], None)
        self.all_entries = [e for e in self.all_entries if e["raw"] != entry["raw"]]
        self.render_entries()


def start_ipc_server(win):
    """Listen on Unix socket for toggle/close commands so clicking toggles cleanly."""
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
    """Toggle off any existing ClipboardPopup instance; return True if toggled."""
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
    if "--prune" in sys.argv:
        ensure_clipboard_watchers()
        prune_expired_clipboard_entries()
        sys.exit(0)

    if try_toggle_existing():
        sys.exit(0)

    win = ClipboardPopup()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

