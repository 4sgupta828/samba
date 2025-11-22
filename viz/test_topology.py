#!/usr/bin/env python3
"""Test script to analyze topology issues."""

from data_loader import load_episode
import pandas as pd

# Load a test episode
episode_data = load_episode('ep_0', '../data/final_validation')

# Check node types
graph = episode_data['topology_graph']
node_types = {}
for node in graph.nodes():
    node_type = graph.nodes[node].get('type', 'Unknown')
    if node_type not in node_types:
        node_types[node_type] = []
    node_types[node_type].append(node)

print('Node types and counts:')
for node_type, nodes in sorted(node_types.items()):
    print(f'{node_type}: {len(nodes)} nodes')
    print(f'  Examples: {nodes[:5]}')

# Check MessageQueue edges
print('\n\nMessageQueue connectivity:')
for node in node_types.get('MessageQueue', []):
    predecessors = list(graph.predecessors(node))
    successors = list(graph.successors(node))
    print(f'\n{node}:')
    print(f'  Incoming edges from: {predecessors}')
    print(f'  Outgoing edges to: {successors}')
    if not predecessors and not successors:
        print(f'  WARNING: {node} is completely isolated!')

# Check topology without ComputeAgent
print('\n\nTopology without ComputeAgent nodes:')
non_agent_nodes = [n for n in graph.nodes() if graph.nodes[n].get('type') != 'ComputeAgent']
print(f'Total nodes without agents: {len(non_agent_nodes)}')

subgraph = graph.subgraph(non_agent_nodes)
print(f'Edges in subgraph: {subgraph.number_of_edges()}')

# Check for disconnected components
import networkx as nx
undirected = subgraph.to_undirected()
connected_components = list(nx.connected_components(undirected))
print(f'\nNumber of connected components: {len(connected_components)}')
if len(connected_components) > 1:
    print('WARNING: Topology is disconnected without agents!')
    for i, component in enumerate(connected_components):
        print(f'\nComponent {i+1} ({len(component)} nodes):')
        print(f'  Nodes: {sorted(component)[:10]}')

        # Check types in this component
        types_in_component = {}
        for node in component:
            node_type = graph.nodes[node].get('type', 'Unknown')
            types_in_component[node_type] = types_in_component.get(node_type, 0) + 1
        print(f'  Types: {types_in_component}')

# Check metrics for a sample component
print('\n\nMetrics check:')
sample_node = 'svc_0'
if sample_node in graph.nodes():
    node_metrics = episode_data['metrics_df'][
        episode_data['metrics_df']['component_id'] == sample_node
    ]
    print(f'{sample_node} has {len(node_metrics)} metric records')
    print(f'Metric names: {node_metrics["metric_name"].unique()}')
else:
    print(f'{sample_node} not found in graph')

print(f'\n\nRoot cause: {episode_data["label"]["root_cause_node"]}')
