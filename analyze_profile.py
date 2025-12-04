#!/usr/bin/env python3
"""Analyze cProfile output to identify performance bottlenecks."""

import pstats
import sys
from pstats import SortKey

def analyze_profile(profile_file):
    """Analyze and print profile statistics."""

    print("=" * 80)
    print("SIMULATION PERFORMANCE PROFILE")
    print("=" * 80)

    stats = pstats.Stats(profile_file)

    # Overall statistics
    print("\n📊 OVERALL STATISTICS")
    print("-" * 80)
    stats.print_stats(0)

    # Top 30 functions by cumulative time
    print("\n⏱️  TOP 30 FUNCTIONS BY CUMULATIVE TIME")
    print("-" * 80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats(30)

    # Top 30 functions by total time (self time)
    print("\n🔥 TOP 30 FUNCTIONS BY SELF TIME (excluding called functions)")
    print("-" * 80)
    stats.sort_stats(SortKey.TIME)
    stats.print_stats(30)

    # Top 30 most called functions
    print("\n📞 TOP 30 MOST CALLED FUNCTIONS")
    print("-" * 80)
    stats.sort_stats(SortKey.CALLS)
    stats.print_stats(30)

    # Focus on simulation-specific code
    print("\n🎯 SIMULATION-SPECIFIC HOTSPOTS (src/ directory only)")
    print("-" * 80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats('src/', 50)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        profile_file = sys.argv[1]
    else:
        profile_file = "/tmp/simulation_profile.prof"

    try:
        analyze_profile(profile_file)
    except FileNotFoundError:
        print(f"❌ Profile file not found: {profile_file}")
        print("Run profiling first: python3 -m cProfile -o profile.prof generate_dataset.py ...")
        sys.exit(1)
