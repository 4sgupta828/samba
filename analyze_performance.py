#!/usr/bin/env python3
"""Analyze performance timing data from generated episodes."""

import json
import sys
from pathlib import Path
from collections import defaultdict

def analyze_performance(data_dir):
    """Analyze performance timing data from all episodes in a directory."""

    data_path = Path(data_dir)

    # Find all episode directories
    episode_dirs = sorted([d for d in data_path.glob("ep_*") if d.is_dir()])

    if not episode_dirs:
        print(f"No episode directories found in {data_dir}")
        return

    print(f"Found {len(episode_dirs)} episodes in {data_dir}")
    print(f"{'='*80}")

    # Collect timing data
    all_timings = defaultdict(list)
    episodes_with_timing = 0

    for ep_dir in episode_dirs:
        timing_file = ep_dir / "performance_timing.json"
        if timing_file.exists():
            with open(timing_file) as f:
                timings = json.load(f)
                episodes_with_timing += 1
                for phase, duration in timings.items():
                    all_timings[phase].append(duration)

    if episodes_with_timing == 0:
        print("No performance timing data found.")
        print("Make sure you're running with the updated generate_dataset.py")
        return

    print(f"Analyzed {episodes_with_timing} episodes with timing data\n")

    # Calculate statistics
    print(f"{'='*80}")
    print(f"PERFORMANCE TIMING SUMMARY (all {episodes_with_timing} episodes)")
    print(f"{'='*80}")
    print(f"{'Phase':<25} {'Min':>8} {'Avg':>8} {'Max':>8} {'Avg %':>8}")
    print(f"{'-'*80}")

    # Get average total for percentage calculation
    avg_total = sum(all_timings['total']) / len(all_timings['total']) if 'total' in all_timings else 0

    # Sort phases by average duration (descending)
    phases = [(phase, sum(durations) / len(durations))
              for phase, durations in all_timings.items() if phase != 'total']
    phases.sort(key=lambda x: x[1], reverse=True)

    for phase, avg_duration in phases:
        durations = all_timings[phase]
        min_dur = min(durations)
        max_dur = max(durations)
        avg_pct = (avg_duration / avg_total * 100) if avg_total > 0 else 0

        print(f"{phase:<25} {min_dur:>7.2f}s {avg_duration:>7.2f}s {max_dur:>7.2f}s {avg_pct:>7.1f}%")

    if 'total' in all_timings:
        durations = all_timings['total']
        print(f"{'-'*80}")
        print(f"{'TOTAL':<25} {min(durations):>7.2f}s {avg_total:>7.2f}s {max(durations):>7.2f}s {'100.0':>7s}%")

    print(f"{'='*80}\n")

    # Identify bottlenecks
    print("BOTTLENECK ANALYSIS")
    print(f"{'-'*80}")

    for phase, avg_duration in phases[:3]:
        avg_pct = (avg_duration / avg_total * 100) if avg_total > 0 else 0
        if avg_pct > 20:
            print(f"  ⚠️  {phase}: {avg_pct:.1f}% of total time ({avg_duration:.2f}s avg)")
        else:
            print(f"  ✓  {phase}: {avg_pct:.1f}% of total time ({avg_duration:.2f}s avg)")

    print(f"{'='*80}\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        # Try to find most recent data directory
        data_path = Path("data")
        if data_path.exists():
            data_dirs = sorted([d for d in data_path.glob("data_*") if d.is_dir()],
                             key=lambda x: x.name, reverse=True)
            if data_dirs:
                data_dir = str(data_dirs[0])
                print(f"Using most recent data directory: {data_dir}\n")
            else:
                print("No data directories found. Usage: python analyze_performance.py <data_directory>")
                sys.exit(1)
        else:
            print("Usage: python analyze_performance.py <data_directory>")
            sys.exit(1)

    analyze_performance(data_dir)
