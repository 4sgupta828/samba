#!/usr/bin/env python3
"""
Aggregate and summarize RCA failure analyses across multiple episodes.
"""

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any


def load_analysis_files(batch_dir: Path) -> List[Dict]:
    """Load all rca_failure_analysis.json files from batch directory."""
    analyses = []

    for analysis_file in batch_dir.rglob("rca_failure_analysis.json"):
        try:
            with open(analysis_file) as f:
                data = json.load(f)
                data['_file'] = str(analysis_file)
                analyses.append(data)
        except Exception as e:
            print(f"Warning: Could not load {analysis_file}: {e}", file=sys.stderr)

    return analyses


def aggregate_statistics(analyses: List[Dict]) -> Dict[str, Any]:
    """Aggregate statistics across all analyses."""
    stats = {
        'total_failures': len(analyses),
        'fault_types': Counter(),
        'component_roles': Counter(),
        'scenarios': Counter(),
        'issue_types': Counter(),
        'issue_severity': Counter(),
        'recommendation_priorities': Counter(),
        'recommendation_categories': Counter(),
        'actual_ranks': [],
        'projected_ranks': [],
        'score_gaps': [],
        'score_improvements': [],
    }

    for analysis in analyses:
        # Fault information
        stats['fault_types'][analysis.get('fault_type', 'unknown')] += 1
        stats['component_roles'][analysis.get('ground_truth_role', 'unknown')] += 1
        stats['scenarios'][analysis.get('scenario', 'unknown')] += 1

        # Ranking
        actual_rank = analysis['rca_summary'].get('actual_rank')
        if actual_rank:
            stats['actual_ranks'].append(actual_rank)

        projected_rank = analysis['projected_impact'].get('ground_truth_projected_rank')
        if projected_rank:
            stats['projected_ranks'].append(projected_rank)

        score_gap = analysis['rca_summary'].get('score_gap')
        if score_gap:
            stats['score_gaps'].append(score_gap)

        score_improvement = analysis['projected_impact'].get('score_improvement')
        if score_improvement:
            stats['score_improvements'].append(score_improvement)

        # Issues
        for issue in analysis.get('root_cause_issues', []):
            stats['issue_types'][issue['issue_type']] += 1
            stats['issue_severity'][issue['severity']] += 1

        # Recommendations
        for rec in analysis.get('recommendations', []):
            stats['recommendation_priorities'][rec['priority']] += 1
            stats['recommendation_categories'][rec['category']] += 1

    return stats


def identify_common_patterns(analyses: List[Dict]) -> Dict[str, Any]:
    """Identify common patterns across failures."""
    patterns = {
        'common_issue_combinations': defaultdict(int),
        'fault_type_to_issues': defaultdict(lambda: defaultdict(int)),
        'component_role_to_issues': defaultdict(lambda: defaultdict(int)),
        'high_impact_recommendations': Counter(),
    }

    for analysis in analyses:
        # Issue combinations
        issue_types = tuple(sorted([i['issue_type'] for i in analysis.get('root_cause_issues', [])]))
        patterns['common_issue_combinations'][issue_types] += 1

        # Fault type correlations
        fault_type = analysis.get('fault_type', 'unknown')
        for issue in analysis.get('root_cause_issues', []):
            patterns['fault_type_to_issues'][fault_type][issue['issue_type']] += 1

        # Component role correlations
        component_role = analysis.get('ground_truth_role', 'unknown')
        for issue in analysis.get('root_cause_issues', []):
            patterns['component_role_to_issues'][component_role][issue['issue_type']] += 1

        # High impact recommendations
        for rec in analysis.get('recommendations', []):
            if rec['priority'] in ['critical', 'high']:
                patterns['high_impact_recommendations'][rec['recommendation_id'] + ': ' + rec['title']] += 1

    return patterns


def generate_summary_report(
    analyses: List[Dict],
    stats: Dict[str, Any],
    patterns: Dict[str, Any]
) -> str:
    """Generate comprehensive summary report."""
    md = []

    md.append("# RCA Failure Analysis Summary Report\n")
    md.append(f"**Total Failures Analyzed**: {stats['total_failures']}\n")
    md.append("\n---\n")

    # Overall Statistics
    md.append("## Overall Statistics\n")

    if stats['actual_ranks']:
        avg_actual_rank = sum(stats['actual_ranks']) / len(stats['actual_ranks'])
        md.append(f"- **Average Actual Rank**: {avg_actual_rank:.1f}\n")

    if stats['projected_ranks']:
        avg_projected_rank = sum(stats['projected_ranks']) / len(stats['projected_ranks'])
        md.append(f"- **Average Projected Rank**: {avg_projected_rank:.1f}\n")

    if stats['score_gaps']:
        avg_score_gap = sum(stats['score_gaps']) / len(stats['score_gaps'])
        md.append(f"- **Average Score Gap**: {avg_score_gap:.2f}\n")

    if stats['score_improvements']:
        avg_score_improvement = sum(stats['score_improvements']) / len(stats['score_improvements'])
        md.append(f"- **Average Score Improvement**: {avg_score_improvement:.2f}\n")

    md.append("\n")

    # Fault Types
    md.append("## Failure Breakdown by Fault Type\n")
    for fault_type, count in stats['fault_types'].most_common():
        pct = (count / stats['total_failures']) * 100
        md.append(f"- **{fault_type}**: {count} ({pct:.1f}%)\n")
    md.append("\n")

    # Component Roles
    md.append("## Failure Breakdown by Component Role\n")
    for role, count in stats['component_roles'].most_common():
        pct = (count / stats['total_failures']) * 100
        md.append(f"- **{role}**: {count} ({pct:.1f}%)\n")
    md.append("\n")

    # Issue Types
    md.append("## Most Common Issues\n")
    for issue_type, count in stats['issue_types'].most_common(10):
        pct = (count / stats['total_failures']) * 100
        md.append(f"- **{issue_type}**: {count} occurrences ({pct:.1f}% of failures)\n")
    md.append("\n")

    # Issue Severity
    md.append("## Issue Severity Distribution\n")
    for severity, count in stats['issue_severity'].most_common():
        md.append(f"- **{severity.capitalize()}**: {count}\n")
    md.append("\n")

    # Recommendation Priorities
    md.append("## Recommendation Priorities\n")
    for priority, count in stats['recommendation_priorities'].most_common():
        md.append(f"- **{priority.capitalize()}**: {count}\n")
    md.append("\n")

    # Common Issue Combinations
    md.append("## Common Issue Combinations\n")
    md.append("Issues that frequently occur together:\n\n")
    for combo, count in sorted(patterns['common_issue_combinations'].items(), key=lambda x: x[1], reverse=True)[:10]:
        if len(combo) > 1:
            pct = (count / stats['total_failures']) * 100
            md.append(f"- {count} failures ({pct:.1f}%):\n")
            for issue in combo:
                md.append(f"  - {issue}\n")
            md.append("\n")
    md.append("\n")

    # Fault Type Correlations
    md.append("## Issue Patterns by Fault Type\n")
    for fault_type, issues in patterns['fault_type_to_issues'].items():
        md.append(f"### {fault_type}\n")
        total_for_fault = sum(issues.values())
        for issue, count in sorted(issues.items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = (count / total_for_fault) * 100
            md.append(f"- **{issue}**: {count} ({pct:.1f}%)\n")
        md.append("\n")

    # Component Role Correlations
    md.append("## Issue Patterns by Component Role\n")
    for role, issues in patterns['component_role_to_issues'].items():
        md.append(f"### {role}\n")
        total_for_role = sum(issues.values())
        for issue, count in sorted(issues.items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = (count / total_for_role) * 100
            md.append(f"- **{issue}**: {count} ({pct:.1f}%)\n")
        md.append("\n")

    # High Impact Recommendations
    md.append("## Most Recommended Fixes (Critical/High Priority)\n")
    md.append("Recommendations that appear most frequently:\n\n")
    for rec, count in patterns['high_impact_recommendations'].most_common(10):
        pct = (count / stats['total_failures']) * 100
        md.append(f"{count}. **{rec}** ({pct:.1f}% of failures)\n")
    md.append("\n")

    # Recommendation Categories
    md.append("## Recommendation Categories\n")
    for category, count in stats['recommendation_categories'].most_common():
        md.append(f"- **{category}**: {count}\n")
    md.append("\n")

    # Top Priority Actions
    md.append("## Top Priority Actions\n")
    md.append("Based on frequency and impact, these are the most critical fixes:\n\n")

    # Get top 5 most common critical/high priority recommendations
    top_recs = patterns['high_impact_recommendations'].most_common(5)
    for i, (rec, count) in enumerate(top_recs, 1):
        pct = (count / stats['total_failures']) * 100
        md.append(f"{i}. {rec}\n")
        md.append(f"   - Affects {pct:.1f}% of failures ({count}/{stats['total_failures']})\n")
    md.append("\n")

    # Individual Failure Details
    md.append("## Individual Failure Details\n")
    md.append("| Episode | Fault Type | Ground Truth | Actual Rank | Projected Rank | Score Gap | Score Improvement |\n")
    md.append("|---------|------------|--------------|-------------|----------------|-----------|-------------------|\n")

    for analysis in sorted(analyses, key=lambda x: x['rca_summary'].get('actual_rank', 999)):
        ep = analysis.get('episode', '?')
        fault = analysis.get('fault_type', '?')[:20]
        gt = analysis.get('ground_truth', '?')[:20]
        actual = analysis['rca_summary'].get('actual_rank', '?')
        projected = analysis['projected_impact'].get('ground_truth_projected_rank', '?')
        gap = analysis['rca_summary'].get('score_gap', 0)
        improvement = analysis['projected_impact'].get('score_improvement', 0)

        md.append(f"| {ep} | {fault} | {gt} | {actual} | {projected} | {gap:.2f} | {improvement:.2f} |\n")

    md.append("\n")

    return ''.join(md)


def main():
    if len(sys.argv) != 2:
        print("Usage: summarize_failures.py <batch_run_directory>")
        print("Example: summarize_failures.py ../data/batch_run_20251215_164016")
        sys.exit(1)

    batch_dir = Path(sys.argv[1])

    if not batch_dir.exists():
        print(f"Error: Directory not found: {batch_dir}")
        sys.exit(1)

    print(f"Loading RCA failure analyses from: {batch_dir}")

    # Load all analyses
    analyses = load_analysis_files(batch_dir)

    if not analyses:
        print("No RCA failure analyses found. Run analyze_rca_failure.py first.")
        sys.exit(1)

    print(f"Found {len(analyses)} failure analyses\n")

    # Aggregate statistics
    print("Aggregating statistics...")
    stats = aggregate_statistics(analyses)

    # Identify patterns
    print("Identifying patterns...")
    patterns = identify_common_patterns(analyses)

    # Generate report
    print("Generating summary report...")
    report = generate_summary_report(analyses, stats, patterns)

    # Save report
    output_file = batch_dir / 'rca_failures_summary.md'
    with open(output_file, 'w') as f:
        f.write(report)

    # Also save JSON
    def serialize_dict(d):
        """Convert non-serializable types to JSON-compatible format."""
        if isinstance(d, (Counter, defaultdict)):
            return {str(k): v for k, v in d.items()}
        elif isinstance(d, dict):
            return {str(k): serialize_dict(v) if isinstance(v, (dict, Counter, defaultdict)) else v
                    for k, v in d.items()}
        else:
            return d

    json_output = {
        'statistics': {
            k: serialize_dict(v) if isinstance(v, (Counter, dict)) else v
            for k, v in stats.items()
        },
        'patterns': {
            k: serialize_dict(v) if isinstance(v, (Counter, defaultdict, dict)) else v
            for k, v in patterns.items()
        },
    }

    json_output_file = batch_dir / 'rca_failures_summary.json'
    with open(json_output_file, 'w') as f:
        json.dump(json_output, f, indent=2)

    print(f"\n✓ Summary complete!")
    print(f"  - Markdown report: {output_file}")
    print(f"  - JSON report: {json_output_file}")
    print(f"\nKey Findings:")
    print(f"  - {len(analyses)} failures analyzed")
    print(f"  - {len(stats['issue_types'])} unique issue types")
    print(f"  - {len(stats['fault_types'])} fault types")
    print(f"  - Most common issue: {stats['issue_types'].most_common(1)[0][0] if stats['issue_types'] else 'N/A'}")


if __name__ == '__main__':
    main()
