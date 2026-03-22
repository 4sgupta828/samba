#!/bin/bash
# Launch script for Dataraft Telemetry Dashboard

echo "🚀 Starting Dataraft Telemetry Dashboard..."
echo ""

# Data directory: DATARAFT_DATA_DIR > SAMBA_DATA_DIR (legacy) > ../data
_DATA="${DATARAFT_DATA_DIR:-${SAMBA_DATA_DIR:-../data}}"
export DATARAFT_DATA_DIR="$_DATA"
export SAMBA_DATA_DIR="$_DATA"
export PORT="${PORT:-8050}"

echo "Configuration:"
echo "  Data Directory: $DATARAFT_DATA_DIR"
echo "  Port: $PORT"
echo ""

# Check if data directory exists
if [ ! -d "$DATARAFT_DATA_DIR" ]; then
    echo "⚠️  Warning: Data directory $DATARAFT_DATA_DIR does not exist"
    echo "   Set DATARAFT_DATA_DIR (or legacy SAMBA_DATA_DIR) to point at your data root"
    echo ""
fi

# Launch the app
echo "Starting dashboard at http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""
lsof -ti:8050 | xargs kill -9 2>/dev/null; sleep 2
python3 app.py
