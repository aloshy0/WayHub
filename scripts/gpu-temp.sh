#!/usr/bin/env bash

# GPU Temperature Monitor for Waybar
# Detects NVIDIA discrete GPU (via nvidia-smi) or AMD/other GPU (via hwmon/drm)

# 1. Try NVIDIA via nvidia-smi
if command -v nvidia-smi >/dev/null 2>&1; then
    nv_temp=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d '[:space:]')
    if [ -n "$nv_temp" ] && [ "$nv_temp" -eq "$nv_temp" ] 2>/dev/null; then
        cls="normal"
        [ "$nv_temp" -ge 65 ] && cls="warning"
        [ "$nv_temp" -ge 80 ] && cls="critical"
        echo "{\"text\": \"󰾲 ${nv_temp}°C\", \"class\": \"${cls}\"}"
        exit 0
    fi
fi

# 2. Try AMD / DRM hwmon temperature
for f in /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input /sys/class/hwmon/hwmon*/temp1_input; do
    if [ -f "$f" ]; then
        hwmon_dir=$(dirname "$f")
        name=$(cat "$hwmon_dir/name" 2>/dev/null)
        if [[ "$name" =~ ^(amdgpu|radeon|nouveau)$ ]]; then
            raw=$(cat "$f" 2>/dev/null)
            if [ -n "$raw" ] && [ "$raw" -gt 0 ] 2>/dev/null; then
                temp=$((raw / 1000))
                cls="normal"
                [ "$temp" -ge 65 ] && cls="warning"
                [ "$temp" -ge 80 ] && cls="critical"
                echo "{\"text\": \"󰾲 ${temp}°C\", \"class\": \"${cls}\"}"
                exit 0
            fi
        fi
    fi
done

# 3. Fallback
echo "{\"text\": \"󰾲 N/A\", \"class\": \"disabled\"}"
