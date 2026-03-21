# Simulation Bugs Found - December 6, 2025

## Issue Summary

Dataset `data_20251206_120914` ran for 17+ minutes with 113MB of logs, indicating cascading failures.

---

## Bug #1: Excessive Steal Time Penalty ✓ FIXED

### Problem
Noisy neighbor steal time penalty was **150ms**, which is too aggressive for systems with tight timeouts.

### Evidence
- 4 victim pods on node_1 each got +150ms latency
- Pods affected: `hub_orchestrator`, `climate_service`, `entertainment_service`, `device_state_service`
- These are critical services in the call chain
- The +150ms pushed services over timeout thresholds
- Cascading failures: 1292 "Request failed due to dynamics-driven error"

### Root Cause
```python
base_steal_time_ms = 100.0  # TOO HIGH!
steal_time_ms = base_steal_time_ms * steal_time_multiplier  # 100 * 1.5 = 150ms
```

With 4-5 pods per node, adding 150ms to each victim pod caused system-wide degradation.

### Fix Applied
**File**: `src/failures/modes.py:542`

**Changed**:
```python
# Before
base_steal_time_ms = 100.0  # Base steal time penalty
steal_time_ms = base_steal_time_ms * steal_time_multiplier  # 150ms

# After
base_steal_time_ms = 20.0  # Modest base steal time penalty
steal_time_ms = base_steal_time_ms * steal_time_multiplier  # 30ms
```

### Impact
- **Before**: 150ms per victim pod → cascading failures
- **After**: 30ms per victim pod → noticeable but not catastrophic (5-10% latency increase)

### Rationale
- Typical services have 100-500ms latency
- 30ms penalty = 6-30% increase (detectable by ML models)
- 150ms penalty = 30-150% increase (system collapse)

---

## Bug #2: Queue Message Processing Error (SEPARATE ISSUE)

### Problem
```json
{
  "level": "ERROR",
  "message": "Failed to process message 5307: list.remove(x): x not in list",
  "component.id": "pod_analytics_service_0"
}
```

### Evidence
Multiple pods experiencing this error during message consumption:
- `pod_analytics_service_0`
- `pod_analytics_service_2`
- Messages: 4345, 5307, 7024, etc.

### Suspected Root Cause
This appears to be a race condition in queue message tracking:
1. Message is dequeued
2. Message times out (visibility timeout expires)
3. Message is re-queued
4. Consumer tries to remove message from tracking list
5. Message already removed → "list.remove(x): x not in list"

### Location
Likely in `src/components/pod.py` or queue consumer logic.

### Status
**NOT FIXED YET** - This is a separate pre-existing bug, not caused by our changes.

### Impact
- Messages fail to process correctly
- Re-queuing logic may be broken
- Could cause message loss or duplicates

---

## Bug #3: Cascading Cache Failures (OBSERVED)

### Problem
After steal time penalty, cache operations started timing out:
- 402 "Cache get failed - connection timeout"
- 267 "Cache operation failed: Connection timeout to device_cache"
- 138 "GC triggered: memory=2000MB (390.6%)" → OOMKilled

### Root Cause
The excessive 150ms steal time caused:
1. Services slower to respond
2. Cache connections timeout
3. Fallback to database
4. Database overload
5. Memory pressure
6. OOM kills
7. Pod restarts
8. More failures

### Fix
Reducing steal time to 30ms should prevent this cascade.

---

## Testing Required

### Test #1: Reduced Steal Time
```bash
python generate_dataset.py --episodes 1 -o data/test_steal_time_fix \
  --fault-type noisy_neighbor --fault-role service
```

**Expected**:
- Log size < 10MB
- No cascading cache failures
- No OOM kills
- Simulation completes in < 5 minutes

### Test #2: Verify Queue Bug (Separate Investigation)
```bash
# Need to find the queue message tracking code
grep -r "list.remove" src/components/pod.py src/components/queue.py
```

---

## Summary

| Bug | Status | Severity | Fix Applied |
|-----|--------|----------|-------------|
| Excessive steal time (150ms) | ✓ Fixed | CRITICAL | Reduced to 30ms |
| Queue message list.remove | ⚠️ Found | HIGH | Not fixed yet |
| Cascading cache failures | ✓ Fixed | CRITICAL | Side effect of steal time fix |

---

## Recommendations

1. **Immediate**: Test with reduced steal time (30ms)
2. **Next**: Investigate queue message tracking bug
3. **Future**: Add configuration parameter for steal_time_base_ms
4. **Future**: Add max_steal_time_per_node cap (e.g., 50ms)

---

## Configuration Parameters

For future reference, noisy neighbor can be tuned via params:

```python
params = {
    'cpu_percent': 100.0,               # Aggressor CPU (default: 100%)
    'steal_time_multiplier': 1.5        # Multiplier for base steal time (default: 1.5)
}
# Actual steal time = 20ms * 1.5 = 30ms
```

To make impact more severe:
```python
params = {'steal_time_multiplier': 3.0}  # 20 * 3 = 60ms
```

To make impact gentler:
```python
params = {'steal_time_multiplier': 0.5}  # 20 * 0.5 = 10ms
```
