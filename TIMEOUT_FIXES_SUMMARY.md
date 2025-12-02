# Timeout and Queue Management Fixes - Summary

## Problem Statement

The simulation was experiencing crash loops where pods would:
1. Get slow/overloaded → requests queue up
2. Pod crashes (OOM) → queued requests persist in SimPy
3. Pod restarts → massive backlog rushes in
4. Pod immediately crashes again → **CrashLoopBackOff**

This didn't match real-world Kubernetes behavior where process crashes clear all in-memory state.

## Root Cause Analysis

### What Was Wrong

**In Real Production Systems:**
- Client times out → TCP connection closed → Request cancelled on server
- Server crashes → Process dies → All in-flight requests lost
- Thread pools cleared on process restart
- Connection pools reset

**In Our Simulation (Before Fix):**
- Client times out → Client gives up ✅
- **Server keeps processing** → SimPy generator continues running ❌
- **Pod crashes** → Thread/DB pool queues persist ❌
- **Pod restarts** → All queued requests immediately execute ❌

## Fixes Implemented

### 1. ✅ Clear Resource Queues on Pod Restart

**File:** `src/components/pod.py:209-234`

**What:** When a pod enters "STARTING" state (after crash), clear all queued requests from:
- Thread pool queue (`self.thread_pool.queue`)
- DB connection pool queue (`self.db_connection_pool.queue`)

**Why:** Simulates real Kubernetes behavior where process termination (SIGKILL) clears all in-memory state. Prevents backlog from overwhelming restarted pod.

**Real-world equivalent:** When a container is killed, all pending work in process memory is lost.

```python
# CRITICAL FIX: Clear resource queues on restart
thread_queue_size = len(self.thread_pool.queue)
if thread_queue_size > 0:
    self._emit_log("WARN", f"Discarding {thread_queue_size} queued requests from thread pool (pod restart)")
    self.thread_pool.queue.clear()

db_queue_size = len(self.db_connection_pool.queue)
if db_queue_size > 0:
    self._emit_log("WARN", f"Discarding {db_queue_size} queued requests from DB connection pool (pod restart)")
    self.db_connection_pool.queue.clear()
```

### 2. ✅ Server-Side Request Timeout

**Files:**
- Config: `config/simulation_config.yaml:280`
- Config class: `src/core/simulation_config.py:68`
- Implementation: `src/components/pod.py:523-628`

**What:** Added independent server-side timeout (default: 30s) that aborts request processing if it takes too long, even if client is still waiting.

**Why:** Real servers (Nginx, Kubernetes, Spring Boot, Express, etc.) have request timeouts independent of client timeouts to prevent resource exhaustion.

**Real-world equivalent:**
- **Nginx:** `proxy_read_timeout`, `proxy_send_timeout` (default 60s)
- **Kubernetes:** `timeoutSeconds` on probes (default 1-10s)
- **Spring Boot:** `server.connection-timeout` (default 30s)
- **Node.js:** `server.timeout` (default 120s)
- **Go:** `ReadTimeout`, `WriteTimeout`

```python
# Get server-side request timeout from config
server_timeout = config.timeouts.server_request_seconds  # Default: 30.0s

# Create request processing as a separate process so we can timeout it
request_process = self.env.process(self._execute_request_with_timeout(...))

# Race between request completion and timeout
result = yield request_process | timeout_event

if timeout_event in result:
    # Server-side timeout occurred
    raise Exception(f"Request timed out on server after {elapsed:.2f}s")
```

### 3. ✅ Track and Interrupt Active Requests on Crash

**File:** `src/components/pod.py:57-58, 223-234, 467-504`

**What:**
- Track all active request processes in `self.active_request_processes` set
- On pod crash/restart, interrupt all active processes with `PodCrashed` cause
- Handle interrupts gracefully and convert to exceptions for clients

**Why:** Simulates SIGKILL behavior where all threads are terminated immediately when process crashes.

**Real-world equivalent:** When Kubernetes kills a pod (SIGKILL), all active threads die mid-execution.

```python
# Track active processes
self.active_request_processes = set()

# In handle_request():
current_process = self.env.active_process
self.active_request_processes.add(current_process)
try:
    # Process request...
    yield from self._handle_request_internal(request_type, span)
except simpy.Interrupt as interrupt:
    if interrupt.cause == "PodCrashed":
        raise Exception("Request failed: Pod crashed during processing")
finally:
    self.active_request_processes.discard(current_process)

# On pod restart:
for process in list(self.active_request_processes):
    try:
        process.interrupt("PodCrashed")
    except RuntimeError:
        pass
self.active_request_processes.clear()
```

## Configuration Changes

### New Configuration Parameter

**File:** `config/simulation_config.yaml`

```yaml
compute:
  timeouts:
    server_request_seconds: 30.0  # Server-side timeout for processing a request
```

This is **independent** of the client timeout (`workload_generator.request_timeout_seconds: 30.0`).

**Why separate?**
- Client timeout: How long client waits for response
- Server timeout: How long server allows request to process

In production, these can be different (e.g., client timeout 60s, server timeout 30s means server fails fast before client gives up).

## Testing

**Test File:** `test_timeout_fixes.py`

### Test Results

**All tests pass! ✅**

```
============================================================
Results: 3/3 tests passed
✅ All tests passed!
============================================================
```

1. ✅ **Queue Clearing Test**: PASSED
   - Queued 20 requests in thread pool
   - Triggered OOM crash
   - Verified queues cleared on restart
   - Output: "Discarding 20 queued requests from thread pool (pod restart)"
   - Output: "Interrupting 20 active request processes (pod crash/restart)"

2. ✅ **Server Timeout Test**: PASSED
   - Injected 35-second slow request
   - Server timeout triggered at exactly 30.0s
   - Output: "Request processing timed out (30.00s >= 30.0s)"
   - Error message: "Request timed out on server after 30.00s"

3. ✅ **Active Request Interruption Test**: PASSED
   - Started long-running request (25 seconds)
   - Crashed pod after 2 seconds (mid-request)
   - Active request properly interrupted
   - Output: "Interrupting 1 active request processes (pod crash/restart)"
   - Output: "Request interrupted due to pod crash: GET"
   - Error message: "Request failed: Pod crashed during processing"

## Impact

### Before Fixes
```
1. Pod gets slow → 100+ requests queue up
2. Pod crashes (OOM)
3. Pod restarts in 10-20s
4. All 100+ queued requests immediately execute
5. Pod immediately OOMs again → CrashLoopBackOff
6. Repeat until manual intervention
```

### After Fixes
```
1. Pod gets slow → 100+ requests queue up
2. Pod crashes (OOM)
3. Pod restart clears:
   - 100+ queued requests (discarded)
   - Active request processes (interrupted)
4. Pod starts clean with empty queues
5. Gradual recovery as new requests arrive
6. Normal operation resumes ✅
```

## Real-World Fidelity

These fixes bring the simulation closer to real production behavior:

| Behavior | Before | After | Real Production |
|----------|--------|-------|-----------------|
| Client timeout | ✅ Yes | ✅ Yes | ✅ Yes (HTTP client) |
| Server timeout | ❌ No | ✅ Yes | ✅ Yes (Nginx, K8s, etc.) |
| Queue clearing on crash | ❌ No | ✅ Yes | ✅ Yes (process death) |
| Active request interruption | ❌ No | ✅ Yes | ✅ Yes (SIGKILL) |
| Backlog prevention | ❌ No | ✅ Yes | ✅ Yes (state reset) |

## Files Modified

1. `src/components/pod.py` - Core timeout and queue management logic
2. `config/simulation_config.yaml` - Added server timeout configuration
3. `src/core/simulation_config.py` - Added `TimeoutsConfig.server_request_seconds`
4. `test_timeout_fixes.py` - Test suite for validation

## Next Steps (Optional Enhancements)

1. **Per-service timeouts** - Allow different timeout values per service type
2. **Gradual recovery** - Implement backoff/rate limiting after pod restart
3. **Queue age tracking** - Track how long requests have been queued
4. **Metrics** - Add metrics for timeouts and queue discards
5. **Configurable interrupt behavior** - Allow pods to gracefully shutdown vs. hard kill

## Validation Checklist

- [x] Queue clearing on restart
- [x] DB connection pool clearing on restart
- [x] Server-side request timeout
- [x] Active process tracking
- [x] Active process interruption on crash
- [x] Configuration parameter added
- [x] Test suite created
- [x] Logging for debugging

## Conclusion

All critical fixes have been implemented. The simulation now accurately models real-world Kubernetes behavior for:
- Request timeouts (both client and server side)
- Process crash/restart state clearing
- Prevention of crash loops due to request backlogs

The pod crash loop scenario you described should no longer occur - queues are cleared on restart, preventing the "massive backlog of queued up requests" from crashing the pod again.
