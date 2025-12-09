# RCA Failure Analysis UI Integration Guide

This guide documents all changes needed to integrate RCA Failure Analysis into the Samba UI.

## ✅ Completed Changes

### 1. Created `/Users/sgupta/samba/viz/charts/failure_analysis.py`
- Module for rendering failure analysis results
- Functions: `create_failure_analysis_view()`, `create_rca_not_run_message()`, `create_rca_success_message()`

### 2. Updated `/Users/sgupta/samba/viz/data_loader.py`
- Added `list_data_runs(scope_dir)` - supports directory scoping
- Added `list_episodes(failed_only)` - filters failed RCA episodes
- Added `is_rca_failed()`, `is_rca_run()`, `has_failure_analysis()` - helper functions
- Added `list_scope_directories()` - lists available scope directories

### 3. Updated `/Users/sgupta/samba/viz/app.py` - Imports
```python
from data_loader import (list_data_runs, list_episodes, load_episode,
                          is_rca_run, is_rca_failed, has_failure_analysis,
                          list_scope_directories)
from charts.failure_analysis import (create_failure_analysis_view,
                                      create_rca_not_run_message,
                                      create_rca_success_message)
from analysis.sotaanalyzer.sota_propagation_analyzer import discover_and_validate_rca
from analyze_failures import FailureAnalyzer
```

---

## 🔧 Remaining Manual Changes Needed

### Step 1: Update Data Run Selector in app.py

**Location**: Find the "Data run and episode selectors" section (around line 466)

**Replace this:**
```python
dbc.Row([
    dbc.Col([
        dbc.Label("Select Data Run:", html_for="datarun-dropdown"),
        dcc.Dropdown(
            id='datarun-dropdown',
            options=[],
            value=None,
            placeholder="Select a data run...",
            clearable=False
        ),
    ], width=3),
    dbc.Col([
        # Copy path button
    ], width=1),
    dbc.Col([
        dbc.Label("Select Episode:", html_for="episode-dropdown"),
        dcc.Dropdown(
            id='episode-dropdown',
            options=[],
            value=None,
            placeholder="Select an episode...",
            clearable=False
        ),
    ], width=3),
```

**With this:**
```python
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
            options=[],
            value=None,
            placeholder="Select a data run...",
            clearable=False
        ),
    ], width=2),
    dbc.Col([
        # Copy path button (keep as is)
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
            options=[],
            value=None,
            placeholder="Select an episode...",
            clearable=False
        ),
    ], width=2),
```

---

### Step 2: Add RCA Failure Analysis Button

**Location**: Find the button row with "Run Forensics" (around line 508-518)

**Add after the "Run Forensics" button:**
```python
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
```

---

### Step 3: Add RCA Failure Analysis Container

**Location**: After the "Forensic Analysis Container" (around line 678)

**Add this:**
```python
    # RCA Failure Analysis Container
    dbc.Row([
        dbc.Col([
            html.Div(id='rca-failure-analysis-container', style={'display': 'none'})
        ])
    ], className="mb-3"),
```

---

### Step 4: Add New Callbacks

**Location**: Add these callbacks after existing callbacks (around line 878 onwards)

```python
# Callback 1: Populate scope dropdown
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


# Callback 2: Update data runs based on scope
@app.callback(
    Output('datarun-dropdown', 'options'),
    Output('datarun-dropdown', 'value'),
    Input('scope-dropdown', 'value'),
    prevent_initial_call=False
)
def populate_data_runs_with_scope(scope_dir):
    """Populate data run dropdown based on scope."""
    runs = list_data_runs(BASE_DATA_DIR, scope_dir=scope_dir if scope_dir else None)
    options = [
        {
            'label': f"{run['id']} ({run['timestamp']})",
            'value': run['path']
        }
        for run in runs
    ]
    default_value = runs[0]['path'] if runs else None
    return options, default_value


# Callback 3: Update episodes based on failed-only filter
@app.callback(
    Output('episode-dropdown', 'options'),
    Output('episode-dropdown', 'value'),
    Input('datarun-dropdown', 'value'),
    Input('failed-only-checkbox', 'value')
)
def populate_episodes_with_filter(data_run_path, failed_filter):
    """Populate episode dropdown with optional failed-only filter."""
    if not data_run_path:
        return [], None

    failed_only = 'failed' in failed_filter
    episodes = list_episodes(data_run_path, failed_only=failed_only)
    options = [{'label': ep, 'value': ep} for ep in episodes]
    default_value = episodes[0] if episodes else None
    return options, default_value


# Callback 4: Enable/disable RCA Failure Analysis button
@app.callback(
    Output('analyze-rca-failure-button', 'disabled'),
    Input('episode-data-store', 'data')
)
def update_rca_failure_button_state(episode_data):
    """Enable RCA failure analysis button when episode loaded."""
    return episode_data is None


# Callback 5: Run RCA Failure Analysis
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
    import os
    import json
    from pathlib import Path

    if not n_clicks or not datarun or not episode:
        return None, {'display': 'none'}

    try:
        episode_dir = os.path.join(datarun, episode)
        print(f"Running RCA failure analysis on: {episode_dir}")

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

            except Exception as e:
                print(f"  ERROR running RCA: {str(e)}")
                import traceback
                traceback.print_exc()

                return dbc.Alert([
                    html.H5("Error running RCA", className="alert-heading"),
                    html.Hr(),
                    html.P(f"Failed to run RCA discovery mode: {str(e)}")
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


# Callback 6: Hide RCA failure analysis when episode changes
@app.callback(
    [Output('rca-failure-analysis-container', 'children', allow_duplicate=True),
     Output('rca-failure-analysis-container', 'style', allow_duplicate=True)],
    [Input('episode-dropdown', 'value')],
    prevent_initial_call=True
)
def reset_rca_failure_analysis(_):
    """Hide RCA failure analysis when episode changes."""
    return None, {'display': 'none'}
```

---

### Step 5: Update Existing Callbacks

**Location**: Find the `populate_episodes` callback (around line 715-728)

**REMOVE THIS CALLBACK** (it's replaced by the new `populate_episodes_with_filter` callback)

---

## 🚀 Testing the Integration

Once all changes are applied:

1. **Start the server**:
   ```bash
   cd viz
   PORT=8051 python3 app.py
   ```

2. **Test Scope Filter**:
   - Select "batch_run" in scope dropdown
   - Verify only batch_run datasets appear

3. **Test Failed Filter**:
   - Check "Show Failed RCA Only"
   - Verify only failed episodes appear
   - If no failures, it should show empty list

4. **Test RCA Failure Analysis**:
   - Select an episode
   - Click "🚨 RCA Failure Analysis"
   - If RCA not run: it should auto-run it
   - If RCA succeeded: show success message
   - If RCA failed: show detailed failure analysis

---

## 📋 Expected Behavior

### First Click on "RCA Failure Analysis":
1. Checks if RCA has been run (`RCAInvestigated.marker` exists)
2. If not: Runs discovery mode RCA automatically
3. If RCA succeeds: Shows success message
4. If RCA fails: Runs failure analysis and displays results

### Subsequent Clicks:
- Loads cached results from `failure_analysis.json`
- Much faster (no re-computation)

### Failure Analysis Display Shows:
- ✅ Overview (dataset, episode, ground truth, fault type)
- 🥇 Top 3 candidates found by RCA
- 📉 Ground truth metrics (severity, health, impact timing)
- ⏱️ Temporal ordering check (was GT impacted first?)
- 💉 Fault injection check (was fault severe enough?)
- 💡 Hypotheses (why RCA failed)

---

## 🐛 Troubleshooting

### Issue: "RCA not run yet" always shows
- **Cause**: `RCAInvestigated.marker` file not being created
- **Fix**: Check `discover_and_validate_rca()` is being called correctly

### Issue: Failure analysis shows error
- **Cause**: Missing required files (`rca_analysis.json`, `label.json`, etc.)
- **Fix**: Ensure episode has all required data files

### Issue: Scope dropdown empty
- **Cause**: No subdirectories with episodes found
- **Fix**: Check `BASE_DATA_DIR` and directory structure

---

## 📝 File Summary

**Files Created:**
- `/Users/sgupta/samba/viz/charts/failure_analysis.py` ✅
- `/Users/sgupta/samba/viz/UI_INTEGRATION_GUIDE.md` (this file)

**Files Modified:**
- `/Users/sgupta/samba/viz/data_loader.py` ✅
- `/Users/sgupta/samba/viz/app.py` ⚠️ (partially - manual changes needed)

**Files Referenced:**
- `/Users/sgupta/samba/analyze_failures.py` (no changes)
- `/Users/sgupta/samba/analysis/sotaanalyzer/sota_propagation_analyzer.py` (no changes)
