# Samba: Spatiotemporal Data Factory for GNN Training

**Samba** is a high-fidelity infrastructure simulator designed to generate infinite, diverse, and perfectly labeled training episodes for Graph Neural Networks (GNNs) that perform root cause analysis in microservice environments.

## 🎯 Purpose

Traditional simulators test predefined scenarios on static topologies. **Samba transforms this paradigm** into a **training data factory** that:

1. **Solves the Labeling Bottleneck**: Automatically generates ground truth labels (root cause node, fault type, time) for every incident
2. **Enables Inductive Learning**: Procedurally generates unique topologies, forcing GNNs to learn structural rules instead of memorizing node IDs
3. **Enforces Temporal Causality**: Propagation delays create the "arrow of time" needed for causal inference
4. **Builds Robustness**: Generates realistic data quality issues (dropped metrics, clock skew, missing logs)

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
     │   Training Data    │
     │                    │
     │ ep_0/              │
     │ ├── label.json     │
     │ ├── metrics.json   │
     │ ├── logs.jsonl     │
     │ ├── traces.json    │
     │ └── ground_truth.json
     └────────────────────┘
```

## 📊 Curriculum Learning (4 Levels)

### Level 1: Simple Service Failures (5 nodes, 300s)
- **Goal**: Learn to identify isolated component failures
- **Faults**: CPU saturation, memory leaks, latency spikes
- **Target**: Single service node

### Level 2: Database Bottlenecks (10 nodes, 600s)
- **Goal**: Learn to distinguish downstream symptom propagation
- **Faults**: Slow queries, connection exhaustion, background jobs
- **Target**: Database nodes

### Level 3: Complex Interactions (20 nodes, 900s)
- **Goal**: Learn multi-hop causal chains (cache miss → DB overload)
- **Faults**: Cache failures, queue backlogs
- **Target**: Cache and queue nodes

### Level 4: External Dependencies (25 nodes, 600s)
- **Goal**: Learn to identify black box failures with no internal metrics
- **Faults**: External API latency, error rate increases
- **Target**: External service nodes

## 🚀 Quick Start

### Installation

```bash
cd ~/samba
pip install -r requirements.txt
```

### Generate Training Data

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
│   ├── topology.json          # Full graph structure for GNN input
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

Each episode includes a `topology.json` file with the complete graph structure for GNN training:

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

## 📈 Training Pipeline Integration

### 1. Load Data

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

### 2. Build Graph

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

### 3. Train GNN

```python
import torch
from torch_geometric.data import Data

# Convert to PyTorch Geometric format
node_features = torch.tensor(...)  # Aggregated metrics per node
edge_index = torch.tensor(...)     # Adjacency list
labels = torch.tensor(...)         # Root cause node (one-hot)

data = Data(x=node_features, edge_index=edge_index, y=labels)

# Train model
model.train()
optimizer.zero_grad()
out = model(data)
loss = criterion(out, labels)
loss.backward()
optimizer.step()
```

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

## 📁 Project Structure

```
~/samba/
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

Unlike instant failure injection (unrealistic), Samba applies failures **gradually over time** to mimic real infrastructure degradation:

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

This creates **temporally rich training data** where GNNs learn to:
- Detect early warning signs
- Track degradation progression
- Distinguish symptom propagation from root causes

## 🤝 Relationship to Main Simulator

**Samba** is a **focused fork** of the main simulator (`~/sim`) designed specifically for GNN training data generation. Key differences:

| Feature | Main Sim (`~/sim`) | Samba (`~/samba`) |
|---------|-------------------|-------------------|
| **Purpose** | Testing & validation | Training data generation |
| **Topology** | Static (Terraform IaC) | Procedural (NetworkX) |
| **Failures** | YAML scenarios | Programmatic gradual injection |
| **Output** | Single run analysis | Batch datasets (1000s) |
| **Usage** | Manual exploration | Automated pipeline |

## 🎓 References

This architecture implements concepts from:
- **Inductive Learning**: Hamilton et al., "Inductive Representation Learning on Large Graphs" (NeurIPS 2017)
- **Temporal GNNs**: Sanchez-Gonzalez et al., "Graph Networks as Learnable Physics Engines" (ICML 2020)
- **Curriculum Learning**: Bengio et al., "Curriculum Learning" (ICML 2009)

## 📝 License

MIT License (same as main simulator)

## 🐛 Issues

Report issues at: https://github.com/anthropics/samba/issues

---

**Built with ❤️ for advancing AI in SRE workflows**
