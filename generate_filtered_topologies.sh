#!/bin/bash
# Generate filtered topologies for all episodes in the data directory
#
# Usage:
#   ./generate_filtered_topologies.sh [data_directory]
#
# Example:
#   ./generate_filtered_topologies.sh data/data_20251121_185526

set -e

# Default to data directory
DATA_DIR="${1:-data}"

echo "=========================================="
echo "Filtered Topology Generator"
echo "=========================================="
echo ""

# Check if data directory exists
if [ ! -d "$DATA_DIR" ]; then
    echo "Error: Directory '$DATA_DIR' not found"
    echo ""
    echo "Usage: $0 [data_directory]"
    echo "Example: $0 data/data_20251121_185526"
    exit 1
fi

# Find all data run directories
data_runs=$(find "$DATA_DIR" -maxdepth 1 -type d -name "data_*" 2>/dev/null | sort -r)

if [ -z "$data_runs" ]; then
    echo "No data runs found in '$DATA_DIR'"
    echo "Looking for directories matching pattern: data_YYYYMMDD_HHMMSS"
    exit 1
fi

# Count data runs
run_count=$(echo "$data_runs" | wc -l | tr -d ' ')
echo "Found $run_count data run(s)"
echo ""

# Process each data run
total_episodes=0
total_filtered=0

for run_dir in $data_runs; do
    run_name=$(basename "$run_dir")
    echo "Processing: $run_name"

    # Find episodes in this run
    episodes=$(find "$run_dir" -maxdepth 1 -type d -name "ep_*" 2>/dev/null | sort)

    if [ -z "$episodes" ]; then
        echo "  No episodes found"
        continue
    fi

    # Process each episode
    for ep_dir in $episodes; do
        ep_name=$(basename "$ep_dir")

        # Check if required files exist
        if [ ! -f "$ep_dir/topology.json" ] || [ ! -f "$ep_dir/label.json" ]; then
            echo "  ✗ $ep_name: Missing topology.json or label.json"
            continue
        fi

        # Check if filtered topology already exists
        if [ -f "$ep_dir/topology_filtered.json" ]; then
            echo "  ✓ $ep_name: Filtered topology already exists"
            total_filtered=$((total_filtered + 1))
        else
            # Generate filtered topology
            if python filter_topology_by_root_cause.py "$ep_dir" --quiet > /dev/null 2>&1; then
                echo "  ✓ $ep_name: Generated filtered topology"
                total_filtered=$((total_filtered + 1))
            else
                echo "  ✗ $ep_name: Failed to generate filtered topology"
            fi
        fi

        total_episodes=$((total_episodes + 1))
    done

    echo ""
done

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total episodes: $total_episodes"
echo "Filtered topologies: $total_filtered"
echo ""

if [ $total_filtered -eq $total_episodes ]; then
    echo "✓ All episodes have filtered topologies!"
else
    missing=$((total_episodes - total_filtered))
    echo "Note: $missing episode(s) do not have filtered topologies"
fi

echo ""
echo "You can now use the 'Filter by Root Cause' toggle in the UI"
echo "to view filtered topologies."
