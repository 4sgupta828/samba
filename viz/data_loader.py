"""
Data loader for Samba training episodes.

This module handles loading all episode data including:
- label.json: Ground truth metadata
- infra_context.json: System topology
- metrics.jsonl: Time-series telemetry data
- ground_truth.json: Detailed failure injection events
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


def load_infra_context(data_dir: str) -> Dict:
    """
    Load infra_context.json containing system topology.

    Args:
        data_dir: Path to episode data directory (data_*)

    Returns:
        Dictionary with architecture and component information
    """
    infra_file = os.path.join(data_dir, "infra_context.json")
    with open(infra_file, 'r') as f:
        return json.load(f)


def load_ground_truth(data_dir: str) -> Dict:
    """
    Load ground_truth.json containing detailed failure injection events.

    Args:
        data_dir: Path to episode data directory (data_*)

    Returns:
        Dictionary with event details
    """
    gt_file = os.path.join(data_dir, "ground_truth.json")
    with open(gt_file, 'r') as f:
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


def build_topology_graph(infra_context: Dict) -> nx.DiGraph:
    """
    Build a NetworkX directed graph from infra_context.

    Args:
        infra_context: Dictionary from infra_context.json

    Returns:
        NetworkX DiGraph with nodes and edges (includes all nodes, including ComputeAgents)
    """
    G = nx.DiGraph()

    # Add nodes with attributes
    for component in infra_context['architecture']['components']:
        node_id = component['id']
        node_type = component['type']

        # Add node with all component data as attributes
        G.add_node(node_id,
                   type=node_type,
                   name=component.get('name', node_id),
                   config=component.get('config', {}),
                   state=component.get('state', {}))

    # Add edges from relationships
    for relationship in infra_context['architecture']['relationships']:
        source = relationship['source']
        target = relationship['target']
        rel_type = relationship['type']

        G.add_edge(source, target,
                   type=rel_type,
                   latency=relationship.get('latency_ms', 0))

    return G


def build_logical_topology(physical_graph: nx.DiGraph) -> nx.DiGraph:
    """
    Build a logical topology that shows direct service-to-resource connections,
    bypassing ComputeAgent nodes.

    The physical graph has edges like:
    - service -> compute_agent (uses_compute)
    - compute_agent -> database (uses_database)

    The logical graph will have:
    - service -> database (uses_database)

    Args:
        physical_graph: Original graph from infra_context

    Returns:
        Logical graph with ComputeAgent nodes removed and edges reconnected
    """
    logical_graph = nx.DiGraph()

    # Add all non-ComputeAgent nodes
    for node in physical_graph.nodes():
        node_type = physical_graph.nodes[node].get('type')
        if node_type != 'ComputeAgent':
            # Copy node with all attributes
            logical_graph.add_node(node, **physical_graph.nodes[node])

    # For each service, find what resources it uses through compute agents
    for node in logical_graph.nodes():
        node_type = logical_graph.nodes[node].get('type')

        # Find all compute agents this node uses
        compute_agents = []
        for successor in physical_graph.successors(node):
            if physical_graph.nodes[successor].get('type') == 'ComputeAgent':
                compute_agents.append(successor)

        # For each compute agent, add edges to its non-compute-agent successors
        for agent in compute_agents:
            for resource in physical_graph.successors(agent):
                resource_type = physical_graph.nodes[resource].get('type')
                if resource_type != 'ComputeAgent' and resource in logical_graph:
                    # Get edge data from agent -> resource
                    edge_data = physical_graph.get_edge_data(agent, resource)
                    # Add edge from node -> resource
                    logical_graph.add_edge(node, resource, **edge_data)

        # Also add direct edges that don't go through compute agents
        for successor in physical_graph.successors(node):
            successor_type = physical_graph.nodes[successor].get('type')
            if successor_type != 'ComputeAgent' and successor in logical_graph:
                edge_data = physical_graph.get_edge_data(node, successor)
                logical_graph.add_edge(node, successor, **edge_data)

    return logical_graph


def load_episode(episode_id: str, data_dir: str = "data/final_validation") -> Dict:
    """
    Load all data for a single episode.

    Args:
        episode_id: Episode identifier (e.g., 'ep_0')
        data_dir: Base data directory

    Returns:
        Dictionary containing:
        - label: Ground truth metadata
        - infra_context: System topology
        - ground_truth: Detailed failure events
        - metrics_df: DataFrame with time-series metrics
        - topology_graph: NetworkX graph (physical, includes ComputeAgents)
        - logical_topology_graph: NetworkX graph (logical, ComputeAgents removed)
        - episode_path: Path to episode directory
        - data_path: Path to data subdirectory
    """
    episode_path = os.path.join(data_dir, episode_id)

    # Check if episode exists
    if not os.path.exists(episode_path):
        raise ValueError(f"Episode {episode_id} not found in {data_dir}")

    # Load label
    label = load_label(episode_path)

    # Find data directory
    data_path = get_episode_data_dir(episode_path)
    if not data_path:
        raise ValueError(f"No data directory found in {episode_path}")

    # Load all components
    infra_context = load_infra_context(data_path)
    ground_truth = load_ground_truth(data_path)
    metrics_df = load_metrics(data_path)
    topology_graph = build_topology_graph(infra_context)
    logical_topology_graph = build_logical_topology(topology_graph)

    return {
        'episode_id': episode_id,
        'label': label,
        'infra_context': infra_context,
        'ground_truth': ground_truth,
        'metrics_df': metrics_df,
        'topology_graph': topology_graph,
        'logical_topology_graph': logical_topology_graph,
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
