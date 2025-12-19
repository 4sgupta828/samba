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


def create_score_breakdown_matrix(score_composition, final_score, node_name):
    """
    Create a detailed score breakdown showing: raw value → formula → adjustments → final points.
    This function dynamically adapts to any score structure.

    Args:
        score_composition: Score composition dictionary from RCA output
        final_score: Final computed score
        node_name: Name of the node being analyzed

    Returns:
        HTML Details element with score breakdown
    """
    def format_score_section(section_name, section_data, level=0):
        """
        Recursively format score section data into table rows showing complete calculation flow.
        Returns list of table rows.
        """
        rows = []

        if isinstance(section_data, dict):
            # Check if this is a leaf node with points
            if 'points' in section_data:
                # This is a scorable component - show complete calculation
                points = section_data.get('points', 0)
                raw = section_data.get('raw', None)

                # Build the calculation flow
                # Step 1: Raw value with context and meaning
                raw_display = f"{raw:.2f}" if raw is not None and not isinstance(raw, bool) else "—"

                # Determine component type to provide better explanations
                is_primary = section_data.get('is_primary', None)
                coverage_context = section_data.get('coverage_context', None)
                confidence = section_data.get('confidence', None)
                multiplier = section_data.get('multiplier', None)
                weight = section_data.get('weight', None)

                # Add raw value meaning based on component type
                raw_meaning = ""
                if section_name in ['base_health', 'Base Health']:
                    raw_meaning = f"Health score (0-10 scale, 0=healthy, 10=critical)"
                    raw_display = f"{raw:.2f}/10" if raw is not None else "—"
                elif section_name in ['physics_coverage', 'Physics Coverage']:
                    raw_meaning = f"Coverage ratio (symptoms explained)"
                    if raw is not None:
                        raw_display = f"{raw:.2f} ({raw*100:.0f}%)"
                elif section_name in ['semantic_bonus', 'Semantic Bonus']:
                    raw_meaning = "Categorical (primary vs secondary symptoms)"
                    raw_display = "Primary" if is_primary else "Secondary"

                # Step 2: Build COMPLETE formula showing ALL steps
                formula_parts = []
                explanation_parts = []

                # Add raw value meaning first
                if raw_meaning:
                    explanation_parts.append(raw_meaning)

                if raw is not None and not isinstance(raw, bool):
                    # Has a raw numeric value - show the math
                    if weight is not None:
                        # Physics-style: raw × weight
                        formula_parts.append(f"{raw:.2f} × {weight:.0f}")
                        explanation_parts.append(f"weight: {weight:.0f}")

                        if multiplier is not None and multiplier != 1.0:
                            formula_parts.append(f"× {multiplier:.2f}")
                            explanation_parts.append(f"multiplier: {multiplier:.2f}")
                    else:
                        # Health-style: raw × confidence_scale × base_scale
                        # Calculate the implied total scale
                        if raw > 0 and points > 0:
                            total_scale = points / raw

                            # Break down the scaling
                            if confidence:
                                confidence_scales = {'high': 5.0, 'medium': 4.0, 'low': 2.5}
                                conf_scale = confidence_scales.get(confidence, 5.0)

                                formula_parts.append(f"{raw:.2f} × {conf_scale:.1f}")
                                explanation_parts.append(f"confidence '{confidence}' → {conf_scale:.1f}× (high=5.0, med=4.0, low=2.5)")

                                if multiplier is not None and multiplier != 1.0:
                                    explanation_parts.append(f"confidence_multiplier: {multiplier:.2f}")
                            else:
                                # Just show the total scale
                                formula_parts.append(f"{raw:.2f} × {total_scale:.1f}")
                                explanation_parts.append(f"base scale: {total_scale:.1f}")

                                if multiplier is not None and multiplier != 1.0:
                                    formula_parts.append(f"× {multiplier:.2f}")
                                    explanation_parts.append(f"multiplier: {multiplier:.2f}")
                else:
                    # No raw value - categorical/boolean bonus
                    if is_primary is not None:
                        if is_primary:
                            formula_parts.append(f"Primary symptom bonus")
                            explanation_parts.append(f"Node exhibits primary symptoms")
                            if coverage_context:
                                explanation_parts.append(f"coverage: {coverage_context}")
                        else:
                            formula_parts.append(f"No bonus (not primary)")
                            explanation_parts.append(f"Secondary symptoms only")
                    elif section_name == 'semantic_bonus':
                        formula_parts.append(f"Semantic evaluation")
                        if coverage_context:
                            explanation_parts.append(f"context: {coverage_context}")
                    else:
                        formula_parts.append(f"Fixed value")

                formula_display = " ".join(formula_parts) if formula_parts else "—"

                # Step 3: Show explanation with ranges
                adjustments_display = " | ".join(explanation_parts) if explanation_parts else "none"

                # Create row with complete calculation
                rows.append(html.Tr([
                    html.Td(
                        section_name.replace('_', ' ').title(),
                        style={
                            'paddingLeft': f'{level * 20 + 10}px',
                            'fontWeight': '500' if level == 0 else 'normal',
                            'borderLeft': '3px solid #0d6efd' if level == 0 else '1px solid #dee2e6'
                        }
                    ),
                    html.Td(raw_display, className="text-center", style={'fontFamily': 'monospace', 'color': '#6c757d'}),
                    html.Td(formula_display, className="text-center small", style={'fontFamily': 'monospace', 'color': '#495057'}),
                    html.Td(adjustments_display, className="small", style={'color': '#6c757d', 'fontSize': '0.85em'}),
                    html.Td(
                        f"{points:.1f}",
                        className="text-end fw-bold",
                        style={
                            'fontFamily': 'monospace',
                            'color': '#0d6efd' if points > 0 else '#6c757d',
                            'fontSize': '1.05em'
                        }
                    )
                ]))
            else:
                # This is a parent node with sub-components
                # Calculate total for this section (excluding metadata fields)
                section_total = 0
                for sub_key, item in section_data.items():
                    if isinstance(item, dict) and 'points' in item:
                        section_total += item.get('points', 0)
                    elif isinstance(item, (int, float)):
                        # Skip metadata fields
                        is_metadata = sub_key in ['trace_degradation', 'degradation', 'ratio', 'factor']
                        if not is_metadata:
                            section_total += item

                # Add section header
                rows.append(html.Tr([
                    html.Td(
                        section_name.replace('_', ' ').title(),
                        colSpan=4,
                        style={
                            'paddingLeft': f'{level * 20 + 10}px',
                            'fontWeight': 'bold',
                            'backgroundColor': '#f8f9fa',
                            'borderTop': '2px solid #dee2e6',
                            'borderLeft': '4px solid #0d6efd'
                        }
                    ),
                    html.Td(
                        f"{section_total:.1f}",
                        className="text-end fw-bold",
                        style={
                            'fontFamily': 'monospace',
                            'backgroundColor': '#f8f9fa',
                            'borderTop': '2px solid #dee2e6',
                            'color': '#0d6efd' if section_total > 0 else '#6c757d',
                            'fontSize': '1.1em'
                        }
                    )
                ], style={'borderTop': '2px solid #dee2e6'}))

                # Recurse into children
                for sub_key, sub_value in section_data.items():
                    # Handle both dict and primitive values
                    if isinstance(sub_value, dict):
                        rows.extend(format_score_section(sub_key, sub_value, level + 1))
                    elif isinstance(sub_value, (int, float)):
                        # Check if this is a metadata field (not a score component)
                        is_metadata = sub_key in ['trace_degradation', 'degradation', 'ratio', 'factor']

                        if is_metadata:
                            # Display as metadata, not score
                            rows.append(html.Tr([
                                html.Td(
                                    f"  ↳ {sub_key.replace('_', ' ').title()} (info)",
                                    className="text-muted fst-italic",
                                    style={'paddingLeft': f'{(level + 1) * 20 + 10}px', 'fontSize': '0.85em'}
                                ),
                                html.Td(f"{sub_value:.2f}", className="text-center small text-muted"),
                                html.Td("—", className="text-center"),
                                html.Td("metadata only", className="small text-muted fst-italic"),
                                html.Td("—", className="text-end text-muted")
                            ]))
                        elif sub_value != 0:
                            # Score component - add description
                            descriptions = {
                                'temporal': 'Time-based correlation bonus',
                                'trace': 'Distributed trace evidence',
                                'logs': 'Log analysis evidence',
                                'impact': 'Traffic impact bonus',
                                'capacity': 'Capacity/zombie pod bonus'
                            }

                            description = descriptions.get(sub_key, 'Direct contribution')

                            rows.append(html.Tr([
                                html.Td(
                                    sub_key.replace('_', ' ').title(),
                                    style={'paddingLeft': f'{(level + 1) * 20 + 10}px'}
                                ),
                                html.Td("—", className="text-center"),
                                html.Td("direct value", className="text-center small text-muted"),
                                html.Td(description, className="small text-muted"),
                                html.Td(
                                    f"{sub_value:.1f}",
                                    className="text-end fw-bold",
                                    style={'fontFamily': 'monospace', 'color': '#0d6efd' if sub_value > 0 else '#6c757d'}
                                )
                            ]))

        return rows

    # Build table rows - handle supplements specially to separate them
    all_rows = []
    section_totals = []

    for section_name, section_data in score_composition.items():
        if section_name == 'supplements' and isinstance(section_data, dict):
            # Separate supplements into individual top-level sections
            for supp_key, supp_value in section_data.items():
                is_metadata = supp_key in ['trace_degradation', 'degradation', 'ratio', 'factor']

                if is_metadata:
                    # Show metadata under the parent component
                    continue
                elif isinstance(supp_value, (int, float)):
                    # Create individual section for this supplement
                    descriptions = {
                        'temporal': 'Time-based correlation',
                        'trace': 'Distributed trace evidence',
                        'logs': 'Log analysis evidence',
                        'impact': 'Traffic impact',
                        'capacity': 'Capacity/zombie pods'
                    }

                    description = descriptions.get(supp_key, 'Additional evidence')

                    # Section header
                    all_rows.append(html.Tr([
                        html.Td(
                            supp_key.replace('_', ' ').title(),
                            colSpan=5,
                            style={
                                'paddingLeft': '10px',
                                'fontWeight': 'bold',
                                'backgroundColor': '#f8f9fa',
                                'borderTop': '2px solid #dee2e6',
                                'borderLeft': '4px solid #0d6efd'
                            }
                        ),
                        html.Td(
                            f"{supp_value:.1f}",
                            className="text-end fw-bold",
                            style={
                                'fontFamily': 'monospace',
                                'backgroundColor': '#f8f9fa',
                                'borderTop': '2px solid #dee2e6',
                                'color': '#0d6efd' if supp_value > 0 else '#6c757d',
                                'fontSize': '1.1em'
                            }
                        )
                    ], style={'borderTop': '2px solid #dee2e6'}))

                    # Detail row
                    if supp_value != 0:
                        all_rows.append(html.Tr([
                            html.Td(
                                supp_key.replace('_', ' ').title(),
                                style={'paddingLeft': '30px'}
                            ),
                            html.Td("—", className="text-center text-muted"),
                            html.Td("direct value", className="text-center small text-muted"),
                            html.Td(description, className="small text-muted"),
                            html.Td(
                                f"{supp_value:.1f}",
                                className="text-end fw-bold",
                                style={'fontFamily': 'monospace', 'color': '#0d6efd'}
                            )
                        ]))

                        # Add metadata if exists
                        metadata_key = f"{supp_key}_degradation"
                        if metadata_key in section_data:
                            meta_value = section_data[metadata_key]
                            all_rows.append(html.Tr([
                                html.Td(
                                    f"  ↳ Degradation (info)",
                                    className="text-muted fst-italic",
                                    style={'paddingLeft': '50px', 'fontSize': '0.85em'}
                                ),
                                html.Td(f"{meta_value:.2f}×", className="text-center small text-muted"),
                                html.Td("—", className="text-center"),
                                html.Td("metadata only", className="small text-muted fst-italic"),
                                html.Td("—", className="text-end text-muted")
                            ]))

                    section_totals.append(supp_value)
        else:
            # Normal section handling
            rows = format_score_section(section_name, section_data)
            all_rows.extend(rows)

            # Calculate section total for final sum (excluding metadata fields)
            if isinstance(section_data, dict) and 'points' in section_data:
                section_totals.append(section_data['points'])
            elif isinstance(section_data, dict):
                total = 0
                for sub_key, item in section_data.items():
                    if isinstance(item, dict) and 'points' in item:
                        total += item.get('points', 0)
                    elif isinstance(item, (int, float)):
                        # Skip metadata fields
                        is_metadata = sub_key in ['trace_degradation', 'degradation', 'ratio', 'factor']
                        if not is_metadata:
                            total += item
                section_totals.append(total)

    calculated_total = sum(section_totals)

    # Check if calculated matches final (for validation)
    score_match = abs(calculated_total - final_score) < 0.1
    match_indicator = "✓" if score_match else "⚠"
    match_color = "#0a5d00" if score_match else "#dc3545"

    # Create the details element
    return html.Details([
        html.Summary("📊 Score Breakdown", style={
            'cursor': 'pointer',
            'fontSize': '0.95em',
            'fontWeight': '600',
            'color': '#003d82',
            'padding': '10px 14px',
            'backgroundColor': '#e7f3ff',
            'borderRadius': '6px',
            'border': '1px solid #0d6efd'
        }),
        html.Div([
            # Explanation header with raw value guide
            html.Div([
                html.P([
                    html.Strong("Score Calculation Flow: ", style={'color': '#0d6efd'}),
                    html.Span("Raw Finding → Formula/Translation → Explanation → Final Points",
                             style={'color': '#495057'})
                ], className="mb-2"),
                html.Div([
                    html.Strong("Raw Value Meanings:", className="d-block mb-2", style={'color': '#212529', 'fontSize': '0.95em'}),
                    html.Ul([
                        html.Li([
                            html.Strong("Base Health: ", style={'color': '#212529'}),
                            html.Span("Integrated health degradation score (0-10 scale). Computed from service + pod metrics. 10 = critically degraded, 0 = healthy",
                                     style={'color': '#495057'})
                        ], className="mb-1", style={'fontSize': '0.9em'}),
                        html.Li([
                            html.Strong("Physics Coverage: ", style={'color': '#212529'}),
                            html.Span("Ratio of system symptoms explained by this node's failure propagation (0.0-1.0 = 0%-100%). Computed by causal graph analysis",
                                     style={'color': '#495057'})
                        ], className="mb-1", style={'fontSize': '0.9em'}),
                        html.Li([
                            html.Strong("Semantic Bonus: ", style={'color': '#212529'}),
                            html.Span("Categorical classification based on symptom type (Primary = root cause symptoms, Secondary = propagated symptoms)",
                                     style={'color': '#495057'})
                        ], className="mb-1", style={'fontSize': '0.9em'}),
                        html.Li([
                            html.Strong("Temporal/Trace/Logs: ", style={'color': '#212529'}),
                            html.Span("Direct point contributions from external evidence sources. Computed by correlation analysis",
                                     style={'color': '#495057'})
                        ], style={'fontSize': '0.9em'})
                    ], className="mb-0", style={'paddingLeft': '20px'})
                ], className="p-3 bg-white rounded border", style={'borderLeftColor': '#0dcaf0', 'borderLeftWidth': '4px'})
            ], className="mb-3"),

            # Score breakdown table
            html.Table([
                html.Thead([
                    html.Tr([
                        html.Th("Component", style={'width': '25%', 'borderBottom': '2px solid #0d6efd'}),
                        html.Th("Raw Value", className="text-center",
                               style={'width': '12%', 'borderBottom': '2px solid #0d6efd'}),
                        html.Th("Formula", className="text-center",
                               style={'width': '18%', 'borderBottom': '2px solid #0d6efd'}),
                        html.Th("Adjustments", style={'width': '28%', 'borderBottom': '2px solid #0d6efd'}),
                        html.Th("Points", className="text-end",
                               style={'width': '17%', 'borderBottom': '2px solid #0d6efd'})
                    ], style={'backgroundColor': '#e7f3ff'})
                ]),
                html.Tbody(all_rows)
            ], className="table table-sm mb-3", style={'fontSize': '0.9em'}),

            # Final sum with validation
            html.Div([
                html.Div([
                    html.Div([
                        html.Strong("Calculated Total: ", className="me-2"),
                        html.Span(f"{calculated_total:.1f}",
                                 className="badge bg-secondary",
                                 style={'fontSize': '1.1em', 'padding': '6px 12px'})
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("Final Score: ", className="me-2"),
                        html.Span(f"{final_score:.1f}",
                                 className="badge bg-primary",
                                 style={'fontSize': '1.2em', 'padding': '8px 16px'}),
                        html.Span(f" {match_indicator}",
                                 className="ms-2",
                                 style={'fontSize': '1.3em', 'color': match_color})
                    ])
                ], className="d-flex flex-column align-items-end")
            ], className="p-3 bg-light rounded border", style={'borderLeft': f'4px solid {match_color}'})
        ], className="p-3")
    ], className="mb-2")


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

            # Score components (needed for calculation display and quick summary)
            integrated_score = result.get('integrated_score', 0)
            temporal_score = result.get('temporal_score', 0)
            trace_score = result.get('trace_score', 0)
            blamed_by = result.get('blamed_by', [])
            is_trace_authoritative = result.get('is_trace_authoritative', False)
            max_outgoing_conf = result.get('max_outgoing_conf', 0)

            # Extract physics coverage from score_composition for quick summary
            score_composition = result.get('score_composition', {})
            physics_data = score_composition.get('physics_coverage', {})
            physics_coverage_bonus = physics_data.get('points', 0) if isinstance(physics_data, dict) else 0
            coverage_score_val = physics_data.get('raw', 0) if isinstance(physics_data, dict) else 0

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

            # 1. Score Calculation - Simplified matrix-based breakdown using score_composition
            if score_composition:
                score_calc_section = create_score_breakdown_matrix(score_composition, score, node)
            else:
                # Fallback for old format without score_composition
                score_calc_section = html.Div([
                    dbc.Alert("Score breakdown not available (old format)", color="info")
                ], className="mb-2")

            additional_details.append(score_calc_section)

            # 2. Symptoms (no duplication - only here)
            if symptoms:
                symptoms_section = html.Details([
                    html.Summary(f"🩺 Symptoms ({len(symptoms)})", style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#664d03',  # Darker brown for better contrast on yellow
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
                # Check if story contains physics narrative markers (ROOT:, Propagated to)
                is_physics_narrative = any('ROOT:' in str(s) or 'Propagated to' in str(s) for s in story)

                story_header = [
                    "📖 Root Cause Story",
                    html.Span(" 🧪 Physics-based", className="badge bg-primary ms-2",
                             style={'fontSize': '0.7em', 'padding': '4px 8px'}) if is_physics_narrative else ""
                ]

                story_section = html.Details([
                    html.Summary(story_header, style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#055160' if not is_physics_narrative else '#003d82',  # Darker colors for better contrast
                        'padding': '10px 14px',
                        'backgroundColor': '#d1ecf1' if not is_physics_narrative else '#e7f3ff',
                        'borderRadius': '6px',
                        'border': '1px solid ' + ('#0dcaf0' if not is_physics_narrative else '#0d6efd')
                    }),
                    html.Div([
                        html.Div([
                            html.Span("This narrative was generated by the Physics Engine, tracing validated causal propagation through the system.",
                                     className="small text-muted d-block mb-3 p-2 bg-light rounded border border-primary")
                        ]) if is_physics_narrative else None,
                        html.Ol([
                            html.Li(step, className="mb-2", style={'fontSize': '0.9em', 'fontFamily': 'monospace' if is_physics_narrative else 'inherit'}) for step in story
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
                        html.Span(f"{pf_degraded_count} degraded", style={'color': '#58151c', 'fontWeight': 'bold', 'marginRight': '8px'}),  # Darker red
                        html.Span(f"{pf_healthy_count} healthy", style={'color': '#0a3622', 'fontWeight': 'bold'})  # Darker green
                    ], style={
                        'cursor': 'pointer',
                        'fontSize': '0.95em',
                        'fontWeight': '600',
                        'color': '#58151c',  # Darker red for better contrast
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
                    'color': '#1c1f23',  # Much darker for better contrast on gray
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

                        # Quick summary line - improved readability with better spacing
                        html.Div([
                            html.Span([
                                html.Strong("Health: ", style={'color': '#212529'}),
                                html.Span(f"{integrated_score:.1f}", style={'color': '#495057'})
                            ], className="me-4", style={'fontSize': '0.9em'}),

                            html.Span([
                                html.Strong("Physics: ", style={'color': '#212529'}),
                                html.Span(f"{physics_coverage_bonus:.1f}", style={'color': '#0d6efd', 'fontWeight': '600'}),
                                html.Span(f" ({coverage_score_val:.0%})", style={'color': '#6c757d', 'fontSize': '0.85em'})
                            ], className="me-4", style={'fontSize': '0.9em'}) if physics_coverage_bonus > 0 else "",

                            html.Span([
                                html.Strong("Temporal: ", style={'color': '#212529'}),
                                html.Span(f"{temporal_score:.1f}", style={'color': '#495057'})
                            ], className="me-4", style={'fontSize': '0.9em'}),

                            html.Span([
                                html.Strong("Trace: ", style={'color': '#212529'}),
                                html.Span(f"{trace_score:.1f}", style={'color': '#495057'}),
                                html.Span(" ★", style={'color': '#ffc107', 'marginLeft': '4px'}) if is_trace_authoritative else ""
                            ], className="me-4", style={'fontSize': '0.9em'}),

                            html.Span([
                                html.Strong(f"{len(symptoms)}", style={'color': '#212529'}),
                                html.Span(" symptoms", style={'color': '#6c757d'})
                            ], style={'fontSize': '0.9em'}) if symptoms else ""
                        ], className="d-flex flex-wrap align-items-center",
                           style={'marginBottom': '16px', 'paddingBottom': '16px', 'borderBottom': '1px solid #e9ecef', 'gap': '8px'}),

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
