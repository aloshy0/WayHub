#!/usr/bin/env python3
import os
import glob
import json
import subprocess

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

def get_battery_info():
    cap = 100
    status = "Unknown"

    bat_paths = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    bat_path = bat_paths[0] if bat_paths else "/sys/class/power_supply/BAT0"

    try:
        with open(os.path.join(bat_path, "capacity"), "r") as f:
            cap = int(f.read().strip())
        with open(os.path.join(bat_path, "status"), "r") as f:
            status = f.read().strip()
    except Exception:
        pass

    icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
    idx = min(9, max(0, cap // 10))
    icon = icons[idx]

    if status == "Charging":
        text = f"{cap}% 󰂄"
    elif status == "Full":
        text = "󰁹"
    else:
        text = f"{cap}% {icon}"

    profile = get_power_profile()

    classes = [profile]
    if profile in ("power-saver", "low-power"):
        classes.append("eco")
        classes.append("power-saver")
    if status.lower() == "charging":
        classes.append("charging")

    profile_display = "Eco (Power Saver)" if profile in ("power-saver", "low-power") else profile.capitalize()
    tooltip = f"Battery: {cap}% ({status})\nPower Profile: {profile_display}"

    return json.dumps({
        "text": text,
        "tooltip": tooltip,
        "class": " ".join(classes),
        "percentage": cap
    })

if __name__ == "__main__":
    print(get_battery_info())
