#!/usr/bin/env python3
"""
Systematic RCA Pattern Analysis

This script analyzes all RCA results across batches to:
1. Validate ground truth (check if fault injection was strong enough)
2. Extract all scoring parameters for each fault
3. Identify global patterns in successful vs failed detections
4. Generate data-driven recommendations for scoring adjustments
"""

import json
import os
import csv
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any
import pandas as pd


# Health threshold for valid fault injection
# Below this, consider it noise/normal fluctuation
HEALTH_THRESHOLD_VALID_FAULT = 2.0  # Minimum health score to consider fault real


class RCAPatternAnalyzer:
    def __init__(self, batch_dirs: List[str]):
        self.batch_dirs = batch_dirs
        self.episodes = []
        self.results = []

    def analyze_all_batches(self):
        """Load and analyze all episodes from all batches."""
        print("=" * 80)
        print("RCA PATTERN ANALYSIS")
        print("=" * 80)

        # Step 1: Load all episodes
        for batch_dir in self.batch_dirs:
            self._load_batch(batch_dir)

        print(f"\nLoaded {len(self.episodes)} episodes")

        # Step 2: Validate ground truth and extract parameters
        for ep in self.episodes:
            result = self._analyze_episode(ep)
            self.results.append(result)

        # Step 3: Generate CSV
        self._write_csv()

        # Step 4: Global pattern analysis
        self._analyze_patterns()

        # Step 5: Generate recommendations
        self._generate_recommendations()

    def _load_batch(self, batch_dir: str):
        """Load all episodes from a batch directory."""
        batch_path = Path(batch_dir)
        if not batch_path.exists():
            print(f"Warning: Batch directory not found: {batch_dir}")
            return

        for ep_dir in sorted(batch_path.iterdir()):
            if not ep_dir.name.startswith('data_'):
                continue

            label_file = ep_dir / 'ep_0' / 'label.json'
            rca_file = ep_dir / 'ep_0' / 'rca_analysis.json'

            if label_file.exists() and rca_file.exists():
                try:
                    with open(label_file) as f:
                        label = json.load(f)
                    with open(rca_file) as f:
                        rca = json.load(f)

                    self.episodes.append({
                        'path': str(ep_dir),
                        'batch': batch_path.name,
                        'label': label,
                        'rca': rca
                    })
                except Exception as e:
                    print(f"Error loading {ep_dir}: {e}")

    def _analyze_episode(self, ep: Dict) -> Dict[str, Any]:
        """Analyze a single episode and extract all relevant parameters."""
        label = ep['label']
        rca = ep['rca']

        fault_type = label.get('fault_type')
        ground_truth = rca.get('ground_truth')
        rank = rca.get('rank')

        # Find ground truth in candidates
        gt_candidate = None
        rank1_candidate = None

        top_candidates = rca.get('top_candidates', [])
        if top_candidates:
            rank1_candidate = top_candidates[0]
            gt_candidate = next((c for c in top_candidates if c['node'] == ground_truth), None)

        # Extract ground truth parameters
        if gt_candidate:
            gt_health = gt_candidate.get('score_composition', {}).get('base_health', {}).get('raw', 0)
            gt_score = gt_candidate.get('score', 0)
            gt_physics = gt_candidate.get('score_composition', {}).get('physics_coverage', {}).get('raw', 0)
            gt_semantic = gt_candidate.get('score_composition', {}).get('semantic_bonus', {}).get('points', 0)
            gt_is_primary = gt_candidate.get('score_composition', {}).get('semantic_bonus', {}).get('is_primary', False)
            gt_supplements = gt_candidate.get('score_composition', {}).get('supplements', {})
            gt_health_meta = gt_candidate.get('health_metadata', {})
        else:
            # Ground truth not in candidates
            gt_health = 0
            gt_score = 0
            gt_physics = 0
            gt_semantic = 0
            gt_is_primary = False
            gt_supplements = {}
            gt_health_meta = {}

        # Extract rank 1 parameters for comparison
        if rank1_candidate:
            r1_health = rank1_candidate.get('score_composition', {}).get('base_health', {}).get('raw', 0)
            r1_score = rank1_candidate.get('score', 0)
            r1_physics = rank1_candidate.get('score_composition', {}).get('physics_coverage', {}).get('raw', 0)
            r1_semantic = rank1_candidate.get('score_composition', {}).get('semantic_bonus', {}).get('points', 0)
            r1_is_primary = rank1_candidate.get('score_composition', {}).get('semantic_bonus', {}).get('is_primary', False)
            r1_node = rank1_candidate.get('node', 'unknown')
        else:
            r1_health = 0
            r1_score = 0
            r1_physics = 0
            r1_semantic = 0
            r1_is_primary = False
            r1_node = 'none'

        # Validate ground truth
        is_valid_fault = gt_health >= HEALTH_THRESHOLD_VALID_FAULT
        fault_strength = 'strong' if gt_health >= 5.0 else ('moderate' if gt_health >= 3.0 else 'weak')

        # Determine detection status
        detected = (rank == 1)

        # Get physics type
        physics_type = self._determine_physics_type(ep, gt_candidate)

        return {
            # Episode info
            'batch': ep['batch'],
            'episode': Path(ep['path']).name,
            'fault_type': fault_type,
            'ground_truth': ground_truth,

            # Detection results
            'detected': detected,
            'rank': rank if rank is not None else 'None',

            # Ground truth validation
            'gt_valid_fault': is_valid_fault,
            'gt_fault_strength': fault_strength,

            # Ground truth parameters
            'gt_health': gt_health,
            'gt_score': gt_score,
            'gt_physics': gt_physics,
            'gt_semantic': gt_semantic,
            'gt_is_primary': gt_is_primary,
            'gt_temporal': gt_supplements.get('temporal', 0),
            'gt_trace': gt_supplements.get('trace', 0),
            'gt_coverage': gt_health_meta.get('coverage', 0),
            'gt_max_severity': gt_health_meta.get('max_severity', 0),
            'gt_degraded_pods': gt_health_meta.get('degraded_count', 0),
            'gt_total_pods': gt_health_meta.get('total_count', 0),

            # Rank 1 parameters (winner)
            'r1_node': r1_node,
            'r1_health': r1_health,
            'r1_score': r1_score,
            'r1_physics': r1_physics,
            'r1_semantic': r1_semantic,
            'r1_is_primary': r1_is_primary,

            # Comparison
            'health_diff': gt_health - r1_health,
            'physics_diff': gt_physics - r1_physics,
            'score_diff': gt_score - r1_score,

            # Physics classification
            'physics_type': physics_type,
        }

    def _determine_physics_type(self, ep: Dict, gt_candidate: Dict) -> str:
        """Determine the type of physics relationship for this fault."""
        if not gt_candidate:
            return 'unknown'

        physics = gt_candidate.get('score_composition', {}).get('physics_coverage', {}).get('raw', 0)
        story = gt_candidate.get('story', [])

        # Check story for propagation types
        story_text = ' '.join(story).lower()

        if physics > 0.3:
            if 'noisy neighbor' in story_text or 'co-located' in story_text:
                return 'shared_compute'
            elif 'propagated' in story_text or 'latency match' in story_text:
                return 'direct_propagation'
            elif 'reverse impact' in story_text:
                return 'reverse_propagation'
            else:
                return 'high_physics_unknown'
        elif physics > 0.05:
            return 'low_physics'
        else:
            # No physics - check if leaf or victim
            health_meta = gt_candidate.get('health_metadata', {})
            coverage = health_meta.get('coverage', 1.0)
            max_severity = health_meta.get('max_severity', 0)

            if coverage < 0.5 and max_severity >= 8.0:
                return 'hot_shard'
            else:
                return 'no_physics'

    def _write_csv(self):
        """Write detailed results to CSV."""
        output_file = 'rca_pattern_analysis.csv'

        if not self.results:
            print("No results to write")
            return

        # Get all keys from first result
        fieldnames = list(self.results[0].keys())

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.results)

        print(f"\n✓ Wrote detailed analysis to: {output_file}")
        return output_file

    def _analyze_patterns(self):
        """Analyze global patterns across all results."""
        df = pd.DataFrame(self.results)

        print("\n" + "=" * 80)
        print("GLOBAL PATTERN ANALYSIS")
        print("=" * 80)

        # Overall statistics
        total = len(df)
        detected = df['detected'].sum()
        valid_faults = df['gt_valid_fault'].sum()

        print(f"\n📊 Overall Statistics:")
        print(f"  Total episodes: {total}")
        print(f"  Detected (Rank 1): {detected} ({detected/total*100:.1f}%)")
        print(f"  Valid fault injections: {valid_faults} ({valid_faults/total*100:.1f}%)")
        print(f"  Invalid/weak faults: {total - valid_faults}")

        # Analysis by fault type
        print(f"\n📋 Detection by Fault Type:")
        fault_summary = df.groupby('fault_type').agg({
            'detected': ['sum', 'count'],
            'gt_valid_fault': 'sum',
            'gt_health': 'mean',
            'gt_physics': 'mean',
        })
        fault_summary.columns = ['detected', 'total', 'valid', 'avg_health', 'avg_physics']
        fault_summary['rate'] = (fault_summary['detected'] / fault_summary['total'] * 100).round(1)

        for fault_type in fault_summary.index:
            row = fault_summary.loc[fault_type]
            print(f"  {fault_type:<25} {int(row['detected'])}/{int(row['total'])} ({row['rate']:.1f}%)  "
                  f"Valid:{int(row['valid'])}  Health:{row['avg_health']:.1f}  Physics:{row['avg_physics']:.2f}")

        # Analysis by physics type
        print(f"\n🔬 Detection by Physics Type:")
        physics_summary = df.groupby('physics_type').agg({
            'detected': ['sum', 'count'],
        })
        physics_summary.columns = ['detected', 'total']
        physics_summary['rate'] = (physics_summary['detected'] / physics_summary['total'] * 100).round(1)

        for physics_type in physics_summary.index:
            row = physics_summary.loc[physics_type]
            print(f"  {physics_type:<25} {int(row['detected'])}/{int(row['total'])} ({row['rate']:.1f}%)")

        # Key differentiators for detected vs not detected
        print(f"\n🔑 Key Differentiators (Detected vs Failed):")
        detected_df = df[df['detected'] == True]
        failed_df = df[df['detected'] == False]

        for metric in ['gt_health', 'gt_physics', 'gt_semantic', 'gt_coverage', 'gt_max_severity']:
            detected_mean = detected_df[metric].mean()
            failed_mean = failed_df[metric].mean()
            diff = detected_mean - failed_mean
            print(f"  {metric:<20} Detected:{detected_mean:6.2f}  Failed:{failed_mean:6.2f}  Diff:{diff:+.2f}")

        # Failed cases analysis
        print(f"\n❌ Failed Cases Analysis:")
        failed_valid = df[(df['detected'] == False) & (df['gt_valid_fault'] == True)]
        print(f"  Valid faults that failed: {len(failed_valid)}")

        if len(failed_valid) > 0:
            print(f"\n  Why they failed:")
            for _, row in failed_valid.iterrows():
                print(f"    {row['fault_type']:<20} GT score:{row['gt_score']:6.1f}  "
                      f"R1 score:{row['r1_score']:6.1f}  Diff:{row['score_diff']:+6.1f}")
                print(f"      Health:{row['gt_health']:.1f}  Physics:{row['gt_physics']:.2f}  "
                      f"Semantic:{row['gt_semantic']:.1f}  vs R1 physics:{row['r1_physics']:.2f}")

    def _generate_recommendations(self):
        """Generate data-driven recommendations for scoring adjustments."""
        df = pd.DataFrame(self.results)

        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)

        # Recommendation 1: Invalid faults
        invalid_faults = df[df['gt_valid_fault'] == False]
        if len(invalid_faults) > 0:
            print(f"\n1️⃣ Invalid/Weak Fault Injections ({len(invalid_faults)} cases):")
            print(f"   These should be excluded from evaluation or simulation fixed:")
            for _, row in invalid_faults.iterrows():
                print(f"     - {row['fault_type']:<20} {row['episode']:<30} health={row['gt_health']:.1f}")

        # Recommendation 2: Pattern-based fixes
        failed_valid = df[(df['detected'] == False) & (df['gt_valid_fault'] == True)]

        if len(failed_valid) > 0:
            print(f"\n2️⃣ Scoring Adjustments Needed ({len(failed_valid)} valid but undetected):")

            # Group by physics type
            for physics_type, group in failed_valid.groupby('physics_type'):
                print(f"\n   {physics_type} pattern ({len(group)} cases):")
                avg_health = group['gt_health'].mean()
                avg_physics = group['gt_physics'].mean()
                avg_semantic = group['gt_semantic'].mean()

                # Diagnose issue
                if avg_physics < 0.1 and avg_semantic < 10:
                    print(f"     Issue: No physics ({avg_physics:.2f}) + low semantic ({avg_semantic:.1f})")
                    print(f"     Suggestion: Increase semantic bonus for {physics_type} pattern")
                elif avg_physics > 0.3:
                    print(f"     Issue: Good physics ({avg_physics:.2f}) but still lost")
                    print(f"     Suggestion: Check why winner scored higher (victim with high health?)")
                else:
                    print(f"     Issue: Moderate physics ({avg_physics:.2f}), semantic ({avg_semantic:.1f})")
                    print(f"     Suggestion: Balanced approach needed")

                # Show specific cases
                for _, row in group.head(3).iterrows():
                    print(f"       {row['fault_type']:<20} Health:{row['gt_health']:.1f} Physics:{row['gt_physics']:.2f} "
                          f"Semantic:{row['gt_semantic']:.1f} (lost to {row['r1_node']} score:{row['r1_score']:.1f})")

        # Recommendation 3: Working patterns to preserve
        detected_cases = df[df['detected'] == True]
        if len(detected_cases) > 0:
            print(f"\n3️⃣ Working Patterns to Preserve ({len(detected_cases)} cases):")
            for physics_type, group in detected_cases.groupby('physics_type'):
                print(f"   {physics_type}: {len(group)} successes "
                      f"(avg health:{group['gt_health'].mean():.1f}, physics:{group['gt_physics'].mean():.2f})")


def main():
    """Main entry point."""
    import sys

    # Get batch directories from command line or use defaults
    if len(sys.argv) > 1:
        batch_dirs = sys.argv[1:]
    else:
        batch_dirs = [
            'data/batch_run_20251222_143334',
            'data/batch_run_20251224_011925',
        ]

    analyzer = RCAPatternAnalyzer(batch_dirs)
    analyzer.analyze_all_batches()

    print("\n" + "=" * 80)
    print("Analysis complete! Review rca_pattern_analysis.csv for details.")
    print("=" * 80)


if __name__ == '__main__':
    main()
