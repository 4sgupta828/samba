"""
Workload Generator Charts

Creates visualizations for workload generator behavior:
- Connection pool utilization and active connections
- In-flight requests (queue depth)
- Circuit breaker state
- Request outcomes (success, failure, rejections, timeouts)

These metrics help understand if the workload generator itself became a bottleneck
or activated protective mechanisms (circuit breaker, backpressure).
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict


def add_fault_markers_with_shading(fig: go.Figure, label_data: Dict, row: int = None, col: int = 1):
    """
    Add fault injection and removal markers with shaded region to a figure.

    Args:
        fig: Plotly figure to add markers to
        label_data: Label data containing fault timing information
        row: Row number for subplot (None for single plot)
        col: Column number for subplot
    """
    fault_start = label_data.get('fault_start_time', 0)
    recovery_start = label_data.get('recovery_start_time')

    # Calculate fault end time (either recovery start or fault_total_duration)
    if recovery_start is not None:
        fault_end = recovery_start
    else:
        fault_end = fault_start + label_data.get('fault_total_duration', 0)

    # Add shaded region for fault period
    fig.add_vrect(
        x0=fault_start, x1=fault_end,
        fillcolor="rgba(255, 0, 0, 0.1)",
        layer="below",
        line_width=0,
        row=row, col=col
    )

    # Add fault injection line
    fig.add_vline(
        x=fault_start,
        line=dict(color="red", width=2, dash="dash"),
        row=row, col=col
    )

    # Add fault removal line if recovery exists
    if recovery_start is not None:
        fig.add_vline(
            x=recovery_start,
            line=dict(color="green", width=2, dash="dash"),
            row=row, col=col
        )


def create_connection_pool_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """
    Create chart showing workload generator connection pool metrics.

    Shows:
    - Connection pool utilization (%)
    - Active connections (count)
    - In-flight requests / queue depth (count)
    """
    # Filter for client/workload metrics
    workload_metrics = metrics_df[metrics_df['metric_name'].str.startswith('workload.')].copy()

    if workload_metrics.empty:
        return go.Figure().add_annotation(
            text="No workload connection pool metrics available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        ).update_layout(template='plotly_dark', height=400)

    # Create subplots: 2 rows (utilization + connections, in-flight requests)
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=(
            'Connection Pool Utilization & Active Connections',
            'In-Flight Requests (Queue Depth)'
        ),
        vertical_spacing=0.15,
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
    )

    # sim_time should already be in the DataFrame
    # If not, we can use it directly from the sim_time column

    # Row 1: Connection pool utilization (%) and active connections (count)
    util_df = workload_metrics[workload_metrics['metric_name'] == 'workload.connection_pool.utilization'].copy()
    active_df = workload_metrics[workload_metrics['metric_name'] == 'workload.connection_pool.active'].copy()

    if not util_df.empty:
        util_df = util_df.sort_values('sim_time')
        fig.add_trace(
            go.Scatter(
                x=util_df['sim_time'],
                y=util_df['value'] * 100,  # Convert to percentage
                name='Pool Utilization (%)',
                mode='lines',
                line=dict(color='#00d4ff', width=2),
                fill='tozeroy',
                fillcolor='rgba(0, 212, 255, 0.2)',
                hovertemplate='<b>Time:</b> %{x}s<br>' +
                             '<b>Utilization:</b> %{y:.1f}%<br>' +
                             '<extra></extra>'
            ),
            row=1, col=1, secondary_y=False
        )

    if not active_df.empty:
        active_df = active_df.sort_values('sim_time')
        fig.add_trace(
            go.Scatter(
                x=active_df['sim_time'],
                y=active_df['value'],
                name='Active Connections',
                mode='lines',
                line=dict(color='#00ff9d', width=2, dash='dot'),
                hovertemplate='<b>Time:</b> %{x}s<br>' +
                             '<b>Active:</b> %{y}<br>' +
                             '<extra></extra>'
            ),
            row=1, col=1, secondary_y=True
        )

    # Row 2: In-flight requests (queue depth)
    inflight_df = workload_metrics[workload_metrics['metric_name'] == 'workload.requests.in_flight'].copy()

    if not inflight_df.empty:
        inflight_df = inflight_df.sort_values('sim_time')
        fig.add_trace(
            go.Scatter(
                x=inflight_df['sim_time'],
                y=inflight_df['value'],
                name='In-Flight Requests',
                mode='lines',
                line=dict(color='#ffa500', width=2),
                fill='tozeroy',
                fillcolor='rgba(255, 165, 0, 0.2)',
                hovertemplate='<b>Time:</b> %{x}s<br>' +
                             '<b>In-Flight:</b> %{y}<br>' +
                             '<extra></extra>'
            ),
            row=2, col=1
        )

    # Add fault injection and removal markers
    for row in [1, 2]:
        add_fault_markers_with_shading(fig, label_data, row=row, col=1)

    # Update axes
    fig.update_xaxes(title_text="Simulation Time (seconds)", row=2, col=1)
    fig.update_yaxes(title_text="Utilization (%)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Connections", row=1, col=1, secondary_y=True, rangemode='tozero')
    fig.update_yaxes(title_text="Requests", row=2, col=1, rangemode='tozero')

    fig.update_layout(
        template='plotly_dark',
        hovermode='x unified',
        height=600,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=100, b=60),
        annotations=[
            dict(
                text="🔴 Red line = Fault Injection | 🟢 Green line = Fault Removal",
                xref="paper", yref="paper",
                x=0.5, y=1.08,
                showarrow=False,
                font=dict(size=11, color="#9ca3af"),
                xanchor="center"
            )
        ]
    )

    return fig


def create_circuit_breaker_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """
    Create chart showing client-side circuit breaker state over time.

    States:
    - 0 = CLOSED (normal operation)
    - 1 = OPEN (failing, rejecting requests)
    - 2 = HALF_OPEN (testing recovery)
    """
    # Filter for circuit breaker state metric
    cb_df = metrics_df[metrics_df['metric_name'] == 'workload.circuit_breaker.state'].copy()

    if cb_df.empty:
        return go.Figure().add_annotation(
            text="No circuit breaker metrics available (may be disabled in config)",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        ).update_layout(template='plotly_dark', height=300)

    # sim_time should already be in the DataFrame
    cb_df = cb_df.sort_values('sim_time')

    fig = go.Figure()

    # Add circuit breaker state as step chart
    fig.add_trace(
        go.Scatter(
            x=cb_df['sim_time'],
            y=cb_df['value'],
            name='Circuit Breaker State',
            mode='lines',
            line=dict(color='#ff00ff', width=3, shape='hv'),  # 'hv' creates step chart
            fill='tozeroy',
            fillcolor='rgba(255, 0, 255, 0.2)',
            hovertemplate='<b>Time:</b> %{x}s<br>' +
                         '<b>State:</b> %{text}<br>' +
                         '<extra></extra>',
            text=[{0: 'CLOSED (Normal)', 1: 'OPEN (Failing)', 2: 'HALF_OPEN (Testing)'}.get(int(v), 'Unknown')
                  for v in cb_df['value']]
        )
    )

    # Add fault injection and removal markers
    add_fault_markers_with_shading(fig, label_data)

    fig.update_layout(
        template='plotly_dark',
        hovermode='x unified',
        height=300,
        xaxis_title="Simulation Time (seconds)",
        yaxis_title="State",
        yaxis=dict(
            tickmode='array',
            tickvals=[0, 1, 2],
            ticktext=['CLOSED<br>(Normal)', 'OPEN<br>(Failing)', 'HALF_OPEN<br>(Testing)'],
            rangemode='tozero'
        ),
        margin=dict(l=60, r=60, t=60, b=60),
        annotations=[
            dict(
                text="🔴 Red line = Fault Injection | 🟢 Green line = Fault Removal",
                xref="paper", yref="paper",
                x=0.5, y=1.1,
                showarrow=False,
                font=dict(size=11, color="#9ca3af"),
                xanchor="center"
            )
        ]
    )

    return fig


def create_request_outcomes_chart(metrics_df: pd.DataFrame, label_data: Dict) -> go.Figure:
    """
    Create chart showing workload request outcomes over time.

    Shows:
    - Successful requests
    - Failed requests
    - Timed out requests
    - Rejected requests (circuit breaker open or queue full)
    """
    # Filter for workload request metrics
    req_df = metrics_df[metrics_df['metric_name'] == 'workload.requests'].copy()
    rejected_df = metrics_df[metrics_df['metric_name'] == 'workload.requests.rejected'].copy()

    if req_df.empty and rejected_df.empty:
        return go.Figure().add_annotation(
            text="No workload request outcome metrics available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        ).update_layout(template='plotly_dark', height=400)

    # sim_time should already be in the DataFrame

    fig = go.Figure()

    # Plot different request types using the 'type' column directly
    if 'type' not in req_df.columns:
        req_df['type'] = 'unknown'

    colors = {
        'attempted': '#808080',  # Gray
        'success': '#00ff00',     # Green
        'failed': '#ff0000',      # Red
        'timeout': '#ffff00',     # Yellow
    }

    for req_type in ['success', 'failed', 'timeout', 'attempted']:
        type_df = req_df[req_df['type'] == req_type].copy()
        if not type_df.empty:
            type_df = type_df.sort_values('sim_time')

            fig.add_trace(
                go.Scatter(
                    x=type_df['sim_time'],
                    y=type_df['value'],
                    name=req_type.title(),
                    mode='lines',
                    line=dict(color=colors.get(req_type, '#ffffff'), width=2),
                    stackgroup='requests' if req_type != 'attempted' else None,
                    hovertemplate=f'<b>Time:</b> %{{x}}s<br>' +
                                 f'<b>{req_type.title()}:</b> %{{y:.0f}} requests<br>' +
                                 '<extra></extra>'
                )
            )

    # Plot rejections
    if not rejected_df.empty:
        # Use the 'type' column as the rejection reason
        if 'type' not in rejected_df.columns:
            rejected_df['reason'] = 'unknown'
        else:
            rejected_df['reason'] = rejected_df['type']

        rejection_colors = {
            'circuit_breaker_open': '#ff00ff',  # Magenta
            'queue_full': '#ff8800',           # Orange
        }

        for reason in ['circuit_breaker_open', 'queue_full']:
            reason_df = rejected_df[rejected_df['reason'] == reason].copy()
            if not reason_df.empty:
                reason_df = reason_df.sort_values('sim_time')

                fig.add_trace(
                    go.Scatter(
                        x=reason_df['sim_time'],
                        y=reason_df['value'],
                        name=f'Rejected ({reason.replace("_", " ").title()})',
                        mode='lines',
                        line=dict(color=rejection_colors.get(reason, '#ffffff'), width=2, dash='dash'),
                        hovertemplate=f'<b>Time:</b> %{{x}}s<br>' +
                                     f'<b>Rejected ({reason}):</b> %{{y:.0f}} requests<br>' +
                                     '<extra></extra>'
                    )
                )

    # Add fault injection and removal markers
    add_fault_markers_with_shading(fig, label_data)

    fig.update_layout(
        template='plotly_dark',
        hovermode='x unified',
        height=400,
        xaxis_title="Simulation Time (seconds)",
        yaxis_title="Requests",
        yaxis=dict(rangemode='tozero'),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=80, b=60),
        annotations=[
            dict(
                text="🔴 Red line = Fault Injection | 🟢 Green line = Fault Removal",
                xref="paper", yref="paper",
                x=0.5, y=1.12,
                showarrow=False,
                font=dict(size=11, color="#9ca3af"),
                xanchor="center"
            )
        ]
    )

    return fig


def create_workload_dashboard(metrics_df: pd.DataFrame, label_data: Dict):
    """
    Create a complete workload generator dashboard with all charts.

    Returns a Dash HTML component with all workload visualizations.
    """
    from dash import dcc, html
    import dash_bootstrap_components as dbc

    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H3("🔌 Workload Generator Behavior", className="text-info mb-3"),
                html.P([
                    "These metrics show the workload generator's behavior and protective mechanisms. ",
                    "High connection pool utilization or an open circuit breaker indicates the system ",
                    "was unable to handle the load (either due to failures or slowness)."
                ], className="text-muted")
            ], width=12)
        ]),

        # Connection Pool
        dbc.Row([
            dbc.Col([
                dcc.Graph(
                    figure=create_connection_pool_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ], className="mb-4"),

        # Circuit Breaker
        dbc.Row([
            dbc.Col([
                html.H5("Circuit Breaker State", className="text-info mb-2"),
                html.P([
                    "CLOSED = Normal operation | ",
                    "OPEN = High failure rate detected, rejecting requests | ",
                    "HALF_OPEN = Testing recovery"
                ], className="text-muted small"),
                dcc.Graph(
                    figure=create_circuit_breaker_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ], className="mb-4"),

        # Request Outcomes
        dbc.Row([
            dbc.Col([
                html.H5("Request Outcomes", className="text-info mb-2"),
                html.P([
                    "Shows successful requests, failures, timeouts, and rejections over time. ",
                    "Stacked area shows how outcomes change during faults."
                ], className="text-muted small"),
                dcc.Graph(
                    figure=create_request_outcomes_chart(metrics_df, label_data),
                    config={'displayModeBar': False}
                )
            ], width=12)
        ])
    ])
