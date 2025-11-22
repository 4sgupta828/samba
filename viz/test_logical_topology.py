#!/usr/bin/env python3
"""Test logical topology construction."""

from data_loader import load_episode
import networkx as nx

episode_data = load_episode('ep_0', '../data/final_validation')

logical_graph = episode_data['logical_topology_graph']

print(f"Logical topology: {logical_graph.number_of_nodes()} nodes, {logical_graph.number_of_edges()} edges")

# Check node types
node_types = {}
for node in logical_graph.nodes():
    node_type = logical_graph.nodes[node].get('type', 'Unknown')
    if node_type not in node_types:
        node_types[node_type] = []
    node_types[node_type].append(node)

print('\nNode types:')
for node_type, nodes in sorted(node_types.items()):
    print(f'  {node_type}: {len(nodes)} nodes')

# Check connectivity
undirected = logical_graph.to_undirected()
connected_components = list(nx.connected_components(undirected))
print(f'\nNumber of connected components: {len(connected_components)}')

if len(connected_components) > 1:
    print('WARNING: Topology is still disconnected!')
    for i, component in enumerate(connected_components):
        print(f'\nComponent {i+1} ({len(component)} nodes): {sorted(component)}')
else:
    print('SUCCESS: Topology is fully connected!')

# Check a sample service's edges
print('\nSample edges for svc_0:')
if 'svc_0' in logical_graph:
    for successor in logical_graph.successors('svc_0'):
        print(f'  svc_0 -> {successor}')
