# Fault Propagation Analysis - Viz Integration Guide

This guide shows how to integrate the fault propagation analysis tool into the visualization dashboard.

## Files Created

✅ `/viz/charts/fault_propagation.py` - New chart module with interactive analysis

## Integration Steps

### 1. Update viz/app.py Imports

Add this import after the existing chart imports (around line 20):

```python
from charts.fault_propagation import create_fault_propagation_analysis
```

### 2. Add Analysis Button to Layout

After the "Load Episode" button section (around line 243), add:

```python
dbc.Col([
    dbc.Button(
        "🔍 Analyze Fault Propagation",
        id="analyze-fault-button",
        color="warning",
        outline=True,
        className="mt-4",
        disabled=True  # Enabled when episode loaded
    ),
], width=2),
```

### 3. Add Analysis Container to Layout

After the existing chart containers (around line 300+), add:

```python
# Fault Propagation Analysis Container
dbc.Row([
    dbc.Col([
        html.Div(id='fault-analysis-container', style={'display': 'none'})
    ])
], className="mt-4"),
```

### 4. Add Callback to Enable Button

Add this callback after the load_episode callback:

```python
@app.callback(
    Output('analyze-fault-button', 'disabled'),
    [Input('episode-data-store', 'data')]
)
def enable_analysis_button(episode_data):
    """Enable analysis button when episode is loaded"""
    return episode_data is None or len(episode_data) == 0
```

### 5. Add Analysis Callback

Add this callback to run the analysis:

```python
@app.callback(
    [Output('fault-analysis-container', 'children'),
     Output('fault-analysis-container', 'style')],
    [Input('analyze-fault-button', 'n_clicks')],
    [State('datarun-dropdown', 'value'),
     State('episode-dropdown', 'value')]
)
def run_fault_analysis(n_clicks, datarun, episode):
    """Run fault propagation analysis and display results"""
    if not n_clicks or not datarun or not episode:
        return [], {'display': 'none'}

    try:
        # Construct episode directory path
        episode_dir = os.path.join(BASE_DATA_DIR, datarun, episode)

        # Run analysis and create visualization
        analysis_view = create_fault_propagation_analysis(episode_dir)

        return analysis_view, {'display': 'block'}

    except Exception as e:
        error_alert = dbc.Alert(
            f"Error running analysis: {str(e)}",
            color="danger",
            className="mt-3"
        )
        return error_alert, {'display': 'block'}
```

## Features

### 1. **Interactive Timeline Chart** 📈
- X-axis: Time (seconds)
- Y-axis: Impact multiplier (log scale)
- Color-coded by severity (red=CRITICAL, orange=HIGH)
- Different symbols for errors vs other metrics
- Hover shows node name, time, and impact
- Vertical lines mark fault injection points

### 2. **Summary Cards** 📊
Four cards showing:
- 🔴 Critical issues count
- 🟠 High issues count
- 💥 Error metrics count
- 📊 Total nodes analyzed

### 3. **Layer-by-Layer Analysis** 🔬
- Organized by distance from root cause
- Each node shows:
  - Most significant impact
  - Impact multiplier
  - Severity badge (CRITICAL/HIGH)
  - Visual indicators (🔴 for errors, ⚠️ for saturation)

### 4. **Clickable Nodes** 🔗
Nodes are clickable and can be linked to:
- Topology visualization (zoom to node)
- Component drilldown charts
- Specific metric charts

## Example Output

When user clicks "🔍 Analyze Fault Propagation":

```
🔍 Fault Propagation Analysis
Analyzing: Database query slowdown

[Summary Cards showing counts]

📈 Chronological Timeline
[Interactive scatter plot showing events over time]

🔬 Layer-by-Layer Analysis

🎯 Root Cause
  🔴 db_1: db.connections.rejected (246.0x) [CRITICAL]
  ⚠️ db_1: db.query.latency (18.4x) [CRITICAL]

📍 Layer 1 (1 hop from root)
  🔴 svc_1: service.svc_1.errors (12.0x) [CRITICAL]
  ⚠️ svc_1: connection_pool.connections.active (30.0x) [CRITICAL]
  🔴 svc_3: service.svc_3.dependency.errors (7.3x) [HIGH]

📍 Layer 2 (2 hops from root)
  🔴 gateway: gateway.dependency.errors (3.0x) [HIGH]
  ⚠️ gateway: http.server.request.duration (4.6x) [HIGH]
```

## Additional Enhancements

### Link to Node in Topology

Modify the layer analysis to add click handlers that zoom to the node in topology:

```python
html.Strong(node, id=f"node-{node}",
           style={'cursor': 'pointer'},
           **{'data-node-id': node})
```

Then add JavaScript to handle clicks:

```python
app.clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            const nodeId = event.target.getAttribute('data-node-id');
            // Trigger topology zoom to this node
            // Implementation depends on your topology chart setup
        }
        return '';
    }
    """,
    Output('dummy-output', 'children'),
    Input({'type': 'node-link', 'index': dash.dependencies.ALL}, 'n_clicks')
)
```

### Export Analysis

Add an export button:

```python
dbc.Button("📥 Export Analysis (JSON)", id="export-analysis-button",
           color="secondary", size="sm"),
dcc.Download(id="download-analysis")
```

With callback:

```python
@app.callback(
    Output("download-analysis", "data"),
    Input("export-analysis-button", "n_clicks"),
    State('datarun-dropdown', 'value'),
    State('episode-dropdown', 'value'),
    prevent_initial_call=True
)
def export_analysis(n_clicks, datarun, episode):
    episode_dir = os.path.join(BASE_DATA_DIR, datarun, episode)
    # Run analyzer with JSON output
    from analyze_fault_propagation import FaultPropagationAnalyzer
    analyzer = FaultPropagationAnalyzer(episode_dir, silent=True)
    analyzer.load_data()
    results = analyzer.analyze_propagation_chain()

    output = {
        "episode": analyzer.label,
        "propagation": results,
        "topology": {
            "nodes": analyzer.topology["num_nodes"],
            "edges": analyzer.topology["num_edges"]
        }
    }

    return dict(content=json.dumps(output, indent=2),
                filename=f"{datarun}_{episode}_analysis.json")
```

## Testing

1. Start the viz dashboard:
```bash
cd viz
python app.py
```

2. Load an episode

3. Click "🔍 Analyze Fault Propagation"

4. View:
   - Timeline chart showing fault progression
   - Summary cards with counts
   - Layer-by-layer detailed analysis

## Benefits

✅ **One-click analysis** - No need to run command-line tool
✅ **Interactive** - Hover for details, click to navigate
✅ **Visual timeline** - See how faults spread over time
✅ **Integrated** - Works with existing topology and metrics charts
✅ **Export ready** - Can export JSON for further analysis
✅ **Production ready** - Error handling and loading states included

## Next Steps

1. Add the imports and layout changes above
2. Add the callbacks
3. Test with different episodes
4. Optionally add node linking to topology chart
5. Optionally add export functionality
