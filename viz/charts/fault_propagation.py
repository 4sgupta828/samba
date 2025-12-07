"""
Enhanced Fault Propagation Analysis UI

Simple, focused display of SOTA fault propagation analysis results.
"""

import sys
import os
import subprocess

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dash import html
import dash_bootstrap_components as dbc


def run_enhanced_analysis(episode_dir):
    """Run enhanced fault propagation analysis and capture output"""
    try:
        # Get the path to analyze_propagation.py
        script_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'analyze_propagation.py'
        ))

        # Run the new enhanced analyzer for text output
        result = subprocess.run(
            [sys.executable, script_path, episode_dir],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            return None, None, f"Analysis failed:\n{result.stderr}"

        text_output = result.stdout

        # Also run with --json-only to get the enhanced JSON
        json_result = subprocess.run(
            [sys.executable, script_path, episode_dir, '--json-only'],
            capture_output=True,
            text=True,
            timeout=120
        )

        json_output = None
        if json_result.returncode == 0:
            json_output = json_result.stdout

        return text_output, json_output, None

    except subprocess.TimeoutExpired:
        return None, None, "Analysis timed out (>120s). Try analyzing a smaller episode."
    except Exception as e:
        return None, None, f"Error running analysis: {str(e)}"


def create_fault_propagation_analysis(episode_dir):
    """
    Create fault propagation analysis view from pre-computed analysis.

    Loads and displays the existing fault_propagation.json file.
    """
    import json

    try:
        print(f"Loading fault propagation analysis from {episode_dir}")

        # Load the pre-computed fault propagation analysis
        fault_propagation_path = os.path.join(episode_dir, 'fault_propagation.json')

        if not os.path.exists(fault_propagation_path):
            return html.Div([
                dbc.Alert([
                    html.H4("No Analysis Found", className="alert-heading"),
                    html.P(f"No fault_propagation.json found in {episode_dir}"),
                    html.Hr(),
                    html.P("This episode may have been generated without analysis enabled.",
                           className="mb-0")
                ], color="warning")
            ])

        with open(fault_propagation_path, 'r') as f:
            analysis_data = json.load(f)

        print("  ✓ Analysis data loaded!")

        # Extract key information
        root_cause = analysis_data.get('root_cause', {})
        root_cause_node = root_cause.get('node_id', 'Unknown')
        fault_type = root_cause.get('fault_type', 'Unknown')

        # Load label for scenario info
        label_path = os.path.join(episode_dir, 'label.json')
        scenario = "Unknown"
        if os.path.exists(label_path):
            with open(label_path, 'r') as f:
                label_data = json.load(f)
                scenario = label_data.get('scenario', 'Unknown')

        # Get propagation statistics
        prop_stats = analysis_data.get('propagation_statistics', {})
        total_impacted = prop_stats.get('total_impacted_nodes', 0)

        # Get node reports
        node_reports = analysis_data.get('node_reports', [])

        # Create summary of impacted nodes
        impacted_nodes_summary = []
        # Sort by severity score
        sorted_reports = sorted(node_reports,
                               key=lambda x: x.get('overall_severity_score', 0),
                               reverse=True)[:10]  # Top 10

        for report in sorted_reports:
            node_id = report.get('node_id', 'Unknown')
            severity_score = report.get('overall_severity_score', 0)
            severity = report.get('overall_severity', 'UNKNOWN')
            is_root = node_id == root_cause_node

            # Color based on severity
            severity_colors = {
                'CRITICAL': '#dc3545',
                'HIGH': '#fd7e14',
                'MEDIUM': '#ffc107',
                'LOW': '#17a2b8'
            }
            color = severity_colors.get(severity, '#6c757d')

            impacted_nodes_summary.append(
                html.Li([
                    html.Strong(node_id, style={'color': color}),
                    html.Span(f" - {severity} (score: {severity_score:.2f})", className="text-muted small"),
                    html.Span(" 🎯 ROOT CAUSE", className="badge bg-danger ms-2") if is_root else ""
                ])
            )

        # Format the full JSON for display
        json_output = json.dumps(analysis_data, indent=2)

        # Create layout
        layout = html.Div([
            # Header card
            dbc.Card([
                dbc.CardBody([
                    html.H3([
                        html.Span("🔍 ", style={'fontSize': '1.2em'}),
                        "Fault Propagation Analysis"
                    ], className="mb-3"),

                    dbc.Row([
                        dbc.Col([
                            html.Strong("Scenario: ", className="text-muted"),
                            html.Span(scenario)
                        ], width=12, className="mb-2"),
                        dbc.Col([
                            html.Strong("Root Cause: ", className="text-muted"),
                            html.Span(root_cause_node, className="text-danger", style={'fontWeight': 'bold'})
                        ], width=6, className="mb-2"),
                        dbc.Col([
                            html.Strong("Fault Type: ", className="text-muted"),
                            html.Span(fault_type, className="text-warning")
                        ], width=6, className="mb-2"),
                    ]),

                    html.Hr(className="my-3"),

                    dbc.Row([
                        dbc.Col([
                            html.Strong("Total Impacted Nodes: ", className="text-muted"),
                            html.Span(str(total_impacted), className="text-info", style={'fontSize': '1.2em', 'fontWeight': 'bold'})
                        ], width=12, className="mb-3"),
                    ]),

                    # Top impacted nodes
                    html.Div([
                        html.H6("Top Impacted Nodes:", className="mb-2"),
                        html.Ul(impacted_nodes_summary, className="small")
                    ]) if impacted_nodes_summary else html.Div()
                ])
            ], className="mb-3 shadow-sm"),

            # Full JSON Data Section (collapsible)
            dbc.Card([
                dbc.CardHeader([
                    html.H5("📄 Complete Analysis Data (JSON)", className="mb-0")
                ]),
                dbc.CardBody([
                    html.Details([
                        html.Summary([
                            html.Strong("Click to expand full JSON data"),
                            html.Span(" (includes all analysis fields and node reports)", className="text-muted small ms-2")
                        ], style={'cursor': 'pointer', 'padding': '10px', 'backgroundColor': '#f8f9fa',
                                 'borderRadius': '5px', 'fontWeight': 'bold'}),
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

        print("  ✓ Layout created successfully!")
        return layout

    except Exception as e:
        print(f"  ✗ Error in create_fault_propagation_analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return html.Div([
            dbc.Alert([
                html.H4("Error Loading Analysis", className="alert-heading"),
                html.P(str(e)),
                html.Hr(),
                html.Pre(traceback.format_exc(), style={'fontSize': '0.8em'})
            ], color="danger")
        ])
