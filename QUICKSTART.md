# Quick Start Guide

## ✅ What Was Built

**Samba** is now a fully functional **Training Data Factory** for GNN-based root cause analysis. It generates infinite, diverse, and perfectly labeled microservice topologies with injected failures.

## 🚀 Generate Your First Dataset

### Single Episode (Test)
```bash
cd ~/samba
python generate_dataset.py -n 1 -v
```

### Small Dataset (10 episodes)
```bash
python generate_dataset.py -n 10
```

### Large Dataset (100 episodes)
```bash
python generate_dataset.py -n 100 -o data/train_large
```

### Reproducible Generation
```bash
python generate_dataset.py -n 20 --seed 42
```

## 📂 Output Structure

```
data/train/
├── dataset_metadata.json       # Overall dataset info
├── ep_0/
│   ├── label.json             # Ground truth: {root_cause: "svc_3", ...}
│   ├── data_YYYYMMDD_HHMMSS/
│   │   ├── metrics.jsonl      # Time-series metrics (2000-3000 data points)
│   │   ├── logs.jsonl         # Structured logs
│   │   ├── traces.jsonl       # Distributed traces
│   │   ├── ground_truth.json  # Causality graph
│   │   └── infra_context.json # Topology metadata
├── ep_1/
...
```

## 📊 Ground Truth Label Format

```json
{
  "episode": 0,
  "level": 4,                           // Difficulty (1-4)
  "scenario": "External API error rate increase",
  "root_cause_node": "ext_0",          // Which node failed
  "root_cause_role": "external",       // Component type
  "fault_type": "inject_errors",       // Failure mode
  "fault_start_time": 180,             // When (simulation seconds)
  "fault_duration": 420,               // How long
  "topology": {
    "nodes": 25,                       // Total components
    "edges": 26,                       // Connections
    "frontends": ["svc_6", "svc_13"]  // Entry points
  }
}
```

## 🎓 Curriculum Levels

| Level | Description | Nodes | Fault Type |
|-------|-------------|-------|------------|
| 1 | Simple service failure | 5 | CPU, memory, latency |
| 2 | Database bottleneck | 10 | Slow queries, connections |
| 3 | Complex interactions | 20 | Cache/queue failures |
| 4 | External dependency | 25 | Black box API failures |

Distribution: **10% L1, 30% L2, 40% L3, 20% L4**

## 🔬 Next Steps

### 1. Verify Data Quality
```bash
cd ~/samba
python -c "
import json
with open('data/train/ep_0/label.json') as f:
    label = json.load(f)
print(f'Episode 0: Level {label[\"level\"]} - {label[\"scenario\"]}')
print(f'Root cause: {label[\"root_cause_node\"]} ({label[\"root_cause_role\"]})')
"
```

### 2. Load Metrics
```python
import json
import pandas as pd

# Load metrics
with open('data/train/ep_0/data_*/metrics.jsonl') as f:
    metrics = [json.loads(line) for line in f]

df = pd.DataFrame(metrics)
print(df.groupby('name').size())
```

### 3. Build GNN Dataset
```python
import networkx as nx
import torch
from torch_geometric.data import Data

# Load topology from infra_context.json
# Aggregate metrics per node
# Create PyTorch Geometric Data object
# Train your GNN!
```

## 📈 Comparison: Samba vs Main Simulator

| Feature | Main Sim (`~/sim`) | Samba (`~/samba`) |
|---------|-------------------|-------------------|
| **Purpose** | Testing & validation | Training data generation |
| **Topology** | Static (Terraform IaC) | Procedural (NetworkX) |
| **Scenarios** | Predefined YAML | Curriculum learning |
| **Output** | Single run analysis | Batch datasets (1000s) |
| **Usage** | Manual exploration | Automated pipeline |
| **Files** | ~200 files | ~60 files (focused) |

## 🐛 Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`, ensure you're running from the repo root:
```bash
cd ~/samba
python generate_dataset.py -n 1
```

### Missing Dependencies
```bash
cd ~/samba
pip install -r requirements.txt
```

### Check Installation
```bash
python -c "import simpy, networkx, yaml; print('✓ All dependencies installed')"
```

## 📝 Key Achievements

✅ **Clean Architecture**: Only essential files (60 vs. 200+)
✅ **Procedural Generation**: Infinite unique topologies
✅ **Automatic Labeling**: Perfect ground truth for every episode
✅ **Curriculum Learning**: 4-level difficulty progression
✅ **High Fidelity**: Same realistic component models as main sim
✅ **Scalable**: Generate 1000s of episodes overnight

## 🎯 What's Different from ~/sim?

1. **No IaC Parsing**: Topologies are generated, not parsed from Terraform
2. **No UI/Control Plane**: Focused on batch generation, not interactive use
3. **Streamlined Dependencies**: Removed unused modules (RCA agents, UI, etc.)
4. **Programmatic Failures**: Injected via code, not YAML files

---

**Next**: Generate 100 episodes and train your first GNN model! 🚀
