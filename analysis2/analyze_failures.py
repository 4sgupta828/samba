#!/usr/bin/env python3
"""Analyze failed RCA cases to understand propagation patterns."""

import json
import sys
from pathlib import Path

def analyze_failures(batch_dir):
    """Analyze all failed RCA cases."""
    batch_path = Path(batch_dir)

    failed_cases = []

    for data_dir in sorted(batch_path.glob("data_*/ep_0")):
        rca_file = data_dir / "rca_analysis.json"
        if not rca_file.exists():
            continue

        with open(rca_file) as f:
            data = json.load(f)

        gt = data['ground_truth']
        rank = data.get('rank')

        if rank != 1:
            # Find ground truth candidate
            candidates = data.get('all_candidates', [])
            gt_cand = [c for c in candidates if c['node'] == gt]

            if gt_cand:
                gt_info = gt_cand[0]
                failed_cases.append({
                    'episode': data_dir.parent.name,
                    'ground_truth': gt,
                    'rank': rank,
                    'score': gt_info['score'],
                    'physics_coverage': gt_info.get('physics_coverage', 0),
                    'primary_symptom_bonus': gt_info.get('primary_symptom_bonus', 0),
                    'breakdown': gt_info.get('scoring_breakdown', {}),
                    'top_candidate': data['top_candidates'][0]['node'] if data.get('top_candidates') else 'N/A',
                    'top_score': data['top_candidates'][0]['score'] if data.get('top_candidates') else 0
                })
            else:
                failed_cases.append({
                    'episode': data_dir.parent.name,
                    'ground_truth': gt,
                    'rank': rank,
                    'score': 0,
                    'physics_coverage': 0,
                    'primary_symptom_bonus': 0,
                    'breakdown': {},
                    'top_candidate': data['top_candidates'][0]['node'] if data.get('top_candidates') else 'N/A',
                    'top_score': data['top_candidates'][0]['score'] if data.get('top_candidates') else 0,
                    'note': 'GT not in candidates'
                })

    # Print summary
    print(f"\n{'='*80}")
    print(f"FAILED CASES ANALYSIS ({len(failed_cases)} cases)")
    print(f"{'='*80}\n")

    for case in failed_cases:
        print(f"Episode: {case['episode']}")
        rank_str = str(case['rank']) if case['rank'] is not None else 'N/A'
        print(f"  GT: {case['ground_truth']:30} Rank: {rank_str:>4}")
        print(f"  GT Score: {case['score']:6.1f} (Physics: {case['physics_coverage']:5.1f}, Primary: {case['primary_symptom_bonus']:5.1f})")
        print(f"  Top: {case['top_candidate']:30} Score: {case['top_score']:6.1f}")

        if case.get('breakdown'):
            bd = case['breakdown']
            print(f"  Breakdown:")
            print(f"    Pod anomalies: {bd.get('pod_anomalies', 0):.1f}")
            print(f"    Service anomalies: {bd.get('service_anomalies', 0):.1f}")
            print(f"    Physics coverage: {bd.get('physics_coverage', 0):.1f}")
            print(f"    Primary bonus: {bd.get('primary_symptom_bonus', 0):.1f}")
            print(f"    Downstream impact: {bd.get('downstream_impact', 0):.1f}")

        if case.get('note'):
            print(f"  NOTE: {case['note']}")
        print()

    # Summary statistics
    print(f"\n{'='*80}")
    print("SUMMARY STATISTICS")
    print(f"{'='*80}\n")

    zero_physics = [c for c in failed_cases if c['physics_coverage'] == 0]
    print(f"Cases with zero physics coverage: {len(zero_physics)}/{len(failed_cases)}")

    if zero_physics:
        print(f"\nZero physics cases:")
        for case in zero_physics:
            print(f"  - {case['ground_truth']:30} (Rank {case['rank']})")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python analyze_failures.py <batch_run_directory>")
        sys.exit(1)

    analyze_failures(sys.argv[1])
