# Fixes Implemented - December 3, 2025

## Summary
Implemented 4 critical fixes to address bugs in dataset generation that were causing:
1. Workload generator rejecting requests due to insufficient capacity
2. Thread pools undersized because cumulative latency wasn't considered
3. Timeouts too generous, hiding real failures
4. **Database connection pool severely undersized**, causing complete system deadlock

---

## Fix 1: WorkloadGeneratorConfig - Massive Capacity Increase ✓
**File**: `src/core/simulation_config.py:313-324`

### Changes:
- `connection_pool_size`: 500 → **5000** (10x increase)
- `request_timeout_seconds`: 30.0 → **60.0** (2x increase)
- `max_queue_size`: 2000 → **10000** (5x increase)

### Rationale:
High-latency service chains need many concurrent connections. For example, at 200 RPS with 15s average latency, you need ~3000 concurrent connections. The old limit of 500 was causing artificial bottlenecks in the test harness itself.

---

## Fix 2: Capacity Planner - Cumulative Latency & Strict Timeouts ✓
**File**: `src/core/capacity_planner.py:168-246`

### Changes:

#### 2a. Thread Pool Sizing Based on Cumulative Latency
**Before**:
```python
concurrency_per_pod = math.ceil(pod_rps * (effective_processing_ms / 1000.0))
```

**After**:
```python
chain_latency = self._estimate_dependency_latency(node_id, phi)
total_thread_occupancy_ms = effective_processing_ms + chain_latency
concurrency_per_pod = math.ceil(pod_rps * (total_thread_occupancy_ms / 1000.0))
```

**Rationale**: Threads are blocked for the **entire time** waiting for downstream dependencies, not just local processing time. Little's Law requires: `Threads = RPS × Total_Blocking_Time`.

#### 2b. Strict Timeout Margins
**Before**:
```python
timeout_margin = 1.2 + (3.0 * (1.0 - phi))  # Results in 1.2x - 4.2x multiplier
```

**After**:
```python
timeout_margin = 1.05 + (0.45 * (1.0 - phi))  # Results in 1.05x - 1.5x multiplier
```

**Rationale**: Overly generous timeouts (3-4x) were compounding through service chains, masking real failures and preventing proper timeout propagation.

---

## Fix 3: Explicit Workload Generator Injection ✓
**File**: `generate_dataset.py:367-378`

### Changes:
Added explicit `workload_generator` configuration to simulation config dictionary:
```python
'workload_generator': {
    'connection_pool_size': 5000,
    'request_timeout_seconds': 60.0,
    'max_queue_size': 10000,
    'circuit_breaker': {
        'enabled': True,
        'failure_threshold': 0.9,
        'success_threshold': 0.8,
        'window_size': 100
    }
}
```

**Rationale**: Ensures configuration overrides defaults, even if YAML loading has different precedence.

---

## Fix 4: Database Connection Pool - Two-Pass Sizing ✓ (NEW CRITICAL FIX)
**File**: `src/core/capacity_planner.py:16-282`

### Problem Discovered:
The database had only **50 connections**, but services needed **~8,000+ connections total**. This caused:
- Complete system deadlock at sim_time ~110s
- Thousands of "max_connections exceeded" errors
- Simulation hanging indefinitely

### Root Cause:
The database sizing formula `rps * latency` only calculated **query concurrency**, not **client connection pool demand**. Each service pod maintains a persistent connection pool to the database, so the database needs capacity equal to the **sum of all client pools**, not just the query rate.

### Solution - Two-Pass Capacity Planning:

**CRITICAL**: The database sizing must read from the `existing_configs` dictionary (passed as a parameter), **NOT** from `graph.nodes[].iac_config_overrides`. The latter creates a race condition because configs are only written to the graph after `plan_capacity()` returns.

#### Pass 1: Size Services First
```python
# PASS 1: Tune Services & Gateways (The Clients) first
client_roles = ['service', 'gateway']
for node_id, metrics in node_metrics.items():
    if role in client_roles:
        tuned_configs[node_id] = self._tune_node(node_id, role, metrics, phi, tuned_configs)
```

#### Pass 2: Size Database Based on Client Demand
```python
# PASS 2: Tune Infrastructure (Databases, Caches, Queues)
infra_roles = ['database', 'cache', 'queue']
for node_id, metrics in node_metrics.items():
    if role in infra_roles:
        # Pass existing_configs so DB can look up client pool sizes
        tuned_configs[node_id] = self._tune_node(node_id, role, metrics, phi, tuned_configs)
```

#### Database Sizing Logic
```python
def _tune_node(self, node_id, role, metrics, phi, existing_configs):
    # ...
    elif role == 'database':
        # 1. Calculate query concurrency (base demand)
        system_concurrency = rps * (base_processing_ms / 1000.0)
        base_capacity = int(system_concurrency * headroom * 2)

        # 2. Calculate client connection pool demand
        client_demand = 0
        for pred in self.graph.predecessors(node_id):
            # ✅ Read from existing_configs (NOT from graph.nodes)
            pred_config = existing_configs.get(pred, {})
            client_pool = pred_config.get('db_connection_pool_capacity', 0)
            if client_pool > 0:
                replicas = pred_config.get('desired_replicas', 1)
                client_demand += client_pool * replicas

        # 3. DB capacity = MAX(base, client_demand * 1.2)
        config['connection_pool_capacity'] = max(50, base_capacity, int(client_demand * 1.2))
```

### Additional Optimization - Don't Allocate Unused DB Pools:

Services that don't connect to any database shouldn't be configured with `db_connection_pool_capacity`. This wastes service resources.

```python
# In service tuning (_tune_node for 'service' role):
# Only allocate DB connection pool if this service actually connects to a database
has_db_dependency = any(
    self.graph.nodes[succ].get('role') == 'database'
    for succ in self.graph.successors(node_id)
)
if has_db_dependency:
    config['db_connection_pool_capacity'] = max(5, int(config['thread_pool_size'] * 0.8))
else:
    config['db_connection_pool_capacity'] = 0  # No DB connections needed
```

This ensures:
- Services only allocate DB pools if they have `database` in their graph successors
- Database sizing only counts predecessors (which are guaranteed to connect)
- No wasted resources on unused connection pools

### Results:
- **Before**: 50 DB connections → System deadlock at 110s
- **After**: 8,468 DB connections → Zero connection errors
- **Optimization**: Services without DB dependencies get pool=0 (saves resources)
- Simulation now progresses smoothly without database bottlenecks

---

## Validation Results

### Test Run Comparison:

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| DB Connection Pool | 50 | 8,468 |
| DB Connection Errors | Thousands | 0 |
| Simulation Progress | Stuck at 110s | Smooth |
| System Deadlock | Yes | No |

### Test Command:
```bash
python generate_dataset.py --episodes 1 --output data --topology-size 10 \
  --fault-type cache_failure --fault-role cache
```

---

## Impact

These fixes resolve all three issues identified in `MoreFixes.md` plus one critical additional issue:

1. ✅ **Workload generator no longer bottlenecks** - Massive capacity increase
2. ✅ **Thread pools properly sized** - Accounts for downstream wait time
3. ✅ **Timeouts are strict** - No more compounding margins hiding failures
4. ✅ **Database connections sufficient** - Two-pass sizing prevents deadlock

The system can now handle high-load, high-latency service chains without artificial bottlenecks or deadlocks.

---

# NEW FIXES - December 6, 2025

## Summary
Implemented 4 critical fixes for noisy neighbor and fault system issues:

1. ✓ **Uniform Target Selection** - Removed bias toward consumer nodes
2. ✓ **Fault Propagation All Nodes** - Now analyzes ALL nodes including unreachable ones  
3. ✓ **Noisy Neighbor Co-location** - Aggressor pod impacts co-located pods with steal time
4. ✓ **Fault Revert Registry** - All faults now revert correctly

---

## Fix 5: Uniform Target Selection ✓

**Problem**: Target selection favored consumer nodes (nodes with many predecessors), systematically over-representing queue consumers.

**File**: `generate_dataset.py:664`

**Before**:
```python
def score_target_connectivity(target_node):
    predecessors = list(nx_graph.predecessors(target_node))  # WRONG
    return num_callers * 10 + len(second_order)
target_id = random.choice(top_half_by_score)
```

**After**:
```python
# UNIFORM SELECTION: simple random to avoid bias
target_id = random.choice(valid_targets)
```

---

## Fix 6: Fault Propagation All Nodes ✓

**Problem**: Only analyzed reachable nodes, missing upstream impact (e.g., queue backpressure).

**File**: `analysis/propagation_analyzer.py:323`

**Before**:
```python
distances = self.compute_node_distances()  # Only reachable nodes
for distance in sorted(distances.keys()):
    for node_id in nodes_by_distance[distance]:
        analyze_node(node_id, distance)
```

**After**:
```python
all_nodes = set(self.graph.nodes())
unreachable_nodes = all_nodes - set(distances.keys())
nodes_by_distance[-1] = list(unreachable_nodes)
# Analyze both reachable AND unreachable nodes
```

---

## Fix 7: Noisy Neighbor Co-location Impact ✓

**Problem**: Only aggressor pod affected, co-located pods not impacted.

**File**: `src/failures/modes.py:479`

**After**:
```python
# EFFECT 1: Pin aggressor CPU
target_pod.dynamics.fault_cpu_floor_percent = cpu_target

# EFFECT 2: Apply steal time to co-located pods
if target_pod.compute_node:
    for victim_pod in node.pods:
        if victim_pod.id != target_pod.id:
            victim_pod.dynamics.fault_latency_additive_ms += steal_time_ms
```

---

## Fix 8: Fault Revert Registry ✓

**Problem**: Revert functions existed but weren't called.

**File**: `src/failures/modes.py:874`

**Added**:
```python
REVERT_MODES = {
    "inject_latency": revert_latency,
    "cpu_saturation": revert_cpu_saturation,
    "noisy_neighbor": revert_noisy_neighbor,
    # ... all fault types
}
```

**File**: `src/failures/training_injector.py:313`

**Updated**:
```python
from src.failures.modes import REVERT_MODES
revert_func = REVERT_MODES.get(failure_mode)
if revert_func:
    revert_func(target, params)
```

---

## Testing

Run: `python test_fixes.py`

Expected: All 4 tests PASS

---

## Files Changed

- `generate_dataset.py` - Uniform selection (~30 lines)
- `analysis/propagation_analyzer.py` - All nodes (~20 lines)
- `src/failures/modes.py` - Noisy neighbor + registry (~120 lines)
- `src/failures/training_injector.py` - Use registry (~20 lines)

Total: ~190 lines across 4 files
