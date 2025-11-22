# Telemetry Dashboard Migration Plan for Samba

**Date**: November 21, 2025
**Purpose**: Migrate and streamline the control UI from `~/sim/src/control_ui` to create a focused telemetry visualization dashboard for Samba GNN training data.

---

## Table of Contents

1. [Context & Background](#context--background)
2. [Current State Analysis](#current-state-analysis)
3. [Problem Statement](#problem-statement)
4. [Proposed Architecture](#proposed-architecture)
5. [Core Features](#core-features)
6. [Implementation Phases](#implementation-phases)
7. [Technical Details](#technical-details)
8. [Success Metrics](#success-metrics)

---

## Context & Background

### About Samba

**Samba** is a high-fidelity infrastructure simulator designed to generate infinite, diverse, and perfectly labeled training episodes for Graph Neural Networks (GNNs) that perform root cause analysis in microservice environments.

**Key Characteristics**:
- **Purpose**: Training data generation (not testing/validation)
- **Topology**: Procedurally generated unique microservice architectures
- **Ground Truth**: Every episode has labeled root cause, fault type, and timeline
- **Curriculum Learning**: 4 levels of increasing complexity
- **Output Format**: Episodes with metrics, logs, traces, and ground truth labels

### About the Existing Control UI

Located at `~/sim/src/control_ui`, this is a comprehensive Flask + Dash application with:
- **Simulation control**: Launch, monitor, and manage simulations
- **Scenario management**: Configure architectures and failure scenarios
- **Real-time monitoring**: Live metrics visualization
- **RCA integration**: Full root cause analysis tooling
- **Extensive charting**: 20+ chart types covering all observability signals
- **Code size**: ~5000+ lines across multiple files

### The Problem

The existing UI is **powerful but bloated** for Samba's needs:
- Too many features for visualizing static training data
- Complex real-time monitoring not needed
- RCA tools are what we're trying to train (chicken-egg problem)
- Hard to understand failure propagation and causality
- Mixes simulation control with telemetry visualization

---

## Current State Analysis

### Existing UI Structure

```
~/sim/src/control_ui/
├── app.py                    (600+ lines)  - Flask server + simulation control
├── dash_telemetry.py         (2000+ lines) - Main Dash app with all features
├── dash_charts.py            (4000+ lines) - 20+ chart creation functions
├── dash_data_loader.py       (2000+ lines) - Complex data loading
├── dash_dynamics_charts.py   (800+ lines)  - Service dynamics
├── utils/
│   ├── topology_graph.py     - NetworkX graph building
│   ├── topology_viz.py       - Plotly topology visualization
│   ├── rca_adapter.py        - RCA tool integration
│   └── rca_orchestrator_adapter.py
├── services/                 - Simulation control services
├── templates/                - HTML templates
└── static/                   - CSS/JS assets
```

### Samba Data Structure

```
data/train/ep_0/
├── label.json              # Ground truth: root cause, fault type, timeline
├── ground_truth.json       # Detailed failure injection events
├── infra_context.json      # Complete topology (components + relationships)
├── metadata.json           # Simulation metadata
├── metrics.jsonl           # Time-series metrics (JSONL format)
├── logs.jsonl              # Structured logs (optional)
├── traces.jsonl            # Distributed traces (optional)
└── configs/
    └── simulation_config.json
```

### What's Bloated and Not Needed

| Feature | Control UI | Samba Needs | Action |
|---------|-----------|-------------|--------|
| Simulation launch/control | ✅ | ❌ | **REMOVE** |
| Scenario management | ✅ | ❌ | **REMOVE** |
| Batch processing | ✅ | ❌ | **REMOVE** |
| Real-time monitoring | ✅ | ❌ | **REMOVE** (static data) |
| RCA tool integration | ✅ | ❌ | **REMOVE** (training RCA) |
| Deployment tracking | ✅ | ❌ | **REMOVE** (not in episodes) |
| Flame graphs | ✅ | ❌ | **REMOVE** |
| 20+ specialized charts | ✅ | ⚠️ | **SIMPLIFY** (keep 6-8) |
| Topology visualization | ✅ | ✅ | **MIGRATE + ENHANCE** |
| Golden signals | ✅ | ✅ | **MIGRATE** |
| Ground truth overlay | ❌ | ✅ | **NEW** |
| Propagation timeline | ❌ | ✅ | **NEW** |

---

## Problem Statement

### Goals

1. **Distill the UI** to focus only on telemetry visualization for training data
2. **Visualize topology** with clear component relationships
3. **Understand failure propagation** from root cause to symptoms
4. **Drill down** into individual components to see detailed metrics
5. **Show ground truth** prominently (what the GNN should learn)
6. **Keep it simple** and maintainable (~1000 lines vs 5000+)

### Non-Goals

- Real-time simulation monitoring (we load static episodes)
- Simulation launch/control (use `generate_dataset.py`)
- Advanced RCA features (that's what we're training)
- Production-grade deployment (research/training tool)

---

## Proposed Architecture

### Directory Structure

```
~/samba/viz/
├── app.py                          # Flask + Dash app (100-150 lines)
│                                   # - Episode selector
│                                   # - Simple routing
│                                   # - Embedded Dash dashboard
│
├── data_loader.py                  # Episode data loading (200-300 lines)
│                                   # - Load label.json, metrics.jsonl, etc.
│                                   # - Parse JSONL metrics into DataFrame
│                                   # - Extract topology from infra_context.json
│                                   # - Ground truth event parsing
│
├── charts/
│   ├── __init__.py
│   ├── topology.py                 # Interactive topology graph
│   │                               # - NetworkX → Plotly network diagram
│   │                               # - Root cause highlighting
│   │                               # - Clickable nodes for drill-down
│   │                               # - Edge styling (type, traffic)
│   │
│   ├── metrics_overview.py         # Golden Signals dashboard
│   │                               # - Request rate (workload patterns)
│   │                               # - Error rate (success vs failure)
│   │                               # - Latency percentiles (P50/P90/P99)
│   │                               # - Saturation (CPU/memory)
│   │
│   ├── component_drilldown.py      # Per-component detailed view
│   │                               # - Time-series for selected component
│   │                               # - Metric type depends on component role
│   │                               # - Upstream/downstream mini-graphs
│   │
│   ├── propagation_timeline.py     # **NEW** Failure propagation
│   │                               # - Timeline showing causal chain
│   │                               # - Animated/stepped propagation
│   │                               # - Metric correlation across components
│   │
│   └── comparison.py               # Compare episodes (optional)
│                                   # - Side-by-side topology
│                                   # - Metric comparisons
│
├── requirements.txt                # Minimal dependencies
├── static/
│   └── custom.css                  # Minimal styling
├── README.md                       # Usage instructions
└── MigrateAndImproveUIPlan.md     # This file
```

### Application Flow

```
User loads viz app
    ↓
Select episode from dropdown (ep_0, ep_1, ...)
    ↓
Load episode data (label, metrics, topology, ground truth)
    ↓
Display 4-panel dashboard:
    ┌─────────────────────────────────────────────────┐
    │  📊 Episode Metadata & Ground Truth             │
    │  Level 4 | External API errors | Root: ext_0    │
    │  Timeline: 120s-360s (ramp), 360s-600s (full)   │
    └─────────────────────────────────────────────────┘
    ┌──────────────────┬──────────────────────────────┐
    │  🗺️ Topology      │  📈 Golden Signals           │
    │  Interactive     │  - Request Rate              │
    │  Network Graph   │  - Error Rate                │
    │  Click nodes →   │  - Latency (P50/P90/P99)     │
    │  drill down      │  - Saturation (CPU/Memory)   │
    └──────────────────┴──────────────────────────────┘
    ┌─────────────────────────────────────────────────┐
    │  🔍 Component Drill-Down (click node above)     │
    │  Detailed time-series for selected component    │
    └─────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────┐
    │  🌊 Failure Propagation Timeline                │
    │  Animated causal chain from root to symptoms    │
    └─────────────────────────────────────────────────┘
```

---

## Core Features

### 1. Topology Visualization (ESSENTIAL)

**Purpose**: Understand the system architecture and identify root cause at a glance

**Features**:
- Interactive network graph (Plotly + NetworkX)
- **Color coding**:
  - By component type: service (blue), database (green), cache (orange), queue (purple), external (red), gateway (gray)
  - By health status: healthy (solid), degraded (yellow border), failed (red border)
  - Root cause: thick red border + label
- **Node attributes**:
  - Size proportional to metric values (e.g., CPU utilization)
  - Hover shows component details (type, role, state)
  - Click to drill down into detailed metrics
- **Edge styling**:
  - Thickness = traffic volume or error rate
  - Dashed = async connections (message queues)
  - Solid = sync connections (HTTP, DB, cache)
  - Color = latency (green=fast, red=slow)
- **Layout**: Hierarchical (gateway at top) or force-directed

**Migrate from**: `~/sim/src/control_ui/utils/topology_viz.py` (create_topology_visualization)

**Enhancements**:
- Add root cause highlighting from `label.json`
- Add failure propagation animation (Phase 4)

---

### 2. Golden Signals Dashboard (ESSENTIAL)

**Purpose**: Four key metrics that reveal system health at a glance

**Charts**:

#### a) Request Rate
- **Metric**: `workload.requests` (attempted vs success)
- **Y-axis**: Requests per time bucket
- **Shows**: Traffic patterns, when load increases/decreases
- **Ground truth overlay**: Vertical line at fault injection time

#### b) Error Rate
- **Metric**: `component.errors.total` aggregated across all components
- **Y-axis**: Error percentage or count
- **Shows**: When errors start appearing (symptom propagation)
- **Stacked by component**: See which components contribute errors

#### c) Latency Percentiles
- **Metrics**: `http.server.request.duration`, `db.query.latency`
- **Y-axis**: Milliseconds
- **Lines**: P50 (median), P90, P99
- **Shows**: Latency degradation patterns

#### d) Saturation (Resource Utilization)
- **Metrics**: `container.cpu.utilization`, `container.memory.usage_mb`
- **Y-axis**: Percentage (CPU) or MB (memory)
- **Shows**: Resource exhaustion, bottlenecks

**Migrate from**: `create_golden_signal_*` functions in `dash_charts.py:2700-3100`

**Enhancements**:
- Split view: before/during/after failure
- Highlight degradation zones

---

### 3. Component Drill-Down View (ESSENTIAL)

**Purpose**: Detailed investigation of individual component behavior

**Triggered by**: Clicking a node in the topology graph

**Displays**:

For **Services** (ApiService):
- CPU utilization
- Memory usage
- Request rate (by type: GET, POST, etc.)
- Request duration (P50/P90/P99)
- Error rate
- Connection pool utilization (if has downstream dependencies)

For **Databases** (SqlDatabase):
- Query latency (P50/P90/P99)
- Active connections
- Connection rejections
- CPU utilization
- Background job activity

For **Caches** (InMemoryCache):
- Hit rate
- Miss rate
- Eviction rate
- Memory usage

For **Queues** (MessageQueue):
- Messages visible (queue depth)
- Messages in-flight
- Message age (seconds)

For **External Services** (ExternalService):
- Request rate
- Error rate (injected failures visible here!)
- Latency

**Layout**: 2x3 grid of charts for selected component

**Migrate from**:
- `create_resource_metrics_chart` (dash_charts.py:1425)
- `create_database_metrics_chart` (dash_charts.py:1658)
- `create_cache_metrics_chart` (dash_charts.py:1711)

**Enhancements**:
- Show upstream/downstream components (mini-graphs)
- Correlation annotations (e.g., "Latency spike 30s after root cause")

---

### 4. Failure Propagation Timeline (ESSENTIAL - NEW FEATURE)

**Purpose**: Visualize how failures propagate through the system over time

**This is the killer feature for understanding GNN training data!**

**Design Option A: Animated Timeline**
```
Timeline slider: [========|-------------] 120s
                         ↑
                    Current time

Graph shows color wave:
- T=120s: ext_0 turns red (root cause)
- T=125s: svc_6 turns yellow (calls ext_0, sees errors)
- T=135s: gateway turns yellow (user requests failing)
- T=150s: Other services calling ext_0 turn yellow
```

**Design Option B: Correlation Matrix**
```
Component | T=0-120s | T=120-360s | T=360-600s
----------|----------|------------|------------
ext_0     | 🟢 Healthy | 🔴 FAILING | 🔴 FAILING  (root cause)
svc_6     | 🟢 Healthy | 🟡 Degraded | 🔴 Failing  (downstream)
gateway   | 🟢 Healthy | 🟡 Degraded | 🟡 Degraded (symptoms)
svc_0     | 🟢 Healthy | 🟢 Healthy  | 🟢 Healthy  (unaffected)
```

**Design Option C: Metric Cascade View**
Side-by-side small multiples showing when each component's key metric degrades:

```
ext_0 error_rate       ▁▁▁▁▁███████████  (T=120s)
svc_6 error_rate       ▁▁▁▁▁▁▁▃▅███████  (T=135s) ← 15s delay
gateway error_rate     ▁▁▁▁▁▁▁▁▁▃▅█████  (T=145s) ← 25s delay
```

**Implementation**:
- Use `ground_truth.json` events to get T0 (failure injection)
- Parse metrics to detect when each component crosses thresholds
- Build causal graph using topology + metric timing
- Animate or step through timeline

**This is NEW** - needs custom implementation

---

### 5. Training Episode Browser (ESSENTIAL)

**Purpose**: Navigate between episodes and understand metadata

**Features**:
- **Dropdown selector**: List all episodes (ep_0, ep_1, ..., ep_N)
- **Metadata display card**:
  ```
  📋 Episode 0
  Level: 4 - External Dependencies
  Scenario: External API error rate increase
  Root Cause: ext_0 (ExternalService)
  Fault Type: inject_errors (error_rate +0.3)

  Timeline:
  • Healthy baseline: 0s - 120s
  • Failure ramp: 120s - 360s (step progression)
  • Full failure: 360s - 600s

  Topology: 25 nodes, 26 edges
  Frontends: svc_6, svc_13
  ```
- **Ground truth always visible**: Show label data prominently

**Data source**: `label.json` in each episode directory

---

## Implementation Phases

### Phase 1: Foundation (1-2 days)

**Goal**: Basic app structure and episode loading

**Tasks**:
1. Set up Flask + Dash app skeleton
   - Create `app.py` with basic routes
   - Integrate Dash app at `/dash/` route
   - Add Bootstrap CSS for styling

2. Implement data loader (`data_loader.py`)
   - Function to list all episodes in `data/` directory
   - Function to load `label.json` (metadata + ground truth)
   - Function to load `infra_context.json` (topology)
   - Function to load `metrics.jsonl` → pandas DataFrame
   - Function to load `ground_truth.json` (detailed events)

3. Create episode selector UI
   - Dropdown to select episode
   - Display metadata card with ground truth info
   - Basic layout with placeholder sections for charts

**Deliverable**: Can load and display episode metadata

---

### Phase 2: Core Visualizations (2-3 days)

**Goal**: Topology graph + golden signals

**Tasks**:
1. Topology visualization (`charts/topology.py`)
   - Parse `infra_context.json` → NetworkX graph
   - Create Plotly network diagram
   - Color nodes by component type
   - Highlight root cause node (from label.json)
   - Add hover tooltips

2. Golden signals dashboard (`charts/metrics_overview.py`)
   - Request rate chart (workload.requests)
   - Error rate chart (component.errors.total)
   - Latency percentiles (http.server.request.duration)
   - Saturation (cpu.utilization, memory.usage_mb)
   - Add vertical line for fault injection time

3. Integrate into main dashboard
   - 2-column layout: topology left, signals right
   - Ground truth metadata at top

**Deliverable**: Can visualize topology and key metrics for any episode

---

### Phase 3: Drill-Down (2-3 days)

**Goal**: Click on topology node → see detailed metrics

**Tasks**:
1. Implement click handler for topology graph
   - Use Dash callbacks to capture node click events
   - Extract component ID from click data

2. Component drill-down charts (`charts/component_drilldown.py`)
   - Detect component type (service, database, cache, queue, external)
   - Filter metrics for selected component
   - Create 2x3 grid of relevant charts
   - Show upstream/downstream components

3. Add section below topology for drill-down view
   - Initially hidden
   - Expands when node is clicked
   - Show component name and type

**Deliverable**: Can drill down into any component's detailed metrics

---

### Phase 4: Propagation Analysis (2-3 days)

**Goal**: Visualize failure propagation over time

**Tasks**:
1. Propagation detection algorithm
   - Start from root cause node (from label.json)
   - For each time bucket, check downstream components for metric degradation
   - Build propagation tree with timestamps

2. Propagation timeline visualization (`charts/propagation_timeline.py`)
   - **Option A**: Animated graph with color wave
   - **Option B**: Correlation matrix (time buckets vs components)
   - **Option C**: Metric cascade (small multiples)
   - Choose based on clarity

3. Integrate into dashboard
   - Add section at bottom or as separate tab
   - Link to topology graph (highlight affected path)

**Deliverable**: Can see how failures propagate from root cause to symptoms

---

### Phase 5: Polish & Extras (1-2 days)

**Goal**: Make it production-ready

**Tasks**:
1. Episode comparison view (`charts/comparison.py`)
   - Select two episodes
   - Show topologies side-by-side
   - Compare key metrics

2. Export capabilities
   - Save visualizations as PNG
   - Export analysis as JSON
   - Generate report (PDF or HTML)

3. Documentation
   - Update README.md with usage instructions
   - Add inline code comments
   - Create example workflows

4. Performance optimization
   - Cache loaded episodes
   - Lazy load metrics data
   - Optimize chart rendering

**Deliverable**: Polished, documented, production-ready viz tool

---

## Technical Details

### Tech Stack

```txt
# Core framework
flask==3.0.0
dash==2.14.0
dash-bootstrap-components==1.5.0

# Visualization
plotly==5.18.0

# Data processing
pandas==2.1.0
networkx==3.2.0

# Utilities (already in Samba requirements)
# numpy, scipy, etc.
```

### Data Model Mapping

#### Episode Structure → UI Components

```python
# File: data/train/ep_0/label.json
# Purpose: Ground truth metadata
# Used by: Episode selector, metadata card, all charts (for markers)
{
    "episode": 0,
    "level": 4,
    "scenario": "External API error rate increase",
    "root_cause_node": "ext_0",
    "fault_start_time": 120,
    # ... more fields
}

# File: data/train/ep_0/infra_context.json
# Purpose: Complete system topology
# Used by: Topology graph, component drill-down
{
    "architecture": {
        "components": [
            {"id": "svc_0", "type": "ApiService", "state": {...}},
            # ... more components
        ],
        "relationships": [
            {"source": "svc_0", "target": "db_0", "type": "uses_database"},
            # ... more relationships
        ]
    }
}

# File: data/train/ep_0/metrics.jsonl
# Purpose: Time-series metrics
# Used by: All charts
# Each line is a JSON object:
{
    "ts": 1763763033151820032,
    "name": "db.query.latency",
    "labels": {"component.id": "db_1", "sim.time": 5},
    "summary": {"count": 131, "sum": 869.52, "p50": 7.5, "p90": 9.5, "p99": 9.95}
}

# File: data/train/ep_0/ground_truth.json
# Purpose: Detailed failure injection events
# Used by: Propagation timeline, event markers
{
    "events": [
        {
            "event_id": "ep0_fault",
            "event_type": "infrastructure_change",
            "sim_time": 120,
            "affected_components": ["ext_0"],
            "description": "error_rate increases by 0.3",
            # ... more fields
        }
    ]
}
```

#### Metrics Processing

```python
# Load metrics.jsonl into DataFrame
import pandas as pd
import json

def load_metrics(episode_dir: str) -> pd.DataFrame:
    """Load metrics from JSONL file into DataFrame."""
    metrics_file = f"{episode_dir}/data_*/metrics.jsonl"

    records = []
    with open(metrics_file, 'r') as f:
        for line in f:
            data = json.loads(line)

            # Flatten structure
            record = {
                'timestamp': data['ts'],
                'metric_name': data['name'],
                'sim_time': data['labels'].get('sim.time'),
                'component_id': data['labels'].get('component.id', 'global'),
            }

            # Handle value vs summary
            if 'value' in data:
                record['value'] = data['value']
            elif 'summary' in data:
                record.update({
                    f'{k}': v for k, v in data['summary'].items()
                })

            # Add additional labels as columns
            record.update(data['labels'])

            records.append(record)

    df = pd.DataFrame(records)
    return df

# Example usage:
# df = load_metrics('data/train/ep_0')
# latency_df = df[df['metric_name'] == 'db.query.latency']
# db1_latency = latency_df[latency_df['component_id'] == 'db_1']
```

### Chart Migration Guide

#### Example: Migrate Request Rate Chart

**From**: `dash_charts.py:create_golden_signal_request_rate`

**To**: `charts/metrics_overview.py:create_request_rate_chart`

**Changes**:
1. Remove real-time update logic (static data)
2. Simplify data filtering (no complex aggregations)
3. Add ground truth markers
4. Use episode metadata for annotations

```python
# BEFORE (control UI - complex)
def create_golden_signal_request_rate(metrics_df, run_id, component_type_filter=None,
                                       incident_marker_time=None, time_mode='simulation'):
    # 100+ lines of complex filtering, aggregation, real-time updates
    # Handles multiple run IDs, dynamic updates, etc.
    ...

# AFTER (Samba viz - simple)
def create_request_rate_chart(metrics_df, ground_truth):
    """Create request rate chart with ground truth overlay."""
    # Filter for workload metrics
    workload_df = metrics_df[metrics_df['metric_name'] == 'workload.requests']

    fig = go.Figure()

    # Add traces
    for req_type in ['attempted', 'success']:
        data = workload_df[workload_df['type'] == req_type]
        fig.add_trace(go.Scatter(
            x=data['sim_time'],
            y=data['value'],
            name=req_type.title(),
            mode='lines+markers'
        ))

    # Add fault injection marker
    fig.add_vline(
        x=ground_truth['fault_start_time'],
        line_dash="dash",
        line_color="red",
        annotation_text="Fault Injection"
    )

    fig.update_layout(
        title="Request Rate",
        xaxis_title="Simulation Time (s)",
        yaxis_title="Requests/bucket"
    )

    return fig
```

---

## Success Metrics

### Code Reduction
- **Target**: Reduce from ~5000 lines to ~1000 lines (80% reduction)
- **Measure**: `wc -l viz/**/*.py`

### Feature Focus
- **Target**: 8 core charts (vs 20+ in control UI)
- **Measure**: Count of chart creation functions

### User Experience
- **Target**: Load episode and see insights in <5 clicks
  1. Select episode
  2. View topology + golden signals
  3. Click component for drill-down
  4. View propagation timeline
  5. Understand root cause → symptoms

### Educational Value
- **Target**: Clearly show what GNN needs to learn
  - Ground truth always visible
  - Causal chains explicit
  - Temporal patterns highlighted

---

## Migration Checklist

### Pre-Migration
- [ ] Review existing control UI code structure
- [ ] Identify reusable utility functions
- [ ] Test loading sample Samba episodes
- [ ] Validate data format assumptions

### Phase 1: Foundation
- [ ] Create `viz/` directory structure
- [ ] Set up Flask + Dash skeleton
- [ ] Implement episode data loader
- [ ] Create episode selector dropdown
- [ ] Display metadata card

### Phase 2: Core Viz
- [ ] Topology graph (migrate + enhance)
- [ ] Request rate chart
- [ ] Error rate chart
- [ ] Latency percentiles chart
- [ ] Saturation chart
- [ ] Ground truth markers

### Phase 3: Drill-Down
- [ ] Click handler for topology nodes
- [ ] Service metrics drill-down
- [ ] Database metrics drill-down
- [ ] Cache metrics drill-down
- [ ] Queue metrics drill-down
- [ ] External service metrics drill-down

### Phase 4: Propagation
- [ ] Propagation detection algorithm
- [ ] Choose visualization approach (A/B/C)
- [ ] Implement propagation timeline
- [ ] Link to topology graph
- [ ] Test with different scenarios

### Phase 5: Polish
- [ ] Episode comparison view
- [ ] Export functionality
- [ ] Documentation (README)
- [ ] Performance optimization
- [ ] User testing

---

## Open Questions

1. **Logs and Traces**: Should we include logs.jsonl and traces.jsonl viewers?
   - **Recommendation**: Start without, add in Phase 5 if needed

2. **Episode Comparison**: How important is comparing multiple episodes?
   - **Recommendation**: Nice-to-have in Phase 5, focus on single episode first

3. **Propagation Visualization**: Which design (A/B/C) is most intuitive?
   - **Recommendation**: Prototype all three, user test to decide

4. **Deployment**: How will this be used (local dev, shared server)?
   - **Recommendation**: Start with local Flask dev server, can containerize later

5. **Real-time Updates**: Should episodes auto-refresh if regenerated?
   - **Recommendation**: No, manual reload is fine (static training data)

---

## Migration Strategy

### Recommended Approach

**Start Small, Iterate Fast**:
1. Begin with Phase 1 (foundation) to validate architecture
2. Implement Phase 2 (core viz) for immediate value
3. User feedback: Does this meet needs?
4. If yes, continue to Phase 3-4
5. If no, adjust before investing more time

**Copy-Paste with Simplification**:
- Don't rewrite from scratch
- Copy functions from control UI
- Strip out unnecessary complexity
- Adapt to Samba's data format

**Test with Real Data**:
- Use existing episodes from `data/comprehensive_test/` or `data/test_final/`
- Validate with all 4 curriculum levels
- Ensure propagation is clear for each scenario type

---

## Appendix: File References

### Key Files to Review in Control UI

```
~/sim/src/control_ui/
├── dash_charts.py
│   ├── Lines 1425-1573: create_resource_metrics_chart
│   ├── Lines 1658-1711: create_database_metrics_chart
│   ├── Lines 1711-1930: create_cache_metrics_chart
│   ├── Lines 2700-3100: create_golden_signal_* (4 functions)
│   └── Lines 3100-3300: create_database_* (3 functions)
│
├── utils/topology_viz.py
│   └── create_topology_visualization (entire file)
│
└── dash_data_loader.py
    ├── load_metrics (adapt for JSONL format)
    └── load_simulation_details (adapt for label.json)
```

### Samba Data Files to Understand

```
data/test_final/ep_0/
├── label.json              # START HERE - understand ground truth format
├── infra_context.json      # Understand topology structure
├── ground_truth.json       # Understand event format
├── metadata.json           # Understand simulation metadata
└── data_*/metrics.jsonl    # Understand metrics format (JSONL)
```

---

## Next Steps

1. **Review and validate this plan** with stakeholders
2. **Set up development environment** (`viz/` directory)
3. **Phase 1 kickoff**: Implement foundation and data loader
4. **Checkpoint after Phase 2**: Validate approach with basic viz
5. **Iterate based on feedback**

---

**End of Plan**
