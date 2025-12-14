#!/bin/bash
# Wrapper script to run RCA analysis on nested batch_run structure
# Usage: ./run_batch_analysis.sh <path_to_batch_run> [top_k] [--reprocess]
# Example: ./run_batch_analysis.sh ../data/batch_run 5
#          ./run_batch_analysis.sh ../data/batch_run 5 --reprocess

if [ $# -eq 0 ]; then
    echo "Usage: $0 <batch_run_directory> [top_k] [--reprocess]"
    echo "Example: $0 ../data/batch_run 5"
    echo "         $0 ../data/batch_run 5 --reprocess"
    echo ""
    echo "Options:"
    echo "  --reprocess    Clear all marker files and analysis outputs before running"
    exit 1
fi

BATCH_DIR="$1"
shift

if [ ! -d "$BATCH_DIR" ]; then
    echo "Error: Directory $BATCH_DIR does not exist"
    exit 1
fi

# Note: The updated run_rca_batch.py now handles nested structures automatically
# So we can just call it once on the batch_run directory
python3 run_rca_batch.py "$BATCH_DIR" "$@"
