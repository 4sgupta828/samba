"""
Topology visualization chart.

Creates an interactive network graph showing system architecture with:
- Color coding by component type
- Root cause highlighting
- Clickable nodes for drill-down
- Edge styling based on relationship type
"""

import networkx as nx
import plotly.graph_objects as go
from typing import Dict


def get_node_color(node_type: str, is_root_cause: bool = False) -> str:
    """Get color for node based on type."""
    if is_root_cause:
        return '#ff4444'  # Bright red for root cause

    color_mapping = {
        'RequestGateway': '#7f8c8d',  # Gray
        'ApiService': '#3498db',      # Blue
        'Service': '#3498db',         # Blue (same as ApiService)
        'SqlDatabase': '#27ae60',     # Green
        'InMemoryCache': '#f39c12',   # Orange
        'MessageQueue': '#9b59b6',    # Purple
        'ExternalService': '#e74c3c', # Red
        'Pod': '#5dade2',             # Light blue
        'ComputeNode': '#85929e',     # Gray-blue
        'ComputeAgent': '#99a3a4'     # Light gray
    }
    return color_mapping.get(node_type, '#95a5a6')


def get_node_size(node_type: str, is_root_cause: bool = False) -> int:
    """Get size for node."""
    if is_root_cause:
        return 30
    if node_type == 'RequestGateway':
        return 25
    return 20


def get_node_symbol(node_type: str) -> str:
    """Get symbol for node based on type."""
    symbol_mapping = {
        'RequestGateway': 'diamond',
        'ApiService': 'circle',
        'Service': 'circle',
        'SqlDatabase': 'square',
        'InMemoryCache': 'hexagon',
        'MessageQueue': 'pentagon',
        'ExternalService': 'star',
        'Pod': 'circle-open',
        'ComputeNode': 'square-open',
        'ComputeAgent': 'diamond-open'
    }
    return symbol_mapping.get(node_type, 'circle')


def _calculate_spring_layout(graph: nx.DiGraph) -> Dict:
    """Calculate spring/force-directed layout."""
    return nx.spring_layout(graph, k=2, iterations=50, seed=42)


def _calculate_hierarchical_layout(graph: nx.DiGraph) -> Dict:
    """
    Calculate hierarchical layout with layers based on component type.
    Entry points (gateways) on left, services in middle, backends on right.
    """
    from collections import defaultdict

    # Define layer order (left to right: entry -> services -> backends -> infrastructure)
    layer_order = {
        'RequestGateway': 0,
        'LoadBalancer': 0,
        'ApiService': 1,
        'Service': 1,
        'Pod': 1,
        'InMemoryCache': 2,
        'SqlDatabase': 2,
        'MessageQueue': 2,
        'ExternalService': 2,
        'ComputeNode': 3,
        'ComputeAgent': 3,
        'ComputeInstance': 3,
        'Container': 3,
        'VM': 3,
    }

    # Group nodes by layer
    layers = defaultdict(list)
    for node in graph.nodes():
        node_type = graph.nodes[node].get('type', 'Unknown')
        layer = layer_order.get(node_type, 1)
        layers[layer].append(node)

    # Assign positions
    positions = {}
    max_layer = max(layers.keys()) if layers else 0

    for layer_idx, node_ids in layers.items():
        x = layer_idx / max(max_layer, 1) if max_layer > 0 else 0.5
        num_nodes = len(node_ids)

        for i, node_id in enumerate(node_ids):
            # Distribute vertically
            y = (i + 1) / (num_nodes + 1) if num_nodes > 0 else 0.5
            positions[node_id] = (x, y)

    return positions


def _calculate_circular_layout(graph: nx.DiGraph) -> Dict:
    """Calculate circular layout with nodes arranged in a circle."""
    import math

    positions = {}
    nodes = list(graph.nodes())
    num_nodes = len(nodes)

    for i, node_id in enumerate(nodes):
        angle = 2 * math.pi * i / num_nodes if num_nodes > 0 else 0
        x = 0.5 + 0.4 * math.cos(angle)
        y = 0.5 + 0.4 * math.sin(angle)
        positions[node_id] = (x, y)

    return positions


def extract_zoom_subgraph(graph: nx.DiGraph, start_node: str, max_depth: int = 2) -> nx.DiGraph:
    """
    Extract a focused subgraph starting from a node showing all its dependencies.

    Uses bidirectional BFS to explore both upstream (callers) and downstream (dependencies)
    from the start node equally.

    Args:
        graph: Full topology graph
        start_node: Starting node ID (the clicked node)
        max_depth: Maximum depth for recursive traversal
                   0 = node only
                   1 = node + direct neighbors (1 hop both directions)
                   2+ = recursive traversal (default: 2)
                   4+ = entire connected component

    Returns:
        Subgraph containing the start node and all reachable nodes within max_depth hops
    """
    if start_node not in graph:
        return nx.DiGraph()

    # Track nodes to include in subgraph
    included_nodes = set([start_node])

    # Depth 0: just the node itself, but include pods for service nodes
    if max_depth == 0:
        # If this is a service node, include its pods (direct children)
        node_type = graph.nodes[start_node].get('type', '') if start_node in graph else ''
        if node_type in ['ApiService', 'Service']:
            # Add pods that belong to this service
            for successor in graph.successors(start_node):
                successor_type = graph.nodes[successor].get('type', '')
                if successor_type in ['Pod', 'ComputeAgent']:
                    # Check if this pod belongs to the service
                    parent_service = graph.nodes[successor].get('parent_service')
                    if parent_service == start_node:
                        included_nodes.add(successor)

        return graph.subgraph(included_nodes).copy()

    # Depth 4+: return entire connected component (both directions)
    if max_depth >= 4:
        # Use undirected version to find connected component
        undirected = graph.to_undirected()
        connected_component = nx.node_connected_component(undirected, start_node)
        return graph.subgraph(connected_component).copy()

    # Bidirectional BFS: explore both upstream (predecessors) and downstream (successors)
    # Skip pods during traversal - we'll only include pods for the start node
    queue = [(start_node, 0)]
    visited = set([start_node])

    while queue:
        current_node, depth = queue.pop(0)

        # Don't expand beyond max_depth
        if depth >= max_depth:
            continue

        # Explore downstream (successors) - what this node calls/depends on
        for successor in graph.successors(current_node):
            # Skip pods/agents unless they belong to the start node
            successor_type = graph.nodes[successor].get('type', '')
            if successor_type in ['Pod', 'ComputeAgent']:
                # Only include if it's a pod of the start node
                parent_service = graph.nodes[successor].get('parent_service')
                if parent_service == start_node:
                    included_nodes.add(successor)
                continue  # Don't traverse through pods

            included_nodes.add(successor)
            if successor not in visited:
                visited.add(successor)
                queue.append((successor, depth + 1))

        # Explore upstream (predecessors) - what calls this node
        for predecessor in graph.predecessors(current_node):
            # Skip pods/agents - we don't want to traverse through them
            predecessor_type = graph.nodes[predecessor].get('type', '')
            if predecessor_type in ['Pod', 'ComputeAgent']:
                continue

            included_nodes.add(predecessor)
            if predecessor not in visited:
                visited.add(predecessor)
                queue.append((predecessor, depth + 1))

    # Create subgraph with all included nodes
    subgraph = graph.subgraph(included_nodes).copy()

    return subgraph


def create_topology_chart(graph: nx.DiGraph, label_data: Dict, visible_types: list = None,
                         hidden_nodes: list = None, layout_type: str = 'spring') -> go.Figure:
    """
    Create an interactive topology visualization using Plotly.

    Args:
        graph: NetworkX directed graph with nodes and edges
        label_data: Label data with ground truth (root_cause_node)
        visible_types: List of node types to show (None = show all)
        hidden_nodes: List of node IDs to hide (e.g., healthy nodes)
        layout_type: Layout algorithm ('spring', 'hierarchical', 'circular')

    Returns:
        Plotly figure
    """
    root_cause_node = label_data.get('root_cause_node')

    # Filter nodes based on visible types
    if visible_types is not None:
        # Create a subgraph with only visible node types
        filtered_nodes = [
            node for node in graph.nodes()
            if graph.nodes[node].get('type') in visible_types
        ]
        # Always keep root cause visible regardless of filter
        if root_cause_node and root_cause_node not in filtered_nodes:
            filtered_nodes.append(root_cause_node)

        graph = graph.subgraph(filtered_nodes).copy()

    # Filter out hidden nodes (e.g., healthy nodes)
    if hidden_nodes:
        visible_nodes = [node for node in graph.nodes() if node not in hidden_nodes]
        # Always keep root cause visible
        if root_cause_node and root_cause_node not in visible_nodes:
            visible_nodes.append(root_cause_node)
        graph = graph.subgraph(visible_nodes).copy()

    # Calculate layout based on selected type
    if layout_type == 'hierarchical':
        pos = _calculate_hierarchical_layout(graph)
    elif layout_type == 'circular':
        pos = _calculate_circular_layout(graph)
    else:  # spring/force-directed (default)
        pos = _calculate_spring_layout(graph)

    # Check if this is a network partition fault and get partition info
    is_network_partition = label_data.get('fault_type') == 'network_partition'
    partition_info = label_data.get('network_partition', {}) or label_data.get('fault_params', {})
    partition_source = partition_info.get('source_component_id', partition_info.get('source_component'))
    partition_target = partition_info.get('target_component_id', partition_info.get('target_component'))
    partition_bidirectional = partition_info.get('bidirectional', False)

    # Create edge traces with arrows
    edge_traces = []
    edge_annotations = []

    for edge in graph.edges():
        source, target = edge
        x0, y0 = pos[source]
        x1, y1 = pos[target]

        # Get edge type for styling
        edge_data = graph.get_edge_data(source, target)
        edge_type = edge_data.get('type', 'unknown') if edge_data else 'unknown'

        # Check if this edge is the partitioned edge
        is_partitioned_edge = False
        if is_network_partition and partition_source and partition_target:
            # Check for any edge that connects the two partitioned components
            # (could be service-level or pod-level connections)
            source_matches = (partition_source in source or source in partition_source)
            target_matches = (partition_target in target or target in partition_target)
            reverse_matches = (partition_target in source or source in partition_target) and \
                            (partition_source in target or target in partition_source)

            if (source_matches and target_matches) or (partition_bidirectional and reverse_matches):
                is_partitioned_edge = True

        # Async edges are dashed, sync are solid
        line_dash = 'dash' if 'async' in edge_type else 'solid'

        # Color edges differently based on type
        edge_color = '#9b59b6' if 'async' in edge_type else '#bdc3c7'
        edge_width = 1.5

        # Highlight partitioned edges with special styling
        if is_partitioned_edge:
            edge_color = '#ff4444'  # Bright red
            line_dash = 'dashdot'   # Special dash pattern
            edge_width = 3.0        # Thicker line
            hover_text = f"{source} ⚡ {target}<br>Type: {edge_type}<br>⚠️ NETWORK PARTITION"
        else:
            hover_text = f"{source} → {target}<br>Type: {edge_type}"

        edge_trace = go.Scatter(
            x=[x0, x1, None],
            y=[y0, y1, None],
            mode='lines',
            line=dict(width=edge_width, color=edge_color, dash=line_dash),
            hoverinfo='text',
            hovertext=hover_text,
            showlegend=False
        )
        edge_traces.append(edge_trace)

        # Add arrow annotation to show direction
        # Calculate arrow position (80% along the edge to avoid overlap with target node)
        arrow_x = x0 + 0.8 * (x1 - x0)
        arrow_y = y0 + 0.8 * (y1 - y0)

        # Calculate direction vector for arrow
        dx = x1 - x0
        dy = y1 - y0

        edge_annotations.append(
            dict(
                x=arrow_x,
                y=arrow_y,
                ax=x0 + 0.6 * dx,
                ay=y0 + 0.6 * dy,
                xref='x',
                yref='y',
                axref='x',
                ayref='y',
                showarrow=True,
                arrowhead=2,
                arrowsize=1.5,
                arrowwidth=2,
                arrowcolor=edge_color,
                opacity=0.8
            )
        )

    # Create node trace
    node_x = []
    node_y = []
    node_colors = []
    node_sizes = []
    node_symbols = []
    node_text = []
    node_hover = []

    for node in graph.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)

        # Get node attributes
        node_data = graph.nodes[node]
        node_type = node_data.get('type', 'Unknown')
        is_root_cause = (node == root_cause_node)

        # Check if this node is part of the network partition
        is_partitioned_node = False
        if is_network_partition and partition_source and partition_target:
            # Check if this node is one of the partitioned components or their pods
            if (partition_source in node or node in partition_source or
                partition_target in node or node in partition_target):
                is_partitioned_node = True

        # NEW: Use semantic name if available
        semantic_name = node_data.get('semantic_name')
        resource_profile = node_data.get('resource_profile')
        domain = node_data.get('domain')

        node_colors.append(get_node_color(node_type, is_root_cause))

        # Slightly enlarge partitioned nodes
        base_size = get_node_size(node_type, is_root_cause)
        if is_partitioned_node and not is_root_cause:
            node_sizes.append(base_size + 5)
        else:
            node_sizes.append(base_size)

        node_symbols.append(get_node_symbol(node_type))

        # Node text (displayed on graph) - use semantic name if available
        if semantic_name and semantic_name != node:
            display_text = f"{semantic_name}"
        else:
            display_text = f"{node}"
        if is_root_cause:
            display_text += "<br>⚠️ ROOT CAUSE"
        elif is_partitioned_node:
            display_text += "<br>🔌"
        node_text.append(display_text)

        # Hover text (additional info)
        if semantic_name and semantic_name != node:
            hover_text = f"<b>{semantic_name}</b><br>"
            hover_text += f"ID: {node}<br>"
        else:
            hover_text = f"<b>{node}</b><br>"
        hover_text += f"Type: {node_type}<br>"
        if resource_profile:
            hover_text += f"Profile: {resource_profile}<br>"
        if domain:
            hover_text += f"Domain: {domain}<br>"
        if is_root_cause:
            hover_text += "<b style='color:red'>ROOT CAUSE</b><br>"
        if is_partitioned_node:
            hover_text += "<b style='color:orange'>🔌 NETWORK PARTITION</b><br>"
        hover_text += f"<i>Click for details</i>"
        node_hover.append(hover_text)

    # Store node IDs in customdata for easier extraction on click
    node_ids = list(graph.nodes())

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode='markers+text',
        marker=dict(
            size=node_sizes,
            color=node_colors,
            symbol=node_symbols,
            line=dict(width=2, color='white')
        ),
        text=node_text,
        textposition="bottom center",
        textfont=dict(size=8),
        hovertext=node_hover,
        hoverinfo='text',
        customdata=node_ids,  # Store node IDs for click handler
        showlegend=False
    )

    # Create legend entries manually
    legend_entries = [
        ('Gateway', '#7f8c8d', 'diamond'),
        ('Service', '#3498db', 'circle'),
        ('Pod', '#5dade2', 'circle-open'),
        ('Database', '#27ae60', 'square'),
        ('Cache', '#f39c12', 'hexagon'),
        ('Queue', '#9b59b6', 'pentagon'),
        ('External', '#e74c3c', 'star'),
        ('Compute Node', '#85929e', 'square-open'),
        ('Root Cause', '#ff4444', 'circle'),
    ]

    legend_traces = []
    for name, color, symbol in legend_entries:
        legend_traces.append(go.Scatter(
            x=[None],
            y=[None],
            mode='markers',
            marker=dict(size=10, color=color, symbol=symbol),
            name=name,
            showlegend=True
        ))

    # Combine all traces
    fig = go.Figure(data=edge_traces + [node_trace] + legend_traces)

    # Update layout with dark theme and add edge annotations (arrows)
    layout_name = layout_type.capitalize()
    fig.update_layout(
        title=dict(
            text=f"System Topology ({layout_name} Layout) - {label_data['topology']['nodes']} nodes, "
                 f"{label_data['topology']['edges']} edges",
            x=0.5,
            xanchor='center',
            font=dict(color='#f9fafb')
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.12,
            xanchor="center",
            x=0.5,
            font=dict(color='#f9fafb')
        ),
        hovermode='closest',
        margin=dict(l=20, r=20, t=40, b=60),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb'),
        height=800,  # Increased from 600 for better visibility
        annotations=edge_annotations  # Add arrow annotations
    )

    return fig


if __name__ == '__main__':
    # Test the topology visualization
    import sys
    sys.path.append('..')
    from data_loader import load_episode

    print("Loading test episode...")
    episode_data = load_episode('ep_0', '../data/final_validation')

    print("Creating topology chart...")
    fig = create_topology_chart(
        episode_data['topology_graph'],
        episode_data['label']
    )

    print("Displaying chart...")
    fig.show()
