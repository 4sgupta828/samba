#!/usr/bin/env python3
"""
Test script for RCA discovery and validation.

This script demonstrates the new discover_and_validate_rca functionality:
1. Runs discovery mode analysis WITHOUT using ground truth
2. Checks if ground truth is in top 3 candidates
3. Creates a marker file if successful
"""

import sys
from pathlib import Path
from analysis.sotaanalyzer.sota_propagation_analyzer import discover_and_validate_rca


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_rca_discovery.py <episode_dir>")
        print("\nExample:")
        print("  python test_rca_discovery.py data/data_20251201_120042/ep_0")
        sys.exit(1)

    episode_dir = sys.argv[1]

    # Validate episode directory
    episode_path = Path(episode_dir)
    if not episode_path.exists():
        print(f"❌ Error: Episode directory not found: {episode_dir}")
        sys.exit(1)

    if not (episode_path / 'label.json').exists():
        print(f"❌ Error: label.json not found in {episode_dir}")
        sys.exit(1)

    if not (episode_path / 'topology.json').exists():
        print(f"❌ Error: topology.json not found in {episode_dir}")
        sys.exit(1)

    if not (episode_path / 'metrics.jsonl').exists():
        print(f"❌ Error: metrics.jsonl not found in {episode_dir}")
        sys.exit(1)

    # Run discovery and validation
    print("="*80)
    print("RCA DISCOVERY AND VALIDATION TEST")
    print("="*80)

    try:
        result = discover_and_validate_rca(
            episode_dir=episode_dir,
            sample_interval=5,
            output_file=None,  # Don't save full analysis
            create_marker=True  # Create marker file on success
        )

        # Print summary
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)

        if result.get('already_investigated'):
            print("⏭️  Episode was already investigated")
            val_result = result['validation_result']
            print(f"   Previous result: {'SUCCESS' if val_result['success'] else 'FAILURE'}")
            if val_result['success']:
                print(f"   Ground truth '{val_result['ground_truth']}' at rank {val_result['rank']}")
        else:
            val_result = result['validation_result']
            print(f"Episode: {episode_dir}")
            print(f"Status: {'✅ SUCCESS' if val_result['success'] else '❌ FAILURE'}")
            print(f"Ground truth: {val_result['ground_truth']}")
            print(f"Top 3 candidates: {val_result['top_3_candidates']}")

            if val_result['success']:
                print(f"Rank: {val_result['rank']}")
                print(f"Confidence: {val_result['confidence']:.3f}")
                print(f"\n✅ Marker file created: {episode_path / 'RCAInvestigated.marker'}")
            else:
                if val_result['rank']:
                    print(f"Ground truth rank: {val_result['rank']} (outside top 3)")
                else:
                    print(f"Ground truth was not detected")
                print(f"\n💡 Consider improving the RCA detection algorithm")

        print("="*80)

        # Return appropriate exit code
        if result.get('already_investigated'):
            sys.exit(0)
        else:
            sys.exit(0 if val_result['success'] else 1)

    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
