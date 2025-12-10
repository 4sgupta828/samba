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
from data_loader import (list_data_runs, list_episodes, load_episode,
                          is_rca_run, is_rca_failed, has_failure_analysis,
                          list_scope_directories)

# Import chart modules (will be created)
from charts.topology import create_topology_chart, extract_zoom_subgraph
from charts.metrics_overview import create_golden_signals_dashboard
from charts.component_drilldown import create_component_drilldown
from charts.fault_propagation import create_fault_propagation_analysis
from charts.forensic_analysis import create_forensic_analysis
from charts.failure_analysis import (create_failure_analysis_view,
                                      create_rca_not_run_message,
                                      create_rca_success_message)
from charts.batch_analysis import create_batch_analysis_view

# Add parent directory to path for analysis imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.propagation_analyzer import analyze_episode
from analysis.forensic_analyzer import analyze_episode as forensic_analyze_episode
from analysis.sotaanalyzer.sota_propagation_analyzer import discover_and_validate_rca
from analyze_failures import FailureAnalyzer

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

# Global state for replay
replay_state = {
    'running': False,
    'process': None,
    'start_time': None,
    'output': []
}

# Valid fault type and role combinations based on redesigned fault catalog (2025-12-10)
# Tier 1: Core Resource Saturation (unique signatures, capacity-relative, severity-based)
# Tier 2: Interaction Failures (distributed system patterns)
VALID_FAULT_COMBINATIONS = {
    # Tier 1: Core Resource Saturation
    'cpu_saturation': ['service', 'database'],  # High CPU → consistent slowdown
    'memory_pressure': ['service', 'database'],  # Sustained high memory → allocation overhead
    'memory_thrashing': ['service', 'database'],  # NEW: Memory bursts → bimodal latency
    'thread_exhaustion': ['service', 'database', 'queue'],  # NEW: Pool saturation → queue buildup
    'disk_io_saturation': ['service', 'database'],  # NEW: HIGH latency, LOW CPU
    'memory_leak': ['service', 'database'],  # Gradual memory exhaustion

    # Tier 2: Interaction Failures
    'inject_latency': ['service', 'cache', 'external', 'database'],  # Generic latency injection
    'inject_errors': ['service', 'cache', 'external', 'database'],  # Generic error injection
    'cache_failure': ['cache'],  # Cache degradation (hit rate, latency, errors)
    'queue_consumer_slowdown': ['queue'],  # Message processing slowdown

    # Structural/Distributed Faults
    'noisy_neighbor': ['service'],  # CPU steal from co-located pods
    'hot_shard': ['service'],  # Traffic skew to single replica
    'force_deadlock': ['service', 'database'],  # Alias for thread_exhaustion (backward compat)
    'network_partition': ['network'],  # Total isolation between components

    # Deprecated faults REMOVED (2025-12-10):
    # - slow_queries → Use disk_io_saturation
    # - connection_exhaustion → Use thread_exhaustion
    # - enable_background_job → Use cpu_saturation
}

# Fault type durations (typical duration for visible impact)
FAULT_DURATIONS = {
    # Tier 1: Core Resource Saturation
    'cpu_saturation': 300,  # 5 min - consistent slowdown
    'memory_pressure': 300,  # 5 min - sustained high memory
    'memory_thrashing': 300,  # 5 min - NEW: bimodal latency spikes
    'thread_exhaustion': 600,  # 10 min - NEW: queue buildup (takes time to manifest)
    'disk_io_saturation': 600,  # 10 min - NEW: I/O bottleneck
    'memory_leak': 300,  # 5 min - gradual exhaustion

    # Tier 2: Interaction Failures
    'inject_latency': 300,  # 5 min - generic latency
    'inject_errors': 600,  # 10 min - error propagation
    'cache_failure': 900,  # 15 min - cascading cache misses
    'queue_consumer_slowdown': 900,  # 15 min - queue accumulation

    # Structural/Distributed Faults
    'noisy_neighbor': 900,  # 15 min - CPU steal accumulation
    'hot_shard': 900,  # 15 min - traffic skew impact
    'force_deadlock': 900,  # 15 min - thread blocking (alias for thread_exhaustion)
    'network_partition': 600,  # 10 min - isolation impact

    # Deprecated faults REMOVED (2025-12-10):
    # - slow_queries, connection_exhaustion, enable_background_job
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
    # Check if this is a network partition fault
    is_network_partition = label_data.get('fault_type') == 'network_partition'
    partition_info = label_data.get('network_partition', {}) or label_data.get('fault_params', {})

    card_contents = [
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
    ]

    # Add network partition alert if applicable
    if is_network_partition and partition_info:
        source = partition_info.get('source_component_id', partition_info.get('source_component', 'Unknown'))
        target = partition_info.get('target_component_id', partition_info.get('target_component', 'Unknown'))
        bidirectional = partition_info.get('bidirectional', False)

        partition_alert = dbc.Alert([
            html.H5("🔌 Network Partition Active", className="alert-heading"),
            html.Hr(),
            html.P([
                html.Strong("Partitioned Components:"),
                html.Br(),
                html.Span(f"  • {source} ", style={'fontFamily': 'monospace'}),
                html.Span("⟷" if bidirectional else "→", style={'color': '#ff6b6b', 'fontSize': '1.2em'}),
                html.Span(f" {target}", style={'fontFamily': 'monospace'}),
            ]),
            html.P([
                html.Strong("Type: "),
                html.Span("Bidirectional" if bidirectional else "Unidirectional"),
                html.Br(),
                html.Strong("Impact: "),
                html.Span("All communication between these components is blocked during the fault period"),
            ], className="mb-0", style={'fontSize': '0.9em'}),
        ], color="warning", className="mt-3")

        card_contents[1].children.append(partition_alert)

    return dbc.Card(card_contents, className="mb-4")


# App layout
app.layout = dbc.Container([
    # URL location component for handling URL parameters
    dcc.Location(id='url', refresh=False),

    # Store for URL parameters (temporary storage for episode from URL)
    dcc.Store(id='url-episode-store', data={}),

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
                                dbc.Label("Fault Severity:", html_for="fault-severity-slider"),
                                html.Div([
                                    dcc.Slider(
                                        id='fault-severity-slider',
                                        min=0.0,
                                        max=1.0,
                                        step=0.1,
                                        value=0.5,
                                        marks={
                                            0.0: {'label': '0.0 (Subtle)', 'style': {'fontSize': '10px'}},
                                            0.3: {'label': '0.3', 'style': {'fontSize': '10px'}},
                                            0.5: {'label': '0.5 (Moderate)', 'style': {'fontSize': '10px'}},
                                            0.7: {'label': '0.7', 'style': {'fontSize': '10px'}},
                                            1.0: {'label': '1.0 (Severe)', 'style': {'fontSize': '10px'}}
                                        },
                                        tooltip={"placement": "bottom", "always_visible": False}
                                    ),
                                    html.Div(id='fault-severity-value', className='text-center small text-muted mt-1')
                                ])
                            ], width=2),
                            dbc.Col([
                                dbc.Label("Fault Type (optional):", html_for="fault-type-dropdown"),
                                dcc.Dropdown(
                                    id='fault-type-dropdown',
                                    options=[
                                        {'label': 'Any (Random)', 'value': ''},
                                        {'label': 'No Fault', 'value': 'no_fault'},
                                        {'label': 'CPU Saturation', 'value': 'cpu_saturation'},
                                        {'label': 'Memory Leak', 'value': 'memory_leak'},
                                        {'label': 'Memory Pressure', 'value': 'memory_pressure'},
                                        {'label': 'Memory Thrashing', 'value': 'memory_thrashing'},
                                        {'label': 'Inject Latency', 'value': 'inject_latency'},
                                        {'label': 'Disk I/O Saturation', 'value': 'disk_io_saturation'},
                                        {'label': 'Thread Exhaustion', 'value': 'thread_exhaustion'},
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
                                dbc.Label("Enhanced Analysis:", html_for="enable-enhanced-analysis-checkbox"),
                                dbc.Checklist(
                                    id='enable-enhanced-analysis-checkbox',
                                    options=[{'label': ' Enable Enhanced Analysis', 'value': 'enable'}],
                                    value=[],
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

    # Scenario Replay Section (Separate Pane)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.H5("🔄 Scenario Replay", className="mb-0 d-inline-block"),
                    dbc.Button("Toggle", id="replay-collapse-button", size="sm", className="float-end", color="secondary")
                ]),
                dbc.Collapse([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Select Scenario to Replay:", html_for="replay-scenario-dropdown"),
                                dcc.Dropdown(
                                    id='replay-scenario-dropdown',
                                    options=[],  # Will be populated from history
                                    value=None,
                                    placeholder="Select a previous scenario...",
                                    clearable=False
                                ),
                            ], width=5),
                            dbc.Col([
                                dbc.Button(
                                    "🔄 Refresh List",
                                    id="replay-refresh-button",
                                    color="secondary",
                                    outline=True,
                                    className="mt-4",
                                    style={'width': '100%'}
                                ),
                            ], width=1),
                            dbc.Col([
                                dbc.Button(
                                    "🔄 Replay Scenario",
                                    id="replay-button",
                                    color="primary",
                                    className="mt-4",
                                    style={'width': '100%'},
                                    disabled=True
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Button(
                                    "Cancel",
                                    id="replay-cancel-button",
                                    color="danger",
                                    outline=True,
                                    className="mt-4",
                                    style={'width': '100%'},
                                    disabled=True
                                ),
                            ], width=1),
                            dbc.Col([
                                html.Div(id='replay-status', className="mt-4")
                            ], width=3),
                        ]),
                    ])
                ], id="replay-collapse", is_open=False),
                # Interval for polling replay status
                dcc.Interval(id='replay-poll-interval', interval=2000, disabled=True)
            ], className="mb-4 shadow-sm")
        ])
    ]),

    # Batch Analysis Section (Collapsible)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.H5("📊 Batch RCA Analysis", className="mb-0 d-inline-block"),
                    dbc.Button("Toggle", id="batch-analysis-collapse-button", size="sm", className="float-end", color="secondary")
                ]),
                dbc.Collapse([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Analysis Folder:", html_for="batch-folder-input"),
                                dbc.InputGroup([
                                    dbc.Input(
                                        id='batch-folder-input',
                                        type='text',
                                        value='data/batch_run',
                                        placeholder="Path to folder (e.g., data/batch_run)"
                                    ),
                                    dbc.Button(
                                        "📁",
                                        id="batch-folder-browse-button",
                                        color="secondary",
                                        outline=True
                                    )
                                ]),
                                html.Small("Path relative to project root. Can be a batch folder or single dataset.", className="text-muted")
                            ], width=6),
                            dbc.Col([
                                dbc.Button(
                                    "🔄 Refresh Folders",
                                    id="batch-refresh-button",
                                    color="secondary",
                                    outline=True,
                                    className="mt-4",
                                    style={'width': '100%'}
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Button(
                                    "📊 Analyze Folder",
                                    id="batch-analyze-button",
                                    color="info",
                                    className="mt-4",
                                    style={'width': '100%'}
                                ),
                            ], width=2),
                            dbc.Col([
                                dbc.Spinner(html.Div(id='batch-analysis-status'), size="sm", spinner_class_name="mt-4"),
                            ], width=2),
                        ]),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Quick Select:", html_for="batch-quick-select"),
                                dcc.Dropdown(
                                    id='batch-quick-select',
                                    options=[],
                                    value=None,
                                    placeholder="Choose from available folders...",
                                    clearable=True
                                ),
                                html.Small("Common folders in data/ directory", className="text-muted")
                            ], width=12)
                        ], className="mt-2"),
                        html.Hr(),
                        dbc.Row([
                            dbc.Col([
                                html.Div(id='batch-analysis-results')
                            ])
                        ])
                    ])
                ], id="batch-analysis-collapse", is_open=False)
            ], className="mb-4 shadow-sm")
        ])
    ]),

    # Data run and episode selectors
    dbc.Row([
        dbc.Col([
            dbc.Label("Scope to Directory:", html_for="scope-dropdown"),
            dcc.Dropdown(
                id='scope-dropdown',
                options=[{'label': 'All Data', 'value': ''}],
                value='',
                placeholder="All data directories...",
                clearable=False
            ),
        ], width=2),
        dbc.Col([
            dbc.Label("Select Data Run:", html_for="datarun-dropdown"),
            dcc.Dropdown(
                id='datarun-dropdown',
                options=[],  # Will be populated on load
                value=None,
                placeholder="Select a data run...",
                clearable=False
            ),
        ], width=2),
        dbc.Col([
            dcc.Clipboard(target_id="datarun-path-text", id="clipboard-datarun"),
            dbc.Button("📋 Copy Path", id="copy-datarun-button", color="secondary", outline=True, size="sm", className="mt-4"),
            html.Div(id="datarun-path-text", style={"display": "none"}),
            html.Div(id="copy-feedback", className="mt-1 small text-success", style={"minHeight": "20px"}),
        ], width=1),
        dbc.Col([
            dbc.Label("Filter Episodes:", html_for="failed-only-checkbox"),
            dbc.Checklist(
                id='failed-only-checkbox',
                options=[{'label': ' Show Failed RCA Only', 'value': 'failed'}],
                value=[],
                switch=True,
                className="mt-2"
            ),
        ], width=2),
        dbc.Col([
            dbc.Label("Select Episode:", html_for="episode-dropdown"),
            dcc.Dropdown(
                id='episode-dropdown',
                options=[],  # Will be populated when data run selected
                value=None,
                placeholder="Select an episode...",
                clearable=False
            ),
        ], width=2),
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
                "🚨 RCA Failure Analysis",
                id="analyze-rca-failure-button",
                color="danger",
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

    # Compute Node Co-location Panel
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.H5("🖥️ Compute Node Co-location Analysis", className="mb-0 d-inline-block"),
                        html.Div([
                            html.Span("Service in Focus: ", style={'marginRight': '8px', 'fontSize': '0.85rem', 'color': '#6c757d', 'fontWeight': 'bold'}),
                            dcc.Dropdown(
                                id='colocation-service-selector',
                                options=[],  # Will be populated dynamically
                                value=None,  # Will default to root cause
                                clearable=False,
                                className="d-inline-block me-3",
                                style={'width': '250px', 'display': 'inline-block', 'verticalAlign': 'middle'}
                            ),
                        ], className="float-end d-inline-block"),
                        dbc.Button("Toggle", id="colocation-collapse-button", size="sm", className="float-end me-2", color="secondary")
                    ], className="clearfix")
                ]),
                dbc.Collapse([
                    dbc.CardBody([
                        html.Div(id='colocation-panel')
                    ], style={'padding': '15px'})
                ], id="colocation-collapse", is_open=False)
            ], className="shadow-sm")
        ], width=12)
    ], className="mb-3"),

    # Fault Propagation Analysis Container
    dbc.Row([
        dbc.Col([
            html.Div(id='fault-analysis-container', style={'display': 'none'})
        ])
    ], className="mb-3"),

    # RCA Failure Analysis Container
    dbc.Row([
        dbc.Col([
            html.Div(id='rca-failure-analysis-container', style={'display': 'none'})
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
# NOTE: Data run and episode dropdowns are populated by RCA failure analysis callbacks below

# Store for URL parameters (to handle async loading)
url_episode_store = {}

# URL Parameter Handler - Parse URL and store parameters
@app.callback(
    Output('url-episode-store', 'data'),
    Input('url', 'search'),
    prevent_initial_call=False
)
def parse_url_parameters(search):
    """
    Parse URL parameters and store them for loading.

    URL format: ?scope=batch_run&datarun=data_20251208_105225&episode=ep_0

    This callback only parses and stores URL parameters.
    Other callbacks will read from the store and set dropdown values.
    """
    import dash
    from urllib.parse import parse_qs

    if not search:
        raise dash.exceptions.PreventUpdate

    # Parse query string (remove leading '?')
    params = parse_qs(search.lstrip('?'))

    # Check if episode parameters are present
    if 'datarun' not in params or 'episode' not in params:
        raise dash.exceptions.PreventUpdate

    scope = params.get('scope', [''])[0]
    datarun_id = params.get('datarun', [None])[0]
    episode = params.get('episode', [None])[0]

    if not datarun_id or not episode:
        raise dash.exceptions.PreventUpdate

    # Look up the full path for this datarun ID
    from data_loader import list_data_runs
    runs = list_data_runs(BASE_DATA_DIR, scope_dir=scope if scope else None)

    # Find the run that matches the datarun_id
    datarun_path = None
    for run in runs:
        # Check if the run ID matches (could be just the dataset name or include parent)
        if run['id'] == datarun_id or run['id'].endswith(f"/{datarun_id}") or run['id'].endswith(datarun_id):
            datarun_path = run['path']
            break

    if not datarun_path:
        # Fallback: try to construct the path
        if scope:
            datarun_path = os.path.join(BASE_DATA_DIR, scope, datarun_id)
        else:
            datarun_path = os.path.join(BASE_DATA_DIR, datarun_id)

        # Check if it exists
        if not os.path.exists(datarun_path):
            print(f"[parse_url] Warning: Could not find datarun path for {datarun_id} in scope {scope}")
            raise dash.exceptions.PreventUpdate

    print(f"[parse_url] Parsed URL: scope={scope}, datarun={datarun_path}, episode={episode}")

    # Store all parameters for subsequent callbacks to use
    return {
        'scope': scope,
        'datarun': datarun_path,
        'episode': episode,
        'trigger_load': True
    }


# Set scope from URL store (datarun will be set by populate_data_runs callback)
@app.callback(
    Output('scope-dropdown', 'value', allow_duplicate=True),
    Input('url-episode-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def set_scope_from_url(url_store):
    """Set scope dropdown value from URL parameters."""
    import dash

    if not url_store or not url_store.get('trigger_load'):
        raise dash.exceptions.PreventUpdate

    scope = url_store.get('scope')

    print(f"[set_scope_from_url] Setting scope={scope}")

    return scope


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
    [Input('episode-data-store', 'data')]
)
def enable_analysis_buttons(episode_data):
    """Enable analysis buttons when episode is loaded"""
    disabled = episode_data is None or len(episode_data) == 0
    return disabled


@app.callback(
    [Output('fault-analysis-container', 'children'),
     Output('fault-analysis-container', 'style')],
    [Input('analyze-fault-button', 'n_clicks')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def run_fault_analysis(n_clicks, datarun, episode):
    """Display fault propagation analysis (loads existing pre-computed analysis)"""
    if not n_clicks or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(datarun, episode)
        fault_analysis_path = os.path.join(episode_dir, 'fault_propagation.json')

        # Check if pre-computed fault propagation analysis exists
        if not os.path.exists(fault_analysis_path):
            # No pre-computed analysis available
            no_analysis_alert = dbc.Alert([
                html.H5("⚠️ No Analysis Available", className="alert-heading"),
                html.P("No pre-computed fault propagation analysis found for this episode."),
                html.P("The analysis is generated during dataset creation. This episode may have been created without analysis enabled.", className="small")
            ],
                color="warning",
                className="mt-3"
            )
            return no_analysis_alert, {'display': 'block'}

        # Debug: Print path for troubleshooting
        print(f"Loading fault propagation analysis from: {fault_analysis_path}")

        # Load and display the existing analysis
        analysis_view = create_fault_propagation_analysis(episode_dir)

        return analysis_view, {'display': 'block'}

    except Exception as e:
        import traceback
        print(f"Error loading fault analysis: {str(e)}")
        traceback.print_exc()

        error_alert = dbc.Alert([
            html.H5("Error loading analysis", className="alert-heading"),
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
    prevent_initial_call=True
)
def reset_fault_analysis_on_load(episode_id):
    """Reset/hide fault analysis when a new episode is loaded."""
    # Hide the analysis container when switching episodes
    # User must click the button to show it
    return [], {'display': 'none'}


# Forensic analysis callbacks removed - use RCA Failure Analysis instead

# @app.callback(
#     [Output('forensic-analysis-container', 'children'),
#      Output('forensic-analysis-container', 'style')],
#     [Input('analyze-forensic-button', 'n_clicks')],
#     [State('datarun-dropdown', 'value'),
#      State('episode-dropdown', 'value')],
#     prevent_initial_call=True
# )
def _disabled_run_forensic_analysis(n_clicks, datarun, episode):
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


# @app.callback(
#     [Output('forensic-analysis-container', 'children', allow_duplicate=True),
#      Output('forensic-analysis-container', 'style', allow_duplicate=True)],
#     [Input('episode-data-store', 'data')],
#     [State('datarun-dropdown', 'value'),
#      State('episode-dropdown', 'value')],
#     prevent_initial_call=True
# )
def _disabled_auto_load_forensic_analysis(episode_id, datarun, episode):
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
        pros = semantic_map.get('pros', [])
        cons = semantic_map.get('cons', [])

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

        # Build the content sections
        content_sections = [
            html.Div([
                html.P(para, className="mb-3", style={
                    'lineHeight': '1.8',
                    'fontSize': '0.95rem',
                    'textAlign': 'justify'
                }) for para in formatted_paragraphs
            ])
        ]

        # Add pros and cons if available
        if pros or cons:
            content_sections.append(html.Hr(className="my-4"))

            pros_cons_row = []

            if pros:
                pros_cons_row.append(
                    dbc.Col([
                        html.H6([
                            html.Span("✓ ", style={'color': '#28a745', 'fontSize': '1.2rem'}),
                            "Advantages"
                        ], className="mb-3 text-success"),
                        html.Ul([
                            html.Li(pro, className="mb-2", style={
                                'lineHeight': '1.6',
                                'fontSize': '0.9rem'
                            }) for pro in pros
                        ], style={'listStyleType': 'none', 'paddingLeft': '1.5rem'})
                    ], width=6 if cons else 12)
                )

            if cons:
                pros_cons_row.append(
                    dbc.Col([
                        html.H6([
                            html.Span("⚠ ", style={'color': '#dc3545', 'fontSize': '1.2rem'}),
                            "Trade-offs"
                        ], className="mb-3 text-danger"),
                        html.Ul([
                            html.Li(con, className="mb-2", style={
                                'lineHeight': '1.6',
                                'fontSize': '0.9rem'
                            }) for con in cons
                        ], style={'listStyleType': 'none', 'paddingLeft': '1.5rem'})
                    ], width=6 if pros else 12)
                )

            content_sections.append(dbc.Row(pros_cons_row))

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
                dbc.CardBody(content_sections, style={'backgroundColor': '#f8f9fa'})
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
            episode_data['label'],
            episode_data.get('topology_events')
        )

        return drilldown_content, True

    except Exception as e:
        return html.Div(f"Error loading component details: {str(e)}", className="text-danger"), False


@app.callback(
    Output('colocation-collapse', 'is_open'),
    Input('colocation-collapse-button', 'n_clicks'),
    State('colocation-collapse', 'is_open')
)
def toggle_colocation_collapse(n_clicks, is_open):
    """Toggle co-location panel collapse."""
    if n_clicks:
        return not is_open
    return is_open


@app.callback(
    Output('colocation-service-selector', 'options'),
    Output('colocation-service-selector', 'value'),
    Input('episode-data-store', 'data')
)
def populate_colocation_service_selector(episode_id):
    """Populate service selector dropdown with services that have pods."""
    if not episode_id or episode_id not in current_episode_data:
        return [], None

    try:
        episode_data = current_episode_data[episode_id]
        graph = episode_data['topology_graph']
        label_data = episode_data['label']
        root_cause_node = label_data['root_cause_node']

        # Find all services that have pods
        services_with_pods = set()
        for node_id in graph.nodes():
            node_data = graph.nodes[node_id]
            if node_data.get('type') == 'Pod':
                parent_service = node_data.get('parent_service')
                if parent_service:
                    services_with_pods.add(parent_service)

        if not services_with_pods:
            return [{'label': 'No services with pods', 'value': '', 'disabled': True}], None

        # Sort services with root cause first
        sorted_services = sorted(services_with_pods)
        if root_cause_node in sorted_services:
            sorted_services.remove(root_cause_node)
            sorted_services.insert(0, root_cause_node)

        # Create options with root cause labeled
        options = []
        for service in sorted_services:
            label = f"{service}"
            if service == root_cause_node:
                label += " (Root Cause)"
            options.append({'label': label, 'value': service})

        # Default to root cause
        return options, root_cause_node

    except Exception as e:
        print(f"Error populating service selector: {e}")
        return [], None


@app.callback(
    Output('colocation-panel', 'children'),
    Input('episode-data-store', 'data'),
    Input('colocation-service-selector', 'value')
)
def update_colocation_panel(episode_id, service_in_focus):
    """Update compute node co-location panel when episode is loaded or service selection changes."""
    if not episode_id or episode_id not in current_episode_data:
        return html.Div("Load an episode to see compute node co-location analysis", className="text-muted")

    try:
        episode_data = current_episode_data[episode_id]
        graph = episode_data['topology_graph']
        label_data = episode_data['label']
        root_cause_node = label_data['root_cause_node']

        # Use root cause as default if no service selected
        if not service_in_focus:
            service_in_focus = root_cause_node

        # Build compute node -> pods -> services mapping
        compute_nodes = {}
        pod_to_service = {}

        for node_id in graph.nodes():
            node_data = graph.nodes[node_id]
            node_type = node_data.get('type', '')

            # Track pod -> service mapping
            if node_type == 'Pod':
                parent_service = node_data.get('parent_service')
                if parent_service:
                    pod_to_service[node_id] = parent_service

            # Build compute node mapping
            if node_type == 'ComputeNode':
                compute_nodes[node_id] = {
                    'pods': [],
                    'services': set(),
                    'has_focus_service': False
                }

        # Find all pods and map them to compute nodes
        for node_id in graph.nodes():
            node_data = graph.nodes[node_id]
            if node_data.get('type') == 'Pod':
                compute_node = node_data.get('compute_node')
                if compute_node and compute_node in compute_nodes:
                    parent_service = pod_to_service.get(node_id)
                    compute_nodes[compute_node]['pods'].append({
                        'id': node_id,
                        'service': parent_service
                    })
                    if parent_service:
                        compute_nodes[compute_node]['services'].add(parent_service)

                    # Check if this pod's service is the service in focus
                    if parent_service == service_in_focus:
                        compute_nodes[compute_node]['has_focus_service'] = True

        # Find compute nodes with focus service pods
        focus_nodes = [
            node_id for node_id, data in compute_nodes.items()
            if data['has_focus_service']
        ]

        if not focus_nodes:
            return dbc.Alert([
                html.H6("ℹ️ No Pod-Level Co-location", className="alert-heading"),
                html.P(f"Service '{service_in_focus}' does not have pods placed on compute nodes."),
                html.P("This may be because the topology doesn't use the service/pod/node model.", className="small")
            ], color="info")

        # Build the panel content
        panel_content = []

        # Summary section
        total_services_on_focus_nodes = set()
        for node_id in focus_nodes:
            total_services_on_focus_nodes.update(compute_nodes[node_id]['services'])

        # Remove service in focus to get co-located services
        colocated_services = total_services_on_focus_nodes - {service_in_focus}

        # Determine if service in focus is the root cause
        is_root_cause = (service_in_focus == root_cause_node)

        summary_card = dbc.Alert([
            html.H6("📊 Co-location Summary", className="alert-heading"),
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Strong("Service in Focus: "),
                        html.Span(service_in_focus, style={'color': '#007bff', 'fontWeight': 'bold'}),
                        html.Span(" (Root Cause)" if is_root_cause else "",
                                 style={'fontStyle': 'italic', 'color': 'red', 'marginLeft': '5px'})
                    ], width=4),
                    dbc.Col([
                        html.Strong("Compute Nodes: "),
                        html.Span(f"{len(focus_nodes)} node(s)"),
                    ], width=4),
                    dbc.Col([
                        html.Strong("Co-located Services: "),
                        html.Span(f"{len(colocated_services)} service(s)",
                                 style={'color': '#fd7e14', 'fontWeight': 'bold'} if colocated_services else {})
                    ], width=4),
                ])
            ])
        ], color="primary", className="mb-3")

        panel_content.append(summary_card)

        # Detail section: Show each compute node
        for node_id in sorted(compute_nodes.keys()):
            node_data = compute_nodes[node_id]
            has_focus_service = node_data['has_focus_service']

            if not node_data['pods']:
                continue

            # Determine card color and styling
            if has_focus_service:
                card_color = "info"
                header_icon = "🔵"
                header_suffix = f" (Contains {service_in_focus})"
            else:
                card_color = "light"
                header_icon = "⚪"
                header_suffix = ""

            # Build pods list grouped by service
            services_on_node = {}
            for pod in node_data['pods']:
                service = pod['service']
                if service not in services_on_node:
                    services_on_node[service] = []
                services_on_node[service].append(pod['id'])

            service_rows = []
            for service_name in sorted(services_on_node.keys()):
                pods = services_on_node[service_name]
                is_focus_service = (service_name == service_in_focus)
                is_root_cause_service = (service_name == root_cause_node)

                # Determine styling based on service type
                if is_focus_service:
                    icon = "🔵"
                    service_style = {'color': '#007bff', 'fontWeight': 'bold'}
                elif is_root_cause_service:
                    icon = "🔴"
                    service_style = {'color': 'red', 'fontWeight': 'bold'}
                elif has_focus_service:
                    icon = "⚠️"
                    service_style = {'color': '#fd7e14', 'fontWeight': 'bold'}
                else:
                    icon = "•"
                    service_style = {'fontWeight': 'normal'}

                service_rows.append(
                    dbc.Row([
                        dbc.Col([
                            html.Span(f"{icon} "),
                            html.Strong(service_name, style=service_style),
                            html.Span(" (Focus)" if is_focus_service else " (Root Cause)" if is_root_cause_service else "",
                                     className="text-muted small", style={'fontStyle': 'italic', 'marginLeft': '5px'}),
                            html.Span(f" - {len(pods)} pod{'s' if len(pods) > 1 else ''}", className="text-muted small"),
                        ], width=4),
                        dbc.Col([
                            html.Span(", ".join(pods), className="small", style={'fontFamily': 'monospace'})
                        ], width=8)
                    ], className="mb-2")
                )

            node_card = dbc.Card([
                dbc.CardHeader([
                    html.Span(f"{header_icon} ", style={'fontSize': '1.2em'}),
                    html.Strong(node_id),
                    html.Span(header_suffix, style={'fontStyle': 'italic', 'marginLeft': '10px'})
                ]),
                dbc.CardBody([
                    html.Div([
                        html.P([
                            html.Strong("Services: "),
                            html.Span(f"{len(services_on_node)} service(s), "),
                            html.Strong("Total Pods: "),
                            html.Span(f"{len(node_data['pods'])} pod(s)")
                        ], className="mb-3"),
                        html.Div(service_rows)
                    ])
                ])
            ], color=card_color, outline=True, className="mb-3")

            panel_content.append(node_card)

        return html.Div(panel_content)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return dbc.Alert([
            html.H6("❌ Error generating co-location panel", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger")


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
    Output('fault-severity-value', 'children'),
    Input('fault-severity-slider', 'value')
)
def update_severity_display(severity):
    """Update the display text for the fault severity slider."""
    if severity is None:
        severity = 0.5

    if severity <= 0.3:
        level = "Subtle"
    elif severity <= 0.7:
        level = "Moderate"
    else:
        level = "Severe"

    return f"Severity: {severity:.1f} ({level})"


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
        'no_fault': 'No Fault (Baseline)',

        # Tier 1: Core Resource Saturation
        'cpu_saturation': 'CPU Saturation (5min) - Consistent slowdown',
        'memory_pressure': 'Memory Pressure (5min) - Sustained high memory',
        'memory_thrashing': '🆕 Memory Thrashing (5min) - Bimodal latency spikes',
        'thread_exhaustion': '🆕 Thread Exhaustion (10min) - Queue buildup',
        'disk_io_saturation': '🆕 Disk I/O Saturation (10min) - High latency, low CPU',
        'memory_leak': 'Memory Leak (5min) - Gradual exhaustion',

        # Tier 2: Interaction Failures
        'inject_latency': 'Inject Latency (5min) - Generic latency',
        'inject_errors': 'Inject Errors (10min) - Generic errors',
        'cache_failure': 'Cache Failure (15min) - Cache degradation',
        'queue_consumer_slowdown': 'Queue Consumer Slowdown (15min)',

        # Structural/Distributed Faults
        'noisy_neighbor': 'Noisy Neighbor (15min) - CPU steal',
        'hot_shard': 'Hot Shard (15min) - Traffic skew',
        'force_deadlock': 'Force Deadlock (15min) - Thread blocking',
        'network_partition': 'Network Partition (10min) - Isolation',

        # Deprecated faults REMOVED: slow_queries, connection_exhaustion, enable_background_job
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
    State('fault-severity-slider', 'value'),
    State('fault-type-dropdown', 'value'),
    State('fault-role-dropdown', 'value'),
    State('output-dir-input', 'value'),
    State('seed-input', 'value'),
    State('verbose-checkbox', 'value'),
    State('llm-topology-checkbox', 'value'),
    State('topology-name-dropdown', 'value'),
    State('enable-enhanced-analysis-checkbox', 'value'),
    State('enable-llm-analysis-checkbox', 'value'),
    prevent_initial_call=True
)
def start_generation(n_clicks, num_episodes, topology_size, fault_severity, fault_type, fault_role, output_dir, seed, verbose_list, llm_topology_list, topology_name, enable_enhanced_analysis_list, enable_llm_analysis_list):
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

    # Special handling for no_fault: doesn't require a role
    if fault_type == 'no_fault':
        # Clear fault_role for no_fault type
        fault_role = None
    else:
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

    # Add fault severity (default to 0.5 if not provided)
    if fault_severity is not None:
        cmd.extend(['--fault-severity', str(fault_severity)])

    verbose = 'verbose' in (verbose_list or [])
    if verbose:
        cmd.append('--verbose')

    # Enhanced Analysis support
    enable_enhanced_analysis = 'enable' in (enable_enhanced_analysis_list or [])
    if enable_enhanced_analysis:
        cmd.append('--enable-enhanced-analysis')

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


# Replay Section Callbacks

@app.callback(
    Output('replay-collapse', 'is_open'),
    Input('replay-collapse-button', 'n_clicks'),
    State('replay-collapse', 'is_open')
)
def toggle_replay_collapse(n_clicks, is_open):
    """Toggle replay section."""
    if n_clicks:
        return not is_open
    return is_open


@app.callback(
    Output('replay-scenario-dropdown', 'options'),
    Input('replay-collapse', 'is_open'),
    Input('replay-refresh-button', 'n_clicks')
)
def populate_replay_scenarios(is_open, n_clicks):
    """Populate replay scenario dropdown from persistent history file."""
    if not is_open:
        return []

    from pathlib import Path
    import sys
    import json
    import os
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from src.utils.replay_history import ReplayHistoryManager
        manager = ReplayHistoryManager()
        runs = manager.list_runs()

        print(f"[REPLAY DEBUG] Found {len(runs)} runs in history")

        if not runs:
            return [{'label': 'No scenarios available yet', 'value': '', 'disabled': True}]

        options = []
        for run in reversed(runs):  # Most recent first
            try:
                # Load the run parameters to get detailed info
                run_params_path = run['run_params_path']

                # Check if the file still exists
                if not os.path.exists(run_params_path):
                    # File was deleted - use cached parameters from history
                    if 'run_params_cached' not in run:
                        # Old history format without cached params - skip
                        continue

                    cached_params = run['run_params_cached']
                    fault_type = cached_params['fault']['type']
                    topology = cached_params['topology']['name']
                    root_cause = cached_params['fault']['root_cause_node']
                    episode_id = cached_params.get('episode_id', '?')
                    added_at = run['added_at'][:10]  # Just date

                    label = f"{fault_type} | {topology} | ep_{episode_id} | {root_cause} | {added_at} [cached]"

                    # Use special prefix to indicate this is from cache
                    # Store the cached params as JSON in the value
                    value = f"CACHED:{json.dumps(cached_params)}"

                    options.append({
                        'label': label,
                        'value': value
                    })
                else:
                    # File exists - use it
                    with open(run_params_path, 'r') as f:
                        params = json.load(f)

                    fault_type = params['fault']['type']
                    topology = params['topology']['name']
                    root_cause = params['fault']['root_cause_node']
                    episode_id = params.get('episode_id', '?')
                    added_at = run['added_at'][:10]  # Just date

                    label = f"{fault_type} | {topology} | ep_{episode_id} | {root_cause} | {added_at}"

                    print(f"[REPLAY DEBUG] Added: {label}")

                    options.append({
                        'label': label,
                        'value': run_params_path
                    })
            except Exception as e:
                print(f"[REPLAY DEBUG] Error reading history entry: {e}")
                import traceback
                traceback.print_exc()
                continue

        if not options:
            print(f"[REPLAY DEBUG] No valid options generated")
            return [{'label': 'No valid scenarios available', 'value': '', 'disabled': True}]

        print(f"[REPLAY DEBUG] Returning {len(options)} options")
        return options

    except Exception as e:
        print(f"[REPLAY DEBUG] Error loading replay history: {e}")
        import traceback
        traceback.print_exc()
        return [{'label': f'Error: {str(e)}', 'value': '', 'disabled': True}]


@app.callback(
    Output('replay-button', 'disabled'),
    Input('replay-scenario-dropdown', 'value')
)
def enable_replay_button(scenario_path):
    """Enable replay button when scenario is selected."""
    return scenario_path is None


@app.callback(
    Output('replay-status', 'children'),
    Output('replay-poll-interval', 'disabled'),
    Input('replay-button', 'n_clicks'),
    State('replay-scenario-dropdown', 'value'),
    prevent_initial_call=True
)
def start_replay(n_clicks, scenario_value):
    """Start scenario replay when button is clicked."""
    import subprocess
    import sys
    from pathlib import Path
    import tempfile
    import time

    if not n_clicks or not scenario_value:
        return html.Div(""), True

    global replay_state
    if replay_state['running']:
        return dbc.Alert("Replay is already running", color="warning"), False

    try:
        # Check if this is a cached scenario or a file path
        if scenario_value.startswith('CACHED:'):
            # Extract cached parameters
            cached_json = scenario_value[7:]  # Remove 'CACHED:' prefix
            cached_params = json.loads(cached_json)

            # Create a temporary file with the cached parameters
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            json.dump(cached_params, temp_file, indent=2)
            temp_file.close()

            replay_path = temp_file.name
            is_cached = True
        else:
            # Use the file path directly
            replay_path = scenario_value
            is_cached = False

        # Build replay command
        script_path = Path(__file__).parent.parent / 'generate_dataset.py'
        # Use absolute path for output directory
        output_dir = (Path(__file__).parent.parent / 'data' / 'replay_test').resolve()

        cmd = [
            sys.executable,
            str(script_path),
            '--replay', replay_path,
            '--episodes', '1',
            '--output', str(output_dir),
            '--verbose'
        ]

        # Start the generation script in background
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Store replay state
        replay_state['running'] = True
        replay_state['process'] = process
        replay_state['start_time'] = time.time()
        replay_state['output'] = []

        # Show starting status
        cache_note = " (using cached params - original data deleted)" if is_cached else ""
        return dbc.Alert([
            html.H6("🔄 Replay Started", className="alert-heading"),
            html.P(f"Replaying scenario in background...{cache_note}"),
            html.P(f"Command: {' '.join(cmd)}", className="small"),
            dbc.Spinner(size="sm")
        ], color="info"), False  # Enable polling

    except Exception as e:
        return dbc.Alert([
            html.H6("❌ Failed to Start Replay", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger"), True  # Disable polling


@app.callback(
    Output('replay-status', 'children', allow_duplicate=True),
    Output('replay-poll-interval', 'disabled', allow_duplicate=True),
    Output('replay-cancel-button', 'disabled'),
    Output('datarun-dropdown', 'options', allow_duplicate=True),
    Output('datarun-dropdown', 'value', allow_duplicate=True),
    Input('replay-poll-interval', 'n_intervals'),
    prevent_initial_call=True
)
def poll_replay_status(n_intervals):
    """Poll the replay process status."""
    import time

    global replay_state

    if not replay_state['running']:
        return dash.no_update, True, True, dash.no_update, dash.no_update

    process = replay_state['process']
    returncode = process.poll()

    if returncode is None:
        # Still running
        elapsed = time.time() - replay_state['start_time']
        mins, secs = divmod(int(elapsed), 60)

        running_msg = dbc.Alert([
            html.H6("⏳ Replay In Progress", className="alert-heading"),
            html.P(f"Elapsed time: {mins}m {secs}s"),
            dbc.Spinner(size="sm")
        ], color="info")

        return running_msg, False, False, dash.no_update, dash.no_update  # Keep polling, enable cancel

    else:
        # Process finished
        stdout, stderr = process.communicate()
        replay_state['running'] = False
        replay_state['process'] = None

        if returncode == 0:
            # Success - Refresh data run dropdown
            runs = list_data_runs(BASE_DATA_DIR)
            options = [
                {
                    'label': f"{run['id']} ({run['timestamp']})",
                    'value': run['path']
                }
                for run in runs
            ]
            default_value = runs[0]['path'] if runs else None

            success_msg = dbc.Alert([
                html.H6("✅ Replay Complete!", className="alert-heading"),
                html.P("Scenario replayed successfully. Data run list refreshed.")
            ], color="success")
            return success_msg, True, True, options, default_value  # Stop polling, disable cancel, refresh dropdown
        else:
            # Error
            error_msg = dbc.Alert([
                html.H6("❌ Replay Failed", className="alert-heading"),
                html.P(f"Process exited with code: {returncode}"),
                html.Pre(stderr[-500:] if stderr else "No error output", className="small")
            ], color="danger")
            return error_msg, True, True, dash.no_update, dash.no_update  # Stop polling, disable cancel


@app.callback(
    Output('replay-status', 'children', allow_duplicate=True),
    Output('replay-poll-interval', 'disabled', allow_duplicate=True),
    Output('replay-cancel-button', 'disabled', allow_duplicate=True),
    Input('replay-cancel-button', 'n_clicks'),
    prevent_initial_call=True
)
def cancel_replay(n_clicks):
    """Cancel the running replay process."""
    import signal

    global replay_state

    if not n_clicks or not replay_state['running']:
        return dash.no_update, dash.no_update, dash.no_update

    process = replay_state['process']

    try:
        # Try graceful termination first
        process.terminate()

        # Give it 2 seconds
        import time
        for _ in range(20):
            if process.poll() is not None:
                break
            time.sleep(0.1)

        # Force kill if still running
        if process.poll() is None:
            process.kill()

        replay_state['running'] = False
        replay_state['process'] = None

        cancel_msg = dbc.Alert([
            html.H6("⚠️ Replay Cancelled", className="alert-heading"),
            html.P("Replay has been cancelled by user."),
        ], color="warning")

        return cancel_msg, True, True  # Stop polling, disable cancel

    except Exception as e:
        error_msg = dbc.Alert([
            html.H6("❌ Failed to Cancel", className="alert-heading"),
            html.P(f"Error: {str(e)}")
        ], color="danger")

        return error_msg, True, True


# ==============================================================================
# RCA FAILURE ANALYSIS CALLBACKS
# ==============================================================================

@app.callback(
    Output('scope-dropdown', 'options'),
    Input('scope-dropdown', 'id')
)
def populate_scope_dropdown(_):
    """Populate scope directory dropdown."""
    scope_dirs = list_scope_directories(BASE_DATA_DIR)
    options = [{'label': 'All Data', 'value': ''}]
    options.extend([{'label': dir_name, 'value': dir_name} for dir_name in scope_dirs])
    return options


@app.callback(
    Output('datarun-dropdown', 'options'),
    Output('datarun-dropdown', 'value'),
    Input('scope-dropdown', 'value'),
    State('url-episode-store', 'data')
)
def populate_data_runs_with_scope(scope_dir, url_store):
    """Populate data run dropdown based on scope."""
    print(f"[populate_data_runs] scope={scope_dir}, url_store={url_store}")

    runs = list_data_runs(BASE_DATA_DIR, scope_dir=scope_dir if scope_dir else None)
    options = [
        {
            'label': f"{run['id']} ({run['timestamp']})",
            'value': run['path']
        }
        for run in runs
    ]

    # Check if we're loading from a URL
    if url_store and url_store.get('datarun') and url_store.get('trigger_load'):
        # Set datarun to the value from URL
        url_datarun = url_store.get('datarun')
        print(f"[populate_data_runs] URL loading detected, setting datarun={url_datarun}")
        default_value = url_datarun
    else:
        default_value = runs[0]['path'] if runs else None
        print(f"[populate_data_runs] Setting default value: {default_value}")

    return options, default_value


@app.callback(
    Output('episode-dropdown', 'options'),
    Output('episode-dropdown', 'value'),
    Input('datarun-dropdown', 'value'),
    Input('failed-only-checkbox', 'value'),
    State('url-episode-store', 'data')
)
def populate_episodes_with_filter(data_run_path, failed_filter, url_store):
    """Populate episode dropdown with optional failed-only filter."""
    if not data_run_path:
        return [], None

    # Check if filter is enabled
    failed_only = failed_filter and 'failed' in failed_filter

    print(f"[populate_episodes] data_run={data_run_path}, failed_only={failed_only}, url_store={url_store}")

    episodes = list_episodes(data_run_path, failed_only=failed_only)

    print(f"[populate_episodes] Found {len(episodes)} episodes")

    if len(episodes) == 0 and failed_only:
        # Show a message in the dropdown
        options = [{'label': '⚠️ No failed RCA episodes found - uncheck filter', 'value': ''}]
        default_value = None
    elif len(episodes) == 0:
        # No episodes at all
        options = [{'label': 'No episodes available', 'value': ''}]
        default_value = None
    else:
        options = [{'label': ep, 'value': ep} for ep in episodes]

        # Check if we're loading from a URL - if so, don't set a default value
        # Let the set_episode_from_url callback handle it
        if url_store and url_store.get('episode') and url_store.get('trigger_load'):
            print(f"[populate_episodes] URL loading detected, not setting default value")
            default_value = None
        else:
            default_value = episodes[0] if episodes else None
            print(f"[populate_episodes] Setting default value: {default_value}")

    return options, default_value


@app.callback(
    [Output('episode-dropdown', 'value', allow_duplicate=True),
     Output('load-button', 'n_clicks', allow_duplicate=True),
     Output('url-episode-store', 'data', allow_duplicate=True)],
    [Input('episode-dropdown', 'options')],
    [State('url-episode-store', 'data'),
     State('episode-dropdown', 'options')],
    prevent_initial_call='initial_duplicate'
)
def set_episode_from_url(options_trigger, url_store, options):
    """
    After episode dropdown options are populated, check if there's a pending
    episode from URL parameters and set it.

    This callback is triggered ONLY when episode-dropdown options change.
    It checks if there's a pending episode from URL to load.
    """
    import dash

    print(f"[set_episode_from_url] Triggered. url_store={url_store}, options count={len(options) if options else 0}")

    # Check if we have a stored episode to load
    if not url_store or not url_store.get('episode') or not url_store.get('trigger_load'):
        print(f"[set_episode_from_url] No stored episode to load, preventing update")
        raise dash.exceptions.PreventUpdate

    episode = url_store['episode']
    print(f"[set_episode_from_url] Stored episode: {episode}")

    # Check if the episode is in the options
    if not options:
        print(f"[set_episode_from_url] No options available yet, preventing update")
        raise dash.exceptions.PreventUpdate

    option_values = [opt['value'] for opt in options]
    print(f"[set_episode_from_url] Available episodes: {option_values}")

    if not any(opt['value'] == episode for opt in options):
        print(f"[set_episode_from_url] WARNING: Episode {episode} not found in options")
        # Clear the store to prevent retry loops
        return dash.no_update, dash.no_update, {}

    print(f"[set_episode_from_url] SUCCESS: Setting episode to {episode} and triggering load")

    # Set the episode value and trigger load
    # Clear the store so this doesn't trigger again
    return episode, 1, {}


@app.callback(
    Output('analyze-rca-failure-button', 'disabled'),
    Input('episode-data-store', 'data')
)
def update_rca_failure_button_state(episode_data):
    """Enable RCA failure analysis button when episode loaded."""
    return episode_data is None


@app.callback(
    [Output('rca-failure-analysis-container', 'children'),
     Output('rca-failure-analysis-container', 'style')],
    [Input('analyze-rca-failure-button', 'n_clicks')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def run_rca_failure_analysis(n_clicks, datarun, episode):
    """Run RCA failure analysis and display results."""
    import json
    import networkx as nx

    if not n_clicks or not datarun or not episode:
        return None, {'display': 'none'}

    try:
        episode_dir = os.path.join(datarun, episode)
        print(f"Running RCA failure analysis on: {episode_dir}")

        # Step 0: Validate topology integrity
        try:
            from data_loader import load_topology
            topology_data = load_topology(episode_dir)

            # Build graph to check for integrity issues
            G = nx.DiGraph()
            for node in topology_data.get('nodes', []):
                G.add_node(node['id'])

            # Check edges reference valid nodes
            invalid_edges = []
            for edge in topology_data.get('edges', []):
                source = edge.get('source')
                target = edge.get('target')
                if source not in G.nodes:
                    invalid_edges.append(f"source '{source}' not in nodes")
                if target not in G.nodes:
                    invalid_edges.append(f"target '{target}' not in nodes")

            if invalid_edges:
                error_msg = '; '.join(invalid_edges[:3])  # Show first 3
                print(f"  ⚠️  Topology integrity issues: {error_msg}")

                return dbc.Alert([
                    html.H5("⚠️ Topology Data Quality Issue", className="alert-heading"),
                    html.Hr(),
                    html.P("This episode has a malformed topology. Some edges reference nodes that don't exist in the node list."),
                    html.P(html.Strong("Issues detected:")),
                    html.Ul([html.Li(issue) for issue in invalid_edges[:5]]),
                    html.Hr(),
                    html.P([
                        "This usually happens when:",
                        html.Br(),
                        "• The topology was not generated correctly",
                        html.Br(),
                        "• Topology filtering removed nodes but not their edges",
                        html.Br(),
                        "• There's a bug in the topology generation code"
                    ], className="small"),
                    html.P(html.Strong("Recommendation: Skip this episode or regenerate the dataset.")),
                ], color="warning"), {'display': 'block'}

        except Exception as e:
            print(f"  ⚠️  Error validating topology: {str(e)}")
            # Continue anyway - let RCA handle it

        # Step 1: Check if RCA has been run
        if not is_rca_run(episode_dir):
            print("  RCA not run yet - running discovery mode...")

            # Run RCA discovery mode
            try:
                rca_result = discover_and_validate_rca(
                    episode_dir=episode_dir,
                    sample_interval=5,
                    output_file=os.path.join(episode_dir, 'rca_analysis.json'),
                    create_marker=True,
                    top_k=5
                )
                print("  ✓ RCA discovery mode completed")

                # Check if it succeeded
                if rca_result['validation_result']['success']:
                    # RCA succeeded - show success message
                    ground_truth = rca_result['validation_result']['ground_truth']
                    rank = rca_result['validation_result']['rank']

                    return create_rca_success_message(ground_truth, rank), {'display': 'block'}

            except nx.NodeNotFound as e:
                print(f"  ERROR: Topology issue - {str(e)}")
                return dbc.Alert([
                    html.H5("⚠️ Topology Issue", className="alert-heading"),
                    html.Hr(),
                    html.P(f"Cannot run RCA due to topology data quality issue:"),
                    html.P(html.Code(str(e))),
                    html.Hr(),
                    html.P("The topology has edges referencing nodes that don't exist. This episode should be skipped or regenerated."),
                ], color="warning"), {'display': 'block'}

            except Exception as e:
                print(f"  ERROR running RCA: {str(e)}")
                import traceback
                traceback.print_exc()

                return dbc.Alert([
                    html.H5("Error running RCA", className="alert-heading"),
                    html.Hr(),
                    html.P(f"Failed to run RCA discovery mode: {str(e)}"),
                    html.P(html.Small("Check console for full traceback"))
                ], color="danger"), {'display': 'block'}

        # Step 2: Check if it's a failure (RCA run but not successful)
        if not is_rca_failed(episode_dir):
            # RCA succeeded - show success message
            marker_file = os.path.join(episode_dir, 'RCAInvestigated.marker')
            with open(marker_file, 'r') as f:
                marker_data = json.load(f)

            ground_truth = marker_data.get('ground_truth')
            rank = marker_data.get('rank', 1)

            return create_rca_success_message(ground_truth, rank), {'display': 'block'}

        # Step 3: RCA failed - run failure analysis
        print("  RCA failed - running failure analysis...")

        # Check if failure analysis already exists
        failure_analysis_file = os.path.join(episode_dir, 'failure_analysis.json')

        if has_failure_analysis(episode_dir):
            print("  Loading existing failure analysis...")
            with open(failure_analysis_file, 'r') as f:
                failure_result = json.load(f)
        else:
            print("  Running new failure analysis...")
            analyzer = FailureAnalyzer(episode_dir)
            failure_result = analyzer.analyze()

            # Save for future use
            with open(failure_analysis_file, 'w') as f:
                json.dump(failure_result, f, indent=2)

            print(f"  ✓ Failure analysis saved to: {failure_analysis_file}")

        # Step 4: Display failure analysis
        analysis_view = create_failure_analysis_view(episode_dir, failure_result)

        return analysis_view, {'display': 'block'}

    except Exception as e:
        print(f"Error in RCA failure analysis: {str(e)}")
        import traceback
        traceback.print_exc()

        return dbc.Alert([
            html.H5("Error running RCA failure analysis", className="alert-heading"),
            html.Hr(),
            html.P(f"An error occurred: {str(e)}"),
            html.P("Check console for details.")
        ], color="danger"), {'display': 'block'}


@app.callback(
    [Output('rca-failure-analysis-container', 'children', allow_duplicate=True),
     Output('rca-failure-analysis-container', 'style', allow_duplicate=True)],
    [Input('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def reset_rca_failure_analysis(_):
    """Hide RCA failure analysis when episode changes."""
    return None, {'display': 'none'}


# ============================================================================
# BATCH ANALYSIS CALLBACKS
# ============================================================================

@app.callback(
    Output('batch-analysis-collapse', 'is_open'),
    [Input('batch-analysis-collapse-button', 'n_clicks')],
    [State('batch-analysis-collapse', 'is_open')],
    prevent_initial_call=True
)
def toggle_batch_analysis_collapse(n_clicks, is_open):
    """Toggle batch analysis section visibility."""
    if n_clicks:
        return not is_open
    return is_open


@app.callback(
    Output('batch-quick-select', 'options'),
    [Input('batch-refresh-button', 'n_clicks'),
     Input('batch-analysis-collapse', 'is_open')],
    prevent_initial_call=False
)
def update_batch_folder_options(n_clicks, is_open):
    """Discover folders in data directory that contain episodes or datasets."""
    import os
    from pathlib import Path

    folders = []

    # Add batch_run if it exists
    batch_run_path = os.path.join(BASE_DATA_DIR, 'batch_run')
    if os.path.exists(batch_run_path):
        # Count total episodes in batch_run
        total_eps = len(list(Path(batch_run_path).rglob('ep_*')))
        folders.append({
            'label': f'📁 batch_run (all datasets, {total_eps} episodes)',
            'value': 'data/batch_run'
        })

        # Add individual batch datasets
        for item in sorted(os.listdir(batch_run_path), reverse=True):
            item_path = os.path.join(batch_run_path, item)
            if os.path.isdir(item_path):
                ep_dirs = [d for d in os.listdir(item_path) if d.startswith('ep_') and os.path.isdir(os.path.join(item_path, d))]
                if ep_dirs:
                    folders.append({
                        'label': f'  └─ {item} ({len(ep_dirs)} episodes)',
                        'value': f'data/batch_run/{item}'
                    })

    # Add test_batch if it exists
    test_batch_path = os.path.join(BASE_DATA_DIR, 'test_batch')
    if os.path.exists(test_batch_path):
        total_eps = len(list(Path(test_batch_path).rglob('ep_*')))
        if total_eps > 0:
            folders.append({
                'label': f'📁 test_batch ({total_eps} episodes)',
                'value': 'data/test_batch'
            })

    # Add other top-level dataset folders
    if os.path.exists(BASE_DATA_DIR):
        for item in os.listdir(BASE_DATA_DIR):
            if item in ['batch_run', 'test_batch']:
                continue
            item_path = os.path.join(BASE_DATA_DIR, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                # Check if it contains episodes directly
                ep_dirs = [d for d in os.listdir(item_path) if d.startswith('ep_') and os.path.isdir(os.path.join(item_path, d))]
                if ep_dirs:
                    folders.append({
                        'label': f'📁 {item} ({len(ep_dirs)} episodes)',
                        'value': f'data/{item}'
                    })

    return folders


@app.callback(
    Output('batch-folder-input', 'value'),
    [Input('batch-quick-select', 'value')],
    prevent_initial_call=True
)
def update_folder_input_from_dropdown(selected_folder):
    """Update the folder input when quick select dropdown changes."""
    if selected_folder:
        return selected_folder
    raise dash.exceptions.PreventUpdate


@app.callback(
    [Output('batch-analysis-results', 'children'),
     Output('batch-analysis-status', 'children')],
    [Input('batch-analyze-button', 'n_clicks')],
    [State('batch-folder-input', 'value')],
    prevent_initial_call=True
)
def analyze_batch_folder(n_clicks, folder_path):
    """Run analyze_failures.py on specified folder and display results."""
    if not n_clicks:
        return html.Div(), ""

    import os
    from pathlib import Path
    from analyze_failures import analyze_all_failures

    if not folder_path:
        return dbc.Alert("Please specify a folder path to analyze", color="warning"), ""

    # Resolve path - handle both absolute and relative paths
    if os.path.isabs(folder_path):
        # Absolute path - use as-is
        analysis_path = folder_path
        folder_display = os.path.basename(folder_path)
    else:
        # Relative path - resolve relative to BASE_DATA_DIR
        relative_path = folder_path
        if relative_path.startswith('data/'):
            # Remove 'data/' prefix since BASE_DATA_DIR already points to data/
            relative_path = relative_path[5:]  # Remove 'data/'

        analysis_path = os.path.join(BASE_DATA_DIR, relative_path)
        folder_display = folder_path.replace('data/', '').replace('\\', '/')

    if not os.path.exists(analysis_path):
        return dbc.Alert(f"Folder not found: {analysis_path}\n(BASE_DATA_DIR: {BASE_DATA_DIR})", color="danger"), ""

    try:

        # Run failure analysis
        status = html.Div([
            dbc.Spinner(size="sm", color="primary"),
            html.Span(f" Analyzing {folder_display}...", className="ms-2")
        ])

        # Analyze all failures in this folder
        results = []
        total_markers = 0
        errors = []

        # Find all RCA failures in the folder
        for marker_file in Path(analysis_path).rglob('RCAInvestigated.marker'):
            total_markers += 1
            import json
            with open(marker_file) as f:
                marker = json.load(f)

            # Only include failures
            if not marker.get('success'):
                from analyze_failures import FailureAnalyzer
                episode_dir = marker_file.parent
                try:
                    analyzer = FailureAnalyzer(str(episode_dir))
                    result = analyzer.analyze()
                    results.append(result)
                except Exception as e:
                    error_msg = f"{episode_dir.name}: {str(e)}"
                    errors.append(error_msg)
                    print(f"Error analyzing {episode_dir}: {e}")

        # Create visualization
        if results:
            view = html.Div([
                create_batch_analysis_view(results),
                # Show errors if any
                html.Div([
                    html.Hr(),
                    dbc.Alert([
                        html.H6(f"⚠️ {len(errors)} episodes failed to analyze:", className="alert-heading"),
                        html.Ul([html.Li(err, className="small") for err in errors[:10]])
                    ], color="warning")
                ]) if errors else html.Div()
            ])
            success_rate = len(results) / (len(results) + len(errors)) * 100 if (len(results) + len(errors)) > 0 else 0
            status = html.Span(
                f"✅ Analyzed {len(results)} failures from {folder_display} ({success_rate:.0f}% success)",
                className="text-success"
            )
        else:
            if total_markers == 0:
                view = dbc.Alert([
                    html.H5("📂 No RCA Results Found", className="alert-heading"),
                    html.P(f"No RCAInvestigated.marker files found in {folder_display}"),
                    html.P("Make sure this folder contains episodes with RCA analysis results.", className="mb-0 small")
                ], color="info")
                status = html.Span(f"No RCA data in {folder_display}", className="text-muted")
            else:
                view = dbc.Alert([
                    html.H5("✅ No Failures Found!", className="alert-heading"),
                    html.P(f"All {total_markers} RCA cases in {folder_display} succeeded!")
                ], color="success")
                status = html.Span(f"✅ Complete - No failures in {folder_display}", className="text-success")

        return view, status

    except Exception as e:
        import traceback
        error_msg = f"Error analyzing folder: {str(e)}\n\n{traceback.format_exc()}"
        return dbc.Alert([
            html.H5("❌ Analysis Error", className="alert-heading"),
            html.Pre(error_msg, style={'fontSize': '0.8em', 'maxHeight': '300px', 'overflow': 'auto'})
        ], color="danger"), html.Span("❌ Error", className="text-danger")


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
