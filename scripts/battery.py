#!/usr/bin/env python3
import fcntl
import glob
import json
import os
import re
import subprocess
import sys
import time

STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
AUTO_ECO_THRESHOLD = 30
PERFORMANCE_MIN_CHARGE = 30
REFRESH_LOCK_THRESHOLD = 30
AUTO_ECO_STATE_FILE = os.path.join(STATE_DIR, "waybar-auto-eco.json")
POWER_ESTIMATE_STATE_FILE = os.path.join(STATE_DIR, "waybar-power-estimates.json")
SYNC_LOCK_PATH = f"/tmp/waybar_power_sync_{os.getuid()}.lock"
PROFILE_COMPUTE_FACTORS = {
    "power-saver": 0.78,
    "balanced": 1.00,
    "performance": 1.32,
}
DISPLAY_144_EXTRA_W = 1.8
DEFAULT_BASE_COMPUTE_W = 12.5


def _read_sysfs(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return None


def _read_int(path):
    val = _read_sysfs(path)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _load_json_state(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_json_state(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_cached_full(bat_name):
    return _load_json_state(os.path.join(STATE_DIR, f"waybar-battery-full-{bat_name}.json"))


def _save_cached_full(bat_name, data):
    _save_json_state(os.path.join(STATE_DIR, f"waybar-battery-full-{bat_name}.json"), data)


def _upower_history_full_uwh(model, serial):
    """Estimate last known full capacity (uWh) from UPower history filenames if sysfs omits it."""
    patterns = []
    if model and serial:
        patterns.append(f"/var/lib/upower/history-charge-{model}-*-{serial}.dat")
    if model:
        patterns.append(f"/var/lib/upower/history-charge-{model}-*.dat")
    patterns.append("/var/lib/upower/history-charge-Primary-*.dat")

    candidates = []
    for pat in patterns:
        for path in glob.glob(pat):
            m = re.search(r"-(\d+)(?:-[^-]+)?\.dat$", os.path.basename(path))
            if m:
                wh = int(m.group(1))
                if 5 <= wh <= 300:
                    try:
                        candidates.append((os.path.getmtime(path), wh * 1_000_000))
                    except OSError:
                        pass
        if candidates:
            break

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def get_power_profile():
    try:
        if os.path.exists("/sys/firmware/acpi/platform_profile"):
            with open("/sys/firmware/acpi/platform_profile", "r") as f:
                p = f.read().strip()
                if p in ("low-power", "power-saver"):
                    return "power-saver"
                elif p:
                    return p
    except Exception:
        pass

    try:
        out = subprocess.check_output([
            "busctl", "get-property",
            "net.hadess.PowerProfiles",
            "/net/hadess/PowerProfiles",
            "net.hadess.PowerProfiles",
            "ActiveProfile"
        ], text=True, timeout=1)
        clean = out.strip().replace('s "', '').replace('"', '').strip()
        if clean:
            return clean
    except Exception:
        pass

    return "balanced"


def _notify(title, body):
    try:
        subprocess.Popen(
            ["notify-send", "-u", "low", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def is_performance_allowed(cap):
    """Allow Performance mode only when battery charge is at least 30% (or unknown)."""
    return cap is None or cap >= PERFORMANCE_MIN_CHARGE


def is_high_refresh_allowed(cap):
    """Allow >60 Hz refresh rates only when battery charge is at least 30% (or unknown)."""
    return cap is None or cap >= REFRESH_LOCK_THRESHOLD


def _get_target_monitors():
    try:
        out = subprocess.check_output(
            ["hyprctl", "monitors", "-j"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
        )
        monitors = json.loads(out)
    except Exception:
        return []

    active = [m for m in monitors if not m.get("disabled")]
    internal = [m for m in active if m.get("name", "").startswith("eDP")]
    return internal if internal else active[:1]


def get_current_refresh_hz():
    """Return rounded current refresh rate (Hz) of the primary/internal monitor, or None."""
    for mon in _get_target_monitors():
        hz = mon.get("refreshRate")
        if isinstance(hz, (int, float)) and hz > 0:
            return round(hz)
    return None


def _select_refresh_mode(target_kind, mon):
    cur_w = mon.get("width")
    cur_h = mon.get("height")
    candidates = []
    for entry in mon.get("availableModes", []):
        match = re.match(r"^(\d+)x(\d+)@(\d+(?:\.\d+)?)Hz$", entry.strip())
        if match and int(match.group(1)) == cur_w and int(match.group(2)) == cur_h:
            candidates.append((float(match.group(3)), entry.strip()[:-2]))

    if not candidates:
        return None
    if target_kind == "60":
        return min(candidates, key=lambda item: (abs(item[0] - 60.0), item[0]))
    return max(candidates, key=lambda item: item[0])


def resolve_target_refresh_kind(profile_id, cap=None, manual_hz=None):
    """Return '60' or 'max' based on battery lock (<30%), manual override, or active profile."""
    if not is_high_refresh_allowed(cap):
        return "60"
    if manual_hz in (60, "60"):
        return "60"
    if manual_hz in (144, "max"):
        return "max"
    if profile_id in ("power-saver", "low-power"):
        return "60"
    return "max"


def _apply_monitor_refresh_rate(target_kind):
    """Switch internal monitor to 60 Hz or max Hz when current rate differs by >1 Hz."""
    changed = False
    try:
        lock_fd = os.open(SYNC_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        lock_fd = None

    try:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        for mon in _get_target_monitors():
            selected = _select_refresh_mode(target_kind, mon)
            if not selected:
                continue
            target_hz, mode_str = selected
            cur_hz = float(mon.get("refreshRate") or 0.0)
            if abs(cur_hz - target_hz) <= 1.0:
                continue
            name = mon.get("name", "")
            pos = f"{mon.get('x', 0)}x{mon.get('y', 0)}"
            scale = str(mon.get("scale", 1))
            lua_expr = (
                f'hl.monitor({{ output = "{name}", mode = "{mode_str}", '
                f'position = "{pos}", scale = "{scale}" }})'
            )
            res = subprocess.run(
                ["hyprctl", "eval", lua_expr],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            if res.returncode == 0:
                changed = True
    except Exception:
        pass
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except OSError:
                pass
    return changed


def sync_display_refresh_rate(profile_id, cap=None, manual_hz=None):
    """Sync display refresh rate to battery lock, manual Hz override, or power profile."""
    if cap is None:
        _, cap, _, _, _, _ = read_battery_summary()
    if manual_hz is None:
        manual_hz = _load_json_state(AUTO_ECO_STATE_FILE).get("manual_hz")
    return _apply_monitor_refresh_rate(resolve_target_refresh_kind(profile_id, cap=cap, manual_hz=manual_hz))


def set_manual_refresh_rate(target_hz, notify_waybar=True, cap=None):
    """Manually switch between 60 Hz and max (144 Hz); blocked above 60 Hz when battery <30%."""
    if cap is None:
        _, cap, _, _, _, _ = read_battery_summary()
    if target_hz > 60 and not is_high_refresh_allowed(cap):
        _apply_monitor_refresh_rate("60")
        return False

    mode_kind = "60" if target_hz <= 60 else "max"
    _apply_monitor_refresh_rate(mode_kind)

    state = _load_json_state(AUTO_ECO_STATE_FILE)
    state["manual_hz"] = 60 if mode_kind == "60" else "max"
    _save_json_state(AUTO_ECO_STATE_FILE, state)
    mark_mode_switch_ts()

    if notify_waybar:
        try:
            subprocess.run(
                ["pkill", "-RTMIN+8", "waybar"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    return True


def set_power_profile(profile_id, notify_waybar=True, cap=None, reset_manual_hz=True):
    """Apply active power profile via PowerProfiles D-Bus or powerprofilesctl and sync display Hz."""
    if cap is None:
        _, cap, _, _, _, _ = read_battery_summary()
    if profile_id == "performance" and not is_performance_allowed(cap):
        return False

    applied = False
    try:
        res = subprocess.run(
            [
                "busctl",
                "set-property",
                "net.hadess.PowerProfiles",
                "/net/hadess/PowerProfiles",
                "net.hadess.PowerProfiles",
                "ActiveProfile",
                "s",
                profile_id,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        applied = res.returncode == 0
    except Exception:
        pass

    if not applied:
        try:
            res = subprocess.run(
                ["powerprofilesctl", "set", profile_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            applied = res.returncode == 0
        except Exception:
            pass

    if applied:
        manual_hz = None if reset_manual_hz else _load_json_state(AUTO_ECO_STATE_FILE).get("manual_hz")
        if reset_manual_hz:
            state = _load_json_state(AUTO_ECO_STATE_FILE)
            if state.get("manual_hz") is not None:
                state["manual_hz"] = None
                _save_json_state(AUTO_ECO_STATE_FILE, state)
        mark_mode_switch_ts()
        sync_display_refresh_rate(profile_id, cap=cap, manual_hz=manual_hz)

    if notify_waybar:
        try:
            subprocess.run(
                ["pkill", "-RTMIN+8", "waybar"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    return applied


def reconcile_power_state(cap, status, current_profile):
    """Enforce power-profile rules (<30% auto-eco, <30% lock performance/60Hz, charging -> balanced)."""
    state = _load_json_state(AUTO_ECO_STATE_FILE)
    triggered = bool(state.get("triggered", False))
    was_charging = state.get("charging")
    manual_hz = state.get("manual_hz")
    is_charging = status.lower() == "charging"

    if cap is not None and not is_performance_allowed(cap) and current_profile == "performance":
        fallback = "balanced" if is_charging else "power-saver"
        if set_power_profile(fallback, notify_waybar=False, cap=cap, reset_manual_hz=True):
            current_profile = get_power_profile()
            manual_hz = None
            if fallback == "power-saver":
                triggered = True
            _notify(
                "Battery Below 30%",
                f"Performance disabled at {cap}% — switched to {'Balanced' if fallback == 'balanced' else 'Eco'} mode (60 Hz).",
            )

    if is_charging:
        triggered = False
        if (was_charging is not True) and current_profile == "power-saver":
            if set_power_profile("balanced", notify_waybar=False, cap=cap, reset_manual_hz=True):
                current_profile = get_power_profile()
                manual_hz = None
                hz_label = "144 Hz" if is_high_refresh_allowed(cap) else "60 Hz locked <30%"
                _notify("Charger Connected", f"Switched back to Balanced mode ({hz_label}).")
    elif cap is not None:
        if cap >= AUTO_ECO_THRESHOLD:
            triggered = False
        elif not triggered:
            if current_profile == "power-saver":
                triggered = True
            elif set_power_profile("power-saver", notify_waybar=False, cap=cap, reset_manual_hz=True):
                current_profile = get_power_profile()
                manual_hz = None
                triggered = True
                _notify("Battery Below 30%", f"Switched to Eco mode (60 Hz) at {cap}%.")

    new_state = {"triggered": triggered, "charging": is_charging, "manual_hz": manual_hz}
    if new_state != state:
        _save_json_state(AUTO_ECO_STATE_FILE, new_state)

    sync_display_refresh_rate(current_profile, cap=cap, manual_hz=manual_hz)
    return current_profile


def _compute_capacity(bat_path):
    bat_name = os.path.basename(bat_path)
    cap = _read_int(os.path.join(bat_path, "capacity"))
    energy_now = _read_int(os.path.join(bat_path, "energy_now"))
    energy_full = _read_int(os.path.join(bat_path, "energy_full"))
    energy_design = _read_int(os.path.join(bat_path, "energy_full_design"))
    charge_now = _read_int(os.path.join(bat_path, "charge_now"))
    charge_full = _read_int(os.path.join(bat_path, "charge_full"))
    charge_design = _read_int(os.path.join(bat_path, "charge_full_design"))

    if (energy_full and energy_full > 0) or (charge_full and charge_full > 0):
        cache_data = {}
        if energy_full and energy_full > 0:
            cache_data["energy_full"] = energy_full
        if charge_full and charge_full > 0:
            cache_data["charge_full"] = charge_full
        _save_cached_full(bat_name, cache_data)

    if cap is not None:
        return max(0, min(100, cap)), False, energy_now, energy_full or energy_design

    full_energy_ref = energy_full if (energy_full and energy_full > 0) else (
        energy_design if (energy_design and energy_design > 0) else None
    )
    if energy_now is not None and full_energy_ref:
        est = round((energy_now / full_energy_ref) * 100)
        return max(0, min(100, est)), False, energy_now, full_energy_ref

    full_charge_ref = charge_full if (charge_full and charge_full > 0) else (
        charge_design if (charge_design and charge_design > 0) else None
    )
    if charge_now is not None and full_charge_ref:
        est = round((charge_now / full_charge_ref) * 100)
        return max(0, min(100, est)), False, None, None

    cached = _load_cached_full(bat_name)
    if energy_now is not None and cached.get("energy_full"):
        ref = cached["energy_full"]
        est = round((energy_now / ref) * 100)
        return max(0, min(100, est)), True, energy_now, ref
    if charge_now is not None and cached.get("charge_full"):
        ref = cached["charge_full"]
        est = round((charge_now / ref) * 100)
        return max(0, min(100, est)), True, None, None

    if energy_now is not None:
        model = _read_sysfs(os.path.join(bat_path, "model_name"))
        serial = _read_sysfs(os.path.join(bat_path, "serial_number"))
        upower_full = _upower_history_full_uwh(model, serial)
        if upower_full:
            est = round((energy_now / upower_full) * 100)
            return max(0, min(100, est)), True, energy_now, upower_full

    return None, False, energy_now, None


def mark_mode_switch_ts():
    """Record timestamp of last profile or refresh-rate switch to avoid UPower lag pollution."""
    est = _load_json_state(POWER_ESTIMATE_STATE_FILE)
    est["last_switch_ts"] = time.time()
    _save_json_state(POWER_ESTIMATE_STATE_FILE, est)


def read_upower_battery_metrics(bat_name="BAT0"):
    """Return (energy_wh, energy_full_wh, energy_rate_w, state_int, update_ts) via UPower."""
    for dev in (f"battery_{bat_name}", "DisplayDevice"):
        try:
            out = subprocess.check_output(
                [
                    "busctl",
                    "get-property",
                    "org.freedesktop.UPower",
                    f"/org/freedesktop/UPower/devices/{dev}",
                    "org.freedesktop.UPower.Device",
                    "Energy",
                    "EnergyFull",
                    "EnergyRate",
                    "State",
                    "UpdateTime",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            ).strip().splitlines()
            if len(out) >= 5:
                vals = [line.split(None, 1)[1] for line in out[:5]]
                return float(vals[0]), float(vals[1]), float(vals[2]), int(vals[3]), int(vals[4])
        except Exception:
            continue
    return None, None, None, None, 0


def format_duration(hours):
    """Format duration in fractional hours as '~Xh YYm' or '~Ym'."""
    if hours is None or hours <= 0:
        return "--"
    total_mins = max(1, round(hours * 60))
    if total_mins >= 60:
        hrs, mins = divmod(total_mins, 60)
        return f"~{hrs}h {mins:02d}m"
    return f"~{total_mins}m"


def compute_mode_predictions(base_compute_w, active_profile, active_hz, cap, energy_wh):
    """Build per-mode wattage and remaining battery ETA using current workload & refresh rules."""
    modes = {}
    for pid in ("power-saver", "balanced", "performance"):
        if pid == active_profile and active_hz:
            hz = 60 if not is_high_refresh_allowed(cap) else (144 if active_hz > 75 else 60)
        else:
            hz = 60 if resolve_target_refresh_kind(pid, cap=cap, manual_hz=None) == "60" else 144

        display_w = DISPLAY_144_EXTRA_W if hz > 75 else 0.0
        pred_w = max(4.5, base_compute_w * PROFILE_COMPUTE_FACTORS[pid] + display_w)
        hours = (energy_wh / pred_w) if (energy_wh is not None and energy_wh > 0) else None
        modes[pid] = {
            "watts": round(pred_w, 1),
            "hz": hz,
            "hours": hours,
            "eta": format_duration(hours),
        }
    return modes


def estimate_mode_runtimes(active_profile, active_hz, cap=None, energy_now=None, bat_name="BAT0", persist=True):
    """Calibrate current usage workload from UPower and predict remaining battery time per mode."""
    up_energy, _up_full, rate_w, state_int, update_ts = read_upower_battery_metrics(bat_name)
    energy_wh = (energy_now / 1_000_000.0) if (energy_now is not None and energy_now > 0) else up_energy

    est_state = _load_json_state(POWER_ESTIMATE_STATE_FILE)
    prev_base = est_state.get("base_compute_w")
    switch_ts = float(est_state.get("last_switch_ts") or 0.0)
    base_w = float(prev_base) if isinstance(prev_base, (int, float)) else DEFAULT_BASE_COMPUTE_W

    is_discharging = state_int == 2
    live_watts = None
    if is_discharging and rate_w is not None and 1.0 <= rate_w <= 150.0:
        live_watts = rate_w
        if update_ts == 0 or update_ts > switch_ts + 5:
            active_display_w = DISPLAY_144_EXTRA_W if (active_hz is not None and active_hz > 75) else 0.0
            factor = PROFILE_COMPUTE_FACTORS.get(active_profile, 1.0)
            instant_base = max(4.0, (rate_w - active_display_w) / factor)
            base_w = instant_base if prev_base is None else (0.55 * instant_base + 0.45 * base_w)
            if persist and (prev_base is None or abs(base_w - float(prev_base)) >= 0.15):
                est_state["base_compute_w"] = round(base_w, 2)
                est_state["last_switch_ts"] = switch_ts
                _save_json_state(POWER_ESTIMATE_STATE_FILE, est_state)

    modes = compute_mode_predictions(base_w, active_profile, active_hz, cap, energy_wh)
    return {
        "base_compute_w": round(base_w, 2),
        "live_watts": round(live_watts, 1) if live_watts is not None else None,
        "energy_wh": round(energy_wh, 2) if energy_wh is not None else None,
        "is_discharging": is_discharging,
        "modes": modes,
    }


def read_battery_summary():
    """Return (status, cap, estimated, energy_now, energy_full, cycles) for the primary battery."""
    bat_paths = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    bat_path = bat_paths[0] if bat_paths else "/sys/class/power_supply/BAT0"
    status = _read_sysfs(os.path.join(bat_path, "status")) or "Unknown"
    cap, estimated, energy_now, energy_ref = _compute_capacity(bat_path)
    cycles = _read_int(os.path.join(bat_path, "cycle_count"))
    return status, cap, estimated, energy_now, energy_ref, cycles


def get_battery_info():
    status, cap, estimated, energy_now, energy_ref, _cycles = read_battery_summary()

    icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
    if cap is None:
        cap_label = "?%"
        icon = "󰂑"
        pct_val = 0
    else:
        cap_label = f"~{cap}%" if estimated else f"{cap}%"
        idx = min(9, max(0, cap // 10))
        icon = icons[idx]
        pct_val = cap

    if status == "Charging":
        text = f"{cap_label} 󰂄"
    elif status == "Full":
        text = "󰁹"
    else:
        text = f"{cap_label} {icon}"

    bat_paths = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    bat_name = os.path.basename(bat_paths[0]) if bat_paths else "BAT0"

    profile = reconcile_power_state(cap, status, get_power_profile())
    refresh_hz = get_current_refresh_hz()
    estimates = estimate_mode_runtimes(profile, refresh_hz, cap=cap, energy_now=energy_now, bat_name=bat_name)

    classes = [profile]
    if profile in ("power-saver", "low-power"):
        classes.append("eco")
        classes.append("power-saver")
    if status.lower() == "charging":
        classes.append("charging")

    profile_display = "Eco (Power Saver)" if profile in ("power-saver", "low-power") else profile.capitalize()
    if refresh_hz:
        profile_display = f"{profile_display} ({refresh_hz} Hz)"
    if cap is None:
        bat_detail = f"Unknown ({status})"
    elif estimated and energy_now is not None and energy_ref:
        bat_detail = f"~{cap}% ({status}, {energy_now / 1_000_000:.2f}/{energy_ref / 1_000_000:.0f} Wh est.)"
    else:
        bat_detail = f"{cap}% ({status})"

    modes = estimates["modes"]
    active_est = modes.get(profile, modes["balanced"])
    draw_w = estimates["live_watts"] if estimates["live_watts"] is not None else active_est["watts"]
    est_label = "Est. Remaining" if status.lower() != "charging" else "Projected on Battery"
    perf_str = f"{modes['performance']['eta']}" if is_performance_allowed(cap) else "Locked <30%"

    tooltip = (
        f"Battery: {bat_detail}\n"
        f"Power Profile: {profile_display}\n"
        f"{est_label}: {active_est['eta']} ({draw_w:.1f} W)\n"
        f"  Eco: {modes['power-saver']['eta']} | Bal: {modes['balanced']['eta']} | Perf: {perf_str}\n"
        f"Click: power profile selector\n"
        f"Right-click: toggle Eco mode"
    )

    return json.dumps({
        "text": text,
        "tooltip": tooltip,
        "class": list(dict.fromkeys(classes)),
        "percentage": pct_val
    })


def toggle_eco_mode():
    target = "balanced" if get_power_profile() == "power-saver" else "power-saver"
    set_power_profile(target, notify_waybar=True)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--toggle-eco":
        toggle_eco_mode()
    elif len(sys.argv) >= 3 and sys.argv[1] == "--set":
        set_power_profile(sys.argv[2], notify_waybar=True)
    elif len(sys.argv) >= 3 and sys.argv[1] == "--set-hz":
        try:
            set_manual_refresh_rate(int(sys.argv[2]), notify_waybar=True)
        except ValueError:
            pass
    else:
        print(get_battery_info())
