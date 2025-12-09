#!/usr/bin/env python3
"""
Analyze batch RCA discovery results.

Generates comprehensive statistics and insights from all processed episodes.
"""

import json
from pathlib import Path
from collections import defaultdict, Counter


def analyze_results(base_dir='data/batch_run'):
    """Analyze all RCA results in the directory."""
    base_path = Path(base_dir)

    # Collect all markers
    markers = list(base_path.rglob('RCAInvestigated.marker'))

    if not markers:
        print(f"No RCA markers found in {base_dir}")
        return

    # Load all results
    results = []
    for marker_file in sorted(markers):
        try:
            with open(marker_file) as f:
                data = json.load(f)

            # Load corresponding label for fault type
            label_file = marker_file.parent / 'label.json'
            if label_file.exists():
                with open(label_file) as f:
                    label = json.load(f)
                data['fault_type'] = label.get('fault_type', 'unknown')
                data['root_cause_role'] = label.get('root_cause_role', 'unknown')
            else:
                data['fault_type'] = 'unknown'
                data['root_cause_role'] = 'unknown'

            results.append(data)
        except Exception as e:
            print(f"Error loading {marker_file}: {e}")

    # Overall statistics
    print("="*80)
    print("BATCH RCA DISCOVERY RESULTS")
    print("="*80)
    print(f"Total episodes analyzed: {len(results)}")
    print()

    # Success rate
    successes = [r for r in results if r.get('success') == True]
    failures = [r for r in results if r.get('success') in [False, None]]

    print(f"✅ Successes (found in top-{results[0].get('top_k', 5)}): {len(successes)} ({len(successes)/len(results)*100:.1f}%)")
    print(f"❌ Failures (not in top-{results[0].get('top_k', 5)}): {len(failures)} ({len(failures)/len(results)*100:.1f}%)")
    print()

    # Detailed rank distribution
    print("Rank Distribution (where ground truth was found):")
    print("-" * 60)
    rank_counts = Counter(r['rank'] for r in successes if r.get('rank'))
    for rank in sorted(rank_counts.keys()):
        count = rank_counts[rank]
        percentage = count/len(successes)*100
        bar = '█' * int(percentage / 5)  # Visual bar
        print(f"  🥇 Rank {rank}: {count:2d} episodes ({percentage:4.1f}%) {bar}")

    # Show examples for each rank
    print("\n  Examples by rank:")
    for rank in sorted(rank_counts.keys()):
        examples = [r for r in successes if r.get('rank') == rank][:3]
        print(f"    Rank {rank}: {', '.join(e['ground_truth'] for e in examples)}")
    print()

    # Average confidence
    if successes:
        avg_confidence = sum(r['confidence'] for r in successes if r.get('confidence')) / len(successes)
        print(f"Average confidence (successes): {avg_confidence:.3f}")
        print()

    # Success by fault type
    print("Success Rate by Fault Type:")
    by_fault_type = defaultdict(lambda: {'total': 0, 'success': 0})
    for r in results:
        ft = r['fault_type']
        by_fault_type[ft]['total'] += 1
        if r.get('success') == True:
            by_fault_type[ft]['success'] += 1

    for ft in sorted(by_fault_type.keys()):
        stats = by_fault_type[ft]
        rate = stats['success'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"  {ft}: {stats['success']}/{stats['total']} ({rate:.1f}%)")
    print()

    # Success by root cause role
    print("Success Rate by Root Cause Role:")
    by_role = defaultdict(lambda: {'total': 0, 'success': 0})
    for r in results:
        role = r['root_cause_role']
        by_role[role]['total'] += 1
        if r.get('success') == True:
            by_role[role]['success'] += 1

    for role in sorted(by_role.keys()):
        stats = by_role[role]
        rate = stats['success'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"  {role}: {stats['success']}/{stats['total']} ({rate:.1f}%)")
    print()

    # Most common false positives (top-1 when ground truth not found)
    print("Most Common False Positives (top-1 candidates):")
    false_positive_top1 = Counter(
        r['top_k_candidates'][0] if r.get('top_k_candidates') else 'none'
        for r in failures
    )
    for candidate, count in false_positive_top1.most_common(10):
        print(f"  {candidate}: {count} times")
    print()

    # Cases where ground truth was close but not in top-K
    print("Near Misses (ground truth detected but not in top-K):")
    near_misses = [r for r in failures if r.get('rank') and r['rank'] > r.get('top_k', 5)]
    if near_misses:
        for r in near_misses[:10]:
            print(f"  {r['ground_truth']} at rank {r['rank']} (top-{r['top_k']})")
    else:
        print("  None - ground truth either in top-K or not detected at all")
    print()

    # Average candidates found
    avg_candidates = sum(r['total_candidates'] for r in results) / len(results)
    print(f"Average candidates found per episode: {avg_candidates:.1f}")
    print()

    # Detailed failure analysis
    print("="*80)
    print("FAILURE ANALYSIS")
    print("="*80)
    print(f"Total failures to analyze: {len(failures)}")
    print()

    # Group failures by ground truth
    print("Failures by Ground Truth Component:")
    failure_by_gt = Counter(r['ground_truth'] for r in failures)
    for gt, count in failure_by_gt.most_common(15):
        print(f"  {gt}: {count} times")
    print()

    # Check if it's a detection issue (not enough candidates)
    low_candidates = [r for r in results if r['total_candidates'] < r.get('top_k', 5)]
    if low_candidates:
        print(f"⚠️  {len(low_candidates)} episodes had fewer candidates than top-K:")
        print(f"   Average: {sum(r['total_candidates'] for r in low_candidates) / len(low_candidates):.1f} candidates")
        print(f"   This limits the potential success rate")

    print()

    # Detailed success list
    print("="*80)
    print("DETAILED SUCCESS LIST")
    print("="*80)
    print(f"All {len(successes)} successful RCA detections:\n")

    # Group by rank
    for rank in sorted(rank_counts.keys()):
        rank_successes = [r for r in successes if r.get('rank') == rank]
        print(f"{'='*60}")
        print(f"Rank {rank} ({len(rank_successes)} episodes):")
        print(f"{'='*60}")

        for i, r in enumerate(sorted(rank_successes, key=lambda x: x.get('confidence', 0), reverse=True), 1):
            print(f"  {i}. Ground Truth: {r['ground_truth']}")
            print(f"     Fault Type: {r['fault_type']}")
            print(f"     Confidence: {r.get('confidence', 0):.3f}")
            print(f"     Top-{r.get('top_k', 5)} Candidates: {', '.join(r.get('top_k_candidates', []))}")
            print()

    print()
    print("="*80)


if __name__ == "__main__":
    import sys
    base_dir = sys.argv[1] if len(sys.argv) > 1 else 'data/batch_run'
    analyze_results(base_dir)
