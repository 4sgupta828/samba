"""
Component drill-down visualization.

Shows detailed metrics for a specific component when clicked in the topology.
Different component types show different relevant metrics.
"""

import pandas as pd
import networkx as nx
import plotly.graph_objects as go
from dash import dcc, html
import dash_bootstrap_components as dbc
from typing import Dict, List


def get_component_type(component_id: str, graph: nx.DiGraph) -> str:
    """Get the type of a component from the graph."""
    if component_id in graph.nodes:
        return graph.nodes[component_id].get('type', 'Unknown')
    return 'Unknown'


def create_metric_chart(metrics_df: pd.DataFrame, component_id: str,
                       metric_name: str, title: str, ylabel: str,
                       value_col: str = 'value') -> go.Figure:
    """Create a simple time-series chart for a specific metric."""
    # Filter for this component and metric
    data = metrics_df[
        (metrics_df['component_id'] == component_id) &
        (metrics_df['metric_name'] == metric_name)
    ].copy()

    fig = go.Figure()

    if not data.empty and value_col in data.columns:
        fig.add_trace(go.Scatter(
            x=data['sim_time'],
            y=data[value_col],
            mode='lines+markers',
            line=dict(width=2),
            marker=dict(size=4),
            name=title
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title=ylabel,
        height=200,
        margin=dict(l=50, r=20, t=40, b=30),
        showlegend=False
    )

    return fig


def create_percentile_chart(metrics_df: pd.DataFrame, component_id: str,
                           metric_name: str, title: str) -> go.Figure:
    """Create a chart showing P50/P90/P99 percentiles."""
    data = metrics_df[
        (metrics_df['component_id'] == component_id) &
        (metrics_df['metric_name'] == metric_name)
    ].copy()

    fig = go.Figure()

    percentiles = ['p50', 'p90', 'p99']
    colors = {'p50': '#3498db', 'p90': '#f39c12', 'p99': '#e74c3c'}

    for pct in percentiles:
        if pct in data.columns and not data.empty:
            fig.add_trace(go.Scatter(
                x=data['sim_time'],
                y=data[pct],
                name=pct.upper(),
                mode='lines',
                line=dict(color=colors[pct], width=2)
            ))

    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title="Latency (ms)",
        height=200,
        margin=dict(l=50, r=20, t=40, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    return fig


def create_service_drilldown(metrics_df: pd.DataFrame, component_id: str,
                             label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for ApiService."""
    charts = []

    # CPU utilization
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'container.cpu.utilization',
            'CPU Utilization',
            'Percentage (%)'
        ),
        config={'displayModeBar': False}
    ))

    # Memory usage
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'container.memory.usage_mb',
            'Memory Usage',
            'MB'
        ),
        config={'displayModeBar': False}
    ))

    # Request duration percentiles
    charts.append(dcc.Graph(
        figure=create_percentile_chart(
            metrics_df, component_id,
            'http.server.request.duration',
            'Request Duration'
        ),
        config={'displayModeBar': False}
    ))

    # Connection pool metrics
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'connection_pool.connections.active',
            'Active Connections',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Thread pool
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'thread_pool.threads.active',
            'Active Threads',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Queue depth
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'thread_pool.queue.depth',
            'Thread Pool Queue Depth',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    return charts


def create_database_drilldown(metrics_df: pd.DataFrame, component_id: str,
                              label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for SqlDatabase."""
    charts = []

    # Query latency percentiles
    charts.append(dcc.Graph(
        figure=create_percentile_chart(
            metrics_df, component_id,
            'db.query.latency',
            'Query Latency'
        ),
        config={'displayModeBar': False}
    ))

    # Active connections
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'db.connections.active',
            'Active Connections',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Connection rejections
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'db.connections.rejected',
            'Connection Rejections',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # CPU utilization
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'container.cpu.utilization',
            'CPU Utilization',
            'Percentage (%)'
        ),
        config={'displayModeBar': False}
    ))

    # Memory usage
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'container.memory.usage_mb',
            'Memory Usage',
            'MB'
        ),
        config={'displayModeBar': False}
    ))

    return charts


def create_cache_drilldown(metrics_df: pd.DataFrame, component_id: str,
                          label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for InMemoryCache."""
    charts = []

    # Hit rate
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'cache.hit_rate',
            'Cache Hit Rate',
            'Rate'
        ),
        config={'displayModeBar': False}
    ))

    # Miss rate
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'cache.miss_rate',
            'Cache Miss Rate',
            'Rate'
        ),
        config={'displayModeBar': False}
    ))

    # Eviction rate
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'cache.evictions',
            'Cache Evictions',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Memory usage
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'container.memory.usage_mb',
            'Memory Usage',
            'MB'
        ),
        config={'displayModeBar': False}
    ))

    return charts


def create_queue_drilldown(metrics_df: pd.DataFrame, component_id: str,
                          label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for MessageQueue."""
    charts = []

    # Messages visible
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'mq.messages.visible',
            'Messages Visible (Queue Depth)',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Messages in-flight
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'mq.messages.in_flight',
            'Messages In-Flight',
            'Count'
        ),
        config={'displayModeBar': False}
    ))

    # Message age
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'mq.messages.age_seconds',
            'Message Age',
            'Seconds'
        ),
        config={'displayModeBar': False}
    ))

    return charts


def create_external_drilldown(metrics_df: pd.DataFrame, component_id: str,
                             label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for ExternalService."""
    charts = []

    # Request rate
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'http.client.requests',
            'Request Rate',
            'Requests'
        ),
        config={'displayModeBar': False}
    ))

    # Error rate
    charts.append(dcc.Graph(
        figure=create_metric_chart(
            metrics_df, component_id,
            'http.client.errors',
            'Error Rate',
            'Errors'
        ),
        config={'displayModeBar': False}
    ))

    # Latency percentiles
    charts.append(dcc.Graph(
        figure=create_percentile_chart(
            metrics_df, component_id,
            'http.client.request.duration',
            'Request Latency'
        ),
        config={'displayModeBar': False}
    ))

    return charts


def create_component_drilldown(component_id: str, metrics_df: pd.DataFrame,
                              graph: nx.DiGraph, label_data: Dict):
    """
    Create detailed drill-down view for a specific component.

    Args:
        component_id: Component identifier
        metrics_df: DataFrame with all metrics
        graph: NetworkX graph with topology
        label_data: Label data with ground truth

    Returns:
        Dash HTML component with component details
    """
    # Get component type
    component_type = get_component_type(component_id, graph)

    # Determine if this is the root cause
    is_root_cause = (component_id == label_data.get('root_cause_node'))

    # Create header
    header = html.Div([
        html.H5(f"Component: {component_id}"),
        html.P([
            html.Strong("Type: "),
            html.Span(component_type),
            html.Span(" | "),
            html.Strong("Status: "),
            html.Span(
                "⚠️ ROOT CAUSE" if is_root_cause else "Normal",
                style={'color': 'red' if is_root_cause else 'green'}
            )
        ])
    ])

    # Create charts based on component type
    charts = []
    if component_type == 'ApiService':
        charts = create_service_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'SqlDatabase':
        charts = create_database_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'InMemoryCache':
        charts = create_cache_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'MessageQueue':
        charts = create_queue_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'ExternalService':
        charts = create_external_drilldown(metrics_df, component_id, label_data)
    else:
        charts = [html.P(f"No specific drill-down for component type: {component_type}")]

    # Layout charts in a grid
    chart_rows = []
    for i in range(0, len(charts), 3):
        row_charts = charts[i:i+3]
        chart_rows.append(
            dbc.Row([
                dbc.Col(chart, width=4) for chart in row_charts
            ], className="mb-3")
        )

    return html.Div([
        header,
        html.Hr(),
        *chart_rows
    ])


if __name__ == '__main__':
    # Test component drill-down
    import sys
    sys.path.append('..')
    from data_loader import load_episode

    print("Loading test episode...")
    episode_data = load_episode('ep_0', '../data/final_validation')

    # Test with root cause component
    root_cause = episode_data['label']['root_cause_node']
    print(f"\nCreating drill-down for root cause: {root_cause}")

    drilldown = create_component_drilldown(
        root_cause,
        episode_data['metrics_df'],
        episode_data['topology_graph'],
        episode_data['label']
    )

    print("Drill-down created successfully!")
