"""
Batch RCA Analysis Visualization

Displays comprehensive analysis of RCA results across a batch run.
Shows both successful (rank=1) and failed (rank!=1) RCA cases.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc
from typing import Dict, List


def create_batch_analysis_summary(all_results: List[Dict], successful_results: List[Dict], failed_results: List[Dict]) -> html.Div:
    """
    Create summary statistics view for batch analysis.

    Args:
        all_results: All RCA results
        successful_results: Successful RCA cases (rank=1)
        failed_results: Failed RCA cases (rank!=1)

    Returns:
        Dash HTML div with summary statistics
    """
    if not all_results:
        return html.Div([
            dbc.Alert("No RCA results found in this batch run!", color="info", className="mt-3")
        ])

    total = len(all_results)
    success_count = len(successful_results)
    fail_count = len(failed_results)
    success_rate = (success_count / total * 100) if total > 0 else 0

    # Calculate statistics
    found_in_top_k = sum(1 for r in all_results if r.get('found_in_top_k', False))

    # Ground truth validation statistics
    gt_valid_count = sum(1 for r in all_results if r.get('ground_truth_validation', {}).get('is_valid', False))
    gt_invalid_count = total - gt_valid_count
    gt_valid_rate = (gt_valid_count / total * 100) if total > 0 else 0

    # Rank distribution for failures
    rank_2 = sum(1 for r in failed_results if r.get('rank') == 2)
    rank_3 = sum(1 for r in failed_results if r.get('rank') == 3)
    rank_4_plus = sum(1 for r in failed_results if r.get('rank') and r.get('rank') >= 4)
    not_in_top_k = sum(1 for r in failed_results if not r.get('found_in_top_k', False))

    # Fault type distribution
    from collections import Counter
    fault_types = Counter(r.get('fault_type', 'Unknown') for r in all_results)
    datasets = Counter(r.get('dataset_dir', 'Unknown') for r in all_results)

    summary_cards = html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(str(total), className="text-primary"),
                        html.P("Total Episodes", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{success_count}", className="text-success"),
                        html.P(f"Rank 1 ({success_rate:.1f}%)", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{fail_count}", className="text-danger"),
                        html.P(f"Failures ({100-success_rate:.1f}%)", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{found_in_top_k}/{total}", className="text-info"),
                        html.P("In Top-K", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{not_in_top_k}", className="text-warning"),
                        html.P("Not in Top-K", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{rank_2 + rank_3}", className="text-secondary"),
                        html.P("Rank 2-3", className="mb-0 text-muted small")
                    ])
                ], className="text-center shadow-sm")
            ], width=2),
        ], className="mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("Ground Truth Validation", className="mb-2 text-center"),
                        dbc.Row([
                            dbc.Col([
                                html.H4(f"{gt_valid_count}", className="text-success mb-0"),
                                html.P(f"Valid ({gt_valid_rate:.1f}%)", className="mb-0 text-muted small")
                            ], width=6, className="text-center"),
                            dbc.Col([
                                html.H4(f"{gt_invalid_count}", className="text-danger mb-0"),
                                html.P(f"Invalid ({100-gt_valid_rate:.1f}%)", className="mb-0 text-muted small")
                            ], width=6, className="text-center")
                        ])
                    ])
                ], className="shadow-sm", color="light")
            ], width=12)
        ], className="mb-3")
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
                html.Th("Count", className="text-end")
            ])
        ]),
        html.Tbody(dataset_rows)
    ], bordered=True, hover=True, size="sm", className="mb-3")

    return html.Div([
        html.H4("📊 Batch RCA Analysis Summary", className="mb-3"),
        summary_cards,
        dbc.Row([
            dbc.Col([
                html.H5("Distribution by Fault Type", className="mb-2"),
                fault_type_table
            ], width=6),
            dbc.Col([
                html.H5("Distribution by Dataset", className="mb-2"),
                dataset_table
            ], width=6)
        ])
    ])


def create_episode_card(result: Dict, index: int, is_success: bool) -> dbc.Card:
    """
    Create a card for a single episode result.

    Args:
        result: Episode result dictionary
        index: Episode number
        is_success: Whether this is a successful RCA (rank=1)

    Returns:
        Dash bootstrap card component
    """
    dataset_dir = result.get('dataset_dir', 'Unknown')
    episode_name = result.get('episode_name', 'Unknown')
    ground_truth = result.get('ground_truth', 'Unknown')
    fault_type = result.get('fault_type', 'Unknown')
    rank = result.get('rank', 'N/A')
    found_in_top_k = result.get('found_in_top_k', False)
    top_candidates = result.get('top_candidates', [])

    # Ground truth validation
    gt_validation = result.get('ground_truth_validation', {})
    gt_is_valid = gt_validation.get('is_valid', False)
    gt_confidence = gt_validation.get('confidence', 'N/A')
    gt_evidence_score = gt_validation.get('evidence_score', 0)
    gt_max_evidence = gt_validation.get('max_evidence_score', 12)

    # Determine status badge
    if is_success:
        status_badge = dbc.Badge("✓ Rank 1", color="success", className="ms-2")
        card_color = "success"
        header_class = "text-success"
    elif found_in_top_k:
        status_badge = dbc.Badge(f"Rank {rank}", color="warning", className="ms-2")
        card_color = "warning"
        header_class = "text-warning"
    else:
        status_badge = dbc.Badge(f"Not in Top-K", color="danger", className="ms-2")
        card_color = "danger"
        header_class = "text-danger"

    # Build top candidates list
    candidate_items = []
    for i, candidate in enumerate(top_candidates[:5], 1):
        node = candidate.get('node', 'Unknown')
        score = candidate.get('score', 0)
        is_gt = (node == ground_truth)

        # Create label with score breakdown
        score_parts = []
        if 'self_score' in candidate:
            score_parts.append(f"self={candidate['self_score']:.1f}")
        if 'integrated_score' in candidate:
            score_parts.append(f"int={candidate['integrated_score']:.1f}")
        if 'guilt_ratio' in candidate and candidate['guilt_ratio'] is not None:
            score_parts.append(f"guilt={candidate['guilt_ratio']:.1f}")
        if 'temporal_score' in candidate:
            score_parts.append(f"temp={candidate['temporal_score']:.1f}")

        score_str = f" ({', '.join(score_parts)})" if score_parts else ""

        item = html.Li([
            html.Strong(f"#{i}: {node}", className="text-success" if is_gt else ""),
            f" - Score: {score:.1f}{score_str}",
            html.Span(" ← Ground Truth", className="text-success ms-2") if is_gt else ""
        ], className="small")
        candidate_items.append(item)

    return dbc.Card([
        dbc.CardHeader([
            html.H6([
                f"#{index}: ",
                html.Span(f"{dataset_dir}/{episode_name}", className=header_class),
                status_badge,
                html.Span(f" - {fault_type}", className="ms-2 text-muted small")
            ], className="mb-0")
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Strong("Ground Truth: "),
                    html.Span(ground_truth, className="text-danger"),
                    html.Br(),
                    html.Strong("GT Validation: "),
                    dbc.Badge(
                        "Valid" if gt_is_valid else "Invalid",
                        color="success" if gt_is_valid else "danger",
                        className="me-1"
                    ),
                    html.Span(f"({gt_confidence}, {gt_evidence_score}/{gt_max_evidence})", className="small text-muted"),
                    html.Br(),
                    html.Strong("Rank: "),
                    html.Span(str(rank)),
                    html.Br(),
                    html.Strong("Total Candidates: "),
                    html.Span(str(result.get('total_candidates', 0))),
                ], width=4),
                dbc.Col([
                    html.Strong("Top 5 Candidates:"),
                    html.Ul(candidate_items, className="mb-0 mt-1")
                ], width=5),
                dbc.Col([
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
                ], width=3, className="text-center")
            ])
        ])
    ], className="mb-3 shadow-sm", color=card_color, outline=True)


def create_batch_results_details(successful_results: List[Dict], failed_results: List[Dict]) -> html.Div:
    """
    Create detailed view of both successful and failed RCA cases.

    Args:
        successful_results: List of successful RCA cases (rank=1)
        failed_results: List of failed RCA cases (rank!=1)

    Returns:
        Dash HTML div with detailed results
    """
    components = []

    # Successful cases section
    if successful_results:
        success_cards = [
            create_episode_card(result, i, is_success=True)
            for i, result in enumerate(successful_results, 1)
        ]
        components.append(html.Div([
            dbc.Collapse([
                html.H5(f"✅ Successful RCA Cases ({len(successful_results)})", className="mb-3 mt-4 text-success"),
                html.Div(success_cards)
            ], id="successful-cases-collapse", is_open=False),
            dbc.Button(
                f"Toggle Successful Cases ({len(successful_results)})",
                id="toggle-successful-button",
                color="success",
                size="sm",
                className="mb-3 mt-3"
            )
        ]))

    # Failed cases section
    if failed_results:
        failure_cards = [
            create_episode_card(result, i, is_success=False)
            for i, result in enumerate(failed_results, 1)
        ]
        components.append(html.Div([
            html.H5(f"❌ Failed RCA Cases ({len(failed_results)})", className="mb-3 mt-4 text-danger"),
            html.Div(failure_cards)
        ]))

    if not components:
        return html.Div()

    return html.Div(components)


def create_batch_analysis_view(all_results: List[Dict], successful_results: List[Dict], failed_results: List[Dict]) -> html.Div:
    """
    Create complete batch analysis view combining summary and details.

    Args:
        all_results: All RCA results
        successful_results: Successful RCA cases (rank=1)
        failed_results: Failed RCA cases (rank!=1)

    Returns:
        Complete batch analysis dashboard
    """
    if not all_results:
        return html.Div([
            dbc.Alert([
                html.H5("📂 No RCA Results Found!", className="alert-heading"),
                html.P("No rca_analysis.json files found in this batch.")
            ], color="info", className="mt-3")
        ])

    return html.Div([
        create_batch_analysis_summary(all_results, successful_results, failed_results),
        html.Hr(),
        create_batch_results_details(successful_results, failed_results)
    ])
