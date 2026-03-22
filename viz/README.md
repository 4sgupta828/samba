# Dataraft Telemetry Dashboard

A streamlined visualization tool for exploring **simulation episodes** from Dataraft (metrics, topology, ground truth, failure propagation).

This UI is part of the public simulation + whitebox RCA framework release. For repo scope and archived internal artifacts, see `../PUBLIC_RELEASE_SCOPE.md`.

## 🎯 Purpose

This dashboard provides a focused interface for understanding **simulated incidents** and **episode artifacts**:
- **System Topology**: Interactive network graph showing component relationships
- **Golden Signals**: Request rate, error rate, latency, and saturation metrics
- **Component Drill-Down**: Detailed metrics for individual components
- **Failure Propagation**: Visualize how failures cascade through the system

## 🚀 Quick Start

### Installation

```bash
cd ~/dataraft/viz
pip install -r requirements.txt
```

### Running the Dashboard

```bash
# Default: Load episodes from ../data/final_validation
python app.py

# Specify custom data directory
export SAMBA_DATA_DIR=../data/train
python app.py

# Custom port
export PORT=8080
python app.py
```

The dashboard will be available at `http://localhost:8050` (or your custom port).

## 📊 Features

### 1. Episode Selector
- Browse all available episodes in the data directory
- View ground truth metadata (root cause, fault type, timeline)

### 2. System Topology
- **Interactive network graph** with color-coded nodes by type:
  - 🔷 Gateway (diamond, gray)
  - 🔵 Service (circle, blue)
  - 🟢 Database (square, green)
  - 🟠 Cache (hexagon, orange)
  - 🟣 Queue (pentagon, purple)
  - ⭐ External (star, red)
- **Root cause highlighting** in bright red
- **Click any node** to drill down into detailed metrics
- **Intelligent filtering**: Toggle visibility of node types to reduce clutter
  - Dynamically detects all node types in the episode
  - Hide Agents (ComputeAgent), Services, Databases, or any other type
  - Root cause always visible regardless of filters
  - Reduces view from 50+ nodes to ~20 essential nodes

### 3. Golden Signals Dashboard

Four key metrics that reveal system health:

#### Request Rate
- Shows traffic patterns and workload changes
- Tracks attempted vs successful requests

#### Error Rate
- Aggregate errors across all components
- Visualizes failure propagation timeline

#### Latency Percentiles
- P50, P90, P99 latency trends
- Averaged across all components

#### Resource Saturation
- CPU utilization and memory usage
- Dual-axis chart for easy comparison

All charts include a **fault injection marker** showing when the failure was introduced.

### 4. Component Drill-Down

Click any node in the topology to see detailed metrics:

**For Services (ApiService)**:
- CPU and memory utilization
- Request duration percentiles
- Active connections and connection pool
- Thread pool metrics and queue depth

**For Databases (SqlDatabase)**:
- Query latency percentiles
- Active connections and rejections
- CPU and memory utilization

**For Caches (InMemoryCache)**:
- Hit rate and miss rate
- Eviction rate
- Memory usage

**For Queues (MessageQueue)**:
- Queue depth (messages visible)
- Messages in-flight
- Message age

**For External Services (ExternalService)**:
- Request and error rates
- Latency percentiles

### 5. Failure Propagation Timeline

**Novel feature** designed to help understand causal relationships:

#### Correlation Matrix
- Heatmap showing component health over time buckets
- Color-coded: 🟢 Healthy | 🟡 Degraded | 🔴 Failing
- Vertical line marks fault injection
- Horizontal line highlights root cause

#### Metric Cascade
- Small multiples showing normalized metric trends
- Visualize when each component degrades
- Root cause highlighted in red

#### Propagation Path
- Lists root cause and affected components
- Shows dependency relationships

## 📁 Project Structure

```
viz/
├── app.py                      # Flask + Dash application (180 lines)
├── data_loader.py              # Episode data loading (280 lines)
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── charts/
│   ├── __init__.py
│   ├── topology.py             # Topology visualization (160 lines)
│   ├── metrics_overview.py    # Golden signals (220 lines)
│   ├── component_drilldown.py # Component details (330 lines)
│   └── propagation_timeline.py # Propagation viz (280 lines)
└── static/
    └── custom.css              # (Optional) Custom styling
```

**Total:** ~1,450 lines (vs 5,000+ in original control UI) ✅

## 🔧 Configuration

### Environment Variables

- `SAMBA_DATA_DIR`: Path to episode data directory (default: `../data/final_validation`)
- `PORT`: Dashboard port (default: `8050`)

### Example

```bash
export SAMBA_DATA_DIR=/path/to/episodes
export PORT=9000
python app.py
```

## 📝 Episode Data Format

The dashboard expects episodes in this structure:

```
data/
├── final_validation/
│   ├── ep_0/
│   │   ├── label.json              # Ground truth metadata
│   │   └── data_TIMESTAMP/
│   │       ├── infra_context.json  # Topology
│   │       ├── metrics.jsonl       # Time-series metrics
│   │       ├── ground_truth.json   # Detailed events
│   │       ├── logs.jsonl          # (Optional)
│   │       └── traces.jsonl        # (Optional)
│   ├── ep_1/
│   └── ...
```

## 🧪 Testing Individual Components

Each chart module can be tested independently:

```bash
# Test data loader
python data_loader.py

# Test topology chart
cd charts
python topology.py

# Test golden signals
python metrics_overview.py

# Test component drill-down
python component_drilldown.py

# Test propagation timeline
python propagation_timeline.py
```

## 🎓 Usage Workflow

1. **Launch the dashboard**
   ```bash
   python app.py
   ```

2. **Select an episode** from the dropdown

3. **Click "Load Episode"** to visualize

4. **Explore the topology**
   - Identify the root cause (red node)
   - See component types and relationships

5. **Review golden signals**
   - When did errors start?
   - How did latency change?
   - Resource saturation patterns

6. **Click a component** in the topology
   - Drill down into detailed metrics
   - Compare healthy vs failing components

7. **Study the propagation timeline**
   - Understand failure cascade
   - Identify affected components
   - See temporal relationships

## 🔍 Tips for Analysis

### Finding Root Causes
- Look for the **red node** in the topology
- Check **when degradation starts** in the correlation matrix
- Compare **before/after fault injection** in golden signals

### Understanding Propagation
- Follow **upstream components** from the root cause
- Look for **delayed degradation** in the cascade view
- Check **error rate spikes** in downstream services

### Comparing Episodes
- Load different episodes to see variety
- Compare **Level 1-4** scenarios
- Notice **different fault types** (CPU, errors, latency)

## 📊 Metrics Reference

### Common Metrics

| Metric | Description | Components |
|--------|-------------|------------|
| `workload.requests` | Request rate (attempted/success) | Global |
| `container.cpu.utilization` | CPU usage (%) | All |
| `container.memory.usage_mb` | Memory usage (MB) | All |
| `http.server.request.duration` | Request latency (P50/P90/P99) | Services |
| `db.query.latency` | Query latency (P50/P90/P99) | Databases |
| `connection_pool.connections.active` | Active connections | Services |
| `thread_pool.threads.active` | Active threads | Services |
| `cache.hit_rate` | Cache hit rate | Caches |
| `cache.miss_rate` | Cache miss rate | Caches |
| `mq.messages.visible` | Queue depth | Queues |
| `mq.messages.age_seconds` | Message age | Queues |

## 🐛 Troubleshooting

### Dashboard won't start
```bash
# Check if port is in use
lsof -i :8050

# Try a different port
export PORT=9000
python app.py
```

### No episodes found
```bash
# Verify data directory
export SAMBA_DATA_DIR=/path/to/episodes
ls $SAMBA_DATA_DIR  # Should show ep_0, ep_1, etc.
```

### Episode fails to load
```bash
# Test data loader directly
python -c "from data_loader import load_episode; load_episode('ep_0', '../data/final_validation')"
```

### Charts not displaying
- Check browser console for JavaScript errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Try refreshing the page (Cmd/Ctrl + R)

## 📚 Architecture Notes

### Design Principles

1. **Simplicity**: ~1,000 lines vs 5,000+ in control UI
2. **Focus**: Telemetry and episode visualization (no live simulation control in this UI)
3. **Ground Truth**: Always visible and prominent
4. **Interactivity**: Click to drill down, hover for details
5. **Causality**: Propagation timeline shows temporal relationships

### Performance

- Episodes are loaded on demand
- In-memory caching for loaded episodes
- Lazy evaluation of charts (only render when visible)

### Extensibility

To add new chart types:
1. Create a new module in `charts/`
2. Import in `app.py`
3. Add callback to update the chart
4. Add HTML container in the layout

## 🤝 Contributing

This is a streamlined tool for Dataraft simulation and RCA workflows. To extend:

1. Keep it **simple** (avoid feature creep)
2. Focus on **clarity of observability and incident data**
3. Maintain **~1,000 line budget**
4. Test with **real episodes**

## 📄 License

MIT License (same as the main Dataraft project)

## 🔗 Related Files

- **Parent Project**: `../README.md` (Dataraft main documentation)
- **Implementation Plan**: `../MigrateAndImproveUIPlan.md`
- **Execution Tracker**: `../Exec.md`

---

**Built for advancing AI in SRE workflows** ❤️
