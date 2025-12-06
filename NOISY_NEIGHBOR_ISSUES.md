# Noisy Neighbor and Fault System Issues

## Summary of Issues Found

After analyzing dataset `data/data_20251206_104254`, I identified **4 critical issues**:

### 1. **Fault Removal Not Working** ❌
**Status**: BROKEN

**Evidence**:
```
[690.00s] <<< REVERTING GRADUAL FAILURE: 'noisy_neighbor' on notification_service over 90.0s
WARNING: Revert logic not implemented for 'noisy_neighbor'
```

**Problem**: The revert function for noisy_neighbor exists (`revert_noisy_neighbor` in src/failures/modes.py:516), but the training injector doesn't know about it!

**Root Cause**: In `src/failures/training_injector.py`, there's no mapping from fault types to their revert functions. The gradual failure system tries to revert but has no function registered.

**Fix Required**: Create a `REVERT_MODES` mapping in `src/failures/modes.py` and use it in the training injector.

---

### 2. **Target Selection Always Picks Consumers** ⚠️
**Status**: DESIGN FLAW

**Evidence** from `generate_dataset.py:663-676`:
```python
def score_target_connectivity(target_node):
    """Score a target based on propagation potential."""
    # Count direct upstream callers (who will be impacted)
    predecessors = list(nx_graph.predecessors(target_node))  # <-- WRONG!
    num_callers = len(predecessors)

    # Count second-order callers (propagation depth)
    second_order = set()
    for pred in predecessors:
        second_order.update(nx_graph.predecessors(pred))

    # Higher score = better propagation potential
    return num_callers * 10 + len(second_order)
```

**Problem**: The scoring function counts **predecessors** (incoming edges), which means:
- Queue consumers score high (they have queue as predecessor)
- Services with many upstream dependencies score high
- Services with DOWNSTREAM impact score LOW

**Why This is Wrong**:
- We want to measure **fault propagation** (downstream impact)
- A fault in a service should propagate to its CALLERS/CONSUMERS
- But the code scores based on how many services the node DEPENDS ON

**Analysis from debug script**:
```
Node selection analysis for: notification_service
Direct callers (predecessors): 1  <-- Only events_queue
Second-order callers: 1
Connectivity score: 11

Comparison with other service nodes:
  user_management_service: score=21, predecessors=2
  billing_service: score=11, predecessors=1
  analytics_service: score=11, predecessors=1
  notification_service: score=11, predecessors=1 <-- SELECTED
  reporting_service: score=11, predecessors=1

ISSUE: High predecessor count favors CONSUMERS (nodes with incoming edges)
SUGGESTION: Should score based on SUCCESSORS (downstream impact) not predecessors
```

**Fix Required**: Change to count **successors** (outgoing edges) instead of predecessors.

---

### 3. **Queue Impact Not Detected in Fault Propagation** ❌
**Status**: BROKEN

**Evidence**:
```
FAULT PROPAGATION ANALYSIS
   Nodes analyzed: 1  <-- Only notification_service itself!
   Critically impacted: 1
   Highly impacted: 0
   Moderately impacted: 0
   Queue nodes in report: 0  <-- events_queue NOT analyzed

   Upstream nodes (should be impacted): 1
     - events_queue: NOT IN REPORT!  <-- Missing!
```

**Problem**: The fault propagation analyzer is NOT analyzing upstream nodes (queues, databases, etc.) that should show impact when their consumers slow down.

**Expected Behavior**:
- When `notification_service` slows down consuming from `events_queue`
- Messages should pile up in the queue
- Queue metrics should show increased `messages_in_flight`
- Fault propagation should detect this as "queue congestion"

**Root Cause**: The fault propagation analyzer likely only traverses downstream dependencies, not upstream sources.

**Fix Required**: Enhance fault propagation to analyze upstream dependencies (queues, databases) and detect backpressure signals.

---

### 4. **Noisy Neighbor Impact Unclear** ⚠️
**Status**: WORKING BUT NEEDS VERIFICATION

**Evidence**:
- Only 1 pod (`pod_notification_service_0`) should have high CPU (aggressor)
- But metrics analysis couldn't verify pod-level request distribution
- Latency metrics for the service exist but couldn't verify per-pod isolation

**Current Implementation** (src/failures/modes.py:480-514):
```python
def noisy_neighbor(component: SimulatedComponent, params: Dict[str, Any]):
    # If component is a Service, pick a random pod
    if isinstance(component, Service):
        if not component.pods:
            component._emit_log("WARN", "noisy_neighbor: Service has no pods")
            return
        target_pod = component.pods[0]  # Pick first pod as aggressor

    # Set CPU floor to pin the CPU
    target_pod.dynamics.fault_cpu_floor_percent = cpu_target
```

**Questions**:
1. Does pinning ONE pod's CPU actually impact OTHER pods on the same node?
2. Are requests still distributed evenly across all pods?
3. Should the aggressor pod refuse new requests due to high CPU?

**Needs**: Testing with multiple pods and verification that:
- Only 1 pod shows high CPU
- That pod's latency increases
- Other pods on same node experience some impact (steal time)
- Request distribution changes (or doesn't, depending on design)

---

## Impact Analysis

### Issue #1: Fault Removal Not Working
**Severity**: **CRITICAL**
- All fault revert operations fail silently
- Faults persist through "recovery" period
- Training data labels incorrectly mark recovery time
- GNN will learn wrong recovery patterns

### Issue #2: Target Selection Bias
**Severity**: **HIGH**
- Systematically biased toward consumer nodes
- Queue consumers over-represented in training data
- Root services (gateways, etc.) under-represented
- GNN may not generalize to faults in different topology positions

### Issue #3: Missing Queue Impact
**Severity**: **HIGH**
- Fault propagation analysis incomplete
- Queue backpressure not detected
- Async interaction patterns not captured
- GNN misses important signal for queue-based architectures

### Issue #4: Noisy Neighbor Verification
**Severity**: **MEDIUM**
- Implementation exists and runs
- Impact may not be realistic
- Needs verification of pod-level isolation

---

## Recommended Fixes

### Fix #1: Implement Fault Revert Registry

**File**: `src/failures/modes.py`

Add after the FAILURE_MODES dictionary:
```python
# Registry of revert functions for each failure mode
REVERT_MODES = {
    'set_component_state': lambda component, params: None,  # State changes handled separately
    'inject_latency': revert_latency,
    'start_memory_leak': stop_memory_leak,
    'enable_background_job': stop_db_background_job,
    'inject_db_wear': reset_db_wear,
    'inject_errors': revert_errors,
    'connection_exhaustion': revert_connection_exhaustion,
    'queue_consumer_slowdown': revert_consumer_slowdown,
    'noisy_neighbor': revert_noisy_neighbor,
    'hot_shard': revert_hot_shard,
    'network_partition': revert_network_partition,
    'force_deadlock': revert_deadlock,
    # ... add others
}
```

**File**: `src/failures/training_injector.py`

Update the revert logic (around line 200):
```python
def _revert_gradual_failure(self, ...):
    # ...

    # Look up revert function
    from src.failures.modes import REVERT_MODES
    revert_func = REVERT_MODES.get(failure_mode)

    if revert_func is None:
        print(f"WARNING: No revert function for '{failure_mode}'")
        return

    # Apply revert with progress
    for step in range(num_steps):
        progress = (step + 1) / num_steps
        # Apply partial revert...
        revert_func(target, params_copy)
        yield self.env.timeout(step_duration)
```

### Fix #2: Correct Target Selection Scoring

**File**: `generate_dataset.py:663-676`

Change from:
```python
def score_target_connectivity(target_node):
    """Score a target based on propagation potential."""
    predecessors = list(nx_graph.predecessors(target_node))  # WRONG
    num_callers = len(predecessors)
    # ...
```

To:
```python
def score_target_connectivity(target_node):
    """Score a target based on DOWNSTREAM propagation potential."""
    # Count direct DOWNSTREAM nodes that will be impacted
    successors = list(nx_graph.successors(target_node))
    num_downstream = len(successors)

    # Count second-order downstream impact
    second_order_downstream = set()
    for succ in successors:
        second_order_downstream.update(nx_graph.successors(succ))

    # Higher score = more downstream impact
    return num_downstream * 10 + len(second_order_downstream)
```

This will prefer:
- Root services (gateway, API endpoints) - high downstream impact
- Services in the middle of the call chain - medium impact
- Leaf services (databases, queues) - low direct impact but high indirect

### Fix #3: Add Upstream Propagation Analysis

**File**: `src/analysis/fault_propagation.py` (or wherever fault propagation is implemented)

Add logic to analyze upstream dependencies:
```python
def analyze_fault_propagation(topology, metrics, root_cause_id, fault_start_time):
    """Analyze both downstream AND upstream propagation."""

    # Existing: Analyze downstream nodes
    downstream_nodes = get_downstream_nodes(topology, root_cause_id)

    # NEW: Analyze upstream sources (queues, databases)
    upstream_nodes = get_upstream_sources(topology, root_cause_id)

    for upstream_id in upstream_nodes:
        # Check for backpressure signals
        if upstream_id in queues:
            # Check messages_in_flight increase
            queue_impact = analyze_queue_backpressure(metrics, upstream_id, fault_start_time)
        elif upstream_id in databases:
            # Check connection pool saturation, query queueing
            db_impact = analyze_db_contention(metrics, upstream_id, fault_start_time)
        # ...
```

### Fix #4: Verify Noisy Neighbor Implementation

Create a test to verify:
1. CPU pinning works (one pod shows 100% CPU)
2. Request distribution (do requests still go to aggressor pod?)
3. Cross-pod impact (do other pods on same node show steal time?)
4. Latency impact (does aggressor pod's latency increase?)

---

## Testing Plan

1. **Fix #1 (Fault Revert)**:
   - Generate new dataset with fixes
   - Verify logs show successful revert
   - Check metrics return to baseline after recovery_complete_time

2. **Fix #2 (Target Selection)**:
   - Generate 100 episodes
   - Count how many times each node type is selected
   - Verify distribution is more balanced (gateways > mid-tier > consumers)

3. **Fix #3 (Queue Impact)**:
   - Generate episode with queue consumer slowdown
   - Verify fault_propagation.json includes queue node
   - Check queue shows increased messages_in_flight

4. **Fix #4 (Noisy Neighbor)**:
   - Generate episode with noisy_neighbor on multi-pod service
   - Extract per-pod CPU metrics
   - Verify only 1 pod shows high CPU
   - Check other pods' latency for steal time effect

---

## Example Commands

```bash
# Run debug analysis
python debug_noisy_neighbor.py data/data_20251206_104254/ep_0

# Generate test episode after fixes
python generate_dataset.py --episodes 1 --output-dir data/test_fixes --force-fault-type noisy_neighbor --force-fault-role service

# Verify fault removal
grep -i "revert" data/test_fixes/ep_0/simulation.log

# Check target selection distribution
for ep in data/test_fixes/ep_*/label.json; do
    jq -r '.root_cause_node' $ep
done | sort | uniq -c
```

---

## Priority

1. **FIX IMMEDIATELY**: Issue #1 (Fault Removal) - breaks all training data
2. **FIX SOON**: Issue #2 (Target Selection) - systematic bias in dataset
3. **FIX SOON**: Issue #3 (Queue Impact) - missing important features
4. **VERIFY LATER**: Issue #4 (Noisy Neighbor) - may already work correctly
