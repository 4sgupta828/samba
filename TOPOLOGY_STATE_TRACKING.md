# Topology State Tracking - Dynamic Service/Pod/Node Mappings

## Problem

The Service/Pod/Node architecture has **dynamic mappings** that change over time:
- Services have pods that can be created, terminated, or rescheduled
- Pods run on compute nodes
- Nodes host multiple pods

These mappings are **not captured in the static topology** but are **critical for root cause analysis**:
- Which pods belong to which service?
- Which nodes are running which pods?
- How did these mappings change over time?

## Solution: Event-Driven Topology State Export

**Simple, efficient approach: Export full topology state ONLY when things change.**

### When Snapshots Are Exported:

1. **Initial state** - At simulation start (after all components registered)
2. **Pod created** - DeploymentController creates a new pod
3. **Pod terminated** - Pod dies (OOMKilled, scale down, etc.)
4. **Pod rescheduled** - Pod moved to different node (future feature)
5. **Final state** - At simulation end

### Output Format: JSONL

Single file: `topology_state.jsonl`

Each line is a complete topology snapshot containing:
```json
{
  "timestamp": 15.0,
  "snapshot_id": 1,
  "snapshot_type": "change",
  "event": "pod_created:pod_service_a_15@service_a→node_0",
  "services": [...],
  "pods": [...],
  "nodes": [...],
  "mappings": {
    "service_to_pods": {"svc_a": ["pod_a_0", "pod_a_1"]},
    "pod_to_node": {"pod_a_0": "node_0", "pod_a_1": "node_1"},
    "node_to_pods": {"node_0": ["pod_a_0"], "node_1": ["pod_a_1"]},
    "pod_to_service": {"pod_a_0": "svc_a", "pod_a_1": "svc_a"}
  },
  "cluster_stats": {...}
}
```

## Usage

### 1. Create Exporter

```python
from src.telemetry.topology_state_exporter import TopologyStateExporter

exporter = TopologyStateExporter(env, output_dir="data/episode_1")
```

### 2. Register Components

```python
# Register services
exporter.register_service(service_a)
exporter.register_service(service_b)

# Register nodes
exporter.register_node(node_0)
exporter.register_node(node_1)

# Register pods
for pod in all_pods:
    exporter.register_pod(pod)

# Register controller (with exporter for automatic tracking)
controller = DeploymentController(env, "controller", topology_exporter=exporter)
exporter.register_controller(controller)
```

### 3. Export Initial State

```python
# After all components registered, before simulation starts
exporter.export_initial_state()
```

### 4. Automatic Tracking

The `DeploymentController` automatically exports snapshots when:
- Creating pods
- Terminating pods
- Rescheduling pods

No manual intervention needed!

### 5. Export Final State

```python
# At end of simulation
exporter.export_final_snapshot()
```

## Data Structure Details

### Services State
```python
{
  "id": "svc_a",
  "service_name": "service_a",
  "desired_replicas": 3,
  "actual_replicas": 2,  # Running pods
  "total_pods": 3,       # Including starting/crashed
  "supported_request_types": ["GET", "POST"],
  "pipeline_steps": 4,
  "connections": {"database": "db_0", "cache": "cache_0"}
}
```

### Pods State
```python
{
  "id": "pod_a_0",
  "operational_state": "RUNNING",
  "restarts": 1,
  "parent_service": "service_a",
  "parent_service_id": "svc_a",
  "compute_node": "node_0",
  "start_time": 0.0,
  "age": 15.5,
  # Runtime metrics (if RUNNING)
  "cpu_percent": 25.3,
  "memory_mb": 256.8,
  "thread_pool_active": 2,
  "connection_pool_active": 1
}
```

### Nodes State
```python
{
  "id": "node_0",
  "operational_state": "RUNNING",
  "cpu_cores": 8,
  "memory_gb": 32,
  "network_bandwidth_gbps": 10,
  "total_pods": 4,
  "running_pods": 3,
  "total_cpu_percent": 120.5,  # Sum across all pods
  "total_memory_mb": 1024.3,
  "cpu_utilization": 0.15,     # 15% of node capacity
  "memory_utilization": 0.03,   # 3% of node capacity
  "can_accept_work": true,
  "pods": ["pod_a_0", "pod_a_1", "pod_b_0", "pod_b_1"]
}
```

### Mappings (Key for GNN)
```python
{
  "service_to_pods": {
    "svc_a": ["pod_a_0", "pod_a_1", "pod_a_2"],
    "svc_b": ["pod_b_0", "pod_b_1"]
  },
  "pod_to_node": {
    "pod_a_0": "node_0",
    "pod_a_1": "node_1",
    "pod_a_2": "node_1",
    "pod_b_0": "node_0",
    "pod_b_1": "node_1"
  },
  "node_to_pods": {
    "node_0": ["pod_a_0", "pod_b_0"],
    "node_1": ["pod_a_1", "pod_a_2", "pod_b_1"]
  },
  "pod_to_service": {
    "pod_a_0": "svc_a",
    "pod_a_1": "svc_a",
    "pod_a_2": "svc_a",
    "pod_b_0": "svc_b",
    "pod_b_1": "svc_b"
  }
}
```

### Cluster Stats
```python
{
  "total_services": 2,
  "total_pods": 5,
  "total_nodes": 2,
  "running_pods": 4,
  "starting_pods": 1,
  "crashed_pods": 0,
  "terminated_pods": 0,
  "cluster_cpu_utilization": {
    "mean": 0.15,
    "max": 0.18,
    "min": 0.12
  },
  "cluster_memory_utilization": {
    "mean": 0.03,
    "max": 0.04,
    "min": 0.02
  },
  "pending_pod_creations": 0
}
```

## Benefits for GNN Training

### 1. Temporal Context
The GNN can learn how topology evolves:
- Pod failures → New pod creation → Service recovery
- Node overload → Pod eviction → Rescheduling

### 2. Complete Mapping Graph
Explicit Service → Pod → Node edges allow GNN to:
- Trace root causes through multiple layers
- Understand noisy neighbor effects (pods on same node)
- Correlate service degradation with node issues

### 3. State Correlation
Each snapshot includes:
- Operational states (RUNNING, STARTING, CRASHED)
- Resource metrics (CPU, memory, connections)
- Cluster health stats

This allows correlation with:
- Metrics (from metrics.jsonl)
- Logs (from logs.jsonl)
- Traces (from traces.jsonl)

### 4. Event Attribution
Each snapshot has an `event` field showing what triggered it:
```
"event": "pod_created:pod_service_a_15@service_a→node_0"
"event": "pod_terminated:pod_a_0:SCALE_DOWN"
"event": "pod_rescheduled:pod_x:node_0→node_1"
```

## Example Output

```
Snapshot timeline:
  [   0.0s] initial    - simulation_start
  [  15.0s] change     - pod_created:pod_service_a_15@service_a→node_0
  [  30.1s] change     - pod_terminated:pod_a_0:SCALE_DOWN
  [  45.2s] change     - pod_created:pod_service_b_45@service_b→node_1
  [  60.0s] final      - simulation_end
```

At each snapshot, you have:
- Complete Service/Pod/Node topology
- All mappings (who's connected to whom)
- Resource utilization
- Operational states

## Integration with Training Data Generation

When generating training data:
```python
# Create exporter for this episode
exporter = TopologyStateExporter(env, f"data/episode_{episode_id}")

# ... setup simulation ...

# Export initial state
exporter.export_initial_state()

# Run simulation (automatic tracking via DeploymentController)
env.run(until=simulation_duration)

# Export final state
exporter.export_final_snapshot()

# Result: data/episode_{episode_id}/topology_state.jsonl
```

The GNN will have:
- `topology.json` - Static topology (nodes, edges, types)
- `topology_state.jsonl` - Dynamic mappings over time
- `metrics.jsonl` - Time-series metrics
- `logs.jsonl` - Log events
- `traces.jsonl` - Distributed traces
- `label.json` - Root cause label

## Summary

**Simple, efficient, complete:**
- ✅ Event-driven (only on changes)
- ✅ Captures all Service/Pod/Node mappings
- ✅ Temporal evolution for learning
- ✅ Automatic tracking via DeploymentController
- ✅ Ready for GNN training

No periodic snapshots needed. No complex scheduling. Just track when things change.
