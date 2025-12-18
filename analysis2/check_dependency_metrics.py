#!/usr/bin/env python3
"""Check if dependency metrics exist in processed data."""

import sys
import pandas as pd
from pathlib import Path
import json

sys.path.insert(0, '/Users/sgupta/samba/analysis2')
from run_rca_batch import DatasetAdapter, METRIC_MAP

def check_metrics(episode_dir):
    """Check what metrics are available after processing."""
    ep_path = Path(episode_dir)

    # Create adapter
    adapter = DatasetAdapter(ep_path)

    # Get processed data
    baseline_pods, current_pods = adapter.get_data_windows()
    baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
    current_services = adapter.aggregate_pods_to_services(current_pods)

    print(f"{'='*80}")
    print(f"SERVICE-LEVEL METRICS")
    print(f"{'='*80}\n")

    # Check a few services
    for svc_id in list(baseline_services.keys())[:5]:
        metrics = list(baseline_services[svc_id].keys())
        print(f"Service: {svc_id}")
        print(f"  Metrics ({len(metrics)}):")
        for m in sorted(metrics):
            print(f"    - {m}")
        print()

    # Check for dependency metrics
    print(f"\n{'='*80}")
    print("DEPENDENCY METRICS CHECK:")
    print(f"{'='*80}\n")

    has_dep_lat = False
    has_dep_err = False
    has_out_rps = False

    for svc_id, metrics in baseline_services.items():
        if 'dependency_latency' in metrics:
            has_dep_lat = True
            print(f"✓ {svc_id} has dependency_latency")
        if 'dependency_error_rate' in metrics:
            has_dep_err = True
            print(f"✓ {svc_id} has dependency_error_rate")
        if 'outbound_rps' in metrics:
            has_out_rps = True
            print(f"✓ {svc_id} has outbound_rps")

    print(f"\n{'='*80}")
    print("SUMMARY:")
    print(f"{'='*80}")
    print(f"  dependency_latency: {'✓ FOUND' if has_dep_lat else '✗ MISSING'}")
    print(f"  dependency_error_rate: {'✓ FOUND' if has_dep_err else '✗ MISSING'}")
    print(f"  outbound_rps: {'✓ FOUND' if has_out_rps else '✗ MISSING'}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python check_dependency_metrics.py <episode_directory>")
        sys.exit(1)

    check_metrics(sys.argv[1])
