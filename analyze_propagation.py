#!/usr/bin/env python3
"""
SOTA Fault Propagation Analyzer - CLI Tool

Comprehensive statistical analysis of fault propagation in distributed systems.

Usage:
    python analyze_propagation.py <episode_dir> [--output results.json] [--verbose]

Examples:
    python analyze_propagation.py data/data_20251125_092902/ep_0
    python analyze_propagation.py data/data_20251125_092902/ep_0 --output propagation.json
    python analyze_propagation.py data/data_20251125_092902/ep_0 --verbose
"""

import sys
import argparse
from pathlib import Path
from analysis.propagation_analyzer import analyze_episode


def print_summary(summary):
    """Print human-readable summary."""
    print(f"\n{'='*80}")
    print(f"FAULT PROPAGATION ANALYSIS - Episode {summary.episode_id}")
    print(f"{'='*80}\n")

    # Root cause info
    rc = summary.root_cause
    print(f"Root Cause: {rc['node_id']} ({rc['node_type']})")
    print(f"Fault Type: {rc['fault_type']}")
    print(f"Fault Start: {rc['fault_start_time']}s")
    if rc.get('fault_params'):
        print(f"Fault Params: {rc['fault_params']}")

    # Overall statistics
    stats = summary.propagation_statistics
    print(f"\n{'─'*80}")
    print(f"IMPACT SUMMARY")
    print(f"{'─'*80}")
    print(f"Total Nodes Analyzed: {stats['total_nodes_analyzed']}")
    print(f"  • Critical Impact:  {stats['nodes_critically_impacted']}")
    print(f"  • High Impact:      {stats['nodes_highly_impacted']}")
    print(f"  • Medium Impact:    {stats['nodes_moderately_impacted']}")
    print(f"  • Unimpacted:       {stats['nodes_unimpacted']}")

    # Propagation timing
    timing = stats['propagation_timing']
    if timing['first_impact_time']:
        print(f"\nPropagation Timing:")
        print(f"  First Impact: {timing['first_impact_time']:.1f}s (node: {timing['first_impact_node']})")
        if timing['median_propagation_delay']:
            print(f"  Median Delay: {timing['median_propagation_delay']:.1f}s from fault injection")
        if timing['max_propagation_delay']:
            print(f"  Max Delay:    {timing['max_propagation_delay']:.1f}s")

    # Impact by distance
    print(f"\nImpact by Distance from Root Cause:")
    for dist in sorted(stats['impact_by_distance'].keys()):
        impacts = stats['impact_by_distance'][dist]
        total = sum(impacts.values())
        critical = impacts.get('critical', 0)
        high = impacts.get('high', 0)
        medium = impacts.get('medium', 0)

        if total > 0:
            print(f"  Distance {dist}: {total} nodes " +
                  f"({critical} critical, {high} high, {medium} medium)")

    # Top impacted nodes
    print(f"\n{'─'*80}")
    print(f"TOP IMPACTED NODES")
    print(f"{'─'*80}")

    # Sort by severity score
    sorted_reports = sorted(
        summary.node_reports,
        key=lambda r: r.overall_severity_score,
        reverse=True
    )

    for i, report in enumerate(sorted_reports[:10], start=1):
        if report.overall_severity == 'NEGLIGIBLE':
            continue

        print(f"\n{i}. {report.node_id} ({report.node_type}) - {report.overall_severity}")
        print(f"   Distance: {report.distance_from_root} hops from root cause")
        print(f"   Severity Score: {report.overall_severity_score:.3f}")

        if report.first_impact_time:
            print(f"   First Impact: {report.first_impact_time:.1f}s " +
                  f"(+{report.impact_delay_seconds:.1f}s from fault)")

        print(f"   Metrics: {report.total_metrics_analyzed} analyzed " +
              f"({report.metrics_with_critical_impact} critical, " +
              f"{report.metrics_with_high_impact} high)")

        if report.primary_impact_type:
            print(f"   Primary Impact: {report.primary_impact_type}")

        # Show top 3 impacted metrics
        if report.ranked_metrics:
            print(f"   Top Impacted Metrics:")
            for metric_info in report.ranked_metrics[:3]:
                print(f"     • {metric_info['metric_name']}: " +
                      f"{metric_info['severity_class']} " +
                      f"(score: {metric_info['severity_score']:.3f})")

    # Validation
    print(f"\n{'─'*80}")
    print(f"VALIDATION")
    print(f"{'─'*80}")

    val = summary.validation
    status = "✅ PASSED" if val['fault_injection_working'] else "❌ FAILED"
    print(f"Fault Injection Quality: {status}")
    print(f"  Quality Score: {val['quality_score']:.2f}/1.0")
    print(f"  Root Cause Impacted: {'✅' if val['root_cause_clearly_impacted'] else '❌'}")
    print(f"  Propagation Detected: {'✅' if val['propagation_detected'] else '❌'}")
    print(f"  Blast Radius: {val['blast_radius']} nodes")

    if val.get('issues'):
        print(f"\n  Issues:")
        for issue in val['issues']:
            print(f"    ⚠️  {issue}")

    print(f"\n{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='SOTA Fault Propagation Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'episode_dir',
        help='Path to episode directory containing label.json, topology.json, and metrics.jsonl'
    )

    parser.add_argument(
        '--output', '-o',
        help='Output JSON file for detailed results',
        default=None
    )

    parser.add_argument(
        '--sample-interval',
        type=int,
        default=5,
        help='Time interval between samples in seconds (default: 5)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed output'
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
            print(f"❌ Error: Required file '{filename}' not found in {args.episode_dir}", file=sys.stderr)
            sys.exit(1)

    # Run analysis
    if not args.json_only:
        print(f"Analyzing episode: {args.episode_dir}")
        print("This may take a moment...")

    try:
        summary = analyze_episode(
            episode_dir=args.episode_dir,
            sample_interval=args.sample_interval,
            output_file=args.output
        )

        # Print results
        if args.json_only:
            print(summary.to_json())
        else:
            print_summary(summary)

            if args.output:
                print(f"✅ Detailed results saved to: {args.output}")

    except Exception as e:
        print(f"❌ Error during analysis: {str(e)}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
