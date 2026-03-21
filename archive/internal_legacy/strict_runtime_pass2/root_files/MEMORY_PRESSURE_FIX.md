# Memory Pressure Fault Fix

## Issues Found

1. **Memory not increasing during fault**: The gradual `memory_pressure` injection was using the wrong parameter (`latency_ms` instead of modifying `memory_base`), so memory never actually increased.

2. **Latency staying high after recovery**: Because the fault was injecting latency instead of memory pressure, and the revert wasn't properly restoring the memory baseline, latency remained elevated.

3. **Revert not working correctly**: The revert function was using a hardcoded fallback value (`memory_increase_mb = 300`) instead of the actual calculated increase, so it might not fully revert the fault.

## Root Cause

In `src/failures/training_injector.py` lines 183-185, the gradual `memory_pressure` injection was incorrectly configured:

```python
elif failure_mode == 'memory_pressure':
    parameter = 'latency_ms'  # WRONG!
    delta = params.get('memory_latency_ms', 300)
```

This caused the fault to inject latency instead of memory pressure, which explains why:
- Memory didn't increase (because `memory_base` was never modified via the gradual mechanism)
- Latency increased (because latency was being injected)
- After recovery, latency stayed high (because the revert removed the wrong thing, or there was queue buildup)

## Fixes Applied

### 1. Updated `memory_pressure` function (`src/failures/modes.py`)

- Added support for gradual injection via `progress` parameter (0.0-1.0)
- Fixed calculation to use original baseline for gradual injection (prevents compounding)
- Store target increase amount for proper revert
- Support both instant and gradual injection modes

### 2. Updated gradual injection logic (`src/failures/training_injector.py`)

- Changed from using `apply_infrastructure_change` with wrong parameter to calling `memory_pressure` function directly with progress (similar to `cache_failure`)
- Supports both `step` and `linear` progression modes
- Properly handles pod-level faults (applies to all pods of a service)

### 3. Updated revert logic (`src/failures/training_injector.py`)

- Changed from instant revert to gradual revert (calls `memory_pressure` with decreasing progress)
- Uses stored target increase value instead of hardcoded fallback
- Properly cleans up tracking attributes
- Returns generator object (consistent with `cache_failure` pattern) for caller to yield from

### 4. Updated `revert_memory_pressure` function (`src/failures/modes.py`)

- Uses stored target increase value for proper revert
- Falls back to parameter if stored value not available
- Properly cleans up all tracking attributes

## Expected Behavior After Fix

1. **During fault injection (60s-90s)**:
   - Memory should gradually increase from baseline (~200 MB) toward target (~350-400 MB based on severity 0.5)
   - Memory increase should be visible in metrics

2. **During fault period (90s-210s)**:
   - Memory should remain elevated
   - Latency should increase due to memory pressure effects (GC pauses, allocation overhead)
   - CPU may spike during GC pauses

3. **During recovery (210s-240s)**:
   - Memory should gradually decrease back toward baseline
   - Latency should decrease as memory pressure is relieved

4. **After recovery (240s-300s)**:
   - Memory should return to baseline levels
   - Latency should return to baseline levels (may take a few seconds for queues to drain)

## Testing

To verify the fix works:

1. Re-run the dataset generation with the same parameters
2. Check that memory increases during fault injection
3. Check that memory decreases during recovery
4. Check that latency returns to baseline after recovery

## Files Modified

- `src/failures/modes.py`: Updated `memory_pressure` and `revert_memory_pressure` functions
- `src/failures/training_injector.py`: Updated gradual injection and revert logic for `memory_pressure`

## Implementation Note

The `revert_gradual_failure()` function now consistently returns generator objects for faults requiring gradual revert (`cache_failure`, `memory_pressure`), matching the pattern established by `cache_failure`. The caller in `generate_dataset.py` checks if a generator is returned and yields from it appropriately (lines 987-989).

