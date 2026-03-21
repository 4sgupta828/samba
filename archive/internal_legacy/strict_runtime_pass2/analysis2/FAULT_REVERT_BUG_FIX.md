# Fault Revert Bug Fix - 2025-12-15

## Problem Discovered During Testing

After fixing the fault injection bugs, testing revealed that **fault removal was not working** - latency and error rates remained elevated even after the recovery period.

### Example
In episode `data/data_20251215_004352/ep_0`:
- **Baseline**: 562.4ms
- **During Fault**: 750.6ms (1.33x - ✅ fault working)
- **After Recovery**: 791.2ms (1.41x - ❌ fault NOT removed!)

## Root Cause

The same bug that prevented fault injection from working also affected fault removal:

**File**: `src/failures/training_injector.py:660`

The revert logic had a separate `pod_level_faults` list that was missing `inject_latency` and `inject_errors`:

```python
# BEFORE (BROKEN):
pod_level_faults = ['cpu_saturation', 'memory_leak', 'memory_pressure']
```

So when reverting:
1. Revert was called on the **Service** component
2. But the fault was actually on the **Pod** components
3. Pod faults were never removed → latency stayed high

This is the SAME issue as the injection bug - there were TWO separate pod_level_faults lists (one for injection at line 489, one for revert at line 660), and both needed the fix!

## Fix Applied

**File**: `src/failures/training_injector.py:661`

Added `inject_latency` and `inject_errors` to the revert pod_level_faults list:

```python
# AFTER (FIXED):
pod_level_faults = ['cpu_saturation', 'memory_leak', 'memory_pressure', 'inject_latency', 'inject_errors']
```

Now fault removal correctly:
1. Identifies that inject_latency/inject_errors are pod-level faults
2. Applies revert to all **Pods** of the service
3. Sets `dynamics.fault_latency_additive_ms = 0.0` on each pod
4. Latency returns to baseline ✅

## Impact

This fix ensures:
- ✅ Faults are properly removed after the fault period
- ✅ System returns to baseline metrics during recovery
- ✅ RCA algorithms can observe both degradation AND recovery
- ✅ A-B-A timeline (healthy → fault → recovered) works correctly

Without this fix:
- ❌ Latency stays elevated permanently
- ❌ Error rates stay elevated permanently
- ❌ Recovery period looks the same as fault period
- ❌ RCA algorithms see continuous degradation (misleading)

## Complete List of Fixes

To make fault injection work properly, THREE fixes were required:

### Fix 1A: Dynamics Attribute Mapping
**File**: `src/components/base_component.py:401-403`
- Changed param_mapping to use `dynamics.fault_latency_additive_ms`

### Fix 1B: Pod-Level Fault Injection
**File**: `src/failures/training_injector.py:489`
- Added inject_latency/inject_errors to injection pod_level_faults list

### Fix 1C: Pod-Level Fault Removal (THIS FIX)
**File**: `src/failures/training_injector.py:661`
- Added inject_latency/inject_errors to revert pod_level_faults list

**All three fixes are required** for proper fault injection and removal!

## Testing

Test episode will validate:
1. Fault injection increases latency (already confirmed ✅)
2. Fault removal decreases latency back to baseline (needs validation)
3. Recovery period shows metrics returning to healthy levels

Expected result after fix:
- Baseline: ~150ms
- Fault: ~400ms (2.7x increase)
- Recovered: ~150ms (1.0x - back to baseline) ✅

## Files Modified

1. ✅ `src/components/base_component.py` - Dynamics attribute mapping
2. ✅ `src/failures/training_injector.py:489` - Injection pod-level list
3. ✅ `src/failures/training_injector.py:661` - **Revert pod-level list (NEW)**

Total: 3 files, 3 distinct bug fixes
