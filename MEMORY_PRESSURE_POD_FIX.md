# Memory Pressure Fault - Pod Support Fix

## Issue

The `memory_pressure` fault had no impact on the root cause node (`social_service`) because:

1. **Root cause was a Service**: The fault was targeting `social_service`, which is a `Service` object, not a `ComputeAgent` or `Pod`.

2. **Service has Pods**: When a Service is targeted, the fault injection code correctly identifies that it's a pod-level fault and tries to apply it to all pods of the service (see `training_injector.py` line 191-192).

3. **Type check failure**: However, the `memory_pressure` function only accepted `ComputeAgent` components, but Pods are the new architecture. When the function was called on a Pod, it would log a warning and return early without applying the fault.

## Root Cause

In `src/failures/modes.py`, the `memory_pressure` function had this type check:

```python
if not isinstance(component, ComputeAgent):
    component._emit_log("WARN", "memory_pressure can only be applied to ComputeAgent components.")
    return
```

This rejected Pods, even though Pods have the same structure as ComputeAgents (they both have dynamics engines and can have memory pressure applied).

## Fix Applied

Updated both `memory_pressure` and `revert_memory_pressure` functions to accept both `ComputeAgent` and `Pod`:

```python
from src.components.compute import ComputeAgent
from src.components.pod import Pod

if not isinstance(component, (ComputeAgent, Pod)):
    component._emit_log("WARN", "memory_pressure can only be applied to ComputeAgent or Pod components.")
    return
```

## Why This Matters

- **New Architecture**: The codebase has migrated from `ComputeAgent` to `Pod` as the container execution unit (matching Kubernetes terminology).
- **Service → Pod Mapping**: Services contain Pods, and pod-level faults (like `memory_pressure`, `cpu_saturation`, `memory_leak`) need to be applied to the Pods, not the Service itself.
- **Backward Compatibility**: The fix maintains support for both `ComputeAgent` (legacy) and `Pod` (new architecture).

## Files Modified

- `src/failures/modes.py`: Updated `memory_pressure` and `revert_memory_pressure` to accept both `ComputeAgent` and `Pod`

## Testing

After this fix, when a `memory_pressure` fault is injected on a service:
1. The fault injection code correctly identifies it as a pod-level fault
2. It applies the fault to all pods of the service
3. The `memory_pressure` function now accepts Pods and successfully modifies their `dynamics.config.memory_base`
4. Memory should increase during fault injection and decrease during recovery

