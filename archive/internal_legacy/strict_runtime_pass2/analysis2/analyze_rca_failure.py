#!/usr/bin/env python3
"""
Analyze RCA failures to understand why ground truth was not ranked as #1.
Provides concrete parameter adjustment recommendations.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


def load_json(filepath: Path) -> Dict:
    """Load JSON file."""
    with open(filepath) as f:
        return json.load(f)


def get_candidate_by_node(candidates: List[Dict], node_id: str) -> Optional[Dict]:
    """Find candidate by node ID."""
    for c in candidates:
        if c['node'] == node_id:
            return c
    return None


def analyze_score_components(candidate: Dict) -> Dict[str, Any]:
    """Analyze individual score components."""
    return {
        'final_score': candidate.get('score', 0),
        'integrated_score': candidate.get('integrated_score', 0),
        'self_score': candidate.get('self_score', 0),
        'trace_score': candidate.get('trace_score', 0),
        'temporal_score': candidate.get('temporal_score', 0),
        'guilt_raw': candidate.get('guilt_raw', 0),
        'guilt_adjusted': candidate.get('guilt_adjusted', 0),
        'discount_factor': candidate.get('discount_factor', 1.0),
        'is_healthy': candidate.get('is_healthy', True),
        'health_filter_reason': candidate.get('health_filter_reason', None),
        'is_trace_authoritative': candidate.get('is_trace_authoritative', False),
    }


def analyze_trace_evidence(candidate: Dict) -> Dict[str, Any]:
    """Analyze trace-based evidence."""
    trace_info = candidate.get('trace_info', {})
    if not trace_info:
        return {'has_trace_data': False}

    return {
        'has_trace_data': True,
        'is_authoritative': trace_info.get('is_authoritative', False),
        'self_time_degradation': trace_info.get('self_time_degradation', 1.0),
        'total_time_degradation': trace_info.get('total_time_degradation', 1.0),
        'trace_score': trace_info.get('trace_score', 0),
        'reason': trace_info.get('reason', ''),
    }


def analyze_health_evidence(candidate: Dict) -> Dict[str, Any]:
    """Analyze health-based evidence."""
    health = candidate.get('health_metadata', {})
    return {
        'service_score': health.get('service_score', 0),
        'integrated_score': health.get('integrated_score', 0),
        'source': health.get('source', 'unknown'),
        'pattern': health.get('pattern', ''),
        'symptoms': candidate.get('symptoms', []),
        'symptom_count': len(candidate.get('symptoms', [])),
    }


def compare_with_top_ranked(ground_truth: Dict, top_candidates: List[Dict]) -> Dict[str, Any]:
    """Compare ground truth with top-ranked candidates."""
    comparisons = []

    for rank, candidate in enumerate(top_candidates[:5], 1):
        gt_scores = analyze_score_components(ground_truth)
        cand_scores = analyze_score_components(candidate)

        score_diffs = {}
        for key in ['integrated_score', 'self_score', 'trace_score', 'temporal_score']:
            score_diffs[key] = cand_scores[key] - gt_scores[key]

        comparisons.append({
            'rank': rank,
            'node': candidate['node'],
            'score': candidate['score'],
            'score_diff': candidate['score'] - ground_truth['score'],
            'component_diffs': score_diffs,
            'has_symptoms': len(candidate.get('symptoms', [])) > 0,
            'is_healthy': candidate.get('is_healthy', True),
        })

    return {'top_5_comparison': comparisons}


def validate_ground_truth(ground_truth: Dict, label: Dict) -> Dict[str, Any]:
    """Validate that ground truth actually shows signs of being faulty."""
    gt_scores = analyze_score_components(ground_truth)
    gt_trace = analyze_trace_evidence(ground_truth)
    gt_health = analyze_health_evidence(ground_truth)

    validation = {
        'is_valid': True,
        'confidence': 'high',
        'reasons': [],
        'evidence_score': 0,
    }

    evidence_score = 0

    # Check for symptoms
    if gt_health['symptom_count'] > 0:
        evidence_score += 3
        validation['reasons'].append(f"Has {gt_health['symptom_count']} symptoms detected")
    else:
        validation['reasons'].append("⚠️ No symptoms detected")

    # Check trace evidence
    if gt_trace.get('has_trace_data'):
        if gt_trace.get('is_authoritative'):
            degradation = gt_trace.get('self_time_degradation', 1.0)
            if degradation > 2.0:
                evidence_score += 5
                validation['reasons'].append(f"Strong trace evidence: {degradation:.1f}x degradation (authoritative)")
            else:
                evidence_score += 2
                validation['reasons'].append(f"Weak trace evidence: {degradation:.1f}x degradation (authoritative)")
        else:
            validation['reasons'].append("⚠️ Non-authoritative trace evidence (might be victim)")
    else:
        validation['reasons'].append("⚠️ No trace evidence")

    # Check health status
    if not gt_scores['is_healthy']:
        evidence_score += 2
        validation['reasons'].append("Marked as unhealthy by health filter")
    else:
        validation['reasons'].append("⚠️ Marked as healthy by health filter")

    # Check scores
    if gt_scores['integrated_score'] > 5.0:
        evidence_score += 2
        validation['reasons'].append(f"High integrated_score: {gt_scores['integrated_score']:.1f}")
    elif gt_scores['integrated_score'] > 0:
        evidence_score += 1
        validation['reasons'].append(f"Low integrated_score: {gt_scores['integrated_score']:.1f}")
    else:
        validation['reasons'].append("⚠️ Zero integrated_score")

    # Determine validity
    validation['evidence_score'] = evidence_score

    if evidence_score >= 8:
        validation['is_valid'] = True
        validation['confidence'] = 'high'
        validation['verdict'] = "✅ Strong evidence that ground truth is actually faulty"
    elif evidence_score >= 5:
        validation['is_valid'] = True
        validation['confidence'] = 'medium'
        validation['verdict'] = "⚠️ Moderate evidence of fault - RCA should catch this"
    elif evidence_score >= 2:
        validation['is_valid'] = False
        validation['confidence'] = 'low'
        validation['verdict'] = "⚠️ Weak evidence of fault - possibly invalid ground truth"
    else:
        validation['is_valid'] = False
        validation['confidence'] = 'very_low'
        validation['verdict'] = "❌ No evidence of fault - likely invalid ground truth label"

    return validation


def identify_root_causes(
    ground_truth: Dict,
    ground_truth_rank: Optional[int],
    top_candidates: List[Dict],
    label: Dict
) -> List[Dict[str, Any]]:
    """Identify root causes of RCA failure."""
    issues = []

    gt_scores = analyze_score_components(ground_truth)
    gt_trace = analyze_trace_evidence(ground_truth)
    gt_health = analyze_health_evidence(ground_truth)

    # Issue 1: Health filter marking as healthy despite evidence
    if gt_scores['is_healthy'] and gt_trace['has_trace_data']:
        if gt_trace['is_authoritative'] and gt_trace['self_time_degradation'] > 2.0:
            issues.append({
                'issue_type': 'health_filter_false_negative',
                'severity': 'critical',
                'description': (
                    f"Ground truth marked as HEALTHY despite authoritative trace showing "
                    f"{gt_trace['self_time_degradation']:.2f}x self-time degradation"
                ),
                'evidence': {
                    'is_healthy': gt_scores['is_healthy'],
                    'health_filter_reason': gt_scores['health_filter_reason'],
                    'is_trace_authoritative': gt_trace['is_authoritative'],
                    'self_time_degradation': gt_trace['self_time_degradation'],
                    'trace_score': gt_trace['trace_score'],
                },
                'impact': {
                    'integrated_score_lost': gt_scores['integrated_score'],
                    'actual_trace_score': gt_trace['trace_score'],
                    'potential_score_if_unhealthy': gt_trace['trace_score'] * 10,  # Estimate
                }
            })

    # Issue 2: Lack of symptoms
    if gt_health['symptom_count'] == 0:
        issues.append({
            'issue_type': 'missing_symptoms',
            'severity': 'high',
            'description': (
                f"Ground truth has NO symptoms detected, despite being the root cause. "
                f"Component type: {label.get('root_cause_role', 'unknown')}"
            ),
            'evidence': {
                'symptom_count': gt_health['symptom_count'],
                'component_role': label.get('root_cause_role'),
                'fault_type': label.get('fault_type'),
                'self_score': gt_scores['self_score'],
            },
            'impact': {
                'self_score_lost': 10.0 - gt_scores['self_score'],
            }
        })

    # Issue 3: Low integrated score
    if gt_scores['integrated_score'] < 5.0:
        issues.append({
            'issue_type': 'low_integrated_score',
            'severity': 'high',
            'description': (
                f"Ground truth has very low integrated_score ({gt_scores['integrated_score']:.2f}), "
                f"which heavily penalizes final ranking"
            ),
            'evidence': {
                'integrated_score': gt_scores['integrated_score'],
                'service_score': gt_health['service_score'],
                'source': gt_health['source'],
            },
            'impact': {
                'integrated_score_gap': 10.0 - gt_scores['integrated_score'],
            }
        })

    # Issue 4: Trace score not weighted enough
    if gt_trace['has_trace_data'] and gt_trace['is_authoritative']:
        top1 = top_candidates[0]
        top1_trace = analyze_trace_evidence(top1)

        if gt_trace['trace_score'] > top1_trace.get('trace_score', 0):
            issues.append({
                'issue_type': 'trace_score_underweighted',
                'severity': 'high',
                'description': (
                    f"Ground truth has authoritative trace evidence (score: {gt_trace['trace_score']}) "
                    f"but still ranked below {top1['node']} (trace score: {top1_trace.get('trace_score', 0)})"
                ),
                'evidence': {
                    'gt_trace_score': gt_trace['trace_score'],
                    'gt_is_authoritative': gt_trace['is_authoritative'],
                    'gt_self_time_degradation': gt_trace['self_time_degradation'],
                    'top1_trace_score': top1_trace.get('trace_score', 0),
                    'top1_integrated_score': top1.get('integrated_score', 0),
                },
                'impact': {
                    'score_gap': top1['score'] - ground_truth['score'],
                }
            })

    # Issue 5: False positives ranked higher
    for rank, candidate in enumerate(top_candidates[:5], 1):
        if candidate['node'] == ground_truth['node']:
            continue

        cand_trace = analyze_trace_evidence(candidate)

        # Check if top candidate has weaker evidence but higher score
        if cand_trace['has_trace_data']:
            if (not cand_trace['is_authoritative'] and
                gt_trace['is_authoritative'] and
                candidate['score'] > ground_truth['score']):
                issues.append({
                    'issue_type': 'false_positive_ranked_higher',
                    'severity': 'medium',
                    'description': (
                        f"{candidate['node']} ranked #{rank} with non-authoritative trace evidence, "
                        f"while ground truth has authoritative evidence"
                    ),
                    'evidence': {
                        'false_positive_node': candidate['node'],
                        'false_positive_rank': rank,
                        'false_positive_score': candidate['score'],
                        'false_positive_trace_authoritative': cand_trace['is_authoritative'],
                        'gt_trace_authoritative': gt_trace['is_authoritative'],
                    },
                    'impact': {
                        'score_gap': candidate['score'] - ground_truth['score'],
                    }
                })

    return issues


def generate_recommendations(issues: List[Dict], ground_truth: Dict, label: Dict) -> List[Dict]:
    """Generate concrete parameter adjustment recommendations."""
    recommendations = []

    issue_types = {issue['issue_type'] for issue in issues}

    # Recommendation 1: Override health filter for authoritative trace data
    if 'health_filter_false_negative' in issue_types:
        rec = {
            'recommendation_id': 'R1',
            'priority': 'critical',
            'category': 'health_filtering',
            'title': 'Disable health filter when authoritative trace evidence exists',
            'description': (
                'The health filter marked the root cause as HEALTHY despite authoritative trace '
                'data showing significant degradation. This is a critical flaw.'
            ),
            'parameter_adjustments': [
                {
                    'parameter': 'health_filter.override_on_authoritative_trace',
                    'current_value': False,
                    'recommended_value': True,
                    'rationale': (
                        'When is_trace_authoritative=True and shows degradation >2x, '
                        'ignore health filter completely'
                    ),
                },
                {
                    'parameter': 'health_filter.min_trace_degradation_to_override',
                    'current_value': None,
                    'recommended_value': 2.0,
                    'rationale': (
                        'Minimum self-time degradation multiplier to override health check'
                    ),
                },
            ],
            'expected_impact': (
                'Ground truth would not be marked as healthy, integrated_score would increase '
                'from 0.0 to potentially 10.0, raising final score significantly'
            ),
        }
        recommendations.append(rec)

    # Recommendation 2: Increase trace score weight
    if 'trace_score_underweighted' in issue_types:
        trace_evidence = None
        for issue in issues:
            if issue['issue_type'] == 'trace_score_underweighted':
                trace_evidence = issue['evidence']
                break

        if trace_evidence:
            rec = {
                'recommendation_id': 'R2',
                'priority': 'high',
                'category': 'scoring_weights',
                'title': 'Increase weight of authoritative trace scores',
                'description': (
                    'Authoritative trace evidence should have much higher weight in final scoring'
                ),
                'parameter_adjustments': [
                    {
                        'parameter': 'scoring.trace_score_multiplier',
                        'current_value': 1.0,
                        'recommended_value': 5.0,
                        'rationale': (
                            f'When is_trace_authoritative=True, multiply trace_score by 5x. '
                            f'This would boost ground truth score from {ground_truth["score"]:.2f} '
                            f'to ~{ground_truth["score"] + (trace_evidence["gt_trace_score"] * 4):.2f}'
                        ),
                    },
                    {
                        'parameter': 'scoring.authoritative_trace_bonus',
                        'current_value': 0,
                        'recommended_value': 50.0,
                        'rationale': (
                            'Add flat bonus for authoritative trace evidence with high degradation'
                        ),
                    },
                ],
                'expected_impact': (
                    f'Ground truth score would increase by ~{trace_evidence.get("score_gap", 0):.2f} points, '
                    f'potentially reaching rank 1'
                ),
            }
            recommendations.append(rec)

    # Recommendation 3: Improve symptom detection for specific component types
    if 'missing_symptoms' in issue_types:
        component_role = label.get('root_cause_role', 'unknown')
        fault_type = label.get('fault_type', 'unknown')

        rec = {
            'recommendation_id': 'R3',
            'priority': 'high',
            'category': 'symptom_detection',
            'title': f'Improve symptom detection for {component_role} components',
            'description': (
                f'The root cause ({component_role}) showed no symptoms despite being faulty. '
                f'Fault type: {fault_type}'
            ),
            'parameter_adjustments': [
                {
                    'parameter': f'symptom_detection.{component_role}.enable_indirect_signals',
                    'current_value': False,
                    'recommended_value': True,
                    'rationale': (
                        f'For {component_role} components, look at downstream impact and '
                        f'trace data as symptoms, not just direct metrics'
                    ),
                },
                {
                    'parameter': f'symptom_detection.{component_role}.trace_as_symptom_threshold',
                    'current_value': None,
                    'recommended_value': 2.0,
                    'rationale': (
                        f'If trace shows >2x degradation for {component_role}, count as symptom'
                    ),
                },
            ],
            'expected_impact': (
                'Ground truth would have detected symptoms, raising self_score from '
                f'{ground_truth.get("self_score", 0):.2f} to ~10.0'
            ),
        }
        recommendations.append(rec)

    # Recommendation 4: Penalize non-authoritative trace more heavily
    if 'false_positive_ranked_higher' in issue_types:
        rec = {
            'recommendation_id': 'R4',
            'priority': 'medium',
            'category': 'scoring_weights',
            'title': 'Reduce scores for non-authoritative trace evidence',
            'description': (
                'Services with non-authoritative trace degradation are likely victims, '
                'not root causes. They should be penalized more.'
            ),
            'parameter_adjustments': [
                {
                    'parameter': 'scoring.non_authoritative_trace_penalty',
                    'current_value': 1.0,
                    'recommended_value': 0.3,
                    'rationale': (
                        'Multiply trace_score by 0.3 when is_authoritative=False to reduce '
                        'victim component scores'
                    ),
                },
                {
                    'parameter': 'scoring.victim_detection_from_trace',
                    'current_value': False,
                    'recommended_value': True,
                    'rationale': (
                        'If total_time_degradation >> self_time_degradation, mark as victim'
                    ),
                },
            ],
            'expected_impact': (
                'False positive candidates would have reduced scores, improving ground truth ranking'
            ),
        }
        recommendations.append(rec)

    # Recommendation 5: Overall scoring formula adjustment
    rec = {
        'recommendation_id': 'R5',
        'priority': 'medium',
        'category': 'scoring_formula',
        'title': 'Revise final score calculation to prioritize authoritative evidence',
        'description': (
            'The current scoring formula does not adequately prioritize authoritative '
            'trace evidence over symptom-based health scores'
        ),
        'parameter_adjustments': [
            {
                'parameter': 'scoring.formula',
                'current_value': 'integrated_score + trace_score + temporal_score + ...',
                'recommended_value': (
                    'if is_trace_authoritative and trace_degradation > threshold:\n'
                    '  score = trace_score * 5 + 50\n'
                    'else:\n'
                    '  score = integrated_score + trace_score + temporal_score + ...'
                ),
                'rationale': (
                    'Use separate scoring path for authoritative trace evidence'
                ),
            },
        ],
        'expected_impact': (
            'Ground truth with authoritative trace evidence would be scored much higher'
        ),
    }
    recommendations.append(rec)

    return recommendations


def calculate_adjusted_scores(
    ground_truth: Dict,
    top_candidates: List[Dict],
    recommendations: List[Dict]
) -> Dict[str, Any]:
    """Calculate what the scores would be with recommended adjustments."""
    gt_trace = analyze_trace_evidence(ground_truth)

    # Simulate applying recommendations
    adjusted_gt_score = ground_truth['score']

    # Apply R1: Override health filter
    if gt_trace.get('has_trace_data') and gt_trace.get('is_authoritative') and gt_trace.get('self_time_degradation', 0) > 2.0:
        # Add back integrated_score that was lost
        adjusted_gt_score += 10.0  # Assume would get full 10.0 integrated_score

    # Apply R2: Increase trace weight
    if gt_trace.get('has_trace_data') and gt_trace.get('is_authoritative'):
        # Multiply trace_score by 5 and add bonus
        adjusted_gt_score += (gt_trace.get('trace_score', 0) * 4)  # *4 because already counted once
        adjusted_gt_score += 50.0  # Bonus

    # Apply R3: Add symptoms
    if len(ground_truth.get('symptoms', [])) == 0:
        adjusted_gt_score += 10.0  # Add self_score

    # Calculate adjusted ranks
    adjusted_scores = [(ground_truth['node'], adjusted_gt_score, 'ground_truth')]

    for cand in top_candidates:
        cand_trace = analyze_trace_evidence(cand)
        cand_score = cand['score']

        # Apply R4: Penalize non-authoritative
        if cand_trace.get('has_trace_data') and not cand_trace.get('is_authoritative'):
            # Reduce trace contribution
            cand_score -= cand_trace.get('trace_score', 0) * 0.7  # Remove 70% of trace score

        adjusted_scores.append((cand['node'], cand_score, 'candidate'))

    # Sort by adjusted score
    adjusted_scores.sort(key=lambda x: x[1], reverse=True)

    # Find new rank of ground truth
    new_rank = None
    for rank, (node, score, node_type) in enumerate(adjusted_scores, 1):
        if node_type == 'ground_truth':
            new_rank = rank
            break

    return {
        'adjusted_scores': [
            {'node': node, 'adjusted_score': score, 'type': node_type}
            for node, score, node_type in adjusted_scores[:10]
        ],
        'ground_truth_current_score': ground_truth['score'],
        'ground_truth_adjusted_score': adjusted_gt_score,
        'ground_truth_current_rank': None,  # Not in top 5
        'ground_truth_projected_rank': new_rank,
        'score_improvement': adjusted_gt_score - ground_truth['score'],
    }


def generate_report(
    episode_dir: Path,
    rca_data: Dict,
    label: Dict,
    topology: Dict
) -> Dict[str, Any]:
    """Generate comprehensive RCA failure analysis report."""

    ground_truth_node = rca_data['ground_truth']
    top_k = rca_data.get('top_k', 5)
    found_in_top_k = rca_data.get('found_in_top_k', False)
    rank = rca_data.get('rank')

    top_candidates = rca_data.get('top_candidates', [])
    all_candidates = rca_data.get('all_candidates', [])

    # Find ground truth in all_candidates
    ground_truth = get_candidate_by_node(all_candidates, ground_truth_node)

    if not ground_truth:
        return {
            'error': f'Ground truth node "{ground_truth_node}" not found in candidates'
        }

    # Get actual rank
    actual_rank = None
    for i, cand in enumerate(all_candidates, 1):
        if cand['node'] == ground_truth_node:
            actual_rank = i
            break

    # Validate ground truth
    gt_validation = validate_ground_truth(ground_truth, label)

    # Analyze components
    gt_scores = analyze_score_components(ground_truth)
    gt_trace = analyze_trace_evidence(ground_truth)
    gt_health = analyze_health_evidence(ground_truth)
    comparison = compare_with_top_ranked(ground_truth, top_candidates)

    # Identify root causes (only if ground truth is valid)
    if gt_validation['is_valid']:
        issues = identify_root_causes(ground_truth, actual_rank, top_candidates, label)
    else:
        issues = []

    # Generate recommendations
    recommendations = generate_recommendations(issues, ground_truth, label)

    # Calculate adjusted scores
    projected = calculate_adjusted_scores(ground_truth, all_candidates, recommendations)

    report = {
        'episode': label.get('episode', 0),
        'scenario': label.get('scenario', 'unknown'),
        'fault_type': label.get('fault_type', 'unknown'),
        'ground_truth': ground_truth_node,
        'ground_truth_role': label.get('root_cause_role', 'unknown'),
        'ground_truth_validation': gt_validation,
        'rca_summary': {
            'found_in_top_k': found_in_top_k,
            'top_k': top_k,
            'actual_rank': actual_rank,
            'ground_truth_score': ground_truth['score'],
            'top1_node': top_candidates[0]['node'] if top_candidates else None,
            'top1_score': top_candidates[0]['score'] if top_candidates else None,
            'score_gap': top_candidates[0]['score'] - ground_truth['score'] if top_candidates else None,
        },
        'ground_truth_analysis': {
            'score_components': gt_scores,
            'trace_evidence': gt_trace,
            'health_evidence': gt_health,
        },
        'comparison_with_top_ranked': comparison,
        'root_cause_issues': issues,
        'recommendations': recommendations,
        'projected_impact': projected,
        'summary': {
            'ground_truth_valid': gt_validation['is_valid'],
            'ground_truth_confidence': gt_validation['confidence'],
            'issue_count': len(issues),
            'critical_issues': len([i for i in issues if i['severity'] == 'critical']),
            'high_priority_recommendations': len([r for r in recommendations if r['priority'] in ['critical', 'high']]),
            'projected_rank_improvement': f"Rank {actual_rank} -> Rank {projected['ground_truth_projected_rank']}" if gt_validation['is_valid'] else "N/A (invalid ground truth)",
            'projected_score_improvement': f"{ground_truth['score']:.2f} -> {projected['ground_truth_adjusted_score']:.2f} (+{projected['score_improvement']:.2f})" if gt_validation['is_valid'] else "N/A (invalid ground truth)",
        }
    }

    return report


def format_report_markdown(report: Dict) -> str:
    """Format report as markdown."""
    md = []

    md.append(f"# RCA Failure Analysis Report\n")
    md.append(f"**Episode**: {report['episode']} | **Scenario**: {report['scenario']}\n")
    md.append(f"**Fault Type**: {report['fault_type']} | **Ground Truth**: {report['ground_truth']} ({report['ground_truth_role']})\n")
    md.append("\n---\n")

    # Ground Truth Validation
    validation = report['ground_truth_validation']
    md.append("## Ground Truth Validation\n")
    md.append(f"**{validation['verdict']}**\n\n")
    md.append(f"- **Validation Status**: {'✅ Valid' if validation['is_valid'] else '❌ Invalid/Questionable'}\n")
    md.append(f"- **Confidence**: {validation['confidence']}\n")
    md.append(f"- **Evidence Score**: {validation['evidence_score']}/12\n")
    md.append("\n**Evidence Analysis**:\n")
    for reason in validation['reasons']:
        md.append(f"- {reason}\n")
    md.append("\n")

    if not validation['is_valid']:
        md.append("⚠️ **WARNING**: Ground truth shows insufficient evidence of being faulty. ")
        md.append("This may be an invalid ground truth label rather than an RCA failure. ")
        md.append("We should not optimize RCA for cases where ground truth is not actually faulty.\n\n")
        md.append("**Recommendation**: Exclude this case from RCA optimization metrics.\n\n")

    md.append("---\n")

    # Summary
    md.append("## Executive Summary\n")
    summary = report['rca_summary']
    md.append(f"- **RCA Result**: Ground truth ranked **#{summary['actual_rank']}** (not in top-{summary['top_k']})\n")
    md.append(f"- **Score Gap**: {summary['ground_truth_score']:.2f} vs {summary['top1_score']:.2f} (top-ranked: {summary['top1_node']})\n")

    if validation['is_valid']:
        md.append(f"- **Issues Found**: {report['summary']['issue_count']} ({report['summary']['critical_issues']} critical)\n")
        md.append(f"- **Projected Improvement**: {report['summary']['projected_rank_improvement']}\n")
        md.append(f"- **Score Improvement**: {report['summary']['projected_score_improvement']}\n")
    else:
        md.append(f"- **Issues Found**: N/A (invalid ground truth)\n")
        md.append(f"- **Projected Improvement**: N/A (should not optimize for invalid ground truth)\n")

    md.append("\n")

    # Ground truth analysis
    md.append("## Ground Truth Analysis\n")
    md.append("### Score Breakdown\n")
    scores = report['ground_truth_analysis']['score_components']
    md.append(f"- **Final Score**: {scores['final_score']:.2f}\n")
    md.append(f"- **Integrated Score**: {scores['integrated_score']:.2f}\n")
    md.append(f"- **Self Score**: {scores['self_score']:.2f}\n")
    md.append(f"- **Trace Score**: {scores['trace_score']:.2f}\n")
    md.append(f"- **Temporal Score**: {scores['temporal_score']:.2f}\n")
    md.append(f"- **Is Healthy**: {scores['is_healthy']} ({scores['health_filter_reason']})\n")
    md.append(f"- **Is Trace Authoritative**: {scores['is_trace_authoritative']}\n")
    md.append("\n")

    # Trace evidence
    trace = report['ground_truth_analysis']['trace_evidence']
    if trace['has_trace_data']:
        md.append("### Trace Evidence\n")
        md.append(f"- **Authoritative**: {trace['is_authoritative']}\n")
        md.append(f"- **Self-Time Degradation**: {trace['self_time_degradation']:.2f}x\n")
        md.append(f"- **Total-Time Degradation**: {trace['total_time_degradation']:.2f}x\n")
        md.append(f"- **Reason**: {trace['reason']}\n")
        md.append("\n")

    # Health evidence
    health = report['ground_truth_analysis']['health_evidence']
    md.append("### Health Evidence\n")
    md.append(f"- **Symptom Count**: {health['symptom_count']}\n")
    md.append(f"- **Symptoms**: {', '.join(health['symptoms']) if health['symptoms'] else 'None'}\n")
    md.append(f"- **Pattern**: {health['pattern']}\n")
    md.append("\n")

    # Root cause issues
    md.append("## Root Cause Issues\n")
    for i, issue in enumerate(report['root_cause_issues'], 1):
        md.append(f"### Issue {i}: {issue['issue_type']} ({issue['severity']})\n")
        md.append(f"{issue['description']}\n\n")
        md.append("**Evidence**:\n")
        for key, value in issue['evidence'].items():
            md.append(f"- `{key}`: {value}\n")
        md.append("\n**Impact**:\n")
        for key, value in issue['impact'].items():
            md.append(f"- `{key}`: {value}\n")
        md.append("\n")

    # Recommendations
    md.append("## Recommendations\n")
    for rec in report['recommendations']:
        md.append(f"### {rec['recommendation_id']}: {rec['title']} (Priority: {rec['priority']})\n")
        md.append(f"**Category**: {rec['category']}\n\n")
        md.append(f"{rec['description']}\n\n")
        md.append("**Parameter Adjustments**:\n")
        for param in rec['parameter_adjustments']:
            md.append(f"- **`{param['parameter']}`**\n")
            md.append(f"  - Current: `{param['current_value']}`\n")
            md.append(f"  - Recommended: `{param['recommended_value']}`\n")
            md.append(f"  - Rationale: {param['rationale']}\n")
        md.append(f"\n**Expected Impact**: {rec['expected_impact']}\n")
        md.append("\n")

    # Projected impact
    md.append("## Projected Impact with Adjustments\n")
    proj = report['projected_impact']
    md.append(f"- **Current Score**: {proj['ground_truth_current_score']:.2f}\n")
    md.append(f"- **Adjusted Score**: {proj['ground_truth_adjusted_score']:.2f}\n")
    md.append(f"- **Score Improvement**: +{proj['score_improvement']:.2f}\n")
    md.append(f"- **Projected Rank**: {proj['ground_truth_projected_rank']}\n")
    md.append("\n**Top 10 with Adjusted Scores**:\n")
    for i, entry in enumerate(proj['adjusted_scores'], 1):
        marker = " **(GROUND TRUTH)**" if entry['type'] == 'ground_truth' else ""
        md.append(f"{i}. {entry['node']}: {entry['adjusted_score']:.2f}{marker}\n")
    md.append("\n")

    return ''.join(md)


def main():
    if len(sys.argv) != 2:
        print("Usage: analyze_rca_failure.py <episode_directory>")
        print("Example: analyze_rca_failure.py ../data/batch_run_20251215_164016/data_20251215_170338/ep_0")
        sys.exit(1)

    episode_dir = Path(sys.argv[1])

    if not episode_dir.exists():
        print(f"Error: Directory not found: {episode_dir}")
        sys.exit(1)

    # Load data
    rca_file = episode_dir / 'rca_analysis.json'
    label_file = episode_dir / 'label.json'
    topology_file = episode_dir / 'topology.json'

    if not rca_file.exists():
        print(f"Error: rca_analysis.json not found in {episode_dir}")
        sys.exit(1)

    rca_data = load_json(rca_file)
    label = load_json(label_file) if label_file.exists() else {}
    topology = load_json(topology_file) if topology_file.exists() else {}

    # Generate report
    print("Analyzing RCA failure...")
    report = generate_report(episode_dir, rca_data, label, topology)

    if 'error' in report:
        print(f"Error: {report['error']}")
        sys.exit(1)

    # Format as markdown
    markdown = format_report_markdown(report)

    # Save report
    output_file = episode_dir / 'rca_failure_analysis.md'
    with open(output_file, 'w') as f:
        f.write(markdown)

    # Also save JSON
    json_output_file = episode_dir / 'rca_failure_analysis.json'
    with open(json_output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n✓ Analysis complete!")
    print(f"  - Markdown report: {output_file}")
    print(f"  - JSON report: {json_output_file}")
    print(f"\nSummary:")
    print(f"  - Ground truth: {report['ground_truth']} (ranked #{report['rca_summary']['actual_rank']})")

    validation = report['ground_truth_validation']
    if validation['is_valid']:
        print(f"  - Ground truth validation: ✅ Valid ({validation['confidence']} confidence, evidence: {validation['evidence_score']}/12)")
        print(f"  - Found {report['summary']['issue_count']} issues ({report['summary']['critical_issues']} critical)")
        print(f"  - {report['summary']['high_priority_recommendations']} high-priority recommendations")
        print(f"  - Projected improvement: {report['summary']['projected_rank_improvement']}")
        print(f"  - Score improvement: {report['summary']['projected_score_improvement']}")
    else:
        print(f"  - Ground truth validation: ❌ INVALID ({validation['confidence']} confidence, evidence: {validation['evidence_score']}/12)")
        print(f"  - {validation['verdict']}")
        print(f"  - ⚠️ Should NOT optimize RCA for this case (invalid ground truth)")


if __name__ == '__main__':
    main()
