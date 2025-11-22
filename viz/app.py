"""
Samba Telemetry Dashboard

A streamlined Flask + Dash application for visualizing training episode data
from the Samba GNN training data generator.
"""

import os
from flask import Flask
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from data_loader import list_episodes, load_episode

# Import chart modules (will be created)
from charts.topology import create_topology_chart
from charts.metrics_overview import create_golden_signals_dashboard
from charts.component_drilldown import create_component_drilldown
from charts.propagation_timeline import create_propagation_timeline

# Configuration
DATA_DIR = os.environ.get('SAMBA_DATA_DIR', '../data/final_validation')
PORT = int(os.environ.get('PORT', 8050))

# Initialize Flask app
server = Flask(__name__)

# Configure Flask to serve static files
@server.route('/static/css/<path:filename>')
def serve_css(filename):
    from flask import send_from_directory
    import os
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'static', 'css'),
        filename
    )

# Initialize Dash app with Bootstrap theme and custom dark theme
app = dash.Dash(
    __name__,
    server=server,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        '/static/css/dark_theme.css'
    ],
    suppress_callback_exceptions=True
)

app.title = "Samba Telemetry Dashboard"

# Global state (in-memory cache for loaded episode)
current_episode_data = {}


def create_metadata_card(label_data):
    """Create a card displaying episode metadata and ground truth."""
    return dbc.Card([
        dbc.CardHeader(html.H4(f"📋 Episode {label_data['episode']}")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Strong("Level: "),
                    html.Span(f"{label_data['level']} - "),
                    html.Span(label_data['scenario'])
                ], width=12),
            ]),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    html.Strong("Root Cause: "),
                    html.Span(label_data['root_cause_node'],
                             style={'color': 'red', 'fontWeight': 'bold'}),
                    html.Span(f" ({label_data['root_cause_role']})"),
                ], width=6),
                dbc.Col([
                    html.Strong("Fault Type: "),
                    html.Span(label_data['fault_type']),
                ], width=6),
            ]),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    html.Strong("Timeline: "),
                    html.Span(f"Fault starts at {label_data['fault_start_time']}s, "),
                    html.Span(f"duration {label_data['fault_duration']}s"),
                ], width=12),
            ]),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    html.Strong("Topology: "),
                    html.Span(f"{label_data['topology']['nodes']} nodes, "),
                    html.Span(f"{label_data['topology']['edges']} edges | "),
                    html.Strong("Frontends: "),
                    html.Span(", ".join(label_data['topology']['frontends'])),
                ], width=12),
            ]),
        ])
    ], className="mb-4")


# App layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.H1("🔍 Samba Telemetry Dashboard", className="text-center mt-3 mb-2"),
            html.P("Visualize GNN training episode data with topology, metrics, and failure propagation",
                   className="text-center text-muted mb-4")
        ])
    ]),

    # Episode selector
    dbc.Row([
        dbc.Col([
            dbc.Label("Select Episode:", html_for="episode-dropdown"),
            dcc.Dropdown(
                id='episode-dropdown',
                options=[],  # Will be populated on load
                value=None,
                placeholder="Select an episode...",
                clearable=False
            ),
        ], width=4),
        dbc.Col([
            dbc.Button("Load Episode", id="load-button", color="primary", className="mt-4"),
        ], width=2),
        dbc.Col([
            dbc.Spinner(html.Div(id="loading-status"), size="sm", spinner_class_name="mt-4"),
        ], width=6),
    ], className="mb-4"),

    # Metadata card (hidden until episode loaded)
    dbc.Row([
        dbc.Col([
            html.Div(id='metadata-card', children=[])
        ])
    ]),

    # Main visualization panels
    dbc.Row([
        # Left column: Topology
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("🗺️ System Topology", className="mb-0 d-inline-block"),
                        html.Div([
                            html.Span("Show: ", style={'marginRight': '8px', 'fontSize': '0.85rem', 'color': '#6c757d'}),
                            dbc.Checklist(
                                id='topology-filters',
                                options=[],  # Will be populated dynamically
                                value=[],     # Will be populated dynamically
                                inline=True,
                                switch=True,
                                className="d-inline-block",
                                style={'fontSize': '0.85rem'}
                            )
                        ], className="float-end")
                    ], className="clearfix")
                ]),
                dbc.CardBody([
                    dcc.Graph(id='topology-graph', style={'height': '600px'}, config={'displayModeBar': True})
                ], style={'padding': '10px'})
            ], className="shadow-sm")
        ], width=6, className="mb-3"),

        # Right column: Golden Signals
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("📈 Golden Signals", className="mb-0")),
                dbc.CardBody([
                    html.Div(id='golden-signals-dashboard')
                ], style={'padding': '10px'})
            ], className="shadow-sm")
        ], width=6, className="mb-3"),
    ], className="mb-3"),

    # Component drill-down (hidden until node clicked)
    dbc.Row([
        dbc.Col([
            dbc.Collapse(
                dbc.Card([
                    dbc.CardHeader(html.H5("🔍 Component Drill-Down", className="mb-0")),
                    dbc.CardBody([
                        html.Div(id='component-drilldown')
                    ], style={'padding': '15px'})
                ], className="shadow-sm"),
                id="drilldown-collapse",
                is_open=False
            )
        ])
    ], className="mb-3"),

    # Failure propagation timeline
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("🌊 Failure Propagation Timeline", className="mb-0")),
                dbc.CardBody([
                    html.Div(id='propagation-timeline')
                ], style={'padding': '15px'})
            ], className="shadow-sm")
        ])
    ], className="mb-3"),

    # Hidden div to store episode data
    dcc.Store(id='episode-data-store'),

], fluid=True)


# Callbacks

@app.callback(
    Output('episode-dropdown', 'options'),
    Output('episode-dropdown', 'value'),
    Input('episode-dropdown', 'id')  # Trigger on page load
)
def populate_episodes(_):
    """Populate episode dropdown on page load."""
    episodes = list_episodes(DATA_DIR)
    options = [{'label': ep, 'value': ep} for ep in episodes]
    default_value = episodes[0] if episodes else None
    return options, default_value


@app.callback(
    Output('episode-data-store', 'data'),
    Output('loading-status', 'children'),
    Output('metadata-card', 'children'),
    Input('load-button', 'n_clicks'),
    State('episode-dropdown', 'value'),
    prevent_initial_call=True
)
def load_episode_data(n_clicks, episode_id):
    """Load episode data when button is clicked."""
    if not episode_id:
        return None, "No episode selected", []

    try:
        # Load episode
        episode_data = load_episode(episode_id, DATA_DIR)

        # Create metadata card
        metadata_card = create_metadata_card(episode_data['label'])

        # Store episode ID (we'll keep full data in global cache to avoid serialization)
        global current_episode_data
        current_episode_data[episode_id] = episode_data

        return episode_id, f"✓ Loaded {episode_id}", metadata_card

    except Exception as e:
        return None, f"❌ Error: {str(e)}", []


@app.callback(
    Output('topology-filters', 'options'),
    Output('topology-filters', 'value'),
    Input('episode-data-store', 'data')
)
def populate_topology_filters(episode_id):
    """Populate topology filters based on node types in the episode."""
    if not episode_id or episode_id not in current_episode_data:
        return [], []

    episode_data = current_episode_data[episode_id]
    # Use physical topology to get ALL available node types (including ComputeAgent)
    graph = episode_data['topology_graph']

    # Get all unique node types in the graph
    node_types = set()
    for node in graph.nodes():
        node_type = graph.nodes[node].get('type', 'Unknown')
        node_types.add(node_type)

    # Create friendly labels for each type
    type_labels = {
        'RequestGateway': 'Gateway',
        'ApiService': 'Service',
        'SqlDatabase': 'Database',
        'InMemoryCache': 'Cache',
        'MessageQueue': 'Queue',
        'ExternalService': 'External',
        'ComputeInstance': 'Compute',
        'ComputeAgent': 'Agent',
        'Container': 'Container',
        'VM': 'VM',
        'LoadBalancer': 'LB',
    }

    # Sort types for consistent display
    sorted_types = sorted(node_types)

    # Create options
    options = [
        {
            'label': f' {type_labels.get(t, t)}',
            'value': t
        }
        for t in sorted_types
    ]

    # All types EXCEPT ComputeAgent enabled by default (show logical view)
    default_values = [t for t in sorted_types if t != 'ComputeAgent']

    return options, default_values


@app.callback(
    Output('topology-graph', 'figure'),
    Input('episode-data-store', 'data'),
    Input('topology-filters', 'value')
)
def update_topology(episode_id, visible_types):
    """Update topology graph when episode is loaded or filters change."""
    if not episode_id or episode_id not in current_episode_data:
        return {}

    episode_data = current_episode_data[episode_id]

    # Decide which topology to use based on whether ComputeAgent is in visible types
    if visible_types and 'ComputeAgent' in visible_types:
        # User wants to see compute agents - use physical topology
        graph = episode_data['topology_graph']
    else:
        # User filtered out compute agents - use logical topology
        graph = episode_data['logical_topology_graph']

    return create_topology_chart(
        graph,
        episode_data['label'],
        visible_types=visible_types or []
    )


@app.callback(
    Output('golden-signals-dashboard', 'children'),
    Input('episode-data-store', 'data')
)
def update_golden_signals(episode_id):
    """Update golden signals dashboard when episode is loaded."""
    if not episode_id or episode_id not in current_episode_data:
        return html.Div("No data loaded", className="text-muted")

    episode_data = current_episode_data[episode_id]
    return create_golden_signals_dashboard(
        episode_data['metrics_df'],
        episode_data['label']
    )


@app.callback(
    Output('component-drilldown', 'children'),
    Output('drilldown-collapse', 'is_open'),
    Input('topology-graph', 'clickData'),
    State('episode-data-store', 'data')
)
def update_component_drilldown(click_data, episode_id):
    """Update component drill-down when topology node is clicked."""
    if not click_data or not episode_id or episode_id not in current_episode_data:
        return html.Div("Click a node in the topology to see details", className="text-muted"), False

    try:
        # Extract component ID from click data
        point = click_data['points'][0]

        # Use customdata which contains the node ID directly
        component_id = point.get('customdata')

        # Fallback methods if customdata is not available
        if not component_id:
            if 'hovertext' in point:
                hovertext = point['hovertext']
                # Extract ID from "<b>component_id</b><br>..." format
                component_id = hovertext.split('<b>')[1].split('</b>')[0] if '<b>' in hovertext else None

        if not component_id:
            # Final fallback to text field
            text = point.get('text', '')
            component_id = text.split('<br>')[0] if text else None

        if not component_id:
            return html.Div("Could not identify component", className="text-danger"), False

        episode_data = current_episode_data[episode_id]

        # Use physical topology for node type lookup (has all nodes)
        drilldown_content = create_component_drilldown(
            component_id,
            episode_data['metrics_df'],
            episode_data['topology_graph'],
            episode_data['label']
        )

        return drilldown_content, True

    except Exception as e:
        return html.Div(f"Error loading component details: {str(e)}", className="text-danger"), False


@app.callback(
    Output('propagation-timeline', 'children'),
    Input('episode-data-store', 'data')
)
def update_propagation_timeline(episode_id):
    """Update propagation timeline when episode is loaded."""
    if not episode_id or episode_id not in current_episode_data:
        return html.Div("No data loaded", className="text-muted")

    episode_data = current_episode_data[episode_id]
    # Use logical topology for propagation analysis (cleaner view)
    return create_propagation_timeline(
        episode_data['metrics_df'],
        episode_data['logical_topology_graph'],
        episode_data['label'],
        episode_data['ground_truth']
    )


if __name__ == '__main__':
    print(f"Starting Samba Telemetry Dashboard...")
    print(f"Data directory: {DATA_DIR}")
    print(f"Loading episodes...")

    episodes = list_episodes(DATA_DIR)
    print(f"Found {len(episodes)} episodes: {episodes}")

    print(f"\n🚀 Dashboard running at http://localhost:{PORT}")
    app.run(debug=True, host='0.0.0.0', port=PORT)
