#!/usr/bin/env python3
"""
Analyze cases where false positives rank higher than ground truth.
"""

import json
from pathlib import Path
from collections import defaultdict

def analyze_false_positives(base_dir='data/batch_run_20251218_133824'):
    """Find cases where false positives rank higher than ground truth."""
    base_path = Path(base_dir)

    # Find all rca_analysis.json files
    analysis_files = list(base_path.rglob('rca_analysis.json'))

    false_positive_cases = []

    for analysis_file in sorted(analysis_files):
        try:
            with open(analysis_file) as f:
                data = json.load(f)

            ground_truth = data['ground_truth']
            ground_truth_rank = data.get('rank')
            top_candidates = data.get('top_candidates', [])

            # Load label to get fault type
            label_file = analysis_file.parent / 'label.json'
            fault_type = 'unknown'
            if label_file.exists():
                with open(label_file) as f:
                    label = json.load(f)
                    fault_type = label.get('fault_type', 'unknown')

            # Find nodes that rank higher than ground truth
            higher_ranking_fps = []

            # If ground truth rank is None, it means it's not in top-K, so all top-K are false positives
            if ground_truth_rank is None:
                for i, candidate in enumerate(top_candidates):
                    rank = i + 1
                    if candidate['node'] != ground_truth:
                        higher_ranking_fps.append({
                            'rank': rank,
                            'node': candidate['node'],
                            'score': candidate['score'],
                            'integrated_score': candidate['integrated_score'],
                            'self_score': candidate['self_score'],
                            'score_composition': candidate['score_composition'],
                            'symptoms': candidate.get('symptoms', []),
                            'health_metadata': candidate.get('health_metadata', {})
                        })
            else:
                # Ground truth is in top-K, find nodes that rank higher
                for i, candidate in enumerate(top_candidates):
                    rank = i + 1
                    if candidate['node'] != ground_truth and rank < ground_truth_rank:
                        higher_ranking_fps.append({
                            'rank': rank,
                            'node': candidate['node'],
                            'score': candidate['score'],
                            'integrated_score': candidate['integrated_score'],
                            'self_score': candidate['self_score'],
                            'score_composition': candidate['score_composition'],
                            'symptoms': candidate.get('symptoms', []),
                            'health_metadata': candidate.get('health_metadata', {})
                        })

            if higher_ranking_fps:
                # Get ground truth details
                gt_candidate = None
                for candidate in top_candidates:
                    if candidate['node'] == ground_truth:
                        gt_candidate = candidate
                        break

                false_positive_cases.append({
                    'file': str(analysis_file),
                    'fault_type': fault_type,
                    'ground_truth': ground_truth,
                    'ground_truth_rank': ground_truth_rank,
                    'ground_truth_candidate': gt_candidate,
                    'higher_ranking_fps': higher_ranking_fps
                })

        except Exception as e:
            print(f"Error processing {analysis_file}: {e}")

    # Print summary
    print("="*80)
    print(f"FALSE POSITIVES RANKING HIGHER THAN GROUND TRUTH")
    print("="*80)
    print(f"Found {len(false_positive_cases)} cases\n")

    # Analyze patterns
    for i, case in enumerate(false_positive_cases, 1):
        print(f"\n{'='*80}")
        print(f"CASE {i}: {case['fault_type']}")
        print(f"{'='*80}")
        print(f"File: {case['file']}")
        rank_str = f"Rank {case['ground_truth_rank']}" if case['ground_truth_rank'] else "NOT IN TOP-K"
        print(f"Ground Truth: {case['ground_truth']} ({rank_str})")

        if case['ground_truth_candidate']:
            gt = case['ground_truth_candidate']
            print(f"\nGround Truth Details:")
            print(f"  Score: {gt['score']}")
            print(f"  Self Score: {gt['self_score']}")
            print(f"  Integrated Score: {gt['integrated_score']}")
            print(f"  Symptoms: {len(gt.get('symptoms', []))}")
            if gt.get('symptoms'):
                for symptom in gt['symptoms'][:3]:
                    print(f"    - {symptom}")

            # Score composition
            composition = gt['score_composition']
            print(f"\n  Score Composition:")
            print(f"    Base Health: raw={composition['base_health']['raw']:.2f}, "
                  f"confidence={composition['base_health']['confidence']}, "
                  f"points={composition['base_health']['points']:.2f}")
            print(f"    Physics Coverage: raw={composition['physics_coverage']['raw']:.2f}, "
                  f"points={composition['physics_coverage']['points']:.2f}")
            print(f"    Semantic Bonus: primary={composition['semantic_bonus']['is_primary']}, "
                  f"points={composition['semantic_bonus']['points']:.2f}")
            supplements = composition['supplements']
            print(f"    Supplements: temporal={supplements['temporal']:.2f}, "
                  f"trace={supplements['trace']:.2f}, "
                  f"trace_degradation={supplements.get('trace_degradation', 0):.2f}")

        print(f"\nFalse Positives Ranking Higher:")
        for fp in case['higher_ranking_fps']:
            print(f"\n  Rank {fp['rank']}: {fp['node']} (Score: {fp['score']})")
            print(f"    Self Score: {fp['self_score']}")
            print(f"    Integrated Score: {fp['integrated_score']}")
            print(f"    Symptoms: {len(fp.get('symptoms', []))}")
            if fp.get('symptoms'):
                for symptom in fp['symptoms'][:3]:
                    print(f"      - {symptom}")

            # Score composition
            composition = fp['score_composition']
            print(f"    Score Composition:")
            print(f"      Base Health: raw={composition['base_health']['raw']:.2f}, "
                  f"confidence={composition['base_health']['confidence']}, "
                  f"points={composition['base_health']['points']:.2f}")
            print(f"      Physics Coverage: raw={composition['physics_coverage']['raw']:.2f}, "
                  f"points={composition['physics_coverage']['points']:.2f}")
            print(f"      Semantic Bonus: primary={composition['semantic_bonus']['is_primary']}, "
                  f"points={composition['semantic_bonus']['points']:.2f}")
            supplements = composition['supplements']
            print(f"      Supplements: temporal={supplements['temporal']:.2f}, "
                  f"trace={supplements['trace']:.2f}, "
                  f"trace_degradation={supplements.get('trace_degradation', 0):.2f}")

            # Health metadata
            health = fp.get('health_metadata', {})
            print(f"    Health Metadata:")
            print(f"      Coverage: {health.get('coverage', 0):.2f}")
            print(f"      Pattern: {health.get('pattern', 'N/A')}")
            if health.get('degraded_count') is not None:
                print(f"      Degraded: {health.get('degraded_count')}/{health.get('total_count')} pods")

    # Pattern analysis
    print("\n\n" + "="*80)
    print("PATTERN ANALYSIS")
    print("="*80)

    # Count by fault type
    by_fault = defaultdict(int)
    for case in false_positive_cases:
        by_fault[case['fault_type']] += 1

    print("\nCases by Fault Type:")
    for fault_type, count in sorted(by_fault.items(), key=lambda x: -x[1]):
        print(f"  {fault_type}: {count}")

    # Analyze false positive nodes
    fp_nodes = defaultdict(int)
    for case in false_positive_cases:
        for fp in case['higher_ranking_fps']:
            fp_nodes[fp['node']] += 1

    print("\nMost Common False Positive Nodes:")
    for node, count in sorted(fp_nodes.items(), key=lambda x: -x[1]):
        print(f"  {node}: {count} times")

    # Check if false positives have symptoms when they shouldn't
    print("\nFalse Positives with/without Symptoms:")
    fp_with_symptoms = 0
    fp_without_symptoms = 0
    for case in false_positive_cases:
        for fp in case['higher_ranking_fps']:
            if fp.get('symptoms'):
                fp_with_symptoms += 1
            else:
                fp_without_symptoms += 1

    print(f"  With symptoms: {fp_with_symptoms}")
    print(f"  Without symptoms: {fp_without_symptoms}")

    # Check self_score vs integrated_score discrepancies
    print("\nSelf Score vs Integrated Score Analysis:")
    print("  (Cases where integrated_score >> self_score might indicate false health detection)")

    for case in false_positive_cases:
        for fp in case['higher_ranking_fps']:
            if fp['self_score'] == 0 and fp['integrated_score'] > 0:
                print(f"  {case['fault_type']}: {fp['node']} - self=0, integrated={fp['integrated_score']:.2f}")

    return false_positive_cases

if __name__ == "__main__":
    import sys
    base_dir = sys.argv[1] if len(sys.argv) > 1 else 'data/batch_run_20251218_133824'
    analyze_false_positives(base_dir)
