# Memory Leak Fault - Consumer Node Fix

**Date:** 2025-12-15
**Issue:** Memory leak fault not having effect on consumer nodes
**Fix:** Consumer-specific logic with persistent leak model

---

## Problem Summary

The memory leak fault was not having any visible effect on async consumer nodes (nodes with `queue_in` connections). Investigation revealed:

### Root Cause
The memory leak implementation uses a **per-request model** that only accumulates memory based on concurrent requests:

```python
memory_from_concurrent = memory_per_request_mb * concurrent_requests
target_memory = memory_base + memory_from_concurrent
```

Where `concurrent_requests` is calculated using Little's Law:
```python
concurrent_requests = throughput * latency
```

**The Problem:**
- Consumer nodes process messages asynchronously from queues
- Low throughput (~1 RPS) → Low concurrent requests (~0.2)
- Memory leak effect = 45 MB/req * 0.2 reqs = **9 MB** (negligible!)
- Memory is NOT persistent (decreases as requests complete)

### Data Analysis
From `../data/batch_run/data_20251215_014022/ep_0`:
- **Fault injected:** sim.time=60 (confirmed in logs)
- **Memory impact:** None - stayed at ~200MB throughout
- **Throughput:** ~5-6 messages per 5 seconds = ~1 RPS
- **Fault removal:** Not logged (secondary issue)

---

## Solution: Consumer-Specific Logic (Option 3)

Implemented dual-model approach that detects consumer nodes and applies appropriate leak model.

### Changes Made

#### File: `/Users/sgupta/samba/src/failures/modes.py`

##### 1. Enhanced `start_memory_leak()` Function

**Detection Logic:**
```python
# Detect if this is a consumer node (has queue_in connection)
is_consumer = False
if isinstance(component, Pod) and hasattr(component, 'parent_service'):
    parent = component.parent_service
    if parent and hasattr(parent, 'connections'):
        connections = getattr(parent, 'connections', {})
        is_consumer = 'queue_in' in connections
```

**Consumer Model (Persistent Leak):**
- Increases `memory_base` directly (persistent memory growth)
- Applies **10x multiplier** to leak rate for visible effect
- Models memory accumulation independent of throughput
- Examples: Cached objects, buffered data, memory fragmentation

```python
persistent_leak_mb = leak_rate * 10  # 10x multiplier
component.dynamics.config.memory_base += persistent_leak_mb
```

**Non-Consumer Model (Per-Request Leak):**
- Increases `memory_per_request_mb` (original behavior)
- Memory accumulates based on concurrent requests
- Works well for high-throughput HTTP services

```python
component.dynamics.config.memory_per_request_mb += leak_rate
```

##### 2. Enhanced `stop_memory_leak()` Function

**Proper Tracking & Cleanup:**
- Stores original values: `_memory_leak_original_base` or `_memory_leak_original_per_request`
- Tracks leak model: `_memory_leak_is_consumer` flag
- Cleans up all tracking attributes on removal

**Model-Aware Revert:**
- Consumer: Restores `memory_base` to original value
- Non-Consumer: Restores `memory_per_request_mb` to original value
- Forces memory drop immediately for clean recovery

##### 3. Improved Logging (Fix #4)

**Changed log level from INFO to WARN** so removal is visible:
```python
component._emit_log("WARN", f"Stopping memory leak (CONSUMER): ...")
component._emit_log("WARN", f"Stopping memory leak (PER-REQUEST): ...")
```

**Before:** Fault removal was silent (INFO logs filtered out)
**After:** Both injection and removal are visible in telemetry

---

## Test Results

### Test Coverage
Created comprehensive test suite: `test_memory_leak_consumer_fix.py`

**Test 1: Consumer Node**
- ✅ Detects consumer (queue_in connection)
- ✅ Applies persistent leak model
- ✅ Baseline memory increases by 400MB (40MB * 10x)
- ✅ Removal restores original baseline
- ✅ Cleanup removes tracking attributes

**Test 2: Non-Consumer Node**
- ✅ Detects non-consumer (no queue_in)
- ✅ Applies per-request leak model
- ✅ Per-request memory increases by 40MB
- ✅ Baseline memory unchanged
- ✅ Removal restores original per-request value

**Test 3: Logging**
- ✅ Injection logs visible (WARN level)
- ✅ Removal logs visible (WARN level)
- ✅ Both models log appropriately

### Example Logs

**Consumer Injection:**
```json
{"level": "WARN", "message": "Starting memory leak (CONSUMER): +400.0MB baseline (memory_base: 600.0MB)", "component.id": "pod_analytics_service_0"}
```

**Consumer Removal:**
```json
{"level": "WARN", "message": "Stopping memory leak (CONSUMER): -400.0MB baseline removed (memory_base restored to 200.0MB, current memory: 200MB)", "component.id": "pod_analytics_service_0"}
```

**Non-Consumer Injection:**
```json
{"level": "WARN", "message": "Starting memory leak (PER-REQUEST): +40.0 MB/request (memory_per_request_mb: 45.00MB)", "component.id": "pod_auth_service_0"}
```

**Non-Consumer Removal:**
```json
{"level": "WARN", "message": "Stopping memory leak (PER-REQUEST): memory_per_request_mb restored to 5.00MB (current memory: 200MB)", "component.id": "pod_auth_service_0"}
```

---

## Expected Impact

### For Consumer Nodes (queue_in)
- **Before:** Memory stays flat (~200MB), no visible effect
- **After:** Memory increases by 400MB, clear degradation signal
- **Recovery:** Memory drops back to baseline

### For HTTP Services
- **No change:** Original per-request model still works
- **Better logging:** Removal is now visible

### Observability
- Both injection and removal are logged
- Model type visible in logs (CONSUMER vs PER-REQUEST)
- Memory values tracked for analysis

---

## Technical Design Decisions

### Why 10x Multiplier?
Consumer nodes typically have:
- Low throughput (1-10 RPS)
- Low concurrent requests (<1)
- Asynchronous processing

The 10x multiplier ensures:
- Visible memory impact (400MB vs 40MB)
- Realistic degradation timeline
- Observable in metrics and RCA

### Why Persistent vs Per-Request?
Different architectural patterns require different leak models:

| Pattern | Leak Type | Example |
|---------|-----------|---------|
| Async Queue Consumer | Persistent | Python object retention, Go goroutine leaks |
| HTTP API Service | Per-Request | Request context leaks, connection pooling |
| Background Job | Persistent | Memory caches, buffered data |
| Streaming Service | Per-Request | In-flight stream buffers |

### Backwards Compatibility
- Non-consumer nodes: No behavior change
- Existing simulations: Continue to work
- Legacy fallback: Handles edge cases

---

## Files Modified

1. `/Users/sgupta/samba/src/failures/modes.py`
   - `start_memory_leak()`: Added consumer detection and dual-model logic
   - `stop_memory_leak()`: Added model-aware revert and cleanup

2. `/Users/sgupta/samba/test_memory_leak_consumer_fix.py` (new)
   - Comprehensive test suite for both models
   - Verification of logging and cleanup

3. `/Users/sgupta/samba/MEMORY_LEAK_CONSUMER_FIX.md` (this document)
   - Complete documentation of issue and fix

---

## Next Steps

### Verification
1. Re-run original failing scenario: `../data/batch_run/data_20251215_014022`
2. Verify memory increases during fault period (sim.time 60-210)
3. Verify memory drops during recovery (sim.time 210-240)
4. Check logs show both injection and removal

### Future Enhancements
1. **Gradual Leak:** Add time-based leak progression (currently instant)
2. **Configurable Multiplier:** Make 10x multiplier tunable via params
3. **Leak Rate Per Second:** Model continuous leak independent of requests
4. **OOM Kill Logic:** Trigger pod restarts when memory exceeds limits

---

## References

- Issue Discussion: Consumer node memory leak not having effect
- Related Files:
  - `/Users/sgupta/samba/src/dynamics/metrics_dynamics_engine.py` (memory dynamics)
  - `/Users/sgupta/samba/src/components/pod.py` (consumer processing)
  - `/Users/sgupta/samba/src/components/service.py` (service connections)
