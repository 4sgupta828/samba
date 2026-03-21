"""
Forensic Analysis UI

Display of comprehensive forensic analysis results.
"""

import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dash import html
import dash_bootstrap_components as dbc


def create_forensic_analysis(episode_dir):
    """
    Create forensic analysis view.

    Simple, focused display of comprehensive forensic analysis.
    """
    try:
        print(f"Loading forensic analysis for {episode_dir}")

        # Load the forensic analysis JSON
        forensic_path = os.path.join(episode_dir, 'forensic_analysis.json')

        if not os.path.exists(forensic_path):
            return html.Div([
                dbc.Alert([
                    html.H4("No Forensic Analysis Found", className="alert-heading"),
                    html.P("Forensic analysis has not been generated for this episode yet."),
                    html.Hr(),
                    html.P([
                        "Run: ",
                        html.Code("python -m analysis.forensic_analyzer <episode_dir>"),
                        " to generate the analysis."
                    ], className="mb-0")
                ], color="warning")
            ])

        with open(forensic_path, 'r') as f:
            forensic_data = json.load(f)

        print("  ✓ Forensic analysis loaded!")

        # Extract summary information
        summary = forensic_data.get('summary', {})
        episode_id = forensic_data.get('episode_id', 'Unknown')
        root_cause = forensic_data.get('root_cause_component', 'Unknown')
        fault_type = forensic_data.get('fault_type', 'Unknown')
        system_recovered = forensic_data.get('system_recovered', False)

        # Extract key metrics
        total_bottlenecks = summary.get('total_bottlenecks', 0)
        total_crashes = summary.get('total_crashes', 0)
        crashes_recovered = summary.get('crashes_recovered', 0)
        total_cascades = summary.get('total_cascades', 0)
        circuit_breaker_events = summary.get('total_circuit_breaker_events', 0)
        num_recommendations = len(forensic_data.get('recovery_recommendations', []))

        # Create layout with header and raw output
        layout = html.Div([
            # Header card
            dbc.Card([
                dbc.CardBody([
                    html.H3([
                        html.Span("🔬 ", style={'fontSize': '1.2em'}),
                        "Forensic Analysis"
                    ], className="mb-3"),

                    dbc.Row([
                        dbc.Col([
                            html.Strong("Episode: ", className="text-muted"),
                            html.Span(episode_id)
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

                    # Key Findings Summary
                    html.H5("Key Findings", className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4(str(total_bottlenecks), className="text-primary mb-0"),
                                    html.Small("Bottlenecks Detected", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4(f"{total_crashes}/{crashes_recovered}", className="text-warning mb-0"),
                                    html.Small("Crashes/Recovered", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4(str(total_cascades), className="text-danger mb-0"),
                                    html.Small("Cascades Detected", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                    ], className="mb-3"),

                    dbc.Row([
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4(str(circuit_breaker_events), className="text-info mb-0"),
                                    html.Small("Circuit Breaker Events", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4("✓" if system_recovered else "✗",
                                           className=f"text-{'success' if system_recovered else 'danger'} mb-0"),
                                    html.Small("System Recovery", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            dbc.Card([
                                dbc.CardBody([
                                    html.H4(str(num_recommendations), className="text-success mb-0"),
                                    html.Small("Recommendations", className="text-muted")
                                ])
                            ], className="text-center")
                        ], width=4),
                    ]),

                    html.Hr(className="my-3"),

                    dbc.Row([
                        dbc.Col([
                            dbc.Badge("✓ Bottleneck Analysis", color="primary", className="me-2"),
                            dbc.Badge("✓ Crash Detection", color="primary", className="me-2"),
                            dbc.Badge("✓ Cascade Detection", color="primary", className="me-2"),
                            dbc.Badge("✓ Health Tracking", color="primary", className="me-2"),
                            dbc.Badge("✓ Recovery Recommendations", color="primary", className="me-2"),
                        ])
                    ]),

                    html.P([
                        "Comprehensive post-simulation analysis: ",
                        "bottleneck detection, crash analysis, cascade tracking, queue analysis, and recovery recommendations."
                    ], className="text-muted small mt-2 mb-0")
                ])
            ], className="mb-3 shadow-sm"),

            # Full JSON Data Section (collapsible)
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("📄 Complete Forensic Analysis (JSON)", className="mb-0 d-inline-block"),
                        dbc.Badge("11 Analysis Phases", color="success", className="ms-2"),
                    ])
                ]),
                dbc.CardBody([
                    dbc.Alert([
                        html.Strong("Forensic Analysis includes:"),
                        html.Ul([
                            html.Li("Component Degradation: Per-component degradation percentages with baseline metrics"),
                            html.Li("Bottleneck Analysis: CPU, memory, thread pool, connection pool, queue depth bottlenecks"),
                            html.Li("Crash Analysis: Component crashes, recovery attempts, crash loops"),
                            html.Li("Cascade Detection: Failure cascades and propagation chains"),
                            html.Li("Queue Analysis: Queue backlogs and producer/consumer health"),
                            html.Li("Health Tracking: System health timeline and state transitions"),
                            html.Li("Circuit Breaker Events: Circuit breaker activations and recoveries"),
                            html.Li("Recovery Recommendations: Actionable suggestions for system improvement")
                        ], className="mb-0 small")
                    ], color="info", className="mb-3"),

                    # JSON output display
                    html.Details([
                        html.Summary([
                            html.Strong("Click to expand full JSON data"),
                            html.Span(" (includes all forensic analysis fields)", className="text-muted small ms-2")
                        ], style={'cursor': 'pointer', 'padding': '10px', 'backgroundColor': '#f8f9fa',
                                 'borderRadius': '5px', 'fontWeight': 'bold'}),
                        html.Pre(
                            json.dumps(forensic_data, indent=2),
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
        print(f"  ✗ Error in create_forensic_analysis: {str(e)}")
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
