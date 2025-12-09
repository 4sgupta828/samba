#!/usr/bin/env python3
"""
Batch RCA Discovery Script

Processes all episodes in data/batch_run and runs discovery mode RCA analysis.
- Uses top-5 candidates for validation
- Creates RCAInvestigated.marker if ground truth found in top 5
- Creates RCAFailed.marker if analysis fails
- Skips already processed episodes
- Continues processing even if individual episodes fail
"""

import sys
import traceback
from pathlib import Path
from typing import List, Dict
from analysis.sotaanalyzer.sota_propagation_analyzer import (
    discover_and_validate_rca,
    mark_episode_as_rca_failed
)


def find_all_episodes(base_dir: str) -> List[Path]:
    """
    Find all episode directories in the base directory.

    Args:
        base_dir: Base directory to search (e.g., data/batch_run)

    Returns:
        List of episode directory paths
    """
    base_path = Path(base_dir)

    if not base_path.exists():
        raise ValueError(f"Base directory does not exist: {base_dir}")

    # Find all directories matching ep_* pattern
    episodes = []
    for dataset_dir in base_path.iterdir():
        if dataset_dir.is_dir():
            for ep_dir in dataset_dir.glob('ep_*'):
                if ep_dir.is_dir():
                    # Verify it has required files
                    if (ep_dir / 'label.json').exists() and \
                       (ep_dir / 'topology.json').exists() and \
                       (ep_dir / 'metrics.jsonl').exists():
                        episodes.append(ep_dir)

    return sorted(episodes)


def is_episode_processed(episode_dir: Path) -> tuple[bool, str]:
    """
    Check if episode has already been processed.

    Returns:
        (is_processed, status) where status is 'investigated', 'failed', or 'not_processed'
    """
    if (episode_dir / 'RCAInvestigated.marker').exists():
        return True, 'investigated'
    elif (episode_dir / 'RCAFailed.marker').exists():
        return True, 'failed'
    else:
        return False, 'not_processed'


def process_episode(
    episode_dir: Path,
    top_k: int = 5,
    sample_interval: int = 5
) -> Dict:
    """
    Process a single episode with error handling.

    Args:
        episode_dir: Path to episode directory
        top_k: Number of top candidates to check
        sample_interval: Sampling interval in seconds

    Returns:
        Dictionary with processing results
    """
    try:
        print(f"\n{'='*80}")
        print(f"Processing: {episode_dir}")
        print(f"{'='*80}")

        # Save full analysis output to episode directory
        output_file = str(episode_dir / 'rca_analysis.json')

        result = discover_and_validate_rca(
            episode_dir=str(episode_dir),
            sample_interval=sample_interval,
            output_file=output_file,
            create_marker=True,
            top_k=top_k
        )

        return {
            'episode': str(episode_dir),
            'status': 'success' if result['validation_result']['success'] else 'not_in_top_k',
            'result': result
        }

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        tb = traceback.format_exc()

        print(f"\n❌ ERROR processing {episode_dir}: {error_msg}")
        print(f"Error type: {error_type}")

        # Create failure marker
        error_info = {
            'error': error_msg,
            'error_type': error_type,
            'traceback': tb
        }
        mark_episode_as_rca_failed(str(episode_dir), error_info)

        return {
            'episode': str(episode_dir),
            'status': 'error',
            'error': error_msg,
            'error_type': error_type
        }


def print_summary(results: List[Dict], skipped: Dict[str, int]):
    """Print summary of batch processing."""
    total_processed = len(results)
    success_count = sum(1 for r in results if r['status'] == 'success')
    not_in_top_k_count = sum(1 for r in results if r['status'] == 'not_in_top_k')
    error_count = sum(1 for r in results if r['status'] == 'error')

    print(f"\n{'='*80}")
    print("BATCH RCA DISCOVERY SUMMARY")
    print(f"{'='*80}")
    print(f"Total episodes found: {total_processed + skipped['investigated'] + skipped['failed']}")
    print(f"  Already investigated: {skipped['investigated']}")
    print(f"  Already failed: {skipped['failed']}")
    print(f"  Processed this run: {total_processed}")
    print()
    print(f"Results for {total_processed} processed episodes:")
    print(f"  ✅ Success (found in top-K): {success_count} ({success_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ❌ Not in top-K: {not_in_top_k_count} ({not_in_top_k_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ⚠️  Errors: {error_count} ({error_count/max(1,total_processed)*100:.1f}%)")
    print(f"{'='*80}")

    # Show success rate including previously investigated
    total_investigated = success_count + skipped['investigated']
    total_attempted = total_processed + skipped['investigated'] + skipped['failed']
    if total_attempted > 0:
        print(f"\nOverall success rate: {total_investigated}/{total_attempted} ({total_investigated/total_attempted*100:.1f}%)")

    # Show errors if any
    if error_count > 0:
        print(f"\nEpisodes with errors:")
        for r in results:
            if r['status'] == 'error':
                print(f"  - {r['episode']}: {r['error_type']}")


def main():
    # Configuration
    base_dir = "data/batch_run"
    top_k = 5
    sample_interval = 5
    limit = None  # Process all by default

    # Parse command line arguments
    if len(sys.argv) > 1:
        base_dir = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
        except ValueError:
            print(f"Warning: Invalid limit '{sys.argv[2]}', processing all episodes")
            limit = None

    print(f"{'='*80}")
    print("BATCH RCA DISCOVERY")
    print(f"{'='*80}")
    print(f"Base directory: {base_dir}")
    print(f"Top-K candidates: {top_k}")
    print(f"Sample interval: {sample_interval}s")
    if limit:
        print(f"Limit: {limit} episodes (testing mode)")
    print(f"{'='*80}\n")

    # Find all episodes
    try:
        episodes = find_all_episodes(base_dir)
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    if not episodes:
        print(f"No episodes found in {base_dir}")
        sys.exit(0)

    print(f"Found {len(episodes)} episodes")

    # Check which episodes are already processed
    skipped = {'investigated': 0, 'failed': 0}
    to_process = []

    for ep in episodes:
        is_processed, status = is_episode_processed(ep)
        if is_processed:
            if status == 'investigated':
                skipped['investigated'] += 1
            else:
                skipped['failed'] += 1
        else:
            to_process.append(ep)

    print(f"  Already investigated: {skipped['investigated']}")
    print(f"  Already failed: {skipped['failed']}")
    print(f"  To process: {len(to_process)}")

    if not to_process:
        print("\n✅ All episodes already processed!")
        sys.exit(0)

    # Apply limit if specified
    if limit and limit < len(to_process):
        print(f"\n⚠️  Limiting to first {limit} episodes for testing")
        to_process = to_process[:limit]

    # Process episodes
    results = []
    for i, episode_dir in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] ", end='')
        result = process_episode(episode_dir, top_k, sample_interval)
        results.append(result)

    # Print summary
    print_summary(results, skipped)

    # Run detailed analysis
    print(f"\n{'='*80}")
    print("RUNNING DETAILED ANALYSIS...")
    print(f"{'='*80}\n")

    try:
        from analyze_batch_results import analyze_results
        analyze_results(base_dir)
    except Exception as e:
        print(f"⚠️  Could not run detailed analysis: {e}")
        print(f"   You can run it manually: python3 analyze_batch_results.py {base_dir}")


if __name__ == "__main__":
    main()
