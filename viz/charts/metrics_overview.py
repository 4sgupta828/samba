"""
Golden Signals Dashboard.

Creates 4 key metric charts that reveal system health:
1. Request Rate - Traffic patterns
2. Error Rate - Failure propagation
3. Latency Percentiles - Performance degradation
4. Saturation - Resource utilization
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dcc, html
import dash_bootstrap_components as dbc
from typing import Dict


def add_fault_markers(fig: go.Figure, label_data: Dict, annotation_position: str = "top"):
    """
    Add fault injection and removal vertical lines to a figure.

    Args:
        fig: Plotly figure to add markers to
        label_data: Label data containing fault timing information
        annotation_position: Position for annotations ("top" or "bottom")
    """
    # Add fault injection marker
    fault_start = label_data.get('fault_start_time', 0)
    fig.add_vline(
        x=fault_start,
        line_dash="dash",
        line_color="red",
        line_width=2,
        annotation_text="Fault Injection",
        annotation_position=annotation_position
    )

    # Add fault removal marker if recovery data exists
    recovery_start = label_data.get('recovery_start_time')
    if recovery_start is not None:
        fig.add_vline(
            x=recovery_start,
            line_dash="dash",
            line_color="green",
            line_width=2,
            annotation_text="Fault Removal",
            annotation_position=annotation_position
        )


def create_request_rate_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """Create request rate chart showing traffic patterns."""
    # Filter for workload metrics
    workload_df = metrics_df[metrics_df['metric_name'] == 'workload.requests'].copy()

    if workload_df.empty:
        return go.Figure().update_layout(title="Request Rate - No Data")

    fig = go.Figure()

    # Plot attempted and success requests
    for req_type in ['attempted', 'success']:
        data = workload_df[workload_df['type'] == req_type]
        if not data.empty:
            fig.add_trace(go.Scatter(
                x=data['sim_time'],
                y=data['value'],
                name=req_type.title(),
                mode='lines+markers',
                line=dict(width=2)
            ))

    # Add fault injection and removal markers
    add_fault_markers(fig, label_data, annotation_position="top")

    fig.update_layout(
        title="Request Rate",
        xaxis_title="Simulation Time (s)",
        yaxis_title="Requests per bucket",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=250,
        margin=dict(l=50, r=20, t=40, b=40)
    )

    return fig


def create_error_rate_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """Create error rate chart showing failure propagation."""
    # Filter for error metrics
    error_df = metrics_df[metrics_df['metric_name'].str.contains('error', case=False, na=False)].copy()

    if error_df.empty:
        return go.Figure().update_layout(title="Error Rate - No Data")

    fig = go.Figure()

    # Aggregate errors by simulation time
    if 'sim_time' in error_df.columns and 'value' in error_df.columns:
        error_agg = error_df.groupby('sim_time')['value'].sum().reset_index()

        fig.add_trace(go.Scatter(
            x=error_agg['sim_time'],
            y=error_agg['value'],
            name='Total Errors',
            mode='lines+markers',
            line=dict(color='red', width=2),
            fill='tozeroy',
            fillcolor='rgba(231, 76, 60, 0.2)'
        ))

    # Add fault injection and removal markers
    add_fault_markers(fig, label_data, annotation_position="top")

    fig.update_layout(
        title="Error Rate",
        xaxis_title="Simulation Time (s)",
        yaxis_title="Errors",
        height=250,
        margin=dict(l=50, r=20, t=40, b=40)
    )

    return fig


def create_latency_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """Create latency percentiles chart."""
    # Filter for latency/duration metrics with percentiles
    latency_metrics = [
        'http.server.request.duration',
        'db.query.latency',
        'http.client.request.duration'
    ]

    latency_df = metrics_df[metrics_df['metric_name'].isin(latency_metrics)].copy()

    if latency_df.empty or 'p50' not in latency_df.columns:
        return go.Figure().update_layout(title="Latency - No Data")

    fig = go.Figure()

    # Aggregate percentiles across all components
    percentiles = ['p50', 'p90', 'p99']
    colors = {'p50': '#3498db', 'p90': '#f39c12', 'p99': '#e74c3c'}

    for percentile in percentiles:
        if percentile in latency_df.columns:
            # Average percentile across all components for each time
            pct_data = latency_df.groupby('sim_time')[percentile].mean().reset_index()

            fig.add_trace(go.Scatter(
                x=pct_data['sim_time'],
                y=pct_data[percentile],
                name=percentile.upper(),
                mode='lines',
                line=dict(color=colors.get(percentile), width=2)
            ))

    # Add fault injection and removal markers
    add_fault_markers(fig, label_data, annotation_position="top")

    fig.update_layout(
        title="Latency Percentiles (Avg across components)",
        xaxis_title="Simulation Time (s)",
        yaxis_title="Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=250,
        margin=dict(l=50, r=20, t=40, b=40)
    )

    return fig


def create_saturation_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """Create saturation chart showing resource utilization."""
    # Filter for CPU and memory metrics
    cpu_df = metrics_df[metrics_df['metric_name'] == 'container.cpu.utilization'].copy()
    mem_df = metrics_df[metrics_df['metric_name'] == 'container.memory.usage_mb'].copy()

    fig = go.Figure()

    # Plot CPU utilization
    if not cpu_df.empty and 'value' in cpu_df.columns:
        cpu_agg = cpu_df.groupby('sim_time')['value'].mean().reset_index()

        fig.add_trace(go.Scatter(
            x=cpu_agg['sim_time'],
            y=cpu_agg['value'],
            name='CPU Util (%)',
            mode='lines',
            line=dict(color='#3498db', width=2),
            yaxis='y1'
        ))

    # Plot memory usage on secondary axis
    if not mem_df.empty and 'value' in mem_df.columns:
        mem_agg = mem_df.groupby('sim_time')['value'].mean().reset_index()

        fig.add_trace(go.Scatter(
            x=mem_agg['sim_time'],
            y=mem_agg['value'],
            name='Memory (MB)',
            mode='lines',
            line=dict(color='#e67e22', width=2),
            yaxis='y2'
        ))

    # Add fault injection and removal markers
    add_fault_markers(fig, label_data, annotation_position="top")

    fig.update_layout(
        title="Resource Saturation (Avg across components)",
        xaxis_title="Simulation Time (s)",
        yaxis=dict(title="CPU Utilization (%)", side='left'),
        yaxis2=dict(title="Memory Usage (MB)", overlaying='y', side='right'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=250,
        margin=dict(l=50, r=50, t=40, b=40)
    )

    return fig


def create_golden_signals_dashboard(metrics_df: pd.DataFrame, label_data: Dict):
    """
    Create a dashboard with 4 golden signal charts.

    Args:
        metrics_df: DataFrame with all metrics
        label_data: Label data with ground truth

    Returns:
        Dash HTML component with 4 charts
    """
    # Create all 4 charts
    request_chart = create_request_rate_chart(metrics_df, label_data)
    error_chart = create_error_rate_chart(metrics_df, label_data)
    latency_chart = create_latency_chart(metrics_df, label_data)
    saturation_chart = create_saturation_chart(metrics_df, label_data)

    # Layout in 2x2 grid (removed nested Container to fix layout)
    return html.Div([
        dbc.Row([
            dbc.Col([
                dcc.Graph(figure=request_chart, config={'displayModeBar': False})
            ], width=6),
            dbc.Col([
                dcc.Graph(figure=error_chart, config={'displayModeBar': False})
            ], width=6),
        ], className="mb-2"),
        dbc.Row([
            dbc.Col([
                dcc.Graph(figure=latency_chart, config={'displayModeBar': False})
            ], width=6),
            dbc.Col([
                dcc.Graph(figure=saturation_chart, config={'displayModeBar': False})
            ], width=6),
        ]),
    ])


if __name__ == '__main__':
    # Test the golden signals dashboard
    import sys
    sys.path.append('..')
    from data_loader import load_episode

    print("Loading test episode...")
    episode_data = load_episode('ep_0', '../data/final_validation')

    print("Creating golden signals dashboard...")
    dashboard = create_golden_signals_dashboard(
        episode_data['metrics_df'],
        episode_data['label']
    )

    print("Dashboard created successfully!")
    print(f"Metrics shape: {episode_data['metrics_df'].shape}")
    print(f"Unique metrics: {episode_data['metrics_df']['metric_name'].nunique()}")
