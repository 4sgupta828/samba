#!/usr/bin/env python3
"""
Validate timing assumptions across all episodes.

Checks that our analysis time formula doesn't cause overlap with recovery period.
"""

import json
from pathlib import Path
from collections import defaultdict


def validate_episode_timing(episode_dir: Path) -> dict:
    """Validate timing for a single episode."""

    label_file = episode_dir / 'label.json'
    if not label_file.exists():
        return None

    with open(label_file) as f:
        label = json.load(f)

    # Extract timing
    fault_start = label.get('fault_start_time', 0)
    fault_full_effect = label.get('fault_full_effect_time', fault_start + label.get('fault_ramp_duration', 0))
    recovery_start = label.get('recovery_start_time', None)
    recovery_complete = label.get('recovery_complete_time', None)
    episode_end = label.get('timeline', {}).get('episode_end', 300)

    episode_duration = episode_end

    # Our formula
    baseline_window_size = episode_duration * 0.25
    current_window_size = episode_duration * 0.15
    propagation_time = baseline_window_size * 1.5
    analysis_time = fault_start + propagation_time

    # Current window bounds
    current_window_start = analysis_time - current_window_size
    current_window_end = analysis_time

    # Steady fault period
    steady_fault_start = fault_full_effect
    steady_fault_end = recovery_start if recovery_start else episode_end
    steady_fault_duration = steady_fault_end - steady_fault_start

    # Check for overlaps/issues
    issues = []

    # Issue 1: Current window overlaps with recovery
    if recovery_start and current_window_end > recovery_start:
        overlap = current_window_end - recovery_start
        issues.append(f"Current window overlaps recovery by {overlap:.1f}s")

    # Issue 2: Current window extends past episode
    if current_window_end > episode_end:
        issues.append(f"Current window extends {current_window_end - episode_end:.1f}s past episode end")

    # Issue 3: Current window is before fault_full_effect
    if current_window_start < fault_full_effect:
        issues.append(f"Current window starts before fault reaches full effect")

    # Issue 4: Steady fault period too short for current window
    if steady_fault_duration < current_window_size:
        issues.append(f"Steady fault period ({steady_fault_duration:.1f}s) < current window ({current_window_size:.1f}s)")

    # Check: How much of current window is in steady fault state?
    steady_overlap_start = max(current_window_start, steady_fault_start)
    steady_overlap_end = min(current_window_end, steady_fault_end)
    steady_overlap = max(0, steady_overlap_end - steady_overlap_start)
    steady_coverage = steady_overlap / current_window_size if current_window_size > 0 else 0

    return {
        'episode_id': episode_dir.parent.name,
        'fault_type': label.get('fault_type', 'unknown'),
        'episode_duration': episode_duration,
        'fault_start': fault_start,
        'fault_full_effect': fault_full_effect,
        'recovery_start': recovery_start,
        'steady_fault_duration': steady_fault_duration,
        'baseline_window': baseline_window_size,
        'current_window': current_window_size,
        'analysis_time': analysis_time,
        'current_window_bounds': (current_window_start, current_window_end),
        'steady_coverage_pct': steady_coverage * 100,
        'issues': issues,
        'is_valid': len(issues) == 0 and steady_coverage > 0.8  # At least 80% in steady state
    }


def validate_batch(batch_dir: Path):
    """Validate all episodes in a batch."""

    episode_dirs = sorted([
        d / 'ep_0' for d in batch_dir.iterdir()
        if d.is_dir() and (d / 'ep_0').exists()
    ])

    print("="*80)
    print("TIMING VALIDATION ACROSS ALL EPISODES")
    print("="*80)
    print(f"Checking {len(episode_dirs)} episodes...\n")

    results = []
    issues_by_type = defaultdict(list)

    for ep_dir in episode_dirs:
        result = validate_episode_timing(ep_dir)
        if result:
            results.append(result)

            status = "✓" if result['is_valid'] else "✗"

            print(f"{status} {result['episode_id']} ({result['fault_type']})")
            print(f"  Episode: {result['episode_duration']:.0f}s | "
                  f"Steady fault: {result['fault_full_effect']:.0f}s - {result['recovery_start']:.0f}s "
                  f"({result['steady_fault_duration']:.0f}s)")
            print(f"  Analysis: {result['analysis_time']:.1f}s | "
                  f"Current window: {result['current_window_bounds'][0]:.1f}s - {result['current_window_bounds'][1]:.1f}s")
            print(f"  Steady coverage: {result['steady_coverage_pct']:.1f}% of current window")

            if result['issues']:
                for issue in result['issues']:
                    print(f"  ⚠️  {issue}")
                    issues_by_type[issue.split()[0]].append(result)
            print()

    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total episodes: {len(results)}")
    print(f"Valid (no issues, >80% steady coverage): {sum(1 for r in results if r['is_valid'])}")
    print(f"With issues: {sum(1 for r in results if not r['is_valid'])}")
    print()

    # Coverage statistics
    coverages = [r['steady_coverage_pct'] for r in results]
    print(f"Steady fault coverage (% of current window):")
    print(f"  Mean: {sum(coverages)/len(coverages):.1f}%")
    print(f"  Min:  {min(coverages):.1f}%")
    print(f"  Max:  {max(coverages):.1f}%")
    print()

    # Issue breakdown
    if issues_by_type:
        print("Issues found:")
        for issue_type, cases in sorted(issues_by_type.items()):
            print(f"  {issue_type}: {len(cases)} episodes")
        print()

    # Check if formula needs adjustment
    needs_adjustment = sum(1 for r in results if r['steady_coverage_pct'] < 80)
    if needs_adjustment > 0:
        print(f"⚠️  {needs_adjustment} episodes have <80% steady coverage")
        print("Consider adjusting formula:")
        print("  - Reduce propagation_time multiplier (currently 1.5x)")
        print("  - Reduce current_window_pct (currently 0.15)")
        print()
    else:
        print("✓ All episodes have sufficient steady fault coverage!")
        print()

    # Recommendations
    print("="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    # Find optimal propagation multiplier
    optimal_multipliers = []
    for r in results:
        # What multiplier would center current window in steady fault?
        steady_mid = (r['fault_full_effect'] + r['recovery_start']) / 2
        optimal_analysis = steady_mid
        optimal_propagation = optimal_analysis - r['fault_start']
        optimal_multiplier = optimal_propagation / r['baseline_window'] if r['baseline_window'] > 0 else 1.0
        optimal_multipliers.append(optimal_multiplier)

    avg_optimal = sum(optimal_multipliers) / len(optimal_multipliers)
    print(f"Current multiplier: 1.5x baseline_window")
    print(f"Optimal multiplier (centers in steady fault): {avg_optimal:.2f}x")
    print()

    if avg_optimal < 1.3:
        print("⚠️  Recommendation: Reduce multiplier to ~1.2x to better fit steady fault period")
    elif avg_optimal > 1.7:
        print("⚠️  Recommendation: Increase multiplier to ~1.8x to better fit steady fault period")
    else:
        print("✓ Current multiplier (1.5x) is appropriate")

    return results


if __name__ == "__main__":
    batch_dir = Path("data/batch_run_20251218_133824")

    if batch_dir.exists():
        results = validate_batch(batch_dir)
    else:
        print(f"Batch directory not found: {batch_dir}")
