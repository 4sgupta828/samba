"""
Data loader for Samba training episodes.

This module handles loading all episode data including:
- label.json: Ground truth metadata (includes fault injection details)
- topology.json: System topology graph (nodes and edges)
- metrics.jsonl: Time-series telemetry data
- health analysis: Identifies healthy vs impacted nodes
"""

import json
import glob
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import networkx as nx
# Import new statistical impact analyzer
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.impact_analyzer import detect_node_impacts


def list_data_runs(base_dir: str = "data") -> List[Dict[str, str]]:
    """
    List all available data runs (data_YYYYMMDD_HHMMSS directories) in reverse chronological order.

    Args:
        base_dir: Base data directory (default: 'data')

    Returns:
        List of dictionaries with 'id', 'path', and 'timestamp' for each run
        Example: [{'id': 'data_20251121_184527', 'path': 'data/data_20251121_184527', 'timestamp': '2025-11-21 18:45:27'}, ...]
    """
    import re
    from datetime import datetime

    if not os.path.exists(base_dir):
        return []

    # Find all directories matching data_YYYYMMDD_HHMMSS pattern
    pattern = re.compile(r'data_(\d{8})_(\d{6})$')
    runs = []

    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        if os.path.isdir(item_path):
            match = pattern.match(item)
            if match:
                date_str, time_str = match.groups()
                # Parse timestamp for sorting and display
                try:
                    timestamp = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                    runs.append({
                        'id': item,
                        'path': item_path,
                        'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'sort_key': timestamp
                    })
                except ValueError:
                    continue

    # Sort by timestamp in reverse chronological order (newest first)
    runs.sort(key=lambda x: x['sort_key'], reverse=True)

    # Remove sort_key from output
    for run in runs:
        del run['sort_key']

    return runs


def list_episodes(data_run_path: str) -> List[str]:
    """
    List all available episodes in a data run directory.

    Args:
        data_run_path: Path to data run directory (e.g., 'data/data_20251121_184527')

    Returns:
        List of episode IDs (e.g., ['ep_0', 'ep_1', ...])
    """
    ep_dirs = glob.glob(os.path.join(data_run_path, "ep_*"))
    episodes = sorted([os.path.basename(d) for d in ep_dirs if os.path.isdir(d)])
    return episodes


def get_episode_data_dir(episode_path: str) -> Optional[str]:
    """
    Find the data directory for an episode.

    For new structure (data/data_YYYYMMDD_HHMMSS/ep_N):
        Returns the episode path itself (no nested data_* subdirectory)

    For legacy structure (data/train/ep_N/data_YYYYMMDD_HHMMSS):
        Returns the nested data_* subdirectory

    Args:
        episode_path: Path to episode directory

    Returns:
        Path to data directory or None if not found
    """
    import re

    # Check if this is the new structure (parent contains data_YYYYMMDD_HHMMSS)
    if re.search(r'data_\d{8}_\d{6}', episode_path):
        # New structure: episode directory IS the data directory
        if os.path.exists(os.path.join(episode_path, "metrics.jsonl")):
            return episode_path
        # Fall through to legacy check if metrics.jsonl not found

    # Legacy structure: look for nested data_* subdirectory
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


def load_topology(episode_path: str, use_filtered: bool = False) -> Dict:
    """
    Load topology.json containing the graph structure.

    Args:
        episode_path: Path to episode directory
        use_filtered: If True, load topology_filtered.json (filtered by root cause reachability)

    Returns:
        Dictionary with nodes and edges
    """
    if use_filtered:
        topology_file = os.path.join(episode_path, "topology_filtered.json")
        if not os.path.exists(topology_file):
            # Fall back to regular topology if filtered version doesn't exist
            topology_file = os.path.join(episode_path, "topology.json")
    else:
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
        Returns empty DataFrame if metrics file is empty or missing.
    """
    metrics_file = os.path.join(data_dir, "metrics.jsonl")

    # Check if file exists and has content
    if not os.path.exists(metrics_file):
        raise ValueError(f"Metrics file not found: {metrics_file}")

    if os.path.getsize(metrics_file) == 0:
        raise ValueError(f"Metrics file is empty. Episode generation may have failed.")

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


def load_episode(episode_id: str, data_run_path: str) -> Dict:
    """
    Load all data for a single episode.

    Args:
        episode_id: Episode identifier (e.g., 'ep_0')
        data_run_path: Path to data run directory (e.g., 'data/data_20251121_184527')

    Returns:
        Dictionary containing:
        - episode_id: Episode identifier
        - label: Ground truth metadata (includes fault details)
        - topology: Topology dictionary from topology.json
        - topology_filtered: Filtered topology dictionary (if exists)
        - has_filtered_topology: Boolean indicating if filtered topology exists
        - metrics_df: DataFrame with time-series metrics
        - topology_graph: NetworkX graph (logical topology)
        - topology_graph_filtered: NetworkX graph (filtered by root cause)
        - logical_topology_graph: NetworkX graph (same as topology_graph, for backward compatibility)
        - ground_truth: Fault injection details (for backward compatibility)
        - episode_path: Path to episode directory
        - data_path: Path to data directory
    """
    episode_path = os.path.join(data_run_path, episode_id)

    # Check if episode exists
    if not os.path.exists(episode_path):
        raise ValueError(f"Episode {episode_id} not found in {data_run_path}")

    # Load label and topology from episode directory
    label = load_label(episode_path)
    topology = load_topology(episode_path)

    # Check if filtered topology exists and load it
    filtered_topology_path = os.path.join(episode_path, "topology_filtered.json")
    has_filtered_topology = os.path.exists(filtered_topology_path)
    topology_filtered = None
    topology_graph_filtered = None

    if has_filtered_topology:
        topology_filtered = load_topology(episode_path, use_filtered=True)
        topology_graph_filtered = build_topology_graph(topology_filtered)

    # Find data directory
    data_path = get_episode_data_dir(episode_path)
    if not data_path:
        raise ValueError(f"No data directory found in {episode_path}")

    # Load metrics from data directory
    metrics_df = load_metrics(data_path)

    # Build graph from topology
    topology_graph = build_topology_graph(topology)

    # Extract ground truth for backward compatibility
    ground_truth = {
        'root_cause_node': label.get('root_cause_node'),
        'fault_type': label.get('fault_type'),
        'fault_start_time': label.get('fault_start_time'),
        'fault_duration': label.get('fault_total_duration', label.get('fault_duration', 0))
    }

    # Perform health analysis to identify healthy vs impacted nodes
    # Uses new statistical analyzer with metric-agnostic approach
    #
    # To adjust the "healthy" threshold (which nodes get hidden when "Hide Healthy Nodes" is checked):
    #   1. Edit analysis/impact_config.py
    #   2. Adjust config.scoring.healthy_threshold (default: 0.7)
    #      - Higher threshold (e.g., 0.8) = fewer nodes classified as healthy (more conservative)
    #      - Lower threshold (e.g., 0.6) = more nodes classified as healthy (more aggressive hiding)
    #
    # To customize configuration programmatically:
    #   from analysis.impact_config import create_custom_config
    #   config = create_custom_config(scoring={'healthy_threshold': 0.75})
    #   health_analysis = detect_node_impacts(..., config=config)
    #
    health_analysis = detect_node_impacts(
        metrics_df=metrics_df,
        graph=topology_graph,
        label_data=label,
        config=None  # Uses default config from analysis/impact_config.py
    )

    return {
        'episode_id': episode_id,
        'label': label,
        'topology': topology,
        'topology_filtered': topology_filtered,
        'has_filtered_topology': has_filtered_topology,
        'metrics_df': metrics_df,
        'topology_graph': topology_graph,
        'topology_graph_filtered': topology_graph_filtered,
        'logical_topology_graph': topology_graph,  # For backward compatibility
        'ground_truth': ground_truth,
        'health_analysis': health_analysis,
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

    base_dir = "data" if len(sys.argv) < 2 else sys.argv[1]

    print(f"Loading data runs from {base_dir}...")
    runs = list_data_runs(base_dir)
    print(f"Found {len(runs)} data runs:")
    for run in runs[:5]:
        print(f"  - {run['id']} ({run['timestamp']})")
    if len(runs) > 5:
        print(f"  ... and {len(runs) - 5} more")

    if runs:
        # Use the most recent run
        run_path = runs[0]['path']
        print(f"\nLoading episodes from {run_path}...")
        episodes = list_episodes(run_path)
        print(f"Found {len(episodes)} episodes: {episodes[:10]}")

        if episodes:
            ep_id = episodes[0]
            print(f"\nLoading {ep_id}...")
            episode_data = load_episode(ep_id, run_path)

            print(f"\nLabel: {episode_data['label']}")
            print(f"\nTopology: {episode_data['label']['topology']['nodes']} nodes, "
                  f"{episode_data['label']['topology']['edges']} edges")
            print(f"\nMetrics shape: {episode_data['metrics_df'].shape}")
            print(f"Metric names: {episode_data['metrics_df']['metric_name'].unique()[:10]}")
            print(f"\nGraph: {episode_data['topology_graph'].number_of_nodes()} nodes, "
                  f"{episode_data['topology_graph'].number_of_edges()} edges")
