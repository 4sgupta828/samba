# Pod ID Tracking Improvements

## Problem Statement

The initial implementation of `noisy_neighbor` and `force_deadlock` was fragile because it relied on pod position (`service.pods[0]`) instead of tracking specific pod IDs. This created issues when:

1. **Pod Replacement**: DeploymentController replaces pods during crashes/restarts
2. **Pod Reordering**: Pod list order changes during updates/scaling
3. **Revert Failures**: Reverting on wrong pod after replacement

**Example failure scenario:**
```python
# Apply fault to service
noisy_neighbor(service, params)  # Affects service.pods[0] = pod_1

# Pod dies, controller replaces it
service.pods.remove(pod_1)
service.pods.insert(0, pod_4)  # New pod at position 0

# Try to revert - affects WRONG pod!
revert_noisy_neighbor(service, params)  # Reverts pod_4 instead of pod_1
```

## Solution

Implemented robust pod ID tracking:

1. **Store pod ID when applying fault** - Track which specific pod was affected
2. **Lookup pod by ID when reverting** - Find the correct pod by ID, not position
3. **Handle missing pods gracefully** - Log warning if pod no longer exists

## Implementation Details

### Noisy Neighbor

#### Apply (`noisy_neighbor`)
```python
def noisy_neighbor(component, params):
    if isinstance(component, Service):
        target_pod = component.pods[0]
        # Store the affected pod ID on the Service
        component._noisy_neighbor_pod_id = target_pod.id  # ✅ Track pod ID
        component._emit_log("INFO", f"Applying to pod {target_pod.id}")

    # Apply fault to target_pod
    target_pod.dynamics.fault_cpu_floor_percent = cpu_target
```

#### Revert (`revert_noisy_neighbor`)
```python
def revert_noisy_neighbor(component, params):
    # Get the originally affected pod ID
    if not hasattr(component, '_noisy_neighbor_pod_id'):
        component._emit_log("WARN", "No pod ID tracked - cannot revert")
        return

    affected_pod_id = component._noisy_neighbor_pod_id

    # Find pod by ID (not position!)
    if isinstance(component, Service):
        target_pod = None
        for pod in component.pods:
            if pod.id == affected_pod_id:  # ✅ Match by ID
                target_pod = pod
                break

        if target_pod is None:
            # Pod was replaced - log and clean up
            component._emit_log("WARN", f"Pod {affected_pod_id} no longer exists")
            del component._noisy_neighbor_pod_id
            return

    # Revert fault on correct pod
    target_pod.dynamics.fault_cpu_floor_percent = None
    del component._noisy_neighbor_pod_id  # ✅ Clean up tracking
```

### Force Deadlock

Same pattern applied to `force_deadlock` and `revert_force_deadlock`:
- Stores `component._force_deadlock_pod_id`
- Looks up pod by ID during revert
- Handles missing pods gracefully

## Benefits

### ✅ Robust Against Pod Replacement
```
TEST: Noisy Neighbor Pod ID Tracking
  Initial pods: ['pod_1', 'pod_2', 'pod_3']
  Applied fault to: pod_1
  Pod replacement: pod_1 removed, pod_4 added at position 0
  Revert: Detected pod_1 missing, logged warning, cleaned up
  ✅ PASSED: Gracefully handled missing pod
```

### ✅ Correct Pod Targeted
```
TEST: Force Deadlock Pod ID Tracking
  Applied fault to: pod_1 (5 threads locked)
  Revert: Found pod_1 by ID, released 5 threads
  ✅ PASSED: Correctly reverted on tracked pod
```

### ✅ Multiple Faults Independent
```
TEST: Concurrent Faults
  Applied noisy_neighbor to: pod_1 (tracked as _noisy_neighbor_pod_id)
  Applied force_deadlock to: pod_1 (tracked as _force_deadlock_pod_id)
  Reverted noisy_neighbor: Found pod_1, reverted CPU floor
  Reverted force_deadlock: Found pod_1, released threads
  ✅ PASSED: Multiple faults track independently
```

## Testing

### Unit Tests
```bash
# Original tests still pass
python test_structural_faults.py
✅ Noisy Neighbor: PASSED
✅ Force Deadlock: PASSED

# New pod tracking tests
python test_pod_tracking.py
✅ Noisy Neighbor Pod Tracking: PASSED
✅ Force Deadlock Pod Tracking: PASSED
✅ Concurrent Faults: PASSED
```

## Edge Cases Handled

| Scenario | Behavior |
|---|---|
| Pod exists during revert | ✅ Reverts on correct pod by ID |
| Pod replaced during fault | ✅ Logs warning, cleans up tracking |
| Pod reordered during fault | ✅ Finds pod by ID (not position) |
| Multiple faults on same pod | ✅ Independent tracking variables |
| Revert called twice | ✅ Second call logs "no pod ID tracked" |
| Pod object type mismatch | ✅ Type checks prevent errors |

## Code Changes

### Files Modified
- `src/failures/modes.py`:
  - `noisy_neighbor()` (lines 381-416)
  - `revert_noisy_neighbor()` (lines 418-455)
  - `force_deadlock()` (lines 549-600)
  - `revert_force_deadlock()` (lines 602-659)

### Tracking Variables Added
- `component._noisy_neighbor_pod_id` - Stores affected pod ID for noisy_neighbor
- `component._force_deadlock_pod_id` - Stores affected pod ID for force_deadlock

### Behavior Changes
| Before | After |
|---|---|
| Reverted on `service.pods[0]` (wrong pod) | Reverts on originally affected pod by ID |
| Silent failure if pod missing | Logs warning, cleans up tracking |
| No tracking cleanup | Deletes tracking variable after revert |

## Future Enhancements

### Optional: Component Registry Lookup
If pods are removed from service but still exist in registry:
```python
# Could look up in global component registry
from src.core.simulation import get_component_registry
registry = get_component_registry()
target_pod = registry.get(affected_pod_id)
```

### Optional: Fault State Persistence
For long-running simulations:
```python
# Could persist fault state to disk
fault_state = {
    'fault_type': 'noisy_neighbor',
    'affected_pod_id': 'pod_1',
    'applied_at': timestamp,
    'params': params
}
```

## Summary

✅ **Pod ID tracking implemented** - Tracks specific pods, not positions
✅ **Graceful handling of missing pods** - Logs warnings, cleans up state
✅ **Independent tracking per fault** - Multiple faults don't interfere
✅ **Backward compatible** - Existing tests still pass
✅ **Comprehensive test coverage** - 3 new tests validate robustness

**Key Insight:** In dynamic systems with pod replacement (like Kubernetes), tracking by ID is essential for fault injection correctness. Position-based references (`pods[0]`) are unreliable and lead to incorrect reverts.
