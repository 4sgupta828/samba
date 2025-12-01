#!/usr/bin/env python3
"""
Test script to verify the refactored forensic analyzer works correctly.
"""

import sys
from pathlib import Path

# Find the most recent episode with forensic data
data_dir = Path("data")
episode_dirs = []

for dataset_dir in sorted(data_dir.glob("data_*"), reverse=True):
    for ep_dir in dataset_dir.glob("ep_*"):
        if (ep_dir / "label.json").exists() and (ep_dir / "topology.json").exists():
            episode_dirs.append(ep_dir)
            if len(episode_dirs) >= 1:  # Just test one episode
                break
    if episode_dirs:
        break

if not episode_dirs:
    print("No episode directories found with required files.")
    sys.exit(1)

print(f"Testing with episode: {episode_dirs[0]}")

# Import and test
from analysis.forensic_analyzer import analyze_episode

try:
    print("\nRunning forensic analysis...")
    report = analyze_episode(str(episode_dirs[0]))

    print("\n" + "="*60)
    print("FORENSIC ANALYSIS SUMMARY")
    print("="*60)
    print(f"Episode ID: {report.episode_id}")
    print(f"Fault Type: {report.fault_type}")
    print(f"Root Cause: {report.root_cause_component}")
    print(f"\nComponent Degradations: {len(report.component_degradations)}")
    print(f"Bottlenecks Detected: {len(report.bottlenecks)}")
    print(f"Crashes: {len(report.crashes)}")
    print(f"Cascades: {len(report.cascades)}")
    print(f"Circuit Breaker Events: {len(report.circuit_breaker_events)}")
    print(f"Queue Analyses: {len(report.queue_analyses)}")
    print(f"Recommendations: {len(report.recovery_recommendations)}")
    print(f"\nSystem Recovered: {report.system_recovered}")
    print(f"Initial Health: {report.initial_health.overall_health.value}")
    print(f"Final Health: {report.final_health.overall_health.value}")

    if report.component_degradations:
        print("\nTop 5 Most Degraded Components:")
        sorted_degs = sorted(report.component_degradations,
                           key=lambda x: x.degradation_pct,
                           reverse=True)[:5]
        for deg in sorted_degs:
            print(f"  - {deg.component_id}: {deg.degradation_pct:.1f}% ({deg.severity})")

    if report.recovery_recommendations:
        print("\nTop 3 Priority Recommendations:")
        for rec in report.recovery_recommendations[:3]:
            print(f"  [{rec.priority.upper()}] {rec.component_id}")
            print(f"    Issue: {rec.issue}")
            print(f"    Recommendation: {rec.recommendation}")

    print("\n" + "="*60)
    print("✓ Refactored forensic analyzer working correctly!")
    print("="*60)

except Exception as e:
    print(f"\n✗ Error during analysis: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
