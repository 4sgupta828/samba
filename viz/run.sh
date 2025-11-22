#!/bin/bash
# Launch script for Samba Telemetry Dashboard

echo "🚀 Starting Samba Telemetry Dashboard..."
echo ""

# Set default data directory if not specified (app.py will find data runs automatically)
export SAMBA_DATA_DIR="${SAMBA_DATA_DIR:-../data}"
export PORT="${PORT:-8050}"

echo "Configuration:"
echo "  Data Directory: $SAMBA_DATA_DIR"
echo "  Port: $PORT"
echo ""

# Check if data directory exists
if [ ! -d "$SAMBA_DATA_DIR" ]; then
    echo "⚠️  Warning: Data directory $SAMBA_DATA_DIR does not exist"
    echo "   You can set SAMBA_DATA_DIR environment variable to specify a different directory"
    echo ""
fi

# Launch the app
echo "Starting dashboard at http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""
lsof -ti:8050 | xargs kill -9 2>/dev/null; sleep 2
python app.py
