#!/usr/bin/env python3
"""Inspect available metrics in an episode to debug propagation issues."""

import sys
import json
from pathlib import Path
from collections import defaultdict

def inspect_metrics(episode_dir):
    """Inspect what metrics are available."""
    ep_path = Path(episode_dir)
    metrics_file = ep_path / "metrics.jsonl"

    if not metrics_file.exists():
        print(f"No metrics file found at {metrics_file}")
        return

    # Collect unique metric names per component
    component_metrics = defaultdict(set)

    with open(metrics_file) as f:
        for i, line in enumerate(f):
            if i >= 10000:  # Limit to first 10k lines
                break
            try:
                entry = json.loads(line)
                # Try to get component_id from labels
                labels = entry.get('labels', {})
                component_id = labels.get('component.id', entry.get('component_id', 'unknown'))
                metric_name = entry.get('name', 'unknown')
                component_metrics[component_id].add(metric_name)
            except:
                continue

    # Print summary
    print(f"{'='*80}")
    print(f"METRICS INSPECTION: {episode_dir}")
    print(f"{'='*80}\n")

    # Show a few example components
    for comp_id in sorted(component_metrics.keys())[:5]:
        print(f"Component: {comp_id}")
        print(f"  Metrics ({len(component_metrics[comp_id])}):")
        for metric in sorted(component_metrics[comp_id])[:15]:
            print(f"    - {metric}")
        print()

    # Check for specific metrics we use in propagation
    print(f"\n{'='*80}")
    print("PROPAGATION METRICS CHECK:")
    print(f"{'='*80}\n")

    key_metrics = [
        'avg_latency',
        'dependency_latency',
        'internal_error_rate',
        'dependency_error_rate',
        'inbound_rps',
        'outbound_rps'
    ]

    # Pick a service component to check
    service_comps = [c for c in component_metrics.keys() if 'svc_' in c or 'service' in c]
    if service_comps:
        comp = service_comps[0]
        print(f"Checking component: {comp}")
        print(f"Available metrics:")
        for metric in sorted(component_metrics[comp]):
            marker = "  ✓" if metric in key_metrics else "   "
            print(f"{marker} {metric}")

        print(f"\n\nKey metrics presence:")
        for metric in key_metrics:
            present = any(metric in component_metrics[c] for c in component_metrics)
            marker = "✓" if present else "✗"
            print(f"  {marker} {metric}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python inspect_metrics.py <episode_directory>")
        print("Example: python inspect_metrics.py ../data/batch_run_20251217_234356/data_20251217_234450/ep_0")
        sys.exit(1)

    inspect_metrics(sys.argv[1])
