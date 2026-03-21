#!/usr/bin/env python3
"""Quick diagnostic to check metrics for a specific node."""

import json
import sys
from pathlib import Path
import numpy as np

def analyze_episode(episode_dir, target_node):
    episode_dir = Path(episode_dir)

    # Load label
    with open(episode_dir / 'label.json') as f:
        label = json.load(f)

    fault_start = label['fault_start_time']
    fault_type = label['fault_type']
    print(f"Episode: {episode_dir.name}")
    print(f"Fault Type: {fault_type}")
    print(f"Ground Truth: {label['root_cause_node']}")
    print(f"Fault Start: {fault_start}s")
    print()

    # Load and analyze metrics
    baseline_metrics = {}
    fault_metrics = {}

    with open(episode_dir / 'metrics.jsonl') as f:
        for line in f:
            data = json.loads(line)
            labels = data.get('labels', {})

            # Extract component ID
            comp_id = (labels.get('component.id') or
                      labels.get('pod_name') or
                      labels.get('service_name'))

            # Check if this is our target or its pods
            if comp_id and (comp_id == target_node or comp_id.startswith(f'pod_{target_node}')):
                time = float(labels.get('sim.time', data.get('timestamp', 0)))
                metric_name = data['name']
                value = data.get('value')

                # Handle summary metrics
                if value is None and 'summary' in data:
                    summary = data['summary']
                    if 'duration' in metric_name or 'latency' in metric_name:
                        value = summary.get('p99', summary.get('mean'))
                    else:
                        value = summary.get('mean')

                if value is not None:
                    try:
                        value = float(value)

                        # Store in baseline or fault window
                        if time < fault_start:
                            if metric_name not in baseline_metrics:
                                baseline_metrics[metric_name] = []
                            baseline_metrics[metric_name].append(value)
                        else:
                            if metric_name not in fault_metrics:
                                fault_metrics[metric_name] = []
                            fault_metrics[metric_name].append(value)
                    except (ValueError, TypeError):
                        pass

    # Compare metrics
    print(f"\nMetrics for {target_node}:")
    print("=" * 80)

    all_metrics = set(baseline_metrics.keys()) | set(fault_metrics.keys())

    for metric in sorted(all_metrics):
        baseline_vals = baseline_metrics.get(metric, [])
        fault_vals = fault_metrics.get(metric, [])

        if baseline_vals and fault_vals:
            base_mean = np.mean(baseline_vals)
            fault_mean = np.mean(fault_vals)

            if base_mean > 0:
                ratio = fault_mean / base_mean
                change = fault_mean - base_mean

                if ratio > 1.2 or ratio < 0.8:  # Show significant changes
                    print(f"\n{metric}:")
                    print(f"  Baseline: {base_mean:.2f} (n={len(baseline_vals)})")
                    print(f"  Fault:    {fault_mean:.2f} (n={len(fault_vals)})")
                    print(f"  Change:   {change:+.2f} ({ratio:.2f}x)")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python debug_metrics.py <episode_dir> <node_id>")
        sys.exit(1)

    analyze_episode(sys.argv[1], sys.argv[2])
