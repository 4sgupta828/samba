#!/bin/bash
# Dataraft Telemetry Dashboard Launcher

echo "🚀 Starting Dataraft Telemetry Dashboard..."
echo ""

# Check if we're in the viz directory
if [ ! -f "app.py" ]; then
    echo "Error: Please run this script from the viz/ directory"
    exit 1
fi

# Check if data directory exists
if [ ! -d "../data" ]; then
    echo "Warning: Data directory not found at ../data"
    echo "Set DATARAFT_DATA_DIR (or legacy SAMBA_DATA_DIR) to your data location"
fi

# Data directory: DATARAFT_DATA_DIR > SAMBA_DATA_DIR (legacy) > ../data
_DATA="${DATARAFT_DATA_DIR:-${SAMBA_DATA_DIR:-../data}}"
export DATARAFT_DATA_DIR="$_DATA"
export SAMBA_DATA_DIR="$_DATA"
export PORT=${PORT:-8050}

echo "Configuration:"
echo "  Data Directory: $DATARAFT_DATA_DIR"
echo "  Port: $PORT"
echo ""

# Run the app (use python3 — macOS often has no `python` in PATH)
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Install Python 3 (e.g. brew install python3) or use: python3 app.py"
    exit 1
fi
python3 app.py
