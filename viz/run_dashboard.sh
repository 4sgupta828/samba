#!/bin/bash
# Samba Telemetry Dashboard Launcher

echo "🚀 Starting Samba Telemetry Dashboard..."
echo ""

# Check if we're in the viz directory
if [ ! -f "app.py" ]; then
    echo "Error: Please run this script from the viz/ directory"
    exit 1
fi

# Check if data directory exists
if [ ! -d "../data/final_validation" ]; then
    echo "Warning: Default data directory not found"
    echo "Set SAMBA_DATA_DIR environment variable to your data location"
fi

# Set defaults
export SAMBA_DATA_DIR=${SAMBA_DATA_DIR:-../data/final_validation}
export PORT=${PORT:-8050}

echo "Configuration:"
echo "  Data Directory: $SAMBA_DATA_DIR"
echo "  Port: $PORT"
echo ""

# Run the app
python app.py
