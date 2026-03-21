#!/usr/bin/env python3
"""
Run RCA on all episodes with new time windows and compare with old results.

Evaluates:
- Ground truth ranking improvements
- False positive reductions
- Any regressions
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, 'analysis2')

from run_rca_batch import DatasetAdapter
from whitebox_rca import WhiteboxRCAEngine


def run_rca_on_episode(episode_dir: Path, use_new_windows: bool = True):
    """Run RCA on a single episode."""

    # Load data
    adapter = DatasetAdapter(episode_dir)

    # Get data windows
    if use_new_windows:
        baseline_pods, current_pods = adapter.get_data_windows()
    else:
        # Old approach: everything from fault_start onwards
        import pandas as pd

        fault_start = adapter.label.get('fault_start_time', 0)
        base_df = adapter.metrics_df[adapter.metrics_df['sim_time'] < fault_start]
        curr_df = adapter.metrics_df[adapter.metrics_df['sim_time'] >= fault_start]

        baseline_pods = adapter._process_window(base_df)
        current_pods = adapter._process_window(curr_df)

    # Aggregate pod metrics to service level
    baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
    current_services = adapter.aggregate_pods_to_services(current_pods)

    # Run RCA with both service and pod data
    engine = WhiteboxRCAEngine(adapter.topology)

    rankings = engine.analyze_incident(
        baseline_data=baseline_services,
        current_data=current_services,
        metrics_df=adapter.metrics_df,
        fault_start_time=adapter.label.get('fault_start_time'),
        traces_file=None,
        logs_file=None,
        baseline_pods=baseline_pods,  # Now passing pod data for coverage filtering
        current_pods=current_pods
    )

    # Find ground truth rank
    ground_truth = adapter.label.get('root_cause_node', 'unknown')
    gt_rank = None
    gt_score = None

    for i, candidate in enumerate(rankings, 1):
        if candidate['node'] == ground_truth:
            gt_rank = i
            gt_score = candidate['score']
            break

    # Count false positives ranking higher
    false_positives_higher = []
    if gt_rank:
        for candidate in rankings[:gt_rank-1]:
            if candidate['node'] != ground_truth:
                false_positives_higher.append({
                    'node': candidate['node'],
                    'rank': rankings.index(candidate) + 1,
                    'score': candidate['score'],
                    'self_score': candidate.get('self_score', 0),
                    'integrated_score': candidate.get('integrated_score', 0)
                })

    return {
        'episode_id': episode_dir.parent.name,
        'fault_type': adapter.label.get('fault_type', 'unknown'),
        'ground_truth': ground_truth,
        'gt_rank': gt_rank,
        'gt_score': gt_score,
        'top_k': len(rankings),
        'false_positives_higher': false_positives_higher,
        'rankings': rankings[:5]  # Store top 5 for analysis
    }


def compare_results(batch_dir: Path, old_results_file: Path = None):
    """Run RCA with new windows and compare with old results."""

    episode_dirs = sorted([
        d / 'ep_0' for d in batch_dir.iterdir()
        if d.is_dir() and (d / 'ep_0').exists()
    ])

    print("="*80)
    print("COMPREHENSIVE RCA EVALUATION")
    print("="*80)
    print(f"Running RCA on {len(episode_dirs)} episodes with NEW time windows...")
    print()

    new_results = []

    for i, ep_dir in enumerate(episode_dirs, 1):
        print(f"[{i}/{len(episode_dirs)}] Processing {ep_dir.parent.name}...")

        try:
            result = run_rca_on_episode(ep_dir, use_new_windows=True)
            new_results.append(result)

            status = "✓" if result['gt_rank'] == 1 else f"✗ (rank {result['gt_rank']})"
            fp_count = len(result['false_positives_higher'])

            print(f"  {status} {result['fault_type']}: Ground truth '{result['ground_truth']}'")
            if fp_count > 0:
                print(f"    ⚠️  {fp_count} false positives rank higher")
            print()

        except Exception as e:
            print(f"  ✗ Error: {e}")
            print()

    # Load old results if available
    old_results = None
    if old_results_file and old_results_file.exists():
        print(f"Loading old results from {old_results_file}...")
        with open(old_results_file) as f:
            old_results = json.load(f)
        print()

    # Analysis
    print("="*80)
    print("RESULTS SUMMARY")
    print("="*80)

    # Overall metrics
    total = len(new_results)

    if total == 0:
        print("\n⚠️  No results to analyze")
        return new_results

    rank_1 = sum(1 for r in new_results if r['gt_rank'] == 1)
    in_top_3 = sum(1 for r in new_results if r['gt_rank'] and r['gt_rank'] <= 3)
    in_top_5 = sum(1 for r in new_results if r['gt_rank'] and r['gt_rank'] <= 5)
    not_found = sum(1 for r in new_results if r['gt_rank'] is None)

    print(f"\nNew Results (with improved time windows):")
    print(f"  Total episodes:     {total}")
    print(f"  Ground truth @ 1:   {rank_1} ({rank_1/total*100:.1f}%)")
    print(f"  Ground truth @ 3:   {in_top_3} ({in_top_3/total*100:.1f}%)")
    print(f"  Ground truth @ 5:   {in_top_5} ({in_top_5/total*100:.1f}%)")
    print(f"  Not in top-k:       {not_found}")

    # MRR (Mean Reciprocal Rank)
    reciprocal_ranks = [1/r['gt_rank'] if r['gt_rank'] else 0 for r in new_results]
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    print(f"  MRR:                {mrr:.3f}")

    # False positives analysis
    total_fps = sum(len(r['false_positives_higher']) for r in new_results)
    episodes_with_fps = sum(1 for r in new_results if len(r['false_positives_higher']) > 0)

    print(f"\nFalse Positives:")
    print(f"  Episodes with FPs:  {episodes_with_fps} ({episodes_with_fps/total*100:.1f}%)")
    print(f"  Total FP instances: {total_fps}")
    if episodes_with_fps > 0:
        print(f"  Avg FPs per episode: {total_fps/episodes_with_fps:.1f}")

    # Comparison with old results
    if old_results:
        print("\n" + "="*80)
        print("COMPARISON: New vs Old")
        print("="*80)

        # Map old results by episode_id
        old_by_id = {r['episode_id']: r for r in old_results if 'episode_id' in r}

        improvements = []
        regressions = []
        unchanged = []

        for new_r in new_results:
            ep_id = new_r['episode_id']
            if ep_id in old_by_id:
                old_r = old_by_id[ep_id]
                old_rank = old_r.get('gt_rank')
                new_rank = new_r['gt_rank']

                if old_rank and new_rank:
                    if new_rank < old_rank:
                        improvements.append({
                            'episode': ep_id,
                            'fault_type': new_r['fault_type'],
                            'old_rank': old_rank,
                            'new_rank': new_rank,
                            'improvement': old_rank - new_rank
                        })
                    elif new_rank > old_rank:
                        regressions.append({
                            'episode': ep_id,
                            'fault_type': new_r['fault_type'],
                            'old_rank': old_rank,
                            'new_rank': new_rank,
                            'regression': new_rank - old_rank
                        })
                    else:
                        unchanged.append(ep_id)

        print(f"\nRank Changes:")
        print(f"  Improvements: {len(improvements)}")
        print(f"  Regressions:  {len(regressions)}")
        print(f"  Unchanged:    {len(unchanged)}")

        if improvements:
            print(f"\n✓ Improvements:")
            for imp in improvements:
                print(f"  {imp['episode']} ({imp['fault_type']}): "
                      f"rank {imp['old_rank']} → {imp['new_rank']} "
                      f"(+{imp['improvement']})")

        if regressions:
            print(f"\n✗ Regressions:")
            for reg in regressions:
                print(f"  {reg['episode']} ({reg['fault_type']}): "
                      f"rank {reg['old_rank']} → {reg['new_rank']} "
                      f"(-{reg['regression']})")

    # By fault type
    print("\n" + "="*80)
    print("BREAKDOWN BY FAULT TYPE")
    print("="*80)

    by_fault = defaultdict(lambda: {'total': 0, 'rank_1': 0, 'fps': 0})
    for r in new_results:
        ft = r['fault_type']
        by_fault[ft]['total'] += 1
        if r['gt_rank'] == 1:
            by_fault[ft]['rank_1'] += 1
        by_fault[ft]['fps'] += len(r['false_positives_higher'])

    print(f"\n{'Fault Type':<25} {'Total':>6} {'@Rank1':>8} {'FPs':>6}")
    print("-"*50)
    for ft in sorted(by_fault.keys()):
        stats = by_fault[ft]
        print(f"{ft:<25} {stats['total']:>6} {stats['rank_1']:>8} {stats['fps']:>6}")

    # Save results
    output_file = batch_dir / "rca_evaluation_new_windows.json"
    with open(output_file, 'w') as f:
        json.dump(new_results, f, indent=2)

    print(f"\n✓ Results saved to: {output_file}")

    return new_results


if __name__ == "__main__":
    batch_dir = Path("data/batch_run_20251218_133824")

    # Check if old results exist for comparison
    old_results_file = batch_dir / "batch_results_results.json"

    if batch_dir.exists():
        results = compare_results(batch_dir, old_results_file)
    else:
        print(f"Batch directory not found: {batch_dir}")
