#!/usr/bin/env python3
"""
Filter Topology by Root Cause Reachability

This script filters a topology graph to show only nodes that can be potentially
affected by a root cause node, using graph traversal techniques.

Usage:
    python filter_topology_by_root_cause.py <episode_dir> [--output <output_path>]

Example:
    python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0
    python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --output filtered_topology.json
"""

import json
import argparse
from pathlib import Path
from typing import Set, Dict, List, Any
from collections import deque


def load_topology(topology_path: str) -> Dict[str, Any]:
    """Load topology from JSON file."""
    with open(topology_path, 'r') as f:
        return json.load(f)


def load_label(label_path: str) -> Dict[str, Any]:
    """Load label (ground truth) from JSON file."""
    with open(label_path, 'r') as f:
        return json.load(f)


def build_reverse_graph(topology: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Build a reverse adjacency list from the topology.

    In the original graph: A -> B means "A calls B"
    In the reverse graph: A -> B means "A is called by B" (i.e., B can affect A)

    This allows us to find all nodes that can be affected when a root cause fails.

    Args:
        topology: Topology dictionary with 'nodes' and 'edges'

    Returns:
        Dictionary mapping node_id -> list of nodes that depend on it
    """
    reverse_graph = {node['id']: [] for node in topology['nodes']}

    for edge in topology['edges']:
        source = edge['source']
        target = edge['target']
        # In reverse graph: if A -> B originally, then B -> A in reverse
        # This means: if B fails, A (which calls B) is affected
        reverse_graph[target].append(source)

    return reverse_graph


def find_reachable_nodes(root_cause: str, reverse_graph: Dict[str, List[str]]) -> Set[str]:
    """
    Find all nodes reachable from the root cause using BFS on the reverse graph.

    This finds all nodes that can be potentially affected by the root cause.

    Args:
        root_cause: The root cause node ID
        reverse_graph: Reverse adjacency list

    Returns:
        Set of node IDs that are reachable from the root cause
    """
    if root_cause not in reverse_graph:
        print(f"Warning: Root cause node '{root_cause}' not found in topology")
        return {root_cause}

    reachable = {root_cause}
    queue = deque([root_cause])

    while queue:
        current = queue.popleft()

        # Visit all neighbors (nodes that depend on current node)
        for neighbor in reverse_graph.get(current, []):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)

    return reachable


def filter_topology(
    topology: Dict[str, Any],
    reachable_nodes: Set[str]
) -> Dict[str, Any]:
    """
    Filter topology to include only reachable nodes and their edges.

    Args:
        topology: Original topology dictionary
        reachable_nodes: Set of node IDs to keep

    Returns:
        Filtered topology dictionary
    """
    # Filter nodes
    filtered_nodes = [
        node for node in topology['nodes']
        if node['id'] in reachable_nodes
    ]

    # Filter edges - keep only edges where both source and target are reachable
    filtered_edges = [
        edge for edge in topology['edges']
        if edge['source'] in reachable_nodes and edge['target'] in reachable_nodes
    ]

    # Create filtered topology
    filtered_topology = {
        'nodes': filtered_nodes,
        'edges': filtered_edges,
        'num_nodes': len(filtered_nodes),
        'num_edges': len(filtered_edges),
        'is_directed': topology.get('is_directed', True),
        'filter_metadata': {
            'root_cause_node': list(reachable_nodes)[0] if len(reachable_nodes) == 1 else None,
            'original_num_nodes': topology.get('num_nodes', len(topology['nodes'])),
            'original_num_edges': topology.get('num_edges', len(topology['edges'])),
            'reachable_nodes': len(filtered_nodes),
            'removed_nodes': topology.get('num_nodes', len(topology['nodes'])) - len(filtered_nodes),
            'removed_edges': topology.get('num_edges', len(topology['edges'])) - len(filtered_edges)
        }
    }

    return filtered_topology


def print_summary(
    root_cause: str,
    original_topology: Dict[str, Any],
    filtered_topology: Dict[str, Any],
    reachable_nodes: Set[str]
):
    """Print a summary of the filtering operation."""
    metadata = filtered_topology['filter_metadata']

    print(f"\n{'='*60}")
    print("Topology Filtering Summary")
    print(f"{'='*60}")
    print(f"Root Cause Node: {root_cause}")
    print(f"\nOriginal Topology:")
    print(f"  Nodes: {metadata['original_num_nodes']}")
    print(f"  Edges: {metadata['original_num_edges']}")
    print(f"\nFiltered Topology (Reachable from Root Cause):")
    print(f"  Nodes: {metadata['reachable_nodes']}")
    print(f"  Edges: {filtered_topology['num_edges']}")
    print(f"\nRemoved (Unreachable):")
    print(f"  Nodes: {metadata['removed_nodes']}")
    print(f"  Edges: {metadata['removed_edges']}")
    print(f"\nReachable Nodes: {sorted(reachable_nodes)}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Filter topology graph to show only nodes reachable from root cause",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter topology for a specific episode
  python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0

  # Save filtered topology to a custom location
  python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --output filtered.json

  # Specify custom root cause node
  python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --root-cause svc_5
        """
    )
    parser.add_argument(
        'episode_dir',
        type=str,
        help='Path to episode directory containing topology.json and label.json'
    )
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        default=None,
        help='Output path for filtered topology (default: <episode_dir>/topology_filtered.json)'
    )
    parser.add_argument(
        '--root-cause',
        '-r',
        type=str,
        default=None,
        help='Override root cause node (default: read from label.json)'
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress summary output'
    )

    args = parser.parse_args()

    # Resolve paths
    episode_dir = Path(args.episode_dir)
    topology_path = episode_dir / 'topology.json'
    label_path = episode_dir / 'label.json'

    # Validate paths
    if not episode_dir.exists():
        print(f"Error: Episode directory not found: {episode_dir}")
        return 1

    if not topology_path.exists():
        print(f"Error: topology.json not found in {episode_dir}")
        return 1

    # Load topology
    topology = load_topology(topology_path)

    # Get root cause
    if args.root_cause:
        root_cause = args.root_cause
    elif label_path.exists():
        label = load_label(label_path)
        root_cause = label.get('root_cause_node')
        if not root_cause:
            print(f"Error: 'root_cause_node' not found in {label_path}")
            return 1
    else:
        print(f"Error: label.json not found in {episode_dir} and --root-cause not specified")
        return 1

    # Build reverse graph and find reachable nodes
    reverse_graph = build_reverse_graph(topology)
    reachable_nodes = find_reachable_nodes(root_cause, reverse_graph)

    # Filter topology
    filtered_topology = filter_topology(topology, reachable_nodes)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = episode_dir / 'topology_filtered.json'

    # Save filtered topology
    with open(output_path, 'w') as f:
        json.dump(filtered_topology, f, indent=2)

    # Print summary
    if not args.quiet:
        print_summary(root_cause, topology, filtered_topology, reachable_nodes)
        print(f"Filtered topology saved to: {output_path}")

    return 0


if __name__ == '__main__':
    exit(main())
