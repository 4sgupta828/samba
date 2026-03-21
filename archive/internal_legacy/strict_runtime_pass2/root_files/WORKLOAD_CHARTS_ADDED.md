# Workload Generator Charts - Integration Complete ✅

## Summary

Added comprehensive workload generator visualizations to the Samba Telemetry Dashboard, matching the charts from `~/sim/src/control_ui`.

## What Was Added

### 1. New Chart Module: `viz/charts/workload.py`

Three main chart functions:

#### A. **Connection Pool Chart** (`create_connection_pool_chart`)
Shows workload generator resource utilization:
- **Connection Pool Utilization** (%)
  - Shows how busy the connection pool is
  - 100% = All connections in use (bottlenecked)

- **Active Connections** (count)
  - Number of concurrent requests being processed

- **In-Flight Requests** (queue depth)
  - Requests waiting to be sent
  - High values indicate backpressure

**Visualization**: 2-row subplot with dual y-axis on top row

#### B. **Circuit Breaker Chart** (`create_circuit_breaker_chart`)
Shows protective circuit breaker state over time:
- **CLOSED (0)**: Normal operation, all requests go through
- **OPEN (1)**: High failure rate detected, rejecting requests to protect system
- **HALF_OPEN (0.5)**: Testing recovery, limited requests allowed

**Visualization**: Step chart showing state transitions

#### C. **Request Outcomes Chart** (`create_request_outcomes_chart`)
Shows request outcomes as rate (req/s):
- **Successful** requests (green)
- **Failed** requests (red)
- **Timed out** requests (yellow)
- **Rejected - Circuit Breaker Open** (magenta, dashed)
- **Rejected - Queue Full** (orange, dashed)

**Visualization**: Stacked area chart + overlay lines

### 2. Dashboard Integration: `viz/app.py`

**Added:**
1. Import statement for workload charts (line 21)
2. Workload section in layout (lines 269-279)
3. Callback to render workload dashboard (lines 617-630)

**Location in UI:**
```
📋 Episode Metadata
    ↓
📈 Golden Signals
    ↓
🔌 Workload Generator  ← NEW!
    ↓
🗺️ System Topology
    ↓
... other sections ...
```

## Features

### Fault Injection Markers
All charts include:
- **Red shaded region**: Fault injection period
- **Red dashed line**: Fault start time
- **Annotation**: "Fault Injection" label

### Interactive Hover
- Unified hover across time axis
- Shows values for all metrics at given time
- Clear labels and units

### Dark Theme
- Matches existing dashboard theme
- Plotly dark template
- Color-coded metrics for clarity

## Usage

1. **Start Dashboard:**
   ```bash
   cd viz
   PORT=8051 python app.py
   ```

2. **Open Browser:**
   ```
   http://localhost:8051
   ```

3. **Load Episode:**
   - Select data run from dropdown
   - Select episode
   - Click "Load Episode"

4. **View Workload Charts:**
   - Scroll down to "🔌 Workload Generator" section
   - See all three charts:
     - Connection Pool & In-Flight Requests
     - Circuit Breaker State
     - Request Outcomes

## Interpreting the Charts

### Healthy Episode
```
Connection Pool Utilization: 40-60%
Circuit Breaker: CLOSED (0) for entire episode
Request Outcomes: 99%+ success rate
```

### Failing Episode (Circuit Breaker Triggered)
```
Connection Pool Utilization: 95-100%
Circuit Breaker: Opens after ~5s (state = 1)
Request Outcomes:
  - First 5s: 80% success
  - After 5s: 0.1% success, 95% rejected (circuit open)
```

## Example Analysis

Using the problematic episode `data_20251124_191951/ep_0`:

**What the charts show:**
1. **Connection Pool**: Utilization spikes to 95% immediately
2. **Circuit Breaker**: Opens at t=5s, stays OPEN for 96% of episode
3. **Request Outcomes**:
   - 47,492 attempted
   - 61 successful (0.1%)
   - 45,459 rejected (circuit breaker)

**Diagnosis**: svc_3 failed at startup → frontend failures → circuit breaker opened → most requests rejected

## Quick Analysis Tool

Also created `analyze_workload.py` for CLI analysis:

```bash
python analyze_workload.py data/data_20251124_191951/ep_0
```

Shows:
- Request success/failure breakdown
- Rejection reasons
- Circuit breaker behavior
- Connection pool pressure
- Automatic diagnosis

## Comparison with Old Control UI

### Parity Achieved ✅

| Chart | Old Control UI | New Samba Viz |
|-------|---------------|---------------|
| Connection Pool Utilization | ✅ | ✅ |
| Active Connections | ✅ | ✅ |
| In-Flight Requests | ✅ | ✅ |
| Circuit Breaker State | ✅ | ✅ |
| Request Outcomes | ✅ | ✅ |
| Fault Markers | ✅ | ✅ |
| Dark Theme | ✅ | ✅ |

### Improvements over Old Version

1. **Better Integration**: Embedded in main dashboard, no separate page needed
2. **Consistent Theme**: Matches rest of Samba dashboard
3. **Fault Context**: Automatic fault injection markers on all charts
4. **Hover Details**: More informative hover tooltips
5. **Stacked Areas**: Request outcomes use stacked areas for better visualization

## Files Modified

1. **`viz/charts/workload.py`** - NEW (420 lines)
   - Connection pool chart
   - Circuit breaker chart
   - Request outcomes chart
   - Dashboard wrapper

2. **`viz/app.py`** - MODIFIED (3 changes)
   - Added import (line 21)
   - Added UI section (lines 269-279)
   - Added callback (lines 617-630)

## Testing

Tested with:
- ✅ Healthy episode: `data_20251124_182756/ep_0`
- ✅ Failing episode: `data_20251124_191951/ep_0`
- ✅ Charts render correctly
- ✅ Fault markers positioned correctly
- ✅ All metrics display properly

## Next Steps

The workload charts are fully functional! You can:

1. **Use the dashboard** to visualize any episode
2. **Compare episodes** to understand different failure patterns
3. **Analyze circuit breaker behavior** for GNN training insights
4. **Identify bottlenecks** in workload generator

---

**Status**: ✅ COMPLETE AND RUNNING

**Dashboard URL**: http://localhost:8051

**Date**: 2025-11-24
**Author**: Claude (Sonnet 4.5)
