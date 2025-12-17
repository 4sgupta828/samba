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
from typing import Dict, List, Optional

# Import workload charts
from charts.workload import (
    create_connection_pool_chart,
    create_circuit_breaker_chart,
    create_request_outcomes_chart
)


def get_component_type(component_id: str, graph: nx.DiGraph) -> str:
    """Get the type of a component from the graph."""
    if component_id in graph.nodes:
        return graph.nodes[component_id].get('type', 'Unknown')
    return 'Unknown'


def create_metric_chart(metrics_df: pd.DataFrame, component_id: str,
                       metric_name: str, title: str, ylabel: str,
                       value_col: str = 'value', aggregate_pattern: str = None) -> go.Figure:
    """Create a simple time-series chart for a specific metric.

    Args:
        metrics_df: DataFrame with all metrics
        component_id: Component ID to filter for
        metric_name: Metric name to display
        title: Chart title
        ylabel: Y-axis label
        value_col: Column name containing the values
        aggregate_pattern: If provided, will aggregate metrics from all components matching this pattern
    """
    fig = go.Figure()

    if aggregate_pattern:
        # Aggregate metrics from multiple components (e.g., all compute agents)
        data = metrics_df[
            (metrics_df['component_id'].str.startswith(aggregate_pattern, na=False)) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

        if not data.empty and value_col in data.columns:
            # Group by sim_time and aggregate
            aggregated = data.groupby('sim_time')[value_col].mean().reset_index()
            fig.add_trace(go.Scatter(
                x=aggregated['sim_time'],
                y=aggregated[value_col],
                mode='lines+markers',
                line=dict(width=2),
                marker=dict(size=4),
                name=f'{title} (avg across agents)'
            ))
    else:
        # Single component metric
        data = metrics_df[
            (metrics_df['component_id'] == component_id) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

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
        showlegend=False,
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
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
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
    )

    return fig


def create_metric_chart_filtered(metrics_df: pd.DataFrame, component_id: str,
                                  metric_name: str, title: str, ylabel: str,
                                  filter_col: str, filter_val: str,
                                  value_col: str = 'value') -> go.Figure:
    """Create a time-series chart for a metric filtered by a label column."""
    fig = go.Figure()

    # Filter by component_id, metric_name, AND the specified label column
    data = metrics_df[
        (metrics_df['component_id'] == component_id) &
        (metrics_df['metric_name'] == metric_name) &
        (metrics_df[filter_col] == filter_val)
    ].copy()

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
        showlegend=False,
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
    )

    return fig


def create_percentile_chart_filtered(metrics_df: pd.DataFrame, component_id: str,
                                     metric_name: str, title: str,
                                     filter_col: str, filter_val: str) -> go.Figure:
    """Create a percentile chart filtered by a label column."""
    data = metrics_df[
        (metrics_df['component_id'] == component_id) &
        (metrics_df['metric_name'] == metric_name) &
        (metrics_df[filter_col] == filter_val)
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
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
    )

    return fig


def create_service_aggregated_chart(metrics_df: pd.DataFrame, service_id: str,
                                   metric_name: str, title: str, ylabel: str,
                                   agg_method: str = 'auto', pod_ids: list = None) -> go.Figure:
    """
    Create aggregated chart for service by aggregating Pod metrics.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        ylabel: Y-axis label
        agg_method: Aggregation method - 'sum', 'mean', or 'auto' (default: 'auto')
                   'auto' chooses based on metric type:
                   - 'sum' for requests, errors, connections, threads, queue depths
                   - 'mean' for CPU utilization
        pod_ids: List of pod IDs to aggregate (if None, will filter by service.id tag)
    """
    # Aggregate Pod metrics by pod IDs (preferred) or service.id tag (fallback)
    if pod_ids:
        data = metrics_df[
            (metrics_df['component_id'].isin(pod_ids)) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()
    else:
        # Fallback to service.id filtering
        data = metrics_df[
            (metrics_df.get('service.id', pd.Series(dtype='object')) == service_id) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Determine aggregation method
    if agg_method == 'auto':
        # Use mean for CPU utilization (it's a percentage)
        if 'cpu.utilization' in metric_name:
            agg_func = 'mean'
        # Use sum for everything else (requests, errors, connections, threads, queue depths, memory)
        else:
            agg_func = 'sum'
    else:
        agg_func = agg_method

    # Group by sim_time and aggregate
    if agg_func == 'mean':
        aggregated = data.groupby('sim_time', as_index=False)['value'].mean()
    else:
        aggregated = data.groupby('sim_time', as_index=False)['value'].sum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['value'],
        mode='lines',
        line=dict(color='#3b82f6', width=2),
        name=ylabel
    ))

    fig.update_layout(
        title=title,
        xaxis_title='Simulation Time (s)',
        yaxis_title=ylabel,
        template='plotly_dark',
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor='#1f2937',
        paper_bgcolor='#111827',
        font=dict(color='#f9fafb')
    )

    return fig


def create_service_aggregated_percentile_chart(metrics_df: pd.DataFrame, service_id: str,
                                               metric_name: str, title: str, pod_ids: list = None) -> go.Figure:
    """
    Create aggregated percentile chart for service by aggregating Pod metrics.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        pod_ids: List of pod IDs to aggregate (if None, will filter by service.id tag)
    """
    # Aggregate Pod percentile metrics by pod IDs (preferred) or service.id tag (fallback)
    if pod_ids:
        data = metrics_df[
            (metrics_df['component_id'].isin(pod_ids)) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()
    else:
        # Fallback to service.id filtering
        data = metrics_df[
            (metrics_df.get('service.id', pd.Series(dtype='object')) == service_id) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Group by sim_time and aggregate percentiles (mean across all pods)
    aggregated = data.groupby('sim_time', as_index=False).agg({
        'p50': 'mean',
        'p90': 'mean',
        'p99': 'mean'
    })

    fig = go.Figure()

    # P99
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p99'],
        mode='lines',
        name='P99',
        line=dict(color='#ef4444', width=1.5)
    ))

    # P90
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p90'],
        mode='lines',
        name='P90',
        line=dict(color='#f59e0b', width=1.5)
    ))

    # P50 (median)
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p50'],
        mode='lines',
        name='P50 (Median)',
        line=dict(color='#3b82f6', width=2)
    ))

    fig.update_layout(
        title=title,
        xaxis_title='Simulation Time (s)',
        yaxis_title='Latency (ms)',
        template='plotly_dark',
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor='#1f2937',
        paper_bgcolor='#111827',
        font=dict(color='#f9fafb')
    )

    return fig


def create_service_aggregated_chart_filtered(metrics_df: pd.DataFrame, service_id: str,
                                            metric_name: str, title: str, ylabel: str,
                                            filter_col: str, filter_val: str,
                                            agg_method: str = 'sum', pod_ids: list = None) -> go.Figure:
    """
    Create aggregated chart for service with additional filter (e.g., for specific dependency).

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        ylabel: Y-axis label
        filter_col: Column name to filter on (e.g., 'dependency_id')
        filter_val: Value to filter for
        agg_method: Aggregation method - 'sum' or 'mean' (default: 'sum' for dependency metrics)
        pod_ids: List of pod IDs to aggregate (if None, will filter by service.id tag)
    """
    # Aggregate Pod metrics by pod IDs (preferred) or service.id tag (fallback) with additional filter
    if pod_ids:
        data = metrics_df[
            (metrics_df['component_id'].isin(pod_ids)) &
            (metrics_df['metric_name'] == metric_name) &
            (metrics_df[filter_col] == filter_val)
        ].copy()
    else:
        # Fallback to service.id filtering
        data = metrics_df[
            (metrics_df.get('service.id', pd.Series(dtype='object')) == service_id) &
            (metrics_df['metric_name'] == metric_name) &
            (metrics_df[filter_col] == filter_val)
        ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Group by sim_time and aggregate (always sum for dependency metrics which are requests/errors)
    if agg_method == 'mean':
        aggregated = data.groupby('sim_time', as_index=False)['value'].mean()
    else:
        aggregated = data.groupby('sim_time', as_index=False)['value'].sum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['value'],
        mode='lines',
        line=dict(color='#3b82f6', width=2),
        name=ylabel
    ))

    fig.update_layout(
        title=title,
        xaxis_title='Simulation Time (s)',
        yaxis_title=ylabel,
        template='plotly_dark',
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor='#1f2937',
        paper_bgcolor='#111827',
        font=dict(color='#f9fafb')
    )

    return fig


def create_service_aggregated_percentile_chart_filtered(metrics_df: pd.DataFrame, service_id: str,
                                                        metric_name: str, title: str,
                                                        filter_col: str, filter_val: str,
                                                        pod_ids: list = None) -> go.Figure:
    """
    Create aggregated percentile chart for service with additional filter.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        filter_col: Column name to filter on (e.g., 'dependency_id')
        filter_val: Value to filter for
        pod_ids: List of pod IDs to aggregate (if None, will filter by service.id tag)
    """
    # Aggregate Pod percentile metrics by pod IDs (preferred) or service.id tag (fallback) with additional filter
    if pod_ids:
        data = metrics_df[
            (metrics_df['component_id'].isin(pod_ids)) &
            (metrics_df['metric_name'] == metric_name) &
            (metrics_df[filter_col] == filter_val)
        ].copy()
    else:
        # Fallback to service.id filtering
        data = metrics_df[
            (metrics_df.get('service.id', pd.Series(dtype='object')) == service_id) &
            (metrics_df['metric_name'] == metric_name) &
            (metrics_df[filter_col] == filter_val)
        ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Group by sim_time and aggregate percentiles (mean across all pods)
    aggregated = data.groupby('sim_time', as_index=False).agg({
        'p50': 'mean',
        'p90': 'mean',
        'p99': 'mean'
    })

    fig = go.Figure()

    # P99
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p99'],
        mode='lines',
        name='P99',
        line=dict(color='#ef4444', width=1.5)
    ))

    # P90
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p90'],
        mode='lines',
        name='P90',
        line=dict(color='#f59e0b', width=1.5)
    ))

    # P50 (median)
    fig.add_trace(go.Scatter(
        x=aggregated['sim_time'],
        y=aggregated['p50'],
        mode='lines',
        name='P50 (Median)',
        line=dict(color='#3b82f6', width=2)
    ))

    fig.update_layout(
        title=title,
        xaxis_title='Simulation Time (s)',
        yaxis_title='Latency (ms)',
        template='plotly_dark',
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor='#1f2937',
        paper_bgcolor='#111827',
        font=dict(color='#f9fafb')
    )

    return fig


def create_pod_breakdown_chart(metrics_df: pd.DataFrame, pod_ids: List[str],
                               metric_name: str, title: str, ylabel: str) -> go.Figure:
    """Create a chart showing a metric for multiple pods (one line per pod).

    This is useful for identifying outlier/hot pods by comparing their metrics side-by-side.

    Args:
        metrics_df: DataFrame with all metrics
        pod_ids: List of pod IDs to include in the chart
        metric_name: Metric name to display
        title: Chart title
        ylabel: Y-axis label
    """
    fig = go.Figure()

    # Define colors for pods (cycle through if more pods than colors)
    colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6',
              '#1abc9c', '#e67e22', '#34495e', '#16a085', '#c0392b']

    for idx, pod_id in enumerate(pod_ids):
        pod_data = metrics_df[
            (metrics_df['component_id'] == pod_id) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

        if not pod_data.empty and 'value' in pod_data.columns:
            color = colors[idx % len(colors)]
            fig.add_trace(go.Scatter(
                x=pod_data['sim_time'],
                y=pod_data['value'],
                mode='lines',
                line=dict(color=color, width=2),
                name=pod_id
            ))

    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title=ylabel,
        height=300,
        margin=dict(l=50, r=20, t=40, b=30),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
    )

    return fig


def create_pod_breakdown_percentile_chart(metrics_df: pd.DataFrame, pod_ids: List[str],
                                          metric_name: str, title: str, percentile: str = 'p50') -> go.Figure:
    """Create a chart showing a specific percentile for multiple pods (one line per pod).

    Args:
        metrics_df: DataFrame with all metrics
        pod_ids: List of pod IDs to include in the chart
        metric_name: Metric name to display (should be a histogram metric with percentiles)
        title: Chart title
        percentile: Which percentile to show (p50, p90, or p99)
    """
    fig = go.Figure()

    # Define colors for pods (cycle through if more pods than colors)
    colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6',
              '#1abc9c', '#e67e22', '#34495e', '#16a085', '#c0392b']

    for idx, pod_id in enumerate(pod_ids):
        pod_data = metrics_df[
            (metrics_df['component_id'] == pod_id) &
            (metrics_df['metric_name'] == metric_name)
        ].copy()

        if not pod_data.empty and percentile in pod_data.columns and not pod_data[percentile].isna().all():
            color = colors[idx % len(colors)]
            fig.add_trace(go.Scatter(
                x=pod_data['sim_time'],
                y=pod_data[percentile],
                mode='lines',
                line=dict(color=color, width=2),
                name=pod_id
            ))

    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title="Latency (ms)",
        height=300,
        margin=dict(l=50, r=20, t=40, b=30),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb')
    )

    return fig


def create_pod_drilldown(metrics_df: pd.DataFrame, component_id: str,
                        label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for individual Pod."""
    charts = []

    # Get all metrics for this pod
    pod_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(pod_metrics['metric_name'].unique())

    # Get service name from pod metrics (needed for request-level metrics)
    service_name_values = pod_metrics['service.name'].dropna().unique()
    service_name = service_name_values[0] if len(service_name_values) > 0 else None

    # Request-level metrics (from service.{name}.* namespace)
    if service_name:
        request_metric = f'service.{service_name}.requests'
        duration_metric = f'service.{service_name}.duration'
        error_metric = f'service.{service_name}.errors'

        # Request rate
        if request_metric in available_metrics:
            charts.append(dcc.Graph(
                figure=create_metric_chart(
                    metrics_df, component_id,
                    request_metric,
                    'Request Rate',
                    'Requests'
                ),
                config={'displayModeBar': False}
            ))

        # Request duration/latency
        if duration_metric in available_metrics:
            duration_data = pod_metrics[pod_metrics['metric_name'] == duration_metric]
            if 'p50' in duration_data.columns and not duration_data['p50'].isna().all():
                charts.append(dcc.Graph(
                    figure=create_percentile_chart(
                        metrics_df, component_id,
                        duration_metric,
                        'Request Duration (Latency)'
                    ),
                    config={'displayModeBar': False}
                ))
            else:
                charts.append(dcc.Graph(
                    figure=create_metric_chart(
                        metrics_df, component_id,
                        duration_metric,
                        'Request Duration',
                        'ms'
                    ),
                    config={'displayModeBar': False}
                ))

        # Error rate
        if error_metric in available_metrics:
            charts.append(dcc.Graph(
                figure=create_metric_chart(
                    metrics_df, component_id,
                    error_metric,
                    'Error Rate',
                    'Errors'
                ),
                config={'displayModeBar': False}
            ))

    # CPU utilization
    if 'container.cpu.utilization' in available_metrics:
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
    if 'container.memory.usage_mb' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'container.memory.usage_mb',
                'Memory Usage',
                'MB'
            ),
            config={'displayModeBar': False}
        ))

    # Connection pool
    if 'connection_pool.connections.active' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'connection_pool.connections.active',
                'Active Connections',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Connection pool queue depth
    if 'connection_pool.queue_depth' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'connection_pool.queue_depth',
                'Connection Pool Queue Depth',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Thread pool
    if 'thread_pool.threads.active' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'thread_pool.threads.active',
                'Active Threads',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Thread pool queue depth
    if 'thread_pool.queue.depth' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'thread_pool.queue.depth',
                'Thread Pool Queue Depth',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # External dependency metrics (at the bottom, grouped in accordion)
    if service_name:
        dependency_request_metric = f'service.{service_name}.dependency.requests'
        dependency_duration_metric = f'service.{service_name}.dependency.duration'
        dependency_error_metric = f'service.{service_name}.dependency.errors'

        has_dependency_metrics = (dependency_request_metric in available_metrics or
                                  dependency_duration_metric in available_metrics or
                                  dependency_error_metric in available_metrics)

        if has_dependency_metrics:
            # Get dependency metrics for this pod
            dep_metrics = pod_metrics[
                pod_metrics['metric_name'].str.contains('dependency', na=False)
            ]

            external_deps = []
            if 'dependency_id' in dep_metrics.columns:
                external_deps = dep_metrics['dependency_id'].dropna().unique().tolist()

            if external_deps:
                # Add section header
                charts.append(html.Hr(style={'marginTop': '40px', 'marginBottom': '20px', 'borderColor': '#555'}))
                charts.append(html.H4("Dependencies (Outgoing Calls)", style={'marginBottom': '15px'}))

                # Create accordion items for each dependency
                accordion_items = []
                for dep_id in sorted(external_deps):
                    dep_specific = dep_metrics[dep_metrics['dependency_id'] == dep_id]
                    dep_name = dep_specific['dependency_name'].iloc[0] if 'dependency_name' in dep_specific.columns and not dep_specific.empty else dep_id

                    # Create charts for this dependency
                    dep_charts = []

                    if dependency_request_metric in available_metrics:
                        dep_charts.append(dcc.Graph(
                            figure=create_metric_chart_filtered(
                                metrics_df, component_id,
                                dependency_request_metric,
                                f'Request Rate',
                                'Requests',
                                filter_col='dependency_id',
                                filter_val=dep_id
                            ),
                            config={'displayModeBar': False}
                        ))

                    if dependency_duration_metric in available_metrics:
                        dep_duration_data = dep_specific[dep_specific['metric_name'] == dependency_duration_metric]
                        if 'p50' in dep_duration_data.columns and not dep_duration_data['p50'].isna().all():
                            dep_charts.append(dcc.Graph(
                                figure=create_percentile_chart_filtered(
                                    metrics_df, component_id,
                                    dependency_duration_metric,
                                    f'Latency',
                                    filter_col='dependency_id',
                                    filter_val=dep_id
                                ),
                                config={'displayModeBar': False}
                            ))
                        else:
                            dep_charts.append(dcc.Graph(
                                figure=create_metric_chart_filtered(
                                    metrics_df, component_id,
                                    dependency_duration_metric,
                                    f'Latency',
                                    'ms',
                                    filter_col='dependency_id',
                                    filter_val=dep_id
                                ),
                                config={'displayModeBar': False}
                            ))

                    if dependency_error_metric in available_metrics:
                        dep_charts.append(dcc.Graph(
                            figure=create_metric_chart_filtered(
                                metrics_df, component_id,
                                dependency_error_metric,
                                f'Errors',
                                'Errors',
                                filter_col='dependency_id',
                                filter_val=dep_id
                            ),
                            config={'displayModeBar': False}
                        ))

                    # Create accordion item
                    accordion_items.append(
                        dbc.AccordionItem(
                            dep_charts,
                            title=f"→ {dep_name}",
                        )
                    )

                # Add accordion to charts
                charts.append(dbc.Accordion(
                    accordion_items,
                    start_collapsed=True,  # All collapsed by default
                    always_open=False,  # Only one open at a time
                ))

    # If no charts, show message
    if not charts:
        charts.append(html.Div([
            html.P(f"No metrics available for Pod {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics) if available_metrics else 'None'}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    return charts


def create_service_drilldown(metrics_df: pd.DataFrame, component_id: str,
                             label_data: Dict, graph: nx.DiGraph = None,
                             topology_events: Optional[Dict] = None) -> List[dcc.Graph]:
    """Create drill-down charts for Service by aggregating Pod metrics."""
    charts = []

    # Get all metrics for this component to see what's available
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # Get Pod IDs for this service from the topology graph
    # This is more reliable than filtering by service.id because not all metrics have service.id labels
    # (e.g., container.cpu.utilization, container.memory.usage_mb only have service.name)
    pod_ids = []
    if graph:
        for node_id in graph.nodes():
            node_attrs = graph.nodes[node_id]
            if node_attrs.get('type') == 'Pod' and node_attrs.get('parent_service') == component_id:
                pod_ids.append(node_id)

    # Get Pod metrics for this service using pod_ids from topology
    if pod_ids:
        pod_metrics = metrics_df[metrics_df['component_id'].isin(pod_ids)]
    else:
        # Fallback: Try filtering by service.id tag (for backward compatibility)
        # Note: service.id contains the component ID (e.g., "svc_1")
        # while service.name contains the semantic name (e.g., "PaymentProcessor")
        pod_metrics = metrics_df[
            (metrics_df.get('service.id', pd.Series(dtype='object')) == component_id) &
            (metrics_df['component_id'].str.startswith('pod_', na=False))
        ]

    pod_metrics_available = set(pod_metrics['metric_name'].unique()) if not pod_metrics.empty else set()

    # Add pod lifecycle timeline first (before other metrics)
    pod_timeline = create_pod_lifecycle_timeline(component_id, topology_events, label_data)
    if pod_timeline:
        charts.append(pod_timeline)

    # Request rate (aggregate from Pod metrics)
    request_metric = f'service.{component_id}.requests'
    if request_metric in pod_metrics_available:
        charts.append(dcc.Graph(
            figure=create_service_aggregated_chart(
                metrics_df, component_id,
                request_metric,
                'Request Rate',
                'Requests/s',
                pod_ids=pod_ids
            ),
            config={'displayModeBar': False}
        ))

    # Request duration (aggregate from Pod metrics)
    duration_metric = f'service.{component_id}.duration'
    if duration_metric in pod_metrics_available:
        # Check if it has percentile data
        duration_data = pod_metrics[pod_metrics['metric_name'] == duration_metric]
        if 'p50' in duration_data.columns and not duration_data['p50'].isna().all():
            # Create aggregated percentile chart for service
            charts.append(dcc.Graph(
                figure=create_service_aggregated_percentile_chart(
                    metrics_df, component_id,
                    duration_metric,
                    'Request Duration (Latency)',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))
        else:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    duration_metric,
                    'Request Duration',
                    'ms',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

    # Error rate (aggregate from Pod metrics)
    error_metric = f'service.{component_id}.errors'
    if error_metric in pod_metrics_available:
        charts.append(dcc.Graph(
            figure=create_service_aggregated_chart(
                metrics_df, component_id,
                error_metric,
                'Error Rate',
                'Errors',
                pod_ids=pod_ids
            ),
            config={'displayModeBar': False}
        ))

    # Total errors (if available at service level)
    if 'component.errors.total' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'component.errors.total',
                'Total Errors',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Now check Pod metrics for infrastructure details
    if pod_metrics_available:
        # CPU utilization
        if 'container.cpu.utilization' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'container.cpu.utilization',
                    'CPU Utilization (Pods)',
                    'Percentage (%)',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

        # Memory usage
        if 'container.memory.usage_mb' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'container.memory.usage_mb',
                    'Memory Usage (Pods)',
                    'MB',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

        # Connection pool
        if 'connection_pool.connections.active' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'connection_pool.connections.active',
                    'Active Connections (Pods)',
                    'Count',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

        # Connection pool queue depth
        if 'connection_pool.queue_depth' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'connection_pool.queue_depth',
                    'Connection Pool Queue Depth (Pods)',
                    'Count',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

        # Thread pool
        if 'thread_pool.threads.active' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'thread_pool.threads.active',
                    'Active Threads (Pods)',
                    'Count',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

        # Queue depth
        if 'thread_pool.queue.depth' in pod_metrics_available:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    'thread_pool.queue.depth',
                    'Thread Pool Queue Depth (Pods)',
                    'Count',
                    pod_ids=pod_ids
                ),
                config={'displayModeBar': False}
            ))

    # If no charts were created, show a message
    if not charts:
        all_metrics = available_metrics | pod_metrics_available
        charts.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Service metrics: {', '.join(available_metrics) if available_metrics else 'None'}",
                   style={'fontSize': '0.8em', 'color': '#666'}),
            html.P(f"Pod metrics: {', '.join(list(pod_metrics_available)[:5]) if pod_metrics_available else 'None'}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    # Pod Breakdown section - allows drilling down into per-pod metrics for any service-level metric
    if pod_ids and len(pod_ids) > 1 and pod_metrics_available:
        # Add section header
        charts.append(html.Hr(style={'marginTop': '40px', 'marginBottom': '20px', 'borderColor': '#555'}))
        charts.append(html.H4("Pod Breakdown", style={'marginBottom': '15px'}))

        # Create a map of metric names to their display info
        # These are metrics that are aggregated from pods to service level
        metric_breakdown_map = {
            f'service.{component_id}.requests': {
                'title': 'Request Rate',
                'ylabel': 'Requests/s',
                'type': 'counter'
            },
            f'service.{component_id}.duration': {
                'title': 'Request Duration (Latency)',
                'ylabel': 'ms',
                'type': 'histogram'
            },
            f'service.{component_id}.errors': {
                'title': 'Error Rate',
                'ylabel': 'Errors',
                'type': 'counter'
            },
            'container.cpu.utilization': {
                'title': 'CPU Utilization',
                'ylabel': 'Percentage (%)',
                'type': 'gauge'
            },
            'container.memory.usage_mb': {
                'title': 'Memory Usage',
                'ylabel': 'MB',
                'type': 'gauge'
            },
            'connection_pool.connections.active': {
                'title': 'Active Connections',
                'ylabel': 'Count',
                'type': 'gauge'
            },
            'connection_pool.queue_depth': {
                'title': 'Connection Pool Queue Depth',
                'ylabel': 'Count',
                'type': 'gauge'
            },
            'thread_pool.threads.active': {
                'title': 'Active Threads',
                'ylabel': 'Count',
                'type': 'gauge'
            },
            'thread_pool.queue.depth': {
                'title': 'Thread Pool Queue Depth',
                'ylabel': 'Count',
                'type': 'gauge'
            }
        }

        # Create accordion items for each available metric
        pod_breakdown_accordion_items = []

        for metric_name, metric_info in metric_breakdown_map.items():
            if metric_name not in pod_metrics_available:
                continue

            metric_charts = []

            if metric_info['type'] == 'histogram':
                # Check if it has percentile data
                metric_data = pod_metrics[pod_metrics['metric_name'] == metric_name]
                if 'p50' in metric_data.columns and not metric_data['p50'].isna().all():
                    # Show each percentile in a separate chart
                    for percentile in ['p50', 'p90', 'p99']:
                        if percentile in metric_data.columns and not metric_data[percentile].isna().all():
                            metric_charts.append(dcc.Graph(
                                figure=create_pod_breakdown_percentile_chart(
                                    metrics_df,
                                    pod_ids,
                                    metric_name,
                                    f'{metric_info["title"]} ({percentile.upper()}) per Pod',
                                    percentile=percentile
                                ),
                                config={'displayModeBar': False}
                            ))
                else:
                    # Show average value per pod
                    metric_charts.append(dcc.Graph(
                        figure=create_pod_breakdown_chart(
                            metrics_df,
                            pod_ids,
                            metric_name,
                            f'{metric_info["title"]} per Pod',
                            metric_info['ylabel']
                        ),
                        config={'displayModeBar': False}
                    ))
            else:
                # Counter or gauge - show value per pod
                metric_charts.append(dcc.Graph(
                    figure=create_pod_breakdown_chart(
                        metrics_df,
                        pod_ids,
                        metric_name,
                        f'{metric_info["title"]} per Pod',
                        metric_info['ylabel']
                    ),
                    config={'displayModeBar': False}
                ))

            # Add accordion item for this metric
            if metric_charts:
                pod_breakdown_accordion_items.append(
                    dbc.AccordionItem(
                        metric_charts,
                        title=f"{metric_info['title']}",
                    )
                )

        # Add accordion for pod breakdown with all metric items
        if pod_breakdown_accordion_items:
            charts.append(dbc.Accordion(
                pod_breakdown_accordion_items,
                start_collapsed=True,
                always_open=False,
            ))

    # External dependency metrics (at the bottom, grouped in accordion)
    # Aggregate from Pod metrics using service.name tag
    dependency_request_metric = f'service.{component_id}.dependency.requests'
    dependency_duration_metric = f'service.{component_id}.dependency.duration'
    dependency_error_metric = f'service.{component_id}.dependency.errors'

    has_dependency_metrics = (dependency_request_metric in pod_metrics_available or
                              dependency_duration_metric in pod_metrics_available or
                              dependency_error_metric in pod_metrics_available)

    if has_dependency_metrics:
        # Get dependency metrics from Pods (not Service)
        dep_metrics = pod_metrics[
            pod_metrics['metric_name'].str.contains('dependency', na=False)
        ]

        external_deps = []
        if 'dependency_id' in dep_metrics.columns:
            external_deps = dep_metrics['dependency_id'].dropna().unique().tolist()

        if external_deps:
            # Add section header
            charts.append(html.Hr(style={'marginTop': '40px', 'marginBottom': '20px', 'borderColor': '#555'}))
            charts.append(html.H4("Dependencies (Outgoing Calls)", style={'marginBottom': '15px'}))

            # Create accordion items for each dependency
            accordion_items = []
            for idx, dep_id in enumerate(sorted(external_deps)):
                dep_specific = dep_metrics[dep_metrics['dependency_id'] == dep_id]
                dep_name = dep_specific['dependency_name'].iloc[0] if 'dependency_name' in dep_specific.columns and not dep_specific.empty else dep_id

                # Create charts for this dependency (aggregated across all Pods)
                dep_charts = []

                if dependency_request_metric in pod_metrics_available:
                    dep_charts.append(dcc.Graph(
                        figure=create_service_aggregated_chart_filtered(
                            metrics_df, component_id,
                            dependency_request_metric,
                            f'Request Rate',
                            'Requests/s',
                            filter_col='dependency_id',
                            filter_val=dep_id,
                            pod_ids=pod_ids
                        ),
                        config={'displayModeBar': False}
                    ))

                if dependency_duration_metric in pod_metrics_available:
                    dep_duration_data = dep_specific[dep_specific['metric_name'] == dependency_duration_metric]
                    if 'p50' in dep_duration_data.columns and not dep_duration_data['p50'].isna().all():
                        dep_charts.append(dcc.Graph(
                            figure=create_service_aggregated_percentile_chart_filtered(
                                metrics_df, component_id,
                                dependency_duration_metric,
                                f'Latency',
                                filter_col='dependency_id',
                                filter_val=dep_id,
                                pod_ids=pod_ids
                            ),
                            config={'displayModeBar': False}
                        ))
                    else:
                        dep_charts.append(dcc.Graph(
                            figure=create_service_aggregated_chart_filtered(
                                metrics_df, component_id,
                                dependency_duration_metric,
                                f'Latency',
                                'ms',
                                filter_col='dependency_id',
                                filter_val=dep_id,
                                pod_ids=pod_ids
                            ),
                            config={'displayModeBar': False}
                        ))

                if dependency_error_metric in pod_metrics_available:
                    dep_charts.append(dcc.Graph(
                        figure=create_service_aggregated_chart_filtered(
                            metrics_df, component_id,
                            dependency_error_metric,
                            f'Errors',
                            'Errors',
                            filter_col='dependency_id',
                            filter_val=dep_id,
                            pod_ids=pod_ids
                        ),
                        config={'displayModeBar': False}
                    ))

                # Create accordion item
                accordion_items.append(
                    dbc.AccordionItem(
                        dep_charts,
                        title=f"→ {dep_name}",
                    )
                )

            # Add accordion to charts
            charts.append(dbc.Accordion(
                accordion_items,
                start_collapsed=True,  # All collapsed by default
                always_open=False,  # Only one open at a time
            ))

    return charts


def create_database_drilldown(metrics_df: pd.DataFrame, component_id: str,
                              label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for SqlDatabase."""
    charts = []

    # === SECTION 1: Internal Database Metrics ===
    charts.append(html.Div([
        html.H5("Database Internal Metrics", style={'marginTop': '10px', 'marginBottom': '15px', 'color': '#f9fafb'}),
    ]))

    # Get all metrics for this component
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # CPU utilization
    if 'db.cpu.utilization' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'db.cpu.utilization',
                'CPU Utilization',
                'Percentage (%)'
            ),
            config={'displayModeBar': False}
        ))

    # Active connections
    if 'db.connections.active' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'db.connections.active',
                'Active Connections',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Connection rejections (counter)
    if 'db.connections.rejected' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'db.connections.rejected',
                'Connection Rejections',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Query latency (percentiles)
    if 'db.query.latency' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_percentile_chart(
                metrics_df, component_id,
                'db.query.latency',
                'Query Latency'
            ),
            config={'displayModeBar': False}
        ))

    # Query errors (counter)
    if 'db.query.errors' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'db.query.errors',
                'Query Errors',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # === SECTION 2: Per-Caller Breakdown ===
    # Find all metrics where this database is the dependency target
    dependency_metrics = metrics_df[
        (metrics_df['dependency_id'] == component_id) |
        (metrics_df['dependency_name'].str.contains(component_id, na=False))
    ].copy()

    if not dependency_metrics.empty:
        # Get unique callers
        callers = sorted(dependency_metrics['service.name'].dropna().unique()) if 'service.name' in dependency_metrics.columns else []

        if len(callers) > 0:
            charts.append(html.Hr(style={'marginTop': '25px', 'marginBottom': '15px', 'borderColor': '#4b5563'}))
            charts.append(html.Div([
                html.H5("Caller Breakdown", style={'marginBottom': '10px', 'color': '#f9fafb'}),
                html.P([
                    html.Strong("Callers: "),
                    html.Span(f"{len(callers)} service(s)", style={'color': '#3b82f6'})
                ], style={'marginBottom': '10px', 'fontSize': '0.9em'}),
                html.P(
                    "Metrics from services calling this database (request rate, latency, errors).",
                    style={'fontSize': '0.85em', 'color': '#9ca3af', 'marginBottom': '15px'}
                )
            ]))

            # Create tabs - one for all callers, and one for each individual caller
            tabs = []

            # Tab 1: All Callers (aggregated)
            all_callers_charts = _create_external_charts_for_caller(
                dependency_metrics, component_id, None, callers
            )
            tabs.append(dbc.Tab(
                label="All Callers",
                tab_id=f"db-all-callers-{component_id}",
                children=all_callers_charts
            ))

            # Individual caller tabs
            for caller in callers:
                caller_data = dependency_metrics[dependency_metrics['service.name'] == caller]
                caller_charts = _create_external_charts_for_caller(
                    caller_data, component_id, caller, None
                )
                tabs.append(dbc.Tab(
                    label=caller,
                    tab_id=f"db-caller-{component_id}-{caller}",
                    children=caller_charts
                ))

            charts.append(dbc.Tabs(
                tabs,
                id=f"database-tabs-{component_id}",
                active_tab=f"db-all-callers-{component_id}",
                className="mb-3"
            ))

    # If no internal metrics were found, show a message
    if len([c for c in charts if isinstance(c, dcc.Graph)]) == 0 and dependency_metrics.empty:
        return [html.Div([
            html.P(f"No metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ])]

    return charts


def create_cache_drilldown(metrics_df: pd.DataFrame, component_id: str,
                          label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for cache components (InMemoryCache, ExternalCache)."""
    charts = []

    # === SECTION 1: Internal Cache Metrics ===
    charts.append(html.Div([
        html.H5("Cache Internal Metrics", style={'marginTop': '10px', 'marginBottom': '15px', 'color': '#f9fafb'}),
    ]))

    # Get all metrics for this component
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # Hit rate (gauge)
    if 'cache.hit_rate' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'cache.hit_rate',
                'Cache Hit Rate',
                'Rate'
            ),
            config={'displayModeBar': False}
        ))

    # Total hits (counter)
    if 'cache.hits.total' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'cache.hits.total',
                'Cache Hits',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Total misses (counter) - renamed from cache.miss_rate to cache.misses.total
    if 'cache.misses.total' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'cache.misses.total',
                'Cache Misses',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Eviction count (counter) - only show if data exists
    if 'cache.evictions' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'cache.evictions',
                'Cache Evictions',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # === SECTION 2: Per-Caller Breakdown ===
    # Find all metrics where this cache is the dependency target
    dependency_metrics = metrics_df[
        (metrics_df['dependency_id'] == component_id) |
        (metrics_df['dependency_name'].str.contains(component_id, na=False))
    ].copy()

    if not dependency_metrics.empty:
        # Get unique callers
        callers = sorted(dependency_metrics['service.name'].dropna().unique()) if 'service.name' in dependency_metrics.columns else []

        if len(callers) > 0:
            charts.append(html.Hr(style={'marginTop': '25px', 'marginBottom': '15px', 'borderColor': '#4b5563'}))
            charts.append(html.Div([
                html.H5("Caller Breakdown", style={'marginBottom': '10px', 'color': '#f9fafb'}),
                html.P([
                    html.Strong("Callers: "),
                    html.Span(f"{len(callers)} service(s)", style={'color': '#3b82f6'})
                ], style={'marginBottom': '10px', 'fontSize': '0.9em'}),
                html.P(
                    "Metrics from services calling this cache (request rate, latency, errors).",
                    style={'fontSize': '0.85em', 'color': '#9ca3af', 'marginBottom': '15px'}
                )
            ]))

            # Create tabs - one for all callers, and one for each individual caller
            tabs = []

            # Tab 1: All Callers (aggregated)
            all_callers_charts = _create_external_charts_for_caller(
                dependency_metrics, component_id, None, callers
            )
            tabs.append(dbc.Tab(
                label="All Callers",
                tab_id=f"cache-all-callers-{component_id}",
                children=all_callers_charts
            ))

            # Individual caller tabs
            for caller in callers:
                caller_data = dependency_metrics[dependency_metrics['service.name'] == caller]
                caller_charts = _create_external_charts_for_caller(
                    caller_data, component_id, caller, None
                )
                tabs.append(dbc.Tab(
                    label=caller,
                    tab_id=f"cache-caller-{component_id}-{caller}",
                    children=caller_charts
                ))

            charts.append(dbc.Tabs(
                tabs,
                id=f"cache-tabs-{component_id}",
                active_tab=f"cache-all-callers-{component_id}",
                className="mb-3"
            ))

    # If no internal metrics were found, show a message
    if len([c for c in charts if isinstance(c, dcc.Graph)]) == 0 and dependency_metrics.empty:
        return [html.Div([
            html.P(f"No metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ])]

    return charts


def _create_queue_charts_for_producer_consumer(
    dependency_metrics: pd.DataFrame,
    component_id: str,
    service_filter: str = None,
    all_services: List[str] = None,
    mode: str = "producer"
) -> List:
    """Helper function to create charts for queue producers or consumers.

    Args:
        dependency_metrics: Pre-filtered metrics for this queue
        component_id: Queue ID
        service_filter: If provided, only show metrics from this service
        all_services: List of all services (used for "All" tab header)
        mode: Either "producer" (for publish operations) or "consumer" (for processing operations)
    """
    charts = []

    # Customize terminology based on mode
    if mode == "producer":
        operation_verb = "publishing to"
        operation_noun = "Publish"
        rate_label = "Messages Published"
        direction = "to"
    else:  # consumer
        operation_verb = "consuming from"
        operation_noun = "Processing"
        rate_label = "Messages Processed"
        direction = "from"

    # Add header if showing all services
    if service_filter is None and all_services:
        charts.append(html.Div([
            html.P([
                html.Strong("Showing: "),
                html.Span(f"Aggregated metrics from {len(all_services)} service(s) {operation_verb} this queue: {', '.join(all_services)}",
                         style={'color': '#10b981'})
            ], style={'marginBottom': '15px', 'fontSize': '0.9em', 'padding': '10px',
                     'backgroundColor': '#1f2937', 'borderRadius': '5px'})
        ]))
    elif service_filter:
        charts.append(html.Div([
            html.P([
                html.Strong("Showing: "),
                html.Span(f"Metrics from {service_filter} only", style={'color': '#10b981'})
            ], style={'marginBottom': '15px', 'fontSize': '0.9em', 'padding': '10px',
                     'backgroundColor': '#1f2937', 'borderRadius': '5px'})
        ]))

    # Request rate chart (aggregate by status)
    request_metrics = dependency_metrics[
        dependency_metrics['metric_name'].str.contains('dependency.requests', na=False)
    ].copy()

    title_suffix = f" ({service_filter})" if service_filter else " (all services)"

    if not request_metrics.empty:
        fig = go.Figure()

        # Group by sim_time and status to show success vs error rates
        if 'status' in request_metrics.columns:
            for status in ['success', 'error']:
                status_data = request_metrics[request_metrics['status'] == status]
                if not status_data.empty:
                    aggregated = status_data.groupby('sim_time')['value'].sum().reset_index()
                    fig.add_trace(go.Scatter(
                        x=aggregated['sim_time'],
                        y=aggregated['value'],
                        mode='lines+markers',
                        name=f'{status.capitalize()}',
                        line=dict(width=2),
                        marker=dict(size=4)
                    ))
        else:
            # No status breakdown, just show total
            aggregated = request_metrics.groupby('sim_time')['value'].sum().reset_index()
            fig.add_trace(go.Scatter(
                x=aggregated['sim_time'],
                y=aggregated['value'],
                mode='lines+markers',
                name='Total',
                line=dict(width=2),
                marker=dict(size=4)
            ))

        fig.update_layout(
            title=f'{rate_label} {direction} {component_id}{title_suffix}',
            xaxis_title="Time (s)",
            yaxis_title="Messages/sec",
            height=250,
            margin=dict(l=50, r=20, t=40, b=30),
            showlegend=True,
            plot_bgcolor='#374151',
            paper_bgcolor='#374151',
            font=dict(color='#f9fafb')
        )

        charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Latency chart
    latency_metrics = dependency_metrics[
        dependency_metrics['metric_name'].str.contains('dependency.duration', na=False)
    ].copy()

    if not latency_metrics.empty and 'p50' in latency_metrics.columns:
        fig = go.Figure()

        # Show P50, P90, P99
        for percentile in ['p50', 'p90', 'p99']:
            if percentile in latency_metrics.columns:
                aggregated = latency_metrics.groupby('sim_time')[percentile].mean().reset_index()
                fig.add_trace(go.Scatter(
                    x=aggregated['sim_time'],
                    y=aggregated[percentile],  # Already in ms
                    mode='lines',
                    name=f'P{percentile[1:]}',
                    line=dict(width=2)
                ))

        fig.update_layout(
            title=f'{operation_noun} Latency {direction} {component_id}{title_suffix}',
            xaxis_title="Time (s)",
            yaxis_title="Latency (ms)",
            height=250,
            margin=dict(l=50, r=20, t=40, b=30),
            showlegend=True,
            plot_bgcolor='#374151',
            paper_bgcolor='#374151',
            font=dict(color='#f9fafb')
        )

        charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Error rate chart (if we have error metrics or can derive from status)
    if 'status' in request_metrics.columns:
        # Calculate error rate over time
        error_data = request_metrics[request_metrics['status'] == 'error'].groupby('sim_time')['value'].sum()
        total_data = request_metrics.groupby('sim_time')['value'].sum()

        if not error_data.empty and not total_data.empty:
            error_rate = (error_data / total_data * 100).fillna(0)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=error_rate.index,
                y=error_rate.values,
                mode='lines+markers',
                name='Error Rate',
                line=dict(color='#ef4444', width=2),
                marker=dict(size=4),
                fill='tozeroy',
                fillcolor='rgba(239, 68, 68, 0.2)'
            ))

            fig.update_layout(
                title=f'{operation_noun} Error Rate {direction} {component_id}{title_suffix}',
                xaxis_title="Time (s)",
                yaxis_title="Error Rate (%)",
                height=250,
                margin=dict(l=50, r=20, t=40, b=30),
                showlegend=False,
                plot_bgcolor='#374151',
                paper_bgcolor='#374151',
                font=dict(color='#f9fafb')
            )

            charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    return charts


def create_queue_drilldown(metrics_df: pd.DataFrame, component_id: str,
                          label_data: Dict, graph: nx.DiGraph = None) -> List[dcc.Graph]:
    """Create drill-down charts for MessageQueue."""
    charts = []

    # === SECTION 1: Internal Queue Metrics ===
    charts.append(html.Div([
        html.H5("Queue Internal Metrics", style={'marginTop': '10px', 'marginBottom': '15px', 'color': '#f9fafb'}),
    ]))

    # Get all metrics for this component to check availability
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

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

    # Message processing outcomes (success vs timeout failures)
    if 'mq.messages.deleted' in available_metrics or 'mq.messages.timeout_failures' in available_metrics:
        fig = go.Figure()

        # Successfully processed messages (cumulative)
        if 'mq.messages.deleted' in available_metrics:
            deleted_data = metrics_df[
                (metrics_df['component_id'] == component_id) &
                (metrics_df['metric_name'] == 'mq.messages.deleted')
            ].copy()

            if not deleted_data.empty and 'sim_time' in deleted_data.columns:
                deleted_data = deleted_data.sort_values('sim_time')
                fig.add_trace(go.Scatter(
                    x=deleted_data['sim_time'],
                    y=deleted_data['value'].cumsum(),
                    mode='lines+markers',
                    name='Successfully Processed',
                    line=dict(color='#10b981', width=2),  # Green
                    marker=dict(size=4)
                ))

        # Timeout failures (cumulative)
        if 'mq.messages.timeout_failures' in available_metrics:
            timeout_data = metrics_df[
                (metrics_df['component_id'] == component_id) &
                (metrics_df['metric_name'] == 'mq.messages.timeout_failures')
            ].copy()

            if not timeout_data.empty and 'sim_time' in timeout_data.columns:
                timeout_data = timeout_data.sort_values('sim_time')
                fig.add_trace(go.Scatter(
                    x=timeout_data['sim_time'],
                    y=timeout_data['value'].cumsum(),
                    mode='lines+markers',
                    name='Timeout Failures (DLQ)',
                    line=dict(color='#ef4444', width=2),  # Red
                    marker=dict(size=4)
                ))

        # Apply consistent styling (same as other queue charts)
        fig.update_layout(
            title='Message Processing Outcomes',
            xaxis_title='Time (s)',
            yaxis_title='Cumulative Count',
            height=200,
            margin=dict(l=50, r=20, t=40, b=30),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor='#374151',
            paper_bgcolor='#374151',
            font=dict(color='#f9fafb')
        )

        charts.append(dcc.Graph(
            figure=fig,
            config={'displayModeBar': False}
        ))

    # === SECTION 2: Producer Breakdown ===
    if graph is not None:
        # Find all producers (services that produce to this queue)
        producers = []
        for source, target, edge_data in graph.in_edges(component_id, data=True):
            if edge_data.get('type') == 'async_produce':
                producers.append(source)

        if producers:
            # Get dependency metrics from producers to this queue
            # Note: producers list contains service IDs, match against service.id column
            # Filter by queue_operation='produce' to distinguish from consume operations
            producer_metrics = metrics_df[
                (metrics_df['dependency_id'] == component_id) &
                (metrics_df['service.id'].isin(producers)) &
                (metrics_df['queue_operation'] == 'produce')
            ].copy()

            if not producer_metrics.empty:
                # Get unique service names for display (using service.name from metrics)
                producer_names = sorted(producer_metrics['service.name'].dropna().unique())

                charts.append(html.Hr(style={'marginTop': '25px', 'marginBottom': '15px', 'borderColor': '#4b5563'}))
                charts.append(html.Div([
                    html.H5("Producer Breakdown", style={'marginBottom': '10px', 'color': '#f9fafb'}),
                    html.P([
                        html.Strong("Producers: "),
                        html.Span(f"{len(producer_names)} service(s)", style={'color': '#3b82f6'})
                    ], style={'marginBottom': '10px', 'fontSize': '0.9em'}),
                    html.P(
                        "Metrics from services producing messages to this queue (message rate, latency).",
                        style={'fontSize': '0.85em', 'color': '#9ca3af', 'marginBottom': '15px'}
                    )
                ]))

                # Create tabs - one for all producers, and one for each individual producer
                tabs = []

                # Tab 1: All Producers (aggregated)
                all_producers_charts = _create_queue_charts_for_producer_consumer(
                    producer_metrics, component_id, None, producer_names, mode="producer"
                )
                tabs.append(dbc.Tab(
                    label="All Producers",
                    tab_id=f"queue-all-producers-{component_id}",
                    children=all_producers_charts
                ))

                # Individual producer tabs
                for producer_name in producer_names:
                    producer_data = producer_metrics[producer_metrics['service.name'] == producer_name]
                    producer_charts = _create_queue_charts_for_producer_consumer(
                        producer_data, component_id, producer_name, None, mode="producer"
                    )
                    tabs.append(dbc.Tab(
                        label=producer_name,
                        tab_id=f"queue-producer-{component_id}-{producer_name}",
                        children=producer_charts
                    ))

                charts.append(dbc.Tabs(
                    tabs,
                    id=f"queue-producer-tabs-{component_id}",
                    active_tab=f"queue-all-producers-{component_id}",
                    className="mb-3"
                ))

    # === SECTION 3: Consumer Breakdown ===
    if graph is not None:
        # Find all consumers (services that consume from this queue)
        consumers = []
        for source, target, edge_data in graph.out_edges(component_id, data=True):
            if edge_data.get('type') == 'async_consume':
                consumers.append(target)

        if consumers:
            # Get dependency metrics from consumers to this queue
            # Note: consumers list contains service IDs, match against service.id column
            # Filter by queue_operation='consume' to distinguish from produce operations
            consumer_metrics = metrics_df[
                (metrics_df['dependency_id'] == component_id) &
                (metrics_df['service.id'].isin(consumers)) &
                (metrics_df['queue_operation'] == 'consume')
            ].copy()

            if not consumer_metrics.empty:
                # Get unique service names for display (using service.name from metrics)
                consumer_names = sorted(consumer_metrics['service.name'].dropna().unique())

                charts.append(html.Hr(style={'marginTop': '25px', 'marginBottom': '15px', 'borderColor': '#4b5563'}))
                charts.append(html.Div([
                    html.H5("Consumer Breakdown", style={'marginBottom': '10px', 'color': '#f9fafb'}),
                    html.P([
                        html.Strong("Consumers: "),
                        html.Span(f"{len(consumer_names)} service(s)", style={'color': '#3b82f6'})
                    ], style={'marginBottom': '10px', 'fontSize': '0.9em'}),
                    html.P(
                        "Metrics from services consuming messages from this queue (message rate, processing latency).",
                        style={'fontSize': '0.85em', 'color': '#9ca3af', 'marginBottom': '15px'}
                    )
                ]))

                # Create tabs - one for all consumers, and one for each individual consumer
                tabs = []

                # Tab 1: All Consumers (aggregated)
                all_consumers_charts = _create_queue_charts_for_producer_consumer(
                    consumer_metrics, component_id, None, consumer_names, mode="consumer"
                )
                tabs.append(dbc.Tab(
                    label="All Consumers",
                    tab_id=f"queue-all-consumers-{component_id}",
                    children=all_consumers_charts
                ))

                # Individual consumer tabs
                for consumer_name in consumer_names:
                    consumer_data = consumer_metrics[consumer_metrics['service.name'] == consumer_name]
                    consumer_charts = _create_queue_charts_for_producer_consumer(
                        consumer_data, component_id, consumer_name, None, mode="consumer"
                    )
                    tabs.append(dbc.Tab(
                        label=consumer_name,
                        tab_id=f"queue-consumer-{component_id}-{consumer_name}",
                        children=consumer_charts
                    ))

                charts.append(dbc.Tabs(
                    tabs,
                    id=f"queue-consumer-tabs-{component_id}",
                    active_tab=f"queue-all-consumers-{component_id}",
                    className="mb-3"
                ))

    return charts


def create_external_drilldown(metrics_df: pd.DataFrame, component_id: str,
                             label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for ExternalService.

    FIXED (2025-12-15): External services don't emit their own metrics.
    Instead, we aggregate metrics from all callers (services that depend on this external service).
    FIXED (2025-12-15): Added tabs to filter metrics by individual callers.
    """
    # External services don't have their own metrics - they're called by other services
    # Find all metrics where this external service is the dependency target
    # These metrics have the pattern: service.<caller>.dependency.* with label dependency_id=<external_id>

    # Filter for dependency metrics targeting this external service
    dependency_metrics = metrics_df[
        (metrics_df['dependency_id'] == component_id) |
        (metrics_df['dependency_name'].str.contains(component_id, na=False))
    ].copy()

    if dependency_metrics.empty:
        return [html.Div([
            html.P(f"No caller metrics found for {component_id}"),
            html.P("External services show metrics from their callers (services that depend on them).",
                   style={'fontSize': '0.8em', 'color': '#9ca3af'}),
            html.P(f"This external service may not have any callers, or the metrics may not be labeled correctly.",
                   style={'fontSize': '0.8em', 'color': '#9ca3af'})
        ])]

    # Get unique callers
    callers = sorted(dependency_metrics['service.name'].dropna().unique()) if 'service.name' in dependency_metrics.columns else []

    if len(callers) == 0:
        return [html.Div([
            html.P(f"No caller information found for {component_id}"),
            html.P("Metrics exist but don't have service.name labels.",
                   style={'fontSize': '0.8em', 'color': '#9ca3af'})
        ])]

    # Create tabs - one for all callers, and one for each individual caller
    tabs = []

    # Tab 1: All Callers (aggregated)
    all_callers_charts = _create_external_charts_for_caller(
        dependency_metrics, component_id, None, callers
    )
    tabs.append(dbc.Tab(
        label="All Callers",
        tab_id="all-callers",
        children=all_callers_charts
    ))

    # Individual caller tabs
    for caller in callers:
        caller_data = dependency_metrics[dependency_metrics['service.name'] == caller]
        caller_charts = _create_external_charts_for_caller(
            caller_data, component_id, caller, None
        )
        tabs.append(dbc.Tab(
            label=caller,
            tab_id=f"caller-{caller}",
            children=caller_charts
        ))

    return [
        html.Div([
            html.P([
                html.Strong("Callers: "),
                html.Span(f"{len(callers)} service(s)", style={'color': '#3b82f6'})
            ], style={'marginBottom': '10px', 'fontSize': '0.9em'}),
            html.P(
                "Use tabs below to view metrics from all callers (aggregated) or from individual callers.",
                style={'fontSize': '0.85em', 'color': '#9ca3af', 'marginBottom': '15px'}
            )
        ]),
        dbc.Tabs(
            tabs,
            id=f"external-tabs-{component_id}",
            active_tab="all-callers",
            className="mb-3"
        )
    ]


def _create_external_charts_for_caller(
    dependency_metrics: pd.DataFrame,
    component_id: str,
    caller_filter: str = None,
    all_callers: List[str] = None
) -> List:
    """Helper function to create charts for external service, optionally filtered by caller.

    Args:
        dependency_metrics: Pre-filtered metrics for this external service
        component_id: External service ID
        caller_filter: If provided, only show metrics from this caller
        all_callers: List of all callers (used for "All Callers" tab header)
    """
    charts = []

    # Add header if showing all callers
    if caller_filter is None and all_callers:
        charts.append(html.Div([
            html.P([
                html.Strong("Showing: "),
                html.Span(f"Aggregated metrics from {len(all_callers)} caller(s): {', '.join(all_callers)}",
                         style={'color': '#10b981'})
            ], style={'marginBottom': '15px', 'fontSize': '0.9em', 'padding': '10px',
                     'backgroundColor': '#1f2937', 'borderRadius': '5px'})
        ]))
    elif caller_filter:
        charts.append(html.Div([
            html.P([
                html.Strong("Showing: "),
                html.Span(f"Metrics from {caller_filter} only", style={'color': '#10b981'})
            ], style={'marginBottom': '15px', 'fontSize': '0.9em', 'padding': '10px',
                     'backgroundColor': '#1f2937', 'borderRadius': '5px'})
        ]))

    # Request rate chart (aggregate by status)
    request_metrics = dependency_metrics[
        dependency_metrics['metric_name'].str.contains('dependency.requests', na=False)
    ].copy()

    title_suffix = f" from {caller_filter}" if caller_filter else " (from all callers)"

    if not request_metrics.empty:
        fig = go.Figure()

        # Group by sim_time and status to show success vs error rates
        if 'status' in request_metrics.columns:
            for status in ['success', 'error']:
                status_data = request_metrics[request_metrics['status'] == status]
                if not status_data.empty:
                    aggregated = status_data.groupby('sim_time')['value'].sum().reset_index()
                    fig.add_trace(go.Scatter(
                        x=aggregated['sim_time'],
                        y=aggregated['value'],
                        mode='lines+markers',
                        name=f'{status.capitalize()} Requests',
                        line=dict(width=2),
                        marker=dict(size=4)
                    ))
        else:
            # No status breakdown, just show total
            aggregated = request_metrics.groupby('sim_time')['value'].sum().reset_index()
            fig.add_trace(go.Scatter(
                x=aggregated['sim_time'],
                y=aggregated['value'],
                mode='lines+markers',
                name='Total Requests',
                line=dict(width=2),
                marker=dict(size=4)
            ))

        fig.update_layout(
            title=f'Request Rate to {component_id}{title_suffix}',
            xaxis_title="Time (s)",
            yaxis_title="Requests",
            height=250,
            margin=dict(l=50, r=20, t=40, b=30),
            showlegend=True,
            plot_bgcolor='#374151',
            paper_bgcolor='#374151',
            font=dict(color='#f9fafb')
        )

        charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Latency chart
    latency_metrics = dependency_metrics[
        dependency_metrics['metric_name'].str.contains('dependency.duration', na=False)
    ].copy()

    if not latency_metrics.empty and 'p50' in latency_metrics.columns:
        fig = go.Figure()

        # Show P50, P90, P99
        for percentile in ['p50', 'p90', 'p99']:
            if percentile in latency_metrics.columns:
                aggregated = latency_metrics.groupby('sim_time')[percentile].mean().reset_index()
                fig.add_trace(go.Scatter(
                    x=aggregated['sim_time'],
                    y=aggregated[percentile],  # Already in ms
                    mode='lines',
                    name=f'P{percentile[1:]}',
                    line=dict(width=2)
                ))

        fig.update_layout(
            title=f'Request Latency to {component_id}{title_suffix}',
            xaxis_title="Time (s)",
            yaxis_title="Latency (ms)",
            height=250,
            margin=dict(l=50, r=20, t=40, b=30),
            showlegend=True,
            plot_bgcolor='#374151',
            paper_bgcolor='#374151',
            font=dict(color='#f9fafb')
        )

        charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Error rate chart (if we have error metrics or can derive from status)
    if 'status' in request_metrics.columns:
        # Calculate error rate over time
        error_data = request_metrics[request_metrics['status'] == 'error'].groupby('sim_time')['value'].sum()
        total_data = request_metrics.groupby('sim_time')['value'].sum()

        if not error_data.empty and not total_data.empty:
            error_rate = (error_data / total_data * 100).fillna(0)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=error_rate.index,
                y=error_rate.values,
                mode='lines+markers',
                name='Error Rate',
                line=dict(color='#ef4444', width=2),
                marker=dict(size=4),
                fill='tozeroy',
                fillcolor='rgba(239, 68, 68, 0.2)'
            ))

            fig.update_layout(
                title=f'Error Rate to {component_id}{title_suffix}',
                xaxis_title="Time (s)",
                yaxis_title="Error Rate (%)",
                height=250,
                margin=dict(l=50, r=20, t=40, b=30),
                showlegend=False,
                plot_bgcolor='#374151',
                paper_bgcolor='#374151',
                font=dict(color='#f9fafb')
            )

            charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    if not charts:
        charts.append(html.Div([
            html.P(f"No charts available for this view", style={'color': '#9ca3af'})
        ]))

    return charts


def create_compute_node_drilldown(metrics_df: pd.DataFrame, component_id: str,
                                 graph: nx.DiGraph, label_data: Dict) -> List:
    """Create comprehensive drill-down for ComputeNode with K8s-style debugging info."""
    components = []

    # Get node specifications from topology
    node_data = graph.nodes[component_id]
    cpu_cores = node_data.get('cpu_cores', 0)
    memory_gb = node_data.get('memory_gb', 0)
    network_bandwidth = node_data.get('network_bandwidth_gbps', 0)

    # Get node-level metrics
    node_metrics = metrics_df[metrics_df['component_id'] == component_id]
    node_available_metrics = set(node_metrics['metric_name'].unique())

    # Find all pods running on this compute node from topology
    pod_ids = []
    pod_to_service = {}  # Map pod to its service
    for node in graph.nodes():
        node_attrs = graph.nodes[node]
        if node_attrs.get('type') == 'Pod' and node_attrs.get('compute_node') == component_id:
            pod_ids.append(node)
            pod_to_service[node] = node_attrs.get('parent_service', 'unknown')

    # Get Pod metrics for pods running on this node
    pod_metrics = metrics_df[metrics_df['component_id'].isin(pod_ids)] if pod_ids else pd.DataFrame()
    pod_available_metrics = set(pod_metrics['metric_name'].unique()) if not pod_metrics.empty else set()

    # Group services on this node
    services_on_node = set(pod_to_service.values())
    service_pod_counts = {}
    for service in services_on_node:
        service_pod_counts[service] = sum(1 for s in pod_to_service.values() if s == service)

    # ===== SECTION 1: Node Specifications =====
    components.append(html.Div([
        html.H5("Node Specifications", style={'marginTop': '0px', 'marginBottom': '15px', 'color': '#3b82f6'}),
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Strong("CPU Cores: "),
                    html.Span(f"{cpu_cores}", style={'fontSize': '1.1em', 'color': '#10b981'})
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Total Memory: "),
                    html.Span(f"{memory_gb} GB", style={'fontSize': '1.1em', 'color': '#10b981'})
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Network Bandwidth: "),
                    html.Span(f"{network_bandwidth} Gbps", style={'fontSize': '1.1em', 'color': '#10b981'})
                ], style={'marginBottom': '8px'}),
            ], width=4),
            dbc.Col([
                html.Div([
                    html.Strong("Pods Running: "),
                    html.Span(f"{len(pod_ids)}", style={'fontSize': '1.1em', 'color': '#3b82f6'})
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Services: "),
                    html.Span(f"{len(services_on_node)}", style={'fontSize': '1.1em', 'color': '#3b82f6'})
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Node ID: "),
                    html.Span(component_id, style={'fontSize': '0.9em', 'color': '#9ca3af'})
                ], style={'marginBottom': '8px'}),
            ], width=4),
        ])
    ], style={
        'backgroundColor': '#1f2937',
        'padding': '20px',
        'borderRadius': '8px',
        'marginBottom': '20px',
        'border': '1px solid #374151'
    }))

    # ===== SECTION 2: Node-Level Utilization =====
    utilization_charts = []

    # CPU Utilization with capacity indicator
    if 'node.cpu.utilization' in node_available_metrics:
        cpu_data = node_metrics[node_metrics['metric_name'] == 'node.cpu.utilization'].copy()
        if not cpu_data.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cpu_data['sim_time'],
                y=cpu_data['value'],
                mode='lines',
                name='CPU Utilization',
                line=dict(color='#3b82f6', width=2),
                fill='tozeroy',
                fillcolor='rgba(59, 130, 246, 0.2)'
            ))
            # Add saturation line at 80%
            fig.add_hline(y=80, line_dash="dash", line_color="orange",
                         annotation_text="80% Saturation", annotation_position="right")
            fig.add_hline(y=100, line_dash="dash", line_color="red",
                         annotation_text="100% Capacity", annotation_position="right")

            fig.update_layout(
                title=f'Node CPU Utilization ({cpu_cores} cores)',
                xaxis_title='Time (s)',
                yaxis_title='Percentage (%)',
                height=300,
                margin=dict(l=50, r=20, t=40, b=40),
                plot_bgcolor='#1f2937',
                paper_bgcolor='#111827',
                font=dict(color='#f9fafb'),
                yaxis=dict(range=[0, 105])
            )
            utilization_charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Memory Utilization with capacity
    if 'node.memory.usage_gb' in node_available_metrics:
        mem_data = node_metrics[node_metrics['metric_name'] == 'node.memory.usage_gb'].copy()
        if not mem_data.empty:
            mem_data['percent'] = (mem_data['value'] / memory_gb) * 100 if memory_gb > 0 else 0

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=mem_data['sim_time'],
                y=mem_data['percent'],
                mode='lines',
                name='Memory Utilization',
                line=dict(color='#10b981', width=2),
                fill='tozeroy',
                fillcolor='rgba(16, 185, 129, 0.2)',
                customdata=mem_data[['value']],
                hovertemplate='<b>Time</b>: %{x}s<br><b>Usage</b>: %{customdata[0]:.2f} GB (%{y:.1f}%)<extra></extra>'
            ))
            fig.add_hline(y=80, line_dash="dash", line_color="orange",
                         annotation_text="80% Saturation", annotation_position="right")
            fig.add_hline(y=100, line_dash="dash", line_color="red",
                         annotation_text=f"100% ({memory_gb} GB)", annotation_position="right")

            fig.update_layout(
                title=f'Node Memory Utilization (Total: {memory_gb} GB)',
                xaxis_title='Time (s)',
                yaxis_title='Percentage (%)',
                height=300,
                margin=dict(l=50, r=20, t=40, b=40),
                plot_bgcolor='#1f2937',
                paper_bgcolor='#111827',
                font=dict(color='#f9fafb'),
                yaxis=dict(range=[0, 105])
            )
            utilization_charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # Pod count over time
    if 'node.pods.count' in node_available_metrics:
        pod_count_data = node_metrics[node_metrics['metric_name'] == 'node.pods.count'].copy()
        if not pod_count_data.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pod_count_data['sim_time'],
                y=pod_count_data['value'],
                mode='lines',
                name='Pod Count',
                line=dict(color='#8b5cf6', width=2),
                fill='tozeroy',
                fillcolor='rgba(139, 92, 246, 0.2)'
            ))
            fig.update_layout(
                title='Pods Running on Node',
                xaxis_title='Time (s)',
                yaxis_title='Count',
                height=300,
                margin=dict(l=50, r=20, t=40, b=40),
                plot_bgcolor='#1f2937',
                paper_bgcolor='#111827',
                font=dict(color='#f9fafb')
            )
            utilization_charts.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    if utilization_charts:
        components.append(html.H5("Node-Level Utilization", style={'marginTop': '20px', 'marginBottom': '15px', 'color': '#3b82f6'}))
        # Layout in 2-column grid
        for i in range(0, len(utilization_charts), 2):
            row_charts = utilization_charts[i:i+2]
            components.append(dbc.Row([
                dbc.Col(chart, width=6) for chart in row_charts
            ], className="mb-3"))

    # ===== SECTION 3: Service Distribution Pie Charts =====
    if services_on_node and len(services_on_node) > 0:
        components.append(html.H5("Service Resource Distribution", style={'marginTop': '20px', 'marginBottom': '15px', 'color': '#3b82f6'}))

        pie_charts = []

        # Create consistent color mapping for services
        service_colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316']
        sorted_services = sorted(services_on_node)
        service_color_map = {service: service_colors[i % len(service_colors)] for i, service in enumerate(sorted_services)}

        # Pie chart 1: By memory usage
        if 'container.memory.usage_mb' in pod_available_metrics and not pod_metrics.empty:
            mem_by_service = {}
            for pod_id in pod_ids:
                service = pod_to_service.get(pod_id, 'unknown')
                pod_mem = pod_metrics[
                    (pod_metrics['component_id'] == pod_id) &
                    (pod_metrics['metric_name'] == 'container.memory.usage_mb')
                ]['value'].mean()
                if pd.notna(pod_mem):
                    mem_by_service[service] = mem_by_service.get(service, 0) + pod_mem

            if mem_by_service:
                # Sort to ensure consistent ordering
                sorted_mem_services = sorted(mem_by_service.keys())
                colors = [service_color_map[s] for s in sorted_mem_services]

                fig1 = go.Figure(data=[go.Pie(
                    labels=sorted_mem_services,
                    values=[mem_by_service[s] for s in sorted_mem_services],
                    hole=0.3,
                    marker=dict(colors=colors),
                    textinfo='label+percent',
                    textfont=dict(size=12)
                )])
                fig1.update_layout(
                    title='Services by Memory Usage',
                    height=350,
                    margin=dict(l=20, r=20, t=40, b=20),
                    paper_bgcolor='#111827',
                    font=dict(color='#f9fafb'),
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
                )
                pie_charts.append(dcc.Graph(figure=fig1, config={'displayModeBar': False}))

        # Pie chart 2: By CPU usage
        if 'container.cpu.utilization' in pod_available_metrics and not pod_metrics.empty:
            cpu_by_service = {}
            for pod_id in pod_ids:
                service = pod_to_service.get(pod_id, 'unknown')
                pod_cpu = pod_metrics[
                    (pod_metrics['component_id'] == pod_id) &
                    (pod_metrics['metric_name'] == 'container.cpu.utilization')
                ]['value'].mean()
                if pd.notna(pod_cpu):
                    cpu_by_service[service] = cpu_by_service.get(service, 0) + pod_cpu

            if cpu_by_service:
                # Sort to ensure consistent ordering
                sorted_cpu_services = sorted(cpu_by_service.keys())
                colors = [service_color_map[s] for s in sorted_cpu_services]

                fig2 = go.Figure(data=[go.Pie(
                    labels=sorted_cpu_services,
                    values=[cpu_by_service[s] for s in sorted_cpu_services],
                    hole=0.3,
                    marker=dict(colors=colors),
                    textinfo='label+percent',
                    textfont=dict(size=12)
                )])
                fig2.update_layout(
                    title='Services by CPU Usage',
                    height=350,
                    margin=dict(l=20, r=20, t=40, b=20),
                    paper_bgcolor='#111827',
                    font=dict(color='#f9fafb'),
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
                )
                pie_charts.append(dcc.Graph(figure=fig2, config={'displayModeBar': False}))

        # Add pie charts in row
        if pie_charts:
            components.append(dbc.Row([
                dbc.Col(chart, width=6) for chart in pie_charts
            ], className="mb-3"))

    # ===== SECTION 4: Pod Breakdown =====
    if pod_available_metrics and pod_ids:
        components.append(html.H5(f"Pod Resource Breakdown ({len(pod_ids)} pods)", style={'marginTop': '20px', 'marginBottom': '15px', 'color': '#3b82f6'}))

        # Stacked CPU chart - show CPU per pod over time
        if 'container.cpu.utilization' in pod_available_metrics:
            cpu_data = pod_metrics[pod_metrics['metric_name'] == 'container.cpu.utilization'].copy()
            if not cpu_data.empty:
                fig = go.Figure()

                # Add trace for each pod
                colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316']
                for idx, pod_id in enumerate(sorted(pod_ids)):
                    pod_cpu = cpu_data[cpu_data['component_id'] == pod_id]
                    if not pod_cpu.empty:
                        service = pod_to_service.get(pod_id, 'unknown')
                        fig.add_trace(go.Scatter(
                            x=pod_cpu['sim_time'],
                            y=pod_cpu['value'],
                            mode='lines',
                            name=f"{pod_id} ({service})",
                            line=dict(width=2, color=colors[idx % len(colors)]),
                            stackgroup='one'
                        ))

                fig.update_layout(
                    title='CPU Usage by Pod (Stacked)',
                    xaxis_title='Time (s)',
                    yaxis_title='CPU %',
                    height=350,
                    margin=dict(l=50, r=20, t=40, b=40),
                    plot_bgcolor='#1f2937',
                    paper_bgcolor='#111827',
                    font=dict(color='#f9fafb'),
                    hovermode='x unified',
                    legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02)
                )
                components.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

        # Stacked Memory chart
        if 'container.memory.usage_mb' in pod_available_metrics:
            mem_data = pod_metrics[pod_metrics['metric_name'] == 'container.memory.usage_mb'].copy()
            if not mem_data.empty:
                fig = go.Figure()

                colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316']
                for idx, pod_id in enumerate(sorted(pod_ids)):
                    pod_mem = mem_data[mem_data['component_id'] == pod_id]
                    if not pod_mem.empty:
                        service = pod_to_service.get(pod_id, 'unknown')
                        fig.add_trace(go.Scatter(
                            x=pod_mem['sim_time'],
                            y=pod_mem['value'],
                            mode='lines',
                            name=f"{pod_id} ({service})",
                            line=dict(width=2, color=colors[idx % len(colors)]),
                            stackgroup='one'
                        ))

                fig.update_layout(
                    title='Memory Usage by Pod (Stacked)',
                    xaxis_title='Time (s)',
                    yaxis_title='Memory (MB)',
                    height=350,
                    margin=dict(l=50, r=20, t=40, b=40),
                    plot_bgcolor='#1f2937',
                    paper_bgcolor='#111827',
                    font=dict(color='#f9fafb'),
                    hovermode='x unified',
                    legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02)
                )
                components.append(dcc.Graph(figure=fig, config={'displayModeBar': False}))

    # If no content created, show message
    if not components:
        components.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Node metrics: {', '.join(node_available_metrics) if node_available_metrics else 'None'}",
                   style={'fontSize': '0.8em', 'color': '#666'}),
            html.P(f"Pod metrics: {', '.join(list(pod_available_metrics)[:5]) if pod_available_metrics else 'None'}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    return components


def create_workload_drilldown(metrics_df: pd.DataFrame, component_id: str,
                               label_data: Dict) -> List:
    """Create drill-down charts for WorkloadGenerator.

    Returns charts wrapped in full-width rows.
    """
    return [
        # Header with description (full width)
        dbc.Row([
            dbc.Col([
                html.H5("Workload Generator Metrics", className="text-info mb-2 mt-3"),
                html.P([
                    "The workload generator sends HTTP requests to the gateway and tracks ",
                    "connection pool usage, circuit breaker state, and request outcomes."
                ], className="text-muted mb-3")
            ], width=12)
        ], className="mb-3"),

        # Section 1: Resource Utilization (full width)
        dbc.Row([
            dbc.Col([
                html.H6("Resource Utilization", className="text-secondary mb-2"),
                dcc.Graph(
                    figure=create_connection_pool_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ], className="mb-4"),

        # Section 2: Circuit Breaker (full width)
        dbc.Row([
            dbc.Col([
                html.H6("Circuit Breaker State", className="text-secondary mb-2"),
                html.P(
                    "Circuit breaker protects the system by stopping requests when failure rate is high.",
                    className="text-muted small mb-2"
                ),
                dcc.Graph(
                    figure=create_circuit_breaker_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ], className="mb-4"),

        # Section 3: Request Outcomes (full width)
        dbc.Row([
            dbc.Col([
                html.H6("Request Outcomes", className="text-secondary mb-2"),
                html.P(
                    "Shows successful, failed, timed-out, and rejected requests over time.",
                    className="text-muted small mb-2"
                ),
                dcc.Graph(
                    figure=create_request_outcomes_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ], className="mb-4")
    ]


def create_gateway_drilldown(metrics_df: pd.DataFrame, component_id: str,
                             label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for RequestGateway."""
    charts = []

    # Get all metrics for this component
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # Request rate
    if 'http.server.requests' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'http.server.requests',
                'Request Rate',
                'Requests'
            ),
            config={'displayModeBar': False}
        ))

    # Request duration
    if 'http.server.request.duration' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_percentile_chart(
                metrics_df, component_id,
                'http.server.request.duration',
                'Request Duration'
            ),
            config={'displayModeBar': False}
        ))

    # Total errors
    if 'component.errors.total' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_metric_chart(
                metrics_df, component_id,
                'component.errors.total',
                'Total Errors',
                'Count'
            ),
            config={'displayModeBar': False}
        ))

    # Dependencies (services gateway routes to)
    dependency_request_metric = 'gateway.dependency.requests'
    dependency_duration_metric = 'gateway.dependency.duration'
    dependency_error_metric = 'gateway.dependency.errors'

    has_dependency_metrics = (dependency_request_metric in available_metrics or
                              dependency_duration_metric in available_metrics or
                              dependency_error_metric in available_metrics)

    if has_dependency_metrics:
        # Get dependency metrics for this gateway
        dep_metrics = component_metrics[
            component_metrics['metric_name'].str.contains('dependency', na=False)
        ]

        external_deps = []
        if 'dependency_id' in dep_metrics.columns:
            external_deps = dep_metrics['dependency_id'].dropna().unique().tolist()

        if external_deps:
            # Add section header
            charts.append(html.Hr(style={'marginTop': '40px', 'marginBottom': '20px', 'borderColor': '#555'}))
            charts.append(html.H4("Dependencies (Routed Services)", style={'marginBottom': '15px'}))

            # Create accordion items for each dependency
            accordion_items = []
            for dep_id in sorted(external_deps):
                dep_specific = dep_metrics[dep_metrics['dependency_id'] == dep_id]
                dep_name = dep_specific['dependency_name'].iloc[0] if 'dependency_name' in dep_specific.columns and not dep_specific.empty else dep_id

                # Create charts for this dependency
                dep_charts = []

                if dependency_request_metric in available_metrics:
                    dep_charts.append(dcc.Graph(
                        figure=create_metric_chart_filtered(
                            metrics_df, component_id,
                            dependency_request_metric,
                            'Request Rate',
                            'Requests',
                            filter_col='dependency_id',
                            filter_val=dep_id
                        ),
                        config={'displayModeBar': False}
                    ))

                if dependency_duration_metric in available_metrics:
                    dep_duration_data = dep_specific[dep_specific['metric_name'] == dependency_duration_metric]
                    if 'p50' in dep_duration_data.columns and not dep_duration_data['p50'].isna().all():
                        dep_charts.append(dcc.Graph(
                            figure=create_percentile_chart_filtered(
                                metrics_df, component_id,
                                dependency_duration_metric,
                                'Latency',
                                filter_col='dependency_id',
                                filter_val=dep_id
                            ),
                            config={'displayModeBar': False}
                        ))
                    else:
                        dep_charts.append(dcc.Graph(
                            figure=create_metric_chart_filtered(
                                metrics_df, component_id,
                                dependency_duration_metric,
                                'Latency',
                                'ms',
                                filter_col='dependency_id',
                                filter_val=dep_id
                            ),
                            config={'displayModeBar': False}
                        ))

                if dependency_error_metric in available_metrics:
                    dep_charts.append(dcc.Graph(
                        figure=create_metric_chart_filtered(
                            metrics_df, component_id,
                            dependency_error_metric,
                            'Errors',
                            'Errors',
                            filter_col='dependency_id',
                            filter_val=dep_id
                        ),
                        config={'displayModeBar': False}
                    ))

                # Create accordion item
                accordion_items.append(
                    dbc.AccordionItem(
                        dep_charts,
                        title=f"→ {dep_name}",
                    )
                )

            # Add accordion to charts
            charts.append(dbc.Accordion(
                accordion_items,
                start_collapsed=True,
                always_open=False,
            ))

    # If no charts were created, show a message
    if not charts:
        charts.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    return charts


def create_fault_injection_timeline(label_data: Dict, component_id: str) -> html.Div:
    """
    Create a visual timeline showing fault injection details including recovery.

    Args:
        label_data: Label data with fault information
        component_id: Component ID to check if it's the root cause

    Returns:
        Dash HTML component with fault timeline
    """
    # Only show if this is the root cause
    if component_id != label_data.get('root_cause_node'):
        return html.Div()

    # Extract fault information
    fault_type = label_data.get('fault_type', 'Unknown')
    fault_start = label_data.get('fault_start_time', 0)
    ramp_duration = label_data.get('fault_ramp_duration', 0)
    full_effect_time = label_data.get('fault_full_effect_time', 0)
    total_duration = label_data.get('fault_total_duration', 0)
    recovery_start = label_data.get('recovery_start_time')
    recovery_complete = label_data.get('recovery_complete_time')
    progression_info = label_data.get('progression', {})
    progression_type = progression_info.get('type', 'instant')
    fault_params = label_data.get('fault_params', {})

    # Get timeline from label data if available
    timeline_data = label_data.get('timeline', {})

    # Create timeline visualization
    # Timeline shows: [healthy] -> [ramp-up] -> [full effect] -> [recovery] -> [recovered]
    timeline_items = []

    # Healthy phase
    timeline_items.append(
        html.Div([
            html.Div("Healthy", style={
                'backgroundColor': '#22c55e',
                'padding': '8px',
                'borderRadius': '4px',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center',
                'marginBottom': '4px'
            }),
            html.Div(f"0s - {fault_start}s", style={
                'fontSize': '0.85em',
                'color': '#9ca3af',
                'textAlign': 'center'
            })
        ], style={'flex': f'{fault_start}', 'marginRight': '8px'})
    )

    # Ramp-up phase (if gradual)
    if ramp_duration > 0:
        timeline_items.append(
            html.Div([
                html.Div(f"Degrading ({progression_type})", style={
                    'backgroundColor': '#f59e0b',
                    'padding': '8px',
                    'borderRadius': '4px',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'textAlign': 'center',
                    'marginBottom': '4px'
                }),
                html.Div(f"{fault_start}s - {full_effect_time}s", style={
                    'fontSize': '0.85em',
                    'color': '#9ca3af',
                    'textAlign': 'center'
                })
            ], style={'flex': f'{ramp_duration}', 'marginRight': '8px'})
        )

    # Full failure phase
    if recovery_start is not None:
        # Fault ends at recovery start
        failure_duration = recovery_start - full_effect_time
        fault_end_time = recovery_start
    else:
        # No recovery, fault lasts until end
        failure_duration = total_duration - ramp_duration
        fault_end_time = fault_start + total_duration

    timeline_items.append(
        html.Div([
            html.Div("Full Failure", style={
                'backgroundColor': '#ef4444',
                'padding': '8px',
                'borderRadius': '4px',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center',
                'marginBottom': '4px'
            }),
            html.Div(f"{full_effect_time}s - {fault_end_time}s", style={
                'fontSize': '0.85em',
                'color': '#9ca3af',
                'textAlign': 'center'
            })
        ], style={'flex': f'{failure_duration}', 'marginRight': '8px' if recovery_start else ''})
    )

    # Recovery phase (if exists)
    if recovery_start is not None and recovery_complete is not None:
        recovery_duration = recovery_complete - recovery_start
        timeline_items.append(
            html.Div([
                html.Div("Recovery", style={
                    'backgroundColor': '#10b981',
                    'padding': '8px',
                    'borderRadius': '4px',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'textAlign': 'center',
                    'marginBottom': '4px'
                }),
                html.Div(f"{recovery_start}s - {recovery_complete}s", style={
                    'fontSize': '0.85em',
                    'color': '#9ca3af',
                    'textAlign': 'center'
                })
            ], style={'flex': f'{recovery_duration}', 'marginRight': '8px'})
        )

        # Recovered/healthy baseline phase
        episode_end = timeline_data.get('episode_end', 600)
        recovered_duration = episode_end - recovery_complete
        if recovered_duration > 0:
            timeline_items.append(
                html.Div([
                    html.Div("Recovered", style={
                        'backgroundColor': '#22c55e',
                        'padding': '8px',
                        'borderRadius': '4px',
                        'color': 'white',
                        'fontWeight': 'bold',
                        'textAlign': 'center',
                        'marginBottom': '4px'
                    }),
                    html.Div(f"{recovery_complete}s - {episode_end}s", style={
                        'fontSize': '0.85em',
                        'color': '#9ca3af',
                        'textAlign': 'center'
                    })
                ], style={'flex': f'{recovered_duration}'})
            )

    # Format fault parameters with detailed breakdown
    param_items = []
    param_badges = []

    # Group parameters by type (changed, added, removed implied)
    for key, value in fault_params.items():
        # Format based on parameter type
        if isinstance(value, float):
            if key.endswith('_rate'):
                formatted = f"{value*100:.1f}%"
                badge_color = '#ef4444' if value > 0.5 else '#f59e0b'
            elif key.endswith('_latency') or key.endswith('_delay'):
                formatted = f"{value:.0f}ms"
                badge_color = '#ef4444' if value > 1000 else '#f59e0b'
            else:
                formatted = f"{value:.2f}"
                badge_color = '#f59e0b'
        elif isinstance(value, int):
            formatted = str(value)
            badge_color = '#f59e0b'
        elif isinstance(value, bool):
            formatted = 'Enabled' if value else 'Disabled'
            badge_color = '#10b981' if value else '#6b7280'
        else:
            formatted = str(value)
            badge_color = '#6b7280'

        param_name = key.replace('_', ' ').title()
        param_items.append(f"{param_name}: {formatted}")

        # Create badge for each parameter
        param_badges.append(
            html.Span([
                html.Strong(f"{param_name}: ", style={'color': '#d1d5db'}),
                html.Span(formatted, style={
                    'backgroundColor': badge_color,
                    'padding': '2px 8px',
                    'borderRadius': '4px',
                    'marginLeft': '4px',
                    'fontWeight': 'bold'
                })
            ], style={'marginRight': '12px', 'display': 'inline-block', 'marginBottom': '8px'})
        )

    # Create progression description with recovery info
    if recovery_start is not None:
        progression_text = f"A-B-A Pattern: {progression_type.title()} degradation ({ramp_duration}s), then recovery ({recovery_complete - recovery_start if recovery_complete else 0}s)"
    else:
        progression_text = f"{progression_type.title()} over {ramp_duration}s" if ramp_duration > 0 else "Instant"

    return html.Div([
        html.Div([
            html.H6("⚠️ Fault Injection & Recovery Details", style={
                'color': '#ef4444',
                'marginBottom': '15px',
                'fontWeight': 'bold'
            }),
            html.Div([
                # Fault Type
                html.Div([
                    html.Strong("Fault Type: ", style={'color': '#d1d5db'}),
                    html.Span(fault_type.replace('_', ' ').title(), style={
                        'backgroundColor': '#7c2d12',
                        'padding': '4px 12px',
                        'borderRadius': '4px',
                        'fontWeight': 'bold',
                        'color': '#fca5a5'
                    })
                ], style={'marginBottom': '12px'}),

                # Progression Type
                html.Div([
                    html.Strong("Progression: ", style={'color': '#d1d5db'}),
                    html.Span(progression_text)
                ], style={'marginBottom': '12px'}),

                # Parameters Section
                html.Div([
                    html.Strong("Fault Parameters:", style={'color': '#d1d5db', 'display': 'block', 'marginBottom': '8px'}),
                    html.Div(
                        param_badges if param_badges else html.Span('No parameters', style={'color': '#9ca3af', 'fontStyle': 'italic'}),
                        style={'marginLeft': '0px'}
                    )
                ], style={'marginBottom': '15px'}),

                # Recovery Info (if exists)
                *([html.Div([
                    html.Strong("Recovery: ", style={'color': '#10b981'}),
                    html.Span(f"Fault removed at {recovery_start}s, fully recovered by {recovery_complete}s", style={'color': '#d1d5db'})
                ], style={'marginBottom': '15px', 'padding': '8px', 'backgroundColor': '#064e3b', 'borderRadius': '4px'})] if recovery_start else []),
            ]),

            # Timeline Visualization
            html.Div([
                html.Strong("Timeline:", style={'marginBottom': '10px', 'display': 'block', 'color': '#d1d5db'}),
                html.Div(timeline_items, style={
                    'display': 'flex',
                    'width': '100%',
                    'marginTop': '10px'
                })
            ])
        ], style={
            'backgroundColor': '#1f2937',
            'padding': '20px',
            'borderRadius': '8px',
            'border': '2px solid #ef4444',
            'marginBottom': '20px'
        })
    ])


def create_pod_lifecycle_timeline(service_id: str, topology_events: Optional[Dict],
                                  label_data: Optional[Dict] = None) -> Optional[html.Div]:
    """
    Create a timeline visualization of pod lifecycle events for a service.

    Args:
        service_id: Service identifier
        topology_events: Dictionary with topology events data
        label_data: Label data containing warmup period info

    Returns:
        Dash HTML component with pod timeline, or None if no events
    """
    if not topology_events or not topology_events.get('by_service'):
        return None

    service_events = topology_events['by_service'].get(service_id, [])

    if not service_events:
        return None

    # Get warmup period to convert physical time to simulation time
    warmup_period = 0
    if label_data:
        warmup_period = label_data.get('warmup_period', 0)

    # Convert event timestamps from physical time to simulation time
    service_events_sim = []
    for event in service_events:
        event_sim = event.copy()
        event_sim['timestamp'] = max(0, event['timestamp'] - warmup_period)
        service_events_sim.append(event_sim)

    # Get simulation time range from all events (to set consistent x-axis across all services)
    all_timestamps = [e['timestamp'] for e in topology_events.get('all_events', [])]
    if all_timestamps:
        # Convert to simulation time
        sim_start = max(0, min(all_timestamps) - warmup_period)
        sim_end = max(0, max(all_timestamps) - warmup_period)
    else:
        sim_start = 0
        sim_end = 300  # Default simulation duration

    # Create timeline figure
    fig = go.Figure()

    # Event type colors
    event_colors = {
        'pod_created': '#10b981',      # Green
        'pod_state_change': '#3b82f6', # Blue
        'pod_crashed': '#ef4444',      # Red
        'pod_terminated': '#6b7280',   # Gray
        'pod_rescheduled': '#f59e0b',  # Orange
        'pod_restarted': '#fbbf24'     # Yellow/Amber
    }

    # Event type symbols
    event_symbols = {
        'pod_created': 'circle',
        'pod_state_change': 'diamond',
        'pod_crashed': 'x',
        'pod_terminated': 'square',
        'pod_rescheduled': 'triangle-up',
        'pod_restarted': 'circle-open'  # Hollow circle
    }

    # Group events by pod for y-axis placement
    pods = sorted(set(e['pod_id'] for e in service_events_sim))
    pod_to_y = {pod_id: i for i, pod_id in enumerate(pods)}

    # Group events by (timestamp, pod_id) to handle overlapping events
    from collections import defaultdict
    events_by_time_pod = defaultdict(list)
    for event in service_events_sim:
        key = (event['timestamp'], event['pod_id'])
        events_by_time_pod[key].append(event)

    # Plot each event with slight offset for overlapping events at same time
    for event in service_events_sim:
        event_type = event['event_type']
        color = event_colors.get(event_type, '#gray')
        symbol = event_symbols.get(event_type, 'circle')

        # Calculate y-offset for overlapping events (spread vertically)
        key = (event['timestamp'], event['pod_id'])
        events_at_time = events_by_time_pod[key]
        if len(events_at_time) > 1:
            event_index = events_at_time.index(event)
            y_offset = (event_index - (len(events_at_time) - 1) / 2) * 0.15  # Spread by ±0.15 units
        else:
            y_offset = 0

        hover_text = f"<b>{event_type.replace('_', ' ').title()}</b><br>"
        hover_text += f"Pod: {event['pod_id']}<br>"
        hover_text += f"Time: {event['timestamp']:.1f}s<br>"
        hover_text += f"Node: {event.get('node_id', 'N/A')}<br>"
        hover_text += f"Details: {event.get('details', '')}"
        if 'restarts' in event:
            hover_text += f"<br>Restarts: {event['restarts']}"

        fig.add_trace(go.Scatter(
            x=[event['timestamp']],
            y=[pod_to_y[event['pod_id']] + y_offset],
            mode='markers',
            marker=dict(
                size=12,
                color=color,
                symbol=symbol,
                line=dict(width=1, color='white')
            ),
            name=event_type.replace('_', ' ').title(),
            hovertext=hover_text,
            hoverinfo='text',
            showlegend=False
        ))

    # Use full simulation time range for consistent x-axis across all services
    time_padding = (sim_end - sim_start) * 0.02  # 2% padding
    x_range = [max(0, sim_start - time_padding), sim_end + time_padding]

    # Update layout to match existing chart style (dark theme)
    fig.update_layout(
        title="Pod Lifecycle Timeline",
        xaxis=dict(
            title="Time (s)",
            gridcolor='rgba(255, 255, 255, 0.1)',
            range=x_range
        ),
        yaxis=dict(
            title="Pods",
            tickmode='array',
            tickvals=list(range(len(pods))),
            ticktext=pods,
            gridcolor='rgba(255, 255, 255, 0.1)',
            range=[-0.5, len(pods) - 0.5] if len(pods) > 1 else [-0.5, 0.5]  # Center pods in view
        ),
        height=max(200, len(pods) * 30 + 60),
        hovermode='closest',
        plot_bgcolor='#374151',
        paper_bgcolor='#374151',
        font=dict(color='#f9fafb'),
        margin=dict(l=150, r=20, t=40, b=40),
        showlegend=False
    )

    # Add legend manually with dark theme colors
    legend_items = []
    for event_type, color in event_colors.items():
        count = sum(1 for e in service_events_sim if e['event_type'] == event_type)
        if count > 0:
            legend_items.append(
                html.Span([
                    html.Span("●", style={'color': color, 'fontSize': '16px', 'marginRight': '5px'}),
                    html.Span(f"{event_type.replace('_', ' ').title()} ({count})",
                             style={'color': '#f9fafb'})
                ], style={'marginRight': '15px', 'display': 'inline-block'})
            )

    return html.Div([
        html.Div(legend_items, style={'marginBottom': '10px', 'marginTop': '10px'}),
        dcc.Graph(figure=fig, config={'displayModeBar': False})
    ])


def create_component_drilldown(component_id: str, metrics_df: pd.DataFrame,
                              graph: nx.DiGraph, label_data: Dict,
                              topology_events: Optional[Dict] = None):
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

    # Check if this is a network partition fault and if this component is affected
    is_network_partition = label_data.get('fault_type') == 'network_partition'
    partition_info = label_data.get('network_partition', {}) or label_data.get('fault_params', {})
    partition_source = partition_info.get('source_component_id', partition_info.get('source_component'))
    partition_target = partition_info.get('target_component_id', partition_info.get('target_component'))
    partition_bidirectional = partition_info.get('bidirectional', False)

    # Check if this component is one of the partitioned components
    is_partitioned_component = False
    partitioned_from = None
    if is_network_partition and partition_source and partition_target:
        if partition_source in component_id or component_id in partition_source:
            is_partitioned_component = True
            partitioned_from = partition_target
        elif partition_target in component_id or component_id in partition_target:
            is_partitioned_component = True
            partitioned_from = partition_source

    # Create header
    header_contents = [
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
    ]

    # Add network partition banner if this component is affected
    if is_partitioned_component and partitioned_from:
        fault_start = label_data.get('fault_start_time', 0)
        recovery_start = label_data.get('recovery_start_time', 0)
        direction_symbol = "⟷" if partition_bidirectional else "→"

        partition_banner = dbc.Alert([
            html.H6("🔌 NETWORK PARTITION DETECTED", className="alert-heading"),
            html.P([
                f"This component is partitioned from: ",
                html.Strong(partitioned_from, style={'fontFamily': 'monospace'}),
            ], className="mb-2"),
            html.P([
                f"Communication between these components is blocked during: ",
                html.Strong(f"{fault_start}s - {recovery_start}s"),
            ], className="mb-0", style={'fontSize': '0.9em'}),
        ], color="danger", className="mt-2 mb-3")

        header_contents.append(partition_banner)

    header = html.Div(header_contents)

    # Add fault injection timeline if this is the root cause
    fault_timeline = create_fault_injection_timeline(label_data, component_id) if is_root_cause else html.Div()

    # Create charts based on component type
    charts = []
    if component_type == 'Service':
        # New architecture: Service with Pods
        charts = create_service_drilldown(metrics_df, component_id, label_data, graph, topology_events)
    elif component_type == 'Pod':
        # New architecture: Individual Pod drill-down
        charts = create_pod_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'SqlDatabase':
        charts = create_database_drilldown(metrics_df, component_id, label_data)
    elif component_type in ['InMemoryCache', 'ExternalCache']:
        charts = create_cache_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'MessageQueue':
        charts = create_queue_drilldown(metrics_df, component_id, label_data, graph)
    elif component_type == 'ExternalService':
        charts = create_external_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'WorkloadGenerator':
        # Workload generator shows connection pool, circuit breaker, and request outcomes
        charts = create_workload_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'RequestGateway':
        # Gateway uses generic HTTP server metrics
        charts = create_gateway_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'ComputeNode':
        # Infrastructure compute node
        charts = create_compute_node_drilldown(metrics_df, component_id, graph, label_data)
    else:
        # Generic fallback - show whatever metrics exist
        component_metrics = metrics_df[metrics_df['component_id'] == component_id]
        available_metrics = set(component_metrics['metric_name'].unique())

        if available_metrics:
            charts = []
            for metric in sorted(available_metrics):
                charts.append(dcc.Graph(
                    figure=create_metric_chart(
                        metrics_df, component_id,
                        metric,
                        metric,
                        'Value'
                    ),
                    config={'displayModeBar': False}
                ))
        else:
            charts = [html.P(f"No metrics available for {component_id} (type: {component_type})")]

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
        fault_timeline,  # Add fault injection timeline for root cause
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
