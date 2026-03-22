# Dataraft Telemetry Dashboard - Test Plan

**Purpose**: Ensure the dashboard correctly visualizes simulation episode data and all interactive features work as expected.

**Version**: 1.0
**Date**: 2025-11-21

---

## 📋 Test Environment

### Prerequisites
- [ ] Python 3.9+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Episode data available in `data/final_validation/` or custom directory
- [ ] At least 2-3 episodes available for testing

### Browser Compatibility
Test on at least one of:
- [ ] Chrome/Chromium (recommended)
- [ ] Firefox
- [ ] Safari
- [ ] Edge

---

## 🧪 Test Cases

### 1. Application Startup

#### Test 1.1: Basic Launch
**Objective**: Verify the application starts without errors

**Steps**:
1. Navigate to `viz/` directory
2. Run `python app.py`
3. Observe console output

**Expected Result**:
```
Starting Dataraft Telemetry Dashboard...
Data directory: ../data/final_validation
Loading episodes...
Found N episodes: ['ep_0', 'ep_1', ...]

🚀 Dashboard running at http://localhost:8050
```
- [ ] No Python errors or tracebacks
- [ ] Server starts on port 8050
- [ ] Episode list is displayed

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 1.2: Custom Data Directory
**Objective**: Verify custom data directory works

**Steps**:
1. Set environment variable: `export DATARAFT_DATA_DIR=../data/train`
2. Run `python app.py`
3. Verify episodes are loaded from custom directory

**Expected Result**:
- [ ] Console shows correct data directory path
- [ ] Episodes from custom directory are listed

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 2. UI Loading and Layout

#### Test 2.1: Page Load
**Objective**: Verify dashboard loads in browser

**Steps**:
1. Start the application
2. Open `http://localhost:8050` in browser
3. Observe page rendering

**Expected Result**:
- [ ] Page loads without errors (check browser console)
- [ ] Title displays: "🔍 Dataraft Telemetry Dashboard"
- [ ] Episode dropdown is visible
- [ ] "Load Episode" button is visible
- [ ] Four main sections are visible (metadata, topology, signals, propagation)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 2.2: Episode Dropdown Population
**Objective**: Verify episode list populates correctly

**Steps**:
1. Click on the episode dropdown
2. Observe available options

**Expected Result**:
- [ ] Dropdown contains all episodes from data directory
- [ ] Episodes are in format: `ep_0`, `ep_1`, etc.
- [ ] First episode is pre-selected by default

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 3. Episode Loading

#### Test 3.1: Load First Episode
**Objective**: Verify episode data loads successfully

**Steps**:
1. Ensure `ep_0` is selected in dropdown
2. Click "Load Episode" button
3. Observe loading status and content update

**Expected Result**:
- [ ] Loading spinner appears briefly
- [ ] Status message shows: "✓ Loaded ep_0"
- [ ] Metadata card appears with:
  - Episode number
  - Level and scenario description
  - Root cause node (in red)
  - Fault type
  - Timeline information
  - Topology stats (nodes, edges, frontends)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 3.2: Load Different Episodes
**Objective**: Verify switching between episodes works

**Steps**:
1. Load `ep_0`
2. Select `ep_1` from dropdown
3. Click "Load Episode" button
4. Repeat for `ep_2` or `ep_3`

**Expected Result**:
- [ ] Each episode loads without errors
- [ ] Metadata card updates with correct information
- [ ] Visualizations update to show new episode data
- [ ] Root cause node changes between episodes

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 4. Topology Visualization

#### Test 4.1: Topology Graph Rendering
**Objective**: Verify topology graph displays correctly

**Steps**:
1. Load any episode
2. Examine the topology graph in the left panel

**Expected Result**:
- [ ] Network graph is displayed
- [ ] Nodes are visible and properly positioned
- [ ] Edges (connections) are visible between nodes
- [ ] Root cause node is highlighted in red
- [ ] Legend shows all component types:
  - Gateway (gray diamond)
  - Service (blue circle)
  - Database (green square)
  - Cache (orange hexagon)
  - Queue (purple pentagon)
  - External (red star)
  - Root Cause (bright red)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 4.2: Node Hover Information
**Objective**: Verify hover tooltips work

**Steps**:
1. Load any episode
2. Hover mouse over different nodes in topology graph

**Expected Result**:
- [ ] Tooltip appears on hover
- [ ] Tooltip shows:
  - Node ID
  - Component type
  - "ROOT CAUSE" label for root cause node
  - "Click for details" prompt

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 4.3: Node Click - Service
**Objective**: Verify clicking on a service node shows drill-down

**Steps**:
1. Load any episode
2. Find a service node (blue circle) - e.g., `svc_0`
3. Click on the node

**Expected Result**:
- [ ] Component drill-down section expands below topology
- [ ] Header shows component ID and type: "Component: svc_X" / "Type: ApiService"
- [ ] Six charts are displayed:
  1. CPU Utilization
  2. Memory Usage
  3. Request Duration (P50/P90/P99)
  4. Active Connections
  5. Active Threads
  6. Thread Pool Queue Depth
- [ ] Charts show time-series data
- [ ] X-axis shows simulation time
- [ ] All charts have proper labels

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 4.4: Node Click - Database
**Objective**: Verify clicking on a database node shows drill-down

**Steps**:
1. Load any episode with database nodes
2. Find a database node (green square) - e.g., `db_0`
3. Click on the node

**Expected Result**:
- [ ] Component drill-down section expands
- [ ] Header shows: "Type: SqlDatabase"
- [ ] Five charts are displayed:
  1. Query Latency (P50/P90/P99)
  2. Active Connections
  3. Connection Rejections
  4. CPU Utilization
  5. Memory Usage

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 4.5: Node Click - Root Cause
**Objective**: Verify clicking root cause node shows it's marked

**Steps**:
1. Load any episode
2. Click on the root cause node (bright red)

**Expected Result**:
- [ ] Drill-down expands
- [ ] Status shows: "⚠️ ROOT CAUSE" in red
- [ ] Component-specific charts are displayed
- [ ] Charts show anomalous behavior (e.g., high errors, high latency)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 5. Golden Signals Dashboard

#### Test 5.1: Request Rate Chart
**Objective**: Verify request rate chart displays correctly

**Steps**:
1. Load any episode
2. Examine "Request Rate" chart in upper-right panel

**Expected Result**:
- [ ] Chart displays two lines:
  - Attempted requests
  - Success requests
- [ ] X-axis shows simulation time (seconds)
- [ ] Y-axis shows requests per bucket
- [ ] Red dashed vertical line marks fault injection time
- [ ] Line indicates when fault starts (e.g., at 180s for level 4)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 5.2: Error Rate Chart
**Objective**: Verify error rate chart displays correctly

**Steps**:
1. Load any episode
2. Examine "Error Rate" chart

**Expected Result**:
- [ ] Chart shows error count over time
- [ ] Area is filled (shaded red)
- [ ] Errors increase after fault injection line
- [ ] Before fault injection, errors are minimal/zero
- [ ] After fault injection, errors spike

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 5.3: Latency Percentiles Chart
**Objective**: Verify latency chart displays correctly

**Steps**:
1. Load any episode
2. Examine "Latency Percentiles" chart

**Expected Result**:
- [ ] Chart shows three lines: P50, P90, P99
- [ ] Lines are color-coded (blue, orange, red)
- [ ] Y-axis shows latency in milliseconds
- [ ] Latency increases after fault injection
- [ ] P99 shows highest values (upper line)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 5.4: Saturation Chart
**Objective**: Verify resource saturation chart displays correctly

**Steps**:
1. Load any episode
2. Examine "Resource Saturation" chart

**Expected Result**:
- [ ] Chart shows two metrics:
  - CPU Utilization (left Y-axis, %)
  - Memory Usage (right Y-axis, MB)
- [ ] Both metrics are plotted over time
- [ ] Dual Y-axis is visible
- [ ] Lines are distinguishable (different colors)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 6. Failure Propagation Timeline

#### Test 6.1: Correlation Matrix
**Objective**: Verify propagation matrix displays correctly

**Steps**:
1. Load any episode
2. Scroll to "Failure Propagation Timeline" section
3. Examine the correlation matrix heatmap

**Expected Result**:
- [ ] Heatmap is displayed
- [ ] Y-axis lists all components
- [ ] X-axis shows time buckets (e.g., "0-30s", "30-60s", etc.)
- [ ] Color coding:
  - 🟢 Green = Healthy
  - 🟡 Orange = Degraded
  - 🔴 Red = Failing
- [ ] Root cause component row is highlighted (dotted line)
- [ ] Vertical dashed line marks fault injection time
- [ ] Components show degradation progression over time

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 6.2: Metric Cascade View
**Objective**: Verify cascade visualization works

**Steps**:
1. Load any episode
2. Examine the metric cascade (small multiples below heatmap)

**Expected Result**:
- [ ] Multiple small charts (one per component)
- [ ] Each chart shows normalized metric over time
- [ ] Root cause component is highlighted in red
- [ ] Other components are in light blue
- [ ] Vertical dashed lines mark fault injection in each chart
- [ ] Time progression is visible

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 6.3: Propagation Path Description
**Objective**: Verify propagation path is described

**Steps**:
1. Load any episode
2. Examine the left side of propagation timeline section

**Expected Result**:
- [ ] "Propagation Path" heading is visible
- [ ] Root cause is listed with node ID
- [ ] Fault start time is shown
- [ ] Upstream components are listed (if any)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 7. Different Episode Levels

#### Test 7.1: Level 1 Episode
**Objective**: Verify Level 1 (Simple Service Failures) displays correctly

**Steps**:
1. Find a Level 1 episode (check label.json or metadata card)
2. Load the episode
3. Examine all visualizations

**Expected Result**:
- [ ] Metadata shows: "Level: 1"
- [ ] Topology has ~5 nodes
- [ ] Root cause is a service node
- [ ] Fault type relates to CPU/memory/latency
- [ ] Propagation is minimal (isolated failure)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 7.2: Level 2 Episode
**Objective**: Verify Level 2 (Database Bottlenecks) displays correctly

**Steps**:
1. Find a Level 2 episode
2. Load the episode
3. Examine all visualizations

**Expected Result**:
- [ ] Metadata shows: "Level: 2"
- [ ] Topology has ~10 nodes
- [ ] Root cause is a database node (green square)
- [ ] Downstream services show degradation
- [ ] Query latency increases in drill-down

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 7.3: Level 4 Episode (External Dependencies)
**Objective**: Verify Level 4 episodes display correctly

**Steps**:
1. Find a Level 4 episode
2. Load the episode
3. Examine all visualizations

**Expected Result**:
- [ ] Metadata shows: "Level: 4"
- [ ] Scenario mentions "External API"
- [ ] Topology has ~25 nodes
- [ ] Root cause is an external service node (red star)
- [ ] Services calling external show errors
- [ ] Error rate spikes in golden signals

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 8. Edge Cases and Error Handling

#### Test 8.1: No Episodes Available
**Objective**: Verify graceful handling when no episodes exist

**Steps**:
1. Set `DATARAFT_DATA_DIR` (or legacy `SAMBA_DATA_DIR`) to an empty directory
2. Start the application
3. Open in browser

**Expected Result**:
- [ ] Console shows: "Found 0 episodes: []"
- [ ] Dropdown is empty or shows "No episodes"
- [ ] No Python errors or crashes
- [ ] UI displays gracefully

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 8.2: Missing Data Files
**Objective**: Verify error handling for incomplete episodes

**Steps**:
1. Create a test episode directory with only `label.json`
2. Try to load the episode

**Expected Result**:
- [ ] Error message is displayed
- [ ] Application doesn't crash
- [ ] User can try loading a different episode

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 8.3: Invalid Episode Data
**Objective**: Verify handling of corrupted data

**Steps**:
1. Load an episode
2. If charts fail to render, check browser console

**Expected Result**:
- [ ] Partial data is displayed where available
- [ ] Missing charts show "No Data" message
- [ ] Application remains functional

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 9. Interactivity and Responsiveness

#### Test 9.1: Multiple Component Clicks
**Objective**: Verify rapid component switching works

**Steps**:
1. Load any episode
2. Quickly click multiple different nodes in topology
3. Observe drill-down updates

**Expected Result**:
- [ ] Drill-down updates for each click
- [ ] No lag or freezing
- [ ] Charts update correctly
- [ ] No JavaScript errors in console

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 9.2: Chart Hover and Zoom
**Objective**: Verify Plotly interactivity works

**Steps**:
1. Load any episode
2. Hover over different points in charts
3. Try zooming in/out on charts (drag to select area)
4. Try panning (shift + drag)
5. Double-click to reset zoom

**Expected Result**:
- [ ] Hover shows data point values
- [ ] Zoom works smoothly
- [ ] Pan works smoothly
- [ ] Reset returns to original view
- [ ] All charts support these interactions

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 9.3: Browser Window Resize
**Objective**: Verify responsive layout

**Steps**:
1. Load any episode
2. Resize browser window to different widths
3. Observe layout adjustments

**Expected Result**:
- [ ] Layout adjusts to window size
- [ ] Charts remain visible and usable
- [ ] No overlapping elements
- [ ] Mobile view is acceptable (optional)

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 10. Performance

#### Test 10.1: Initial Load Time
**Objective**: Measure page load performance

**Steps**:
1. Clear browser cache
2. Start application
3. Open `http://localhost:8050`
4. Measure time until page is fully loaded

**Expected Result**:
- [ ] Page loads in < 5 seconds
- [ ] No noticeable delays
- [ ] Smooth rendering

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Time Measured**: _____ seconds

---

#### Test 10.2: Episode Load Time
**Objective**: Measure episode loading performance

**Steps**:
1. Select an episode
2. Click "Load Episode"
3. Measure time until all visualizations are displayed

**Expected Result**:
- [ ] Small episodes (Level 1): < 3 seconds
- [ ] Large episodes (Level 4): < 10 seconds
- [ ] No browser freezing during load

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Time Measured**: _____ seconds

---

#### Test 10.3: Memory Usage
**Objective**: Verify reasonable memory consumption

**Steps**:
1. Load multiple episodes sequentially
2. Monitor browser memory usage (browser dev tools)

**Expected Result**:
- [ ] Memory usage stays < 500 MB
- [ ] No memory leaks (memory returns after switching episodes)
- [ ] Browser remains responsive

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 11. Data Accuracy

#### Test 11.1: Ground Truth Verification
**Objective**: Verify displayed data matches source files

**Steps**:
1. Load `ep_0`
2. Open `data/final_validation/ep_0/label.json` manually
3. Compare values

**Expected Result**:
- [ ] Episode number matches
- [ ] Level matches
- [ ] Scenario description matches
- [ ] Root cause node matches
- [ ] Fault start time matches
- [ ] Topology stats (nodes, edges) match

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 11.2: Fault Injection Timing
**Objective**: Verify fault markers align with actual fault time

**Steps**:
1. Load any episode
2. Note the fault start time from metadata (e.g., 180s)
3. Check all charts with fault markers

**Expected Result**:
- [ ] All red vertical lines are at the same time
- [ ] Time matches `fault_start_time` from label
- [ ] Error rate increases after this line
- [ ] Metrics show degradation after this line

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 11.3: Component Count
**Objective**: Verify topology node count is accurate

**Steps**:
1. Load any episode
2. Count nodes in topology graph manually
3. Compare with metadata card "Topology: X nodes"

**Expected Result**:
- [ ] Visual node count matches metadata
- [ ] All component types are represented
- [ ] No duplicate nodes
- [ ] No missing nodes

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

### 12. Console Checks

#### Test 12.1: Python Console Output
**Objective**: Verify no unexpected errors in Python console

**Steps**:
1. Start application
2. Load multiple episodes
3. Click various components
4. Monitor terminal output

**Expected Result**:
- [ ] No Python tracebacks
- [ ] No error messages
- [ ] Only INFO/DEBUG log messages
- [ ] Callback executions complete successfully

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

#### Test 12.2: Browser Console Output
**Objective**: Verify no JavaScript errors

**Steps**:
1. Open browser developer console (F12)
2. Load episode and interact with dashboard
3. Check console for errors

**Expected Result**:
- [ ] No JavaScript errors (red messages)
- [ ] No 404 errors (missing resources)
- [ ] Only INFO/DEBUG messages from Dash
- [ ] No CORS errors

**Status**: ⬜ Pass | ⬜ Fail | ⬜ Skip

**Notes**:
```


```

---

## 📊 Test Summary

### Execution Details
- **Tester Name**: _________________
- **Date**: _________________
- **Environment**: _________________
- **Browser**: _________________
- **Python Version**: _________________

### Results Overview

| Category | Total Tests | Passed | Failed | Skipped |
|----------|-------------|--------|--------|---------|
| Startup | 2 | | | |
| UI Loading | 2 | | | |
| Episode Loading | 2 | | | |
| Topology | 5 | | | |
| Golden Signals | 4 | | | |
| Propagation | 3 | | | |
| Episode Levels | 3 | | | |
| Edge Cases | 3 | | | |
| Interactivity | 3 | | | |
| Performance | 3 | | | |
| Data Accuracy | 3 | | | |
| Console Checks | 2 | | | |
| **TOTAL** | **35** | | | |

**Pass Rate**: _____ %

---

## 🐛 Issues Found

### Issue 1
**Title**: _________________
**Severity**: 🔴 Critical | 🟡 Major | 🟢 Minor
**Test Case**: _________________
**Description**:
```


```
**Steps to Reproduce**:
```


```
**Expected vs Actual**:
```


```

---

### Issue 2
**Title**: _________________
**Severity**: 🔴 Critical | 🟡 Major | 🟢 Minor
**Test Case**: _________________
**Description**:
```


```

---

## ✅ Sign-Off

- [ ] All critical tests passed
- [ ] All major issues documented
- [ ] Dashboard is ready for use
- [ ] Known issues documented

**Tester Signature**: _________________
**Date**: _________________

---

## 📝 Notes and Recommendations

```




```

---

*End of Test Plan*
