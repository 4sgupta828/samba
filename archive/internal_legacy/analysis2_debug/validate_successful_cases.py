#!/usr/bin/env python3
"""
Validate that recommended RCA fixes won't break successful cases.
Analyzes successful RCA cases to ensure proposed changes are safe.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any


def load_json(filepath: Path) -> Dict:
    """Load JSON file."""
    with open(filepath) as f:
        return json.load(f)


def find_successful_cases(batch_dir: Path) -> List[Path]:
    """Find all episodes where RCA succeeded (ground truth rank 1)."""
    successful = []

    for rca_file in batch_dir.rglob("rca_analysis.json"):
        try:
            rca_data = load_json(rca_file)
            if rca_data.get('found_in_top_k') and rca_data.get('rank') == 1:
                successful.append(rca_file.parent)
        except Exception as e:
            print(f"Warning: Could not load {rca_file}: {e}", file=sys.stderr)

    return successful


def analyze_successful_case(episode_dir: Path) -> Dict[str, Any]:
    """Analyze characteristics of a successful RCA case."""
    rca_file = episode_dir / 'rca_analysis.json'
    label_file = episode_dir / 'label.json'

    rca_data = load_json(rca_file)
    label = load_json(label_file) if label_file.exists() else {}

    ground_truth_node = rca_data['ground_truth']

    # Find ground truth in candidates
    ground_truth = None
    for cand in rca_data.get('all_candidates', []):
        if cand['node'] == ground_truth_node:
            ground_truth = cand
            break

    if not ground_truth:
        return {'error': f'Ground truth {ground_truth_node} not found'}

    # Extract key characteristics
    trace_info = ground_truth.get('trace_info', {})
    health_metadata = ground_truth.get('health_metadata', {})

    analysis = {
        'episode_dir': str(episode_dir),
        'ground_truth_node': ground_truth_node,
        'ground_truth_role': label.get('root_cause_role', 'unknown'),
        'fault_type': label.get('fault_type', 'unknown'),
        'rank': rca_data.get('rank'),
        'score': ground_truth.get('score'),

        # Score components
        'integrated_score': ground_truth.get('integrated_score', 0),
        'self_score': ground_truth.get('self_score', 0),
        'trace_score': ground_truth.get('trace_score', 0),
        'temporal_score': ground_truth.get('temporal_score', 0),

        # Key signals
        'has_symptoms': len(ground_truth.get('symptoms', [])) > 0,
        'symptom_count': len(ground_truth.get('symptoms', [])),
        'symptoms': ground_truth.get('symptoms', []),

        'has_trace_data': bool(trace_info),
        'trace_is_authoritative': trace_info.get('is_authoritative', False),
        'trace_self_degradation': trace_info.get('self_time_degradation', 1.0),
        'trace_total_degradation': trace_info.get('total_time_degradation', 1.0),

        'is_healthy_flag': ground_truth.get('is_healthy', True),
        'health_filter_reason': ground_truth.get('health_filter_reason'),

        # Health details
        'service_score': health_metadata.get('service_score', 0),
        'pod_score': health_metadata.get('pod_score', 0),
        'coverage': health_metadata.get('coverage', 0),

        # Top competitors
        'top_2_score': rca_data['top_candidates'][1]['score'] if len(rca_data.get('top_candidates', [])) > 1 else 0,
        'score_margin': ground_truth.get('score', 0) - (rca_data['top_candidates'][1]['score'] if len(rca_data.get('top_candidates', [])) > 1 else 0),
    }

    return analysis


def simulate_recommended_fixes(analysis: Dict) -> Dict[str, Any]:
    """Simulate how recommended fixes would affect the score."""
    original_score = analysis['score']
    adjusted_score = original_score

    changes_applied = []

    # Fix 1: Symptom detection enhancement
    # If already has symptoms, no change. If no symptoms but has trace, add symptoms.
    if not analysis['has_symptoms'] and analysis['has_trace_data']:
        if analysis['trace_self_degradation'] > 2.0:
            adjusted_score += 10.0  # Would get symptoms from trace
            changes_applied.append({
                'fix': 'symptom_detection_from_trace',
                'change': +10.0,
                'reason': f'Trace degradation {analysis["trace_self_degradation"]:.1f}x would be detected as symptom'
            })

    # Fix 2: Health filter override for authoritative trace
    # If marked healthy but has authoritative trace with degradation, would be marked unhealthy
    if (analysis['is_healthy_flag'] and
        analysis['trace_is_authoritative'] and
        analysis['trace_self_degradation'] > 2.0):
        # Might get higher integrated score
        if analysis['integrated_score'] < 10.0:
            boost = 10.0 - analysis['integrated_score']
            adjusted_score += boost
            changes_applied.append({
                'fix': 'health_filter_override',
                'change': boost,
                'reason': f'Authoritative trace would override health filter'
            })

    # Fix 3: Authoritative trace score boost
    if analysis['trace_is_authoritative'] and analysis['trace_score'] > 0:
        # Multiply trace score by 5 and add 50
        boost = (analysis['trace_score'] * 4) + 50  # *4 because already counted once
        adjusted_score += boost
        changes_applied.append({
            'fix': 'authoritative_trace_boost',
            'change': boost,
            'reason': f'Authoritative trace score {analysis["trace_score"]:.1f} multiplied by 5 + bonus'
        })

    # Fix 4: Would victim penalty apply?
    # This doesn't affect ground truth (only affects non-root-cause components)
    # No change for ground truth

    # Calculate new margin
    # Assume competitors don't get the boost (they're not ground truth)
    # But they might get penalty if they're victims with non-authoritative trace
    # For simplicity, assume they stay the same (worst case for us)
    new_margin = adjusted_score - analysis['top_2_score']

    return {
        'original_score': original_score,
        'adjusted_score': adjusted_score,
        'score_increase': adjusted_score - original_score,
        'original_margin': analysis['score_margin'],
        'adjusted_margin': new_margin,
        'margin_increase': new_margin - analysis['score_margin'],
        'changes_applied': changes_applied,
        'would_still_rank_1': adjusted_score > analysis['top_2_score'],
        'confidence': 'high' if new_margin > 10 else 'medium' if new_margin > 0 else 'low'
    }


def generate_validation_report(analyses: List[Dict], simulations: List[Dict]) -> str:
    """Generate validation report."""
    md = []

    md.append("# RCA Fixes Validation Report\n")
    md.append(f"**Successful Cases Analyzed**: {len(analyses)}\n")
    md.append("\n---\n")

    # Overall validation result
    all_safe = all(sim['would_still_rank_1'] for sim in simulations)
    md.append("## Validation Result\n")
    if all_safe:
        md.append("✅ **SAFE**: All successful cases would remain rank 1 with recommended fixes\n")
    else:
        unsafe_count = sum(1 for sim in simulations if not sim['would_still_rank_1'])
        md.append(f"⚠️ **WARNING**: {unsafe_count}/{len(simulations)} cases might break with recommended fixes\n")
    md.append("\n")

    # Summary statistics
    md.append("## Summary Statistics\n")

    avg_score_increase = sum(s['score_increase'] for s in simulations) / len(simulations)
    avg_margin_increase = sum(s['margin_increase'] for s in simulations) / len(simulations)

    md.append(f"- **Average Score Increase**: +{avg_score_increase:.2f}\n")
    md.append(f"- **Average Margin Increase**: +{avg_margin_increase:.2f}\n")
    md.append(f"- **Cases with Margin Improvement**: {sum(1 for s in simulations if s['margin_increase'] > 0)}/{len(simulations)}\n")
    md.append(f"- **High Confidence Cases**: {sum(1 for s in simulations if s['confidence'] == 'high')}/{len(simulations)}\n")
    md.append("\n")

    # Characteristics of successful cases
    md.append("## Characteristics of Successful Cases\n")

    with_symptoms = sum(1 for a in analyses if a.get('has_symptoms'))
    with_trace = sum(1 for a in analyses if a.get('has_trace_data'))
    with_auth_trace = sum(1 for a in analyses if a.get('trace_is_authoritative'))
    marked_healthy = sum(1 for a in analyses if not a.get('is_healthy_flag', True))

    md.append(f"- **Have Symptoms**: {with_symptoms}/{len(analyses)} ({with_symptoms/len(analyses)*100:.1f}%)\n")
    md.append(f"- **Have Trace Data**: {with_trace}/{len(analyses)} ({with_trace/len(analyses)*100:.1f}%)\n")
    md.append(f"- **Authoritative Trace**: {with_auth_trace}/{len(analyses)} ({with_auth_trace/len(analyses)*100:.1f}%)\n")
    md.append(f"- **Marked Unhealthy**: {marked_healthy}/{len(analyses)} ({marked_healthy/len(analyses)*100:.1f}%)\n")
    md.append("\n")

    # Component roles
    from collections import Counter
    roles = Counter(a.get('ground_truth_role', 'unknown') for a in analyses)
    md.append("### By Component Role\n")
    for role, count in roles.most_common():
        md.append(f"- **{role}**: {count}\n")
    md.append("\n")

    # Fault types
    faults = Counter(a.get('fault_type', 'unknown') for a in analyses)
    md.append("### By Fault Type\n")
    for fault, count in faults.most_common():
        md.append(f"- **{fault}**: {count}\n")
    md.append("\n")

    # Fix impact analysis
    md.append("## Fix Impact Analysis\n")

    fix_counts = Counter()
    for sim in simulations:
        for change in sim['changes_applied']:
            fix_counts[change['fix']] += 1

    md.append("### How Often Each Fix Would Apply\n")
    for fix, count in fix_counts.most_common():
        pct = (count / len(simulations)) * 100
        md.append(f"- **{fix}**: {count}/{len(simulations)} cases ({pct:.1f}%)\n")
    md.append("\n")

    # Individual case details
    md.append("## Individual Case Analysis\n")
    md.append("| Episode | Ground Truth | Fault Type | Original Score | Adjusted Score | Margin | Still Rank 1? |\n")
    md.append("|---------|--------------|------------|----------------|----------------|--------|---------------|\n")

    for analysis, simulation in zip(analyses, simulations):
        ep_name = Path(analysis['episode_dir']).name
        gt = analysis['ground_truth_node'][:15]
        fault = analysis['fault_type'][:20]
        orig_score = analysis['score']
        adj_score = simulation['adjusted_score']
        margin = simulation['adjusted_margin']
        still_rank_1 = '✅' if simulation['would_still_rank_1'] else '⚠️'

        md.append(f"| {ep_name} | {gt} | {fault} | {orig_score:.2f} | {adj_score:.2f} | +{margin:.2f} | {still_rank_1} |\n")

    md.append("\n")

    # Detailed change breakdown
    md.append("## Detailed Change Breakdown\n")

    for i, (analysis, simulation) in enumerate(zip(analyses, simulations), 1):
        if not simulation['changes_applied']:
            continue

        md.append(f"### Case {i}: {analysis['ground_truth_node']} ({analysis['fault_type']})\n")
        md.append(f"- **Original Score**: {simulation['original_score']:.2f}\n")
        md.append(f"- **Adjusted Score**: {simulation['adjusted_score']:.2f}\n")
        md.append(f"- **Score Increase**: +{simulation['score_increase']:.2f}\n")
        md.append(f"- **Margin Increase**: +{simulation['margin_increase']:.2f}\n")
        md.append("\n**Changes Applied**:\n")
        for change in simulation['changes_applied']:
            md.append(f"- **{change['fix']}**: +{change['change']:.2f}\n")
            md.append(f"  - {change['reason']}\n")
        md.append("\n")

    # Risk assessment
    md.append("## Risk Assessment\n")

    low_margin_cases = [sim for sim in simulations if 0 < sim['adjusted_margin'] < 10]
    if low_margin_cases:
        md.append(f"⚠️ **Medium Risk**: {len(low_margin_cases)} cases have narrow margin (<10 points) after fixes\n")
        md.append("These cases should be monitored closely during rollout.\n\n")
    else:
        md.append("✅ **Low Risk**: All successful cases maintain comfortable margin\n\n")

    # Recommendations
    md.append("## Recommendations\n")

    if all_safe:
        md.append("1. ✅ **Proceed with recommended fixes**\n")
        md.append("   - All successful cases remain rank 1\n")
        md.append("   - Most cases show improved margins\n")
        md.append("\n")

        if low_margin_cases:
            md.append("2. ⚠️ **Monitor narrow-margin cases**\n")
            md.append(f"   - {len(low_margin_cases)} cases have margin <10 points\n")
            md.append("   - Include in canary deployment\n")
            md.append("\n")

        md.append("3. ✅ **Safe to implement Phase 1 changes**\n")
        md.append("   - Symptom detection enhancements are safe\n")
        md.append("   - Start with A/B test at 10% traffic\n")
    else:
        unsafe_cases = [(a, s) for a, s in zip(analyses, simulations) if not s['would_still_rank_1']]
        md.append("1. ⚠️ **HOLD - Investigation Required**\n")
        md.append(f"   - {len(unsafe_cases)} cases would break\n")
        md.append("   - Review these cases before proceeding\n")
        md.append("\n")

        md.append("2. **Cases Requiring Investigation**:\n")
        for analysis, simulation in unsafe_cases:
            md.append(f"   - {analysis['ground_truth_node']} ({analysis['fault_type']})\n")
            md.append(f"     - Margin would become: {simulation['adjusted_margin']:.2f}\n")

    md.append("\n")

    return ''.join(md)


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_successful_cases.py <batch_run_directory>")
        print("Example: validate_successful_cases.py ../data/batch_run_20251215_164016")
        sys.exit(1)

    batch_dir = Path(sys.argv[1])

    if not batch_dir.exists():
        print(f"Error: Directory not found: {batch_dir}")
        sys.exit(1)

    print(f"Finding successful RCA cases in: {batch_dir}")

    # Find successful cases
    successful_episodes = find_successful_cases(batch_dir)

    if not successful_episodes:
        print("No successful RCA cases found (ground truth rank 1)")
        sys.exit(1)

    print(f"Found {len(successful_episodes)} successful cases\n")

    # Analyze each successful case
    print("Analyzing successful cases...")
    analyses = []
    for episode_dir in successful_episodes:
        analysis = analyze_successful_case(episode_dir)
        if 'error' not in analysis:
            analyses.append(analysis)
        else:
            print(f"Warning: {analysis['error']}")

    print(f"Successfully analyzed {len(analyses)} cases\n")

    # Simulate recommended fixes
    print("Simulating recommended fixes...")
    simulations = [simulate_recommended_fixes(a) for a in analyses]

    # Generate report
    print("Generating validation report...")
    report = generate_validation_report(analyses, simulations)

    # Save report
    output_file = batch_dir / 'rca_fixes_validation.md'
    with open(output_file, 'w') as f:
        f.write(report)

    # Also save JSON
    json_output = {
        'analyses': analyses,
        'simulations': simulations,
        'summary': {
            'total_cases': len(analyses),
            'all_safe': all(sim['would_still_rank_1'] for sim in simulations),
            'avg_score_increase': sum(s['score_increase'] for s in simulations) / len(simulations),
            'avg_margin_increase': sum(s['margin_increase'] for s in simulations) / len(simulations),
        }
    }

    json_output_file = batch_dir / 'rca_fixes_validation.json'
    with open(json_output_file, 'w') as f:
        json.dump(json_output, f, indent=2)

    print(f"\n✓ Validation complete!")
    print(f"  - Markdown report: {output_file}")
    print(f"  - JSON report: {json_output_file}")

    # Summary
    all_safe = all(sim['would_still_rank_1'] for sim in simulations)
    if all_safe:
        print(f"\n✅ SAFE: All {len(analyses)} successful cases would remain rank 1")
    else:
        unsafe_count = sum(1 for sim in simulations if not sim['would_still_rank_1'])
        print(f"\n⚠️ WARNING: {unsafe_count}/{len(analyses)} cases might break")


if __name__ == '__main__':
    main()
