#!/usr/bin/env python3
"""
Waybar Wi-Fi Control Center Popup
A modern, dark-themed Wi-Fi control center built with GTK3 & GtkLayerShell.
"""

import os
import sys
import re
import json
import fcntl
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
try:
    gi.require_version('NM', '1.0')
    from gi.repository import NM
    NM_AVAILABLE = True
except Exception:
    NM_AVAILABLE = False
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell

SOCKET_PATH = f"/tmp/waybar_wifi_menu_{os.getuid()}.sock"
AUTO_SWITCH_SOCKET_PATH = f"/tmp/waybar_wifi_autoswitch_{os.getuid()}.sock"
AUTO_SWITCH_LOCK_PATH = f"/tmp/waybar_wifi_autoswitch_{os.getuid()}.lock"
STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
AUTO_SWITCH_STATE_FILE = os.path.join(STATE_DIR, "waybar-wifi-autoswitch")
WIFI_QUALITY_STATE_FILE = os.path.join(STATE_DIR, "waybar-wifi-quality.json")

QUALITY_HISTORY_TTL = 7 * 24 * 3600
PROACTIVE_PASSIVE_MARGIN = 18.0
PROACTIVE_LIVE_MARGIN = 5.0
HEALTH_CHECK_INTERVAL_SEC = 20
REJECTED_COOLDOWN_SEC = 300.0
FAILED_COOLDOWN_SEC = 180.0
MANUAL_CONNECT_GRACE_SEC = 120.0
POST_SWITCH_SETTLE_SEC = 1.5
TRIAL_CONNECT_TIMEOUT_SEC = 18
HEALTH_PING_BAD_MS = 200.0
HEALTH_LOSS_BAD_PCT = 20.0
HEALTH_SIGNAL_BAD_PCT = 28


def read_auto_switch_enabled():
    try:
        with open(AUTO_SWITCH_STATE_FILE, "r") as f:
            return f.read().strip().lower() in ("1", "true", "on", "yes")
    except OSError:
        return False


def write_auto_switch_enabled(enabled):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(AUTO_SWITCH_STATE_FILE, "w") as f:
            f.write("on\n" if enabled else "off\n")
    except OSError:
        pass


def send_auto_switch_command(cmd):
    if not os.path.exists(AUTO_SWITCH_SOCKET_PATH):
        return False
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.4)
        client.connect(AUTO_SWITCH_SOCKET_PATH)
        client.sendall((cmd.strip() + "\n").encode())
        client.close()
        return True
    except Exception:
        return False


def is_auto_switcher_running():
    if not os.path.exists(AUTO_SWITCH_LOCK_PATH):
        return False
    try:
        fd = os.open(AUTO_SWITCH_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)
    except OSError:
        return False


def ensure_auto_switcher_daemon():
    if is_auto_switcher_running():
        send_auto_switch_command("check")
        return
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--auto-switcher-daemon"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"Auto switcher daemon launch error: {e}")


def _get_ap_ssid(ap):
    if not ap:
        return ""
    sb = ap.get_ssid()
    data = sb.get_data() if sb else None
    ssid = NM.utils_ssid_to_utf8(data) if data else ""
    return "" if (not ssid or ssid == "--") else ssid


def load_wifi_quality_cache():
    try:
        with open(WIFI_QUALITY_STATE_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_wifi_quality_cache(cache):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp_path = f"{WIFI_QUALITY_STATE_FILE}.tmp.{os.getpid()}"
        with open(tmp_path, "w") as f:
            json.dump(cache, f, indent=2)
        os.replace(tmp_path, WIFI_QUALITY_STATE_FILE)
    except OSError:
        pass


def record_ssid_quality(ssid, **fields):
    if not ssid:
        return
    cache = load_wifi_quality_cache()
    entry = dict(cache.get(ssid) or {})
    for key, val in fields.items():
        if val is not None:
            entry[key] = val
    entry["updated_ts"] = int(time.time())
    cache[ssid] = entry
    save_wifi_quality_cache(cache)


def compute_passive_ap_score(signal, max_mbps=0.0, freq_mhz=0, cached=None, now_ts=None):
    """Estimate network quality from beacon/scan RF info and cached past measurements."""
    score = (
        float(signal or 0) * 0.65
        + min(float(max_mbps or 0.0), 600.0) * 0.12
        + (14.0 if (freq_mhz or 0) >= 4900 else 0.0)
    )
    if cached:
        updated_ts = cached.get("updated_ts") or 0
        age = (now_ts if now_ts is not None else time.time()) - updated_ts
        if 0 <= age <= QUALITY_HISTORY_TTL:
            if cached.get("internet_ok") is False:
                score -= 250.0
            elif cached.get("internet_ok") is True:
                score += 20.0
            loss = cached.get("loss_pct")
            if isinstance(loss, (int, float)):
                score -= min(max(float(loss), 0.0), 100.0) * 3.0
            ping_ms = cached.get("ping_ms")
            if isinstance(ping_ms, (int, float)):
                score += max(-40.0, 25.0 - float(ping_ms) * 0.25)
            down_mbps = cached.get("down_mbps")
            if isinstance(down_mbps, (int, float)):
                score += min(max(float(down_mbps), 0.0), 300.0) * 0.15
    return round(score, 2)


def compute_live_network_score(metrics):
    """Score an active connection from real internet health, latency, loss, speed, and RF link."""
    internet_ok = bool(metrics.get("internet_ok"))
    loss_pct = float(metrics.get("loss_pct") if metrics.get("loss_pct") is not None else 100.0)
    ping_ms = metrics.get("ping_ms")
    signal = float(metrics.get("signal") or 0)
    max_mbps = float(metrics.get("max_mbps") or 0.0)
    freq = int(metrics.get("freq") or 0)
    down_mbps = metrics.get("down_mbps")

    score = 1000.0 if internet_ok else -1000.0
    score -= min(max(loss_pct, 0.0), 100.0) * 8.0
    if isinstance(ping_ms, (int, float)):
        score += max(-150.0, 80.0 - float(ping_ms) * 0.6)
    elif not internet_ok:
        score -= 80.0
    score += signal * 0.5 + min(max_mbps, 600.0) * 0.08 + (12.0 if freq >= 4900 else 0.0)
    if isinstance(down_mbps, (int, float)):
        score += min(max(float(down_mbps), 0.0), 300.0) * 0.25
    return round(score, 2)


def classify_network_health(metrics):
    """Return a short reason string if the current network is degraded, or None if healthy."""
    if not metrics.get("internet_ok"):
        return "No internet access"
    loss_pct = float(metrics.get("loss_pct") or 0.0)
    if loss_pct >= HEALTH_LOSS_BAD_PCT:
        return f"{int(round(loss_pct))}% packet loss"
    ping_ms = metrics.get("ping_ms")
    if isinstance(ping_ms, (int, float)) and ping_ms >= HEALTH_PING_BAD_MS:
        return f"High latency ({int(round(ping_ms))} ms)"
    signal = metrics.get("signal")
    if isinstance(signal, (int, float)) and 0 < signal <= HEALTH_SIGNAL_BAD_PCT:
        return f"Weak signal ({int(signal)}%)"
    return None


def _run_ping_probe(target):
    """Run a fast 3-packet ICMP probe and return (loss_pct, avg_ping_ms)."""
    try:
        proc = subprocess.run(
            ["ping", "-n", "-c", "3", "-i", "0.2", "-W", "1", target],
            capture_output=True,
            text=True,
            timeout=4,
        )
        out = proc.stdout or ""
        m_loss = re.search(r"([0-9.]+)%\s+packet loss", out)
        loss_pct = float(m_loss.group(1)) if m_loss else (0.0 if proc.returncode == 0 else 100.0)
        m_rtt = re.search(r"(?:rtt|round-trip) min/avg/max[^=]*=\s*[0-9.]+/([0-9.]+)/", out)
        ping_ms = float(m_rtt.group(1)) if m_rtt else None
        if ping_ms is None:
            times = [float(x) for x in re.findall(r"time=([0-9.]+)\s*ms", out)]
            if times:
                ping_ms = sum(times) / len(times)
        return loss_pct, ping_ms
    except Exception:
        return 100.0, None


def _run_http_connectivity_probe():
    """Verify real HTTP internet reachability without captive portal interception."""
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-L", "--max-time", "2.5",
                "-o", "/dev/null", "-w", "%{http_code}",
                "http://connectivitycheck.gstatic.com/generate_204",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "204"
    except Exception:
        return False


def _run_quick_speed_probe():
    """Measure short download throughput in Mbps (bounded ~1 MB / 1.5s)."""
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "--max-time", "1.5",
                "-w", "%{speed_download}", "-o", "/dev/null",
                "https://speed.cloudflare.com/__down?bytes=1048576",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            bps = float(proc.stdout.strip())
            if bps > 0:
                return round((bps * 8.0) / (1000.0 * 1000.0), 2)
    except Exception:
        pass
    return None


def measure_live_network_quality(signal=0, max_mbps=0.0, freq=0, cached_down_mbps=None, include_speed=False):
    """Measure live internet reachability, packet loss, latency, optional speed, and compute score."""
    loss_pct, ping_ms = _run_ping_probe("1.1.1.1")
    if loss_pct >= 100.0:
        loss2, ping2 = _run_ping_probe("8.8.8.8")
        if loss2 < loss_pct:
            loss_pct, ping_ms = loss2, ping2

    http_ok = _run_http_connectivity_probe()
    internet_ok = bool(http_ok or (loss_pct < 100.0 and ping_ms is not None))
    if http_ok and ping_ms is None and loss_pct >= 100.0:
        loss_pct = 0.0

    down_mbps = cached_down_mbps
    if include_speed and internet_ok:
        measured = _run_quick_speed_probe()
        if measured is not None:
            down_mbps = measured

    metrics = {
        "internet_ok": internet_ok,
        "http_ok": http_ok,
        "loss_pct": round(loss_pct, 1),
        "ping_ms": round(ping_ms, 1) if ping_ms is not None else None,
        "signal": int(signal or 0),
        "max_mbps": round(float(max_mbps or 0.0), 1),
        "freq": int(freq or 0),
        "down_mbps": down_mbps,
    }
    metrics["score"] = compute_live_network_score(metrics)
    metrics["bad_reason"] = classify_network_health(metrics)
    return metrics


def format_comparison_summary(cand_metrics, prev_metrics):
    parts = []
    cp = cand_metrics.get("ping_ms")
    pp = prev_metrics.get("ping_ms")
    if isinstance(cp, (int, float)) and isinstance(pp, (int, float)):
        parts.append(f"{int(round(cp))}ms vs {int(round(pp))}ms")
    cd = cand_metrics.get("down_mbps")
    pd = prev_metrics.get("down_mbps")
    if isinstance(cd, (int, float)) and isinstance(pd, (int, float)):
        parts.append(f"{cd:.1f} vs {pd:.1f} Mbps")
    if not parts:
        parts.append(f"score {cand_metrics.get('score', 0):.0f} vs {prev_metrics.get('score', 0):.0f}")
    return ", ".join(parts)


def is_candidate_better(cand_metrics, prev_metrics, proactive=False):
    """Compare candidate vs previous live metrics; return (is_better, detail_summary)."""
    cand_ok = bool(cand_metrics.get("internet_ok"))
    prev_ok = bool(prev_metrics.get("internet_ok"))
    if not cand_ok:
        return False, "no internet access"
    if not prev_ok:
        return True, "internet restored"

    cand_loss = float(cand_metrics.get("loss_pct") or 0.0)
    prev_loss = float(prev_metrics.get("loss_pct") or 0.0)
    if cand_loss >= HEALTH_LOSS_BAD_PCT and cand_loss > prev_loss + 5.0:
        return False, f"{int(round(cand_loss))}% packet loss"

    margin = PROACTIVE_LIVE_MARGIN if proactive else 0.01
    better = float(cand_metrics.get("score") or 0.0) >= float(prev_metrics.get("score") or 0.0) + margin
    return better, format_comparison_summary(cand_metrics, prev_metrics)


def find_best_saved_candidate(
    nm_client,
    nm_wifi_dev,
    exclude_ssids=None,
    require_previously_connected=False,
    quality_cache=None,
):
    """Return (NM.RemoteConnection, ssid, signal, passive_score) for the highest-scoring in-range saved network."""
    if not nm_client or not nm_wifi_dev:
        return None, None, 0, -9999.0

    saved_profiles = {}
    for conn in nm_client.get_connections():
        s_wifi = conn.get_setting_wireless()
        if not s_wifi:
            continue
        s_conn = conn.get_setting_connection()
        if s_conn and not s_conn.get_autoconnect():
            continue
        sb = s_wifi.get_ssid()
        data = sb.get_data() if sb else None
        ssid = NM.utils_ssid_to_utf8(data) if data else (conn.get_id() or "")
        if not ssid:
            continue
        ts = int(s_conn.get_timestamp()) if s_conn else 0
        if require_previously_connected and ts <= 0:
            continue
        prev = saved_profiles.get(ssid)
        if prev is None or ts > prev[1]:
            saved_profiles[ssid] = (conn, ts)

    if not saved_profiles:
        return None, None, 0, -9999.0

    cache = quality_cache if quality_cache is not None else load_wifi_quality_cache()
    now_ts = time.time()
    best_ap_by_ssid = {}
    for ap in nm_wifi_dev.get_access_points():
        ssid = _get_ap_ssid(ap)
        if not ssid or ssid not in saved_profiles:
            continue
        if exclude_ssids and ssid in exclude_ssids:
            continue
        sig = int(ap.get_strength())
        max_mbps = float(ap.get_max_bitrate() or 0) / 1000.0
        freq = int(ap.get_frequency() or 0)
        ap_score = compute_passive_ap_score(
            sig, max_mbps=max_mbps, freq_mhz=freq, cached=cache.get(ssid), now_ts=now_ts
        )
        prev_ap = best_ap_by_ssid.get(ssid)
        if prev_ap is None or (ap_score, sig) > (prev_ap[1], prev_ap[0]):
            best_ap_by_ssid[ssid] = (sig, ap_score)

    best = None
    for ssid, (sig, ap_score) in best_ap_by_ssid.items():
        conn, ts = saved_profiles[ssid]
        rank = (1 if ts > 0 else 0, ap_score, sig, ts)
        if best is None or rank > best[0]:
            best = (rank, conn, ssid, sig, ap_score)

    if best:
        return best[1], best[2], best[3], best[4]
    return None, None, 0, -9999.0


def find_best_saved_network(nm_client, nm_wifi_dev, exclude_ssids=None):
    """Return (NM.RemoteConnection, ssid, signal) for the strongest previously connected in-range network."""
    conn, ssid, sig, _ = find_best_saved_candidate(
        nm_client, nm_wifi_dev, exclude_ssids=exclude_ssids
    )
    return conn, ssid, sig

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

/* Auto Switcher */
.auto-switch-btn {
    background-color: #171b23;
    border: 1px solid #282f3d;
    border-radius: 8px;
    padding: 4px 14px;
    color: #c5cdd9;
    font-size: 11.5px;
    font-weight: 600;
    transition: all 150ms ease;
}

.auto-switch-btn:hover {
    background-color: #212733;
    border-color: #3b4557;
    color: #ffffff;
}

.auto-switch-btn.active {
    background-color: #1e3a8a;
    background: #1e3a8a;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 700;
}

.auto-switch-btn.active:hover {
    background-color: #2563eb;
    background: #2563eb;
    border-color: #60a5fa;
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

/* Connect Buttons (Blue for previously connected / saved, Red for new / unsaved) */
.btn-connect-blue {
    background-color: #1e40af;
    background: #1e40af;
    border: 1px solid #3b82f6;
    border-radius: 6px;
    padding: 3px 12px;
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
    transition: all 150ms ease;
}

.btn-connect-blue:hover {
    background-color: #2563eb;
    background: #2563eb;
    border-color: #60a5fa;
    color: #ffffff;
    box-shadow: 0 0 8px rgba(59, 130, 246, 0.4);
}

.btn-connect-blue:active {
    background-color: #1d4ed8;
    background: #1d4ed8;
}

.btn-connect-blue:disabled {
    background-color: #1e3a8a;
    background: #1e3a8a;
    border-color: #3b82f6;
    color: #93c5fd;
    opacity: 0.9;
}

.btn-connect-red {
    background-color: #991b1b;
    background: #991b1b;
    border: 1px solid #ef4444;
    border-radius: 6px;
    padding: 3px 12px;
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
    transition: all 150ms ease;
}

.btn-connect-red:hover {
    background-color: #dc2626;
    background: #dc2626;
    border-color: #f87171;
    color: #ffffff;
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.4);
}

.btn-connect-red:active {
    background-color: #7f1d1d;
    background: #7f1d1d;
}

.btn-connect-red:disabled {
    background-color: #7f1d1d;
    background: #7f1d1d;
    border-color: #ef4444;
    color: #fca5a5;
    opacity: 0.9;
}

.btn-edit {
    background-color: #1a202c;
    background: #1a202c;
    border: 1px solid #2d3748;
    border-radius: 6px;
    padding: 3px 8px;
    color: #a0aec0;
    font-size: 11px;
    font-weight: 600;
    transition: all 150ms ease;
}

.btn-edit:hover {
    background-color: #2d3748;
    background: #2d3748;
    border-color: #4a5568;
    color: #ffffff;
}

.btn-edit:active {
    background-color: #1a202c;
    background: #1a202c;
}

/* Wired / Ethernet Card */
.wired-card {
    background-color: #161b26;
    background: #161b26;
    border: 1px solid #293548;
    border-radius: 12px;
    padding: 10px 14px;
    margin-bottom: 8px;
    transition: all 150ms ease;
}

.wired-card:hover {
    background-color: #1c2331;
    border-color: #3b4d68;
}

.wired-icon {
    font-size: 22px;
    color: #60a5fa;
    margin-right: 10px;
}

.wired-badge {
    background-color: #1e3a8a;
    border: 1px solid #3b82f6;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 700;
    color: #bfdbfe;
    letter-spacing: 0.5px;
}

.wired-detail-box {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid #232c3d;
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
        self.connect("destroy", self.on_destroy)

        # Network state variables
        self.wifi_device = "wlo1"
        self.nm_client = None
        self.nm_wifi_dev = None
        self.is_scanning = False
        self._pending_scan_on_ready = False
        self._scan_start_last_scan = -1
        self._scan_timeout_id = None
        self._ap_refresh_id = None
        self._periodic_scan_id = None
        self._poll_stats_id = None
        self._nm_client_signals = []
        self._nm_dev_signals = []
        self._has_other_networks = False
        self._displayed_other_nets = []
        self._last_other_sig = None
        self._last_wired_sig = None
        self._destroyed = False

        self._init_nm_client()
        if not self.wifi_device:
            self.wifi_device = self.find_wifi_device()
        self.prev_rx = 0
        self.prev_tx = 0
        self.prev_time = time.time()
        self.active_ssid = ""
        self.active_security = ""
        self.active_bssid = ""
        self.wifi_enabled = True
        self.speedtest_running = False
        self.auto_switcher_enabled = read_auto_switch_enabled()
        self.connecting_ssids = set()
        self.start_time = time.time()

        self.init_ui()
        self.apply_css()
        self._update_auto_switch_ui()

        # Immediate fast synchronous initial state load (<25ms)
        self.fetch_fast_initial_data()

        # Trigger non-blocking background scan right after initial render
        GLib.idle_add(self._maybe_initial_scan)
        if self.auto_switcher_enabled:
            GLib.idle_add(lambda: (ensure_auto_switcher_daemon(), False)[1])

        # Timers for background updates
        self._poll_stats_id = GLib.timeout_add(1500, self.poll_stats)
        self._periodic_scan_id = GLib.timeout_add(6000, self._periodic_rescan)

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
        if time.time() - self.start_time < 0.5:
            return False
        if not hasattr(self, 'card'):
            return False
        alloc = self.card.get_allocation()
        if alloc.width <= 1 or alloc.height <= 1:
            return False
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

        # Active Wi-Fi Disconnect Button
        self.btn_active_disc = Gtk.Button(label="Disconnect")
        self.btn_active_disc.get_style_context().add_class("action-btn")
        self.btn_active_disc.get_style_context().add_class("danger")
        self.btn_active_disc.set_valign(Gtk.Align.CENTER)
        self.btn_active_disc.set_no_show_all(True)
        self.btn_active_disc.set_visible(False)
        self.btn_active_disc.connect("clicked", lambda w: self.disconnect_active_wifi())
        actions_box.pack_start(self.btn_active_disc, False, False, 0)

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

        # 4.2 Auto Switcher Section
        autoswitch_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        autoswitch_title = Gtk.Label(label="AUTO SWITCHER", xalign=0)
        autoswitch_title.get_style_context().add_class("section-title")
        autoswitch_header.pack_start(autoswitch_title, True, True, 0)

        self.auto_switch_btn = Gtk.Button(label="󰓦  Off")
        self.auto_switch_btn.get_style_context().add_class("auto-switch-btn")
        self.auto_switch_btn.set_valign(Gtk.Align.CENTER)
        self.auto_switch_btn.set_tooltip_text(
            "Auto-switch on disconnect, bad connection, or better saved network (reverts if worse)"
        )
        self.auto_switch_btn.connect("clicked", self.on_auto_switch_clicked)
        autoswitch_header.pack_end(self.auto_switch_btn, False, False, 0)
        main_box.pack_start(autoswitch_header, False, False, 0)

        # 4.5 Wired Connection Section
        self.wired_title = Gtk.Label(label="WIRED CONNECTION", xalign=0)
        self.wired_title.get_style_context().add_class("section-title")
        self.wired_title.set_no_show_all(True)
        self.wired_title.set_visible(False)
        main_box.pack_start(self.wired_title, False, False, 0)

        self.wired_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.wired_container.set_no_show_all(True)
        self.wired_container.set_visible(False)
        main_box.pack_start(self.wired_container, False, False, 0)

        # 5. Available Networks Section
        other_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.other_title = Gtk.Label(label="AVAILABLE NETWORKS", xalign=0)
        self.other_title.get_style_context().add_class("section-title")
        other_header.pack_start(self.other_title, True, True, 0)

        self.scan_status_lbl = Gtk.Label(label="Scanning...", xalign=1)
        self.scan_status_lbl.get_style_context().add_class("stat-label")
        self.scan_status_lbl.set_valign(Gtk.Align.CENTER)
        self.scan_status_lbl.set_no_show_all(True)
        self.scan_status_lbl.set_visible(False)

        self.rescan_btn = Gtk.Button(label="󰑐")
        self.rescan_btn.get_style_context().add_class("flat-icon-btn")
        self.rescan_btn.set_valign(Gtk.Align.CENTER)
        self.rescan_btn.set_tooltip_text("Rescan networks")
        self.rescan_btn.connect("clicked", lambda w: self.trigger_rescan())
        other_header.pack_end(self.rescan_btn, False, False, 0)
        other_header.pack_end(self.scan_status_lbl, False, False, 6)
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

    def on_destroy(self, widget):
        self._destroyed = True
        for attr in ("_scan_timeout_id", "_ap_refresh_id", "_periodic_scan_id", "_poll_stats_id"):
            sid = getattr(self, attr, None)
            if sid is not None:
                GLib.source_remove(sid)
                setattr(self, attr, None)
        self._disconnect_nm_signals()
        if Gtk.main_level() > 0:
            Gtk.main_quit()

    def _disconnect_signals(self, signal_list):
        for obj, hid in signal_list:
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        signal_list.clear()

    def _disconnect_nm_signals(self):
        self._disconnect_signals(self._nm_dev_signals)
        self._disconnect_signals(self._nm_client_signals)

    def _bind_wifi_device(self, dev):
        self._disconnect_signals(self._nm_dev_signals)

        self.nm_wifi_dev = dev
        if not dev:
            return
        self.wifi_device = dev.get_iface()
        self._nm_dev_signals.extend([
            (dev, dev.connect("access-point-added", lambda *a: self._schedule_ap_refresh(60))),
            (dev, dev.connect("access-point-removed", lambda *a: self._schedule_ap_refresh(60))),
            (dev, dev.connect("notify::active-access-point", lambda *a: self._schedule_ap_refresh(30))),
            (dev, dev.connect("notify::last-scan", self._on_nm_last_scan)),
            (dev, dev.connect("state-changed", self._on_nm_device_state_changed)),
        ])

    def _init_nm_client(self):
        self._disconnect_nm_signals()
        self.nm_client = None
        self.nm_wifi_dev = None
        if NM_AVAILABLE:
            try:
                self.nm_client = NM.Client.new(None)
                self._nm_client_signals.extend([
                    (self.nm_client, self.nm_client.connect("notify::wireless-enabled", self._on_nm_wireless_enabled)),
                    (self.nm_client, self.nm_client.connect("notify::active-connections", lambda *a: self._schedule_ap_refresh(40))),
                    (self.nm_client, self.nm_client.connect("device-added", self._on_nm_devices_changed)),
                    (self.nm_client, self.nm_client.connect("device-removed", self._on_nm_devices_changed)),
                ])
                for d in self.nm_client.get_devices():
                    if isinstance(d, NM.DeviceWifi):
                        self._bind_wifi_device(d)
                        break
            except Exception as e:
                print(f"NM Client init error: {e}")
                self._disconnect_nm_signals()
                self.nm_client = None

    def _on_nm_devices_changed(self, client, dev):
        if self._destroyed:
            return
        wifi_dev = None
        for d in client.get_devices():
            if isinstance(d, NM.DeviceWifi):
                wifi_dev = d
                break
        if wifi_dev is not self.nm_wifi_dev:
            self._bind_wifi_device(wifi_dev)
        self._schedule_ap_refresh(60)

    def _schedule_ap_refresh(self, delay_ms=60):
        if self._destroyed or self._ap_refresh_id is not None:
            return
        self._ap_refresh_id = GLib.timeout_add(delay_ms, self._run_scheduled_ap_refresh)

    def _run_scheduled_ap_refresh(self):
        self._ap_refresh_id = None
        if not self._destroyed:
            self._do_scan_parse(async_render=False)
        return False

    def _on_nm_last_scan(self, dev, pspec):
        if self._destroyed:
            return
        new_last_scan = dev.get_last_scan()
        if self.is_scanning and new_last_scan != self._scan_start_last_scan:
            self._finish_scan_state(refresh=True)
        else:
            self._schedule_ap_refresh(20)

    def _on_nm_device_state_changed(self, dev, new_state, old_state, reason):
        if self._destroyed:
            return
        if new_state >= NM.DeviceState.DISCONNECTED and self._pending_scan_on_ready and self.wifi_enabled:
            self._pending_scan_on_ready = False
            self._start_nm_scan()
        self._schedule_ap_refresh(40)

    def _on_nm_wireless_enabled(self, client, pspec):
        if self._destroyed:
            return
        was_enabled = self.wifi_enabled
        self.wifi_enabled = client.wireless_get_enabled()
        self.wifi_switch.handler_block_by_func(self.on_switch_toggled)
        self.wifi_switch.set_active(self.wifi_enabled)
        self.wifi_switch.set_state(self.wifi_enabled)
        self.wifi_switch.handler_unblock_by_func(self.on_switch_toggled)

        if self.wifi_enabled and not was_enabled:
            if self.nm_wifi_dev and self.nm_wifi_dev.get_state() >= NM.DeviceState.DISCONNECTED:
                self.trigger_rescan()
            else:
                self._pending_scan_on_ready = True
                self._set_scanning_ui(True)
                self._do_scan_parse(async_render=False)
        elif not self.wifi_enabled:
            self._pending_scan_on_ready = False
            self._finish_scan_state(refresh=True)

    def _set_scanning_ui(self, scanning):
        self.is_scanning = scanning
        self.rescan_btn.set_sensitive(not scanning)
        self.scan_status_lbl.set_visible(scanning)

    def _maybe_initial_scan(self):
        if self._destroyed or not self.wifi_enabled:
            return False
        if self.nm_wifi_dev:
            if self.nm_wifi_dev.get_state() < NM.DeviceState.DISCONNECTED:
                self._pending_scan_on_ready = True
                self._set_scanning_ui(True)
                self._do_scan_parse(async_render=False)
                return False
            if not self.is_scanning:
                self.trigger_rescan()
        else:
            self.trigger_rescan()
        return False

    def _update_auto_switch_ui(self):
        ctx = self.auto_switch_btn.get_style_context()
        if self.auto_switcher_enabled:
            self.auto_switch_btn.set_label("󰓦  Auto Switch: ON")
            ctx.add_class("active")
        else:
            self.auto_switch_btn.set_label("󰓦  Auto Switch: OFF")
            ctx.remove_class("active")

    def on_auto_switch_clicked(self, widget):
        self.auto_switcher_enabled = not self.auto_switcher_enabled
        write_auto_switch_enabled(self.auto_switcher_enabled)
        self._update_auto_switch_ui()

        if self.auto_switcher_enabled:
            send_auto_switch_command("resume")
            ensure_auto_switcher_daemon()
            # If currently disconnected in the UI right now, also trigger scan/switch immediately
            if self.wifi_enabled and self.nm_wifi_dev and self.nm_wifi_dev.get_state() == NM.DeviceState.DISCONNECTED:
                best_conn, best_ssid, _ = find_best_saved_network(self.nm_client, self.nm_wifi_dev)
                if best_conn:
                    try:
                        self.nm_client.activate_connection_async(best_conn, self.nm_wifi_dev, None, None, None, None)
                    except Exception:
                        pass
                elif not self.is_scanning:
                    self.trigger_rescan()
        else:
            send_auto_switch_command("stop")

    def _get_ap_security(self, ap):
        try:
            flags = ap.get_flags()
            wpa_flags = ap.get_wpa_flags()
            rsn_flags = ap.get_rsn_flags()
            sec = []
            if rsn_flags:
                sec.append("WPA2/WPA3")
            elif wpa_flags:
                sec.append("WPA")
            elif hasattr(NM, "80211ApFlags") and (flags & getattr(NM, "80211ApFlags").PRIVACY):
                sec.append("WEP")
            return " ".join(sec)
        except Exception:
            return ""

    # -------------------------------------------------------------
    # State & Polling (Fast, Latency-Free)
    # -------------------------------------------------------------
    def fetch_fast_initial_data(self):
        """Immediately loads cached NM Wi-Fi data & network stats in memory (<2ms)"""
        try:
            if self.nm_client:
                self.wifi_enabled = self.nm_client.wireless_get_enabled()
            else:
                state = subprocess.check_output(["nmcli", "radio", "wifi"], text=True, stderr=subprocess.DEVNULL).strip()
                self.wifi_enabled = (state == "enabled")
            self.wifi_switch.handler_block_by_func(self.on_switch_toggled)
            self.wifi_switch.set_active(self.wifi_enabled)
            self.wifi_switch.set_state(self.wifi_enabled)
            self.wifi_switch.handler_unblock_by_func(self.on_switch_toggled)
        except Exception:
            pass

        # 1. Immediate synchronous parse of in-memory network list (<1ms)
        self._do_scan_parse(async_render=False)

        # 2. Immediate interface stats
        self._update_interface_stats()

        # 3. Fast IP and Gateway check from libnm in-memory data
        ip_addr = "0.0.0.0"
        gateway = "0.0.0.0"
        if self.nm_wifi_dev:
            try:
                ip4 = self.nm_wifi_dev.get_ip4_config()
                if ip4:
                    addrs = ip4.get_addresses()
                    if addrs:
                        ip_addr = addrs[0].get_address()
                        self.v_ip.set_text(ip_addr)
                    gw = ip4.get_gateway()
                    if gw:
                        gateway = gw
                        self.v_gw.set_text(gateway)
            except Exception:
                pass
        else:
            try:
                out_ip = subprocess.check_output(
                    ["ip", "-4", "addr", "show", self.wifi_device], text=True, stderr=subprocess.DEVNULL
                )
                m_ip = re.search(r"inet\s+([0-9.]+)", out_ip)
                if m_ip:
                    ip_addr = m_ip.group(1)
                    self.v_ip.set_text(ip_addr)

                out_gw = subprocess.check_output(
                    ["ip", "-4", "route", "show", "default"], text=True, stderr=subprocess.DEVNULL
                )
                m_gw = re.search(r"via\s+([0-9.]+)", out_gw)
                if m_gw:
                    gateway = m_gw.group(1)
                    self.v_gw.set_text(gateway)
            except Exception:
                pass

        # 4. Asynchronously check ping in background so ping never delays UI
        threading.Thread(target=self._async_ping, args=(ip_addr, gateway), daemon=True).start()

    def poll_wifi_state(self):
        def worker():
            try:
                was_enabled = self.wifi_enabled
                if self.nm_client:
                    self.wifi_enabled = self.nm_client.wireless_get_enabled()
                else:
                    state = subprocess.check_output(["nmcli", "radio", "wifi"], text=True, stderr=subprocess.DEVNULL).strip()
                    self.wifi_enabled = (state == "enabled")
                def update_switch():
                    self.wifi_switch.handler_block_by_func(self.on_switch_toggled)
                    self.wifi_switch.set_active(self.wifi_enabled)
                    self.wifi_switch.set_state(self.wifi_enabled)
                    self.wifi_switch.handler_unblock_by_func(self.on_switch_toggled)
                GLib.idle_add(update_switch)

                if not was_enabled and self.wifi_enabled:
                    GLib.idle_add(self.scan_networks, True)
            except Exception:
                pass
        if not self.nm_client:
            threading.Thread(target=worker, daemon=True).start()

    def _toggle_wifi_via_nmcli(self, state):
        def worker():
            subprocess.run(["nmcli", "radio", "wifi", "on" if state else "off"], check=False)
            if state:
                time.sleep(0.5)
                GLib.idle_add(self.trigger_rescan)
            else:
                GLib.idle_add(self.scan_networks)
        threading.Thread(target=worker, daemon=True).start()

    def on_switch_toggled(self, switch, state):
        self.wifi_enabled = state
        switch.set_state(state)
        if not state:
            self._pending_scan_on_ready = False
            self._finish_scan_state(refresh=False)
            self.active_ssid = ""
            self.ssid_title.set_text("Wi-Fi Disabled")
            self.ssid_subtitle.set_text("NO ACTIVE CONNECTION")
            self.header_icon.set_text("󰤮")
            self._render_networks(None, [])
        else:
            self._set_scanning_ui(True)
            self.ssid_title.set_text("Enabling Wi-Fi...")
            self.ssid_subtitle.set_text("SCANNING FOR NETWORKS")
            self._render_networks(None, [])

        if self.nm_client:
            if state:
                self._pending_scan_on_ready = True
                self._arm_scan_timeout(10000)
            try:
                self.nm_client.dbus_set_property(
                    NM.DBUS_PATH,
                    NM.DBUS_INTERFACE,
                    "WirelessEnabled",
                    GLib.Variant("b", state),
                    5000,
                    None,
                    self._on_wireless_toggle_done,
                    state,
                )
            except Exception:
                self._toggle_wifi_via_nmcli(state)
        else:
            self._toggle_wifi_via_nmcli(state)

        return True

    def _on_wireless_toggle_done(self, client, res, state):
        if self._destroyed:
            return
        try:
            client.dbus_set_property_finish(res)
            if state and self.nm_wifi_dev and self.nm_wifi_dev.get_state() >= NM.DeviceState.DISCONNECTED:
                self._pending_scan_on_ready = False
                self._start_nm_scan()
        except Exception:
            self._toggle_wifi_via_nmcli(state)

    def _update_interface_stats(self):
        try:
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if self.wifi_device in line:
                        parts = line.split(":")[1].split()
                        rx_bytes = int(parts[0])
                        tx_bytes = int(parts[8])

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

                        self.v_down.set_text(self.format_bytes(rx_bytes))
                        self.v_up.set_text(self.format_bytes(tx_bytes))
                        break
        except Exception:
            pass

    def poll_stats(self):
        if self._destroyed:
            return False
        self._update_interface_stats()
        if self.nm_wifi_dev:
            ip_addr = "Disconnected"
            gateway = "---"
            try:
                ip4 = self.nm_wifi_dev.get_ip4_config()
                if ip4:
                    addrs = ip4.get_addresses()
                    if addrs:
                        ip_addr = addrs[0].get_address()
                    gw = ip4.get_gateway()
                    if gw:
                        gateway = gw
            except Exception:
                pass
            self.v_ip.set_text(ip_addr)
            self.v_gw.set_text(gateway)
            threading.Thread(target=self._async_ping, args=(ip_addr, gateway), daemon=True).start()
        else:
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

        GLib.idle_add(self._set_ip_gw_labels, ip_addr, gateway)
        self._async_ping(ip_addr, gateway)

    def _set_ip_gw_labels(self, ip_addr, gateway):
        if not self._destroyed:
            self.v_ip.set_text(ip_addr)
            self.v_gw.set_text(gateway)
        return False

    def _set_ping_labels(self, ping_str, loss_str):
        if not self._destroyed:
            self.v_ping.set_text(ping_str)
            self.v_loss.set_text(loss_str)
        return False

    def _async_ping(self, ip_addr="", gateway="---"):
        target = gateway if (gateway and gateway not in ("---", "0.0.0.0")) else "1.1.1.1"
        ping_str = "---"
        loss_str = "0%"
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
            loss_str = "100%" if ip_addr not in ("", "Disconnected", "0.0.0.0") else "---"

        GLib.idle_add(self._set_ping_labels, ping_str, loss_str)

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

    def _periodic_rescan(self):
        if self._destroyed:
            return False
        self.scan_networks(rescan=True)
        return True

    def scan_networks(self, rescan=False):
        if self._destroyed:
            return False
        if self.nm_client and self.nm_wifi_dev:
            if rescan and self.wifi_enabled and not self.is_scanning:
                last_scan = self.nm_wifi_dev.get_last_scan()
                now_ms = NM.utils_get_timestamp_msec()
                if last_scan <= 0 or (now_ms - last_scan) >= 5000:
                    self.trigger_rescan()
                    return False
            self._do_scan_parse(async_render=False)
            return False

        if not self.wifi_enabled:
            threading.Thread(target=self._do_scan_parse, daemon=True).start()
            return False

        def worker():
            if rescan:
                subprocess.run(["nmcli", "device", "wifi", "rescan"], stderr=subprocess.DEVNULL)
            self._do_scan_parse()

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _arm_scan_timeout(self, timeout_ms=8000):
        if self._scan_timeout_id is not None:
            GLib.source_remove(self._scan_timeout_id)
        self._scan_timeout_id = GLib.timeout_add(timeout_ms, self._on_scan_timeout)

    def trigger_rescan(self):
        if self._destroyed or not self.wifi_enabled or self.is_scanning:
            return
        self._set_scanning_ui(True)
        if not self._has_other_networks:
            if self.nm_client and self.nm_wifi_dev:
                self._do_scan_parse(async_render=False)
            else:
                self._render_networks(None, [])

        if self.nm_wifi_dev:
            if self.nm_wifi_dev.get_state() < NM.DeviceState.DISCONNECTED:
                self._pending_scan_on_ready = True
                self._arm_scan_timeout(8000)
                return
            self._start_nm_scan()
            return

        def worker():
            subprocess.run(["nmcli", "device", "wifi", "rescan"], stderr=subprocess.DEVNULL)
            self._do_scan_parse(async_render=True)
            GLib.idle_add(self._finish_scan_state, False)
        threading.Thread(target=worker, daemon=True).start()

    def _start_nm_scan(self):
        if self._destroyed or not self.nm_wifi_dev:
            return
        self._scan_start_last_scan = self.nm_wifi_dev.get_last_scan()
        self._arm_scan_timeout(8000)
        try:
            if hasattr(self.nm_wifi_dev, "request_scan_options_async"):
                self.nm_wifi_dev.request_scan_options_async(
                    GLib.Variant("a{sv}", {}), None, self._on_request_scan_done, None
                )
            else:
                self.nm_wifi_dev.request_scan_async(None, self._on_request_scan_done, None)
        except Exception:
            self._finish_scan_state(refresh=True)

    def _on_request_scan_done(self, dev, res, user_data):
        if self._destroyed:
            return
        try:
            dev.request_scan_finish(res)
        except Exception as e:
            err_msg = str(e).lower()
            if "already" in err_msg or "in progress" in err_msg:
                return
            self._finish_scan_state(refresh=True)

    def _on_scan_timeout(self):
        self._scan_timeout_id = None
        if not self._destroyed:
            self._finish_scan_state(refresh=True)
        return False

    def _finish_scan_state(self, refresh=True):
        if self._scan_timeout_id is not None:
            GLib.source_remove(self._scan_timeout_id)
            self._scan_timeout_id = None
        if self._ap_refresh_id is not None:
            GLib.source_remove(self._ap_refresh_id)
            self._ap_refresh_id = None
        if self._destroyed:
            return False
        self._set_scanning_ui(False)
        if refresh:
            if self.nm_client and self.nm_wifi_dev:
                self._do_scan_parse(async_render=False)
            else:
                self.scan_networks()
        return False

    def _detect_wired_connections(self):
        wired_list = []
        try:
            if self.nm_client:
                for d in self.nm_client.get_devices():
                    if isinstance(d, NM.DeviceEthernet) and d.get_state() == NM.DeviceState.ACTIVATED:
                        conn = d.get_active_connection()
                        conn_name = conn.get_id() if conn else d.get_iface()
                        ip_str = "---"
                        gw_str = "---"
                        dns_str = "---"
                        ip4 = d.get_ip4_config()
                        if ip4:
                            addrs = ip4.get_addresses()
                            if addrs:
                                ip_str = addrs[0].get_address()
                            gw_str = ip4.get_gateway() or "---"
                            dns_arr = ip4.get_nameservers()
                            if dns_arr:
                                dns_str = ", ".join(dns_arr)
                        mac_str = d.get_permanent_hw_address() or d.get_hw_address() or "---"
                        speed = f"{d.get_speed()} Mb/s" if d.get_speed() > 0 else ""
                        wired_list.append({
                            "device": d.get_iface(),
                            "connection": conn_name,
                            "ip": ip_str,
                            "gateway": gw_str,
                            "dns": dns_str,
                            "mac": mac_str,
                            "speed": speed
                        })
            else:
                dev_out = subprocess.check_output(
                    ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip().splitlines()
                for line in dev_out:
                    parts = line.split(":")
                    if len(parts) >= 4 and parts[1] == "ethernet" and parts[2] == "connected":
                        dev_name = parts[0]
                        conn_name = parts[3]
                        ip_str = "---"
                        gw_str = "---"
                        dns_str = "---"
                        mac_str = "---"
                        speed = ""
                        try:
                            dev_info = subprocess.check_output(
                                ["nmcli", "-t", "device", "show", dev_name],
                                text=True, stderr=subprocess.DEVNULL
                            ).splitlines()
                            for l in dev_info:
                                parts_info = l.split(":", 1)
                                if len(parts_info) == 2:
                                    k, v = parts_info[0].strip(), parts_info[1].strip()
                                    if k.startswith("IP4.ADDRESS") and ip_str == "---":
                                        ip_str = v.split("/")[0]
                                    elif k == "IP4.GATEWAY" and v:
                                        gw_str = v
                                    elif k.startswith("IP4.DNS") and dns_str == "---" and v:
                                        dns_str = v
                                    elif k == "GENERAL.HWADDR" and v:
                                        mac_str = v
                                    elif k == "WIRED-PROPERTIES.SPEED" and v and v != "--":
                                        speed = f"{v} Mb/s"
                        except Exception:
                            pass
                        wired_list.append({
                            "device": dev_name,
                            "connection": conn_name,
                            "ip": ip_str,
                            "gateway": gw_str,
                            "dns": dns_str,
                            "mac": mac_str,
                            "speed": speed
                        })
        except Exception:
            pass
        return wired_list

    def _render_wired_connections(self, wired_list):
        wired_sig = tuple(
            (w["device"], w["connection"], w["ip"], w["gateway"], w["dns"], w["mac"], w["speed"])
            for w in wired_list
        )
        if wired_sig == self._last_wired_sig:
            return
        self._last_wired_sig = wired_sig

        for child in self.wired_container.get_children():
            self.wired_container.remove(child)
            child.destroy()

        if not wired_list:
            self.wired_title.set_visible(False)
            self.wired_container.set_visible(False)
            return

        for w in wired_list:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("wired-card")

            # Top Row: Icon + Title/Sub + Badge + Disconnect Button
            top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            icon_lbl = Gtk.Label(label="󰈀")
            icon_lbl.get_style_context().add_class("wired-icon")
            icon_lbl.set_valign(Gtk.Align.CENTER)
            top_row.pack_start(icon_lbl, False, False, 0)

            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title_box.set_valign(Gtk.Align.CENTER)
            conn_lbl = Gtk.Label(label=w["connection"], xalign=0)
            conn_lbl.get_style_context().add_class("net-ssid")
            sub_text = f"{w['device']} • Connected"
            if w.get("speed"):
                sub_text += f" • {w['speed']}"
            sub_lbl = Gtk.Label(label=sub_text, xalign=0)
            sub_lbl.get_style_context().add_class("net-status")
            title_box.pack_start(conn_lbl, False, False, 0)
            title_box.pack_start(sub_lbl, False, False, 0)
            top_row.pack_start(title_box, True, True, 0)

            badge = Gtk.Label(label="ETHERNET")
            badge.get_style_context().add_class("wired-badge")
            badge.set_valign(Gtk.Align.CENTER)
            top_row.pack_end(badge, False, False, 4)

            btn_disc = Gtk.Button(label="Disconnect")
            btn_disc.get_style_context().add_class("action-btn")
            btn_disc.get_style_context().add_class("danger")
            btn_disc.set_valign(Gtk.Align.CENTER)
            btn_disc.connect("clicked", lambda btn, c=w["connection"], d=w["device"]: self.disconnect_wired(c, d))
            top_row.pack_end(btn_disc, False, False, 0)

            card.pack_start(top_row, False, False, 0)

            # Details Grid: IP, Gateway, DNS, MAC
            det_grid = Gtk.Grid()
            det_grid.get_style_context().add_class("wired-detail-box")
            det_grid.set_column_spacing(16)
            det_grid.set_row_spacing(4)
            det_grid.set_hexpand(True)

            # Row 1: IP & Gateway
            lbl_ip_t = Gtk.Label(label="IP Address:", xalign=0)
            lbl_ip_t.get_style_context().add_class("stat-label")
            lbl_ip_v = Gtk.Label(label=w["ip"], xalign=0)
            lbl_ip_v.get_style_context().add_class("stat-value")

            lbl_gw_t = Gtk.Label(label="Gateway:", xalign=0)
            lbl_gw_t.get_style_context().add_class("stat-label")
            lbl_gw_v = Gtk.Label(label=w["gateway"], xalign=0)
            lbl_gw_v.get_style_context().add_class("stat-value")

            det_grid.attach(lbl_ip_t, 0, 0, 1, 1)
            det_grid.attach(lbl_ip_v, 1, 0, 1, 1)
            det_grid.attach(lbl_gw_t, 2, 0, 1, 1)
            det_grid.attach(lbl_gw_v, 3, 0, 1, 1)

            # Row 2: DNS & MAC (if available)
            if w.get("dns") and w["dns"] != "---":
                lbl_dns_t = Gtk.Label(label="DNS Server:", xalign=0)
                lbl_dns_t.get_style_context().add_class("stat-label")
                lbl_dns_v = Gtk.Label(label=w["dns"], xalign=0)
                lbl_dns_v.get_style_context().add_class("stat-value")
                det_grid.attach(lbl_dns_t, 0, 1, 1, 1)
                det_grid.attach(lbl_dns_v, 1, 1, 1, 1)

            if w.get("mac") and w["mac"] != "---":
                lbl_mac_t = Gtk.Label(label="MAC:", xalign=0)
                lbl_mac_t.get_style_context().add_class("stat-label")
                lbl_mac_v = Gtk.Label(label=w["mac"], xalign=0)
                lbl_mac_v.get_style_context().add_class("stat-value")
                det_grid.attach(lbl_mac_t, 2, 1, 1, 1)
                det_grid.attach(lbl_mac_v, 3, 1, 1, 1)

            card.pack_start(det_grid, False, False, 0)
            self.wired_container.pack_start(card, False, False, 0)

        self.wired_title.set_visible(True)
        self.wired_container.set_visible(True)
        for child in self.wired_container.get_children():
            child.show_all()

    def disconnect_wired(self, conn_name, device):
        def worker():
            try:
                subprocess.run(["nmcli", "device", "disconnect", device], check=False)
                subprocess.run(["nmcli", "connection", "down", conn_name], check=False)
                subprocess.run([
                    "notify-send", "-a", "Network", "-i", "network-wired-disconnected",
                    "Wired Disconnected", f"Disconnected '{conn_name}'"
                ], check=False)
            except Exception as e:
                print(f"Disconnect error: {e}")
            GLib.idle_add(self.scan_networks)
        threading.Thread(target=worker, daemon=True).start()

    def disconnect_active_wifi(self):
        if not self.active_ssid:
            return
        ssid = self.active_ssid
        if self.auto_switcher_enabled:
            send_auto_switch_command(f"pause:{ssid}")
        def worker():
            try:
                subprocess.run(["nmcli", "device", "disconnect", self.wifi_device], check=False)
                subprocess.run([
                    "notify-send", "-a", "Network", "-i", "network-wireless-disconnected",
                    "Wi-Fi Disconnected", f"Disconnected from '{ssid}'"
                ], check=False)
            except Exception as e:
                print(f"Disconnect Wi-Fi error: {e}")
            GLib.idle_add(self.scan_networks)
        threading.Thread(target=worker, daemon=True).start()

    def _do_scan_parse(self, async_render=True):
        try:
            active_net = None
            raw_other_nets = []
            saved_ssids = set()

            if not self.wifi_enabled:
                other_nets = []
                wired_list = self._detect_wired_connections()
                if async_render:
                    GLib.idle_add(self._render_networks, None, other_nets, wired_list)
                else:
                    self._render_networks(None, other_nets, wired_list)
                return

            if self.nm_client and self.nm_wifi_dev:
                # Fast in-memory libnm extraction (<1ms)
                for conn in self.nm_client.get_connections():
                    s_wifi = conn.get_setting_wireless()
                    if s_wifi:
                        sb = s_wifi.get_ssid()
                        data = sb.get_data() if sb else None
                        if data:
                            s_name = NM.utils_ssid_to_utf8(data)
                            if s_name:
                                saved_ssids.add(s_name)
                        elif conn.get_id():
                            saved_ssids.add(conn.get_id())

                active_ap = self.nm_wifi_dev.get_active_access_point()
                active_ssid = ""
                if active_ap:
                    sb = active_ap.get_ssid()
                    data = sb.get_data() if sb else None
                    active_ssid = NM.utils_ssid_to_utf8(data) if data else ""
                    if active_ssid and active_ssid != "--":
                        active_net = {
                            "ssid": active_ssid,
                            "signal": active_ap.get_strength(),
                            "security": self._get_ap_security(active_ap),
                            "bssid": active_ap.get_bssid() or ""
                        }

                for ap in self.nm_wifi_dev.get_access_points():
                    sb = ap.get_ssid()
                    data = sb.get_data() if sb else None
                    ssid = NM.utils_ssid_to_utf8(data) if data else ""
                    if not ssid or ssid == "--" or (active_ssid and ssid == active_ssid):
                        continue
                    raw_other_nets.append({
                        "ssid": ssid,
                        "signal": ap.get_strength(),
                        "security": self._get_ap_security(ap),
                        "saved": (ssid in saved_ssids),
                        "bssid": ap.get_bssid() or ""
                    })
            else:
                out = subprocess.check_output(
                    ["nmcli", "-m", "multiline", "-f", "ACTIVE,SSID,SIGNAL,SECURITY,BSSID", "device", "wifi", "list", "--rescan", "no"],
                    text=True, stderr=subprocess.DEVNULL
                )
                saved_out = subprocess.check_output(
                    ["nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show"],
                    text=True, stderr=subprocess.DEVNULL
                )
                for l in saved_out.strip().splitlines():
                    p = l.split(":")
                    if len(p) >= 3 and "wireless" in p[2]:
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
                    else:
                        raw_other_nets.append({
                            "ssid": ssid, "signal": signal,
                            "security": security, "saved": (ssid in saved_ssids)
                        })

            # Exclude active connected SSID and deduplicate available networks
            other_nets = []
            seen = set()
            if active_net:
                seen.add(active_net["ssid"])

            for net_item in sorted(raw_other_nets, key=lambda x: x["signal"], reverse=True):
                if net_item["ssid"] not in seen:
                    seen.add(net_item["ssid"])
                    other_nets.append(net_item)

            if self.is_scanning and self.wifi_enabled and self._displayed_other_nets:
                for prev_item in self._displayed_other_nets:
                    if prev_item["ssid"] not in seen:
                        seen.add(prev_item["ssid"])
                        merged_item = dict(prev_item)
                        merged_item["saved"] = (prev_item["ssid"] in saved_ssids)
                        other_nets.append(merged_item)
                other_nets.sort(key=lambda x: x["signal"], reverse=True)

            wired_list = self._detect_wired_connections()

            if async_render:
                GLib.idle_add(self._render_networks, active_net, other_nets, wired_list)
            else:
                self._render_networks(active_net, other_nets, wired_list)
        except Exception as e:
            print(f"Scan error: {e}")

    def _render_networks(self, active_net, other_nets, wired_list=None):
        if wired_list is None:
            wired_list = self._detect_wired_connections()

        if active_net:
            other_nets = [n for n in other_nets if n["ssid"] != active_net["ssid"]]

        self.active_wired_devices = [w["device"] for w in wired_list]
        self._render_wired_connections(wired_list)

        # Update Header
        if active_net:
            self.active_ssid = active_net["ssid"]
            self.active_security = active_net["security"]
            self.active_bssid = active_net["bssid"]
            self.ssid_title.set_text(self.active_ssid)
            self.ssid_subtitle.set_text("COUNTING COLLISIONS")
            self.header_icon.set_text("")
        elif wired_list:
            self.active_ssid = ""
            self.ssid_title.set_text(wired_list[0]["connection"])
            self.ssid_subtitle.set_text(f"ETHERNET • {wired_list[0]['device'].upper()}")
            self.header_icon.set_text("󰈀")
        else:
            self.active_ssid = ""
            self.ssid_title.set_text("Wi-Fi Disconnected" if self.wifi_enabled else "Wi-Fi Disabled")
            self.ssid_subtitle.set_text("NO ACTIVE CONNECTION")
            self.header_icon.set_text("󰤮")

        # Update DNS Active Provider
        self.update_active_dns()

        # Update Active Wi-Fi Disconnect Button Visibility
        self.btn_active_disc.set_visible(bool(active_net))

        self._has_other_networks = bool(other_nets)
        self._displayed_other_nets = list(other_nets) if self.wifi_enabled else []
        device_enabling = bool(
            self.wifi_enabled
            and not other_nets
            and self.nm_wifi_dev
            and self.nm_wifi_dev.get_state() < NM.DeviceState.DISCONNECTED
        )
        other_sig = (
            self.wifi_enabled,
            bool(self.is_scanning and not other_nets),
            device_enabling,
            tuple(
                (n["ssid"], n["signal"], n["security"], n.get("saved", False), n["ssid"] in self.connecting_ssids)
                for n in other_nets
            ),
        )
        if other_sig == self._last_other_sig:
            return
        self._last_other_sig = other_sig

        # Render Other Networks List
        for child in self.other_container.get_children():
            self.other_container.remove(child)
            child.destroy()

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
            empty_text = "Enabling Wi-Fi..." if device_enabling else (
                "Scanning for networks..." if self.is_scanning else "No other networks in range"
            )
            lbl = Gtk.Label(label=empty_text)
            lbl.get_style_context().add_class("stat-label")
            empty_box.pack_start(lbl, False, False, 0)
            self.other_container.pack_start(empty_box, False, False, 0)
        else:
            for net in other_nets:
                row = Gtk.EventBox()
                row.get_style_context().add_class("network-row")
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row_box.set_margin_start(10)
                row_box.set_margin_end(10)
                row_box.set_margin_top(6)
                row_box.set_margin_bottom(6)
                row.add(row_box)

                # Signal icon
                sig = net["signal"]
                icon_str = "󰤨" if sig >= 75 else ("󰤥" if sig >= 50 else ("󰤢" if sig >= 25 else "󰤟"))
                icon_lbl = Gtk.Label(label=icon_str)
                icon_lbl.get_style_context().add_class("net-icon")
                icon_lbl.set_size_request(22, 22)
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
                    row_box.pack_start(lock_lbl, False, False, 4)

                # Connect Button: Blue if previously connected (saved), Red if not previously connected (new)
                is_saved = net.get("saved", False)
                is_connecting = net["ssid"] in self.connecting_ssids
                btn_connect = Gtk.Button(label="Connecting..." if is_connecting else "Connect")
                if is_saved:
                    btn_connect.get_style_context().add_class("btn-connect-blue")
                    btn_connect.set_tooltip_text("Previously connected network")
                else:
                    btn_connect.get_style_context().add_class("btn-connect-red")
                    btn_connect.set_tooltip_text("New network (not previously connected)")

                if is_connecting:
                    btn_connect.set_sensitive(False)

                btn_connect.set_valign(Gtk.Align.CENTER)
                btn_connect.connect("clicked", lambda w, n=net, b=btn_connect: self.trigger_network_connect(n, b))
                row_box.pack_end(btn_connect, False, False, 0)

                # Edit Option for previously connected / saved networks
                if is_saved:
                    btn_edit = Gtk.Button(label="󰏫")
                    btn_edit.get_style_context().add_class("btn-edit")
                    btn_edit.set_tooltip_text("Edit network settings & password")
                    btn_edit.set_valign(Gtk.Align.CENTER)
                    btn_edit.connect("clicked", lambda w, s=net["ssid"]: self.show_edit_network_dialog(s))
                    row_box.pack_end(btn_edit, False, False, 4)

                row.connect("button-press-event", lambda w, e, n=net, b=btn_connect: self.trigger_network_connect(n, b))
                self.other_container.pack_start(row, False, False, 0)

        self.scroll_win.show_all()
        self.other_container.show_all()

    # -------------------------------------------------------------
    # DNS Provider Management
    # -------------------------------------------------------------
    def get_active_connection_name(self):
        if self.nm_wifi_dev:
            try:
                ac = self.nm_wifi_dev.get_active_connection()
                if ac:
                    return ac.get_id()
                return None
            except Exception:
                pass
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

    def _classify_dns_servers(self, dns_str, default="Custom"):
        if "1.1.1.1" in dns_str or "1.0.0.1" in dns_str:
            return "Cloudflare"
        if "8.8.8.8" in dns_str or "8.8.4.4" in dns_str:
            return "Google"
        return default

    def _detect_dns_provider_from_resolv(self):
        resolv_content = ""
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf", "r") as f:
                resolv_content = f.read()
        return self._classify_dns_servers(resolv_content, default=None)

    def update_active_dns(self):
        if self.nm_wifi_dev:
            ac = self.nm_wifi_dev.get_active_connection()
            if not ac:
                self._set_dns_button_active(None)
                return
            provider = "DHCP"
            try:
                resolv_provider = self._detect_dns_provider_from_resolv()
                if resolv_provider:
                    provider = resolv_provider
                else:
                    rc = ac.get_connection()
                    s_ip4 = rc.get_setting_ip4_config() if rc else None
                    if s_ip4 and s_ip4.get_ignore_auto_dns():
                        dns_list = [s_ip4.get_dns(i) for i in range(s_ip4.get_num_dns())]
                        if dns_list:
                            provider = self._classify_dns_servers(" ".join(dns_list))
            except Exception:
                pass
            self._set_dns_button_active(provider)
            return

        conn_name = self.get_active_connection_name()
        if not conn_name:
            self._set_dns_button_active(None)
            return

        def dns_worker():
            provider = "DHCP"
            try:
                # 1. Check /etc/resolv.conf for active resolver IPs
                resolv_provider = self._detect_dns_provider_from_resolv()
                if resolv_provider:
                    provider = resolv_provider
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
                        provider = self._classify_dns_servers(dns_servers)
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
        tested_ssid = self.active_ssid

        def worker():
            down_speed = "---"
            try:
                # Fast chunk download test from Cloudflare CDN
                p = subprocess.run([
                    "curl", "-s", "-w", "%{speed_download}", "-o", "/dev/null",
                    "https://speed.cloudflare.com/__down?bytes=10000000"
                ], capture_output=True, text=True, timeout=10)
                if p.returncode == 0 and p.stdout.strip():
                    speed_bps = float(p.stdout.strip())
                    down_mbps = (speed_bps * 8) / (1000 * 1000)
                    down_speed = f"{down_mbps:.1f} Mbps"
                    if tested_ssid and down_mbps > 0:
                        record_ssid_quality(tested_ssid, down_mbps=round(down_mbps, 2), internet_ok=True)
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
        btn_edit = Gtk.Button(label="󰏫 Edit")
        btn_edit.get_style_context().add_class("action-btn")
        btn_forget = Gtk.Button(label="Forget")
        btn_forget.get_style_context().add_class("action-btn")
        btn_forget.get_style_context().add_class("danger")
        btn_close = Gtk.Button(label="Back")
        btn_close.get_style_context().add_class("action-btn")

        def do_disconnect(w):
            if self.auto_switcher_enabled:
                send_auto_switch_command(f"pause:{ssid}")
            subprocess.run(["nmcli", "connection", "down", ssid], check=False)
            self.clear_overlay()
            self.scan_networks()

        def do_forget(w):
            if self.auto_switcher_enabled:
                send_auto_switch_command(f"pause:{ssid}")
            subprocess.run(["nmcli", "connection", "delete", ssid], check=False)
            self.clear_overlay()
            self.scan_networks()

        btn_disc.connect("clicked", do_disconnect)
        btn_edit.connect("clicked", lambda w: self.show_edit_network_dialog(ssid))
        btn_forget.connect("clicked", do_forget)
        btn_close.connect("clicked", lambda w: self.clear_overlay())

        btn_box.pack_start(btn_disc, True, True, 0)
        btn_box.pack_start(btn_edit, True, True, 0)
        btn_box.pack_start(btn_forget, True, True, 0)
        btn_box.pack_start(btn_close, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()

    def show_edit_network_dialog(self, ssid):
        self.clear_overlay()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class("card-overlay")

        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_lbl = Gtk.Label(label=f"Edit Network: {ssid}", xalign=0)
        title_lbl.get_style_context().add_class("ssid-title")
        title_box.pack_start(title_lbl, True, True, 0)
        card.pack_start(title_box, False, False, 0)

        # Password Input Field with Toggle Visibility
        lbl_pwd = Gtk.Label(label="Password / Security Key:", xalign=0)
        lbl_pwd.get_style_context().add_class("stat-label")
        card.pack_start(lbl_pwd, False, False, 0)

        pwd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        entry_pwd = Gtk.Entry()
        entry_pwd.set_text("")
        entry_pwd.set_visibility(False)
        pwd_box.pack_start(entry_pwd, True, True, 0)

        btn_toggle_eye = Gtk.Button(label="")
        btn_toggle_eye.get_style_context().add_class("btn-edit")
        btn_toggle_eye.set_tooltip_text("Show/Hide password")

        def toggle_pwd_vis(w):
            vis = entry_pwd.get_visibility()
            entry_pwd.set_visibility(not vis)
            btn_toggle_eye.set_label("" if not vis else "")

        btn_toggle_eye.connect("clicked", toggle_pwd_vis)
        pwd_box.pack_end(btn_toggle_eye, False, False, 0)
        card.pack_start(pwd_box, False, False, 0)

        # Autoconnect Switch
        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auto_box.set_margin_top(4)
        auto_box.set_margin_bottom(4)
        lbl_auto = Gtk.Label(label="Connect automatically", xalign=0)
        lbl_auto.get_style_context().add_class("stat-label")
        auto_box.pack_start(lbl_auto, True, True, 0)

        sw_auto = Gtk.Switch()
        sw_auto.set_active(True)
        auto_box.pack_end(sw_auto, False, False, 0)
        card.pack_start(auto_box, False, False, 0)

        # Asynchronously fetch current password & autoconnect in background thread
        conn_target = ssid
        initial_autoconnect = "yes"
        if self.nm_client:
            for c in self.nm_client.get_connections():
                s_w = c.get_setting_wireless()
                if s_w:
                    sb = s_w.get_ssid()
                    data = sb.get_data() if sb else None
                    c_ssid = NM.utils_ssid_to_utf8(data) if data else ""
                    if c_ssid == ssid or c.get_id() == ssid:
                        conn_target = c.get_uuid()
                        s_conn = c.get_setting_connection()
                        if s_conn:
                            initial_autoconnect = "yes" if s_conn.get_autoconnect() else "no"
                        break

        def load_secrets_worker(target_id, autoconnect_default):
            curr_pwd = ""
            autoconnect = autoconnect_default
            try:
                out = subprocess.check_output([
                    "nmcli", "--show-secrets", "-g",
                    "802-11-wireless-security.psk,802-11-wireless-security.wep-key0,connection.autoconnect",
                    "connection", "show", target_id
                ], text=True, stderr=subprocess.DEVNULL).strip().splitlines()
                if len(out) >= 1 and out[0]:
                    curr_pwd = out[0]
                if len(out) >= 2 and out[1]:
                    autoconnect = out[1].lower()
                elif len(out) >= 3 and out[2]:
                    autoconnect = out[2].lower()
            except Exception:
                pass

            def apply_loaded():
                if curr_pwd:
                    entry_pwd.set_text(curr_pwd)
                sw_auto.set_active(autoconnect in ("yes", "true", "1"))
                return False
            GLib.idle_add(apply_loaded)

        threading.Thread(
            target=load_secrets_worker,
            args=(conn_target, initial_autoconnect),
            daemon=True,
        ).start()

        # Buttons Box (Save, Forget, Cancel)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(4)

        btn_save = Gtk.Button(label="Save")
        btn_save.get_style_context().add_class("btn-connect-blue")
        btn_forget = Gtk.Button(label="Forget")
        btn_forget.get_style_context().add_class("action-btn")
        btn_forget.get_style_context().add_class("danger")
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.get_style_context().add_class("action-btn")

        def do_save(w):
            new_pwd = entry_pwd.get_text()
            auto_val = "yes" if sw_auto.get_active() else "no"
            self.clear_overlay()

            def worker():
                try:
                    if new_pwd:
                        subprocess.run([
                            "nmcli", "connection", "modify", ssid,
                            "802-11-wireless-security.psk", new_pwd
                        ], check=False)
                    subprocess.run([
                        "nmcli", "connection", "modify", ssid,
                        "connection.autoconnect", auto_val
                    ], check=False)
                    subprocess.run([
                        "notify-send", "-a", "Wi-Fi", "-i", "network-wireless",
                        "Network Updated", f"Saved settings for '{ssid}'"
                    ], check=False)
                except Exception as e:
                    print(f"Error saving network: {e}")
                GLib.idle_add(self.scan_networks)

            threading.Thread(target=worker, daemon=True).start()

        def do_forget(w):
            self.clear_overlay()
            if self.auto_switcher_enabled:
                send_auto_switch_command(f"pause:{ssid}")
            def worker():
                subprocess.run(["nmcli", "connection", "delete", ssid], check=False)
                subprocess.run([
                    "notify-send", "-a", "Wi-Fi", "-i", "network-wireless",
                    "Network Removed", f"Forgot '{ssid}'"
                ], check=False)
                GLib.idle_add(self.scan_networks)
            threading.Thread(target=worker, daemon=True).start()

        btn_save.connect("clicked", do_save)
        btn_forget.connect("clicked", do_forget)
        btn_cancel.connect("clicked", lambda w: self.clear_overlay())
        entry_pwd.connect("activate", do_save)

        btn_box.pack_start(btn_save, True, True, 0)
        btn_box.pack_start(btn_forget, True, True, 0)
        btn_box.pack_start(btn_cancel, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()
        entry_pwd.grab_focus()

    def trigger_network_connect(self, net, btn=None):
        ssid = net["ssid"]
        is_saved = net.get("saved", False)
        is_secured = bool(net["security"] and net["security"] != "--")
        if self.auto_switcher_enabled:
            send_auto_switch_command(f"manual:{ssid}")

        if is_saved or not is_secured:
            self.connecting_ssids.add(ssid)
            if btn:
                btn.set_label("Connecting...")
                btn.set_sensitive(False)

            def connect_worker():
                try:
                    if is_saved:
                        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
                    else:
                        subprocess.run(["nmcli", "device", "wifi", "connect", ssid], check=False)
                finally:
                    self.connecting_ssids.discard(ssid)
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
        btn_modal_connect = Gtk.Button(label="Connect")
        btn_modal_connect.get_style_context().add_class("action-btn")
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.get_style_context().add_class("action-btn")

        def do_connect(w):
            pwd = entry.get_text()
            self.clear_overlay()
            self.connecting_ssids.add(ssid)
            if btn:
                btn.set_label("Connecting...")
                btn.set_sensitive(False)

            def worker():
                try:
                    subprocess.run(["nmcli", "device", "wifi", "connect", ssid, "password", pwd], check=False)
                finally:
                    self.connecting_ssids.discard(ssid)
                    GLib.idle_add(self.scan_networks)

            threading.Thread(target=worker, daemon=True).start()

        btn_modal_connect.connect("clicked", do_connect)
        btn_cancel.connect("clicked", lambda w: self.clear_overlay())
        entry.connect("activate", do_connect)

        btn_box.pack_start(btn_modal_connect, True, True, 0)
        btn_box.pack_start(btn_cancel, True, True, 0)
        card.pack_start(btn_box, False, False, 0)

        self.overlay_container.pack_start(card, False, False, 0)
        self.overlay_container.show_all()
        entry.grab_focus()

    def on_network_row_clicked(self, widget, event, net):
        self.trigger_network_connect(net)


class WifiAutoSwitcherDaemon:
    """Headless background watcher that keeps Wi-Fi on the best working saved network."""

    IGNORE_REASONS = (
        {
            NM.DeviceStateReason.USER_REQUESTED,
            NM.DeviceStateReason.NEW_ACTIVATION,
            NM.DeviceStateReason.SLEEPING,
            NM.DeviceStateReason.NETWORKING_OFF,
            NM.DeviceStateReason.NOW_UNMANAGED,
        }
        if NM_AVAILABLE
        else set()
    )

    def __init__(self):
        self.loop = GLib.MainLoop()
        self.nm_client = None
        self.nm_wifi_dev = None
        self.dev_signals = []
        self.client_signals = []
        self.last_connected_ssid = ""
        self.failed_cooldowns = {}
        self.rejected_cooldowns = {}
        self.manual_pause_until = 0.0
        self.proactive_pause_until = 0.0
        self.pending_switch_after_scan = False
        self.switching_in_progress = False
        self._lost_connection_pending = False
        self._ignore_next_disconnect = False
        self._retry_timer_id = None
        self._health_timer_id = None
        self._health_probe_in_flight = False
        self._consecutive_soft_bad = 0
        self._last_scan_eval_ts = 0.0
        self._trial_seq = 0
        self.trial_state = None
        self._lock_fd = None
        self._server_sock = None

    def run(self):
        if not NM_AVAILABLE or not read_auto_switch_enabled():
            return
        try:
            self._lock_fd = os.open(AUTO_SWITCH_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
            return

        try:
            self._init_nm()
            self._start_socket_server()
            self._health_timer_id = GLib.timeout_add_seconds(
                HEALTH_CHECK_INTERVAL_SEC, self._on_health_timer
            )
            GLib.idle_add(self._initial_check)
            self.loop.run()
        finally:
            self._cleanup()

    def _cleanup(self):
        self._clear_trial_state()
        if self._health_timer_id is not None:
            GLib.source_remove(self._health_timer_id)
            self._health_timer_id = None
        if self._retry_timer_id is not None:
            GLib.source_remove(self._retry_timer_id)
            self._retry_timer_id = None
        for obj, hid in self.dev_signals + self.client_signals:
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        self.dev_signals.clear()
        self.client_signals.clear()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
        if os.path.exists(AUTO_SWITCH_SOCKET_PATH):
            try:
                os.unlink(AUTO_SWITCH_SOCKET_PATH)
            except OSError:
                pass
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass

    def _notify(self, title, body):
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Wi-Fi", "-i", "network-wireless", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _clear_trial_state(self):
        if self.trial_state:
            tid = self.trial_state.get("timeout_id")
            if tid is not None:
                try:
                    GLib.source_remove(tid)
                except Exception:
                    pass
            self.trial_state = None
        self.switching_in_progress = False

    def _init_nm(self):
        self.nm_client = NM.Client.new(None)
        self.client_signals = [
            (self.nm_client, self.nm_client.connect("notify::wireless-enabled", self._on_wireless_enabled)),
            (self.nm_client, self.nm_client.connect("device-added", self._on_devices_changed)),
            (self.nm_client, self.nm_client.connect("device-removed", self._on_devices_changed)),
        ]
        self._bind_wifi_dev()

    def _bind_wifi_dev(self):
        for obj, hid in self.dev_signals:
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        self.dev_signals.clear()
        self.nm_wifi_dev = None
        for d in self.nm_client.get_devices():
            if isinstance(d, NM.DeviceWifi):
                self.nm_wifi_dev = d
                self.dev_signals = [
                    (d, d.connect("state-changed", self._on_state_changed)),
                    (d, d.connect("access-point-added", self._on_ap_or_scan)),
                    (d, d.connect("notify::last-scan", self._on_last_scan)),
                ]
                if d.get_state() == NM.DeviceState.ACTIVATED:
                    self._record_active_ssid(d)
                break

    def _get_active_ap_info(self, dev):
        if not dev:
            return None, "", 0, 0.0, 0
        ac = dev.get_active_connection()
        conn = ac.get_connection() if ac else None
        ap = dev.get_active_access_point()
        ssid = _get_ap_ssid(ap) or (ac.get_id() if ac else "")
        sig = int(ap.get_strength()) if ap else 0
        max_mbps = float(ap.get_max_bitrate() or 0) / 1000.0 if ap else 0.0
        freq = int(ap.get_frequency() or 0) if ap else 0
        return conn, ssid, sig, max_mbps, freq

    def _record_active_ssid(self, dev):
        _conn, ssid, _sig, _mbps, _freq = self._get_active_ap_info(dev)
        if ssid:
            self.last_connected_ssid = ssid

    def _on_devices_changed(self, client, dev):
        self._bind_wifi_dev()

    def _on_wireless_enabled(self, client, pspec):
        if client.wireless_get_enabled():
            self.manual_pause_until = 0.0
            self.pending_switch_after_scan = True
        else:
            self._clear_trial_state()
            self.pending_switch_after_scan = False
            self._lost_connection_pending = False

    def _on_ap_or_scan(self, *args):
        if not self.nm_wifi_dev:
            return
        state = self.nm_wifi_dev.get_state()
        if self.pending_switch_after_scan and state == NM.DeviceState.DISCONNECTED:
            self.try_auto_switch(allow_rescan=False)
        elif state == NM.DeviceState.ACTIVATED and not self.trial_state:
            now = time.monotonic()
            if now - self._last_scan_eval_ts >= 8.0:
                self._last_scan_eval_ts = now
                self._evaluate_connected_network(force_proactive=False)

    def _on_last_scan(self, dev, pspec):
        state = dev.get_state()
        if self.pending_switch_after_scan and state == NM.DeviceState.DISCONNECTED:
            self.try_auto_switch(allow_rescan=False, allow_cooled_fallback=True)
        elif state == NM.DeviceState.ACTIVATED and not self.trial_state:
            now = time.monotonic()
            if now - self._last_scan_eval_ts >= 8.0:
                self._last_scan_eval_ts = now
                self._evaluate_connected_network(force_proactive=False)

    def _on_state_changed(self, dev, new_state, old_state, reason):
        if not read_auto_switch_enabled():
            self._clear_trial_state()
            self.loop.quit()
            return

        if reason == NM.DeviceStateReason.USER_REQUESTED and new_state in (
            NM.DeviceState.DEACTIVATING,
            NM.DeviceState.DISCONNECTED,
        ):
            self._clear_trial_state()

        if self.trial_state:
            trial = self.trial_state
            phase = trial["phase"]
            if phase == "switching_to_cand":
                if new_state == NM.DeviceState.ACTIVATED:
                    self._record_active_ssid(dev)
                    if self.last_connected_ssid == trial["cand_ssid"]:
                        if trial.get("timeout_id") is not None:
                            try:
                                GLib.source_remove(trial["timeout_id"])
                            except Exception:
                                pass
                            trial["timeout_id"] = None
                        trial["phase"] = "verifying_cand"
                        GLib.timeout_add(
                            int(POST_SWITCH_SETTLE_SEC * 1000),
                            self._run_trial_verification,
                            trial["id"],
                        )
                    return
                if new_state == NM.DeviceState.FAILED or (
                    new_state == NM.DeviceState.DISCONNECTED
                    and reason != NM.DeviceStateReason.NEW_ACTIVATION
                    and old_state >= NM.DeviceState.PREPARE
                ):
                    self._rollback_to_previous(f"'{trial['cand_ssid']}' failed to connect")
                return
            elif phase == "rolling_back":
                if new_state == NM.DeviceState.ACTIVATED:
                    self._record_active_ssid(dev)
                    prev_ssid = trial["prev_ssid"]
                    msg = trial.get("rollback_msg", "")
                    self._clear_trial_state()
                    self.proactive_pause_until = time.monotonic() + 45.0
                    self._consecutive_soft_bad = 0
                    self._notify(
                        "Auto Switcher",
                        f"Returned to '{prev_ssid}'" + (f" ({msg})" if msg else ""),
                    )
                elif new_state == NM.DeviceState.FAILED:
                    self._clear_trial_state()
                return
            return

        if new_state == NM.DeviceState.ACTIVATED:
            self._record_active_ssid(dev)
            if self.last_connected_ssid:
                self.failed_cooldowns.pop(self.last_connected_ssid, None)
            self.pending_switch_after_scan = False
            self._lost_connection_pending = False
            self._ignore_next_disconnect = False
            self.manual_pause_until = 0.0
            self.switching_in_progress = False
            self._consecutive_soft_bad = 0
            return

        if new_state in (NM.DeviceState.PREPARE, NM.DeviceState.CONFIG, NM.DeviceState.NEED_AUTH, NM.DeviceState.IP_CONFIG):
            self._ignore_next_disconnect = False
            self._record_active_ssid(dev)
            return

        if new_state == NM.DeviceState.DEACTIVATING:
            if reason == NM.DeviceStateReason.USER_REQUESTED:
                self.manual_pause_until = time.monotonic() + 20.0
                self._ignore_next_disconnect = True
            elif reason in self.IGNORE_REASONS:
                self._ignore_next_disconnect = True
            return

        if new_state == NM.DeviceState.FAILED:
            if reason in self.IGNORE_REASONS or self._ignore_next_disconnect:
                return
            if self.last_connected_ssid:
                self.failed_cooldowns[self.last_connected_ssid] = time.monotonic() + 30.0
            self._lost_connection_pending = True
            return

        if new_state == NM.DeviceState.DISCONNECTED:
            if reason == NM.DeviceStateReason.USER_REQUESTED:
                self.manual_pause_until = time.monotonic() + 20.0
                self._lost_connection_pending = False
                self._ignore_next_disconnect = False
                self.pending_switch_after_scan = False
                return
            if reason in self.IGNORE_REASONS or self._ignore_next_disconnect:
                self._lost_connection_pending = False
                self._ignore_next_disconnect = False
                return
            if self._lost_connection_pending or old_state >= NM.DeviceState.PREPARE:
                if old_state >= NM.DeviceState.PREPARE and self.last_connected_ssid:
                    self.failed_cooldowns[self.last_connected_ssid] = time.monotonic() + 30.0
                self._lost_connection_pending = False
                self.try_auto_switch(allow_rescan=True)

    def _active_cooldowns(self, include_rejected=False):
        now = time.monotonic()
        for store in (self.failed_cooldowns, self.rejected_cooldowns):
            for k in [k for k, exp in store.items() if exp <= now]:
                del store[k]
        res = set(self.failed_cooldowns.keys())
        if include_rejected:
            res |= set(self.rejected_cooldowns.keys())
        return res

    def _initial_check(self):
        if not read_auto_switch_enabled():
            self.loop.quit()
            return False
        if not self.nm_wifi_dev:
            return False
        state = self.nm_wifi_dev.get_state()
        if state == NM.DeviceState.DISCONNECTED:
            self.try_auto_switch(allow_rescan=True)
        elif state == NM.DeviceState.ACTIVATED:
            self._evaluate_connected_network(force_proactive=True)
        return False

    def _on_health_timer(self):
        if not read_auto_switch_enabled():
            self.loop.quit()
            return False
        if self.nm_wifi_dev and self.nm_wifi_dev.get_state() == NM.DeviceState.ACTIVATED:
            self._evaluate_connected_network(force_proactive=False)
        return True

    def _evaluate_connected_network(self, force_proactive=False):
        if not read_auto_switch_enabled():
            return
        if self.trial_state or self.switching_in_progress or self._health_probe_in_flight:
            return
        if not self.nm_client or not self.nm_wifi_dev or not self.nm_client.wireless_get_enabled():
            return
        if self.nm_wifi_dev.get_state() != NM.DeviceState.ACTIVATED:
            return

        curr_conn, curr_ssid, curr_sig, curr_mbps, curr_freq = self._get_active_ap_info(self.nm_wifi_dev)
        if not curr_conn or not curr_ssid:
            return

        self._health_probe_in_flight = True

        def worker():
            try:
                cache = load_wifi_quality_cache()
                cached_down = (cache.get(curr_ssid) or {}).get("down_mbps")
                metrics = measure_live_network_quality(
                    signal=curr_sig,
                    max_mbps=curr_mbps,
                    freq=curr_freq,
                    cached_down_mbps=cached_down,
                    include_speed=False,
                )
                bad_reason = metrics.get("bad_reason")
                if bad_reason:
                    is_hard = (not metrics.get("internet_ok")) or float(metrics.get("loss_pct") or 0.0) >= 35.0
                    if is_hard or force_proactive:
                        time.sleep(1.2)
                        metrics = measure_live_network_quality(
                            signal=curr_sig,
                            max_mbps=curr_mbps,
                            freq=curr_freq,
                            cached_down_mbps=cached_down,
                            include_speed=False,
                        )
                        bad_reason = metrics.get("bad_reason")

                record_ssid_quality(
                    curr_ssid,
                    internet_ok=metrics["internet_ok"],
                    loss_pct=metrics["loss_pct"],
                    ping_ms=metrics["ping_ms"],
                    signal=curr_sig,
                    max_mbps=curr_mbps,
                    freq=curr_freq,
                )
                GLib.idle_add(self._on_health_result, curr_conn, curr_ssid, metrics, bad_reason, force_proactive)
            finally:
                self._health_probe_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_health_result(self, curr_conn, curr_ssid, curr_metrics, bad_reason, force_proactive):
        if not read_auto_switch_enabled() or self.trial_state or self.switching_in_progress:
            return False
        if not self.nm_wifi_dev or self.nm_wifi_dev.get_state() != NM.DeviceState.ACTIVATED:
            return False
        _c, active_ssid, _s, _m, _f = self._get_active_ap_info(self.nm_wifi_dev)
        if active_ssid != curr_ssid:
            return False

        now = time.monotonic()
        if now < self.manual_pause_until and not force_proactive:
            return False

        cache = load_wifi_quality_cache()
        cooldowns = self._active_cooldowns(include_rejected=True) | {curr_ssid}

        if bad_reason:
            is_hard = (not curr_metrics.get("internet_ok")) or float(curr_metrics.get("loss_pct") or 0.0) >= 35.0
            if is_hard or force_proactive:
                self._consecutive_soft_bad += 2
            else:
                self._consecutive_soft_bad += 1
            if self._consecutive_soft_bad < 2:
                return False

            cand_conn, cand_ssid, cand_sig, _cand_score = find_best_saved_candidate(
                self.nm_client,
                self.nm_wifi_dev,
                exclude_ssids=cooldowns,
                require_previously_connected=False,
                quality_cache=cache,
            )
            if not cand_conn:
                return False
            self._prepare_and_begin_trial(
                curr_conn, curr_ssid, curr_metrics, cand_conn, cand_ssid, cand_sig, f"bad:{bad_reason}"
            )
            return False

        self._consecutive_soft_bad = 0
        if not force_proactive and now < self.proactive_pause_until:
            return False

        cand_conn, cand_ssid, cand_sig, cand_passive = find_best_saved_candidate(
            self.nm_client,
            self.nm_wifi_dev,
            exclude_ssids=cooldowns,
            require_previously_connected=True,
            quality_cache=cache,
        )
        if not cand_conn:
            return False

        curr_passive = compute_passive_ap_score(
            curr_metrics["signal"],
            max_mbps=curr_metrics["max_mbps"],
            freq_mhz=curr_metrics["freq"],
            cached=cache.get(curr_ssid),
        )
        if cand_passive >= curr_passive + PROACTIVE_PASSIVE_MARGIN:
            self._prepare_and_begin_trial(
                curr_conn, curr_ssid, curr_metrics, cand_conn, cand_ssid, cand_sig, "better_saved"
            )
        return False

    def _prepare_and_begin_trial(self, prev_conn, prev_ssid, prev_metrics, cand_conn, cand_ssid, cand_sig, reason):
        if self.trial_state or self.switching_in_progress:
            return
        self.switching_in_progress = True

        def prep_worker():
            final_prev = dict(prev_metrics)
            if final_prev.get("internet_ok"):
                speed = _run_quick_speed_probe()
                if speed is not None:
                    final_prev["down_mbps"] = speed
                    final_prev["score"] = compute_live_network_score(final_prev)
                    record_ssid_quality(prev_ssid, down_mbps=speed, internet_ok=True)
            GLib.idle_add(
                self._activate_trial_candidate,
                prev_conn,
                prev_ssid,
                final_prev,
                cand_conn,
                cand_ssid,
                cand_sig,
                reason,
            )

        threading.Thread(target=prep_worker, daemon=True).start()

    def _activate_trial_candidate(self, prev_conn, prev_ssid, prev_metrics, cand_conn, cand_ssid, cand_sig, reason):
        if not read_auto_switch_enabled() or not self.nm_client or not self.nm_wifi_dev:
            self.switching_in_progress = False
            return False
        if self.nm_wifi_dev.get_state() != NM.DeviceState.ACTIVATED:
            self.switching_in_progress = False
            return False

        self._trial_seq += 1
        seq = self._trial_seq
        timeout_id = GLib.timeout_add_seconds(TRIAL_CONNECT_TIMEOUT_SEC, self._on_trial_timeout, seq)
        self.trial_state = {
            "id": seq,
            "phase": "switching_to_cand",
            "prev_conn": prev_conn,
            "prev_ssid": prev_ssid,
            "prev_metrics": prev_metrics,
            "cand_conn": cand_conn,
            "cand_ssid": cand_ssid,
            "cand_sig": cand_sig,
            "reason": reason,
            "timeout_id": timeout_id,
        }
        try:
            self.nm_client.activate_connection_async(
                cand_conn,
                self.nm_wifi_dev,
                None,
                None,
                self._on_trial_cand_activate_done,
                seq,
            )
        except Exception:
            self._rollback_to_previous(f"Failed to start switch to '{cand_ssid}'")
        return False

    def _on_trial_cand_activate_done(self, client, res, seq):
        try:
            client.activate_connection_finish(res)
        except Exception:
            if self.trial_state and self.trial_state["id"] == seq and self.trial_state["phase"] == "switching_to_cand":
                self._rollback_to_previous(f"'{self.trial_state['cand_ssid']}' activation error")

    def _on_trial_timeout(self, seq):
        if self.trial_state and self.trial_state["id"] == seq:
            self.trial_state["timeout_id"] = None
            if self.trial_state["phase"] in ("switching_to_cand", "verifying_cand"):
                self._rollback_to_previous(f"'{self.trial_state['cand_ssid']}' timed out")
        return False

    def _run_trial_verification(self, seq):
        if not self.trial_state or self.trial_state["id"] != seq or self.trial_state["phase"] != "verifying_cand":
            return False
        if not self.nm_wifi_dev or self.nm_wifi_dev.get_state() != NM.DeviceState.ACTIVATED:
            self._rollback_to_previous("candidate disconnected")
            return False

        _conn, active_ssid, sig, max_mbps, freq = self._get_active_ap_info(self.nm_wifi_dev)
        cand_ssid = self.trial_state["cand_ssid"]
        if active_ssid != cand_ssid:
            self._clear_trial_state()
            return False

        def verify_worker():
            cand_metrics = measure_live_network_quality(
                signal=sig,
                max_mbps=max_mbps,
                freq=freq,
                include_speed=True,
            )
            record_ssid_quality(
                cand_ssid,
                internet_ok=cand_metrics["internet_ok"],
                loss_pct=cand_metrics["loss_pct"],
                ping_ms=cand_metrics["ping_ms"],
                down_mbps=cand_metrics.get("down_mbps"),
                signal=sig,
                max_mbps=max_mbps,
                freq=freq,
            )
            GLib.idle_add(self._finish_trial_verification, seq, cand_metrics)

        threading.Thread(target=verify_worker, daemon=True).start()
        return False

    def _finish_trial_verification(self, seq, cand_metrics):
        if not self.trial_state or self.trial_state["id"] != seq or self.trial_state["phase"] != "verifying_cand":
            return False
        if not read_auto_switch_enabled():
            self._clear_trial_state()
            return False

        trial = self.trial_state
        cand_ssid = trial["cand_ssid"]
        prev_ssid = trial["prev_ssid"]
        reason = trial["reason"]
        better, detail = is_candidate_better(
            cand_metrics,
            trial["prev_metrics"],
            proactive=(reason == "better_saved"),
        )
        if better:
            self._clear_trial_state()
            self.proactive_pause_until = time.monotonic() + 60.0
            self._consecutive_soft_bad = 0
            if reason.startswith("bad:"):
                self.failed_cooldowns[prev_ssid] = time.monotonic() + FAILED_COOLDOWN_SEC
            self._notify("Auto Switcher", f"Switched to '{cand_ssid}' ({detail})")
        else:
            self._rollback_to_previous(f"'{cand_ssid}' not better: {detail}")
        return False

    def _rollback_to_previous(self, msg=""):
        if not self.trial_state or not self.nm_client or not self.nm_wifi_dev:
            self._clear_trial_state()
            return
        trial = self.trial_state
        cand_ssid = trial["cand_ssid"]
        prev_conn = trial["prev_conn"]
        prev_ssid = trial["prev_ssid"]
        self.rejected_cooldowns[cand_ssid] = time.monotonic() + REJECTED_COOLDOWN_SEC
        if trial.get("timeout_id") is not None:
            try:
                GLib.source_remove(trial["timeout_id"])
            except Exception:
                pass
            trial["timeout_id"] = None
        trial["phase"] = "rolling_back"
        trial["rollback_msg"] = msg
        try:
            self.nm_client.activate_connection_async(
                prev_conn,
                self.nm_wifi_dev,
                None,
                None,
                self._on_rollback_done,
                (trial["id"], prev_ssid, msg),
            )
        except Exception:
            self._clear_trial_state()

    def _on_rollback_done(self, client, res, info):
        _seq, prev_ssid, msg = info
        try:
            client.activate_connection_finish(res)
        except Exception:
            if self.trial_state and self.trial_state.get("phase") == "rolling_back":
                self._clear_trial_state()
                self._notify("Auto Switcher", f"Could not return to '{prev_ssid}'" + (f" ({msg})" if msg else ""))

    def _schedule_retry(self):
        if self._retry_timer_id is not None:
            return
        self._retry_timer_id = GLib.timeout_add(5000, self._on_retry_timer)

    def _on_retry_timer(self):
        self._retry_timer_id = None
        if not read_auto_switch_enabled():
            self.loop.quit()
            return False
        if self.nm_wifi_dev and self.nm_wifi_dev.get_state() == NM.DeviceState.DISCONNECTED:
            self.try_auto_switch(allow_rescan=True, allow_cooled_fallback=True)
        return False

    def try_auto_switch(self, allow_rescan=True, allow_cooled_fallback=False):
        if not read_auto_switch_enabled():
            self.loop.quit()
            return
        if self.trial_state or self.switching_in_progress or not self.nm_client or not self.nm_wifi_dev:
            return
        if not self.nm_client.wireless_get_enabled():
            return
        if time.monotonic() < self.manual_pause_until:
            return
        if self.nm_wifi_dev.get_state() != NM.DeviceState.DISCONNECTED:
            return

        cooldowns = self._active_cooldowns(include_rejected=False)
        best_conn, best_ssid, best_sig = find_best_saved_network(
            self.nm_client, self.nm_wifi_dev, exclude_ssids=cooldowns
        )
        if not best_conn and allow_cooled_fallback and cooldowns:
            best_conn, best_ssid, best_sig = find_best_saved_network(
                self.nm_client, self.nm_wifi_dev, exclude_ssids=None
            )

        if best_conn:
            self.pending_switch_after_scan = False
            self.switching_in_progress = True
            try:
                self.nm_client.activate_connection_async(
                    best_conn, self.nm_wifi_dev, None, None, self._on_activate_done, (best_ssid, best_sig)
                )
            except Exception:
                self.switching_in_progress = False
                self._schedule_retry()
        else:
            self.pending_switch_after_scan = True
            if allow_rescan:
                try:
                    self.nm_wifi_dev.request_scan_options_async(
                        GLib.Variant("a{sv}", {}), None, lambda d, r, u: None, None
                    )
                except Exception:
                    pass
            self._schedule_retry()

    def _on_activate_done(self, client, res, info):
        self.switching_in_progress = False
        ssid, sig = info
        try:
            client.activate_connection_finish(res)
            self._notify("Auto Switcher", f"Connected to '{ssid}' ({sig}%)")
        except Exception:
            self.failed_cooldowns[ssid] = time.monotonic() + 30.0
            self._schedule_retry()

    def _start_socket_server(self):
        if os.path.exists(AUTO_SWITCH_SOCKET_PATH):
            try:
                os.unlink(AUTO_SWITCH_SOCKET_PATH)
            except OSError:
                pass
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(AUTO_SWITCH_SOCKET_PATH)
        self._server_sock.listen(5)

        def listen_loop():
            while True:
                try:
                    conn, _ = self._server_sock.accept()
                    msg = conn.recv(1024).decode().strip()
                    conn.close()
                    if msg == "stop":
                        GLib.idle_add(self.loop.quit)
                        break
                    elif msg == "check":
                        GLib.idle_add(self._handle_check_cmd)
                    elif msg == "resume":
                        GLib.idle_add(self._handle_resume_cmd)
                    elif msg.startswith("manual:"):
                        ssid = msg.split(":", 1)[1]
                        GLib.idle_add(self._handle_manual_cmd, ssid)
                    elif msg.startswith("pause:"):
                        ssid = msg.split(":", 1)[1]
                        GLib.idle_add(self._handle_pause_cmd, ssid)
                except Exception:
                    break

        threading.Thread(target=listen_loop, daemon=True).start()

    def _handle_check_cmd(self):
        self.manual_pause_until = 0.0
        self.proactive_pause_until = 0.0
        self.rejected_cooldowns.clear()
        if self.nm_wifi_dev and self.nm_wifi_dev.get_state() == NM.DeviceState.ACTIVATED:
            self._evaluate_connected_network(force_proactive=True)
        else:
            self.try_auto_switch(allow_rescan=True, allow_cooled_fallback=True)
        return False

    def _handle_resume_cmd(self):
        self.manual_pause_until = 0.0
        self.proactive_pause_until = 0.0
        return False

    def _handle_manual_cmd(self, ssid):
        self._clear_trial_state()
        self.manual_pause_until = 0.0
        self.proactive_pause_until = time.monotonic() + MANUAL_CONNECT_GRACE_SEC
        self._consecutive_soft_bad = 0
        if ssid:
            self.rejected_cooldowns.pop(ssid, None)
        return False

    def _handle_pause_cmd(self, ssid):
        self._clear_trial_state()
        self.manual_pause_until = time.monotonic() + 25.0
        self.pending_switch_after_scan = False
        self._lost_connection_pending = False
        if ssid:
            self.failed_cooldowns[ssid] = time.monotonic() + 25.0
        return False


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
    if "--auto-switcher-daemon" in sys.argv:
        WifiAutoSwitcherDaemon().run()
        sys.exit(0)

    if try_toggle_existing():
        sys.exit(0)

    win = WifiControlCenter()
    start_ipc_server(win)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
