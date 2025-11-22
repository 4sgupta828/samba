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
        'SqlDatabase': '#27ae60',     # Green
        'InMemoryCache': '#f39c12',   # Orange
        'MessageQueue': '#9b59b6',    # Purple
        'ExternalService': '#e74c3c'  # Red
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
        'SqlDatabase': 'square',
        'InMemoryCache': 'hexagon',
        'MessageQueue': 'pentagon',
        'ExternalService': 'star'
    }
    return symbol_mapping.get(node_type, 'circle')


def create_topology_chart(graph: nx.DiGraph, label_data: Dict, visible_types: list = None, hidden_nodes: list = None) -> go.Figure:
    """
    Create an interactive topology visualization using Plotly.

    Args:
        graph: NetworkX directed graph with nodes and edges
        label_data: Label data with ground truth (root_cause_node)
        visible_types: List of node types to show (None = show all)
        hidden_nodes: List of node IDs to hide (e.g., healthy nodes)

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

    # Use spring layout for positioning
    pos = nx.spring_layout(graph, k=2, iterations=50, seed=42)

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

        # Async edges are dashed, sync are solid
        line_dash = 'dash' if 'async' in edge_type else 'solid'

        # Color edges differently based on type
        edge_color = '#9b59b6' if 'async' in edge_type else '#bdc3c7'

        edge_trace = go.Scatter(
            x=[x0, x1, None],
            y=[y0, y1, None],
            mode='lines',
            line=dict(width=1.5, color=edge_color, dash=line_dash),
            hoverinfo='text',
            hovertext=f"{source} → {target}<br>Type: {edge_type}",
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

        node_colors.append(get_node_color(node_type, is_root_cause))
        node_sizes.append(get_node_size(node_type, is_root_cause))
        node_symbols.append(get_node_symbol(node_type))

        # Node text (displayed on graph)
        display_text = f"{node}"
        if is_root_cause:
            display_text += "<br>⚠️ ROOT CAUSE"
        node_text.append(display_text)

        # Hover text (additional info)
        hover_text = f"<b>{node}</b><br>"
        hover_text += f"Type: {node_type}<br>"
        if is_root_cause:
            hover_text += "<b style='color:red'>ROOT CAUSE</b><br>"
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
        ('Database', '#27ae60', 'square'),
        ('Cache', '#f39c12', 'hexagon'),
        ('Queue', '#9b59b6', 'pentagon'),
        ('External', '#e74c3c', 'star'),
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
    fig.update_layout(
        title=dict(
            text=f"System Topology - {label_data['topology']['nodes']} nodes, "
                 f"{label_data['topology']['edges']} edges",
            x=0.5,
            xanchor='center',
            font=dict(color='#f9fafb')
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
            font=dict(color='#f9fafb')
        ),
        hovermode='closest',
        margin=dict(l=20, r=20, t=40, b=80),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb'),
        height=600,
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
