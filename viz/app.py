"""
Samba Telemetry Dashboard

A streamlined Flask + Dash application for visualizing training episode data
from the Samba GNN training data generator.
"""

import os
import random
from flask import Flask
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from data_loader import list_data_runs, list_episodes, load_episode

# Import chart modules (will be created)
from charts.topology import create_topology_chart
from charts.metrics_overview import create_golden_signals_dashboard
from charts.component_drilldown import create_component_drilldown
from charts.propagation_timeline import create_propagation_timeline

# Configuration
# Default to ../data relative to this file's location
_default_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
BASE_DATA_DIR = os.environ.get('SAMBA_DATA_DIR', _default_data_dir)
PORT = int(os.environ.get('PORT', 8050))

# Default topology size: random between 8-15 nodes
DEFAULT_TOPOLOGY_SIZE = random.randint(8, 15)

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

# Global state for dataset generation
generation_state = {
    'running': False,
    'process': None,
    'start_time': None,
    'config': None,
    'output': [],
    'error': None
}


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
                    html.Span(f"duration {label_data.get('fault_total_duration', label_data.get('fault_duration', 0))}s"),
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

    # Dataset Generator Section (Collapsible)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.H5("🏭 Dataset Generator", className="mb-0 d-inline-block"),
                    dbc.Button("Toggle", id="generator-collapse-button", size="sm", className="float-end", color="secondary")
                ]),
                dbc.Collapse([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Number of Episodes:", html_for="episodes-input"),
                                dbc.Input(
                                    id='episodes-input',
                                    type='number',
                                    value=1,
                                    min=1,
                                    max=1000,
                                    placeholder="Number of episodes to generate"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Topology Size:", html_for="topology-size-input"),
                                dbc.Input(
                                    id='topology-size-input',
                                    type='number',
                                    value=DEFAULT_TOPOLOGY_SIZE,
                                    min=2,
                                    max=100,
                                    placeholder="Number of nodes (8-15 recommended)"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Output Directory:", html_for="output-dir-input"),
                                dbc.Input(
                                    id='output-dir-input',
                                    type='text',
                                    value='data',
                                    placeholder="Output directory (e.g., 'data')"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Random Seed (optional):", html_for="seed-input"),
                                dbc.Input(
                                    id='seed-input',
                                    type='number',
                                    placeholder="Leave empty for random"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label(" ", html_for="verbose-checkbox"),
                                dbc.Checklist(
                                    id='verbose-checkbox',
                                    options=[{'label': ' Verbose Output', 'value': 'verbose'}],
                                    value=[],
                                    switch=True,
                                    className="mt-2"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Button(
                                    "Generate Dataset",
                                    id="generate-button",
                                    color="success",
                                    className="mt-4",
                                    style={'width': '100%'}
                                ),
                            ], width=2),
                        ]),
                        html.Hr(),
                        dbc.Row([
                            dbc.Col([
                                html.Div(id='generation-status', children=[
                                    html.Div("Ready to generate training data", className="text-muted")
                                ]),
                            ])
                        ]),
                    ])
                ], id="generator-collapse", is_open=False)
            ], className="mb-4 shadow-sm")
        ])
    ]),

    # Data run and episode selectors
    dbc.Row([
        dbc.Col([
            dbc.Label("Select Data Run:", html_for="datarun-dropdown"),
            dcc.Dropdown(
                id='datarun-dropdown',
                options=[],  # Will be populated on load
                value=None,
                placeholder="Select a data run...",
                clearable=False
            ),
        ], width=3),
        dbc.Col([
            dcc.Clipboard(target_id="datarun-path-text", id="clipboard-datarun"),
            dbc.Button("📋 Copy Path", id="copy-datarun-button", color="secondary", outline=True, size="sm", className="mt-4"),
            html.Div(id="datarun-path-text", style={"display": "none"}),
            html.Div(id="copy-feedback", className="mt-1 small text-success", style={"minHeight": "20px"}),
        ], width=1),
        dbc.Col([
            dbc.Label("Select Episode:", html_for="episode-dropdown"),
            dcc.Dropdown(
                id='episode-dropdown',
                options=[],  # Will be populated when data run selected
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
        ], width=2),
    ], className="mb-4"),

    # Metadata card (hidden until episode loaded)
    dbc.Row([
        dbc.Col([
            html.Div(id='metadata-card', children=[])
        ])
    ]),

    # Golden Signals (full width at top)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("📈 Golden Signals", className="mb-0")),
                dbc.CardBody([
                    html.Div(id='golden-signals-dashboard')
                ], style={'padding': '10px'})
            ], className="shadow-sm")
        ], width=12)
    ], className="mb-3"),

    # System Topology (full width below)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("🗺️ System Topology", className="mb-0 d-inline-block"),
                        html.Div([
                            html.Span("Layout: ", style={'marginRight': '8px', 'fontSize': '0.85rem', 'color': '#6c757d', 'fontWeight': 'bold'}),
                            dcc.Dropdown(
                                id='topology-layout-selector',
                                options=[
                                    {'label': 'Spring (Force-Directed)', 'value': 'spring'},
                                    {'label': 'Hierarchical', 'value': 'hierarchical'},
                                    {'label': 'Circular', 'value': 'circular'}
                                ],
                                value='hierarchical',
                                clearable=False,
                                className="d-inline-block me-3",
                                style={'width': '200px', 'display': 'inline-block', 'verticalAlign': 'middle'}
                            ),
                            dbc.Checklist(
                                id='use-filtered-topology',
                                options=[{'label': ' Filter by Root Cause', 'value': 'filtered'}],
                                value=[],
                                inline=True,
                                switch=True,
                                className="me-3 d-inline-block",
                                style={'fontSize': '0.85rem', 'fontWeight': 'bold', 'color': '#dc3545'}
                            ),
                            dbc.Checklist(
                                id='hide-healthy-nodes',
                                options=[{'label': ' Hide Healthy Nodes', 'value': 'hide_healthy'}],
                                value=[],
                                inline=True,
                                switch=True,
                                className="me-3 d-inline-block",
                                style={'fontSize': '0.85rem', 'fontWeight': 'bold', 'color': '#28a745'}
                            ),
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
                    dcc.Graph(id='topology-graph', style={'height': '800px'}, config={'displayModeBar': True}),
                    html.Div(id='topology-info', className="text-muted small mt-2")
                ], style={'padding': '10px'})
            ], className="shadow-sm")
        ], width=12)
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

    # Interval for polling generation status
    dcc.Interval(id='generation-poll-interval', interval=2000, disabled=True),

], fluid=True)


# Callbacks

@app.callback(
    Output('datarun-dropdown', 'options'),
    Output('datarun-dropdown', 'value'),
    Input('datarun-dropdown', 'id')  # Trigger on page load
)
def populate_data_runs(_):
    """Populate data run dropdown on page load."""
    runs = list_data_runs(BASE_DATA_DIR)
    options = [
        {
            'label': f"{run['id']} ({run['timestamp']})",
            'value': run['path']
        }
        for run in runs
    ]
    default_value = runs[0]['path'] if runs else None
    return options, default_value


@app.callback(
    Output('episode-dropdown', 'options'),
    Output('episode-dropdown', 'value'),
    Input('datarun-dropdown', 'value')
)
def populate_episodes(data_run_path):
    """Populate episode dropdown when data run is selected."""
    if not data_run_path:
        return [], None

    episodes = list_episodes(data_run_path)
    options = [{'label': ep, 'value': ep} for ep in episodes]
    default_value = episodes[0] if episodes else None
    return options, default_value


@app.callback(
    Output('datarun-path-text', 'children'),
    Output('copy-feedback', 'children'),
    Input('copy-datarun-button', 'n_clicks'),
    State('datarun-dropdown', 'value'),
    prevent_initial_call=True
)
def copy_datarun_path(n_clicks, data_run_path):
    """Copy data run path to clipboard when button is clicked."""
    if not data_run_path:
        return "", "No data run selected"

    # Return the path to be copied and a feedback message
    return data_run_path, "✓ Copied!"


@app.callback(
    Output('episode-data-store', 'data'),
    Output('loading-status', 'children'),
    Output('metadata-card', 'children'),
    Input('load-button', 'n_clicks'),
    State('datarun-dropdown', 'value'),
    State('episode-dropdown', 'value'),
    prevent_initial_call=True
)
def load_episode_data(n_clicks, data_run_path, episode_id):
    """Load episode data when button is clicked."""
    if not episode_id or not data_run_path:
        return None, "No episode or data run selected", []

    try:
        # Load episode
        episode_data = load_episode(episode_id, data_run_path)

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
    Output('use-filtered-topology', 'options'),
    Input('episode-data-store', 'data')
)
def populate_topology_filters(episode_id):
    """Populate topology filters based on node types in the episode."""
    if not episode_id or episode_id not in current_episode_data:
        return [], [], [{'label': ' Filter by Root Cause (unavailable)', 'value': 'filtered', 'disabled': True}]

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

    # All types EXCEPT infrastructure components and pods hidden by default
    # These clutter the topology view - show services instead of individual pods
    infrastructure_types = {'ComputeAgent', 'ComputeNode', 'DeploymentController', 'Pod'}
    default_values = [t for t in sorted_types if t not in infrastructure_types]

    # Configure filtered topology toggle based on availability
    has_filtered = episode_data.get('has_filtered_topology', False)
    if has_filtered:
        filter_options = [{'label': ' Filter by Root Cause', 'value': 'filtered'}]
    else:
        filter_options = [{'label': ' Filter by Root Cause (not generated)', 'value': 'filtered', 'disabled': True}]

    return options, default_values, filter_options


@app.callback(
    Output('topology-graph', 'figure'),
    Output('topology-info', 'children'),
    Input('episode-data-store', 'data'),
    Input('topology-filters', 'value'),
    Input('use-filtered-topology', 'value'),
    Input('hide-healthy-nodes', 'value'),
    Input('topology-layout-selector', 'value')
)
def update_topology(episode_id, visible_types, use_filtered, hide_healthy, layout_type):
    """Update topology graph when episode is loaded or filters change."""
    if not episode_id or episode_id not in current_episode_data:
        return {}, ""

    episode_data = current_episode_data[episode_id]

    # Determine if we should use filtered topology
    use_filtered_topo = 'filtered' in (use_filtered or [])

    # Determine if we should hide healthy nodes
    hide_healthy_nodes = 'hide_healthy' in (hide_healthy or [])

    # Choose graph based on filter setting
    if use_filtered_topo and episode_data.get('has_filtered_topology'):
        # Use filtered topology (only nodes reachable from root cause)
        graph = episode_data['topology_graph_filtered']
        filter_metadata = episode_data.get('topology_filtered', {}).get('filter_metadata', {})

        info_text = (
            f"Showing {filter_metadata.get('reachable_nodes', 0)} nodes reachable from root cause "
            f"({filter_metadata.get('removed_nodes', 0)} nodes hidden)"
        )
    else:
        # Decide which topology to use based on whether ComputeAgent is in visible types
        if visible_types and 'ComputeAgent' in visible_types:
            # User wants to see compute agents - use physical topology
            graph = episode_data['topology_graph']
        else:
            # User filtered out compute agents - use logical topology
            graph = episode_data['logical_topology_graph']

        info_text = f"Showing full topology ({graph.number_of_nodes()} nodes)"

    # Get healthy nodes to hide if requested
    hidden_nodes = None
    if hide_healthy_nodes and 'health_analysis' in episode_data:
        health_analysis = episode_data['health_analysis']
        node_results = health_analysis.get('node_results', {})

        # Filter out entry point nodes (gateways) - they should never be hidden
        hidden_nodes = [
            node_id for node_id in health_analysis['healthy_nodes']
            if not node_results.get(node_id, type('obj', (), {'is_entry_point': False})).is_entry_point
        ]

        healthy_count = len(health_analysis['healthy_nodes'])
        impacted_count = len(health_analysis['impacted_nodes'])
        uncertain_count = len(health_analysis.get('uncertain_nodes', set()))
        entry_point_count = len(health_analysis['healthy_nodes']) - len(hidden_nodes)

        info_text += f" | Impacted: {impacted_count}, Healthy: {healthy_count}, Uncertain: {uncertain_count}"
        if hidden_nodes:
            info_text += f" ({len(hidden_nodes)} hidden"
            if entry_point_count > 0:
                info_text += f", {entry_point_count} gateway(s) kept visible"
            info_text += ")"

    return create_topology_chart(
        graph,
        episode_data['label'],
        visible_types=visible_types or [],
        hidden_nodes=hidden_nodes,
        layout_type=layout_type or 'hierarchical'
    ), info_text


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


# Dataset Generator Callbacks

@app.callback(
    Output('generator-collapse', 'is_open'),
    Input('generator-collapse-button', 'n_clicks'),
    State('generator-collapse', 'is_open')
)
def toggle_generator_collapse(n_clicks, is_open):
    """Toggle dataset generator section."""
    if n_clicks:
        return not is_open
    return is_open


@app.callback(
    Output('generation-status', 'children'),
    Output('generation-poll-interval', 'disabled'),
    Output('generate-button', 'disabled'),
    Input('generate-button', 'n_clicks'),
    State('episodes-input', 'value'),
    State('topology-size-input', 'value'),
    State('output-dir-input', 'value'),
    State('seed-input', 'value'),
    State('verbose-checkbox', 'value'),
    prevent_initial_call=True
)
def start_generation(n_clicks, num_episodes, topology_size, output_dir, seed, verbose_list):
    """Start dataset generation in background when button is clicked."""
    import subprocess
    import sys
    from pathlib import Path
    import time

    if not n_clicks:
        return html.Div("Ready to generate training data", className="text-muted"), True, False

    # Check if generation is already running
    global generation_state
    if generation_state['running']:
        return dbc.Alert("Generation is already running", color="warning"), False, True

    # Validate inputs
    if not num_episodes or num_episodes < 1:
        return dbc.Alert("Please enter a valid number of episodes (minimum 1)", color="danger"), True, False

    if not output_dir:
        output_dir = 'data'

    # Convert output_dir to absolute path relative to project root, not viz directory
    if not os.path.isabs(output_dir):
        project_root = Path(__file__).parent.parent
        output_dir = str(project_root / output_dir)

    # Build command
    script_path = Path(__file__).parent.parent / 'generate_dataset.py'
    cmd = [sys.executable, str(script_path), '--episodes', str(num_episodes), '--output', output_dir]

    if topology_size:
        cmd.extend(['--topology-size', str(topology_size)])

    if seed:
        cmd.extend(['--seed', str(seed)])

    verbose = 'verbose' in (verbose_list or [])
    if verbose:
        cmd.append('--verbose')

    try:
        # Start the generation script in background
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Update global state
        generation_state['running'] = True
        generation_state['process'] = process
        generation_state['start_time'] = time.time()
        generation_state['config'] = {
            'episodes': num_episodes,
            'output_dir': output_dir,
            'command': ' '.join(cmd)
        }
        generation_state['output'] = []
        generation_state['error'] = None

        # Show starting status
        starting_msg = dbc.Alert([
            html.H6("🚀 Generation Started", className="alert-heading"),
            html.P(f"Generating {num_episodes} episodes in background..."),
            html.P(f"Command: {' '.join(cmd)}", className="small mb-2"),
            dbc.Spinner(size="sm")
        ], color="info")

        return starting_msg, False, True  # Enable polling, disable button

    except Exception as e:
        exception_msg = dbc.Alert([
            html.H6("❌ Failed to Start Generation", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger")

        return exception_msg, True, False  # Disable polling, enable button


@app.callback(
    Output('generation-status', 'children', allow_duplicate=True),
    Output('generation-poll-interval', 'disabled', allow_duplicate=True),
    Output('generate-button', 'disabled', allow_duplicate=True),
    Output('datarun-dropdown', 'options', allow_duplicate=True),
    Output('datarun-dropdown', 'value', allow_duplicate=True),
    Input('generation-poll-interval', 'n_intervals'),
    prevent_initial_call=True
)
def poll_generation_status(n_intervals):
    """Poll the generation process status."""
    import time

    global generation_state

    if not generation_state['running']:
        return dash.no_update, True, False, dash.no_update, dash.no_update

    process = generation_state['process']
    config = generation_state['config']

    # Check if process is still running
    returncode = process.poll()

    if returncode is None:
        # Still running - show progress
        elapsed = time.time() - generation_state['start_time']
        mins, secs = divmod(int(elapsed), 60)

        running_msg = dbc.Alert([
            html.H6("⏳ Generation In Progress", className="alert-heading"),
            html.P(f"Generating {config['episodes']} episodes..."),
            html.P(f"Elapsed time: {mins}m {secs}s", className="mb-2"),
            dbc.Progress(animated=True, striped=True, value=100, color="info", className="mb-2"),
            html.P(f"Command: {config['command']}", className="small mb-0")
        ], color="info")

        return running_msg, False, True, dash.no_update, dash.no_update

    else:
        # Process finished
        stdout, stderr = process.communicate()

        generation_state['running'] = False
        generation_state['process'] = None

        if returncode == 0:
            # Success
            success_msg = dbc.Alert([
                html.H6("✅ Generation Complete!", className="alert-heading"),
                html.P(f"Successfully generated {config['episodes']} episodes"),
                html.P(f"Output directory: {config['output_dir']}", className="mb-2"),
                html.Hr(),
                html.P("Output (last 1000 chars):", className="small mb-1"),
                html.Pre(stdout[-1000:] if stdout else "No output", className="small mb-0",
                        style={'maxHeight': '200px', 'overflow': 'auto', 'backgroundColor': '#f8f9fa'})
            ], color="success")

            # Refresh data run dropdown
            runs = list_data_runs(BASE_DATA_DIR)
            options = [
                {
                    'label': f"{run['id']} ({run['timestamp']})",
                    'value': run['path']
                }
                for run in runs
            ]
            default_value = runs[0]['path'] if runs else None

            return success_msg, True, False, options, default_value
        else:
            # Error
            error_msg = dbc.Alert([
                html.H6("❌ Generation Failed", className="alert-heading"),
                html.P(f"Process exited with code: {returncode}"),
                html.Hr(),
                html.P("Error output (last 1000 chars):", className="small mb-1"),
                html.Pre(stderr[-1000:] if stderr else "No error output", className="small mb-0",
                        style={'maxHeight': '200px', 'overflow': 'auto', 'backgroundColor': '#fff5f5'})
            ], color="danger")

            return error_msg, True, False, dash.no_update, dash.no_update


if __name__ == '__main__':
    print(f"Starting Samba Telemetry Dashboard...")
    print(f"Base data directory: {BASE_DATA_DIR}")
    print(f"Loading data runs...")

    runs = list_data_runs(BASE_DATA_DIR)
    print(f"Found {len(runs)} data runs:")
    for run in runs[:5]:  # Show first 5
        print(f"  - {run['id']} ({run['timestamp']})")
    if len(runs) > 5:
        print(f"  ... and {len(runs) - 5} more")

    print(f"\n🚀 Dashboard running at http://localhost:{PORT}")
    app.run(debug=True, host='0.0.0.0', port=PORT)
