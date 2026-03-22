# Dataraft: Microservice Simulation & Whitebox RCA Framework

**Dataraft** is a high-fidelity infrastructure simulator that generates **labeled, time-series-rich episodes** (metrics, logs, traces, topology, ground truth) for microservice-style systems. It ships with a **whitebox root-cause analysis (RCA)** stack and a **telemetry dashboard** to explore episodes and validate RCA behavior.

> **Note:** The Git repository may still use the historical folder or remote name (`samba`); the product and documentation use the name **Dataraft**.

## 🎯 Purpose

Traditional simulators often fix topology and scenarios. **Dataraft** focuses on **repeatable incident simulation** and **observability-aligned outputs** that:

1. **Ground truth per episode**: Root cause node, fault type, and timeline for each run
2. **Diverse topologies**: Procedural graphs so analysis generalizes beyond fixed architectures
3. **Temporal causality**: Propagation delays and gradual faults support realistic RCA and forensics
4. **Realistic observability**: Imperfect data (dropped metrics, skew, sampling) like production systems

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  generate_dataset.py                         │
│                    (Orchestrator)                            │
└────────────┬─────────────────────────────────────────┬──────┘
             │                                         │
     ┌───────▼────────┐                       ┌────────▼───────┐
     │  Topology      │                       │   Scenario     │
     │  Generator     │                       │   Library      │
     │                │                       │                │
     │ Creates NetworkX│                       │ Curriculum     │
     │ graphs with:   │                       │ Learning:      │
     │ - Services     │                       │ L1: Simple     │
     │ - Databases    │                       │ L2: Database   │
     │ - Caches       │                       │ L3: Complex    │
     │ - Queues       │                       │ L4: External   │
     │ - External APIs│                       │                │
     └────────┬───────┘                       └────────┬───────┘
              │                                        │
              │         ┌──────────────────────────────┘
              │         │
       ┌──────▼─────────▼─────┐
       │   Topology Adapter    │
       │                       │
       │ NetworkX → SimPy      │
       │ Components            │
       └──────┬────────────────┘
              │
     ┌────────▼───────────┐
     │   Simulation       │
     │                    │
     │ • Workload Gen     │
     │ • Failure Injector │
     │ • Telemetry Export │
     │ • Ground Truth     │
     └────────┬───────────┘
              │
     ┌────────▼───────────┐
     │   Episode output   │
     │                    │
     │ ep_0/              │
     │ ├── label.json     │
     │ ├── metrics.json   │
     │ ├── logs.jsonl     │
     │ ├── traces.json    │
     │ └── ground_truth.json
     └────────────────────┘
```

## 📊 Curriculum-style scenarios (4 levels)

### Level 1: Simple service failures (5 nodes, 300s)
- **Focus**: Isolated component stress
- **Faults**: CPU saturation, memory leaks, latency spikes
- **Typical targets**: Service nodes

### Level 2: Database bottlenecks (10 nodes, 600s)
- **Focus**: Downstream and DB-visible symptoms
- **Faults**: Slow queries, connection exhaustion, background jobs
- **Typical targets**: Database nodes

### Level 3: Complex interactions (20 nodes, 900s)
- **Focus**: Multi-hop cascades (e.g. cache → DB)
- **Faults**: Cache failures, queue backlogs
- **Typical targets**: Cache and queue nodes

### Level 4: External dependencies (25 nodes, 600s)
- **Focus**: Limited observability into dependencies
- **Faults**: External API latency, error rate increases
- **Typical targets**: External service nodes

## 🚀 Quick Start

### Installation

```bash
cd ~/dataraft
pip install -r requirements.txt
```

### Public Release Workflows

```bash
# 1) Generate one simulation episode
python generate_dataset.py -n 1 -v

# 2) Run whitebox RCA over a dataset
python analysis2/run_rca_batch.py data/final_validation

# 3) Launch the dashboard UI
cd viz && python app.py
```

For keep/archive scope used in this public release, see `PUBLIC_RELEASE_SCOPE.md`.

### Generate datasets

```bash
# Generate 10 episodes (default)
python generate_dataset.py

# Generate 100 episodes with verbose output
python generate_dataset.py -n 100 -v

# Specify output directory
python generate_dataset.py -n 50 -o data/train_large

# Reproducible generation
python generate_dataset.py -n 20 --seed 42
```

### Output Structure

```
data/train/
├── dataset_metadata.json       # Overall dataset info
├── ep_0/
│   ├── label.json             # Ground truth: {root_cause: "svc_3", ...}
│   ├── topology.json          # Full graph structure (for analysis / visualization)
│   ├── metrics.json           # Time-series metrics
│   ├── logs.jsonl             # Structured logs
│   ├── traces.json            # Distributed traces
│   └── ground_truth.json      # Causality graph
├── ep_1/
...
```

### Ground Truth Label Format

```json
{
  "episode": 0,
  "level": 2,
  "scenario": "Database query slowdown",
  "root_cause_node": "db_0",
  "root_cause_role": "database",
  "fault_type": "slow_queries",
  "fault_start_time": 180,
  "fault_duration": 420,
  "topology": {
    "nodes": 10,
    "edges": 15,
    "frontends": ["svc_0", "svc_2"]
  }
}
```

### Topology Graph Format

Each episode includes a `topology.json` file with the complete graph structure for analysis and visualization:

```json
{
  "nodes": [
    {
      "id": "gateway",
      "type": "RequestGateway",
      "role": "gateway"
    },
    {
      "id": "svc_0",
      "type": "ApiService",
      "role": "service",
      "is_frontend": true
    },
    {
      "id": "db_0",
      "type": "SqlDatabase",
      "role": "database"
    }
  ],
  "edges": [
    {
      "source": "gateway",
      "target": "svc_0",
      "type": "sync_http",
      "base_latency": 5.0
    },
    {
      "source": "svc_0",
      "target": "db_0",
      "type": "sync_db",
      "base_latency": 2.0
    }
  ],
  "num_nodes": 10,
  "num_edges": 15,
  "is_directed": true
}
```

**Node attributes:**
- `id`: Unique node identifier
- `type`: Component type (ApiService, SqlDatabase, InMemoryCache, MessageQueue, ExternalService, RequestGateway)
- `role`: Semantic role (gateway, service, database, cache, queue, external)
- `is_frontend`: Boolean flag (only on frontend services)

**Edge attributes:**
- `source`, `target`: Node IDs
- `type`: Connection type (sync_http, sync_rpc, sync_db, sync_cache, sync_external, async_produce, async_consume)
- `base_latency`: Network latency in milliseconds

## 🧬 Procedural Topology Generation

Each episode generates a **unique microservice architecture** with:

- **Gateway**: Single entry point (load balancer)
- **Services**: Business logic (20% are frontends)
- **Databases**: Persistent storage (20% of non-gateway nodes)
- **Caches**: Performance layer (15%)
- **Message Queues**: Async processing (10%)
- **External APIs**: 3rd party dependencies (5%)

### Realistic Wiring Patterns

1. **Gateway → Frontends** (20% of services)
2. **Service → Database** (1:1 ownership)
3. **Service → Cache** (sidecar pattern)
4. **Producer → Queue → Consumer** (async messaging)
5. **Service → External API** (3rd party calls)
6. **Service → Service** (RPC calls, 50% additional edges)
7. **Connectivity Repair** (ensures no isolated islands)

## 🔬 Key Features

### 1. Automatic Ground Truth Labeling
- Root cause node ID
- Fault type and severity
- Precise fault injection time
- Affected component roles

### 2. High-Fidelity Simulation
- **Dynamics Engine**: CPU/latency/errors based on throughput and queue depth
- **Circuit Breakers**: Realistic client-side failure handling
- **Retries**: Amplification effects on downstream services
- **Propagation Delays**: Network latency enforces temporal causality

### 3. Realistic Observability Data
- **Metrics**: Time-averaged gauges (like CloudWatch/Prometheus)
- **Logs**: Structured JSON with correlation IDs
- **Traces**: OpenTelemetry distributed traces with sampling
- **Resolution Mismatch**: 5-10s metric intervals vs. ms-level ground truth

### 4. Data Quality Challenges
- Dropped metrics (simulated network issues)
- Clock skew (different component clocks)
- Missing logs (sampling)
- Hard negatives (similar fault signatures)

### 5. Baseline Health Validation
- **Automatic Validation**: Every episode is validated to ensure healthy baseline before fault injection
- **Degradation Guarantee**: Faults must cause actual degradation, not improvement
- **Automatic Retry**: Invalid episodes are automatically regenerated (up to 3 attempts)
- **Validation Tool**: Standalone script to validate existing datasets

## 🔍 Topology Filtering by Root Cause

Dataraft includes tools to filter topology graphs to show only nodes that can be affected by a root cause, helping you focus analysis on relevant components.

### Quick Start

```bash
# Generate filtered topologies for all episodes
./generate_filtered_topologies.sh

# Or filter a specific episode
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0
```

### Use in Visualization UI

1. Generate filtered topologies (one-time setup)
2. Start the dashboard: `python viz/app.py`
3. Toggle **"Filter by Root Cause"** in the topology card

The filtered view shows only nodes reachable from the root cause through graph traversal, reducing noise and highlighting the impact scope.

**Example**: If an external API (`ext_0`) fails, the filtered topology shows only:
- The failing API
- Services that call it
- Upstream services and gateways

See [TOPOLOGY_FILTERING.md](TOPOLOGY_FILTERING.md) for detailed documentation.

## 📈 Working with episode data

### 1. Load labels and metrics

```python
import json
import pandas as pd

# Load episode
with open('data/train/ep_0/label.json') as f:
    label = json.load(f)

with open('data/train/ep_0/metrics.json') as f:
    metrics = json.load(f)

# Convert to DataFrame
df = pd.DataFrame(metrics['data_points'])
```

### 2. Build a graph (NetworkX)

```python
import networkx as nx
import json

# Load topology directly from topology.json
with open('data/train/ep_0/topology.json') as f:
    topo = json.load(f)

# Reconstruct NetworkX graph
G = nx.DiGraph()
for node in topo['nodes']:
    node_id = node.pop('id')
    G.add_node(node_id, **node)
for edge in topo['edges']:
    G.add_edge(edge['source'], edge['target'],
               type=edge['type'], base_latency=edge['base_latency'])
```

Use the same episode files with **whitebox RCA** (`analysis2/run_rca_batch.py`) and the **dashboard** (`viz/app.py`) to inspect runs and RCA results without any separate ML pipeline.

## 🧪 Testing

### Single Episode Test

```bash
python generate_dataset.py -n 1 -v
```

Check output:
```bash
ls -la data/train/ep_0/
cat data/train/ep_0/label.json
```

### Batch Generation

```bash
python generate_dataset.py -n 100
```

## ✅ Baseline Health Validation

All generated episodes are automatically validated to ensure:
1. **Healthy baseline**: System has ≥50% success rate before fault injection
2. **Proper degradation**: Fault causes actual degradation (not improvement)

### Automatic Validation During Generation

Validation runs automatically after each episode:
- Invalid episodes are marked with `.validation_failed`
- System automatically retries up to 3 times with new random seed
- Episodes that fail all retries are skipped and logged

### Validate Existing Datasets

Check if an existing dataset has unhealthy baselines:

```bash
# Validate all episodes in a dataset
python validate_baseline_health.py data/data_20251127_114143

# Verbose output with detailed metrics
python validate_baseline_health.py data/data_20251127_114143 -v

# Custom thresholds
python validate_baseline_health.py data/data_20251127_114143 \
    --min-success-rate 60.0 \
    --min-degradation-ratio 1.0
```

### Understanding Validation Failures

If validation fails, check the marker file:
```bash
cat data/data_20251127_114143/ep_0/.validation_failed
```

Common reasons for failure:
- **Unhealthy baseline**: Baseline success rate < 50%
- **System improved after fault**: Post-fault success > baseline (the fault actually helped!)
- **Topology issues**: Circular dependencies or cascading failures from the start

See [BASELINE_HEALTH_FIX.md](BASELINE_HEALTH_FIX.md) for detailed information about the validation system.

## 📁 Project Structure

```
~/dataraft/
├── README.md                          # This file
├── requirements.txt                   # Python dependencies
├── generate_dataset.py                # Main orchestrator
├── src/
│   ├── components/                    # Simulation components
│   │   ├── base_component.py
│   │   ├── service.py
│   │   ├── networking.py
│   │   ├── database.py
│   │   ├── storage.py
│   │   ├── messaging.py
│   │   ├── compute.py
│   │   ├── network.py
│   │   └── external.py                # NEW: 3rd party APIs
│   ├── topology/                      # NEW: Procedural generation
│   │   ├── generator.py               # NetworkX topology generator
│   │   └── adapter.py                 # Graph → SimPy adapter
│   ├── scenarios/                     # NEW: Curriculum learning
│   │   └── library.py                 # Level definitions
│   ├── failures/                      # Failure injection
│   │   ├── modes.py
│   │   └── injector.py
│   ├── telemetry/                     # Observability
│   │   ├── setup.py
│   │   ├── exporters.py
│   │   └── ...
│   ├── dynamics/                      # Realistic behavior
│   │   ├── metrics_dynamics_engine.py
│   │   └── correlated_noise.py
│   ├── workloads/                     # Traffic generation
│   │   ├── generator.py
│   │   ├── patterns.py
│   │   └── circuit_breaker.py
│   └── core/                          # Utilities
│       ├── simulation_config.py
│       ├── ground_truth.py
│       ├── logging_setup.py
│       └── ...
└── data/                              # Generated datasets
    └── train/
```

## 🔥 Gradual Failure Injection

Unlike instant failure injection (unrealistic), Dataraft applies failures **gradually over time** to mimic real infrastructure degradation:

### **Progression Types**
- **Linear**: Steady degradation (e.g., latency increases uniformly)
- **Exponential**: Accelerating problems (e.g., memory leaks compound)
- **Step**: Sudden changes in phases (e.g., background jobs start)

### **Example Timeline**
```
Episode Duration: 600s
├─ 0-120s:    Healthy baseline (20%)
├─ 120-360s:  Gradual failure ramp (40%)
└─ 360-600s:  Full failure state (40%)
```

This creates **temporally rich episodes** that are useful for:
- RCA and incident forensics (including whitebox RCA in `analysis2/`)
- Visual exploration in the dashboard
- Optional export to your own analytics or ML tooling

## 🤝 Relationship to Main Simulator

**Dataraft** is a **focused fork** of the main simulator (`~/sim`) oriented toward **dataset generation, RCA, and visualization**. Key differences:

| Feature | Main Sim (`~/sim`) | Dataraft (`~/dataraft`) |
|---------|-------------------|-------------------|
| **Purpose** | Testing & validation | Simulation + labeled episodes + RCA tooling |
| **Topology** | Static (Terraform IaC) | Procedural (NetworkX) |
| **Failures** | YAML scenarios | Programmatic gradual injection |
| **Output** | Single run analysis | Batch datasets and RCA artifacts |
| **Usage** | Manual exploration | Pipelines, dashboard, `analysis2` RCA |

## 🎓 References

Useful background (general systems / observability—not required to run Dataraft):

- Distributed tracing and microservice observability (OpenTelemetry)
- Time-series analysis and changepoint ideas for incident comparison
- Curriculum-style scenario design for structured fault coverage

## 📝 License

MIT License (same as main simulator)

## 🐛 Issues

Report issues in the [project repository](https://github.com/4sgupta828/samba/issues) (GitHub path may differ from the **Dataraft** product name).

---

**Built with ❤️ for advancing AI in SRE workflows**
