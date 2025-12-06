# Bug Fix Summary - December 6, 2025

## Issue Reported
```
Error in episode 0: cannot import name 'get_global_registry' from 'src.simulation'
```

Also discovered: `analyze_node() got an unexpected keyword argument 'distance'`

---

## Fixes Applied

### Fix #1: Import Error in `revert_noisy_neighbor`
**File**: `src/failures/modes.py:597`

**Problem**: Tried to import non-existent `get_global_registry` function to look up victim pods.

**Solution**: Use the compute node to find victim pods instead of global registry.

**Before**:
```python
from src.simulation import get_global_registry
registry = get_global_registry()
victim_pod = registry.get(victim_pod_id)
```

**After**:
```python
# Get compute node from aggressor pod
compute_node = target_pod.compute_node
# Look up victim pods via compute node
for victim_pod in compute_node.pods:
    if victim_pod.id in victims_info:
        # Revert steal time
        victim_pod.dynamics.fault_latency_additive_ms = info['original_latency']
```

### Fix #2: Keyword Argument Error in Fault Propagation
**File**: `analysis/propagation_analyzer.py:351`

**Problem**: Called `analyze_node(node_id, distance=-1)` with keyword argument, but method expects positional argument.

**Before**:
```python
report = self.analyze_node(node_id, distance=-1)
```

**After**:
```python
report = self.analyze_node(node_id, -1)
```

---

## Verification

### Test Dataset: `data/test_final_fix/data_20251206_115033/ep_0`

#### ✓ Noisy Neighbor Injection Working
```json
{
  "message": "Noisy neighbor: CPU pinned to 100.0% (aggressor pod)",
  "component.id": "pod_svc_3_0"
}
```

#### ✓ Co-located Pods Experiencing Steal Time
```json
{
  "message": "noisy_neighbor: Experiencing CPU steal time (+150.0ms latency penalty)",
  "component.id": "pod_svc_0_2"
},
{
  "message": "noisy_neighbor: Experiencing CPU steal time (+150.0ms latency penalty)",
  "component.id": "pod_svc_4_1"
}
```
**Result**: 1 aggressor + 3 victims = 4 pods affected (co-location working!)

#### ✓ Fault Propagation Analyzes All Nodes
- **Total nodes in topology**: 35
- **Nodes analyzed**: 35 (100% coverage)
- **Queue nodes found**: `["queue_0"]`

**Result**: All nodes including unreachable queues are now analyzed!

#### ✓ No Errors
- No import errors
- No keyword argument errors
- Simulation completed successfully

---

## Summary of All Fixes (December 6, 2025)

| Fix | Status | File | Impact |
|-----|--------|------|--------|
| 1. Uniform Target Selection | ✓ | generate_dataset.py:664 | No bias |
| 2. All Nodes Analyzed | ✓ | propagation_analyzer.py:323 | 100% coverage |
| 3. Noisy Neighbor Co-location | ✓ | modes.py:479 | Realistic impact |
| 4. Fault Revert Registry | ✓ | modes.py:874 + training_injector.py:313 | Clean revert |
| 5. Import Error Fix | ✓ | modes.py:597 | No crashes |
| 6. Keyword Arg Fix | ✓ | propagation_analyzer.py:351 | No errors |

---

## All Issues Resolved

✓ Fault revert works (no warnings)
✓ Target selection uniform (no bias toward consumers)
✓ All nodes analyzed (including queues)
✓ Co-located pods experience steal time
✓ No import errors
✓ No keyword argument errors
✓ Simulation completes successfully

**Status**: All 4 original issues + 2 bugs FIXED and verified!
