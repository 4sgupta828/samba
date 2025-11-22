"""
Data loader for Samba training episodes.

This module handles loading all episode data including:
- label.json: Ground truth metadata (includes fault injection details)
- topology.json: System topology graph (nodes and edges)
- metrics.jsonl: Time-series telemetry data
"""

import json
import glob
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import networkx as nx


def list_episodes(data_dir: str) -> List[str]:
    """
    List all available episodes in the data directory.

    Args:
        data_dir: Path to data directory (e.g., 'data/final_validation')

    Returns:
        List of episode IDs (e.g., ['ep_0', 'ep_1', ...])
    """
    ep_dirs = glob.glob(os.path.join(data_dir, "ep_*"))
    episodes = sorted([os.path.basename(d) for d in ep_dirs if os.path.isdir(d)])
    return episodes


def get_episode_data_dir(episode_path: str) -> Optional[str]:
    """
    Find the data_* subdirectory within an episode directory.

    Args:
        episode_path: Path to episode (e.g., 'data/final_validation/ep_0')

    Returns:
        Path to data subdirectory or None if not found
    """
    data_dirs = glob.glob(os.path.join(episode_path, "data_*"))
    if not data_dirs:
        return None
    # Return the most recent if multiple exist
    return sorted(data_dirs)[-1]


def load_label(episode_path: str) -> Dict:
    """
    Load label.json containing ground truth metadata.

    Args:
        episode_path: Path to episode directory

    Returns:
        Dictionary with episode metadata and ground truth
    """
    label_file = os.path.join(episode_path, "label.json")
    with open(label_file, 'r') as f:
        return json.load(f)


def load_topology(episode_path: str) -> Dict:
    """
    Load topology.json containing the graph structure.

    Args:
        episode_path: Path to episode directory

    Returns:
        Dictionary with nodes and edges
    """
    topology_file = os.path.join(episode_path, "topology.json")
    with open(topology_file, 'r') as f:
        return json.load(f)


def load_metrics(data_dir: str) -> pd.DataFrame:
    """
    Load metrics.jsonl into a pandas DataFrame.

    Each line in metrics.jsonl is a JSON object with:
    - ts: Nanosecond timestamp
    - name: Metric name
    - labels: Dict with metadata (component.id, sim.time, etc.)
    - value: Single value (for gauges/counters)
    - summary: Dict with statistics (count, sum, p50, p90, p99) for histograms

    Args:
        data_dir: Path to episode data directory (data_*)

    Returns:
        DataFrame with columns: timestamp, metric_name, sim_time, component_id, value, p50, p90, p99, etc.
    """
    metrics_file = os.path.join(data_dir, "metrics.jsonl")

    records = []
    with open(metrics_file, 'r') as f:
        for line in f:
            data = json.loads(line)

            # Flatten structure
            record = {
                'timestamp': data['ts'],
                'metric_name': data['name'],
                'sim_time': data['labels'].get('sim.time'),
                'component_id': data['labels'].get('component.id', 'global'),
            }

            # Handle value vs summary
            if 'value' in data:
                record['value'] = data['value']
            elif 'summary' in data:
                record.update({
                    k: v for k, v in data['summary'].items()
                })

            # Add additional labels as columns
            for key, val in data['labels'].items():
                if key not in ['sim.time', 'component.id']:
                    record[key] = val

            records.append(record)

    df = pd.DataFrame(records)

    # Sort by simulation time for chronological analysis
    if 'sim_time' in df.columns:
        df = df.sort_values('sim_time')

    return df


def build_topology_graph(topology: Dict) -> nx.DiGraph:
    """
    Build a NetworkX directed graph from topology.json.

    Args:
        topology: Dictionary from topology.json

    Returns:
        NetworkX DiGraph with nodes and edges (logical topology only)
    """
    G = nx.DiGraph()

    # Add nodes with attributes
    for node in topology['nodes']:
        node_id = node['id']
        node_type = node['type']
        role = node.get('role')
        is_frontend = node.get('is_frontend', False)

        G.add_node(node_id,
                   type=node_type,
                   role=role,
                   is_frontend=is_frontend)

    # Add edges
    for edge in topology['edges']:
        source = edge['source']
        target = edge['target']
        edge_type = edge['type']
        latency = edge.get('base_latency', 0)

        G.add_edge(source, target,
                   type=edge_type,
                   latency=latency)

    return G


# REMOVED: build_logical_topology()
# No longer needed - topology.json already contains the logical topology
# without ComputeAgent nodes


def load_episode(episode_id: str, data_dir: str = "data/final_validation") -> Dict:
    """
    Load all data for a single episode.

    Args:
        episode_id: Episode identifier (e.g., 'ep_0')
        data_dir: Base data directory

    Returns:
        Dictionary containing:
        - label: Ground truth metadata (includes fault details)
        - topology: Topology dictionary from topology.json
        - metrics_df: DataFrame with time-series metrics
        - topology_graph: NetworkX graph (logical topology)
        - episode_path: Path to episode directory
        - data_path: Path to data subdirectory
    """
    episode_path = os.path.join(data_dir, episode_id)

    # Check if episode exists
    if not os.path.exists(episode_path):
        raise ValueError(f"Episode {episode_id} not found in {data_dir}")

    # Load label and topology from episode directory
    label = load_label(episode_path)
    topology = load_topology(episode_path)

    # Find data directory
    data_path = get_episode_data_dir(episode_path)
    if not data_path:
        raise ValueError(f"No data directory found in {episode_path}")

    # Load metrics from data subdirectory
    metrics_df = load_metrics(data_path)

    # Build graph from topology
    topology_graph = build_topology_graph(topology)

    return {
        'episode_id': episode_id,
        'label': label,
        'topology': topology,
        'metrics_df': metrics_df,
        'topology_graph': topology_graph,
        'episode_path': episode_path,
        'data_path': data_path
    }


def get_component_role(component_type: str) -> str:
    """
    Map component type to role for visualization.

    Args:
        component_type: Component type (e.g., 'ApiService', 'SqlDatabase')

    Returns:
        Role string (gateway, service, database, cache, queue, external)
    """
    role_mapping = {
        'RequestGateway': 'gateway',
        'ApiService': 'service',
        'SqlDatabase': 'database',
        'InMemoryCache': 'cache',
        'MessageQueue': 'queue',
        'ExternalService': 'external'
    }
    return role_mapping.get(component_type, 'unknown')


def get_component_color(component_type: str, is_root_cause: bool = False) -> str:
    """
    Get color for component based on type.

    Args:
        component_type: Component type
        is_root_cause: Whether this is the root cause node

    Returns:
        Color string (for Plotly)
    """
    if is_root_cause:
        return '#ff0000'  # Red for root cause

    color_mapping = {
        'RequestGateway': '#808080',  # Gray
        'ApiService': '#3498db',      # Blue
        'SqlDatabase': '#2ecc71',     # Green
        'InMemoryCache': '#e67e22',   # Orange
        'MessageQueue': '#9b59b6',    # Purple
        'ExternalService': '#e74c3c'  # Red
    }
    return color_mapping.get(component_type, '#95a5a6')  # Default gray


if __name__ == '__main__':
    # Test the data loader
    import sys

    data_dir = "data/final_validation" if len(sys.argv) < 2 else sys.argv[1]

    print(f"Loading episodes from {data_dir}...")
    episodes = list_episodes(data_dir)
    print(f"Found {len(episodes)} episodes: {episodes}")

    if episodes:
        ep_id = episodes[0]
        print(f"\nLoading {ep_id}...")
        episode_data = load_episode(ep_id, data_dir)

        print(f"\nLabel: {episode_data['label']}")
        print(f"\nTopology: {episode_data['label']['topology']['nodes']} nodes, "
              f"{episode_data['label']['topology']['edges']} edges")
        print(f"\nMetrics shape: {episode_data['metrics_df'].shape}")
        print(f"Metric names: {episode_data['metrics_df']['metric_name'].unique()[:10]}")
        print(f"\nGraph: {episode_data['topology_graph'].number_of_nodes()} nodes, "
              f"{episode_data['topology_graph'].number_of_edges()} edges")
