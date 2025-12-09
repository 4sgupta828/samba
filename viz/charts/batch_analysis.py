"""
Batch RCA Analysis Visualization

Displays comprehensive analysis of RCA failures across a batch run.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc
from typing import Dict, List


def create_batch_analysis_summary(results: List[Dict]) -> html.Div:
    """
    Create summary statistics view for batch analysis.

    Args:
        results: List of failure analysis results from analyze_failures.py

    Returns:
        Dash HTML div with summary statistics
    """
    if not results:
        return html.Div([
            dbc.Alert("No failures found in this batch run!", color="success", className="mt-3")
        ])

    total = len(results)

    # Calculate statistics
    detected = sum(1 for r in results if r.get('ground_truth_detected', False))
    temporal_violations = sum(
        1 for r in results
        if r.get('temporal_ordering', {}).get('valid') == False
    )
    weak_injection = sum(
        1 for r in results
        if r.get('fault_injection_severity', {}).get('adequate') == False
    )
    service_faults = sum(
        1 for r in results
        if 'service' in r.get('topology', {}).get('ground_truth_type', '').lower()
    )
    low_severity = sum(
        1 for r in results
        if r.get('ground_truth_metrics', {}).get('found')
        and r.get('ground_truth_metrics', {}).get('overall_severity_score', 0) < 0.1
    )

    # Fault type distribution
    from collections import Counter
    fault_types = Counter(r.get('fault_type', 'Unknown') for r in results)
    datasets = Counter(r.get('dataset_dir', 'Unknown') for r in results)

    summary_cards = dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(str(total), className="text-danger"),
                    html.P("Total Failures", className="mb-0 text-muted")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(f"{detected}/{total}", className="text-warning"),
                    html.P("GT Detected (not top-K)", className="mb-0 text-muted small")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(f"{temporal_violations}", className="text-danger"),
                    html.P("Temporal Violations", className="mb-0 text-muted small")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(f"{weak_injection}", className="text-warning"),
                    html.P("Weak Fault Injection", className="mb-0 text-muted small")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(f"{service_faults}", className="text-info"),
                    html.P("Service-Level Faults", className="mb-0 text-muted small")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H3(f"{low_severity}", className="text-secondary"),
                    html.P("Low Severity (<0.1)", className="mb-0 text-muted small")
                ])
            ], className="text-center shadow-sm")
        ], width=2),
    ], className="mb-4")

    # Fault type breakdown
    fault_type_rows = [
        html.Tr([
            html.Td(ft),
            html.Td(count, className="text-end"),
            html.Td(f"{count/total*100:.1f}%", className="text-end text-muted")
        ])
        for ft, count in fault_types.most_common()
    ]

    fault_type_table = dbc.Table([
        html.Thead([
            html.Tr([
                html.Th("Fault Type"),
                html.Th("Count", className="text-end"),
                html.Th("Percentage", className="text-end")
            ])
        ]),
        html.Tbody(fault_type_rows)
    ], bordered=True, hover=True, size="sm", className="mb-3")

    # Dataset breakdown
    dataset_rows = [
        html.Tr([
            html.Td(dataset),
            html.Td(count, className="text-end"),
        ])
        for dataset, count in datasets.most_common()
    ]

    dataset_table = dbc.Table([
        html.Thead([
            html.Tr([
                html.Th("Dataset Directory"),
                html.Th("Failures", className="text-end")
            ])
        ]),
        html.Tbody(dataset_rows)
    ], bordered=True, hover=True, size="sm", className="mb-3")

    return html.Div([
        html.H4("📊 Batch Analysis Summary", className="mb-3"),
        summary_cards,
        dbc.Row([
            dbc.Col([
                html.H5("Failures by Fault Type", className="mb-2"),
                fault_type_table
            ], width=6),
            dbc.Col([
                html.H5("Failures by Dataset", className="mb-2"),
                dataset_table
            ], width=6)
        ])
    ])


def create_batch_failure_details(results: List[Dict]) -> html.Div:
    """
    Create detailed view of individual failures.

    Args:
        results: List of failure analysis results from analyze_failures.py

    Returns:
        Dash HTML div with individual failure details
    """
    if not results:
        return html.Div()

    failure_cards = []

    for i, result in enumerate(results, 1):
        # Build hypothesis list
        hypotheses = result.get('root_cause_hypothesis', [])
        hypothesis_items = [
            html.Li(h, className="mb-2 small") for h in hypotheses
        ]

        # Ground truth metrics
        gt_metrics = result.get('ground_truth_metrics', {})
        severity_score = gt_metrics.get('overall_severity_score', 0) if gt_metrics.get('found') else 0
        health_status = gt_metrics.get('health_status', 'UNKNOWN') if gt_metrics.get('found') else 'NOT ANALYZED'

        # Topology info
        topo = result.get('topology', {})

        # Create clickable link to load episode
        dataset_dir = result.get('dataset_dir', 'Unknown')
        episode_name = result.get('episode_name', 'Unknown')

        failure_card = dbc.Card([
            dbc.CardHeader([
                html.H6([
                    f"Failure #{i}: ",
                    html.Span(f"{dataset_dir}/{episode_name}", className="text-primary"),
                    html.Span(f" - {result.get('fault_type', 'Unknown')}", className="ms-2 text-muted")
                ], className="mb-0")
            ]),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Strong("Ground Truth: "),
                        html.Span(result.get('ground_truth', 'Unknown'), className="text-danger"),
                        html.Br(),
                        html.Strong("Type: "),
                        html.Span(f"{topo.get('ground_truth_type', 'Unknown')} ({topo.get('ground_truth_role', 'Unknown')})"),
                        html.Br(),
                        html.Strong("Topology: "),
                        html.Span(f"{topo.get('total_nodes', 0)} nodes, Leaf: {topo.get('is_leaf_node', False)}"),
                    ], width=4),
                    dbc.Col([
                        html.Strong("Top 3 Candidates: "),
                        html.Ul([
                            html.Li(candidate) for candidate in result.get('top_3_candidates', [])
                        ], className="mb-0 small")
                    ], width=4),
                    dbc.Col([
                        html.Strong("Metrics: "),
                        html.Br(),
                        html.Span(f"Severity: {severity_score:.3f}", className="small"),
                        html.Br(),
                        html.Span(f"Health: {health_status}", className="small"),
                        html.Br(),
                        html.Span(f"GT Detected: {'Yes' if result.get('ground_truth_detected') else 'No'}", className="small"),
                        html.Br(),
                        html.A(
                            dbc.Button(
                                "🔍 Open Episode",
                                color="primary",
                                size="sm",
                                className="mt-2"
                            ),
                            href=f"/?scope=batch_run&datarun={dataset_dir}&episode={episode_name}",
                            target="_blank",
                            style={'textDecoration': 'none'}
                        )
                    ], width=4)
                ]),
                html.Hr(className="my-2"),
                html.Div([
                    html.Strong("Why RCA Failed (Hypotheses):"),
                    html.Ul(hypothesis_items, className="mb-0 mt-2")
                ])
            ])
        ], className="mb-3 shadow-sm")

        failure_cards.append(failure_card)

    return html.Div([
        html.H4(f"📋 Individual Failure Details ({len(results)} cases)", className="mb-3 mt-4"),
        html.Div(failure_cards)
    ])


def create_batch_analysis_view(results: List[Dict]) -> html.Div:
    """
    Create complete batch analysis view combining summary and details.

    Args:
        results: List of failure analysis results from analyze_failures.py

    Returns:
        Complete batch analysis dashboard
    """
    if not results:
        return html.Div([
            dbc.Alert([
                html.H5("✅ No RCA Failures Found!", className="alert-heading"),
                html.P("All RCA cases in this batch run succeeded. Great job!")
            ], color="success", className="mt-3")
        ])

    return html.Div([
        create_batch_analysis_summary(results),
        html.Hr(),
        create_batch_failure_details(results)
    ])
