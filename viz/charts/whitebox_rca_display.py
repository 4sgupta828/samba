"""
Whitebox RCA Analysis Display

Comprehensive display of whitebox RCA analysis results including rankings,
scores, symptoms, and root cause story.
"""

import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dash import html
import dash_bootstrap_components as dbc


def create_whitebox_rca_display(episode_dir):
    """
    Create comprehensive whitebox RCA analysis display from pre-computed analysis.

    Loads and displays the existing whitebox_rca.json file with all details.

    Args:
        episode_dir: Path to episode directory

    Returns:
        Dash HTML layout with RCA analysis visualization
    """
    try:
        print(f"Loading whitebox RCA analysis from {episode_dir}")

        # Load the pre-computed whitebox RCA analysis
        rca_path = os.path.join(episode_dir, 'rca_analysis.json')

        if not os.path.exists(rca_path):
            return html.Div([
                dbc.Alert([
                    html.H4("No Whitebox RCA Analysis Found", className="alert-heading"),
                    html.P(f"No rca_analysis.json found in {episode_dir}"),
                    html.Hr(),
                    html.P("This episode may have been generated without whitebox RCA analysis enabled.",
                           className="mb-0")
                ], color="warning")
            ])

        with open(rca_path, 'r') as f:
            rca_data = json.load(f)

        print("  ✓ RCA data loaded!")

        # Handle both old and new formats
        # Old format: {'top_candidates': [...], 'all_candidates': [...], 'ground_truth': '...', 'rank': N, 'found_in_top_k': bool}
        # New format: {'rankings': [...], 'ground_truth': '...', 'fault_start_time': N}

        if 'rankings' in rca_data:
            # New format from generate_dataset.py
            rankings = rca_data.get('rankings', [])
            ground_truth = rca_data.get('ground_truth', 'Unknown')
            fault_start_time = rca_data.get('fault_start_time', 0)
        elif 'all_candidates' in rca_data:
            # Old format from run_rca_batch.py
            rankings = rca_data.get('all_candidates', [])
            ground_truth = rca_data.get('ground_truth', 'Unknown')
            fault_start_time = 0  # Not available in old format
        else:
            # Fallback - try top_candidates
            rankings = rca_data.get('top_candidates', [])
            ground_truth = rca_data.get('ground_truth', 'Unknown')
            fault_start_time = 0

        if not rankings:
            return html.Div([
                dbc.Alert([
                    html.H4("No RCA Results", className="alert-heading"),
                    html.P("The whitebox RCA analysis found no results."),
                ], color="info")
            ])

        # Load label for additional context
        label_path = os.path.join(episode_dir, 'label.json')
        fault_type = "Unknown"
        fault_role = "Unknown"
        if os.path.exists(label_path):
            with open(label_path, 'r') as f:
                label_data = json.load(f)
                fault_type = label_data.get('fault_type', 'Unknown')
                fault_role = label_data.get('root_cause_component_type', 'Unknown')

        # Find rank of ground truth
        top_k_nodes = [r['node'] for r in rankings[:10]]
        if ground_truth in top_k_nodes:
            gt_rank = top_k_nodes.index(ground_truth) + 1
            rank_status = "success" if gt_rank == 1 else "warning"
        else:
            gt_rank = ">10"
            rank_status = "danger"

        # Top result
        top_result = rankings[0]
        top_node = top_result['node']
        top_score = top_result['score']

        # Create summary cards
        summary_cards = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("🎯 Ground Truth", className="text-muted mb-2 small"),
                        html.H4(ground_truth, className="text-danger mb-0"),
                        html.P(f"Type: {fault_role}", className="text-muted small mb-0")
                    ])
                ], className="text-center shadow-sm h-100")
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("🔍 Top Prediction", className="text-muted mb-2 small"),
                        html.H4(top_node, className="text-primary mb-0"),
                        html.P(f"Score: {top_score:.1f}", className="text-muted small mb-0")
                    ])
                ], className="text-center shadow-sm h-100")
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("📊 GT Rank", className="text-muted mb-2 small"),
                        html.H4(str(gt_rank), className=f"text-{rank_status} mb-0"),
                        html.P(f"Out of {len(rankings)} nodes", className="text-muted small mb-0")
                    ])
                ], className="text-center shadow-sm h-100")
            ], width=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("⚠️ Fault Type", className="text-muted mb-2 small"),
                        html.H4(fault_type.replace('_', ' ').title(), className="text-warning mb-0",
                               style={'fontSize': '1.2em'}),
                        html.P(f"Start: {fault_start_time:.1f}s", className="text-muted small mb-0")
                    ])
                ], className="text-center shadow-sm h-100")
            ], width=3),
        ], className="mb-4")

        # Create detailed ranking cards
        ranking_cards = []
        for i, result in enumerate(rankings[:10], 1):  # Top 10
            node = result['node']
            score = result['score']
            symptoms = result.get('symptoms', [])
            story = result.get('story', [])

            # Score breakdown
            integrated_score = result.get('integrated_score', 0)
            self_score = result.get('self_score', 0)
            guilt_raw = result.get('guilt_raw', 0)
            guilt_adjusted = result.get('guilt_adjusted', 0)
            temporal_score = result.get('temporal_score', 0)
            trace_score = result.get('trace_score', 0)
            blamed_by = result.get('blamed_by', [])
            is_trace_authoritative = result.get('is_trace_authoritative', False)

            # Health metadata
            health_metadata = result.get('health_metadata', {})
            pod_score = health_metadata.get('pod_score', 0)
            coverage = health_metadata.get('coverage', 0)
            pattern = health_metadata.get('pattern', 'N/A')

            # Determine card color
            is_ground_truth = (node == ground_truth)
            if is_ground_truth:
                card_color = "success"
                header_class = "bg-success text-white"
            elif i == 1:
                card_color = "primary"
                header_class = "bg-primary text-white"
            else:
                card_color = "light"
                header_class = "bg-light"

            # Build score breakdown
            score_breakdown = dbc.Table([
                html.Tbody([
                    html.Tr([
                        html.Td("Final Score:", className="fw-bold"),
                        html.Td(f"{score:.1f}", className="text-end fw-bold")
                    ]),
                    html.Tr([
                        html.Td("├─ Integrated Health:", style={'paddingLeft': '20px'}),
                        html.Td(f"{integrated_score:.1f}", className="text-end")
                    ]),
                    html.Tr([
                        html.Td("│  ├─ Service Self:", style={'paddingLeft': '40px'}),
                        html.Td(f"{self_score:.1f}", className="text-end small text-muted")
                    ]),
                    html.Tr([
                        html.Td("│  └─ Pod Health:", style={'paddingLeft': '40px'}),
                        html.Td(f"{pod_score:.1f} (cov: {coverage:.1%})", className="text-end small text-muted")
                    ]) if pod_score > 0 else None,
                    html.Tr([
                        html.Td("├─ Guilt (External):", style={'paddingLeft': '20px'}),
                        html.Td(f"{guilt_adjusted:.1f} (raw: {guilt_raw:.1f})", className="text-end")
                    ]),
                    html.Tr([
                        html.Td("├─ Temporal:", style={'paddingLeft': '20px'}),
                        html.Td(f"{temporal_score:.1f}", className="text-end")
                    ]),
                    html.Tr([
                        html.Td("└─ Trace:", style={'paddingLeft': '20px'}),
                        html.Td([
                            f"{trace_score:.1f}",
                            html.Span(" ★", className="text-warning ms-1") if is_trace_authoritative else ""
                        ], className="text-end")
                    ])
                ])
            ], bordered=False, size="sm", className="mb-0")

            # Build symptoms list
            symptoms_list = html.Ul([
                html.Li(symptom, className="small") for symptom in symptoms
            ], className="mb-2") if symptoms else html.P("No symptoms detected", className="text-muted small mb-2")

            # Build blame list
            blame_list = html.Div([
                html.Strong("Blamed by: ", className="small"),
                html.Span(", ".join(blamed_by) if blamed_by else "None", className="small text-muted")
            ], className="mb-2") if blamed_by or guilt_adjusted > 0 else None

            # Build story
            story_display = html.Div([
                html.Strong("Root Cause Story:", className="mb-2 d-block text-dark"),
                html.Ul([
                    html.Li(step, className="small text-dark") for step in story
                ], className="mb-0")
            ], className="mt-2 p-2 bg-light rounded border") if story else None

            # Build pod forensics display (if available)
            pod_forensics = result.get('pod_forensics', {})
            pod_forensics_display = None
            if pod_forensics and pod_forensics.get('pod_count', 0) > 0:
                degraded_pods = pod_forensics.get('degraded_pods', [])
                healthy_pods = pod_forensics.get('healthy_pods', [])

                degraded_items = [
                    html.Li([
                        html.Strong(pod['pod_id'], className="text-danger"),
                        html.Span(f" - Score: {pod.get('self_score', 0):.1f}", className="text-dark"),
                        html.Ul([
                            html.Li(symptom, className="small text-dark")
                            for symptom in pod.get('symptoms', [])
                        ]) if pod.get('symptoms') else ""
                    ], className="small mb-1")
                    for pod in degraded_pods[:3]  # Top 3
                ]

                pod_forensics_display = html.Div([
                    html.Strong(f"Pod Forensics ({pod_forensics['pod_count']} pods):", className="mb-2 d-block small text-dark"),
                    html.P([
                        html.Span(f"Degraded: {pod_forensics.get('degraded_count', 0)}", className="text-danger me-2 fw-bold"),
                        html.Span(f"Healthy: {pod_forensics.get('healthy_count', 0)}", className="text-success fw-bold")
                    ], className="small mb-2"),
                    html.P(pod_forensics.get('pattern', ''), className="small text-dark mb-2"),
                    html.Div([
                        html.Strong("Top degraded pods:", className="small d-block mb-1 text-dark"),
                        html.Ul(degraded_items, className="mb-0")
                    ]) if degraded_items else html.Div()
                ], className="mt-2 p-2 bg-light rounded border")

            # Create card
            ranking_cards.append(
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            f"#{i}: ",
                            html.Strong(node),
                            html.Span(" 🎯 GROUND TRUTH", className="badge bg-danger ms-2") if is_ground_truth else "",
                            html.Span(f" Score: {score:.1f}", className="ms-2 text-muted")
                        ], className="mb-0")
                    ], className=header_class),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.H6("Score Breakdown", className="mb-2"),
                                score_breakdown
                            ], width=4),
                            dbc.Col([
                                html.H6("Symptoms", className="mb-2"),
                                symptoms_list,
                                blame_list if blame_list else html.Div()
                            ], width=4),
                            dbc.Col([
                                html.H6("Analysis Details", className="mb-2"),
                                html.P([
                                    html.Strong("Pattern: "),
                                    html.Span(pattern)
                                ], className="small mb-1"),
                                html.P([
                                    html.Strong("Coverage: "),
                                    html.Span(f"{coverage:.1%}")
                                ], className="small mb-1") if pod_score > 0 else None,
                                html.P([
                                    html.Strong("Trace Auth: "),
                                    html.Span("Yes" if is_trace_authoritative else "No")
                                ], className="small mb-1"),
                            ], width=4)
                        ]),
                        story_display if story_display else html.Div(),
                        pod_forensics_display if pod_forensics_display else html.Div()
                    ])
                ], className="mb-3 shadow-sm", color=card_color, outline=True)
            )

        # Format the full JSON for display
        json_output = json.dumps(rca_data, indent=2)

        # Create layout
        layout = html.Div([
            # Header
            dbc.Card([
                dbc.CardBody([
                    html.H3([
                        html.Span("🔬 ", style={'fontSize': '1.2em'}),
                        "Whitebox RCA Analysis"
                    ], className="mb-3"),
                    html.P("Comprehensive root cause analysis using integrated health scoring, fault propagation, and temporal causality.",
                           className="text-muted mb-0")
                ])
            ], className="mb-3 shadow-sm"),

            # Summary cards
            summary_cards,

            # Ranking cards
            html.H4("📋 Detailed Rankings (Top 10)", className="mb-3"),
            html.Div(ranking_cards),

            # Full JSON Data Section (collapsible)
            dbc.Card([
                dbc.CardHeader([
                    html.H5("📄 Complete RCA Data (JSON)", className="mb-0")
                ]),
                dbc.CardBody([
                    html.Details([
                        html.Summary([
                            html.Strong("Click to expand full JSON data", className="text-dark"),
                            html.Span(" (includes all rankings, scores, and metadata)", className="text-muted small ms-2")
                        ], style={'cursor': 'pointer', 'padding': '10px', 'backgroundColor': '#f8f9fa',
                                 'borderRadius': '5px', 'fontWeight': 'bold', 'color': '#212529'}),
                        html.Pre(
                            json_output,
                            style={
                                'backgroundColor': '#1e1e1e',
                                'color': '#d4d4d4',
                                'padding': '20px',
                                'borderRadius': '5px',
                                'overflow': 'auto',
                                'maxHeight': '800px',
                                'fontSize': '0.85em',
                                'lineHeight': '1.5',
                                'whiteSpace': 'pre-wrap',
                                'fontFamily': "'Fira Code', 'Courier New', monospace",
                                'marginTop': '10px'
                            }
                        )
                    ], open=False)  # Collapsed by default
                ])
            ], className="shadow-sm mt-3")
        ])

        print("  ✓ Whitebox RCA layout created successfully!")
        return layout

    except Exception as e:
        print(f"  ✗ Error in create_whitebox_rca_display: {str(e)}")
        import traceback
        traceback.print_exc()
        return html.Div([
            dbc.Alert([
                html.H4("Error Loading Whitebox RCA Analysis", className="alert-heading"),
                html.P(str(e)),
                html.Hr(),
                html.Pre(traceback.format_exc(), style={'fontSize': '0.8em'})
            ], color="danger")
        ])
