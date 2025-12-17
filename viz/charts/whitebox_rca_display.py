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

        # Find rank of ground truth in ALL rankings
        all_nodes = [r['node'] for r in rankings]
        if ground_truth in all_nodes:
            gt_rank = all_nodes.index(ground_truth) + 1
            if gt_rank == 1:
                rank_status = "success"
            elif gt_rank <= 10:
                rank_status = "warning"
            else:
                rank_status = "danger"
        else:
            gt_rank = "Not Found"
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

        # Determine which rankings to show
        # Always show top 10, plus ground truth if it's outside top 10
        rankings_to_show = []

        # Add ground truth card first if it's outside top 10
        gt_outside_top10 = isinstance(gt_rank, int) and gt_rank > 10
        if gt_outside_top10:
            gt_result = rankings[gt_rank - 1]
            rankings_to_show.append((gt_rank, gt_result, True))  # (rank, result, is_special_gt)

        # Add top 10
        for i, result in enumerate(rankings[:10], 1):
            rankings_to_show.append((i, result, False))

        # Create detailed ranking cards - clean version without duplication
        ranking_cards = []

        # Add warning banner if ground truth is outside top 10
        if gt_outside_top10:
            ranking_cards.append(
                dbc.Alert([
                    html.Strong("⚠️ Ground Truth Outside Top 10", className="me-2"),
                    html.Span(f"Ground truth '{ground_truth}' ranked #{gt_rank}. Showing it here for analysis."),
                ], color="warning", className="mb-3")
            )

        for rank_idx, (i, result, is_special_gt) in enumerate(rankings_to_show):
            # Add separator after ground truth card
            if rank_idx == 1 and gt_outside_top10:
                ranking_cards.append(
                    html.Div([
                        html.Hr(className="my-4"),
                        html.H5("📋 Top 10 Predictions", className="mb-3 text-primary")
                    ])
                )
            node = result['node']
            score = result['score']
            symptoms = result.get('symptoms', [])
            story = result.get('story', [])

            # Score components (needed for calculation display)
            integrated_score = result.get('integrated_score', 0)
            self_score = result.get('self_score', 0)
            guilt_adjusted = result.get('guilt_adjusted', 0)
            temporal_score = result.get('temporal_score', 0)
            trace_score = result.get('trace_score', 0)
            blamed_by = result.get('blamed_by', [])
            is_trace_authoritative = result.get('is_trace_authoritative', False)

            # Additional score components from whitebox_rca.py
            guilt_raw = result.get('guilt_raw', 0)
            discount_factor = result.get('discount_factor', 1.0)
            max_outgoing_conf = result.get('max_outgoing_conf', 0)

            # Health metadata
            health_metadata = result.get('health_metadata', {})
            pod_score = health_metadata.get('pod_score', 0)
            coverage = health_metadata.get('coverage', 0)
            pattern = health_metadata.get('pattern', 'N/A')
            degraded_count = health_metadata.get('degraded_count', 0)
            healthy_count = health_metadata.get('healthy_count', 0)
            zombie_count = health_metadata.get('zombie_pods', 0)

            # Additional info
            is_healthy = result.get('is_healthy', False)
            temporal_info = result.get('temporal_info', {})
            trace_info = result.get('trace_info', {})

            # Determine styling - clean and consistent
            is_ground_truth = (node == ground_truth)
            if is_special_gt:
                # Special styling for ground truth outside top 10
                border_color = "#dc3545"  # Red to indicate it's poorly ranked
                rank_badge_bg = "#dc3545"
            elif is_ground_truth:
                border_color = "#198754"  # Green for ground truth in top 10
                rank_badge_bg = "#198754"
            elif i == 1:
                border_color = "#0d6efd"  # Blue for top prediction
                rank_badge_bg = "#0d6efd"
            else:
                border_color = "#dee2e6"  # Light gray for others
                rank_badge_bg = "#6c757d"

            # Expandable sections for detailed information
            additional_details = []

            # 1. Score Calculation - Use the complete breakdown from whitebox_rca.py output
            score_breakdown = result.get('score_breakdown', {})

            # If score_breakdown exists (new format), use it directly
            if score_breakdown:
                base_health_score = score_breakdown.get('base_health_score', integrated_score * 10.0)
                trace_symptom_bonus = score_breakdown.get('trace_symptom_bonus', 0.0)
                symptom_bonus = score_breakdown.get('symptom_strength_bonus', 0.0)
                trace_boost = score_breakdown.get('trace_boost', 0.0)
                base_before_penalties = score_breakdown.get('base_before_penalties', base_health_score + trace_boost + symptom_bonus)
                victim_penalty_applied = score_breakdown.get('victim_penalty_applied', False)
                healthy_penalty_applied = score_breakdown.get('healthy_penalty_applied', False)
                base_after_penalties = score_breakdown.get('base_after_penalties', base_before_penalties)
                guilt_component = score_breakdown.get('guilt_component', guilt_adjusted * 20.0)
                temporal_component = score_breakdown.get('temporal_component', temporal_score * 2.0)
                impact_bonus = score_breakdown.get('impact_bonus', 0.0)
                capacity_bonus = score_breakdown.get('capacity_bonus', 0.0)
                confirmation_score_total = score_breakdown.get('confirmation_score', guilt_component + temporal_component + impact_bonus + capacity_bonus)
            else:
                # Fallback for old format (backward compatibility)
                base_health_score = integrated_score * 10.0
                trace_symptom_bonus = 0.0
                symptom_bonus = 0.0
                trace_boost = 0.0
                base_before_penalties = base_health_score
                victim_penalty_applied = False
                healthy_penalty_applied = is_healthy and not is_trace_authoritative
                base_after_penalties = base_health_score
                guilt_component = guilt_adjusted * 20.0
                temporal_component = temporal_score * 2.0
                impact_bonus = 0.0
                capacity_bonus = 0.0
                confirmation_score_total = guilt_component + temporal_component

            # Calculate trace boost formula for display
            trace_boost_formula = "0 (no authoritative trace)"
            trace_boost_reason = ""
            if trace_boost > 0 and is_trace_authoritative and trace_info:
                self_time_deg = trace_info.get('self_time_degradation', 1.0)
                if self_time_deg > 3.0:
                    multiplier = 6.0
                    base_boost = 80.0
                    trace_boost_formula = f"({trace_score:.2f} × {multiplier}) + {base_boost} = {trace_boost:.1f}"
                    trace_boost_reason = f"Critical degradation: {self_time_deg:.2f}x > 3.0x threshold"
                elif self_time_deg > 2.0:
                    multiplier = 5.0
                    base_boost = 60.0
                    trace_boost_formula = f"({trace_score:.2f} × {multiplier}) + {base_boost} = {trace_boost:.1f}"
                    trace_boost_reason = f"Severe degradation: {self_time_deg:.2f}x > 2.0x threshold"
                else:
                    multiplier = 4.0
                    base_boost = 40.0
                    trace_boost_formula = f"({trace_score:.2f} × {multiplier}) + {base_boost} = {trace_boost:.1f}"
                    trace_boost_reason = f"Moderate degradation: {self_time_deg:.2f}x"

            # Calculate penalty values from flags
            victim_penalty = 0.1 if victim_penalty_applied else 1.0
            healthy_penalty = 0.05 if healthy_penalty_applied else 1.0

            # Penalty descriptions
            victim_penalty_desc = "90% penalty (victim detected)" if victim_penalty_applied else "None"
            healthy_penalty_desc = "95% penalty (healthy node)" if healthy_penalty_applied else "None"

            # Symptom bonus description
            symptom_count = len(symptoms)
            symptom_bonus_desc = f"{symptom_bonus:.1f} ({symptom_count} symptoms, no trace)" if symptom_bonus > 0 else "0 (has trace or insufficient symptoms)"

            # Calculated final score (should match actual score exactly!)
            calculated_final = base_after_penalties + confirmation_score_total

            score_calc_section = html.Details([
                html.Summary("📊 Score Calculation (How We Got This Score)", style={
                    'cursor': 'pointer',
                    'fontSize': '0.95em',
                    'fontWeight': '600',
                    'color': '#212529',
                    'padding': '10px 14px',
                    'backgroundColor': '#e7f3ff',
                    'borderRadius': '6px',
                    'border': '1px solid #0d6efd'
                }),
                html.Div([
                    # Formula
                    html.Div([
                        html.Strong("Formula (from whitebox_rca.py):", className="d-block mb-2", style={'color': '#0d6efd'}),
                        html.Pre(
                            "Final Score = Base Score + Confirmation Score\n\n"
                            "Base Score = [(Health × 10) + Trace Boost + Symptom Boost] × Penalties\n"
                            "Confirmation Score = (Guilt × 20) + (Temporal × 2) + Impact + Capacity",
                            className="p-3 mb-3",
                            style={
                                'backgroundColor': '#f8f9fa',
                                'border': '1px solid #dee2e6',
                                'borderRadius': '4px',
                                'fontSize': '0.85em',
                                'color': '#212529',
                                'lineHeight': '1.6'
                            }
                        ),
                    ]),

                    # Step-by-step calculation
                    html.Div([
                        html.Strong("Step-by-Step Calculation:", className="d-block mb-3", style={'color': '#0d6efd'}),

                        # Base Score Components
                        html.Div([
                            html.Strong("1. Base Score Components:", className="d-block mb-3 text-success"),

                            # Health component
                            html.Div([
                                html.Strong("a) Health Score:", className="d-block mb-2"),
                                html.Code(f"Integrated Health × 10 = {integrated_score:.2f} × 10 = {base_health_score:.1f}"),
                                html.Ul([
                                    html.Li(f"Service Self Score: {self_score:.2f}"),
                                    html.Li(f"Pod Health Score: {pod_score:.2f} (coverage: {coverage:.0%})") if pod_score > 0 else None,
                                ], className="small text-muted mt-2 mb-0")
                            ], className="mb-3 p-2 bg-light rounded"),

                            # Trace boost
                            html.Div([
                                html.Strong("b) Trace Boost:", className="d-block mb-2"),
                                html.Div([
                                    html.Code(f"+ {trace_boost_formula}", className="d-block mb-2") if trace_boost > 0 else html.Code("+ 0 (no trace)", className="d-block mb-2"),
                                    html.Div([
                                        html.Span("Reason: ", className="fw-bold small"),
                                        html.Span(trace_boost_reason, className="small text-muted")
                                    ], className="mb-2") if trace_boost_reason else None,
                                    html.Ul([
                                        html.Li(f"Trace Score: {trace_score:.2f}"),
                                        html.Li(f"Is Authoritative: {'Yes ★' if is_trace_authoritative else 'No'}"),
                                        html.Li(f"Self-time degradation: {trace_info.get('self_time_degradation', 1.0):.2f}x" if trace_info and 'self_time_degradation' in trace_info else "No trace data"),
                                        html.Li([
                                            html.Span("Formula by severity:", className="fw-bold"),
                                            html.Ul([
                                                html.Li("Critical (>3x): (trace × 6.0) + 80", className="small"),
                                                html.Li("Severe (>2x): (trace × 5.0) + 60", className="small"),
                                                html.Li("Moderate: (trace × 4.0) + 40", className="small"),
                                            ], className="mb-0")
                                        ])
                                    ], className="small text-muted mt-2 mb-0")
                                ])
                            ], className="mb-3 p-2 bg-light rounded"),

                            # Symptom boost
                            html.Div([
                                html.Strong("c) Symptom Strength Boost:", className="d-block mb-2"),
                                html.Code(f"+ {symptom_bonus_desc}"),
                                html.Ul([
                                    html.Li(f"Applies when: no trace + ≥2 symptoms + self_score > 2"),
                                ], className="small text-muted mt-2 mb-0")
                            ], className="mb-3 p-2 bg-light rounded"),

                            # Subtotal before penalties
                            html.Div([
                                html.Strong("Subtotal before penalties: ", className="me-2"),
                                html.Code(f"{base_health_score:.1f} + {trace_boost:.1f} + {symptom_bonus:.1f} = {base_before_penalties:.1f}")
                            ], className="mb-3 p-2 border rounded bg-warning bg-opacity-10"),

                            # Penalties
                            html.Div([
                                html.Strong("d) Penalties Applied:", className="d-block mb-2"),
                                html.Ul([
                                    html.Li(f"Victim Penalty: {victim_penalty_desc}"),
                                    html.Li(f"Healthy Node Penalty: {healthy_penalty_desc}"),
                                ], className="mb-2"),
                                html.Code(f"Base Score = {base_before_penalties:.1f} × {victim_penalty} × {healthy_penalty} = {base_after_penalties:.1f}")
                            ], className="mb-3 p-2 bg-light rounded"),

                        ], className="p-3 mb-3 border-start border-success border-4"),

                        # Confirmation Score
                        html.Div([
                            html.Strong("2. Confirmation Score (External Evidence):", className="d-block mb-3 text-info"),
                            html.Ul([
                                html.Li([
                                    html.Strong("Guilt: "),
                                    html.Code(f"{guilt_adjusted:.2f} × 20 = {guilt_component:.1f}"),
                                    html.Ul([
                                        html.Li(f"Raw guilt from blame: {guilt_raw:.2f}"),
                                        html.Li(f"Discount factor (proxy detection): {discount_factor:.2f}"),
                                        html.Li(f"Blamed by: {', '.join(blamed_by) if blamed_by else 'none'}"),
                                    ], className="small text-muted mt-1")
                                ], className="mb-2"),
                                html.Li([
                                    html.Strong("Temporal: "),
                                    html.Code(f"{temporal_score:.2f} × 2 = {temporal_component:.1f}"),
                                ], className="mb-2"),
                                html.Li([
                                    html.Strong("Impact Bonus: "),
                                    html.Code(f"{impact_bonus:.1f}"),
                                    html.Div([
                                        html.Span("Formula: log₁₀(max(1, traffic_volume))", className="small text-muted d-block"),
                                    ], className="mt-1")
                                ], className="mb-2"),
                                html.Li([
                                    html.Strong("Capacity: "),
                                    html.Code(f"{capacity_bonus:.1f}"),
                                    html.Span(f" ({zombie_count} zombie pods)" if zombie_count > 0 else " (no zombies)", className="small text-muted ms-2")
                                ], className="mb-2"),
                            ], className="mb-2"),
                            html.Code(f"Confirmation Score = {guilt_component:.1f} + {temporal_component:.1f} + {impact_bonus:.1f} + {capacity_bonus:.1f} = {confirmation_score_total:.1f}")
                        ], className="p-3 mb-3 border-start border-info border-4"),

                        # Final Result
                        html.Div([
                            html.Strong("Final Calculation:", className="d-block mb-3 fs-5"),
                            html.Div([
                                html.Div([
                                    html.Span("Base Score: ", className="me-2"),
                                    html.Code(f"{base_after_penalties:.1f}", className="fs-6 fw-bold")
                                ], className="mb-2"),
                                html.Div([
                                    html.Span("+ Confirmation Score: ", className="me-2"),
                                    html.Code(f"{confirmation_score_total:.1f}", className="fs-6 fw-bold")
                                ], className="mb-3"),
                                html.Hr(),
                                html.Div([
                                    html.Span("= Final Score: ", className="me-2"),
                                    html.Strong(f"{calculated_final:.1f}", className="text-success fs-4"),
                                    html.Span(f" (actual: {score:.1f})", className="small text-muted ms-2")
                                ])
                            ])
                        ], className="p-4 bg-success bg-opacity-10 border border-success rounded")
                    ])
                ], className="p-3")
            ], className="mb-2")
            additional_details.append(score_calc_section)

            # 2. Symptoms (no duplication - only here)
            if symptoms:
                symptoms_section = html.Details([
                    html.Summary(f"🩺 Symptoms ({len(symptoms)})", style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#212529',
                        'padding': '10px 14px',
                        'backgroundColor': '#fff3cd',
                        'borderRadius': '6px',
                        'border': '1px solid #ffc107'
                    }),
                    html.Div([
                        html.Ul([
                            html.Li(symptom, className="mb-2", style={'fontSize': '0.9em'}) for symptom in symptoms
                        ], className="mb-0 mt-2")
                    ], className="p-3")
                ])
                additional_details.append(symptoms_section)

            # 3. Root Cause Story
            if story:
                story_section = html.Details([
                    html.Summary("📖 Root Cause Story", style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#212529',
                        'padding': '10px 14px',
                        'backgroundColor': '#d1ecf1',
                        'borderRadius': '6px',
                        'border': '1px solid #0dcaf0'
                    }),
                    html.Div([
                        html.Ol([
                            html.Li(step, className="mb-2", style={'fontSize': '0.9em'}) for step in story
                        ], className="mb-0 mt-2")
                    ], className="p-3")
                ])
                additional_details.append(story_section)

            # 4. Pod Forensics (if available)
            pod_forensics = result.get('pod_forensics', {})
            if pod_forensics and pod_forensics.get('pod_count', 0) > 0:
                pf_degraded_count = pod_forensics.get('degraded_count', 0)
                pf_healthy_count = pod_forensics.get('healthy_count', 0)
                degraded_pods = pod_forensics.get('degraded_pods', [])
                healthy_pods = pod_forensics.get('healthy_pods', [])

                # All degraded pods with symptoms
                degraded_items = [
                    html.Li([
                        html.Strong(pod['pod_id'], style={'color': '#dc3545'}),
                        html.Span(f" (score: {pod.get('self_score', 0):.1f})", className="text-muted ms-2"),
                        html.Ul([
                            html.Li(symptom, className="small text-muted")
                            for symptom in pod.get('symptoms', [])
                        ], className="mt-1") if pod.get('symptoms') else ""
                    ], className="mb-2", style={'fontSize': '0.9em'})
                    for pod in degraded_pods
                ]

                # Sample healthy pods
                healthy_items = [
                    html.Li([
                        html.Strong(pod['pod_id'], style={'color': '#198754'}),
                        html.Span(f" (score: {pod.get('self_score', 0):.1f})", className="text-muted ms-2 small")
                    ], className="small")
                    for pod in healthy_pods[:5]
                ]

                pod_forensics_section = html.Details([
                    html.Summary([
                        f"🔬 Pod Forensics: ",
                        html.Span(f"{pf_degraded_count} degraded", style={'color': '#dc3545', 'fontWeight': 'bold', 'marginRight': '8px'}),
                        html.Span(f"{pf_healthy_count} healthy", style={'color': '#198754', 'fontWeight': 'bold'})
                    ], style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#212529',
                        'padding': '10px 14px',
                        'backgroundColor': '#f8d7da',
                        'borderRadius': '6px',
                        'border': '1px solid #dc3545'
                    }),
                    html.Div([
                        html.Div([
                            html.Strong("Pattern: ", style={'color': '#0d6efd'}),
                            html.Span(pod_forensics.get('pattern', ''))
                        ], className="mb-3 p-2 bg-light rounded"),
                        html.Div([
                            html.Strong("Degraded Pods:", className="d-block mb-2", style={'color': '#dc3545'}),
                            html.Ul(degraded_items, className="mb-3") if degraded_items else html.P("None", className="text-muted")
                        ]),
                        html.Div([
                            html.Strong("Healthy Pods (sample):", className="d-block mb-2", style={'color': '#198754'}),
                            html.Ul(healthy_items, className="mb-0") if healthy_items else html.P("None", className="text-muted")
                        ]) if healthy_items else html.Div()
                    ], className="p-3")
                ])
                additional_details.append(pod_forensics_section)

            # 5. Metadata (no duplication - only technical details here)
            metadata_section = html.Details([
                html.Summary("⚙️ Technical Metadata", style={
                    'cursor': 'pointer',
                    'fontSize': '0.95em',
                    'fontWeight': '600',
                    'color': '#212529',
                    'padding': '10px 14px',
                    'backgroundColor': '#e2e3e5',
                    'borderRadius': '6px',
                    'border': '1px solid #6c757d'
                }),
                html.Div([
                    html.Table([
                        html.Tbody([
                            html.Tr([
                                html.Td(html.Strong("Health Pattern:"), style={'width': '200px'}),
                                html.Td(pattern)
                            ]),
                            html.Tr([
                                html.Td(html.Strong("Pod Coverage:"), style={'width': '200px'}),
                                html.Td(f"{coverage:.1%} ({degraded_count + healthy_count} total pods)")
                            ]) if pod_score > 0 else None,
                            html.Tr([
                                html.Td(html.Strong("Degraded / Healthy:"), style={'width': '200px'}),
                                html.Td(f"{degraded_count} degraded / {healthy_count} healthy")
                            ]) if pod_score > 0 else None,
                            html.Tr([
                                html.Td(html.Strong("Zombie Pods:"), style={'width': '200px'}),
                                html.Td(f"{zombie_count}" if zombie_count > 0 else "None")
                            ]) if zombie_count > 0 else None,
                            html.Tr([
                                html.Td(html.Strong("Trace Authoritative:"), style={'width': '200px'}),
                                html.Td("Yes ★" if is_trace_authoritative else "No")
                            ]),
                            html.Tr([
                                html.Td(html.Strong("Blamed By:"), style={'width': '200px'}),
                                html.Td(", ".join(blamed_by) if blamed_by else "None")
                            ]),
                            html.Tr([
                                html.Td(html.Strong("Max Outgoing Conf:"), style={'width': '200px'}),
                                html.Td(f"{max_outgoing_conf:.2f}")
                            ]),
                            html.Tr([
                                html.Td(html.Strong("Is Healthy:"), style={'width': '200px'}),
                                html.Td("Yes" if is_healthy else "No")
                            ]),
                        ])
                    ], className="table table-sm mb-0", style={'fontSize': '0.9em'})
                ], className="p-3")
            ])
            additional_details.append(metadata_section)

            # Create clean card - no duplications, everything in expandable sections
            ranking_cards.append(
                dbc.Card([
                    dbc.CardBody([
                        # Header: Rank + Component Name + Score (that's it!)
                        html.Div([
                            html.Span(f"#{i}", className="badge rounded-pill me-3",
                                     style={'fontSize': '1.1em', 'backgroundColor': rank_badge_bg, 'color': 'white',
                                            'minWidth': '40px', 'padding': '8px 12px', 'fontWeight': 'bold'}),
                            html.Strong(node, style={'fontSize': '1.2em', 'color': '#212529', 'flex': '1'}),
                            html.Span(" 🎯 GROUND TRUTH", className="badge bg-success me-3",
                                     style={'fontSize': '0.9em', 'padding': '6px 12px'}) if is_ground_truth else "",
                            html.Span(f"Score: {score:.1f}", className="badge",
                                     style={'fontSize': '1.1em', 'backgroundColor': '#212529', 'color': 'white',
                                            'padding': '8px 16px', 'fontWeight': 'bold'})
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '16px'}),

                        # Quick summary line
                        html.Div([
                            html.Span(f"Health: {integrated_score:.1f}", className="me-3",
                                     style={'fontSize': '0.9em', 'color': '#6c757d'}),
                            html.Span(f"Guilt: {guilt_adjusted:.1f}", className="me-3",
                                     style={'fontSize': '0.9em', 'color': '#6c757d'}),
                            html.Span(f"Temporal: {temporal_score:.1f}", className="me-3",
                                     style={'fontSize': '0.9em', 'color': '#6c757d'}),
                            html.Span(f"Trace: {trace_score:.1f}", className="me-2",
                                     style={'fontSize': '0.9em', 'color': '#6c757d'}),
                            html.Span("★", style={'color': '#ffc107'}) if is_trace_authoritative else "",
                            html.Span(f" • {len(symptoms)} symptoms", className="ms-3",
                                     style={'fontSize': '0.9em', 'color': '#6c757d'}) if symptoms else ""
                        ], style={'marginBottom': '16px', 'paddingBottom': '16px', 'borderBottom': '1px solid #e9ecef'}),

                        # All details in expandable sections (no duplication!)
                        html.Div(additional_details)
                    ], style={'padding': '20px'})
                ], className="mb-3 shadow-sm", style={
                    'border': f'3px solid {border_color}',
                    'borderRadius': '8px',
                    'backgroundColor': '#ffffff'
                })
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
