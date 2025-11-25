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
import numpy as np
from analysis.propagation_analyzer import analyze_episode


def _explain_metric_impact(fault_type, metric_name, mean_change, distance):
    """Generate qualitative explanation of why metric changed."""
    if mean_change is None or np.isnan(mean_change) or np.isinf(mean_change):
        return None

    metric_lower = metric_name.lower()
    direction = "increased" if mean_change > 0 else "decreased"

    # Database faults
    if 'slow_queries' in fault_type:
        if 'request' in metric_lower and mean_change < 0:
            return "Database slowdown reduces request processing throughput"
        elif 'latency' in metric_lower or 'duration' in metric_lower:
            return "Queries taking longer due to database degradation"
        elif 'queue' in metric_lower and mean_change > 0:
            return "Requests backing up due to slow database responses"
        # Message queue specific metrics
        elif 'messages.visible' in metric_lower and mean_change > 0:
            return "Messages accumulating due to slow consumer processing (database bottleneck)"
        elif 'messages.age' in metric_lower and mean_change > 0:
            return "Messages waiting longer due to slow consumer processing (database bottleneck)"
        elif 'messages.in_flight' in metric_lower:
            if mean_change > 0:
                return "More messages being processed (consumers working harder to drain queue)"
            else:
                return "Fewer messages being processed (consumers stuck waiting on database)"

    # Error injection faults
    elif 'inject_errors' in fault_type or 'error_rate' in fault_type:
        if 'error' in metric_lower and mean_change > 0:
            if distance == 0:
                return "Direct fault injection increasing error rate"
            else:
                return f"Errors propagating from root cause ({distance} hops away)"
        elif 'request' in metric_lower and mean_change < 0:
            return "Failed requests reducing overall throughput"

    # Latency injection faults
    elif 'inject_latency' in fault_type or 'slow' in fault_type:
        if 'latency' in metric_lower or 'duration' in metric_lower:
            if distance == 0:
                return "Artificial latency injection"
            else:
                return f"Latency propagating through dependency chain ({distance} hops)"
        elif 'queue' in metric_lower and mean_change > 0:
            return "Increased latency causing request queuing"

    # Resource exhaustion
    elif 'cpu' in fault_type or 'memory' in fault_type:
        if 'request' in metric_lower and mean_change < 0:
            return "Resource exhaustion limiting request processing"
        elif 'latency' in metric_lower and mean_change > 0:
            return "Resource contention increasing response times"

    # Connection limit faults
    elif 'connection' in fault_type or 'pool' in fault_type:
        if 'reject' in metric_lower and mean_change > 0:
            return "Connection limit reached, rejecting new connections"
        elif 'request' in metric_lower and mean_change < 0:
            return "Connection pool saturation limiting throughput"

    # Generic explanations based on metric type and direction
    if 'error' in metric_lower and mean_change > 0:
        return f"Fault causing increased error rate ({distance} hops from root cause)"
    elif 'request' in metric_lower and mean_change < 0:
        return f"Degradation reducing request throughput ({distance} hops from root cause)"
    elif 'latency' in metric_lower or 'duration' in metric_lower:
        return f"Fault impact on response time ({distance} hops from root cause)"
    # Message queue metrics (generic)
    elif 'mq.' in metric_lower or 'queue' in metric_lower:
        if 'messages.visible' in metric_lower or 'depth' in metric_lower:
            if mean_change > 0:
                return f"Messages accumulating due to degraded processing ({distance} hops from root cause)"
            else:
                return f"Queue draining (fewer messages waiting)"
        elif 'age' in metric_lower and mean_change > 0:
            return f"Messages waiting longer due to slow processing ({distance} hops from root cause)"
        elif 'in_flight' in metric_lower or 'active' in metric_lower:
            if mean_change > 0:
                return f"More concurrent processing (attempting to handle backlog)"
            else:
                return f"Less concurrent processing (consumers blocked or failing)"

    return None


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

        # Show top 3 impacted metrics with detailed analysis
        if report.ranked_metrics:
            print(f"\n   Top Impacted Metrics:")
            for metric_info in report.ranked_metrics[:3]:
                print(f"\n     • {metric_info['metric_name']}: " +
                      f"{metric_info['severity_class']} " +
                      f"(severity: {metric_info['severity_score']:.3f})")

                # Direction and magnitude
                mean_change = metric_info.get('mean_change_pct')
                cohens_d = metric_info.get('cohens_d')
                cohens_d_cat = metric_info.get('cohens_d_category')

                if mean_change is not None and not np.isinf(mean_change):
                    direction = "increased" if mean_change > 0 else "decreased"
                    print(f"       Direction: {direction} by {abs(mean_change):.1f}%")

                if cohens_d is not None and not np.isnan(cohens_d) and not np.isinf(cohens_d):
                    print(f"       Effect Size: {cohens_d_cat} (Cohen's d = {abs(cohens_d):.2f})")

                # Baseline vs Fault values
                baseline_mean = metric_info.get('baseline_mean')
                fault_mean = metric_info.get('fault_mean')
                baseline_std = metric_info.get('baseline_std')
                fault_std = metric_info.get('fault_std')

                if baseline_mean is not None and fault_mean is not None:
                    print(f"       Baseline: mean={baseline_mean:.2f}, std={baseline_std:.2f}")
                    print(f"       Fault:    mean={fault_mean:.2f}, std={fault_std:.2f}")

                # Variance change
                var_ratio = metric_info.get('variance_ratio')
                if var_ratio is not None and not np.isnan(var_ratio) and not np.isinf(var_ratio):
                    if var_ratio > 1.5:
                        print(f"       Variance: increased {var_ratio:.1f}x (more unstable)")
                    elif var_ratio < 0.67 and var_ratio > 0:
                        print(f"       Variance: decreased {1/var_ratio:.1f}x (more stable)")
                    elif var_ratio == 0:
                        print(f"       Variance: became zero (completely stable)")

                # Pattern changes
                vol_ratio = metric_info.get('volatility_ratio')
                burst_change = metric_info.get('burstiness_change')

                if vol_ratio is not None and not np.isnan(vol_ratio) and not np.isinf(vol_ratio):
                    if vol_ratio > 1.5:
                        print(f"       Pattern: became {vol_ratio:.1f}x more volatile")

                if burst_change is not None and not np.isnan(burst_change):
                    if abs(burst_change) > 0.1:
                        if burst_change > 0:
                            print(f"       Pattern: became more bursty (Δ={burst_change:.2f})")
                        else:
                            print(f"       Pattern: became more regular (Δ={burst_change:.2f})")

                # Show interpretation
                interp = metric_info.get('interpretation', '')
                if interp:
                    print(f"       Summary: {interp}")

                # Add qualitative explanation based on fault type and metric
                fault_type = summary.root_cause.get('fault_type', '')
                metric_name = metric_info['metric_name']
                explanation = _explain_metric_impact(fault_type, metric_name, mean_change, report.distance_from_root)
                if explanation:
                    print(f"       Why: {explanation}")

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
