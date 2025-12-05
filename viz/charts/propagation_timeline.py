"""
Failure Propagation Timeline.

Visualizes how failures propagate through the system over time.
This is a novel feature designed to help understand causal relationships
in the GNN training data.

Implements Option B from the plan: Correlation Matrix showing component
health status over time buckets.
"""

import pandas as pd
import networkx as nx
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .timing_utils import get_fault_times_adjusted, adjust_time_for_warmup
from dash import dcc, html
import dash_bootstrap_components as dbc
from typing import Dict, List, Tuple
import numpy as np


def detect_component_degradation(metrics_df: pd.DataFrame, component_id: str,
                                 time_bucket_start: int, time_bucket_end: int) -> str:
    """
    Detect if a component is healthy, degraded, or failing in a time bucket.

    Args:
        metrics_df: DataFrame with all metrics
        component_id: Component identifier
        time_bucket_start: Start of time bucket (sim_time)
        time_bucket_end: End of time bucket

    Returns:
        Status string: 'healthy', 'degraded', or 'failing'
    """
    # Filter metrics for this component and time range
    comp_metrics = metrics_df[
        (metrics_df['component_id'] == component_id) &
        (metrics_df['sim_time'] >= time_bucket_start) &
        (metrics_df['sim_time'] < time_bucket_end)
    ]

    if comp_metrics.empty:
        return 'healthy'  # No data = assume healthy

    # Check for error metrics
    error_metrics = comp_metrics[
        comp_metrics['metric_name'].str.contains('error', case=False, na=False)
    ]

    if not error_metrics.empty and 'value' in error_metrics.columns:
        total_errors = error_metrics['value'].sum()
        if total_errors > 100:  # Threshold for failing
            return 'failing'
        elif total_errors > 10:  # Threshold for degraded
            return 'degraded'

    # Check CPU utilization
    cpu_metrics = comp_metrics[comp_metrics['metric_name'] == 'container.cpu.utilization']
    if not cpu_metrics.empty and 'value' in cpu_metrics.columns:
        avg_cpu = cpu_metrics['value'].mean()
        if avg_cpu > 90:
            return 'degraded'

    # Check latency (P99)
    latency_metrics = comp_metrics[
        comp_metrics['metric_name'].str.contains('latency|duration', case=False, na=False)
    ]
    if not latency_metrics.empty and 'p99' in latency_metrics.columns:
        avg_p99 = latency_metrics['p99'].mean()
        # Get baseline (first time bucket)
        baseline_metrics = metrics_df[
            (metrics_df['component_id'] == component_id) &
            (metrics_df['sim_time'] < time_bucket_start) &
            (metrics_df['metric_name'].str.contains('latency|duration', case=False, na=False))
        ]
        if not baseline_metrics.empty and 'p99' in baseline_metrics.columns:
            baseline_p99 = baseline_metrics['p99'].mean()
            if baseline_p99 > 0:
                latency_increase = (avg_p99 - baseline_p99) / baseline_p99
                if latency_increase > 2.0:  # 200% increase
                    return 'failing'
                elif latency_increase > 0.5:  # 50% increase
                    return 'degraded'

    return 'healthy'


def create_correlation_matrix(metrics_df: pd.DataFrame, graph: nx.DiGraph,
                              label_data: Dict) -> go.Figure:
    """
    Create a correlation matrix showing component health over time buckets.

    Args:
        metrics_df: DataFrame with all metrics
        graph: NetworkX graph with topology
        label_data: Label data with ground truth

    Returns:
        Plotly figure with heatmap
    """
    # Define time buckets (every 30s)
    max_time = int(metrics_df['sim_time'].max()) if 'sim_time' in metrics_df.columns else 600
    bucket_size = 30
    time_buckets = list(range(0, max_time + bucket_size, bucket_size))

    # Get all components
    components = sorted(list(graph.nodes()))

    # Build status matrix
    status_matrix = []
    status_labels = []

    for component in components:
        row = []
        for i in range(len(time_buckets) - 1):
            status = detect_component_degradation(
                metrics_df, component,
                time_buckets[i], time_buckets[i + 1]
            )
            row.append(status)
        status_matrix.append(row)
        status_labels.append(component)

    # Convert to numeric for heatmap (healthy=0, degraded=1, failing=2)
    status_to_value = {'healthy': 0, 'degraded': 1, 'failing': 2}
    numeric_matrix = [
        [status_to_value[status] for status in row]
        for row in status_matrix
    ]

    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=numeric_matrix,
        x=[f"{time_buckets[i]}-{time_buckets[i+1]}s" for i in range(len(time_buckets) - 1)],
        y=status_labels,
        colorscale=[
            [0, '#2ecc71'],    # Green for healthy
            [0.5, '#f39c12'],  # Orange for degraded
            [1, '#e74c3c']     # Red for failing
        ],
        showscale=True,
        colorbar=dict(
            title="Status",
            tickmode='array',
            tickvals=[0, 1, 2],
            ticktext=['Healthy', 'Degraded', 'Failing']
        ),
        hovertemplate='Component: %{y}<br>Time: %{x}<br>Status: %{text}<extra></extra>',
        text=status_matrix
    ))

    # Add fault injection line
    times = get_fault_times_adjusted(label_data)
    bucket_index = times['fault_start'] // bucket_size
    fig.add_vline(
        x=bucket_index,
        line_dash="dash",
        line_color="darkred",
        line_width=3,
        annotation_text="Fault Injection",
        annotation_position="top"
    )

    # Add fault removal line if recovery exists
    if times['recovery_start'] is not None:
        recovery_bucket_index = times['recovery_start'] // bucket_size
        fig.add_vline(
            x=recovery_bucket_index,
            line_dash="dash",
            line_color="green",
            line_width=3,
            annotation_text="Fault Removal",
            annotation_position="top"
        )

    # Highlight root cause component
    root_cause = label_data.get('root_cause_node')
    if root_cause in components:
        root_cause_index = components.index(root_cause)
        fig.add_hline(
            y=root_cause_index,
            line_dash="dot",
            line_color="red",
            line_width=2
        )

    fig.update_layout(
        title="Failure Propagation: Component Health Over Time",
        xaxis_title="Time Bucket",
        yaxis_title="Component",
        height=max(400, len(components) * 20),  # Scale height with number of components
        margin=dict(l=100, r=20, t=60, b=60)
    )

    return fig


def create_metric_cascade(metrics_df: pd.DataFrame, graph: nx.DiGraph,
                         label_data: Dict, metric_name: str = 'container.cpu.utilization') -> go.Figure:
    """
    Create a metric cascade view showing when each component's metrics degrade.

    Args:
        metrics_df: DataFrame with all metrics
        graph: NetworkX graph with topology
        label_data: Label data with ground truth
        metric_name: Which metric to visualize

    Returns:
        Plotly figure with small multiples
    """
    # Get all components
    components = sorted(list(graph.nodes()))[:15]  # Limit to first 15 for visibility

    # Create subplots
    fig = make_subplots(
        rows=len(components),
        cols=1,
        subplot_titles=[f"{comp}" for comp in components],
        vertical_spacing=0.02,
        shared_xaxes=True
    )

    root_cause = label_data.get('root_cause_node')

    for idx, component in enumerate(components):
        comp_data = metrics_df[
            (metrics_df['component_id'] == component) &
            (metrics_df['metric_name'] == metric_name)
        ]

        if not comp_data.empty and 'value' in comp_data.columns:
            # Normalize values to 0-1 range for comparison
            values = comp_data['value'].values
            if values.max() > 0:
                normalized = values / values.max()
            else:
                normalized = values

            color = 'red' if component == root_cause else 'lightblue'

            fig.add_trace(
                go.Scatter(
                    x=comp_data['sim_time'],
                    y=normalized,
                    mode='lines',
                    line=dict(color=color, width=1),
                    fill='tozeroy',
                    showlegend=False,
                    hovertemplate=f'{component}<br>Time: %{{x}}s<br>Value: %{{y:.2f}}<extra></extra>'
                ),
                row=idx + 1,
                col=1
            )

    # Add fault injection and removal lines
    times = get_fault_times_adjusted(label_data)

    for idx in range(len(components)):
        # Fault injection line
        fig.add_vline(
            x=times['fault_start'],
            line_dash="dash",
            line_color="red",
            line_width=1,
            row=idx + 1,
            col=1
        )
        # Fault removal line
        if times['recovery_start'] is not None:
            fig.add_vline(
                x=times['recovery_start'],
                line_dash="dash",
                line_color="green",
                line_width=1,
                row=idx + 1,
                col=1
            )

    fig.update_layout(
        title=f"Metric Cascade: {metric_name} (Normalized)",
        height=len(components) * 50 + 100,
        showlegend=False,
        margin=dict(l=80, r=20, t=60, b=40)
    )

    fig.update_xaxes(title_text="Simulation Time (s)", row=len(components), col=1)

    return fig


def create_propagation_graph(metrics_df: pd.DataFrame, graph: nx.DiGraph,
                            label_data: Dict, ground_truth: Dict) -> List:
    """
    Create a visual representation of propagation path.

    Args:
        metrics_df: DataFrame with all metrics
        graph: NetworkX graph with topology
        label_data: Label data with ground truth
        ground_truth: Ground truth events

    Returns:
        List of HTML components showing propagation path
    """
    root_cause = label_data.get('root_cause_node')
    times = get_fault_times_adjusted(label_data)
    fault_start = times['fault_start']

    # Find downstream components (BFS from root cause)
    if root_cause not in graph.nodes():
        return [html.P("Root cause node not found in graph")]

    # Get all descendants (downstream components)
    try:
        # For directed graph, get predecessors (who calls the root cause)
        predecessors = list(nx.ancestors(graph, root_cause))
    except:
        predecessors = []

    # Create propagation path description
    path_elements = [
        html.H6("Propagation Path", className="mb-3"),
        html.Div([
            html.Strong("Root Cause: "),
            html.Span(root_cause, style={'color': 'red', 'fontWeight': 'bold'}),
            html.Span(f" (failure starts at {fault_start}s)")
        ], className="mb-2"),
    ]

    if predecessors:
        path_elements.append(html.Div([
            html.Strong("Upstream Components Affected:"),
            html.Ul([
                html.Li(comp) for comp in sorted(predecessors)[:10]
            ])
        ]))
    else:
        path_elements.append(html.P("No upstream dependencies detected", className="text-muted"))

    return path_elements


def create_propagation_timeline(metrics_df: pd.DataFrame, graph: nx.DiGraph,
                               label_data: Dict, ground_truth: Dict):
    """
    Create failure propagation timeline visualization.

    Args:
        metrics_df: DataFrame with all metrics
        graph: NetworkX graph with topology
        label_data: Label data with ground truth
        ground_truth: Ground truth events

    Returns:
        Dash HTML component with propagation visualization
    """
    # Create correlation matrix (primary visualization)
    correlation_matrix = create_correlation_matrix(metrics_df, graph, label_data)

    # Create metric cascade (secondary visualization)
    metric_cascade = create_metric_cascade(metrics_df, graph, label_data)

    # Create propagation path description
    propagation_path = create_propagation_graph(metrics_df, graph, label_data, ground_truth)

    # Combine into layout (removed nested Container to fix layout)
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div(propagation_path)
            ], width=3),
            dbc.Col([
                dcc.Graph(figure=correlation_matrix, config={'displayModeBar': False})
            ], width=9)
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dcc.Graph(figure=metric_cascade, config={'displayModeBar': False})
            ], width=12)
        ])
    ])


if __name__ == '__main__':
    # Test propagation timeline
    import sys
    sys.path.append('..')
    from data_loader import load_episode

    print("Loading test episode...")
    episode_data = load_episode('ep_0', '../data/final_validation')

    print("Creating propagation timeline...")
    timeline = create_propagation_timeline(
        episode_data['metrics_df'],
        episode_data['topology_graph'],
        episode_data['label'],
        episode_data['ground_truth']
    )

    print("Propagation timeline created successfully!")
