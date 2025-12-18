#!/usr/bin/env python3
"""Debug propagation physics for a specific failed case."""

import json
import sys
import pickle
import numpy as np
from pathlib import Path

def debug_case(episode_dir):
    """Debug propagation physics for a specific episode."""
    ep_path = Path(episode_dir)

    # Load RCA analysis
    rca_file = ep_path / "rca_analysis.json"
    if not rca_file.exists():
        print(f"No RCA analysis found at {rca_file}")
        return

    with open(rca_file) as f:
        rca_data = json.load(f)

    gt = rca_data['ground_truth']
    rank = rca_data.get('rank')

    print(f"{'='*80}")
    print(f"DEBUGGING EPISODE: {episode_dir}")
    print(f"Ground Truth: {gt}")
    print(f"Rank: {rank}")
    print(f"{'='*80}\n")

    # Load baseline and current data
    baseline_file = ep_path / "baseline_data.pkl"
    current_file = ep_path / "current_data.pkl"

    if not baseline_file.exists() or not current_file.exists():
        print(f"Missing baseline or current data files")
        return

    with open(baseline_file, 'rb') as f:
        baseline_data = pickle.load(f)

    with open(current_file, 'rb') as f:
        current_data = pickle.load(f)

    # Load topology
    import networkx as nx
    topology_file = ep_path / "topology.pkl"
    if not topology_file.exists():
        print(f"Missing topology file")
        return

    with open(topology_file, 'rb') as f:
        topology = pickle.load(f)

    # Helper functions
    def get_mean(d, n, m):
        vals = d.get(n, {}).get(m, [])
        return np.mean(vals) if len(vals) > 0 else 0.0

    def calc_growth(b, c):
        return (c + 0.01) / (b + 0.01)

    # Find all callers of ground truth
    callers = list(topology.predecessors(gt)) if gt in topology.nodes() else []

    print(f"Ground Truth Node: {gt}")
    print(f"Number of callers: {len(callers)}\n")

    # Check GT metrics
    gt_lat_base = get_mean(baseline_data, gt, 'avg_latency')
    gt_lat_curr = get_mean(current_data, gt, 'avg_latency')
    gt_lat_growth = calc_growth(gt_lat_base, gt_lat_curr)

    gt_err_base = get_mean(baseline_data, gt, 'internal_error_rate')
    gt_err_curr = get_mean(current_data, gt, 'internal_error_rate')
    gt_err_delta = gt_err_curr - gt_err_base

    print(f"Ground Truth Metrics:")
    print(f"  Latency: {gt_lat_base:.3f}s -> {gt_lat_curr:.3f}s (growth: {gt_lat_growth:.2f}x)")
    print(f"  Error Rate: {gt_err_base:.1%} -> {gt_err_curr:.1%} (delta: {gt_err_delta:+.1%})")
    print()

    # Check propagation to callers
    print(f"Propagation Analysis:")
    print(f"{'='*80}\n")

    for caller in callers[:10]:  # Limit to first 10 callers
        caller_dep_base = get_mean(baseline_data, caller, 'dependency_latency')
        caller_dep_curr = get_mean(current_data, caller, 'dependency_latency')
        caller_dep_growth = calc_growth(caller_dep_base, caller_dep_curr)

        caller_dep_err_base = get_mean(baseline_data, caller, 'dependency_error_rate')
        caller_dep_err_curr = get_mean(current_data, caller, 'dependency_error_rate')
        caller_dep_err_delta = caller_dep_err_curr - caller_dep_err_base

        # Check latency propagation
        MIN_LATENCY_GROWTH = 1.2
        LATENCY_DILUTION_FACTOR = 0.2

        latency_match = False
        error_match = False

        if gt_lat_growth > MIN_LATENCY_GROWTH:
            required_growth = 1.0 + ((gt_lat_growth - 1.0) * LATENCY_DILUTION_FACTOR)
            latency_match = caller_dep_growth > required_growth

        if gt_err_delta > 0.01 and caller_dep_err_delta > 0:
            error_match = True

        status = "✅" if (latency_match or error_match) else "❌"

        print(f"{status} {caller:30}")
        print(f"  Dependency Latency: {caller_dep_base:.3f}s -> {caller_dep_curr:.3f}s (growth: {caller_dep_growth:.2f}x)")
        print(f"  Dependency Error Rate: {caller_dep_err_base:.1%} -> {caller_dep_err_curr:.1%} (delta: {caller_dep_err_delta:+.1%})")

        if gt_lat_growth > MIN_LATENCY_GROWTH:
            required_growth = 1.0 + ((gt_lat_growth - 1.0) * LATENCY_DILUTION_FACTOR)
            print(f"  Latency Check: GT={gt_lat_growth:.2f}x, Required={required_growth:.2f}x, Actual={caller_dep_growth:.2f}x {'✅' if latency_match else '❌'}")

        if gt_err_delta > 0.01:
            print(f"  Error Check: GT_delta={gt_err_delta:+.1%}, Caller_delta={caller_dep_err_delta:+.1%} {'✅' if error_match else '❌'}")

        print()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python debug_propagation.py <episode_directory>")
        print("Example: python debug_propagation.py ../data/batch_run_20251217_234356/data_20251217_234450/ep_0")
        sys.exit(1)

    debug_case(sys.argv[1])
