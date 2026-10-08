#!/usr/bin/env python3
"""
Waybar / Hyprland Modern Application Launcher
A sleek, fast, full-featured desktop application launcher and search menu built with GTK3 & GtkLayerShell.
"""

import os
import sys
import glob
import shlex
import socket
import threading
import subprocess
import math

import cairo

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GtkLayerShell

SOCKET_PATH = f"/tmp/waybar_apps_menu_{os.getuid()}.sock"

CSS_STYLE = """
* {
    all: unset;
    font-family: 'JetBrainsMono Nerd Font', 'JetBrains Mono', 'Inter', -apple-system, sans-serif;
}

window {
    background-color: transparent;
    background: transparent;
}

.card {
    background-color: #1b222a;
    border: 1px solid #334050;
    border-radius: 18px;
    padding: 18px;
}

.search-box {
    background-color: #13181f;
    border: 1px solid #334050;
    border-radius: 12px;
    padding: 10px 14px;
    color: #e2e8f0;
    font-size: 15px;
}

.search-box:focus {
    border: 1px solid #25a7ff;
    background-color: #151c24;
}

.search-icon {
    color: #25a7ff;
    font-size: 16px;
    margin-right: 8px;
}

.pill-btn {
    background-color: #13181f;
    color: #8fa0b5;
    border: 1px solid #2a3543;
    border-radius: 10px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: bold;
    transition: all 150ms ease-in-out;
}

.pill-btn:hover {
    background-color: #232d39;
    color: #ffffff;
    border-color: #3b4b5e;
}

.pill-btn.active {
    background-color: #25a7ff;
    color: #0b1117;
    border-color: #25a7ff;
}

.app-row {
    border-radius: 12px;
    padding: 8px 12px;
    margin-bottom: 4px;
    background-color: transparent;
    transition: background-color 100ms ease;
}

.app-row:hover, .app-row.selected {
    background-color: #242d38;
}

.app-name {
    color: #f1f5f9;
    font-size: 14px;
    font-weight: 600;
}

.app-desc {
    color: #8fa0b5;
    font-size: 12px;
}

.app-category-badge {
    background-color: #121820;
    color: #62768d;
    border: 1px solid #283340;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 10px;
}

.footer-label {
    color: #62768d;
    font-size: 11px;
}
"""

CATEGORIES = [
    ("All", "All"),
    ("Dev", "Development"),
    ("Web", "Network"),
    ("Media", "AudioVideo"),
    ("Office", "Office"),
    ("System", "System"),
    ("Tools", "Utility"),
    ("Games", "Game"),
    ("Settings", "Settings"),
]


class DesktopApp:
    def __init__(self, file_path, name, exec_cmd, icon, comment, categories, terminal):
        self.file_path = file_path
        self.name = name
        self.exec_cmd = exec_cmd
        self.icon = icon
        self.comment = comment
        self.categories = categories
        self.terminal = terminal

    def matches(self, query, category):
        if category and category != "All":
            if category not in self.categories:
                return False
        if not query:
            return True
        q = query.lower()
        return (
            q in self.name.lower() or
            q in self.comment.lower() or
            q in self.exec_cmd.lower() or
            q in self.categories.lower()
        )


def load_all_apps():
    search_dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/local/share/applications",
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
    ]

    apps = {}
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if not f.endswith(".desktop"):
                    continue
                full_path = os.path.join(root, f)
                if f in apps:
                    continue
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    if "[Desktop Entry]" not in content:
                        continue
                    section = content.split("[Desktop Entry]")[1].split("\n[")[0].splitlines()
                    data = {}
                    for line in section:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            data[k.strip()] = v.strip()

                    if data.get("Type", "Application") != "Application":
                        continue
                    if data.get("NoDisplay", "false").lower() == "true":
                        continue
                    if data.get("Hidden", "false").lower() == "true":
                        continue

                    name = data.get("Name")
                    exec_cmd = data.get("Exec")
                    if not name or not exec_cmd:
                        continue

                    icon = data.get("Icon", "application-x-executable")
                    comment = data.get("Comment") or data.get("GenericName") or ""
                    categories = data.get("Categories", "")
                    terminal = data.get("Terminal", "false").lower() == "true"

                    apps[f] = DesktopApp(
                        file_path=full_path,
                        name=name,
                        exec_cmd=exec_cmd,
                        icon=icon,
                        comment=comment,
                        categories=categories,
                        terminal=terminal,
                    )
                except Exception:
                    continue

    sorted_apps = sorted(apps.values(), key=lambda a: a.name.lower())
    return sorted_apps


class AppLauncher(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
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

        self.apps = load_all_apps()
        self.filtered_apps = list(self.apps)
        self.current_category = "All"
        self.selected_index = 0
        self.row_widgets = []
        self.icon_theme = Gtk.IconTheme.get_default()

        self.connect("draw", self.on_window_draw)
        self.connect("key-press-event", self.on_key_press)
        self.connect("button-press-event", self.on_window_clicked)
        self.connect("destroy", Gtk.main_quit)

        self.init_ui()
        self.apply_css()
        self.render_app_list()

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE.encode())
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def on_window_draw(self, widget, cr):
        # 1. Clear fullscreen backdrop with subtle dim
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()

        # 2. Paint 100% solid opaque card with Cairo
        if hasattr(self, 'card'):
            alloc = self.card.get_allocation()
            if alloc.width > 1 and alloc.height > 1:
                cr.set_operator(cairo.OPERATOR_OVER)
                radius = 18.0
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

                # Card background #1b222a
                cr.set_source_rgb(27 / 255.0, 34 / 255.0, 42 / 255.0)
                cr.fill_preserve()

                # Border #334050
                cr.set_source_rgb(51 / 255.0, 64 / 255.0, 80 / 255.0)
                cr.set_line_width(1.2)
                cr.stroke()

        return False

    def on_window_clicked(self, widget, event):
        if hasattr(self, 'card'):
            alloc = self.card.get_allocation()
            if not (alloc.x <= event.x <= alloc.x + alloc.width and alloc.y <= event.y <= alloc.y + alloc.height):
                self.close()
                return True
        return False

    def init_ui(self):
        # Center container
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        center_box.set_valign(Gtk.Align.CENTER)
        center_box.set_halign(Gtk.Align.CENTER)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.card.get_style_context().add_class("card")
        self.card.set_size_request(620, 560)

        # Header: Search Entry
        search_box_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        search_box_container.get_style_context().add_class("search-box")

        search_icon = Gtk.Label(label="")
        search_icon.get_style_context().add_class("search-icon")
        search_box_container.pack_start(search_icon, False, False, 0)

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Type to search applications...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("changed", self.on_search_changed)
        search_box_container.pack_start(self.search_entry, True, True, 0)

        self.card.pack_start(search_box_container, False, False, 0)

        # Category Filter Pills
        self.pills_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pill_buttons = {}

        for label, cat_val in CATEGORIES:
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("pill-btn")
            if cat_val == "All":
                btn.get_style_context().add_class("active")
            btn.connect("clicked", self.on_category_clicked, cat_val)
            self.pills_box.pack_start(btn, False, False, 0)
            self.pill_buttons[cat_val] = btn

        self.card.pack_start(self.pills_box, False, False, 0)

        # Scrollable App List
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_vexpand(True)

        self.app_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scrolled_window.add(self.app_list_box)
        self.card.pack_start(self.scrolled_window, True, True, 0)

        # Footer Status Bar
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.count_label = Gtk.Label(label=f"{len(self.apps)} applications available")
        self.count_label.get_style_context().add_class("footer-label")
        footer.pack_start(self.count_label, False, False, 0)

        shortcuts_hint = Gtk.Label(label="[↑/↓] Navigate  •  [Enter] Launch  •  [Esc] Close")
        shortcuts_hint.get_style_context().add_class("footer-label")
        footer.pack_end(shortcuts_hint, False, False, 0)

        self.card.pack_start(footer, False, False, 0)

        center_box.pack_start(self.card, False, False, 0)
        self.add(center_box)

    def on_category_clicked(self, widget, cat_val):
        self.current_category = cat_val
        for c, btn in self.pill_buttons.items():
            if c == cat_val:
                btn.get_style_context().add_class("active")
            else:
                btn.get_style_context().remove_class("active")
        self.filter_and_render()

    def on_search_changed(self, entry):
        self.filter_and_render()

    def filter_and_render(self):
        query = self.search_entry.get_text().strip()
        self.filtered_apps = [
            app for app in self.apps if app.matches(query, self.current_category)
        ]
        self.selected_index = 0
        self.render_app_list()

    def get_app_icon_pixbuf(self, icon_name_or_path, size=38):
        if not icon_name_or_path:
            icon_name_or_path = "application-x-executable"

        # Check if absolute path
        if os.path.exists(icon_name_or_path):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    icon_name_or_path, size, size, True
                )
            except Exception:
                pass

        # Try icon theme lookup
        clean_name = icon_name_or_path
        for ext in (".png", ".svg", ".xpm"):
            if clean_name.endswith(ext):
                clean_name = clean_name[:-len(ext)]
                break

        try:
            return self.icon_theme.load_icon(clean_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        except Exception:
            try:
                return self.icon_theme.load_icon(
                    "application-x-executable", size, Gtk.IconLookupFlags.FORCE_SIZE
                )
            except Exception:
                return None

    def render_app_list(self):
        for child in self.app_list_box.get_children():
            self.app_list_box.remove(child)

        self.row_widgets = []
        self.count_label.set_text(f"{len(self.filtered_apps)} applications found")

        if not self.filtered_apps:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(40)
            empty_icon = Gtk.Label(label="")
            empty_icon.get_style_context().add_class("search-icon")
            empty_label = Gtk.Label(label="No matching applications found")
            empty_label.get_style_context().add_class("footer-label")
            empty_box.pack_start(empty_icon, False, False, 0)
            empty_box.pack_start(empty_label, False, False, 0)
            self.app_list_box.pack_start(empty_box, True, True, 0)
            self.app_list_box.show_all()
            return

        for idx, app in enumerate(self.filtered_apps):
            event_box = Gtk.EventBox()
            event_box.get_style_context().add_class("app-row")
            if idx == self.selected_index:
                event_box.get_style_context().add_class("selected")

            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)

            # Icon
            pixbuf = self.get_app_icon_pixbuf(app.icon, size=36)
            if pixbuf:
                img = Gtk.Image.new_from_pixbuf(pixbuf)
            else:
                img = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DND)
            row_box.pack_start(img, False, False, 0)

            # Info (Name + Description)
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            info_box.set_valign(Gtk.Align.CENTER)
            name_label = Gtk.Label(label=app.name, xalign=0)
            name_label.get_style_context().add_class("app-name")
            name_label.set_ellipsize(3)
            info_box.pack_start(name_label, False, False, 0)

            desc_text = app.comment if app.comment else app.exec_cmd.split()[0]
            desc_label = Gtk.Label(label=desc_text, xalign=0)
            desc_label.get_style_context().add_class("app-desc")
            desc_label.set_ellipsize(3)
            info_box.pack_start(desc_label, False, False, 0)

            row_box.pack_start(info_box, True, True, 0)

            # First category tag
            first_cat = ""
            if app.categories:
                cats = [c for c in app.categories.split(";") if c]
                if cats:
                    first_cat = cats[0]

            if first_cat:
                cat_badge = Gtk.Label(label=first_cat)
                cat_badge.get_style_context().add_class("app-category-badge")
                cat_badge.set_valign(Gtk.Align.CENTER)
                row_box.pack_end(cat_badge, False, False, 0)

            event_box.add(row_box)
            event_box.connect("button-press-event", self.on_app_clicked, app)
            event_box.connect("enter-notify-event", self.on_app_hover, idx)

            self.app_list_box.pack_start(event_box, False, False, 0)
            self.row_widgets.append(event_box)

        self.app_list_box.show_all()
        self.scroll_to_selected()

    def on_app_hover(self, widget, event, idx):
        self.set_selected_index(idx)

    def set_selected_index(self, idx):
        if 0 <= self.selected_index < len(self.row_widgets):
            self.row_widgets[self.selected_index].get_style_context().remove_class("selected")
        self.selected_index = max(0, min(idx, len(self.row_widgets) - 1))
        if 0 <= self.selected_index < len(self.row_widgets):
            self.row_widgets[self.selected_index].get_style_context().add_class("selected")
            self.scroll_to_selected()

    def scroll_to_selected(self):
        if 0 <= self.selected_index < len(self.row_widgets):
            widget = self.row_widgets[self.selected_index]
            adj = self.scrolled_window.get_vadjustment()
            alloc = widget.get_allocation()
            if alloc.height > 0:
                y = alloc.y
                h = alloc.height
                page_size = adj.get_page_size()
                val = adj.get_value()
                if y < val:
                    adj.set_value(y)
                elif y + h > val + page_size:
                    adj.set_value(y + h - page_size)

    def on_app_clicked(self, widget, event, app):
        self.launch_app(app)

    def launch_app(self, app):
        raw_cmd = app.exec_cmd
        # Strip field codes like %f, %F, %u, %U, %d, %D, %n, %N, %i, %c, %k, %v, %m
        cleaned_tokens = []
        try:
            tokens = shlex.split(raw_cmd)
        except Exception:
            tokens = raw_cmd.split()

        for t in tokens:
            if t.startswith("%") and len(t) == 2:
                continue
            cleaned_tokens.append(t)

        if not cleaned_tokens:
            return

        cmd = cleaned_tokens
        if app.terminal:
            term = os.environ.get("TERMINAL", "kitty")
            cmd = [term, "-e"] + cmd

        try:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"Error launching {app.name}: {e}", file=sys.stderr)

        self.close()

    def on_key_press(self, widget, event):
        keyval = event.keyval
        keyname = Gdk.keyval_name(keyval)

        if keyname == "Escape":
            self.close()
            return True
        elif keyname in ("Down", "KP_Down"):
            self.set_selected_index(self.selected_index + 1)
            return True
        elif keyname in ("Up", "KP_Up"):
            self.set_selected_index(self.selected_index - 1)
            return True
        elif keyname in ("Return", "KP_Enter"):
            if 0 <= self.selected_index < len(self.filtered_apps):
                self.launch_app(self.filtered_apps[self.selected_index])
            return True
        elif keyname == "Tab":
            # Cycle categories
            cat_list = [c[1] for c in CATEGORIES]
            curr_idx = cat_list.index(self.current_category) if self.current_category in cat_list else 0
            next_idx = (curr_idx + 1) % len(cat_list)
            self.on_category_clicked(None, cat_list[next_idx])
            return True

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
    if try_toggle_existing():
        sys.exit(0)

    win = AppLauncher()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
