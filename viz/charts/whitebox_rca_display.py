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

        # Create detailed ranking cards - streamlined version
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

            # Determine styling
            is_ground_truth = (node == ground_truth)
            if is_ground_truth:
                border_color = "#28a745"
                header_bg = "#d4edda"
                badge_color = "success"
            elif i == 1:
                border_color = "#007bff"
                header_bg = "#cfe2ff"
                badge_color = "primary"
            else:
                border_color = "#dee2e6"
                header_bg = "#f8f9fa"
                badge_color = "secondary"

            # Build compact score display with visual bars
            def score_bar(value, max_val=100, color="#007bff"):
                """Create a simple progress-style bar"""
                pct = min(100, (value / max_val) * 100) if max_val > 0 else 0
                return html.Div([
                    html.Div(
                        style={
                            'width': f'{pct}%',
                            'height': '6px',
                            'backgroundColor': color,
                            'borderRadius': '3px',
                            'transition': 'width 0.3s ease'
                        }
                    )
                ], style={
                    'width': '100%',
                    'height': '6px',
                    'backgroundColor': '#e9ecef',
                    'borderRadius': '3px',
                    'overflow': 'hidden'
                })

            # Compact score breakdown
            score_items = [
                html.Div([
                    html.Span(f"Health: {integrated_score:.1f}", className="small fw-bold me-2", style={'minWidth': '90px', 'display': 'inline-block'}),
                    html.Span(f"(Self: {self_score:.1f}", className="small text-muted"),
                    html.Span(f" + Pod: {pod_score:.1f})", className="small text-muted") if pod_score > 0 else html.Span(")", className="small text-muted")
                ], className="mb-1"),
                html.Div([
                    html.Span(f"Guilt: {guilt_adjusted:.1f}", className="small fw-bold me-2", style={'minWidth': '90px', 'display': 'inline-block'}),
                    html.Span(f"Blamed by: {', '.join(blamed_by[:2]) if blamed_by else 'none'}", className="small text-muted") if blamed_by else html.Span("(not blamed)", className="small text-muted")
                ], className="mb-1"),
                html.Div([
                    html.Span(f"Temporal: {temporal_score:.1f}", className="small fw-bold me-2", style={'minWidth': '90px', 'display': 'inline-block'}),
                    html.Span(f"Trace: {trace_score:.1f}", className="small fw-bold me-2"),
                    html.Span("★", className="text-warning") if is_trace_authoritative else ""
                ], className="mb-0")
            ]

            # Top 3 symptoms only
            top_symptoms = symptoms[:3] if len(symptoms) > 0 else []
            symptom_display = html.Div([
                html.Div([
                    html.Span("• ", className="me-1"),
                    html.Span(symptom, className="small")
                ], className="mb-1") for symptom in top_symptoms
            ] + ([
                html.Span(f"+ {len(symptoms) - 3} more", className="small text-muted fst-italic")
            ] if len(symptoms) > 3 else []))

            if not symptoms:
                symptom_display = html.Span("No symptoms detected", className="small text-muted fst-italic")

            # Collapsible story and pod forensics
            additional_details = []

            # Story section (collapsible)
            if story:
                additional_details.append(
                    html.Details([
                        html.Summary("Root Cause Story", style={'cursor': 'pointer', 'fontSize': '0.9em', 'fontWeight': '500', 'color': '#495057', 'marginBottom': '8px'}),
                        html.Ul([
                            html.Li(step, className="small") for step in story
                        ], className="mb-0 ms-3")
                    ], className="mt-2")
                )

            # Pod forensics section (collapsible)
            pod_forensics = result.get('pod_forensics', {})
            if pod_forensics and pod_forensics.get('pod_count', 0) > 0:
                degraded_count = pod_forensics.get('degraded_count', 0)
                healthy_count = pod_forensics.get('healthy_count', 0)
                degraded_pods = pod_forensics.get('degraded_pods', [])[:3]  # Top 3

                pod_items = [
                    html.Li([
                        html.Strong(pod['pod_id'], className="text-danger", style={'fontSize': '0.85em'}),
                        html.Span(f" ({pod.get('self_score', 0):.0f})", className="text-muted small ms-1")
                    ], className="small mb-1")
                    for pod in degraded_pods
                ]

                additional_details.append(
                    html.Details([
                        html.Summary([
                            f"Pod Forensics: ",
                            html.Span(f"{degraded_count} degraded", className="text-danger fw-bold me-2"),
                            html.Span(f"{healthy_count} healthy", className="text-success fw-bold")
                        ], style={'cursor': 'pointer', 'fontSize': '0.9em', 'fontWeight': '500', 'color': '#495057', 'marginBottom': '8px'}),
                        html.Div([
                            html.Span(pod_forensics.get('pattern', ''), className="small text-muted d-block mb-2"),
                            html.Ul(pod_items, className="mb-0 ms-3") if pod_items else html.Div()
                        ])
                    ], className="mt-2")
                )

            # Create streamlined card
            ranking_cards.append(
                dbc.Card([
                    dbc.CardBody([
                        # Header row with rank, name, score
                        html.Div([
                            html.Div([
                                html.Span(f"#{i}", className="badge rounded-pill me-2",
                                         style={'fontSize': '1em', 'backgroundColor': border_color, 'color': 'white', 'minWidth': '35px'}),
                                html.Strong(node, style={'fontSize': '1.1em', 'color': '#212529'}),
                                html.Span(" 🎯", className="ms-2") if is_ground_truth else "",
                                html.Span(f"{score:.1f}", className="badge bg-dark ms-auto", style={'fontSize': '1em'})
                            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'})
                        ]),

                        # Main content in 2 columns
                        dbc.Row([
                            # Left column: Scores
                            dbc.Col([
                                html.Div([
                                    html.Strong("Scores", className="text-muted small d-block mb-2", style={'textTransform': 'uppercase', 'fontSize': '0.75em', 'letterSpacing': '0.5px'}),
                                    html.Div(score_items)
                                ])
                            ], width=5, className="border-end pe-3"),

                            # Right column: Symptoms & metadata
                            dbc.Col([
                                html.Div([
                                    html.Strong("Symptoms", className="text-muted small d-block mb-2", style={'textTransform': 'uppercase', 'fontSize': '0.75em', 'letterSpacing': '0.5px'}),
                                    symptom_display,
                                    html.Div([
                                        html.Span(f"Pattern: {pattern}", className="badge bg-light text-dark me-1 mt-2", style={'fontSize': '0.75em'}),
                                        html.Span(f"Cov: {coverage:.0%}", className="badge bg-light text-dark me-1", style={'fontSize': '0.75em'}) if pod_score > 0 else ""
                                    ])
                                ])
                            ], width=7, className="ps-3")
                        ], className="g-0"),

                        # Additional details (collapsible sections)
                        html.Div(additional_details, className="mt-2 pt-2 border-top") if additional_details else html.Div()
                    ], style={'padding': '15px'})
                ], className="mb-2 shadow-sm", style={'border': f'2px solid {border_color}', 'borderRadius': '8px'})
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
