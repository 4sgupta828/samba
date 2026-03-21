#!/usr/bin/env python3
"""
Example script demonstrating how to load topology data for GNN training.

This shows how to:
1. Load the topology.json file
2. Reconstruct the NetworkX graph
3. Convert to PyTorch Geometric format (example)
"""
import json
import networkx as nx
from pathlib import Path


def load_topology_from_json(episode_dir: str) -> nx.DiGraph:
    """
    Load topology graph from episode directory.

    Args:
        episode_dir: Path to episode directory (e.g., 'data/train/ep_0')

    Returns:
        NetworkX DiGraph with full topology
    """
    topology_path = Path(episode_dir) / 'topology.json'

    with open(topology_path, 'r') as f:
        data = json.load(f)

    # Reconstruct NetworkX graph
    G = nx.DiGraph()

    # Add nodes with attributes
    for node in data['nodes']:
        node_id = node.pop('id')
        G.add_node(node_id, **node)

    # Add edges with attributes
    for edge in data['edges']:
        G.add_edge(edge['source'], edge['target'],
                  type=edge['type'],
                  base_latency=edge['base_latency'])

    return G


def graph_to_adjacency_list(G: nx.DiGraph) -> dict:
    """
    Convert NetworkX graph to adjacency list format for GNN input.

    Returns:
        Dictionary with:
        - node_ids: List of node IDs
        - node_features: List of node attribute dicts
        - edge_index: List of [source_idx, target_idx] pairs
        - edge_features: List of edge attribute dicts
    """
    # Create node ID to index mapping
    node_ids = list(G.nodes())
    node_to_idx = {node_id: idx for idx, node_id in enumerate(node_ids)}

    # Extract node features
    node_features = [G.nodes[node_id] for node_id in node_ids]

    # Extract edge indices and features
    edge_index = []
    edge_features = []

    for source, target, attrs in G.edges(data=True):
        src_idx = node_to_idx[source]
        tgt_idx = node_to_idx[target]
        edge_index.append([src_idx, tgt_idx])
        edge_features.append(attrs)

    return {
        'node_ids': node_ids,
        'node_features': node_features,
        'edge_index': edge_index,
        'edge_features': edge_features,
        'num_nodes': len(node_ids),
        'num_edges': len(edge_index)
    }


def example_pytorch_geometric_format(episode_dir: str):
    """
    Example showing conversion to PyTorch Geometric Data format.

    Note: This is a simplified example. You would need to:
    - Encode categorical features (node type, role) as integers or one-hot
    - Normalize numerical features (latency)
    - Add temporal metrics data from metrics.json
    """
    # Load graph
    G = load_topology_from_json(episode_dir)

    # Convert to adjacency list
    adj_data = graph_to_adjacency_list(G)

    print(f"Loaded topology for {episode_dir}")
    print(f"  Nodes: {adj_data['num_nodes']}")
    print(f"  Edges: {adj_data['num_edges']}")
    print(f"\nNode roles:")

    role_counts = {}
    for feat in adj_data['node_features']:
        role = feat.get('role', 'unknown')
        role_counts[role] = role_counts.get(role, 0) + 1

    for role, count in sorted(role_counts.items()):
        print(f"  {role}: {count}")

    print(f"\nEdge types:")
    edge_type_counts = {}
    for feat in adj_data['edge_features']:
        etype = feat.get('type', 'unknown')
        edge_type_counts[etype] = edge_type_counts.get(etype, 0) + 1

    for etype, count in sorted(edge_type_counts.items()):
        print(f"  {etype}: {count}")

    # Example: Create PyTorch Geometric Data object
    # Uncomment if you have torch_geometric installed
    # import torch
    # from torch_geometric.data import Data
    #
    # # Encode node features (simplified)
    # role_to_idx = {role: i for i, role in enumerate(['gateway', 'service', 'database', 'cache', 'queue', 'external'])}
    # node_features_encoded = []
    # for feat in adj_data['node_features']:
    #     role_idx = role_to_idx.get(feat['role'], 0)
    #     is_frontend = 1 if feat.get('is_frontend', False) else 0
    #     node_features_encoded.append([role_idx, is_frontend])
    #
    # x = torch.tensor(node_features_encoded, dtype=torch.float)
    # edge_index = torch.tensor(adj_data['edge_index'], dtype=torch.long).t().contiguous()
    #
    # # Load label
    # with open(Path(episode_dir) / 'label.json', 'r') as f:
    #     label_data = json.load(f)
    #
    # # Create target (which node is root cause)
    # root_cause = label_data['root_cause_node']
    # root_cause_idx = adj_data['node_ids'].index(root_cause)
    # y = torch.zeros(adj_data['num_nodes'], dtype=torch.long)
    # y[root_cause_idx] = 1
    #
    # data = Data(x=x, edge_index=edge_index, y=y)
    # print(f"\nPyTorch Geometric Data:")
    # print(f"  {data}")

    return adj_data


if __name__ == '__main__':
    # Example usage
    episode_dir = 'data/test_topology/ep_0'

    print("="*60)
    print("Example: Loading Topology Data for GNN Training")
    print("="*60)

    adj_data = example_pytorch_geometric_format(episode_dir)

    print("\n" + "="*60)
    print("Sample node features (first 3 nodes):")
    print("="*60)
    for i, (node_id, feat) in enumerate(zip(adj_data['node_ids'][:3], adj_data['node_features'][:3])):
        print(f"{node_id}: {feat}")

    print("\n" + "="*60)
    print("Sample edges (first 3):")
    print("="*60)
    for i in range(min(3, len(adj_data['edge_index']))):
        src_idx, tgt_idx = adj_data['edge_index'][i]
        src_id = adj_data['node_ids'][src_idx]
        tgt_id = adj_data['node_ids'][tgt_idx]
        feat = adj_data['edge_features'][i]
        print(f"{src_id} -> {tgt_id}: {feat}")
