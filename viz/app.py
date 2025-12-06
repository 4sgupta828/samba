"""
Samba Telemetry Dashboard

A streamlined Flask + Dash application for visualizing training episode data
from the Samba GNN training data generator.
"""

import os
import random
import sys
from pathlib import Path
from flask import Flask
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from data_loader import list_data_runs, list_episodes, load_episode

# Import chart modules (will be created)
from charts.topology import create_topology_chart, extract_zoom_subgraph
from charts.metrics_overview import create_golden_signals_dashboard
from charts.component_drilldown import create_component_drilldown
from charts.fault_propagation import create_fault_propagation_analysis
from charts.forensic_analysis import create_forensic_analysis

# Add parent directory to path for analysis imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.propagation_analyzer import analyze_episode
from analysis.forensic_analyzer import analyze_episode as forensic_analyze_episode

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

# Valid fault type and role combinations based on scenario library
VALID_FAULT_COMBINATIONS = {
    'cpu_saturation': ['service'],
    'memory_leak': ['service'],
    'inject_latency': ['service', 'cache', 'external'],
    'slow_queries': ['database'],
    'connection_exhaustion': ['database'],
    'enable_background_job': ['database'],
    'cache_failure': ['cache'],
    'inject_errors': ['external'],
    'queue_consumer_slowdown': ['queue'],
    # Structural faults
    'noisy_neighbor': ['service'],
    'hot_shard': ['service'],
    'force_deadlock': ['service'],
    'network_partition': ['network'],
}

# Fault type durations (from scenario library)
FAULT_DURATIONS = {
    'cpu_saturation': 300,  # 5 min
    'memory_leak': 300,  # 5 min
    'inject_latency': 300,  # 5 min (service), 900 (cache), 600 (external)
    'slow_queries': 600,  # 10 min
    'connection_exhaustion': 600,  # 10 min
    'enable_background_job': 600,  # 10 min
    'cache_failure': 900,  # 15 min
    'inject_errors': 600,  # 10 min
    'queue_consumer_slowdown': 900,  # 15 min
    # Structural faults
    'noisy_neighbor': 900,  # 15 min
    'hot_shard': 900,  # 15 min
    'force_deadlock': 900,  # 15 min
    'network_partition': 600,  # 10 min
}

# Reverse mapping: role -> valid fault types
VALID_ROLE_FAULTS = {}
for fault_type, roles in VALID_FAULT_COMBINATIONS.items():
    for role in roles:
        if role not in VALID_ROLE_FAULTS:
            VALID_ROLE_FAULTS[role] = []
        VALID_ROLE_FAULTS[role].append(fault_type)


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
                                dbc.Label("Fault Type (optional):", html_for="fault-type-dropdown"),
                                dcc.Dropdown(
                                    id='fault-type-dropdown',
                                    options=[
                                        {'label': 'Any (Random)', 'value': ''},
                                        {'label': 'CPU Saturation', 'value': 'cpu_saturation'},
                                        {'label': 'Memory Leak', 'value': 'memory_leak'},
                                        {'label': 'Inject Latency', 'value': 'inject_latency'},
                                        {'label': 'Slow Queries', 'value': 'slow_queries'},
                                        {'label': 'Connection Exhaustion', 'value': 'connection_exhaustion'},
                                        {'label': 'Background Job', 'value': 'enable_background_job'},
                                        {'label': 'Cache Failure', 'value': 'cache_failure'},
                                        {'label': 'Inject Errors', 'value': 'inject_errors'},
                                        {'label': 'Queue Consumer Slowdown', 'value': 'queue_consumer_slowdown'},
                                        {'label': 'Noisy Neighbor', 'value': 'noisy_neighbor'},
                                        {'label': 'Hot Shard', 'value': 'hot_shard'},
                                        {'label': 'Network Partition', 'value': 'network_partition'},
                                        {'label': 'Force Deadlock', 'value': 'force_deadlock'},
                                    ],
                                    value='',
                                    placeholder="Select fault type...",
                                    clearable=True
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Node Type (optional):", html_for="fault-role-dropdown"),
                                dcc.Dropdown(
                                    id='fault-role-dropdown',
                                    options=[
                                        {'label': 'Any (Random)', 'value': ''},
                                        {'label': 'Service', 'value': 'service'},
                                        {'label': 'Database', 'value': 'database'},
                                        {'label': 'Cache', 'value': 'cache'},
                                        {'label': 'Queue', 'value': 'queue'},
                                        {'label': 'External', 'value': 'external'},
                                        {'label': 'Network', 'value': 'network'},
                                    ],
                                    value='',
                                    placeholder="Select node type...",
                                    clearable=True
                                ),
                            ], width=2),
                        ]),
                        dbc.Row([
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
                                dbc.Label("Topology Source:", html_for="llm-topology-checkbox"),
                                dbc.Checklist(
                                    id='llm-topology-checkbox',
                                    options=[{'label': ' LLM Topologies (uncheck for custom)', 'value': 'llm'}],
                                    value=['llm'],
                                    switch=True,
                                    className="mt-2"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("LLM Analysis:", html_for="enable-llm-analysis-checkbox"),
                                dbc.Checklist(
                                    id='enable-llm-analysis-checkbox',
                                    options=[{'label': ' Enable LLM Analysis', 'value': 'enable'}],
                                    value=[],
                                    switch=True,
                                    className="mt-2"
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Specific Topology:", html_for="topology-name-dropdown"),
                                dcc.Dropdown(
                                    id='topology-name-dropdown',
                                    options=[],
                                    value='',
                                    placeholder="Random (leave empty)",
                                    clearable=True
                                ),
                            ], width=1),
                            dbc.Col([
                                dbc.Button(
                                    "Generate Dataset",
                                    id="generate-button",
                                    color="success",
                                    className="mt-4",
                                    style={'width': '100%'}
                                ),
                            ], width=1),
                            dbc.Col([
                                dbc.Button(
                                    "Cancel",
                                    id="cancel-button",
                                    color="danger",
                                    outline=True,
                                    className="mt-4",
                                    style={'width': '100%'},
                                    disabled=True
                                ),
                            ], width=1),
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
        ], width=3),
        dbc.Col([
            dbc.Button("Load Episode", id="load-button", color="primary", className="mt-4", style={'width': '100%'}),
        ], width=2),
        dbc.Col([
            dbc.Button(
                "🔍 Analyze Fault",
                id="analyze-fault-button",
                color="warning",
                outline=True,
                className="mt-4",
                disabled=True,  # Enabled when episode loaded
                style={'width': '100%'}
            ),
        ], width=2),
        dbc.Col([
            dbc.Button(
                "🔬 Run Forensics",
                id="analyze-forensic-button",
                color="info",
                outline=True,
                className="mt-4",
                disabled=True,  # Enabled when episode loaded
                style={'width': '100%'}
            ),
        ], width=2),
        dbc.Col([
            dbc.Spinner(html.Div(id="loading-status"), size="sm", spinner_class_name="mt-4"),
        ], width=1),
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
                                value='circular',
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
                            dbc.Checklist(
                                id='zoom-mode-toggle',
                                options=[{'label': ' Zoom Mode (click node to focus)', 'value': 'zoom'}],
                                value=[],
                                inline=True,
                                switch=True,
                                className="me-3 d-inline-block",
                                style={'fontSize': '0.85rem', 'fontWeight': 'bold', 'color': '#17a2b8'}
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
                    html.Div(id='topology-info', className="text-muted small mt-2"),
                    html.Div(id='zoom-controls', children=[
                        dbc.ButtonGroup([
                            dbc.Button("Node Only", id='zoom-depth-0', size="sm", outline=True, color="info"),
                            dbc.Button("1 Hop", id='zoom-depth-1', size="sm", outline=True, color="info"),
                            dbc.Button("2 Hops", id='zoom-depth-2', size="sm", outline=True, color="info", active=True),
                            dbc.Button("3 Hops", id='zoom-depth-3', size="sm", outline=True, color="info"),
                            dbc.Button("4+ Hops", id='zoom-depth-4', size="sm", outline=True, color="info"),
                        ], className="mt-2")
                    ], style={'display': 'none'}),
                    html.Div(id='semantic-description', className="mt-3")
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
        ], width=12)
    ], className="mb-3"),

    # Fault Propagation Analysis Container
    dbc.Row([
        dbc.Col([
            html.Div(id='fault-analysis-container', style={'display': 'none'})
        ])
    ], className="mb-3"),

    # Forensic Analysis Container
    dbc.Row([
        dbc.Col([
            html.Div(id='forensic-analysis-container', style={'display': 'none'})
        ])
    ], className="mb-3"),

    # Hidden div to store episode data
    dcc.Store(id='episode-data-store'),

    # Store for zoom mode state
    dcc.Store(id='zoom-mode-store', data={'enabled': False, 'node': None, 'depth': 2}),

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
    Output('analyze-fault-button', 'disabled'),
    Output('analyze-forensic-button', 'disabled'),
    [Input('episode-data-store', 'data')]
)
def enable_analysis_buttons(episode_data):
    """Enable analysis buttons when episode is loaded"""
    disabled = episode_data is None or len(episode_data) == 0
    return disabled, disabled


@app.callback(
    [Output('fault-analysis-container', 'children'),
     Output('fault-analysis-container', 'style')],
    [Input('analyze-fault-button', 'n_clicks')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def run_fault_analysis(n_clicks, datarun, episode):
    """Run fault propagation analysis and display results"""
    if not n_clicks or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(datarun, episode)

        # Debug: Print path for troubleshooting
        print(f"Running fault propagation analysis on: {episode_dir}")

        # Run analysis and save results
        print("  Analyzing episode and saving results...")
        output_path = os.path.join(episode_dir, 'fault_propagation.json')
        analyze_episode(
            episode_dir=episode_dir,
            sample_interval=5,
            output_file=output_path
        )
        print(f"  ✅ Fault propagation analysis saved to: {output_path}")

        # Create visualization
        analysis_view = create_fault_propagation_analysis(episode_dir)

        return analysis_view, {'display': 'block'}

    except Exception as e:
        import traceback
        print(f"Error in fault analysis: {str(e)}")
        traceback.print_exc()

        error_alert = dbc.Alert([
            html.H5("Error running analysis", className="alert-heading"),
            html.P(f"Error: {str(e)}"),
            html.Hr(),
            html.Pre(traceback.format_exc(), style={'fontSize': '0.8em'})
        ],
            color="danger",
            className="mt-3"
        )
        return error_alert, {'display': 'block'}


# Use clientside callback for tab switching in fault analysis
app.clientside_callback(
    """
    function(active_tab) {
        if (!active_tab) return [{'display': 'block'}, {'display': 'none'}];

        if (active_tab === 'visual') {
            return [{'display': 'block'}, {'display': 'none'}];
        } else {
            return [{'display': 'none'}, {'display': 'block'}];
        }
    }
    """,
    [Output('visual-tab', 'style'),
     Output('raw-tab', 'style')],
    [Input('analysis-tabs', 'active_tab')]
)


@app.callback(
    [Output('fault-analysis-container', 'children', allow_duplicate=True),
     Output('fault-analysis-container', 'style', allow_duplicate=True)],
    [Input('episode-data-store', 'data')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def auto_load_fault_analysis(episode_id, datarun, episode):
    """Automatically load existing fault propagation analysis when episode is loaded."""
    if not episode_id or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(datarun, episode)
        fault_analysis_path = os.path.join(episode_dir, 'fault_propagation.json')

        # Check if pre-existing fault propagation analysis exists
        if os.path.exists(fault_analysis_path):
            print(f"Loading existing fault propagation analysis from: {fault_analysis_path}")

            # Load and display the existing analysis
            analysis_view = create_fault_propagation_analysis(episode_dir)
            return analysis_view, {'display': 'block'}
        else:
            # No existing analysis, hide container
            return [], {'display': 'none'}

    except Exception as e:
        print(f"Error loading existing fault analysis: {str(e)}")
        # Don't show error, just hide container
        return [], {'display': 'none'}


@app.callback(
    [Output('forensic-analysis-container', 'children'),
     Output('forensic-analysis-container', 'style')],
    [Input('analyze-forensic-button', 'n_clicks')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def run_forensic_analysis(n_clicks, datarun, episode):
    """Run forensic analysis and display results"""
    if not n_clicks or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(datarun, episode)

        # Debug: Print path for troubleshooting
        print(f"Running forensic analysis on: {episode_dir}")

        # Run forensic analysis
        print("  Running comprehensive forensic analysis...")
        forensic_report = forensic_analyze_episode(episode_dir)

        # The analyze_episode function saves to forensic_analysis.json automatically
        output_path = os.path.join(episode_dir, 'forensic_analysis.json')
        print(f"  ✅ Forensic analysis saved to: {output_path}")

        # Create visualization
        analysis_view = create_forensic_analysis(episode_dir)

        return analysis_view, {'display': 'block'}

    except Exception as e:
        import traceback
        print(f"Error in forensic analysis: {str(e)}")
        traceback.print_exc()

        error_alert = dbc.Alert([
            html.H5("Error running forensic analysis", className="alert-heading"),
            html.P(f"Error: {str(e)}"),
            html.Hr(),
            html.Pre(traceback.format_exc(), style={'fontSize': '0.8em'})
        ],
            color="danger",
            className="mt-3"
        )
        return error_alert, {'display': 'block'}


@app.callback(
    [Output('forensic-analysis-container', 'children', allow_duplicate=True),
     Output('forensic-analysis-container', 'style', allow_duplicate=True)],
    [Input('episode-data-store', 'data')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def auto_load_forensic_analysis(episode_id, datarun, episode):
    """Automatically load existing forensic analysis when episode is loaded."""
    if not episode_id or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(datarun, episode)
        forensic_analysis_path = os.path.join(episode_dir, 'forensic_analysis.json')

        # Check if pre-existing forensic analysis exists
        if os.path.exists(forensic_analysis_path):
            print(f"Loading existing forensic analysis from: {forensic_analysis_path}")

            # Load and display the existing analysis
            analysis_view = create_forensic_analysis(episode_dir)
            return analysis_view, {'display': 'block'}
        else:
            # No existing analysis, hide container
            return [], {'display': 'none'}

    except Exception as e:
        print(f"Error loading existing forensic analysis: {str(e)}")
        # Don't show error, just hide container
        return [], {'display': 'none'}


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
    Output('zoom-mode-store', 'data'),
    Output('zoom-controls', 'style'),
    Input('zoom-mode-toggle', 'value'),
    Input('topology-graph', 'clickData'),
    Input('zoom-depth-0', 'n_clicks'),
    Input('zoom-depth-1', 'n_clicks'),
    Input('zoom-depth-2', 'n_clicks'),
    Input('zoom-depth-3', 'n_clicks'),
    Input('zoom-depth-4', 'n_clicks'),
    State('zoom-mode-store', 'data')
)
def update_zoom_mode(zoom_toggle, click_data, d0, d1, d2, d3, d4, current_zoom_state):
    """Update zoom mode state when toggle is changed, node is clicked, or depth is changed."""
    import dash

    # Determine which input triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_zoom_state, {'display': 'none'}

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Get current depth (default to 2)
    current_depth = current_zoom_state.get('depth', 2) if current_zoom_state else 2

    # If depth button was clicked
    if trigger_id.startswith('zoom-depth-'):
        depth_map = {
            'zoom-depth-0': 0,
            'zoom-depth-1': 1,
            'zoom-depth-2': 2,
            'zoom-depth-3': 3,
            'zoom-depth-4': 4
        }
        new_depth = depth_map.get(trigger_id, 2)
        zoom_enabled = current_zoom_state.get('enabled', False)
        return {
            'enabled': zoom_enabled,
            'node': current_zoom_state.get('node'),
            'depth': new_depth
        }, {'display': 'block' if zoom_enabled else 'none'}

    # If zoom toggle was changed
    if trigger_id == 'zoom-mode-toggle':
        zoom_enabled = 'zoom' in (zoom_toggle or [])
        if not zoom_enabled:
            # Zoom disabled - reset state
            return {'enabled': False, 'node': None, 'depth': current_depth}, {'display': 'none'}
        else:
            # Zoom enabled - keep current node and depth
            return {
                'enabled': True,
                'node': current_zoom_state.get('node'),
                'depth': current_depth
            }, {'display': 'block'}

    # If node was clicked
    if trigger_id == 'topology-graph' and click_data:
        zoom_enabled = current_zoom_state.get('enabled', False)
        if zoom_enabled:
            # Extract clicked node ID
            point = click_data['points'][0]
            node_id = point.get('customdata')

            # Fallback methods
            if not node_id and 'hovertext' in point:
                hovertext = point['hovertext']
                node_id = hovertext.split('<b>')[1].split('</b>')[0] if '<b>' in hovertext else None

            if not node_id:
                text = point.get('text', '')
                node_id = text.split('<br>')[0] if text else None

            return {
                'enabled': True,
                'node': node_id,
                'depth': current_depth
            }, {'display': 'block'}

    zoom_enabled = current_zoom_state.get('enabled', False) if current_zoom_state else False
    return current_zoom_state, {'display': 'block' if zoom_enabled else 'none'}


@app.callback(
    Output('zoom-depth-0', 'active'),
    Output('zoom-depth-1', 'active'),
    Output('zoom-depth-2', 'active'),
    Output('zoom-depth-3', 'active'),
    Output('zoom-depth-4', 'active'),
    Input('zoom-mode-store', 'data')
)
def update_zoom_button_states(zoom_state):
    """Update button active states based on current zoom depth."""
    if not zoom_state:
        return False, False, True, False, False  # Default to depth 2

    depth = zoom_state.get('depth', 2)
    return (
        depth == 0,
        depth == 1,
        depth == 2,
        depth == 3,
        depth == 4
    )


@app.callback(
    Output('topology-graph', 'figure'),
    Output('topology-info', 'children'),
    Output('semantic-description', 'children'),
    Input('episode-data-store', 'data'),
    Input('topology-filters', 'value'),
    Input('use-filtered-topology', 'value'),
    Input('hide-healthy-nodes', 'value'),
    Input('topology-layout-selector', 'value'),
    Input('zoom-mode-store', 'data')
)
def update_topology(episode_id, visible_types, use_filtered, hide_healthy, layout_type, zoom_state):
    """Update topology graph when episode is loaded or filters change."""
    if not episode_id or episode_id not in current_episode_data:
        return {}, "", ""

    episode_data = current_episode_data[episode_id]

    # Determine if we should use filtered topology
    use_filtered_topo = 'filtered' in (use_filtered or [])

    # Determine if we should hide healthy nodes
    hide_healthy_nodes = 'hide_healthy' in (hide_healthy or [])

    # Check zoom mode first to determine which topology to use
    zoom_enabled = zoom_state and zoom_state.get('enabled', False)
    zoom_node = zoom_state.get('node') if zoom_state else None
    zoom_depth = zoom_state.get('depth', 2) if zoom_state else 2

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
        # In zoom mode, always use physical topology to make pods available
        # The visible_types filter will control whether they're shown
        if zoom_enabled and zoom_node:
            graph = episode_data['topology_graph']
            info_text = f"Showing full topology ({graph.number_of_nodes()} nodes)"
        # Decide which topology to use based on whether ComputeAgent is in visible types
        elif visible_types and 'ComputeAgent' in visible_types:
            # User wants to see compute agents - use physical topology
            graph = episode_data['topology_graph']
            info_text = f"Showing full topology ({graph.number_of_nodes()} nodes)"
        else:
            # User filtered out compute agents - use logical topology
            graph = episode_data['logical_topology_graph']
            info_text = f"Showing full topology ({graph.number_of_nodes()} nodes)"

    if zoom_enabled and zoom_node and zoom_node in graph:
        # Extract zoom subgraph centered on the selected node
        graph = extract_zoom_subgraph(graph, zoom_node, max_depth=zoom_depth)

        # Create depth description
        if zoom_depth == 0:
            depth_desc = "node only"
        elif zoom_depth == 1:
            depth_desc = "1 hop"
        else:
            depth_desc = f"{zoom_depth} hops"

        info_text = f"Zoom view: '{zoom_node}' ({depth_desc}) - {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
    elif zoom_enabled and not zoom_node:
        # Zoom mode is on but no node selected yet
        info_text += " | Zoom Mode: Click a node to focus"

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

    # Build semantic description section
    semantic_map = episode_data.get('semantic_map')
    if semantic_map and 'description' in semantic_map:
        domain = semantic_map.get('domain', 'Unknown')
        description = semantic_map.get('description', '')

        # Split description into paragraphs for better formatting
        paragraphs = [p.strip() for p in description.split('.') if p.strip()]

        # Group sentences into logical paragraphs (roughly 2-3 sentences each)
        formatted_paragraphs = []
        current_para = []
        for i, sentence in enumerate(paragraphs):
            current_para.append(sentence + '.')
            # Create paragraph every 2-3 sentences or if we detect topic change keywords
            if (len(current_para) >= 2 and any(keyword in sentence.lower() for keyword in
                ['bottleneck', 'fault mode', 'common', 'key', 'failure'])) or len(current_para) >= 3:
                formatted_paragraphs.append(' '.join(current_para))
                current_para = []

        # Add any remaining sentences
        if current_para:
            formatted_paragraphs.append(' '.join(current_para))

        semantic_content = dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.H6([
                        "📚 Architecture Overview - ",
                        html.Span(domain.replace('_', ' ').title(), className="text-info")
                    ], className="mb-0 d-inline-block"),
                    dbc.Button(
                        "Show Details",
                        id="semantic-description-toggle",
                        size="sm",
                        color="info",
                        outline=True,
                        className="float-end"
                    )
                ], className="clearfix")
            ]),
            dbc.Collapse([
                dbc.CardBody([
                    html.Div([
                        html.P(para, className="mb-3", style={
                            'lineHeight': '1.8',
                            'fontSize': '0.95rem',
                            'textAlign': 'justify'
                        }) for para in formatted_paragraphs
                    ])
                ], style={'backgroundColor': '#f8f9fa'})
            ], id="semantic-description-collapse", is_open=False)
        ], className="border-secondary mt-3")
    else:
        semantic_content = html.Div("")

    return create_topology_chart(
        graph,
        episode_data['label'],
        visible_types=visible_types,
        hidden_nodes=hidden_nodes,
        layout_type=layout_type or 'hierarchical'
    ), info_text, semantic_content


@app.callback(
    Output('semantic-description-collapse', 'is_open'),
    Output('semantic-description-toggle', 'children'),
    Input('semantic-description-toggle', 'n_clicks'),
    State('semantic-description-collapse', 'is_open'),
    prevent_initial_call=True
)
def toggle_semantic_description(n_clicks, is_open):
    """Toggle semantic description collapse."""
    if n_clicks:
        new_state = not is_open
        button_text = "Hide Details" if new_state else "Show Details"
        return new_state, button_text
    return is_open, "Show Details" if not is_open else "Hide Details"


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
    Output('topology-size-input', 'disabled'),
    Output('topology-name-dropdown', 'disabled'),
    Output('topology-name-dropdown', 'options'),
    Input('llm-topology-checkbox', 'value')
)
def update_topology_controls(llm_topology_list):
    """Update topology controls based on LLM topology selection."""
    use_llm = 'llm' in (llm_topology_list or [])

    # When using LLM topologies:
    # - Disable topology size (LLM determines size)
    # - Enable topology name dropdown and populate it
    # When using custom topology:
    # - Enable topology size
    # - Disable topology name dropdown

    if use_llm:
        # Try to load available topologies from the topology bank
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        topology_bank_path = project_root / 'data' / 'topology_bank'

        options = []
        if topology_bank_path.exists():
            try:
                subdirs = sorted([d.name for d in topology_bank_path.iterdir() if d.is_dir()])
                options = [{'label': name, 'value': name} for name in subdirs]
            except Exception:
                pass  # If we can't read the directory, just leave options empty

        return True, False, options  # size disabled, dropdown enabled, with options
    else:
        return False, True, []  # size enabled, dropdown disabled, no options


@app.callback(
    Output('fault-role-dropdown', 'options'),
    Output('fault-type-dropdown', 'options'),
    Input('fault-type-dropdown', 'value'),
    Input('fault-role-dropdown', 'value'),
)
def update_fault_dropdowns(fault_type, fault_role):
    """Update both fault type and role dropdown options to show only valid combinations.

    This callback only updates OPTIONS, not VALUES, to avoid circular dependencies.
    """
    import dash

    # Determine which input triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        trigger_id = None
    else:
        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    role_labels = {
        'service': 'Service',
        'database': 'Database',
        'cache': 'Cache',
        'queue': 'Queue',
        'external': 'External',
        'network': 'Network',
    }

    fault_type_labels = {
        'cpu_saturation': 'CPU Saturation (5min)',
        'memory_leak': 'Memory Leak (5min)',
        'inject_latency': 'Inject Latency (5-15min)',
        'slow_queries': 'Slow Queries (10min)',
        'connection_exhaustion': 'Connection Exhaustion (10min)',
        'enable_background_job': 'Enable Background Job (10min)',
        'cache_failure': 'Cache Failure (15min)',
        'inject_errors': 'Inject Errors (10min)',
        'queue_consumer_slowdown': 'Queue Consumer Slowdown (15min)',
        'noisy_neighbor': 'Noisy Neighbor (15min)',
        'hot_shard': 'Hot Shard (15min)',
        'force_deadlock': 'Force Deadlock (15min)',
        'network_partition': 'Network Partition (10min)',
    }

    # Default: show all options
    all_role_options = [
        {'label': role_labels[role], 'value': role}
        for role in sorted(role_labels.keys())
    ]

    all_fault_type_options = [
        {'label': fault_type_labels[ft], 'value': ft}
        for ft in sorted(fault_type_labels.keys())
    ]

    # If fault type was just selected, filter roles
    if trigger_id == 'fault-type-dropdown' and fault_type:
        valid_roles = VALID_FAULT_COMBINATIONS.get(fault_type, [])
        role_options = [
            {'label': role_labels[role], 'value': role}
            for role in valid_roles
        ]
        return role_options, all_fault_type_options

    # If role was just selected, filter fault types
    elif trigger_id == 'fault-role-dropdown' and fault_role:
        valid_fault_types = VALID_ROLE_FAULTS.get(fault_role, [])
        fault_type_options = [
            {'label': fault_type_labels[ft], 'value': ft}
            for ft in valid_fault_types
        ]
        return all_role_options, fault_type_options

    # Default: show all options
    return all_role_options, all_fault_type_options


@app.callback(
    Output('generation-status', 'children'),
    Output('generation-poll-interval', 'disabled'),
    Output('generate-button', 'disabled'),
    Output('cancel-button', 'disabled'),
    Input('generate-button', 'n_clicks'),
    State('episodes-input', 'value'),
    State('topology-size-input', 'value'),
    State('fault-type-dropdown', 'value'),
    State('fault-role-dropdown', 'value'),
    State('output-dir-input', 'value'),
    State('seed-input', 'value'),
    State('verbose-checkbox', 'value'),
    State('llm-topology-checkbox', 'value'),
    State('topology-name-dropdown', 'value'),
    State('enable-llm-analysis-checkbox', 'value'),
    prevent_initial_call=True
)
def start_generation(n_clicks, num_episodes, topology_size, fault_type, fault_role, output_dir, seed, verbose_list, llm_topology_list, topology_name, enable_llm_analysis_list):
    """Start dataset generation in background when button is clicked."""
    import subprocess
    import sys
    from pathlib import Path
    import time

    if not n_clicks:
        return html.Div("Ready to generate training data", className="text-muted"), True, False, True

    # Check if generation is already running
    global generation_state
    if generation_state['running']:
        return dbc.Alert("Generation is already running", color="warning"), False, True, False

    # Validate inputs
    if not num_episodes or num_episodes < 1:
        return dbc.Alert("Please enter a valid number of episodes (minimum 1)", color="danger"), True, False, True

    # Validate fault forcing only works with single episode
    if (fault_type or fault_role) and num_episodes > 1:
        return dbc.Alert("Fault forcing only works with single episode generation. Please set episodes to 1.", color="danger"), True, False, True

    # Validate that both fault type and role are provided together
    if (fault_type and not fault_role) or (fault_role and not fault_type):
        return dbc.Alert("Both fault type and fault role must be specified together.", color="danger"), True, False, True

    # Validate that the fault type and role combination is valid
    if fault_type and fault_role:
        valid_roles = VALID_FAULT_COMBINATIONS.get(fault_type, [])
        if fault_role not in valid_roles:
            return dbc.Alert(
                f"Invalid combination: '{fault_type}' cannot be applied to '{fault_role}'. "
                f"Valid roles for {fault_type}: {', '.join(valid_roles)}",
                color="danger"
            ), True, False, True

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

    if fault_type:
        cmd.extend(['--fault-type', fault_type])

    if fault_role:
        cmd.extend(['--fault-role', fault_role])

    if seed:
        cmd.extend(['--seed', str(seed)])

    if fault_type:
        cmd.extend(['--fault-type', fault_type])

    if fault_role:
        cmd.extend(['--fault-role', fault_role])

    verbose = 'verbose' in (verbose_list or [])
    if verbose:
        cmd.append('--verbose')

    # LLM Analysis support
    enable_llm_analysis = 'enable' in (enable_llm_analysis_list or [])
    if enable_llm_analysis:
        cmd.append('--enable-llm-analysis')

    # LLM Topology support
    use_llm_topologies = 'llm' in (llm_topology_list or [])
    if use_llm_topologies:
        # Convert topology bank to absolute path
        topology_bank_path = 'data/topology_bank'
        if not os.path.isabs(topology_bank_path):
            project_root = Path(__file__).parent.parent
            topology_bank_path = str(project_root / topology_bank_path)

        # Validate that topology bank exists
        if not os.path.exists(topology_bank_path):
            return dbc.Alert([
                html.H6("❌ Topology Bank Not Found", className="alert-heading"),
                html.P(f"The topology bank directory does not exist: {topology_bank_path}"),
                html.P("Please generate the topology bank first by running:"),
                html.Pre("python3 generate_topology_bank.py --samples 2 --output data/topology_bank",
                        className="small bg-light p-2"),
                html.P("This will generate LLM-based topologies that can be reused for multiple dataset generations.", className="small")
            ], color="danger"), True, False, True

        # Check if topology bank has any topologies
        try:
            subdirs = [d for d in os.listdir(topology_bank_path) if os.path.isdir(os.path.join(topology_bank_path, d))]
            if len(subdirs) == 0:
                return dbc.Alert([
                    html.H6("❌ Empty Topology Bank", className="alert-heading"),
                    html.P(f"The topology bank directory exists but contains no topologies: {topology_bank_path}"),
                    html.P("Please generate topologies first by running:"),
                    html.Pre("python3 generate_topology_bank.py --samples 2 --output data/topology_bank",
                            className="small bg-light p-2")
                ], color="danger"), True, False, True
        except Exception as e:
            return dbc.Alert([
                html.H6("❌ Error Checking Topology Bank", className="alert-heading"),
                html.P(f"Could not read topology bank directory: {str(e)}")
            ], color="danger"), True, False, True

        cmd.append('--llm-topologies')
        cmd.extend(['--topology-bank', topology_bank_path])

        # Add specific topology name if selected
        if topology_name:
            cmd.extend(['--topology-name', topology_name])

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

        return starting_msg, False, True, False  # Enable polling, disable generate button, enable cancel button

    except Exception as e:
        exception_msg = dbc.Alert([
            html.H6("❌ Failed to Start Generation", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger")

        return exception_msg, True, False, True  # Disable polling, enable generate button, disable cancel button


@app.callback(
    Output('generation-status', 'children', allow_duplicate=True),
    Output('generation-poll-interval', 'disabled', allow_duplicate=True),
    Output('generate-button', 'disabled', allow_duplicate=True),
    Output('cancel-button', 'disabled', allow_duplicate=True),
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
        return dash.no_update, True, False, True, dash.no_update, dash.no_update

    process = generation_state['process']
    config = generation_state['config']

    # Check if process is still running
    returncode = process.poll()

    if returncode is None:
        # Still running - show progress
        elapsed = time.time() - generation_state['start_time']
        mins, secs = divmod(int(elapsed), 60)

        # Read available output (non-blocking)
        import select
        trailing_lines = []
        try:
            # Check if there's data available to read (non-blocking)
            if hasattr(select, 'select'):
                # Unix-based systems
                ready, _, _ = select.select([process.stdout], [], [], 0)
                if ready:
                    line = process.stdout.readline()
                    if line:
                        trailing_lines.append(line.strip())
                        generation_state['output'].append(line.strip())
        except Exception:
            pass  # Ignore errors in non-blocking read

        # Get last 10 lines from output buffer
        recent_output = '\n'.join(generation_state['output'][-10:]) if generation_state['output'] else "Waiting for output..."

        running_msg = dbc.Alert([
            html.H6("⏳ Generation In Progress", className="alert-heading"),
            html.P(f"Generating {config['episodes']} episodes..."),
            html.P(f"Elapsed time: {mins}m {secs}s", className="mb-2"),
            dbc.Progress(animated=True, striped=True, value=100, color="info", className="mb-2"),
            html.P(f"Command: {config['command']}", className="small mb-2"),
            html.Hr(),
            html.P("Recent output:", className="small mb-1"),
            html.Pre(recent_output, className="small mb-0",
                    style={'maxHeight': '150px', 'overflow': 'auto', 'backgroundColor': '#f8f9fa', 'fontSize': '0.75rem'})
        ], color="info")

        return running_msg, False, True, False, dash.no_update, dash.no_update

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

            return success_msg, True, False, True, options, default_value
        else:
            # Error (including cancelled)
            error_title = "❌ Generation Cancelled" if returncode == -15 or returncode == -9 else "❌ Generation Failed"
            error_msg = dbc.Alert([
                html.H6(error_title, className="alert-heading"),
                html.P(f"Process exited with code: {returncode}"),
                html.Hr(),
                html.P("Error output (last 1000 chars):", className="small mb-1"),
                html.Pre(stderr[-1000:] if stderr else "No error output", className="small mb-0",
                        style={'maxHeight': '200px', 'overflow': 'auto', 'backgroundColor': '#fff5f5'})
            ], color="warning" if returncode == -15 or returncode == -9 else "danger")

            return error_msg, True, False, True, dash.no_update, dash.no_update


@app.callback(
    Output('generation-status', 'children', allow_duplicate=True),
    Output('generation-poll-interval', 'disabled', allow_duplicate=True),
    Output('generate-button', 'disabled', allow_duplicate=True),
    Output('cancel-button', 'disabled', allow_duplicate=True),
    Input('cancel-button', 'n_clicks'),
    prevent_initial_call=True
)
def cancel_generation(n_clicks):
    """Cancel the running generation process."""
    import signal

    global generation_state

    if not n_clicks or not generation_state['running']:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    process = generation_state['process']

    try:
        # Try graceful termination first (SIGTERM)
        process.terminate()

        # Give it 2 seconds to terminate gracefully
        import time
        for _ in range(20):
            if process.poll() is not None:
                break
            time.sleep(0.1)

        # If still running, force kill (SIGKILL)
        if process.poll() is None:
            process.kill()

        generation_state['running'] = False
        generation_state['process'] = None

        cancel_msg = dbc.Alert([
            html.H6("⚠️ Generation Cancelled", className="alert-heading"),
            html.P("Dataset generation has been cancelled by user."),
        ], color="warning")

        return cancel_msg, True, False, True  # Disable polling, enable generate button, disable cancel button

    except Exception as e:
        error_msg = dbc.Alert([
            html.H6("❌ Failed to Cancel", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger")

        return error_msg, True, False, True  # Disable polling, enable generate button, disable cancel button


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
