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
                                   metric_name: str, title: str, ylabel: str) -> go.Figure:
    """
    Create aggregated chart for service by aggregating Pod metrics.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        ylabel: Y-axis label
    """
    # Aggregate Pod metrics by service.name tag
    data = metrics_df[
        (metrics_df.get('service.name', pd.Series(dtype='object')) == service_id) &
        (metrics_df['metric_name'] == metric_name)
    ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Group by sim_time and aggregate (mean across all pods)
    aggregated = data.groupby('sim_time', as_index=False)['value'].mean()

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
                                               metric_name: str, title: str) -> go.Figure:
    """
    Create aggregated percentile chart for service by aggregating Pod metrics.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
    """
    # Aggregate Pod percentile metrics by service.name tag
    data = metrics_df[
        (metrics_df.get('service.name', pd.Series(dtype='object')) == service_id) &
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
                                            filter_col: str, filter_val: str) -> go.Figure:
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
    """
    # Aggregate Pod metrics by service.name tag with additional filter
    data = metrics_df[
        (metrics_df.get('service.name', pd.Series(dtype='object')) == service_id) &
        (metrics_df['metric_name'] == metric_name) &
        (metrics_df[filter_col] == filter_val)
    ].copy()

    if data.empty:
        return go.Figure().update_layout(title=f"{title} (No Data)")

    # Group by sim_time and aggregate (mean across all pods)
    aggregated = data.groupby('sim_time', as_index=False)['value'].mean()

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
                                                        filter_col: str, filter_val: str) -> go.Figure:
    """
    Create aggregated percentile chart for service with additional filter.

    Args:
        metrics_df: DataFrame with all metrics
        service_id: Service ID to aggregate for
        metric_name: Metric name to display
        title: Chart title
        filter_col: Column name to filter on (e.g., 'dependency_id')
        filter_val: Value to filter for
    """
    # Aggregate Pod percentile metrics by service.name tag with additional filter
    data = metrics_df[
        (metrics_df.get('service.name', pd.Series(dtype='object')) == service_id) &
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
                             label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for Service by aggregating Pod metrics."""
    charts = []

    # Get all metrics for this component to see what's available
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # Get Pod metrics for this service (aggregate by service.name tag)
    pod_metrics = metrics_df[
        (metrics_df.get('service.name', pd.Series(dtype='object')) == component_id) &
        (metrics_df['component_id'].str.startswith('pod_', na=False))
    ]

    pod_metrics_available = set(pod_metrics['metric_name'].unique()) if not pod_metrics.empty else set()

    # Request rate (aggregate from Pod metrics using service.name tag)
    request_metric = f'service.{component_id}.requests'
    if request_metric in pod_metrics_available:
        charts.append(dcc.Graph(
            figure=create_service_aggregated_chart(
                metrics_df, component_id,
                request_metric,
                'Request Rate',
                'Requests/s'
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
                    'Request Duration (Latency)'
                ),
                config={'displayModeBar': False}
            ))
        else:
            charts.append(dcc.Graph(
                figure=create_service_aggregated_chart(
                    metrics_df, component_id,
                    duration_metric,
                    'Request Duration',
                    'ms'
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
                'Errors'
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
                    'Percentage (%)'
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
                    'MB'
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
                    'Count'
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
                    'Count'
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
                    'Count'
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
                    'Count'
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
                            filter_val=dep_id
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
                                filter_val=dep_id
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
                                filter_val=dep_id
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

    return charts


def create_database_drilldown(metrics_df: pd.DataFrame, component_id: str,
                              label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for SqlDatabase."""
    charts = []

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

    # If no charts were created, show a message
    if not charts:
        charts.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    return charts


def create_cache_drilldown(metrics_df: pd.DataFrame, component_id: str,
                          label_data: Dict) -> List[dcc.Graph]:
    """Create drill-down charts for InMemoryCache."""
    charts = []

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

    # If no charts were created, show a message
    if not charts:
        charts.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

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

    # Get all metrics for this component
    component_metrics = metrics_df[metrics_df['component_id'] == component_id]
    available_metrics = set(component_metrics['metric_name'].unique())

    # Request rate
    if 'http.client.requests' in available_metrics:
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
    if 'http.client.errors' in available_metrics:
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
    if 'http.client.request.duration' in available_metrics:
        charts.append(dcc.Graph(
            figure=create_percentile_chart(
                metrics_df, component_id,
                'http.client.request.duration',
                'Request Latency'
            ),
            config={'displayModeBar': False}
        ))

    # If no charts were created, show a message
    if not charts:
        charts.append(html.Div([
            html.P(f"No detailed metrics available for {component_id}"),
            html.P(f"Available metrics: {', '.join(available_metrics)}",
                   style={'fontSize': '0.8em', 'color': '#666'})
        ]))

    return charts


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
    Create a visual timeline showing fault injection details.

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
    fault_end = fault_start + total_duration
    progression_info = label_data.get('progression', {})
    progression_type = progression_info.get('type', 'instant')
    fault_params = label_data.get('fault_params', {})

    # Create timeline visualization
    # Timeline shows: [healthy] -> [ramp-up] -> [full effect]
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
    failure_duration = total_duration - ramp_duration
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
            html.Div(f"{full_effect_time}s - {fault_end}s", style={
                'fontSize': '0.85em',
                'color': '#9ca3af',
                'textAlign': 'center'
            })
        ], style={'flex': f'{failure_duration}'})
    )

    # Format fault parameters
    param_items = []
    for key, value in fault_params.items():
        if isinstance(value, float):
            if key.endswith('_rate'):
                param_items.append(f"{key}: {value*100:.1f}%")
            else:
                param_items.append(f"{key}: {value:.2f}")
        else:
            param_items.append(f"{key}: {value}")

    return html.Div([
        html.Div([
            html.H6("⚠️ Fault Injection Details", style={
                'color': '#ef4444',
                'marginBottom': '15px',
                'fontWeight': 'bold'
            }),
            html.Div([
                html.Div([
                    html.Strong("Fault Type: "),
                    html.Span(fault_type.replace('_', ' ').title())
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Parameters: "),
                    html.Span(', '.join(param_items) if param_items else 'None')
                ], style={'marginBottom': '8px'}),
                html.Div([
                    html.Strong("Progression: "),
                    html.Span(f"{progression_type.title()} over {ramp_duration}s" if ramp_duration > 0 else "Instant")
                ], style={'marginBottom': '15px'}),
            ]),
            html.Div([
                html.Strong("Timeline:", style={'marginBottom': '10px', 'display': 'block'}),
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

    # Add fault injection timeline if this is the root cause
    fault_timeline = create_fault_injection_timeline(label_data, component_id) if is_root_cause else html.Div()

    # Create charts based on component type
    charts = []
    if component_type == 'Service':
        # New architecture: Service with Pods
        charts = create_service_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'Pod':
        # New architecture: Individual Pod drill-down
        charts = create_pod_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'SqlDatabase':
        charts = create_database_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'InMemoryCache':
        charts = create_cache_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'MessageQueue':
        charts = create_queue_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'ExternalService':
        charts = create_external_drilldown(metrics_df, component_id, label_data)
    elif component_type == 'RequestGateway':
        # Gateway uses generic HTTP server metrics
        charts = create_gateway_drilldown(metrics_df, component_id, label_data)
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
