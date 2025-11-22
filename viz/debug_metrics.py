#!/usr/bin/env python3
"""Debug script to check metric availability for all nodes."""

from data_loader import load_episode
import pandas as pd

episode_data = load_episode('ep_0', '../data/final_validation')
metrics_df = episode_data['metrics_df']
graph = episode_data['logical_topology_graph']

print("=" * 80)
print("METRIC AVAILABILITY BY NODE TYPE")
print("=" * 80)

# Group by node type
node_types = {}
for node in graph.nodes():
    node_type = graph.nodes[node].get('type', 'Unknown')
    if node_type not in node_types:
        node_types[node_type] = []
    node_types[node_type].append(node)

for node_type in sorted(node_types.keys()):
    print(f"\n{node_type}")
    print("-" * 80)

    nodes = node_types[node_type]

    # Check first 3 nodes of this type
    for node in nodes[:3]:
        node_metrics = metrics_df[metrics_df['component_id'] == node]

        if node_metrics.empty:
            print(f"  {node}: NO METRICS FOUND ❌")
        else:
            metric_names = sorted(node_metrics['metric_name'].unique())
            print(f"  {node}: {len(node_metrics)} records, {len(metric_names)} unique metrics")
            for metric in metric_names:
                count = len(node_metrics[node_metrics['metric_name'] == metric])
                print(f"    - {metric} ({count} records)")

    if len(nodes) > 3:
        print(f"  ... and {len(nodes) - 3} more nodes of this type")

# Check if there are any component IDs in metrics that aren't in the graph
print("\n" + "=" * 80)
print("METRICS FOR NON-GRAPH COMPONENTS")
print("=" * 80)

all_component_ids = set(metrics_df['component_id'].unique())
graph_node_ids = set(graph.nodes())
extra_components = all_component_ids - graph_node_ids - {'global'}

if extra_components:
    print(f"\nFound {len(extra_components)} component IDs in metrics that aren't in the logical graph:")
    for comp_id in sorted(extra_components):
        comp_metrics = metrics_df[metrics_df['component_id'] == comp_id]
        metric_names = comp_metrics['metric_name'].unique()
        print(f"  {comp_id}: {len(comp_metrics)} records, metrics: {metric_names[:3]}")
else:
    print("\nAll metric component IDs are present in the graph ✓")

# Check global metrics
print("\n" + "=" * 80)
print("GLOBAL METRICS")
print("=" * 80)

global_metrics = metrics_df[metrics_df['component_id'] == 'global']
if not global_metrics.empty:
    print(f"\nFound {len(global_metrics)} global metric records:")
    for metric in sorted(global_metrics['metric_name'].unique()):
        count = len(global_metrics[global_metrics['metric_name'] == metric])
        print(f"  - {metric} ({count} records)")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

nodes_with_metrics = 0
nodes_without_metrics = 0

for node in graph.nodes():
    node_metrics = metrics_df[metrics_df['component_id'] == node]
    if not node_metrics.empty:
        nodes_with_metrics += 1
    else:
        nodes_without_metrics += 1

print(f"\nNodes with metrics: {nodes_with_metrics}/{len(graph.nodes())}")
print(f"Nodes without metrics: {nodes_without_metrics}/{len(graph.nodes())}")

if nodes_without_metrics > 0:
    print(f"\n⚠️  WARNING: {nodes_without_metrics} nodes have NO metrics!")
    print("Nodes without metrics:")
    for node in graph.nodes():
        node_metrics = metrics_df[metrics_df['component_id'] == node]
        if node_metrics.empty:
            node_type = graph.nodes[node].get('type')
            print(f"  - {node} ({node_type})")
