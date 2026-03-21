"""
Debug script to test pod-to-service aggregation for tenant_service.
"""

import sys
import json
import numpy as np
from pathlib import Path
from run_rca_batch import DatasetAdapter

if __name__ == "__main__":
    episode_dir = Path("../data/batch_run/data_20251215_015616/ep_0")

    print(f"Loading data from: {episode_dir}")

    # Load data
    adapter = DatasetAdapter(episode_dir)
    baseline_pods, current_pods = adapter.get_data_windows()

    print(f"\n{'='*80}")
    print("BASELINE POD DATA")
    print(f"{'='*80}")
    print(f"Total nodes with metrics: {len(baseline_pods)}")

    # Check tenant_service pods
    tenant_pods = [k for k in baseline_pods.keys() if 'tenant_service' in k]
    print(f"\nTenant service related nodes: {len(tenant_pods)}")
    for pod in sorted(tenant_pods):
        metrics = baseline_pods[pod]
        print(f"  {pod}: {list(metrics.keys())}")
        if 'internal_error_rate' in metrics:
            print(f"    -> internal_error_rate: {metrics['internal_error_rate'][:5]}")

    print(f"\n{'='*80}")
    print("AGGREGATED SERVICE DATA")
    print(f"{'='*80}")

    # Aggregate to service level
    baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
    current_services = adapter.aggregate_pods_to_services(current_pods)

    print(f"Total services with metrics: {len(baseline_services)}")

    # Check tenant_service
    if 'tenant_service' in baseline_services:
        print(f"\n✅ tenant_service found in aggregated data")
        print(f"   Metrics: {list(baseline_services['tenant_service'].keys())}")

        for metric_name, values in baseline_services['tenant_service'].items():
            print(f"   - {metric_name}: {len(values)} values, mean={np.mean(values):.4f}")

        # Check for error rate specifically
        if 'internal_error_rate' in baseline_services['tenant_service']:
            print(f"\n   ✅ internal_error_rate present!")
            baseline_errors = baseline_services['tenant_service']['internal_error_rate']
            current_errors = current_services['tenant_service']['internal_error_rate']
            print(f"      Baseline mean: {np.mean(baseline_errors):.4f}")
            print(f"      Current mean:  {np.mean(current_errors):.4f}")
            print(f"      Increase: {np.mean(current_errors) / np.mean(baseline_errors):.2f}x")
        else:
            print(f"\n   ❌ internal_error_rate MISSING!")
    else:
        print(f"\n❌ tenant_service NOT FOUND in aggregated data")
        print(f"   Available services: {list(baseline_services.keys())[:10]}")
