#!/usr/bin/env python3
"""
Batch Filter Topologies by Root Cause

This script filters topology graphs for multiple episodes in a dataset directory.

Usage:
    python batch_filter_topologies.py <dataset_dir> [--pattern <pattern>]

Example:
    python batch_filter_topologies.py data/data_20251121_185526
    python batch_filter_topologies.py data/data_20251121_185526 --pattern "ep_*"
"""

import argparse
import sys
from pathlib import Path
from filter_topology_by_root_cause import (
    load_topology,
    load_label,
    build_reverse_graph,
    find_reachable_nodes,
    filter_topology
)


def find_episode_directories(dataset_dir: Path, pattern: str = "ep_*") -> list:
    """
    Find all episode directories in the dataset directory.

    Args:
        dataset_dir: Path to dataset directory
        pattern: Glob pattern for episode directories

    Returns:
        List of episode directory paths
    """
    episode_dirs = sorted(dataset_dir.glob(pattern))
    # Filter to only include directories that have both topology.json and label.json
    valid_dirs = []
    for ep_dir in episode_dirs:
        if ep_dir.is_dir() and (ep_dir / 'topology.json').exists() and (ep_dir / 'label.json').exists():
            valid_dirs.append(ep_dir)
    return valid_dirs


def process_episode(episode_dir: Path, quiet: bool = False) -> bool:
    """
    Process a single episode directory.

    Args:
        episode_dir: Path to episode directory
        quiet: Suppress output

    Returns:
        True if successful, False otherwise
    """
    try:
        if not quiet:
            print(f"\nProcessing: {episode_dir.name}")

        topology_path = episode_dir / 'topology.json'
        label_path = episode_dir / 'label.json'
        output_path = episode_dir / 'topology_filtered.json'

        # Load data
        topology = load_topology(topology_path)
        label = load_label(label_path)
        root_cause = label.get('root_cause_node')

        if not root_cause:
            print(f"  Error: 'root_cause_node' not found in {label_path}")
            return False

        # Build reverse graph and find reachable nodes
        reverse_graph = build_reverse_graph(topology)
        reachable_nodes = find_reachable_nodes(root_cause, reverse_graph)

        # Filter topology
        filtered_topology = filter_topology(topology, reachable_nodes)

        # Save filtered topology
        import json
        with open(output_path, 'w') as f:
            json.dump(filtered_topology, f, indent=2)

        # Print summary
        if not quiet:
            metadata = filtered_topology['filter_metadata']
            print(f"  Root Cause: {root_cause}")
            print(f"  Nodes: {metadata['original_num_nodes']} -> {metadata['reachable_nodes']} "
                  f"(removed {metadata['removed_nodes']})")
            print(f"  Edges: {metadata['original_num_edges']} -> {filtered_topology['num_edges']} "
                  f"(removed {metadata['removed_edges']})")
            print(f"  Saved to: {output_path.name}")

        return True

    except Exception as e:
        print(f"  Error processing {episode_dir.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Batch filter topology graphs for multiple episodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter all episodes in a dataset
  python batch_filter_topologies.py data/data_20251121_185526

  # Use custom pattern for episode directories
  python batch_filter_topologies.py data/data_20251121_185526 --pattern "episode_*"

  # Run quietly (minimal output)
  python batch_filter_topologies.py data/data_20251121_185526 --quiet
        """
    )
    parser.add_argument(
        'dataset_dir',
        type=str,
        help='Path to dataset directory containing episode subdirectories'
    )
    parser.add_argument(
        '--pattern',
        '-p',
        type=str,
        default='ep_*',
        help='Glob pattern for episode directories (default: ep_*)'
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress detailed output'
    )

    args = parser.parse_args()

    # Resolve dataset directory
    dataset_dir = Path(args.dataset_dir)

    if not dataset_dir.exists():
        print(f"Error: Dataset directory not found: {dataset_dir}")
        return 1

    if not dataset_dir.is_dir():
        print(f"Error: Not a directory: {dataset_dir}")
        return 1

    # Find episode directories
    episode_dirs = find_episode_directories(dataset_dir, args.pattern)

    if not episode_dirs:
        print(f"No episode directories found in {dataset_dir} matching pattern '{args.pattern}'")
        print("Each episode directory must contain both topology.json and label.json")
        return 1

    print(f"Found {len(episode_dirs)} episode(s) to process")

    # Process each episode
    success_count = 0
    fail_count = 0

    for episode_dir in episode_dirs:
        if process_episode(episode_dir, args.quiet):
            success_count += 1
        else:
            fail_count += 1

    # Print final summary
    print(f"\n{'='*60}")
    print(f"Batch Processing Complete")
    print(f"{'='*60}")
    print(f"Successfully processed: {success_count}/{len(episode_dirs)} episodes")
    if fail_count > 0:
        print(f"Failed: {fail_count} episodes")
    print(f"{'='*60}")

    return 0 if fail_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
