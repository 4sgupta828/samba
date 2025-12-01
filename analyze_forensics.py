#!/usr/bin/env python3
"""
Forensic Analyzer - CLI Tool

Comprehensive post-simulation forensic analysis of distributed system failures.

Usage:
    python analyze_forensics.py <episode_dir> [--output results.json] [--verbose]

Examples:
    python analyze_forensics.py data/data_20251125_092902/ep_0
    python analyze_forensics.py data/data_20251125_092902/ep_0 --output forensic.json
    python analyze_forensics.py data/data_20251125_092902/ep_0 --verbose
"""

import sys
import argparse
import json
from pathlib import Path
from analysis.forensic_analyzer import analyze_episode


def print_summary(report):
    """Print a human-readable summary of the forensic analysis."""

    print("\n" + "="*80)
    print("FORENSIC ANALYSIS REPORT")
    print("="*80)

    # Episode information
    print(f"\n📋 Episode: {report.episode_id}")
    print(f"   Duration: {report.simulation_duration:.1f}s")
    print(f"   Fault Injection: {report.fault_injection_time:.1f}s")
    print(f"   Root Cause: {report.root_cause_component}")
    print(f"   Fault Type: {report.fault_type}")

    # Summary statistics
    summary = report.summary
    print(f"\n📊 Summary Statistics:")
    print(f"   Total Components: {summary.get('total_components', 'N/A')}")
    print(f"   Components Degraded: {summary.get('components_degraded', 'N/A')}")
    print(f"   Bottlenecks Detected: {summary.get('total_bottlenecks', 0)}")
    print(f"   Crashes: {summary.get('total_crashes', 0)} ({summary.get('crashes_recovered', 0)} recovered)")
    print(f"   Cascades: {summary.get('total_cascades', 0)}")
    print(f"   Circuit Breaker Events: {summary.get('total_circuit_breaker_events', 0)}")
    print(f"   System Recovered: {'✓ Yes' if report.system_recovered else '✗ No'}")

    # Component degradations
    if report.component_degradations:
        print(f"\n🔻 Component Degradation (Top 5):")
        sorted_degradations = sorted(
            report.component_degradations,
            key=lambda x: x['degradation_percent'],
            reverse=True
        )[:5]

        for deg in sorted_degradations:
            print(f"   • {deg['component_id']}: {deg['degradation_percent']:.1f}% "
                  f"({deg['severity']})")

    # Bottlenecks
    if report.bottlenecks:
        print(f"\n⚠️  Bottlenecks Detected:")
        for bottleneck in report.bottlenecks[:5]:  # Top 5
            # Handle both dict and dataclass
            if hasattr(bottleneck, '__dict__'):
                component_id = bottleneck.component_id
                bottleneck_type = bottleneck.bottleneck_type
                duration = bottleneck.duration
                severity = bottleneck.severity
            else:
                component_id = bottleneck['component_id']
                bottleneck_type = bottleneck['bottleneck_type']
                duration = bottleneck['duration']
                severity = bottleneck['severity']

            # Handle Enum types
            if hasattr(bottleneck_type, 'value'):
                bottleneck_type = bottleneck_type.value

            print(f"   • {component_id}: {str(bottleneck_type).upper()}")
            print(f"     Duration: {duration:.1f}s, Severity: {severity}")

    # Crashes
    if report.crashes:
        print(f"\n💥 Crashes:")
        for crash in report.crashes:
            # Handle both dict and dataclass
            if hasattr(crash, '__dict__'):
                component_id = crash.component_id
                crash_time = crash.crash_time
                recovered = crash.recovered
                recovery_time = crash.recovery_time
            else:
                component_id = crash['component_id']
                crash_time = crash['crash_time']
                recovered = crash['recovered']
                recovery_time = crash['recovery_time']

            status = "✓ Recovered" if recovered else "✗ Failed to recover"
            print(f"   • {component_id} at {crash_time:.1f}s - {status}")
            if recovery_time:
                print(f"     Recovery time: {recovery_time - crash_time:.1f}s")

    # Cascades
    if report.cascades:
        print(f"\n🔗 Failure Cascades:")
        for i, cascade in enumerate(report.cascades, 1):
            # Handle both dict and dataclass
            if hasattr(cascade, '__dict__'):
                origin_component = cascade.origin_component
                affected_components = cascade.affected_components
                propagation_mechanism = cascade.propagation_mechanism
            else:
                origin_component = cascade['origin_component']
                affected_components = cascade['affected_components']
                propagation_mechanism = cascade['propagation_mechanism']

            print(f"   Cascade #{i}:")
            print(f"     Origin: {origin_component}")
            print(f"     Affected: {len(affected_components)} components")
            print(f"     Mechanism: {propagation_mechanism}")
            affected = ', '.join(affected_components[:5])
            if len(affected_components) > 5:
                affected += f" ... (+{len(affected_components) - 5} more)"
            print(f"     Components: {affected}")

    # Health progression
    print(f"\n❤️  System Health:")
    initial = report.initial_health
    final = report.final_health

    # Handle both dict and dataclass
    if hasattr(initial, '__dict__'):
        initial_healthy = initial.healthy_services
        initial_degraded = initial.degraded_services
        initial_failed = initial.failed_services
    else:
        initial_healthy = initial['healthy_services']
        initial_degraded = initial['degraded_services']
        initial_failed = initial['failed_services']

    if hasattr(final, '__dict__'):
        final_healthy = final.healthy_services
        final_degraded = final.degraded_services
        final_failed = final.failed_services
    else:
        final_healthy = final['healthy_services']
        final_degraded = final['degraded_services']
        final_failed = final['failed_services']

    print(f"   Initial: {initial_healthy} healthy, {initial_degraded} degraded, "
          f"{initial_failed} failed")
    print(f"   Final:   {final_healthy} healthy, {final_degraded} degraded, "
          f"{final_failed} failed")

    # Recovery recommendations
    if report.recovery_recommendations:
        print(f"\n💡 Recovery Recommendations:")
        for i, rec in enumerate(report.recovery_recommendations[:5], 1):
            # Handle both dict and dataclass
            if hasattr(rec, '__dict__'):
                priority = rec.priority
                component_id = rec.component_id
                issue = rec.issue
                recommendation = rec.recommendation
            else:
                priority = rec['priority']
                component_id = rec['component_id']
                issue = rec['issue']
                recommendation = rec['recommendation']

            print(f"   {i}. [{priority.upper()}] {component_id}")
            print(f"      Issue: {issue}")
            print(f"      Recommendation: {recommendation}")

    print("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(
        description='Run forensic analysis on a simulation episode',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run forensic analysis and display summary
  python analyze_forensics.py data/data_20251125_092902/ep_0

  # Save results to custom file
  python analyze_forensics.py data/data_20251125_092902/ep_0 --output forensic.json

  # Verbose mode with detailed progress
  python analyze_forensics.py data/data_20251125_092902/ep_0 --verbose

  # JSON-only output (no summary)
  python analyze_forensics.py data/data_20251125_092902/ep_0 --json-only
        """
    )

    parser.add_argument(
        'episode_dir',
        help='Path to episode directory (e.g., data/data_20251125_092902/ep_0)'
    )

    parser.add_argument(
        '--output', '-o',
        help='Output JSON file path (default: <episode_dir>/forensic_analysis.json)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed progress information'
    )

    parser.add_argument(
        '--json-only',
        action='store_true',
        help='Only output JSON (suppress human-readable summary)'
    )

    args = parser.parse_args()

    # Check if episode directory exists
    episode_path = Path(args.episode_dir)
    if not episode_path.exists():
        print(f"❌ Error: Episode directory '{args.episode_dir}' not found", file=sys.stderr)
        sys.exit(1)

    required_files = ['label.json', 'topology.json', 'metrics.jsonl']
    for filename in required_files:
        if not (episode_path / filename).exists():
            print(f"❌ Error: Required file '{filename}' not found in {args.episode_dir}",
                  file=sys.stderr)
            sys.exit(1)

    # Run analysis
    if not args.json_only:
        print(f"Analyzing episode: {args.episode_dir}")
        print("Running comprehensive forensic analysis...")
        print("This may take a moment...")

    try:
        report = analyze_episode(args.episode_dir)

        # Save to file
        output_file = args.output or str(episode_path / 'forensic_analysis.json')

        # Use the to_json method which handles numpy types
        json_str = report.to_json(filepath=output_file)

        # Print results
        if args.json_only:
            print(json_str)
        else:
            print_summary(report)
            print(f"\n✅ Detailed results saved to: {output_file}")

    except Exception as e:
        print(f"❌ Error during analysis: {str(e)}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
