"""
RCA Failure Analysis Chart Module

Creates visualizations for RCA failure analysis results.
"""

import sys
from pathlib import Path
from typing import Dict, Optional
import dash_bootstrap_components as dbc
from dash import html, dcc
import plotly.graph_objects as go

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def create_failure_analysis_view(episode_dir: str, failure_result: Dict) -> dbc.Card:
    """
    Create a comprehensive failure analysis visualization.

    Args:
        episode_dir: Path to episode directory
        failure_result: Output from FailureAnalyzer.analyze()

    Returns:
        Dash Bootstrap Card with failure analysis
    """

    # Extract key data
    dataset_dir = failure_result.get('dataset_dir', 'Unknown')
    episode_name = failure_result.get('episode_name', 'Unknown')
    ground_truth = failure_result['ground_truth']
    fault_type = failure_result['fault_type']
    detected = failure_result['ground_truth_detected']
    rank = failure_result.get('ground_truth_rank')
    top_3 = failure_result['top_3_candidates']

    # Get analysis results
    gt_metrics = failure_result['ground_truth_metrics']
    topology = failure_result['topology']
    temporal_ordering = failure_result.get('temporal_ordering', {})
    fault_injection = failure_result.get('fault_injection_severity', {})
    hypotheses = failure_result.get('root_cause_hypothesis', [])

    # Create header alert
    if detected:
        header_alert = dbc.Alert([
            html.H5("✅ Ground Truth Detected", className="alert-heading"),
            html.P(f"Ground truth '{ground_truth}' was found at rank {rank}, but not in top-K", className="mb-0")
        ], color="warning")
    else:
        header_alert = dbc.Alert([
            html.H5("❌ Ground Truth Not Detected", className="alert-heading"),
            html.P(f"Ground truth '{ground_truth}' was not detected in top candidates", className="mb-0")
        ], color="danger")

    # Create overview section
    overview_section = dbc.Card([
        dbc.CardHeader(html.H6("📊 Overview")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Strong("Dataset: "), html.Span(dataset_dir)
                ], width=6),
                dbc.Col([
                    html.Strong("Episode: "), html.Span(episode_name)
                ], width=6),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Strong("Ground Truth: "),
                    html.Span(ground_truth, style={'color': 'red', 'fontWeight': 'bold'})
                ], width=6),
                dbc.Col([
                    html.Strong("Fault Type: "), html.Span(fault_type)
                ], width=6),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Strong("Node Type: "),
                    html.Span(topology.get('ground_truth_type', 'Unknown'))
                ], width=6),
                dbc.Col([
                    html.Strong("Is Leaf: "),
                    html.Span("Yes" if topology.get('is_leaf_node') else "No")
                ], width=6),
            ])
        ])
    ], className="mb-3")

    # Top 3 candidates
    candidates_section = dbc.Card([
        dbc.CardHeader(html.H6("🥇 Top 3 Candidates Found")),
        dbc.CardBody([
            html.Ol([
                html.Li(candidate, style={'fontFamily': 'monospace', 'fontSize': '1.1em'})
                for candidate in top_3
            ])
        ])
    ], className="mb-3")

    # Ground truth metrics
    gt_metrics_section = _create_gt_metrics_section(gt_metrics)

    # Temporal ordering check
    temporal_section = _create_temporal_section(temporal_ordering)

    # Fault injection severity check
    injection_section = _create_injection_section(fault_injection)

    # Hypotheses
    hypotheses_section = _create_hypotheses_section(hypotheses)

    # Create the full card
    return dbc.Card([
        dbc.CardHeader([
            html.H4("🔍 RCA Failure Analysis", className="mb-0 d-inline-block"),
            dbc.Badge(f"{dataset_dir}/{episode_name}", color="info", className="float-end")
        ]),
        dbc.CardBody([
            header_alert,
            overview_section,
            candidates_section,
            dbc.Row([
                dbc.Col([gt_metrics_section], width=6),
                dbc.Col([
                    temporal_section,
                    injection_section
                ], width=6),
            ]),
            hypotheses_section
        ])
    ], className="shadow-sm")


def _create_gt_metrics_section(gt_metrics: Dict) -> dbc.Card:
    """Create ground truth metrics section."""

    if not gt_metrics.get('found'):
        return dbc.Card([
            dbc.CardHeader(html.H6("📉 Ground Truth Metrics")),
            dbc.CardBody([
                dbc.Alert([
                    html.Strong("❌ Ground truth node was not analyzed"),
                    html.Br(),
                    html.Small(gt_metrics.get('reason', 'Unknown reason'))
                ], color="danger")
            ])
        ], className="mb-3")

    severity = gt_metrics.get('overall_severity_score', 0)
    health = gt_metrics.get('health_status', 'UNKNOWN')
    critical_metrics = gt_metrics.get('critical_metrics', 0)
    high_metrics = gt_metrics.get('high_metrics', 0)
    top_metrics = gt_metrics.get('top_impacted_metrics', [])

    # Color code health status
    health_colors = {
        'HEALTHY': 'success',
        'DEGRADED': 'warning',
        'IMPACTED': 'warning',
        'CRITICAL': 'danger',
        'UNKNOWN': 'secondary'
    }
    health_color = health_colors.get(health, 'secondary')

    # Severity gauge
    severity_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=severity,
        title={'text': "Severity Score"},
        gauge={
            'axis': {'range': [0, 1]},
            'bar': {'color': "darkred" if severity > 0.7 else "orange" if severity > 0.4 else "green"},
            'steps': [
                {'range': [0, 0.3], 'color': "lightgray"},
                {'range': [0.3, 0.7], 'color': "gray"},
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 0.5
            }
        }
    ))
    severity_fig.update_layout(height=200, margin=dict(l=20, r=20, t=40, b=20))

    return dbc.Card([
        dbc.CardHeader(html.H6("📉 Ground Truth Metrics")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dcc.Graph(figure=severity_fig, config={'displayModeBar': False})
                ], width=6),
                dbc.Col([
                    html.Div([
                        html.Strong("Health: "),
                        dbc.Badge(health, color=health_color, className="ms-2"),
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("Critical Metrics: "),
                        html.Span(str(critical_metrics))
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("High Metrics: "),
                        html.Span(str(high_metrics))
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("First Impact: "),
                        html.Span(f"{gt_metrics.get('first_impact_time', 'N/A')}s" if gt_metrics.get('first_impact_time') else "N/A")
                    ])
                ], width=6)
            ]),
            html.Hr(),
            html.Div([
                html.Strong("Top Impacted Metrics:"),
                html.Ul([
                    html.Li([
                        html.Code(m['name']),
                        html.Span(f" - {m['severity']}",
                                 style={'color': 'red' if m['severity'] == 'CRITICAL' else 'orange'})
                    ])
                    for m in top_metrics[:5]
                ] if top_metrics else [html.Li("No metrics available")])
            ])
        ])
    ], className="mb-3")


def _create_temporal_section(temporal: Dict) -> dbc.Card:
    """Create temporal ordering section."""

    if temporal.get('error'):
        return dbc.Card([
            dbc.CardHeader(html.H6("⏱️ Temporal Ordering")),
            dbc.CardBody([
                dbc.Alert(f"❌ {temporal['error']}", color="danger")
            ])
        ], className="mb-3")

    valid = temporal.get('valid', False)
    violations = temporal.get('violations', [])
    gt_impact_time = temporal.get('gt_impact_time')
    dependents_count = temporal.get('dependents_count', 0)

    if valid:
        content = dbc.Alert([
            html.Strong("✅ Temporal Ordering Valid"),
            html.Br(),
            html.Small(f"Ground truth was impacted first at {gt_impact_time:.1f}s"),
            html.Br(),
            html.Small(f"All {dependents_count} dependents were impacted after")
        ], color="success")
    else:
        content = [
            dbc.Alert([
                html.Strong("❌ Temporal Ordering VIOLATED"),
                html.Br(),
                html.Small(f"{len(violations)} dependent(s) impacted BEFORE ground truth")
            ], color="danger"),
            html.Div([
                html.Strong("Violations:"),
                html.Ul([
                    html.Li([
                        html.Code(v['node']),
                        html.Span(f" impacted {v['delta']:.1f}s before ground truth")
                    ])
                    for v in violations[:3]
                ])
            ])
        ]

    return dbc.Card([
        dbc.CardHeader(html.H6("⏱️ Temporal Ordering Check")),
        dbc.CardBody(content)
    ], className="mb-3")


def _create_injection_section(injection: Dict) -> dbc.Card:
    """Create fault injection severity section."""

    if injection.get('error'):
        return dbc.Card([
            dbc.CardHeader(html.H6("💉 Fault Injection Severity")),
            dbc.CardBody([
                dbc.Alert(f"❌ {injection['error']}", color="danger")
            ])
        ], className="mb-3")

    adequate = injection.get('adequate', False)
    severity_score = injection.get('severity_score', 0)
    health_status = injection.get('health_status', 'UNKNOWN')
    critical_metrics = injection.get('critical_metrics', 0)
    high_metrics = injection.get('high_metrics', 0)
    issues = injection.get('issues', [])

    if adequate:
        content = dbc.Alert([
            html.Strong("✅ Fault Injection Adequate"),
            html.Br(),
            html.Small(f"Severity: {severity_score:.3f}, Health: {health_status}"),
            html.Br(),
            html.Small(f"{critical_metrics} critical + {high_metrics} high metrics")
        ], color="success")
    else:
        content = [
            dbc.Alert([
                html.Strong("❌ Fault Injection TOO WEAK"),
                html.Br(),
                html.Small(f"Severity: {severity_score:.3f}, Health: {health_status}")
            ], color="danger"),
            html.Div([
                html.Strong("Issues Detected:"),
                html.Ul([
                    html.Li(issue, style={'fontSize': '0.9em'})
                    for issue in issues
                ])
            ])
        ]

    return dbc.Card([
        dbc.CardHeader(html.H6("💉 Fault Injection Check")),
        dbc.CardBody(content)
    ], className="mb-3")


def _create_hypotheses_section(hypotheses: list) -> dbc.Card:
    """Create hypotheses section."""

    if not hypotheses:
        content = html.P("No hypotheses generated.", className="text-muted")
    else:
        content = html.Ol([
            html.Li(
                html.Div(hypothesis, style={'whiteSpace': 'pre-wrap'}),
                className="mb-3"
            )
            for hypothesis in hypotheses
        ])

    return dbc.Card([
        dbc.CardHeader(html.H6("💡 Why RCA Failed - Hypotheses")),
        dbc.CardBody(content)
    ], className="mb-3")


def create_rca_not_run_message() -> dbc.Alert:
    """Create message when RCA hasn't been run yet."""
    return dbc.Alert([
        html.H5("⚠️ RCA Not Run Yet", className="alert-heading"),
        html.Hr(),
        html.P("This episode has not been analyzed with RCA Discovery mode yet."),
        html.P("The failure analysis requires RCA to be run first to detect root causes."),
        html.P([
            html.Strong("What will happen:"),
            html.Br(),
            "1. RCA Discovery mode will be run automatically",
            html.Br(),
            "2. Results will be validated against ground truth",
            html.Br(),
            "3. Failure analysis will be performed if RCA failed",
            html.Br(),
            "4. Results will be displayed on this panel"
        ]),
    ], color="warning")


def create_rca_success_message(ground_truth: str, rank: int) -> dbc.Alert:
    """Create message when RCA succeeded."""
    return dbc.Alert([
        html.H5("✅ RCA Succeeded!", className="alert-heading"),
        html.Hr(),
        html.P(f"Ground truth '{ground_truth}' was successfully detected at rank {rank}."),
        html.P("No failure analysis needed - RCA is working correctly for this case.")
    ], color="success")
