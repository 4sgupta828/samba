#!/bin/bash
# Wrapper script to run RCA analysis on nested batch_run structure
# Usage: ./run_batch_analysis.sh <path_to_batch_run>
# Example: ./run_batch_analysis.sh ../data/batch_run

if [ $# -eq 0 ]; then
    echo "Usage: $0 <batch_run_directory>"
    echo "Example: $0 ../data/batch_run"
    exit 1
fi

BATCH_DIR="$1"

if [ ! -d "$BATCH_DIR" ]; then
    echo "Error: Directory $BATCH_DIR does not exist"
    exit 1
fi

echo "Running RCA analysis on all data directories in $BATCH_DIR"
echo "============================================================"

# Find all data_* directories and run analysis on each
for data_dir in "$BATCH_DIR"/data_*; do
    if [ -d "$data_dir" ]; then
        echo ""
        echo "Processing: $(basename $data_dir)"
        echo "------------------------------------------------------------"
        python3 run_rca_batch.py "$data_dir"
    fi
done

echo ""
echo "============================================================"
echo "Analysis complete!"
