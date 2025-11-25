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

        # Run the new enhanced analyzer
        result = subprocess.run(
            [sys.executable, script_path, episode_dir],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            return result.stdout, None
        else:
            return None, f"Analysis failed:\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return None, "Analysis timed out (>120s). Try analyzing a smaller episode."
    except Exception as e:
        return None, f"Error running analysis: {str(e)}"


def create_fault_propagation_analysis(episode_dir):
    """
    Create enhanced fault propagation analysis view.

    Simple, focused display of comprehensive statistical analysis.
    """
    try:
        print(f"Starting enhanced fault propagation analysis for {episode_dir}")

        # Run enhanced analysis
        print("  Running SOTA analysis...")
        output, error = run_enhanced_analysis(episode_dir)

        if error:
            print(f"  ✗ Error: {error}")
            return html.Div([
                dbc.Alert([
                    html.H4("Analysis Failed", className="alert-heading"),
                    html.P(error),
                    html.Hr(),
                    html.P("Check that the episode directory contains label.json, topology.json, and metrics.jsonl",
                           className="mb-0")
                ], color="danger")
            ])

        print("  ✓ Analysis complete!")

        # Parse output to extract key summary info
        lines = output.split('\n')
        scenario = "Unknown"
        fault_type = "Unknown"
        root_cause = "Unknown"

        for line in lines:
            if "Root Cause:" in line:
                root_cause = line.split("Root Cause:")[1].strip()
            elif "Fault Type:" in line:
                fault_type = line.split("Fault Type:")[1].strip()
            elif "Scenario:" in line:
                scenario = line.split("Scenario:")[1].strip()

        # Create layout with header and raw output
        layout = html.Div([
            # Header card
            dbc.Card([
                dbc.CardBody([
                    html.H3([
                        html.Span("🔍 ", style={'fontSize': '1.2em'}),
                        "Enhanced Fault Propagation Analysis"
                    ], className="mb-3"),

                    dbc.Row([
                        dbc.Col([
                            html.Strong("Scenario: ", className="text-muted"),
                            html.Span(scenario)
                        ], width=12, className="mb-2"),
                        dbc.Col([
                            html.Strong("Root Cause: ", className="text-muted"),
                            html.Span(root_cause, className="text-info")
                        ], width=6, className="mb-2"),
                        dbc.Col([
                            html.Strong("Fault Type: ", className="text-muted"),
                            html.Span(fault_type, className="text-warning")
                        ], width=6, className="mb-2"),
                    ]),

                    html.Hr(className="my-3"),

                    dbc.Row([
                        dbc.Col([
                            dbc.Badge("✓ Statistical Rigor", color="success", className="me-2"),
                            dbc.Badge("✓ Effect Sizes", color="success", className="me-2"),
                            dbc.Badge("✓ Pattern Analysis", color="success", className="me-2"),
                            dbc.Badge("✓ Changepoint Detection", color="success", className="me-2"),
                        ])
                    ]),

                    html.P([
                        "Comprehensive analysis using SOTA statistical methods: ",
                        "Mann-Whitney U, Cohen's d, KL divergence, ACF, PELT changepoint detection, and more."
                    ], className="text-muted small mt-2 mb-0")
                ])
            ], className="mb-3 shadow-sm"),

            # Analysis output card
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("📊 Detailed Analysis Report", className="mb-0 d-inline-block"),
                        dbc.Badge("SOTA Statistical Methods", color="primary", className="ms-2"),
                    ])
                ]),
                dbc.CardBody([
                    # Quick guide
                    dbc.Alert([
                        html.Strong("Report includes:"),
                        " Impact summary by severity • Propagation timing & delays • ",
                        "Top impacted nodes with metric details (effect size, direction, variance, patterns) • ",
                        "Validation of fault injection quality"
                    ], color="info", className="mb-3 small"),

                    # Raw output display
                    html.Pre(
                        output,
                        style={
                            'backgroundColor': '#1e1e1e',
                            'color': '#d4d4d4',
                            'padding': '20px',
                            'borderRadius': '5px',
                            'overflow': 'auto',
                            'maxHeight': '1200px',
                            'fontSize': '0.9em',
                            'lineHeight': '1.6',
                            'whiteSpace': 'pre-wrap',
                            'fontFamily': "'Fira Code', 'Courier New', monospace"
                        }
                    )
                ])
            ], className="shadow-sm")
        ])

        print("  ✓ Layout created successfully!")
        return layout

    except Exception as e:
        print(f"  ✗ Error in create_fault_propagation_analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return html.Div([
            dbc.Alert([
                html.H4("Unexpected Error", className="alert-heading"),
                html.P(str(e)),
                html.Hr(),
                html.Pre(traceback.format_exc(), style={'fontSize': '0.8em'})
            ], color="danger")
        ])
