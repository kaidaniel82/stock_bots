#!/bin/bash
# Trailing Stop Manager Startup Script
# Delegates to main.py which handles cleanup, tray, etc.

cd "$(dirname "$0")"

# Exclude data and logs from hot-reload to prevent TWS disconnect
export REFLEX_HOT_RELOAD_EXCLUDE_PATHS="data:logs"

.venv/bin/python main.py "$@"
