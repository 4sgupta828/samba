#!/bin/bash
# Example: Analyze fault propagation for an episode

EPISODE_DIR="$1"

if [ -z "$EPISODE_DIR" ]; then
    echo "Usage: $0 <episode_directory>"
    echo "Example: $0 data/data_20251125_092902/ep_1"
    exit 1
fi

echo "=== Human-Readable Analysis ==="
python analyze_fault_propagation.py "$EPISODE_DIR"

echo -e "\n\n=== JSON Summary (first few nodes) ==="
python analyze_fault_propagation.py "$EPISODE_DIR" --json | \
    jq '{
        scenario: .episode.scenario,
        root_cause: .episode.root_cause_node,
        fault_type: .episode.fault_type,
        timeline: {
            start: .episode.fault_start_time,
            full_effect: .episode.fault_full_effect_time
        },
        impacted_nodes: (.propagation | to_entries | map({
            node: .key,
            distance: .value.distance,
            type: .value.type,
            metrics_affected: (.value.metrics | length)
        }) | sort_by(.distance))
    }'
