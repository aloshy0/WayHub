#!/usr/bin/env python3
"""
Waybar Wi-Fi Control Center Popup
A modern, dark-themed Wi-Fi control center built with GTK3 & GtkLayerShell.
"""

import os
import sys
import re
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

SOCKET_PATH = f"/tmp/waybar_wifi_menu_{os.getuid()}.sock"

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

.wifi-window {
    background-color: #12151c;
    background: #12151c;
    border: 1px solid #2b3240;
    border-radius: 16px;
    padding: 18px 20px;
    color: #e2e8f0;
}

/* Header */
.header-box {
    margin-bottom: 12px;
}

.wifi-icon-large {
    font-size: 32px;
    color: #ffffff;
    margin-right: 14px;
}

.ssid-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}

.ssid-subtitle {
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

/* Wi-Fi Switch */
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

/* DNS Provider Buttons */
.dns-btn {
    background-color: #171b23;
    border: 1px solid #282f3d;
    border-radius: 8px;
    padding: 7px 14px;
    color: #b0bac8;
    font-size: 11.5px;
    font-weight: 600;
    transition: all 150ms ease;
}

.dns-btn:hover {
    background-color: #212733;
    border-color: #3b4557;
    color: #ffffff;
}

.dns-btn.active {
    background-color: #232a37;
    border: 1px solid #4d5a71;
    color: #ffffff;
    font-weight: 700;
}

/* Speed Test */
.speed-run-btn {
    background-color: #171b23;
    border: 1px solid #282f3d;
    border-radius: 8px;
    padding: 4px 14px;
    color: #c5cdd9;
    font-size: 11.5px;
    font-weight: 600;
    transition: all 150ms ease;
}

.speed-run-btn:hover {
    background-color: #212733;
    border-color: #3b4557;
    color: #ffffff;
}

/* Known Network Card */
.known-network-card {
    background-color: #1f242e;
    border: 1px solid #2e3747;
    border-radius: 10px;
    padding: 10px 14px;
    transition: all 150ms ease;
}

.known-network-card:hover {
    background-color: #262d3a;
    border-color: #3d495d;
}

.known-network-card .net-icon {
    font-size: 17px;
    color: #ffffff;
    margin-right: 12px;
}

.known-network-card .net-ssid {
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
}

.known-network-card .net-status {
    font-size: 10.5px;
    color: #7d8799;
}

.known-network-card .net-lock {
    font-size: 13px;
    color: #657082;
}

/* Other Networks */
.network-row {
    padding: 7px 10px;
    border-radius: 8px;
    transition: all 120ms ease;
}

.network-row:hover {
    background-color: #1b202a;
}

.network-row .net-icon {
    font-size: 15px;
    color: #929db0;
    margin-right: 12px;
}

.network-row .net-ssid {
    font-size: 12.5px;
    font-weight: 500;
    color: #c7d0dc;
}

.network-row .net-lock {
    font-size: 12px;
    color: #5d6778;
}

.network-row:hover .net-ssid {
    color: #ffffff;
}

.network-row:hover .net-icon {
    color: #ffffff;
}

/* Input Fields */
entry {
    background-color: #181d26;
    border: 1px solid #333d4e;
    border-radius: 8px;
    padding: 6px 10px;
    color: #ffffff;
    font-size: 12px;
}

entry:focus {
    border-color: #556682;
}

/* Action Dialog / Overlay */
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

# =============================================================================
# Pure Python ISO/IEC 18004 QR Code Generator (Byte Mode, ECC Level M)
# =============================================================================

EXP_TABLE = [0] * 512
LOG_TABLE = [0] * 256
_x = 1
for _i in range(255):
    EXP_TABLE[_i] = _x
    EXP_TABLE[_i + 255] = _x
    LOG_TABLE[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D

def _gf_mul(x, y):
    if x == 0 or y == 0:
        return 0
    return EXP_TABLE[(LOG_TABLE[x] + LOG_TABLE[y]) % 255]

def _get_generator_poly(num_ec_bytes):
    g = [1]
    for i in range(num_ec_bytes):
        root = EXP_TABLE[i]
        next_g = [0] * (len(g) + 1)
        for j in range(len(g)):
            next_g[j] ^= g[j]
            next_g[j + 1] ^= _gf_mul(g[j], root)
        g = next_g
    return g

def _rs_encode(data, num_ec_bytes):
    gen = _get_generator_poly(num_ec_bytes)
    msg = list(data) + [0] * num_ec_bytes
    for i in range(len(data)):
        lead = msg[i]
        if lead != 0:
            for j in range(len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], lead)
    return msg[len(data):]

# Specs for ECC Level M: (total_cw, ec_cw_per_blk, g1_blks, g1_data, g2_blks, g2_data)
VERSION_TABLE_M = {
    1:  (26, 10, 1, 16, 0, 0),
    2:  (44, 16, 1, 28, 0, 0),
    3:  (70, 26, 1, 44, 0, 0),
    4:  (100, 18, 2, 32, 0, 0),
    5:  (134, 24, 2, 43, 0, 0),
    6:  (172, 16, 4, 27, 0, 0),
    7:  (196, 18, 4, 31, 0, 0),
    8:  (242, 22, 2, 38, 2, 39),
    9:  (292, 22, 3, 36, 2, 37),
    10: (346, 26, 4, 43, 1, 44)
}

ALIGNMENT_PATTERNS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50]
}

REMAINDER_BITS = {
    1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0
}

def _get_format_bits(ec_level_bits, mask_idx):
    data = (ec_level_bits << 3) | mask_idx
    rem = data << 10
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= (0x537 << (i - 10))
    raw = (data << 10) | rem
    return raw ^ 0x5412

def _calculate_penalty(grid, N):
    penalty = 0
    # Rule 1: 5+ same color in line
    for r in range(N):
        cnt = 1
        for c in range(1, N):
            if grid[r][c] == grid[r][c - 1]:
                cnt += 1
            else:
                if cnt >= 5: penalty += 3 + (cnt - 5)
                cnt = 1
        if cnt >= 5: penalty += 3 + (cnt - 5)

    for c in range(N):
        cnt = 1
        for r in range(1, N):
            if grid[r][c] == grid[r - 1][c]:
                cnt += 1
            else:
                if cnt >= 5: penalty += 3 + (cnt - 5)
                cnt = 1
        if cnt >= 5: penalty += 3 + (cnt - 5)

    # Rule 2: 2x2 blocks
    for r in range(N - 1):
        for c in range(N - 1):
            if grid[r][c] == grid[r + 1][c] == grid[r][c + 1] == grid[r + 1][c + 1]:
                penalty += 3

    # Rule 3: Finder-like patterns
    p1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    p2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for r in range(N):
        for c in range(N - 10):
            sub = grid[r][c:c + 11]
            if sub == p1 or sub == p2:
                penalty += 40
    for c in range(N):
        for r in range(N - 10):
            sub = [grid[r + k][c] for k in range(11)]
            if sub == p1 or sub == p2:
                penalty += 40

    # Rule 4: Dark/Light balance
    dark_count = sum(sum(row) for row in grid)
    pct = (dark_count * 100) / (N * N)
    prev_5 = int(pct / 5) * 5
    next_5 = prev_5 + 5
    penalty += min(abs(prev_5 - 50) // 5, abs(next_5 - 50) // 5) * 10
    return penalty


class PureQRCode:
    """Standard ISO/IEC 18004 QR Code Matrix Encoder."""
    @staticmethod
    def encode(text: str):
        # 1. Check if qrencode CLI is available as high-speed system utility
        try:
            p = subprocess.run(['qrencode', '-t', 'ASCII', '-m', '4', text],
                               capture_output=True, text=True, check=True)
            lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
            matrix = []
            for line in lines:
                row = [1 if ch != ' ' else 0 for ch in line]
                matrix.append(row)
            if matrix:
                return matrix
        except Exception:
            pass

        # 2. Pure Python Engine
        data_bytes = text.encode('utf-8')
        length = len(data_bytes)

        version = None
        for v in range(1, 11):
            tot, ec_cw, g1_b, g1_d, g2_b, g2_d = VERSION_TABLE_M[v]
            cap = g1_b * g1_d + g2_b * g2_d
            hdr_bits = 4 + (16 if v >= 10 else 8)
            if hdr_bits + length * 8 <= cap * 8:
                version = v
                break

        if not version:
            version = 10

        tot, ec_cw, g1_b, g1_d, g2_b, g2_d = VERSION_TABLE_M[version]
        total_data_cw = g1_b * g1_d + g2_b * g2_d

        # Build Bitstream
        bit_str = "0100"  # Byte mode
        char_count_len = 16 if version >= 10 else 8
        bit_str += format(length, f'0{char_count_len}b')
        for b in data_bytes:
            bit_str += format(b, '08b')

        # Terminator
        rem_cap_bits = total_data_cw * 8 - len(bit_str)
        bit_str += "0" * max(0, min(4, rem_cap_bits))

        if len(bit_str) % 8 != 0:
            bit_str += "0" * (8 - (len(bit_str) % 8))

        pad_bytes = ["11101100", "00010001"]
        pad_idx = 0
        while len(bit_str) < total_data_cw * 8:
            bit_str += pad_bytes[pad_idx % 2]
            pad_idx += 1

        data_codewords = [int(bit_str[i:i+8], 2) for i in range(0, len(bit_str), 8)]

        # Blocks and ECC
        data_blocks, ec_blocks = [], []
        offset = 0
        for _ in range(g1_b):
            blk = data_codewords[offset:offset + g1_d]
            data_blocks.append(blk)
            ec_blocks.append(_rs_encode(blk, ec_cw))
            offset += g1_d
        for _ in range(g2_b):
            blk = data_codewords[offset:offset + g2_d]
            data_blocks.append(blk)
            ec_blocks.append(_rs_encode(blk, ec_cw))
            offset += g2_d

        # Interleave
        final_cw = []
        max_d = max(len(b) for b in data_blocks)
        for i in range(max_d):
            for blk in data_blocks:
                if i < len(blk): final_cw.append(blk[i])
        for i in range(ec_cw):
            for blk in ec_blocks:
                final_cw.append(blk[i])

        final_bits = "".join(format(cw, '08b') for cw in final_cw)
        final_bits += "0" * REMAINDER_BITS[version]

        # Construct Matrix
        N = 4 * version + 17
        matrix = [[0] * N for _ in range(N)]
        is_func = [[False] * N for _ in range(N)]

        def set_func(r, c, val):
            matrix[r][c] = val
            is_func[r][c] = True

        # Finder Patterns
        def place_finder(top, left):
            for r in range(7):
                for c in range(7):
                    if (r in (0, 6) or c in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4):
                        set_func(top + r, left + c, 1)
                    else:
                        set_func(top + r, left + c, 0)
            for r in range(-1, 8):
                for c in range(-1, 8):
                    rr, cc = top + r, left + c
                    if 0 <= rr < N and 0 <= cc < N and not is_func[rr][cc]:
                        set_func(rr, cc, 0)

        place_finder(0, 0)
        place_finder(0, N - 7)
        place_finder(N - 7, 0)

        # Alignment Patterns
        pos = ALIGNMENT_PATTERNS[version]
        for r in pos:
            for c in pos:
                if (r <= 8 and c <= 8) or (r <= 8 and c >= N - 9) or (r >= N - 9 and c <= 8):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        rr, cc = r + dr, c + dc
                        if abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0):
                            set_func(rr, cc, 1)
                        else:
                            set_func(rr, cc, 0)

        # Timing Patterns
        for i in range(8, N - 8):
            if not is_func[6][i]: set_func(6, i, 1 if i % 2 == 0 else 0)
            if not is_func[i][6]: set_func(i, 6, 1 if i % 2 == 0 else 0)

        # Dark Module
        set_func(4 * version + 9, 8, 1)

        # Reserve Format Areas
        for c in range(9):
            if not is_func[8][c]: is_func[8][c] = True
            if not is_func[c][8]: is_func[c][8] = True
        for c in range(N - 8, N):
            if not is_func[8][c]: is_func[8][c] = True
        for r in range(N - 7, N):
            if not is_func[r][8]: is_func[r][8] = True

        # Zig-Zag Data Placement
        bit_idx = 0
        bit_len = len(final_bits)
        c = N - 1
        upward = True

        while c > 0:
            if c == 6:
                c -= 1
            rows = range(N - 1, -1, -1) if upward else range(N)
            for r in rows:
                for col in (c, c - 1):
                    if not is_func[r][col]:
                        val = int(final_bits[bit_idx]) if bit_idx < bit_len else 0
                        matrix[r][col] = val
                        bit_idx += 1
            upward = not upward
            c -= 2

        # Masking & Optimal Selection
        mask_fns = [
            lambda r, c: (r + c) % 2 == 0,
            lambda r, c: r % 2 == 0,
            lambda r, c: c % 3 == 0,
            lambda r, c: (r + c) % 3 == 0,
            lambda r, c: (r // 2 + c // 3) % 2 == 0,
            lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
            lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
            lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0
        ]

        best_score = float('inf')
        best_grid = matrix

        coords_1 = [(8,0), (8,1), (8,2), (8,3), (8,4), (8,5), (8,7), (8,8),
                    (7,8), (5,8), (4,8), (3,8), (2,8), (1,8), (0,8)]
        coords_2 = [(N-1,8), (N-2,8), (N-3,8), (N-4,8), (N-5,8), (N-6,8), (N-7,8),
                    (8,N-8), (8,N-7), (8,N-6), (8,N-5), (8,N-4), (8,N-3), (8,N-2), (8,N-1)]

        for mask_idx in range(8):
            test_grid = [row[:] for row in matrix]
            fn = mask_fns[mask_idx]
            for r in range(N):
                for col in range(N):
                    if not is_func[r][col]:
                        test_grid[r][col] ^= (1 if fn(r, col) else 0)

            fmt = _get_format_bits(0, mask_idx)  # EC Level M = 0
            fmt_bits = [int(b) for b in format(fmt, '015b')]

            for k in range(15):
                r1, c1 = coords_1[k]
                r2, c2 = coords_2[k]
                test_grid[r1][c1] = fmt_bits[k]
                test_grid[r2][c2] = fmt_bits[k]

            score = _calculate_penalty(test_grid, N)
            if score < best_score:
                best_score = score
                best_grid = test_grid

        # Add 4-module Quiet Zone
        quiet = 4
        total_size = N + 2 * quiet
        result = [[0] * total_size for _ in range(total_size)]
        for r in range(N):
            for col in range(N):
                result[r + quiet][col + quiet] = best_grid[r][col]

        return result


class QRDrawingArea(Gtk.DrawingArea):
    def __init__(self, matrix, size=210):
        super().__init__()
        self.matrix = matrix
        self.box_size = size
        self.set_size_request(size, size)
        self.connect("draw", self.on_draw)

    def on_draw(self, widget, cr):
        if not self.matrix:
            return False
        n = len(self.matrix)
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        
        # Calculate pixel-aligned module size
        module_size = max(1, math.floor(min(w, h) / n))
        total_dim = module_size * n
        offset_x = (w - total_dim) / 2
        offset_y = (h - total_dim) / 2

        # 1. Pure White Background
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # 2. Crisp Black Modules
        cr.set_source_rgb(0.0, 0.0, 0.0)
        for r in range(n):
            for c in range(n):
                if self.matrix[r][c]:
                    cr.rectangle(
                        math.floor(offset_x + c * module_size),
                        math.floor(offset_y + r * module_size),
                        math.ceil(module_size),
                        math.ceil(module_size)
                    )
        cr.fill()
        return False


class WifiControlCenter(Gtk.Window):
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

        # Allow transparent window
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        self.connect("draw", self.on_window_draw)
        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", Gtk.main_quit)

        # Network state variables
        self.wifi_device = self.find_wifi_device()
        self.prev_rx = 0
        self.prev_tx = 0
        self.prev_time = time.time()
        self.active_ssid = ""
        self.active_security = ""
        self.active_bssid = ""
        self.wifi_enabled = True
        self.speedtest_running = False

        self.init_ui()
        self.apply_css()

        # Initial data poll
        self.poll_wifi_state()
        self.poll_stats()
        self.scan_networks()

        # Timers
        GLib.timeout_add(1500, self.poll_stats)
        GLib.timeout_add(10000, self.scan_networks)

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

                # Solid dark card background #12151c
                cr.set_source_rgb(18 / 255.0, 21 / 255.0, 28 / 255.0)
                cr.fill_preserve()

                # Border #2b3240
                cr.set_source_rgb(43 / 255.0, 50 / 255.0, 64 / 255.0)
                cr.set_line_width(1.0)
                cr.stroke()

        return False

    def on_backdrop_clicked(self, widget, event):
        alloc = self.card.get_allocation()
        if alloc.x <= event.x <= alloc.x + alloc.width and alloc.y <= event.y <= alloc.y + alloc.height:
            return False
        self.close()
        return True

    def find_wifi_device(self):
        try:
            for iface in os.listdir('/sys/class/net'):
                if os.path.exists(f'/sys/class/net/{iface}/wireless') or os.path.exists(f'/sys/class/net/{iface}/phy80211'):
                    return iface
        except Exception:
            pass
        return "wlo1"

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
        self.card.get_style_context().add_class("wifi-window")
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

        # Large Wi-Fi Icon
        self.header_icon = Gtk.Label(label="")
        self.header_icon.get_style_context().add_class("wifi-icon-large")
        self.header_icon.set_size_request(36, 36)
        self.header_icon.set_halign(Gtk.Align.CENTER)
        self.header_icon.set_valign(Gtk.Align.CENTER)
        header_box.pack_start(self.header_icon, False, False, 0)

        # Title + Subtitle Box
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_valign(Gtk.Align.CENTER)
        self.ssid_title = Gtk.Label(label="Wi-Fi", xalign=0)
        self.ssid_title.get_style_context().add_class("ssid-title")
        self.ssid_subtitle = Gtk.Label(label="COUNTING COLLISIONS", xalign=0)
        self.ssid_subtitle.get_style_context().add_class("ssid-subtitle")
        title_box.pack_start(self.ssid_title, False, False, 0)
        title_box.pack_start(self.ssid_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Right Action Box (QR + Switch)
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions_box.set_valign(Gtk.Align.CENTER)
        header_box.pack_end(actions_box, False, False, 0)

        # QR Code Button
        self.qr_btn = Gtk.Button(label="󰐲")
        self.qr_btn.get_style_context().add_class("icon-button")
        self.qr_btn.set_tooltip_text("Show QR code")
        self.qr_btn.connect("clicked", self.toggle_qr_modal)
        actions_box.pack_start(self.qr_btn, False, False, 0)

        # Wi-Fi Power Switch
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.connect("state-set", self.on_switch_toggled)
        actions_box.pack_start(self.wifi_switch, False, False, 0)

        # Modal/Overlay Container for QR Code / Connection dialogs
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
        l_ping = Gtk.Label(label="Ping", xalign=0)
        l_ping.get_style_context().add_class("stat-label")
        self.v_ping = Gtk.Label(label="-- ms", xalign=1)
        self.v_ping.get_style_context().add_class("stat-value")

        l_recv = Gtk.Label(label="Receiving", xalign=0)
        l_recv.get_style_context().add_class("stat-label")
        self.v_recv = Gtk.Label(label="0.0 KB/s", xalign=1)
        self.v_recv.get_style_context().add_class("stat-value")

        l_down = Gtk.Label(label="Downloaded", xalign=0)
        l_down.get_style_context().add_class("stat-label")
        self.v_down = Gtk.Label(label="0.00 GB", xalign=1)
        self.v_down.get_style_context().add_class("stat-value")

        l_ip = Gtk.Label(label="IP Address", xalign=0)
        l_ip.get_style_context().add_class("stat-label")
        self.v_ip = Gtk.Label(label="0.0.0.0", xalign=1)
        self.v_ip.get_style_context().add_class("stat-value")

        # Column 2
        l_loss = Gtk.Label(label="Packet Loss", xalign=0)
        l_loss.get_style_context().add_class("stat-label")
        self.v_loss = Gtk.Label(label="0%", xalign=1)
        self.v_loss.get_style_context().add_class("stat-value")

        l_send = Gtk.Label(label="Sending", xalign=0)
        l_send.get_style_context().add_class("stat-label")
        self.v_send = Gtk.Label(label="0.0 KB/s", xalign=1)
        self.v_send.get_style_context().add_class("stat-value")

        l_up = Gtk.Label(label="Uploaded", xalign=0)
        l_up.get_style_context().add_class("stat-label")
        self.v_up = Gtk.Label(label="0.00 GB", xalign=1)
        self.v_up.get_style_context().add_class("stat-value")

        l_gw = Gtk.Label(label="Gateway", xalign=0)
        l_gw.get_style_context().add_class("stat-label")
        self.v_gw = Gtk.Label(label="0.0.0.0", xalign=1)
        self.v_gw.get_style_context().add_class("stat-value")

        # Attach to Grid
        stats_grid.attach(l_ping, 0, 0, 1, 1)
        stats_grid.attach(self.v_ping, 1, 0, 1, 1)
        stats_grid.attach(l_loss, 2, 0, 1, 1)
        stats_grid.attach(self.v_loss, 3, 0, 1, 1)

        stats_grid.attach(l_recv, 0, 1, 1, 1)
        stats_grid.attach(self.v_recv, 1, 1, 1, 1)
        stats_grid.attach(l_send, 2, 1, 1, 1)
        stats_grid.attach(self.v_send, 3, 1, 1, 1)

        stats_grid.attach(l_down, 0, 2, 1, 1)
        stats_grid.attach(self.v_down, 1, 2, 1, 1)
        stats_grid.attach(l_up, 2, 2, 1, 1)
        stats_grid.attach(self.v_up, 3, 2, 1, 1)

        stats_grid.attach(l_ip, 0, 3, 1, 1)
        stats_grid.attach(self.v_ip, 1, 3, 1, 1)
        stats_grid.attach(l_gw, 2, 3, 1, 1)
        stats_grid.attach(self.v_gw, 3, 3, 1, 1)

        # Set column expands
        stats_grid.set_column_homogeneous(False)
        stats_grid.get_child_at(1, 0).set_hexpand(True)
        stats_grid.get_child_at(3, 0).set_hexpand(True)

        # 3. DNS Provider Section
        dns_title = Gtk.Label(label="DNS PROVIDER", xalign=0)
        dns_title.get_style_context().add_class("section-title")
        main_box.pack_start(dns_title, False, False, 0)

        dns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dns_box.set_homogeneous(True)
        main_box.pack_start(dns_box, False, False, 0)

        self.dns_btns = {}
        for name in ["DHCP", "Cloudflare", "Google", "Custom"]:
            btn = Gtk.Button(label=name)
            btn.get_style_context().add_class("dns-btn")
            btn.connect("clicked", self.on_dns_clicked, name)
            dns_box.pack_start(btn, True, True, 0)
            self.dns_btns[name] = btn

        # 4. Speed Test Section
        speed_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        speed_title = Gtk.Label(label="SPEED TEST", xalign=0)
        speed_title.get_style_context().add_class("section-title")
        speed_header.pack_start(speed_title, True, True, 0)

        self.speed_btn = Gtk.Button(label="Run")
        self.speed_btn.get_style_context().add_class("speed-run-btn")
        self.speed_btn.set_valign(Gtk.Align.CENTER)
        self.speed_btn.connect("clicked", self.run_speedtest)
        speed_header.pack_end(self.speed_btn, False, False, 0)
        main_box.pack_start(speed_header, False, False, 0)

        # 5. Known Networks Section
        self.known_title = Gtk.Label(label="KNOWN NETWORKS", xalign=0)
        self.known_title.get_style_context().add_class("section-title")
        main_box.pack_start(self.known_title, False, False, 0)

        self.known_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        main_box.pack_start(self.known_container, False, False, 0)

        # 6. Other Networks Section
        other_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.other_title = Gtk.Label(label="OTHER NETWORKS", xalign=0)
        self.other_title.get_style_context().add_class("section-title")
        other_header.pack_start(self.other_title, True, True, 0)

        self.rescan_btn = Gtk.Button(label="󰑐")
        self.rescan_btn.get_style_context().add_class("flat-icon-btn")
        self.rescan_btn.set_valign(Gtk.Align.CENTER)
        self.rescan_btn.set_tooltip_text("Rescan networks")
        self.rescan_btn.connect("clicked", lambda w: self.trigger_rescan())
        other_header.pack_end(self.rescan_btn, False, False, 0)
        main_box.pack_start(other_header, False, False, 0)

        # Scrollable area for other networks
        self.scroll_win = Gtk.ScrolledWindow()
        self.scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll_win.set_min_content_height(80)
        self.scroll_win.set_max_content_height(220)
        self.scroll_win.set_propagate_natural_height(True)
        main_box.pack_start(self.scroll_win, True, True, 0)

        self.other_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scroll_win.add(self.other_container)

    # -------------------------------------------------------------
    # State & Polling
    # -------------------------------------------------------------
    def poll_wifi_state(self):
        def worker():
            try:
                state = subprocess.check_output(["nmcli", "radio", "wifi"], text=True).strip()
                was_enabled = self.wifi_enabled
                self.wifi_enabled = (state == "enabled")
                def update_switch():
                    self.wifi_switch.handler_block_by_func(self.on_switch_toggled)
                    self.wifi_switch.set_active(self.wifi_enabled)
                    self.wifi_switch.handler_unblock_by_func(self.on_switch_toggled)
                GLib.idle_add(update_switch)

                # If enabled state changed externally, trigger scan
                if not was_enabled and self.wifi_enabled:
                    self.scan_networks(rescan=True)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def on_switch_toggled(self, switch, state):
        self.wifi_enabled = state
        if not state:
            # Turned off: update UI immediately
            self.active_ssid = ""
            self.ssid_title.set_text("Wi-Fi Disabled")
            self.ssid_subtitle.set_text("NO ACTIVE CONNECTION")
            self.header_icon.set_text("󰤮")
            self._render_networks(None, [])

        def toggle_worker():
            cmd = ["nmcli", "radio", "wifi", "on" if state else "off"]
            subprocess.run(cmd, check=False)
            if state:
                # Multi-stage scan after turning radio on to catch devices as adapter warms up
                time.sleep(1.0)
                subprocess.run(["nmcli", "device", "wifi", "rescan"], stderr=subprocess.DEVNULL)
                time.sleep(1.2)
                self._do_scan_parse()
                time.sleep(2.0)
                self._do_scan_parse()
            else:
                self._do_scan_parse()

        threading.Thread(target=toggle_worker, daemon=True).start()
        return True

    def poll_stats(self):
        # 1. Update Traffic stats from /proc/net/dev
        try:
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if self.wifi_device in line:
                        parts = line.split(":")[1].split()
                        rx_bytes = int(parts[0])
                        tx_bytes = int(parts[8])
                        colls = int(parts[14])

                        now = time.time()
                        dt = now - self.prev_time
                        if self.prev_rx > 0 and dt > 0:
                            rx_rate = (rx_bytes - self.prev_rx) / dt
                            tx_rate = (tx_bytes - self.prev_tx) / dt
                            self.v_recv.set_text(self.format_rate(rx_rate))
                            self.v_send.set_text(self.format_rate(tx_rate))

                        self.prev_rx = rx_bytes
                        self.prev_tx = tx_bytes
                        self.prev_time = now

                        # Total download / upload
                        self.v_down.set_text(self.format_bytes(rx_bytes))
                        self.v_up.set_text(self.format_bytes(tx_bytes))
                        break
        except Exception:
            pass

        # 2. Update IP and Gateway
        threading.Thread(target=self._fetch_network_details, daemon=True).start()
        return True

    def _fetch_network_details(self):
        ip_addr = "Disconnected"
        gateway = "---"
        try:
            out_ip = subprocess.check_output(
                ["ip", "-4", "addr", "show", self.wifi_device], text=True, stderr=subprocess.DEVNULL
            )
            m_ip = re.search(r"inet\s+([0-9.]+)", out_ip)
            if m_ip:
                ip_addr = m_ip.group(1)

            out_gw = subprocess.check_output(
                ["ip", "-4", "route", "show", "default"], text=True, stderr=subprocess.DEVNULL
            )
            m_gw = re.search(r"via\s+([0-9.]+)", out_gw)
            if m_gw:
                gateway = m_gw.group(1)
        except Exception:
            pass

        # Immediately update IP and Gateway on UI
        GLib.idle_add(lambda: (self.v_ip.set_text(ip_addr), self.v_gw.set_text(gateway)))

        # Ping target asynchronously in background
        ping_str = "---"
        loss_str = "0%"
        target = gateway if gateway != "---" else "1.1.1.1"
        try:
            out_ping = subprocess.check_output(
                ["ping", "-c", "1", "-W", "1", target], text=True, stderr=subprocess.DEVNULL
            )
            m_loss = re.search(r"(\d+)% packet loss", out_ping)
            if m_loss:
                loss_str = f"{m_loss.group(1)}%"
            m_time = re.search(r"time=([0-9.]+)\s*ms", out_ping)
            if m_time:
                ping_str = f"{int(float(m_time.group(1)))} ms"
        except Exception:
            loss_str = "100%" if ip_addr != "Disconnected" else "---"

        GLib.idle_add(lambda: (self.v_ping.set_text(ping_str), self.v_loss.set_text(loss_str)))

    def _update_network_labels(self, ip_addr, gateway, ping_str, loss_str):
        self.v_ip.set_text(ip_addr)
        self.v_gw.set_text(gateway)
        self.v_ping.set_text(ping_str)
        self.v_loss.set_text(loss_str)

    def format_rate(self, b_per_sec):
        if b_per_sec < 1024:
            return f"{b_per_sec:.1f} B/s"
        elif b_per_sec < 1024 * 1024:
            return f"{b_per_sec / 1024:.1f} KB/s"
        else:
            return f"{b_per_sec / (1024 * 1024):.1f} MB/s"

    def format_bytes(self, b):
        if b < 1024 * 1024:
            return f"{b / 1024:.2f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.2f} MB"
        else:
            return f"{b / (1024 * 1024 * 1024):.2f} GB"

    def scan_networks(self, rescan=False):
        if not self.wifi_enabled:
            self._do_scan_parse()
            return True

        def worker():
            self._do_scan_parse()
            if rescan:
                subprocess.run(["nmcli", "device", "wifi", "rescan"], stderr=subprocess.DEVNULL)
                self._do_scan_parse()

        threading.Thread(target=worker, daemon=True).start()
        return True

    def trigger_rescan(self):
        self.rescan_btn.set_sensitive(False)
        def worker():
            subprocess.run(["nmcli", "device", "wifi", "rescan"], stderr=subprocess.DEVNULL)
            time.sleep(1.2)
            self._do_scan_parse()
            GLib.idle_add(lambda: self.rescan_btn.set_sensitive(True))
        threading.Thread(target=worker, daemon=True).start()

    def _do_scan_parse(self):
        try:
            out = subprocess.check_output(
                ["nmcli", "-m", "multiline", "-f", "ACTIVE,SSID,SIGNAL,SECURITY,BSSID", "device", "wifi", "list"],
                text=True, stderr=subprocess.DEVNULL
            )
            saved_out = subprocess.check_output(
                ["nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show"],
                text=True, stderr=subprocess.DEVNULL
            )
            saved_ssids = set()
            for l in saved_out.strip().splitlines():
                p = l.split(":")
                if len(p) >= 3 and p[2] == "802-11-wireless":
                    saved_ssids.add(p[0])

            current = {}
            entries = []
            for line in out.splitlines():
                m = re.match(r"^([A-Z-]+):\s*(.*)$", line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if key == "ACTIVE":
                        if current and current.get("SSID") and current.get("SSID") != "--":
                            entries.append(current)
                        current = {"ACTIVE": (val == "yes")}
                    else:
                        current[key] = val
            if current and current.get("SSID") and current.get("SSID") != "--":
                entries.append(current)

            active_net = None
            other_nets = []
            seen = set()

            for item in entries:
                ssid = item.get("SSID", "")
                if not ssid or ssid == "--":
                    continue
                is_active = item.get("ACTIVE", False)
                sig_str = item.get("SIGNAL", "0")
                signal = int(sig_str) if sig_str.isdigit() else 0
                security = item.get("SECURITY", "")
                bssid = item.get("BSSID", "")

                if is_active:
                    active_net = {
                        "ssid": ssid, "signal": signal,
                        "security": security, "bssid": bssid
                    }
                elif ssid not in seen:
                    seen.add(ssid)
                    other_nets.append({
                        "ssid": ssid, "signal": signal,
                        "security": security, "saved": (ssid in saved_ssids)
                    })

            other_nets.sort(key=lambda x: x["signal"], reverse=True)
            GLib.idle_add(self._render_networks, active_net, other_nets)
        except Exception as e:
            print(f"Scan error: {e}")

    def _render_networks(self, active_net, other_nets):
        # Update Header
        if active_net:
            self.active_ssid = active_net["ssid"]
            self.active_security = active_net["security"]
            self.active_bssid = active_net["bssid"]
            self.ssid_title.set_text(self.active_ssid)
            self.ssid_subtitle.set_text("COUNTING COLLISIONS")
            self.header_icon.set_text("")
        else:
            self.active_ssid = ""
            self.ssid_title.set_text("Wi-Fi Disconnected" if self.wifi_enabled else "Wi-Fi Disabled")
            self.ssid_subtitle.set_text("NO ACTIVE CONNECTION")
            self.header_icon.set_text("󰤮")

        # Update DNS Active Provider
        self.update_active_dns()

        # Render Known / Active Card
        for child in self.known_container.get_children():
            self.known_container.remove(child)

        if active_net:
            card = Gtk.EventBox()
            card.get_style_context().add_class("known-network-card")
            card_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card_box.set_margin_start(14)
            card_box.set_margin_end(14)
            card_box.set_margin_top(10)
            card_box.set_margin_bottom(10)
            card.add(card_box)

            net_icon = Gtk.Label(label="")
            net_icon.get_style_context().add_class("net-icon")
            net_icon.set_size_request(24, 24)
            net_icon.set_valign(Gtk.Align.CENTER)
            net_icon.set_halign(Gtk.Align.CENTER)
            card_box.pack_start(net_icon, False, False, 0)

            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            info_box.set_valign(Gtk.Align.CENTER)
            lbl_ssid = Gtk.Label(label=active_net["ssid"], xalign=0)
            lbl_ssid.get_style_context().add_class("net-ssid")
            lbl_status = Gtk.Label(label="Connected", xalign=0)
            lbl_status.get_style_context().add_class("net-status")
            info_box.pack_start(lbl_ssid, False, False, 0)
            info_box.pack_start(lbl_status, False, False, 0)
            card_box.pack_start(info_box, True, True, 0)

            if active_net["security"] and active_net["security"] != "--":
                lock_icon = Gtk.Label(label="")
                lock_icon.get_style_context().add_class("net-lock")
                lock_icon.set_valign(Gtk.Align.CENTER)
                card_box.pack_end(lock_icon, False, False, 0)

            card.connect("button-press-event", self.on_active_card_clicked, active_net["ssid"])
            self.known_container.pack_start(card, False, False, 0)
            self.known_title.show()
            self.known_container.show_all()
        else:
            self.known_title.hide()

        # Render Other Networks List
        for child in self.other_container.get_children():
            self.other_container.remove(child)

        if not self.wifi_enabled:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(12)
            empty_box.set_margin_bottom(12)
            lbl = Gtk.Label(label="Wi-Fi is turned off")
            lbl.get_style_context().add_class("stat-label")
            empty_box.pack_start(lbl, False, False, 0)
            self.other_container.pack_start(empty_box, False, False, 0)
        elif not other_nets:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.set_margin_top(12)
            empty_box.set_margin_bottom(12)
            lbl = Gtk.Label(label="No other networks in range")
            lbl.get_style_context().add_class("stat-label")
            empty_box.pack_start(lbl, False, False, 0)
            self.other_container.pack_start(empty_box, False, False, 0)
        else:
            for net in other_nets:
                row = Gtk.EventBox()
                row.get_style_context().add_class("network-row")
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row_box.set_margin_start(10)
                row_box.set_margin_end(10)
                row_box.set_margin_top(7)
                row_box.set_margin_bottom(7)
                row.add(row_box)

                # Signal icon
                sig = net["signal"]
                icon_str = "󰤨" if sig >= 75 else ("󰤥" if sig >= 50 else ("󰤢" if sig >= 25 else "󰤟"))
                icon_lbl = Gtk.Label(label=icon_str)
                icon_lbl.get_style_context().add_class("net-icon")
                icon_lbl.set_size_request(24, 24)
                icon_lbl.set_valign(Gtk.Align.CENTER)
                row_box.pack_start(icon_lbl, False, False, 0)

                ssid_lbl = Gtk.Label(label=net["ssid"], xalign=0)
                ssid_lbl.get_style_context().add_class("net-ssid")
                ssid_lbl.set_valign(Gtk.Align.CENTER)
                row_box.pack_start(ssid_lbl, True, True, 0)

                if net["security"] and net["security"] != "--":
                    lock_lbl = Gtk.Label(label="")
                    lock_lbl.get_style_context().add_class("net-lock")
                    lock_lbl.set_valign(Gtk.Align.CENTER)
                    row_box.pack_end(lock_lbl, False, False, 0)

                row.connect("button-press-event", self.on_network_row_clicked, net)
                self.other_container.pack_start(row, False, False, 0)

        self.scroll_win.show_all()
        self.other_container.show_all()

    # -------------------------------------------------------------
    # DNS Provider Management
    # -------------------------------------------------------------
    def get_active_connection_name(self):
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "DEVICE,NAME", "connection", "show", "--active"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[0] == self.wifi_device:
                    return parts[1]
        except Exception:
            pass
        return self.active_ssid or None

    def update_active_dns(self):
        conn_name = self.get_active_connection_name()
        if not conn_name:
            for b in self.dns_btns.values():
                b.get_style_context().remove_class("active")
            return

        def dns_worker():
            provider = "DHCP"
            try:
                # 1. Check /etc/resolv.conf for active resolver IPs
                resolv_content = ""
                if os.path.exists("/etc/resolv.conf"):
                    with open("/etc/resolv.conf", "r") as f:
                        resolv_content = f.read()

                if "1.1.1.1" in resolv_content or "1.0.0.1" in resolv_content:
                    provider = "Cloudflare"
                elif "8.8.8.8" in resolv_content or "8.8.4.4" in resolv_content:
                    provider = "Google"
                else:
                    # 2. Check connection profile configuration in NetworkManager
                    ignore_auto = subprocess.check_output(
                        ["nmcli", "-g", "ipv4.ignore-auto-dns", "connection", "show", conn_name],
                        text=True, stderr=subprocess.DEVNULL
                    ).strip()
                    dns_servers = subprocess.check_output(
                        ["nmcli", "-g", "ipv4.dns", "connection", "show", conn_name],
                        text=True, stderr=subprocess.DEVNULL
                    ).strip()

                    if ignore_auto == "yes" and dns_servers:
                        if "1.1.1.1" in dns_servers or "1.0.0.1" in dns_servers:
                            provider = "Cloudflare"
                        elif "8.8.8.8" in dns_servers or "8.8.4.4" in dns_servers:
                            provider = "Google"
                        else:
                            provider = "Custom"
                    else:
                        provider = "DHCP"
            except Exception:
                pass

            GLib.idle_add(self._set_dns_button_active, provider)

        threading.Thread(target=dns_worker, daemon=True).start()

    def _set_dns_button_active(self, provider):
        for name, btn in self.dns_btns.items():
            if name == provider:
                btn.get_style_context().add_class("active")
            else:
                btn.get_style_context().remove_class("active")

    def on_dns_clicked(self, widget, name):
        conn_name = self.get_active_connection_name()
        if not conn_name:
            return

        if name == "Custom":
            self.show_custom_dns_dialog()
            return

        dns_configs = {
            "DHCP": {
                "v4_dns": "", "v4_ignore": "no",
                "v6_dns": "", "v6_ignore": "no",
                "label": "DHCP (Automatic)"
            },
            "Cloudflare": {
                "v4_dns": "1.1.1.1 1.0.0.1", "v4_ignore": "yes",
                "v6_dns": "2606:4700:4700::1111 2606:4700:4700::1001", "v6_ignore": "yes",
                "label": "Cloudflare (1.1.1.1)"
            },
            "Google": {
                "v4_dns": "8.8.8.8 8.8.4.4", "v4_ignore": "yes",
                "v6_dns": "2001:4860:4860::8888 2001:4860:4860::8844", "v6_ignore": "yes",
                "label": "Google DNS (8.8.8.8)"
            }
        }

        cfg = dns_configs.get(name)
        if not cfg:
            return

        def apply_dns():
            try:
                # Apply IPv4 DNS settings
                subprocess.run([
                    "nmcli", "connection", "modify", conn_name,
                    "ipv4.ignore-auto-dns", cfg["v4_ignore"],
                    "ipv4.dns", cfg["v4_dns"]
                ], check=True)
                # Apply IPv6 DNS settings (if supported)
                subprocess.run([
                    "nmcli", "connection", "modify", conn_name,
                    "ipv6.ignore-auto-dns", cfg["v6_ignore"],
                    "ipv6.dns", cfg["v6_dns"]
                ], stderr=subprocess.DEVNULL)
                # Reapply connection settings immediately
                subprocess.run(["nmcli", "connection", "up", conn_name], check=True)
                subprocess.run([
                    "notify-send", "-a", "Wi-Fi", "-i", "network-wireless",
                    "DNS Provider Changed", f"Active DNS: {cfg['label']}"
                ], check=False)
                GLib.idle_add(self.update_active_dns)
            except Exception as e:
                print(f"Error changing DNS: {e}")

        threading.Thread(target=apply_dns, daemon=True).start()

    def show_custom_dns_dialog(self):
        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card-overlay")

        title = Gtk.Label(label="Set Custom DNS Servers (space or comma-separated):", xalign=0)
        title.get_style_context().add_class("stat-label")
        card.pack_start(title, False, False, 0)

        entry = Gtk.Entry()
        entry.set_placeholder_text("9.9.9.9 149.112.112.112")
        card.pack_start(entry, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_apply = Gtk.Button(label="Apply")
        btn_apply.get_style_context().add_class("action-btn")
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.get_style_context().add_class("action-btn")

        def on_apply(w):
            dns_val = entry.get_text().strip().replace(",", " ")
            conn_name = self.get_active_connection_name()
            if dns_val and conn_name:
                def worker():
                    subprocess.run([
                        "nmcli", "connection", "modify", conn_name,
                        "ipv4.ignore-auto-dns", "yes",
                        "ipv4.dns", dns_val
                    ], check=False)
                    subprocess.run(["nmcli", "connection", "up", conn_name], check=False)
                    subprocess.run([
                        "notify-send", "-a", "Wi-Fi", "-i", "network-wireless",
                        "Custom DNS Applied", f"Active DNS: {dns_val}"
                    ], check=False)
                    GLib.idle_add(self.update_active_dns)
                threading.Thread(target=worker, daemon=True).start()
            self.clear_overlay()

        btn_apply.connect("clicked", on_apply)
        btn_cancel.connect("clicked", lambda w: self.clear_overlay())
        entry.connect("activate", on_apply)

        btn_box.pack_start(btn_apply, True, True, 0)
        btn_box.pack_start(btn_cancel, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()
        entry.grab_focus()

    # -------------------------------------------------------------
    # Speed Test Runner
    # -------------------------------------------------------------
    def run_speedtest(self, widget):
        if self.speedtest_running:
            return
        self.speedtest_running = True
        self.speed_btn.set_label("Testing...")
        self.speed_btn.set_sensitive(False)

        def worker():
            down_speed = "---"
            up_speed = "---"
            try:
                # Fast chunk download test from Cloudflare CDN
                start = time.time()
                p = subprocess.run([
                    "curl", "-s", "-w", "%{speed_download}", "-o", "/dev/null",
                    "https://speed.cloudflare.com/__down?bytes=10000000"
                ], capture_output=True, text=True, timeout=10)
                dur = time.time() - start
                if p.returncode == 0 and p.stdout.strip():
                    speed_bps = float(p.stdout.strip())
                    down_mbps = (speed_bps * 8) / (1000 * 1000)
                    down_speed = f"{down_mbps:.1f} Mbps"
            except Exception:
                down_speed = "Err"

            GLib.idle_add(self._finish_speedtest, down_speed)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_speedtest(self, result):
        self.speedtest_running = False
        self.speed_btn.set_label(f"↓ {result}")
        self.speed_btn.set_sensitive(True)
        GLib.timeout_add(8000, lambda: self.speed_btn.set_label("Run"))

    # -------------------------------------------------------------
    # QR Code Modal
    # -------------------------------------------------------------
    def toggle_qr_modal(self, widget):
        if len(self.overlay_container.get_children()) > 0:
            self.clear_overlay()
            return

        if not self.active_ssid:
            return

        # Helper to escape special Wi-Fi QR characters
        def escape_wifi_field(s):
            if not s:
                return ""
            res = []
            for ch in s:
                if ch in ('\\', ';', ',', ':', '"'):
                    res.append('\\' + ch)
                else:
                    res.append(ch)
            return "".join(res)

        # 1. Fetch password for current SSID directly by connection name
        password = ""
        try:
            out = subprocess.check_output([
                "nmcli", "-s", "-g",
                "802-11-wireless-security.psk,802-11-wireless-security.wep-key0",
                "connection", "show", self.active_ssid
            ], text=True, stderr=subprocess.DEVNULL).strip().splitlines()
            for p in out:
                if p:
                    password = p
                    break
        except Exception:
            pass

        # 2. If password not found by exact name, inspect all wireless connection profiles
        if not password:
            try:
                conns = subprocess.check_output([
                    "nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show"
                ], text=True, stderr=subprocess.DEVNULL).strip().splitlines()
                for c in conns:
                    parts = c.split(":")
                    if len(parts) >= 3 and "wireless" in parts[2]:
                        uuid = parts[1]
                        conn_ssid = subprocess.check_output([
                            "nmcli", "-g", "802-11-wireless.ssid", "connection", "show", uuid
                        ], text=True, stderr=subprocess.DEVNULL).strip()
                        if conn_ssid == self.active_ssid:
                            p = subprocess.check_output([
                                "nmcli", "-s", "-g",
                                "802-11-wireless-security.psk,802-11-wireless-security.wep-key0",
                                "connection", "show", uuid
                            ], text=True, stderr=subprocess.DEVNULL).strip().splitlines()
                            for line in p:
                                if line:
                                    password = line
                                    break
                            if password:
                                break
            except Exception:
                pass

        # Standard Wi-Fi QR string: WIFI:S:<SSID>;T:<WPA|WEP|nopass>;P:<password>;;
        sec_upper = self.active_security.upper()
        if "WEP" in sec_upper:
            sec_type = "WEP"
        elif "WPA" in sec_upper or "PSK" in sec_upper or "SAE" in sec_upper or password:
            sec_type = "WPA"
        else:
            sec_type = "nopass"

        escaped_ssid = escape_wifi_field(self.active_ssid)
        if sec_type == "nopass" or not password:
            qr_text = f"WIFI:S:{escaped_ssid};T:nopass;;"
        else:
            escaped_pass = escape_wifi_field(password)
            qr_text = f"WIFI:S:{escaped_ssid};T:{sec_type};P:{escaped_pass};;"

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class("card-overlay")

        lbl = Gtk.Label(label=f"Scan to Connect: {self.active_ssid}", xalign=0.5)
        lbl.get_style_context().add_class("stat-label")
        card.pack_start(lbl, False, False, 0)

        # Generate and draw standard QR Code
        try:
            matrix = PureQRCode.encode(qr_text)
            qr_widget = QRDrawingArea(matrix, size=210)
            qr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            qr_box.pack_start(qr_widget, True, False, 0)
            card.pack_start(qr_box, False, False, 4)
        except Exception as e:
            err_lbl = Gtk.Label(label=f"QR Error: {e}")
            card.pack_start(err_lbl, False, False, 4)

        if password:
            pass_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            pass_box.set_halign(Gtk.Align.CENTER)
            p_tag = Gtk.Label(label="Password:")
            p_tag.get_style_context().add_class("stat-label")
            p_val = Gtk.Label(label=password)
            p_val.get_style_context().add_class("stat-value")
            p_val.set_selectable(True)
            pass_box.pack_start(p_tag, False, False, 0)
            pass_box.pack_start(p_val, False, False, 0)
            card.pack_start(pass_box, False, False, 0)
        else:
            open_lbl = Gtk.Label(label="Open Network (No Password)")
            open_lbl.get_style_context().add_class("stat-label")
            card.pack_start(open_lbl, False, False, 0)

        close_btn = Gtk.Button(label="Close QR")
        close_btn.get_style_context().add_class("action-btn")
        close_btn.connect("clicked", lambda w: self.clear_overlay())
        card.pack_start(close_btn, False, False, 4)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()

    def clear_overlay(self):
        for child in self.overlay_container.get_children():
            self.overlay_container.remove(child)

    # -------------------------------------------------------------
    # Network Click Actions & Password Connection
    # -------------------------------------------------------------
    def on_active_card_clicked(self, widget, event, ssid):
        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card-overlay")

        title = Gtk.Label(label=f"Manage '{ssid}'", xalign=0)
        title.get_style_context().add_class("ssid-title")
        card.pack_start(title, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        btn_disc = Gtk.Button(label="Disconnect")
        btn_disc.get_style_context().add_class("action-btn")
        btn_forget = Gtk.Button(label="Forget")
        btn_forget.get_style_context().add_class("action-btn")
        btn_forget.get_style_context().add_class("danger")
        btn_close = Gtk.Button(label="Back")
        btn_close.get_style_context().add_class("action-btn")

        def do_disconnect(w):
            subprocess.run(["nmcli", "connection", "down", ssid], check=False)
            self.clear_overlay()
            self.scan_networks()

        def do_forget(w):
            subprocess.run(["nmcli", "connection", "delete", ssid], check=False)
            self.clear_overlay()
            self.scan_networks()

        btn_disc.connect("clicked", do_disconnect)
        btn_forget.connect("clicked", do_forget)
        btn_close.connect("clicked", lambda w: self.clear_overlay())

        btn_box.pack_start(btn_disc, True, True, 0)
        btn_box.pack_start(btn_forget, True, True, 0)
        btn_box.pack_start(btn_close, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()

    def on_network_row_clicked(self, widget, event, net):
        ssid = net["ssid"]
        is_saved = net.get("saved", False)
        is_secured = bool(net["security"] and net["security"] != "--")

        if is_saved or not is_secured:
            # Connect directly
            def connect_worker():
                if is_saved:
                    subprocess.run(["nmcli", "connection", "up", ssid], check=False)
                else:
                    subprocess.run(["nmcli", "device", "wifi", "connect", ssid], check=False)
                GLib.idle_add(self.scan_networks)
            threading.Thread(target=connect_worker, daemon=True).start()
            return

        # Show inline password entry
        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card-overlay")

        lbl = Gtk.Label(label=f"Enter Password for '{ssid}':", xalign=0)
        lbl.get_style_context().add_class("stat-label")
        card.pack_start(lbl, False, False, 0)

        entry = Gtk.Entry()
        entry.set_visibility(False)
        card.pack_start(entry, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_connect = Gtk.Button(label="Connect")
        btn_connect.get_style_context().add_class("action-btn")
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.get_style_context().add_class("action-btn")

        def do_connect(w):
            pwd = entry.get_text()
            self.clear_overlay()
            def worker():
                subprocess.run(["nmcli", "device", "wifi", "connect", ssid, "password", pwd], check=False)
                GLib.idle_add(self.scan_networks)
            threading.Thread(target=worker, daemon=True).start()

        btn_connect.connect("clicked", do_connect)
        btn_cancel.connect("clicked", lambda w: self.clear_overlay())
        entry.connect("activate", do_connect)

        btn_box.pack_start(btn_connect, True, True, 0)
        btn_box.pack_start(btn_cancel, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()
        entry.grab_focus()


def start_ipc_server(win):
    """Listens on a Unix socket for toggle / close signals."""
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
    """If an instance is already running, send toggle to close it and exit."""
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

    win = WifiControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
