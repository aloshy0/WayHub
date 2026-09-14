#!/usr/bin/env python3
"""
Waybar Autohide Daemon for Hyprland
Monitors cursor position to seamlessly show/hide Waybar on top-edge hover.
Prevents phantom clicks and ensures underlying windows are 100% clickable when hidden.
"""

import os
import sys
import glob
import time
import json
import socket
import signal
import subprocess

# Timing & thresholds
LEAVE_DELAY = 0.35      # Seconds to wait before hiding bar after cursor leaves
POLL_INTERVAL = 0.05    # Polling frequency (50ms)
BAR_THRESHOLD_Y = 50    # Y offset threshold to keep bar visible
EDGE_TRIGGER_Y = 2      # Y offset threshold at screen top to reveal bar

def get_hypr_socket():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    
    if sig:
        sock = os.path.join(runtime_dir, "hypr", sig, ".socket.sock")
        if os.path.exists(sock):
            return sock

    # Fallback: search for available hyprland sockets
    pattern = os.path.join(runtime_dir, "hypr", "*", ".socket.sock")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]

    return None

def query_hypr_socket(sock_path, cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.2)
        s.connect(sock_path)
        s.sendall(cmd.encode("utf-8"))
        res = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            res += chunk
        s.close()
        return res.decode("utf-8", errors="ignore")
    except Exception:
        return None

def is_wofi_active():
    try:
        res = subprocess.run(["pgrep", "-x", "wofi"], stdout=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception:
        return False

def get_cursor_pos(sock_path):
    res = query_hypr_socket(sock_path, "cursorpos")
    if res:
        parts = res.strip().split(",")
        if len(parts) == 2:
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except ValueError:
                pass
    return None

def get_monitors(sock_path):
    res = query_hypr_socket(sock_path, "j/monitors")
    if res:
        try:
            return json.loads(res)
        except Exception:
            pass
    return []

def is_waybar_visible(sock_path):
    res = query_hypr_socket(sock_path, "j/layers")
    if res:
        try:
            data = json.loads(res)
            for mon_name, mon_info in data.items():
                levels = mon_info.get("levels", {})
                # In Hyprland, visible Waybar sits on layer 2 (top) or layer 3 (overlay)
                for layer in levels.get("2", []) + levels.get("3", []):
                    if layer.get("namespace") == "waybar":
                        return True
            return False
        except Exception:
            pass
    return False

def toggle_waybar():
    subprocess.run(["killall", "-SIGUSR1", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def show_waybar(sock_path):
    if not is_waybar_visible(sock_path):
        toggle_waybar()

def hide_waybar(sock_path):
    if is_waybar_visible(sock_path):
        toggle_waybar()

def get_monitor_relative_y(x, y, monitors):
    for mon in monitors:
        mx = mon.get("x", 0)
        my = mon.get("y", 0)
        mw = mon.get("width", 1920)
        mh = mon.get("height", 1080)
        scale = mon.get("scale", 1.0)
        
        # Unscaled width/height in compositor coordinates
        w = int(mw / scale)
        h = int(mh / scale)
        
        if mx <= x < mx + w and my <= y < my + h:
            return y - my
            
    # Fallback to absolute y
    return y

def main():
    sock_path = get_hypr_socket()
    if not sock_path or not os.path.exists(sock_path):
        print("Hyprland socket not found. Exiting autohide daemon.", file=sys.stderr)
        sys.exit(1)

    monitors = get_monitors(sock_path)
    last_mon_check = time.time()
    leave_start_time = None

    def handle_sig(sig, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    while True:
        now = time.time()
        
        # Periodically refresh monitor geometries
        if now - last_mon_check > 5.0:
            new_mons = get_monitors(sock_path)
            if new_mons:
                monitors = new_mons
            last_mon_check = now

        pos = get_cursor_pos(sock_path)
        if pos is None:
            time.sleep(POLL_INTERVAL)
            continue

        cx, cy = pos
        rel_y = get_monitor_relative_y(cx, cy, monitors)
        visible = is_waybar_visible(sock_path)

        if not visible:
            # Reveal bar if cursor touches top edge
            if 0 <= rel_y <= EDGE_TRIGGER_Y:
                show_waybar(sock_path)
                leave_start_time = None
        else:
            # Bar is currently visible
            # Keep visible if inside bar boundary or if menus (e.g. wofi) are active
            if rel_y <= BAR_THRESHOLD_Y or is_wofi_active():
                leave_start_time = None
            else:
                if leave_start_time is None:
                    leave_start_time = now
                elif now - leave_start_time >= LEAVE_DELAY:
                    hide_waybar(sock_path)
                    leave_start_time = None

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
