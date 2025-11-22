#!/usr/bin/env python3
"""Test script to analyze metric names."""

from data_loader import load_episode
import pandas as pd

episode_data = load_episode('ep_0', '../data/final_validation')
metrics_df = episode_data['metrics_df']

# Get unique metrics per component type
graph = episode_data['topology_graph']

component_types = {}
for node in graph.nodes():
    node_type = graph.nodes[node].get('type', 'Unknown')
    if node_type != 'ComputeAgent':  # Skip compute agents
        if node_type not in component_types:
            component_types[node_type] = []
        component_types[node_type].append(node)

print('Metric names by component type:\n')

for node_type, nodes in sorted(component_types.items()):
    print(f'\n{node_type}:')
    # Get metrics for first node of this type
    sample_node = nodes[0]
    node_metrics = metrics_df[metrics_df['component_id'] == sample_node]

    if not node_metrics.empty:
        metric_names = node_metrics['metric_name'].unique()
        print(f'  Sample node: {sample_node}')
        print(f'  Metrics ({len(metric_names)}):')
        for metric in sorted(metric_names):
            print(f'    - {metric}')
    else:
        print(f'  No metrics found for {sample_node}')

# Also check global metrics
print('\n\nGlobal metrics (component_id == "global"):')
global_metrics = metrics_df[metrics_df['component_id'] == 'global']
if not global_metrics.empty:
    for metric in sorted(global_metrics['metric_name'].unique()):
        print(f'  - {metric}')
