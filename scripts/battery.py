#!/usr/bin/env python3
import fcntl
import glob
import json
import os
import re
import subprocess
import sys

STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
AUTO_ECO_THRESHOLD = 30
PERFORMANCE_MIN_CHARGE = 30
AUTO_ECO_STATE_FILE = os.path.join(STATE_DIR, "waybar-auto-eco.json")
SYNC_LOCK_PATH = f"/tmp/waybar_power_sync_{os.getuid()}.lock"


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


def _select_refresh_mode(profile_id, mon):
    cur_w = mon.get("width")
    cur_h = mon.get("height")
    candidates = []
    for entry in mon.get("availableModes", []):
        match = re.match(r"^(\d+)x(\d+)@(\d+(?:\.\d+)?)Hz$", entry.strip())
        if match and int(match.group(1)) == cur_w and int(match.group(2)) == cur_h:
            candidates.append((float(match.group(3)), entry.strip()[:-2]))

    if not candidates:
        return None
    if profile_id in ("power-saver", "low-power"):
        return min(candidates, key=lambda item: (abs(item[0] - 60.0), item[0]))
    return max(candidates, key=lambda item: item[0])


def sync_display_refresh_rate(profile_id):
    """Set internal monitor to 60 Hz for Eco/power-saver and max Hz for balanced/performance."""
    changed = False
    try:
        lock_fd = os.open(SYNC_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        lock_fd = None

    try:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        for mon in _get_target_monitors():
            selected = _select_refresh_mode(profile_id, mon)
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


def set_power_profile(profile_id, notify_waybar=True, cap=None):
    """Apply active power profile via PowerProfiles D-Bus or powerprofilesctl and sync display Hz."""
    if profile_id == "performance":
        if cap is None:
            _, cap, _, _, _, _ = read_battery_summary()
        if not is_performance_allowed(cap):
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
        sync_display_refresh_rate(profile_id)

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
    """Enforce power-profile rules (<30% auto-eco, <30% lock performance, charging -> balanced) and Hz."""
    state = _load_json_state(AUTO_ECO_STATE_FILE)
    triggered = bool(state.get("triggered", False))
    was_charging = state.get("charging")
    is_charging = status.lower() == "charging"

    if cap is not None and not is_performance_allowed(cap) and current_profile == "performance":
        fallback = "balanced" if is_charging else "power-saver"
        if set_power_profile(fallback, notify_waybar=False, cap=cap):
            current_profile = get_power_profile()
            if fallback == "power-saver":
                triggered = True
            _notify(
                "Battery Below 30%",
                f"Performance disabled at {cap}% — switched to {'Balanced' if fallback == 'balanced' else 'Eco'} mode.",
            )

    if is_charging:
        triggered = False
        if (was_charging is not True) and current_profile == "power-saver":
            if set_power_profile("balanced", notify_waybar=False, cap=cap):
                current_profile = get_power_profile()
                _notify("Charger Connected", "Switched back to Balanced mode (144 Hz).")
    elif cap is not None:
        if cap >= AUTO_ECO_THRESHOLD:
            triggered = False
        elif not triggered:
            if current_profile == "power-saver":
                triggered = True
            elif set_power_profile("power-saver", notify_waybar=False, cap=cap):
                current_profile = get_power_profile()
                triggered = True
                _notify("Battery Below 30%", f"Switched to Eco mode (60 Hz) at {cap}%.")

    new_state = {"triggered": triggered, "charging": is_charging}
    if new_state != state:
        _save_json_state(AUTO_ECO_STATE_FILE, new_state)

    sync_display_refresh_rate(current_profile)
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

    profile = reconcile_power_state(cap, status, get_power_profile())
    refresh_hz = get_current_refresh_hz()

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

    tooltip = (
        f"Battery: {bat_detail}\n"
        f"Power Profile: {profile_display}\n"
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
    else:
        print(get_battery_info())
