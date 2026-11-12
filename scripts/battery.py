#!/usr/bin/env python3
import os
import re
import glob
import json
import subprocess

STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))


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


def _load_cached_full(bat_name):
    cache_file = os.path.join(STATE_DIR, f"waybar-battery-full-{bat_name}.json")
    try:
        with open(cache_file, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cached_full(bat_name, data):
    cache_file = os.path.join(STATE_DIR, f"waybar-battery-full-{bat_name}.json")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


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


def get_battery_info():
    bat_paths = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    bat_path = bat_paths[0] if bat_paths else "/sys/class/power_supply/BAT0"

    status = _read_sysfs(os.path.join(bat_path, "status")) or "Unknown"
    cap, estimated, energy_now, energy_ref = _compute_capacity(bat_path)

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

    profile = get_power_profile()

    classes = [profile]
    if profile in ("power-saver", "low-power"):
        classes.append("eco")
        classes.append("power-saver")
    if status.lower() == "charging":
        classes.append("charging")

    profile_display = "Eco (Power Saver)" if profile in ("power-saver", "low-power") else profile.capitalize()
    if cap is None:
        bat_detail = f"Unknown ({status})"
    elif estimated and energy_now is not None and energy_ref:
        bat_detail = f"~{cap}% ({status}, {energy_now / 1_000_000:.2f}/{energy_ref / 1_000_000:.0f} Wh est.)"
    else:
        bat_detail = f"{cap}% ({status})"

    tooltip = f"Battery: {bat_detail}\nPower Profile: {profile_display}"

    return json.dumps({
        "text": text,
        "tooltip": tooltip,
        "class": list(dict.fromkeys(classes)),
        "percentage": pct_val
    })


if __name__ == "__main__":
    print(get_battery_info())
