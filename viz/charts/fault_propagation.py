"""
Fault Propagation Analysis Chart

Interactive visualization of fault propagation analysis with clickable nodes
and chronological timeline.
"""

import sys
import os
import subprocess
# Add parent directory to path to import analyze_fault_propagation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from analyze_fault_propagation import FaultPropagationAnalyzer


def get_raw_text_output(episode_dir):
    """Get raw text output from command-line analysis"""
    try:
        # Get the path to analyze_fault_propagation.py
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'analyze_fault_propagation.py'))

        # Run the script and capture output
        result = subprocess.run(
            [sys.executable, script_path, episode_dir],
            capture_output=True,
            text=True,
            timeout=60
        )

        return result.stdout if result.returncode == 0 else f"Error running analysis:\n{result.stderr}"
    except Exception as e:
        return f"Error capturing raw output: {str(e)}"


def run_fault_analysis(episode_dir):
    """Run fault propagation analysis on an episode"""
    print(f"  [1/4] Creating analyzer for {episode_dir}...")
    analyzer = FaultPropagationAnalyzer(episode_dir, silent=True)

    print(f"  [2/4] Loading data...")
    analyzer.load_data()

    print(f"  [3/4] Analyzing propagation chain...")
    results = analyzer.analyze_propagation_chain()

    print(f"  [4/4] Preparing results...")
    return {
        'label': analyzer.label,
        'topology': analyzer.topology,
        'results': results,
        'analyzer': analyzer
    }


def create_timeline_chart(analysis_data):
    """Create interactive timeline chart of fault propagation"""
    label = analysis_data['label']
    results = analysis_data['results']

    # Collect timeline events
    timeline_events = []
    for node, data in results.items():
        if data["metrics"]:
            for metric_name, impacts in data["metrics"].items():
                for impact_data in impacts:
                    for change_key, change_val in impact_data["impact"]["changes"].items():
                        if "multiplier" in change_val and "significance" in change_val:
                            significance = change_val["significance"]
                            if significance in ["CRITICAL", "HIGH"]:
                                metric_type = impact_data["impact"].get("metric_type", "other")
                                timeline_events.append({
                                    "time": impact_data["time"],
                                    "node": node,
                                    "metric": metric_name,
                                    "significance": significance,
                                    "metric_type": metric_type,
                                    "change": change_val,
                                    "distance": data["distance"]
                                })

    # Sort by time and distance
    timeline_events.sort(key=lambda x: (x["time"], x["distance"]))

    # Create figure
    fig = go.Figure()

    # Group by significance for color coding
    for significance in ["CRITICAL", "HIGH"]:
        events_sig = [e for e in timeline_events if e["significance"] == significance]
        if not events_sig:
            continue

        times = [e["time"] for e in events_sig]
        nodes = [f"{e['node']}<br>{e['metric']}" for e in events_sig]
        multipliers = [e["change"]["multiplier"] for e in events_sig]
        distances = [e["distance"] for e in events_sig]

        color = "red" if significance == "CRITICAL" else "orange"
        symbol = "circle" if events_sig[0]["metric_type"] == "error" else "diamond"

        fig.add_trace(go.Scatter(
            x=times,
            y=multipliers,
            mode='markers+text',
            name=significance,
            marker=dict(
                size=[15 + d*5 for d in distances],  # Size by layer
                color=color,
                symbol=symbol,
                line=dict(width=2, color='white')
            ),
            text=[e["node"] for e in events_sig],
            textposition="top center",
            hovertemplate='<b>%{text}</b><br>' +
                         'Time: %{x}s<br>' +
                         'Impact: %{y:.1f}x<br>' +
                         '<extra></extra>',
            customdata=nodes
        ))

    # Add fault injection markers
    fig.add_vline(x=label['fault_start_time'], line_dash="dash",
                  line_color="yellow", annotation_text="Fault Start")
    fig.add_vline(x=label['fault_full_effect_time'], line_dash="dash",
                  line_color="red", annotation_text="Full Effect")

    fig.update_layout(
        title="Fault Propagation Timeline",
        xaxis_title="Time (seconds)",
        yaxis_title="Impact Multiplier",
        yaxis_type="log",
        hovermode='closest',
        height=500,
        template="plotly_dark"
    )

    return dcc.Graph(figure=fig, id='timeline-chart')


def create_impact_summary_cards(analysis_data):
    """Create summary cards for impacted nodes"""
    results = analysis_data['results']
    label = analysis_data['label']

    # Count by severity
    critical_count = 0
    high_count = 0
    error_count = 0

    for node, data in results.items():
        if data["metrics"]:
            for metric_name, impacts in data["metrics"].items():
                for impact_data in impacts:
                    for change_key, change_val in impact_data["impact"]["changes"].items():
                        if "significance" in change_val:
                            if change_val["significance"] == "CRITICAL":
                                critical_count += 1
                            elif change_val["significance"] == "HIGH":
                                high_count += 1
                        if impact_data["impact"].get("metric_type") == "error":
                            error_count += 1

    cards = dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("🔴", className="text-center"),
                    html.H3(critical_count, className="text-center text-danger"),
                    html.P("Critical Issues", className="text-center")
                ])
            ], color="dark")
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("🟠", className="text-center"),
                    html.H3(high_count, className="text-center text-warning"),
                    html.P("High Issues", className="text-center")
                ])
            ], color="dark")
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("💥", className="text-center"),
                    html.H3(error_count, className="text-center text-danger"),
                    html.P("Error Metrics", className="text-center")
                ])
            ], color="dark")
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("📊", className="text-center"),
                    html.H3(len(results), className="text-center text-info"),
                    html.P("Nodes Analyzed", className="text-center")
                ])
            ], color="dark")
        ], width=3),
    ], className="mb-4")

    return cards


def create_layer_analysis(analysis_data):
    """Create layered analysis view with clickable nodes"""
    results = analysis_data['results']
    label = analysis_data['label']

    # Group by distance
    layers = {}
    for node, data in results.items():
        dist = data["distance"]
        if dist not in layers:
            layers[dist] = []
        layers[dist].append((node, data))

    layer_cards = []

    for distance in sorted(layers.keys()):
        nodes = layers[distance]
        layer_title = "🎯 Root Cause" if distance == 0 else f"📍 Layer {distance} ({distance} hop{'s' if distance > 1 else ''} from root)"

        node_items = []
        for node, data in nodes:
            # Find most significant impact
            max_significance = "LOW"
            max_impact = None
            impact_symbol = "📊"

            if data["metrics"]:
                for metric_name, impacts in data["metrics"].items():
                    for impact_data in impacts:
                        for change_key, change_val in impact_data["impact"]["changes"].items():
                            if "significance" in change_val:
                                sig = change_val["significance"]
                                if sig in ["CRITICAL", "HIGH"]:
                                    if max_significance == "LOW" or \
                                       (sig == "CRITICAL" and max_significance == "HIGH"):
                                        max_significance = sig
                                        max_impact = (metric_name, change_val)
                                        metric_type = impact_data["impact"].get("metric_type", "other")
                                        if metric_type == "error":
                                            impact_symbol = "🔴" if sig == "CRITICAL" else "🟠"
                                        else:
                                            impact_symbol = "⚠️" if sig == "CRITICAL" else "📈"

            # Create node badge
            badge_color = "danger" if max_significance == "CRITICAL" else \
                         "warning" if max_significance == "HIGH" else "secondary"

            impact_text = ""
            if max_impact:
                metric_name, change = max_impact
                impact_text = f": {metric_name} ({change['multiplier']:.1f}x)"

            node_items.append(
                dbc.ListGroupItem([
                    html.Span(impact_symbol + " ", style={'fontSize': '1.2em'}),
                    html.Strong(node, id=f"node-{node}"),
                    html.Span(impact_text, className="text-muted ms-2"),
                    dbc.Badge(max_significance, color=badge_color, className="ms-2")
                ], action=True, href=f"#node-{node}")
            )

        layer_cards.append(
            dbc.Card([
                dbc.CardHeader(html.H5(layer_title)),
                dbc.CardBody([
                    dbc.ListGroup(node_items, flush=True)
                ])
            ], className="mb-3")
        )

    return html.Div(layer_cards)


def create_fault_propagation_analysis(episode_dir):
    """Main function to create complete fault propagation analysis view"""
    try:
        print(f"Starting fault propagation analysis for {episode_dir}")

        # Run analysis
        print("  Running analysis...")
        analysis_data = run_fault_analysis(episode_dir)
        print("  ✓ Analysis complete!")

        # Create layout
        print("  Creating summary cards...")
        summary_cards = create_impact_summary_cards(analysis_data)

        print("  Creating timeline chart...")
        timeline = create_timeline_chart(analysis_data)

        print("  Creating layer analysis...")
        layer_analysis = create_layer_analysis(analysis_data)

        # Get raw text output
        print("  Getting raw text output...")
        raw_output = get_raw_text_output(episode_dir)

        print("  Building final layout...")
        # Create visual view
        visual_view = html.Div([
            # Summary cards
            summary_cards,

            # Timeline chart
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H5("📈 Chronological Timeline")),
                        dbc.CardBody([
                            timeline
                        ])
                    ], className="mb-4")
                ])
            ]),

            # Layer-by-layer analysis
            dbc.Row([
                dbc.Col([
                    html.H4("🔬 Layer-by-Layer Analysis", className="mb-3"),
                    layer_analysis
                ])
            ])
        ])

        # Create raw view
        raw_view = html.Div([
            dbc.Card([
                dbc.CardHeader([
                    html.H5("📄 Raw Analysis Output", className="mb-0 d-inline-block"),
                    dbc.Badge("Command-line format", color="secondary", className="ms-2")
                ]),
                dbc.CardBody([
                    html.Pre(
                        raw_output,
                        style={
                            'backgroundColor': '#1e1e1e',
                            'color': '#d4d4d4',
                            'padding': '20px',
                            'borderRadius': '5px',
                            'overflow': 'auto',
                            'maxHeight': '800px',
                            'fontSize': '0.85em',
                            'lineHeight': '1.5',
                            'whiteSpace': 'pre-wrap'
                        }
                    )
                ])
            ])
        ])

        # Create tabbed layout
        layout = dbc.Card([
            dbc.CardHeader([
                html.H3("🔍 Fault Propagation Analysis", className="mb-2"),
                html.P(f"Analyzing: {analysis_data['label']['scenario']}", className="text-muted mb-3"),
                dbc.Tabs([
                    dbc.Tab(label="📊 Visual", tab_id="visual", label_style={"cursor": "pointer"}),
                    dbc.Tab(label="📄 Raw Output", tab_id="raw", label_style={"cursor": "pointer"}),
                ], id="analysis-tabs", active_tab="visual")
            ]),
            dbc.CardBody([
                html.Div(id='analysis-tab-content', children=[
                    html.Div(visual_view, id='visual-tab', style={'display': 'block'}),
                    html.Div(raw_view, id='raw-tab', style={'display': 'none'})
                ])
            ])
        ], className="shadow-sm")

        # Add clientside callback to handle tab switching
        layout = html.Div([
            layout,
            dcc.Store(id='active-analysis-tab', data='visual')
        ])

        print("  ✓ Layout created successfully!")
        return layout

    except Exception as e:
        print(f"  ✗ Error in create_fault_propagation_analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return html.Div([
            dbc.Alert(f"Error running fault propagation analysis: {str(e)}", color="danger"),
            html.Pre(traceback.format_exc())
        ])
