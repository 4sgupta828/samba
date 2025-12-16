#!/bin/bash
# Analyze all RCA failures in a batch run directory

BATCH_DIR=${1:?"Usage: $0 <batch_run_directory>"}

echo "Scanning for RCA failures in: $BATCH_DIR"
echo ""

failure_count=0
success_count=0

for data_dir in "$BATCH_DIR"/data_*/; do
    if [ ! -d "$data_dir" ]; then
        continue
    fi

    for ep_dir in "$data_dir"ep_*/; do
        if [ ! -d "$ep_dir" ]; then
            continue
        fi

        rca_file="$ep_dir/rca_analysis.json"

        if [ -f "$rca_file" ]; then
            # Check if RCA failed (not rank 1)
            rank=$(python3 -c "import json; f=open('$rca_file'); data=json.load(f); print(data.get('rank', 'None')); f.close()" 2>/dev/null)

            if [ "$rank" != "1" ]; then
                echo "Analyzing: $ep_dir (rank: $rank)"
                python3 analyze_rca_failure.py "$ep_dir"
                failure_count=$((failure_count + 1))
                echo ""
            else
                success_count=$((success_count + 1))
            fi
        fi
    done
done

echo "================================"
echo "Analysis Complete"
echo "  RCA Failures Analyzed: $failure_count"
echo "  RCA Successes: $success_count"
echo "================================"
