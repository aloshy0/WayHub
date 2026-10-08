#!/usr/bin/env bash
# Wrapper to launch or toggle the Apps Menu popup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/apps-menu.py" "$@"
