#!/usr/bin/env python3
"""
SOTA Fault Propagation Analyzer - CLI Tool

State-of-the-art fault propagation analysis with:
- Blind root cause detection (discovery mode)
- Ground truth validation (validation mode)
- Pod-level forensics
- Multi-path convergence
- Temporal causality
- Network partition detection

Usage:
    python analyze_sota.py <episode_dir> [--mode discovery|validation] [--output results.json]

Examples:
    # Discovery mode (blind root cause detection)
    python analyze_sota.py data/data_20251208_120000/ep_0 --mode discovery

    # Validation mode (with ground truth)
    python analyze_sota.py data/data_20251208_120000/ep_0 --mode validation

    # Save detailed JSON output
    python analyze_sota.py data/data_20251208_120000/ep_0 --output sota_analysis.json
"""

import sys
import argparse
from pathlib import Path
from analysis.sotaanalyzer import analyze_episode_sota


def print_discovery_summary(result):
    """Print summary for discovery mode."""
    print(f"\n{'='*80}")
    print(f"SOTA FAULT PROPAGATION ANALYSIS - Episode {result.episode_id}")
    print(f"Mode: {result.analysis_mode.upper()}")
    print(f"{'='*80}\n")

    # Network partition check
    if result.network_partition:
        np_data = result.network_partition
        print(f"⚠️  NETWORK PARTITION DETECTED")
        print(f"   Affected Nodes: {len(np_data.affected_nodes)}")
        print(f"   Evidence Score: {np_data.evidence_score:.2f}")
        print(f"   {np_data.description}\n")

    # Health summary
    print(f"{'─'*80}")
    print(f"HEALTH SUMMARY")
    print(f"{'─'*80}")
    print(f"Total Nodes: {result.total_nodes_analyzed}")
    print(f"  • Healthy:   {len(result.healthy_nodes)}")
    print(f"  • Degraded:  {len(result.degraded_nodes)}")
    print(f"  • Impacted:  {len(result.impacted_nodes)}")
    print(f"  • Critical:  {len(result.critical_nodes)}")

    # Root cause candidates
    print(f"\n{'─'*80}")
    print(f"TOP ROOT CAUSE CANDIDATES")
    print(f"{'─'*80}")

    for i, candidate in enumerate(result.root_cause_candidates[:3], start=1):
        print(f"\n{i}. {candidate.node_id} ({candidate.node_type})")
        print(f"   Probability: {candidate.probability:.3f} ({candidate.confidence} confidence)")
        print(f"   Reasoning: {candidate.reasoning}")

        if candidate.is_leaf_node:
            print(f"   ✓ Leaf node (no dependencies)")

        if candidate.impacted_first:
            print(f"   ✓ Impacted first (t={candidate.first_impact_time:.1f}s)")

        if candidate.convergence_path_count > 0:
            print(f"   ✓ {candidate.convergence_path_count} impact paths converge here")

        if candidate.signature_match_score > 0.5:
            sig = candidate.fault_signature
            print(f"   ✓ Fault signature match: {sig.get('detected_signature', 'unknown')}")

    # Service impact summary
    print(f"\n{'─'*80}")
    print(f"SERVICE IMPACT SUMMARY (Pods Aggregated)")
    print(f"{'─'*80}")

    for svc in result.service_impact_summary[:10]:
        print(f"\n• {svc['service_id']}")
        print(f"  Severity: {svc['aggregated_severity_score']:.3f} " +
              f"(across {svc['total_pods']} pods)")

        if svc['pod_consensus'] < 1.0:
            print(f"  Pod Consensus: {svc['pod_consensus']*100:.0f}% pods impacted")

        if not svc['consistent_impact']:
            print(f"  ⚠️  Inconsistent impact across pods")

        if svc['outlier_pods_count'] > 0:
            print(f"  ⚠️  {svc['outlier_pods_count']} outlier pods detected")

        if svc['hot_pods']:
            print(f"  🔥 Hot pods: {', '.join(svc['hot_pods'])}")

        if svc['noisy_neighbor_count'] > 0:
            print(f"  👥 {svc['noisy_neighbor_count']} pods affected by noisy neighbors")

    print(f"\n{'='*80}\n")


def print_validation_summary(result):
    """Print summary for validation mode."""
    print_discovery_summary(result)  # First print discovery info

    if not result.validation_results:
        return

    val = result.validation_results

    print(f"{'─'*80}")
    print(f"GROUND TRUTH VALIDATION")
    print(f"{'─'*80}")
    print(f"Ground Truth Root Cause: {result.ground_truth_root_cause}")
    print(f"")

    if val['correct_detection']:
        print(f"✅ CORRECT - Detected as rank #{val['detected_rank']}")
        print(f"   Detection Probability: {val['detection_probability']:.3f}")
    elif val['root_cause_in_top_3']:
        print(f"⚠️  PARTIAL - Found in top 3 (rank #{val['detected_rank']})")
        print(f"   Detection Probability: {val['detection_probability']:.3f}")
    else:
        print(f"❌ MISSED - Not in top 3 candidates")
        print(f"   Top 3 were: {', '.join(val['top_3_candidates'])}")

    # Propagation by distance
    if result.propagation_by_distance:
        print(f"\n{'─'*80}")
        print(f"PROPAGATION BY DISTANCE")
        print(f"{'─'*80}")

        for dist in sorted(result.propagation_by_distance.keys()):
            nodes = result.propagation_by_distance[dist]
            print(f"\nDistance {dist}: {len(nodes)} nodes")

            for node in nodes[:3]:  # Top 3 per distance
                print(f"  • {node['node_id']}: {node['severity_class']} " +
                      f"(severity: {node['severity_score']:.3f})")

                if node['first_impact_time']:
                    print(f"    First impact: {node['first_impact_time']:.1f}s")

    print(f"\n{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='SOTA Fault Propagation Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'episode_dir',
        help='Path to episode directory'
    )

    parser.add_argument(
        '--mode', '-m',
        choices=['discovery', 'validation'],
        default='discovery',
        help='Analysis mode: discovery (blind) or validation (ground truth)'
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

    args = parser.parse_args()

    # Check episode directory
    episode_path = Path(args.episode_dir)
    if not episode_path.exists():
        print(f"❌ Error: Episode directory '{args.episode_dir}' not found", file=sys.stderr)
        sys.exit(1)

    required_files = ['label.json', 'topology.json', 'metrics.jsonl']
    for filename in required_files:
        if not (episode_path / filename).exists():
            print(f"❌ Error: Required file '{filename}' not found", file=sys.stderr)
            sys.exit(1)

    # Run analysis
    print(f"Analyzing episode: {args.episode_dir}")
    print(f"Mode: {args.mode}")
    print("This may take a moment...\n")

    try:
        result = analyze_episode_sota(
            episode_dir=args.episode_dir,
            mode=args.mode,
            sample_interval=args.sample_interval,
            output_file=args.output
        )

        # Print summary
        if args.mode == 'validation':
            print_validation_summary(result)
        else:
            print_discovery_summary(result)

        if args.output:
            print(f"✅ Detailed results saved to: {args.output}")

    except Exception as e:
        print(f"❌ Error during analysis: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
