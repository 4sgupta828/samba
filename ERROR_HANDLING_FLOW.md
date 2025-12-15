# Error Handling Flow - Complete Guide

## How Errors Flow Through the System

This document explains the complete error handling flow from when an error occurs to how it's reported to the user.

---

## 1. Error Origin Points

Errors can originate from multiple sources:

### A. Network Partition
```python
# src/components/network.py:check_network_partition
raise NetworkPartitionError("Network partition blocks communication from X to Y")
```

### B. Database Errors
```python
# Database query failures, timeouts, connection issues
raise DatabaseError("Query failed")
```

### C. Service Errors
```python
# Downstream service failures, timeouts
raise DependencyFailureException("Service call failed")
```

### D. Resource Exhaustion
```python
# Thread pool full, connection pool exhausted
raise Exception("Thread pool queue full: 250 requests waiting")
```

### E. Dynamics-Based Errors
```python
# Random errors based on CPU/latency thresholds
if random.random() < self.dynamics.get_error_rate():
    raise Exception("Request processing failed: Service temporarily unavailable")
```

---

## 2. Error Handling Layers

### Layer 1: Dependency Call (Database, Cache, Service, External)

#### Database Calls (`pod.py:1092-1153`)
```python
for attempt in range(max_retries):  # Default: 3 attempts
    try:
        # Check network partition
        self._check_network_partition(db.id)  # ← May raise NetworkPartitionError

        # Make DB call
        yield self.env.process(db.handle_query(...))

        # Record success metrics
        break  # Success - exit retry loop

    except Exception as e:
        self._emit_log("WARN", f"DB call failed (attempt {attempt+1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            # Retry with exponential backoff
            backoff_time = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s
            yield self.env.timeout(backoff_time)
        else:
            # Final failure - record error metrics and re-raise
            self.dependency_errors.add(1, {"dependency_id": db.id, ...})
            raise  # ← Error propagates up
```

**Error Flow**:
```
NetworkPartitionError raised
  ↓
Retry 1: Wait 0.1s
  ↓
Retry 2: Wait 0.2s
  ↓
Retry 3: Wait 0.4s
  ↓
ALL RETRIES FAILED
  ↓
Record error metrics
  ↓
RE-RAISE exception ← Propagates to Layer 2
```

#### Service Calls (`service_propagation_mixin.py:195-320`)
```python
# Check network partition FIRST
check_network_partition(source_id, target_id)  # ← May raise NetworkPartitionError

# Check circuit breaker
if not circuit_breaker.should_allow_request():
    raise CircuitBreakerOpenException(...)  # ← Fail fast

# Retry loop
for attempt in range(1, max_attempts + 1):
    try:
        # Call with timeout
        result = yield from call_with_timeout(call_func, timeout_ms)

        # Success
        circuit_breaker.record_success()
        return result

    except Exception as e:
        # Track failure
        circuit_breaker.record_failure()

        if attempt < max_attempts:
            # Retry with backoff
            yield self.env.timeout(retry_delay)
        else:
            # Final failure
            raise DependencyFailureException(...)  # ← Propagates up
```

**Error Flow**:
```
NetworkPartitionError raised
  ↓
Circuit breaker: Record failure
  ↓
Retry 1
  ↓
Retry 2
  ↓
ALL RETRIES FAILED
  ↓
Circuit breaker opens (after 5 failures)
  ↓
Wrapped in DependencyFailureException
  ↓
RE-RAISE ← Propagates to Layer 2
```

---

### Layer 2: Processing Pipeline (`pod.py:838-898`)

The processing pipeline executes steps sequentially. If ANY step fails, the entire pipeline aborts:

```python
def _execute_processing_pipeline(self, request_type: str, span):
    pipeline = self.parent_service.processing_pipeline

    for step in pipeline:
        if step["type"] == "cache_check":
            yield from self._execute_cache_logic(step, span)
            # Cache errors are caught and treated as misses (don't fail request)

        elif step["type"] == "db_query":
            yield from self._execute_db_logic(step, span)
            # ← If this raises, pipeline aborts immediately

        elif step["type"] == "service_calls":
            yield from self._execute_service_calls(step, span, request_type)
            # ← If this raises, pipeline aborts immediately

        elif step["type"] == "external_calls":
            yield from self._execute_external_calls(step, span)
            # ← If this raises, pipeline aborts immediately
```

**Error Flow**:
```
DB call fails (Layer 1)
  ↓
Exception propagates via "yield from"
  ↓
Pipeline aborts (remaining steps NOT executed)
  ↓
Exception propagates to Layer 3
```

**Key Point**: `yield from` propagates exceptions immediately - no swallowing!

---

### Layer 3: Request Handler (`pod.py:677-836`)

This is the main request processing wrapper:

```python
def _handle_request_internal(self, request_type: str, span, skip_metrics: bool = False):
    start_time = self.env.now

    try:
        # Execute processing pipeline
        yield from self._execute_processing_pipeline(request_type, span)
        # ↑ Any exception from pipeline lands here

        # Record SUCCESS metrics
        latency_ms = (self.env.now - start_time) * 1000
        if not skip_metrics:
            self.request_counter.add(1, {"status": "success", ...})
            self.request_duration.record(latency_ms, {"status": "success", ...})

    except Exception as e:
        # Record ERROR metrics
        latency_ms = (self.env.now - start_time) * 1000
        if not skip_metrics:
            self.request_counter.add(1, {"status": "error", ...})
            self.request_duration.record(latency_ms, {"status": "error", ...})
            self.request_errors.add(1, {...})

        # Re-raise exception so caller knows the request failed
        raise  # ← OUR FIX: Exception propagates to Layer 4
```

**Error Flow**:
```
Exception from pipeline (Layer 2)
  ↓
Caught by try/except at line 806
  ↓
Record error metrics:
  - request_counter{status="error"}
  - request_duration{status="error"}
  - request_errors{error_type="NetworkPartitionError"}
  ↓
RE-RAISE exception (line 832) ← OUR FIX
  ↓
Exception propagates to Layer 4
```

**Before Our Fix**:
```
Exception caught
  ↓
Error metrics recorded
  ↓
Exception SWALLOWED (no raise)
  ↓
Function returns normally
  ↓
Caller thinks: SUCCESS! ✗ BUG
```

**After Our Fix**:
```
Exception caught
  ↓
Error metrics recorded
  ↓
Exception RE-RAISED (line 832)
  ↓
Caller receives exception
  ↓
Caller knows: FAILURE! ✓ CORRECT
```

---

### Layer 4A: HTTP Request Handler (Workload Generator)

For HTTP requests from the workload generator:

```python
# src/workloads/generator.py
try:
    # Call service
    request_process = self.env.process(gateway.handle_request(request_type))
    request_timeout = self.env.timeout(self.request_timeout)

    result = yield request_process | request_timeout

    if request_process not in result:
        # Timeout
        self.total_requests_timeout += 1
    else:
        # Success
        self.total_requests_successful += 1

except Exception as e:
    # Request failed with exception ← Receives exception from Layer 3
    self.total_requests_failed += 1
    self.requests_counter.add(1, {"type": "failed"})
    # Circuit breaker records failure

# Simulation continues - exception is caught and handled
```

**Error Flow**:
```
Exception from Layer 3 (handle_request)
  ↓
Caught by workload generator
  ↓
Increment total_requests_failed
  ↓
Record workload.requests{type="failed"}
  ↓
Update circuit breaker
  ↓
Continue generating more requests
  ↓
Simulation DOES NOT CRASH ✓
```

---

### Layer 4B: Queue Message Processing

For async queue consumers:

```python
# pod.py:_process_queue_message
try:
    # Process message
    yield from self._handle_request_internal(request_type, span=None, skip_metrics=True)
    # ↑ May raise exception from Layer 3

    # Success - delete message from queue
    queue.delete_message(msg)

    # Record success metrics
    self.request_counter.add(1, {"status": "success", "request_type": "PROCESS", ...})

except Exception as e:
    # Processing failed ← Receives exception from Layer 3
    self._emit_log("ERROR", f"Failed to process message {msg.id}: {e}")

    # Record error metrics
    self.request_counter.add(1, {"status": "error", "request_type": "PROCESS", ...})
    self.request_errors.add(1, {...})

    # Don't delete message - let visibility timeout return it to queue
    # Re-raise so circuit breaker can track failures
    raise  # ← Exception propagates to Layer 5
```

**Error Flow**:
```
Exception from Layer 3 (_handle_request_internal)
  ↓
Caught by _process_queue_message
  ↓
Message NOT deleted (will be retried)
  ↓
Record error metrics
  ↓
RE-RAISE exception ← Propagates to Layer 5 (circuit breaker)
```

---

### Layer 5: Queue Consumer Circuit Breaker

```python
# pod.py:_consume_from_queue
consecutive_failures = 0
backoff_delay = 1.0

while True:
    # Circuit breaker: if too many failures, back off
    if consecutive_failures >= 5:
        self._emit_log("WARN", f"Circuit breaker: {consecutive_failures} failures, backing off {backoff_delay}s")
        yield self.env.timeout(backoff_delay)
        backoff_delay = min(backoff_delay * 2, 60.0)  # Exponential backoff

    try:
        # Receive message
        msg = yield from queue.receive_message()

        # Process message
        try:
            yield self.env.process(self._process_queue_message(msg, queue))
            # ↑ May raise exception from Layer 4B

            # Success - reset circuit breaker
            consecutive_failures = 0
            backoff_delay = 1.0

        except Exception as proc_error:
            # Message processing failed ← Receives exception from Layer 4B
            consecutive_failures += 1
            self._emit_log("WARN", f"Message failed (consecutive: {consecutive_failures})")
            # Circuit breaker will apply backpressure on next iteration

    except Exception as e:
        # Queue receive failed
        consecutive_failures += 1
        yield self.env.timeout(backoff_delay)
        backoff_delay = min(backoff_delay * 2, 60.0)

# Consumer continues running - exceptions are handled
# Simulation DOES NOT CRASH ✓
```

**Error Flow**:
```
Exception from Layer 4B (_process_queue_message)
  ↓
Caught by _consume_from_queue
  ↓
Increment consecutive_failures
  ↓
[If failures >= 5]
  ↓
Circuit breaker opens
  ↓
Next iteration: Wait backoff_delay (1s → 2s → 4s → ... → 60s)
  ↓
Periodically retry
  ↓
[When DB recovers]
  ↓
First success resets circuit breaker
  ↓
Normal operation resumes
```

---

## 3. Error Metrics Tracking

Errors are tracked at multiple layers for observability:

### Layer 1: Dependency Metrics
```python
# Database dependency error
self.dependency_errors.add(1, {
    "dependency_id": "analytics_db",
    "dependency_name": "database",
    "component.id": "pod_analytics_service_0",
    "service.name": "analytics_service"
})

# Metric: service.analytics_service.dependency.errors
```

### Layer 2: Circuit Breaker Metrics
```python
# Circuit breaker rejection
self.circuit_breaker_rejection_counter.add(1, {
    "dependency_name": "billing_service",
    "dependency_type": "service",
    "component.id": "pod_gateway_0"
})

# Metric: circuit_breaker.rejections
```

### Layer 3: Service Request Metrics
```python
# Service request error
self.request_counter.add(1, {
    "status": "error",
    "request_type": "POST",
    "component.id": "pod_analytics_service_0",
    "service.name": "analytics_service",
    "service.id": "analytics_service"
})

# Metrics:
#   - service.analytics_service.requests{status="error"}
#   - service.analytics_service.errors{error_type="NetworkPartitionError"}
```

### Layer 4: Workload Metrics
```python
# Workload request failure
self.requests_counter.add(1, {
    "type": "failed"
})

# Metric: workload.requests{type="failed"}
```

---

## 4. Complete Error Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     ERROR ORIGIN                                │
├─────────────────────────────────────────────────────────────────┤
│ • Network Partition                                             │
│ • Database Error                                                │
│ • Service Timeout                                               │
│ • Resource Exhaustion                                           │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 1: DEPENDENCY CALL                           │
├─────────────────────────────────────────────────────────────────┤
│ • Check network partition                                       │
│ • Retry with exponential backoff (DB: 3x, Service: configurable│
│ • Record dependency error metrics                               │
│ • Circuit breaker tracking (service calls)                      │
│ • RE-RAISE exception                                            │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│          LAYER 2: PROCESSING PIPELINE                           │
├─────────────────────────────────────────────────────────────────┤
│ • Exception propagates via "yield from"                         │
│ • Pipeline aborts (remaining steps NOT executed)                │
│ • No error swallowing                                           │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│           LAYER 3: REQUEST HANDLER                              │
├─────────────────────────────────────────────────────────────────┤
│ • Catch exception                                               │
│ • Record error metrics:                                         │
│   - request_counter{status="error"}                             │
│   - request_duration{status="error"}                            │
│   - request_errors{error_type="..."}                            │
│ • RE-RAISE exception ← OUR FIX                                  │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
         ┌───────────┴───────────┐
         ↓                       ↓
┌─────────────────────┐  ┌─────────────────────┐
│  LAYER 4A: HTTP     │  │  LAYER 4B: QUEUE    │
│  (Workload Gen)     │  │  (Message Proc)     │
├─────────────────────┤  ├─────────────────────┤
│ • Catch exception   │  │ • Catch exception   │
│ • Increment failed  │  │ • Don't delete msg  │
│ • Record metrics    │  │ • Record metrics    │
│ • Continue          │  │ • RE-RAISE          │
│ • NO CRASH ✓        │  └─────────┬───────────┘
└─────────────────────┘            ↓
                          ┌─────────────────────┐
                          │  LAYER 5: CIRCUIT   │
                          │  BREAKER            │
                          ├─────────────────────┤
                          │ • Track failures    │
                          │ • Exponential       │
                          │   backoff           │
                          │ • Auto-recovery     │
                          │ • NO CRASH ✓        │
                          └─────────────────────┘
```

---

## 5. Key Principles

### ✅ Fail Fast
- Errors detected immediately at origin
- Network partitions checked BEFORE calls
- No silent failures

### ✅ Explicit Error Propagation
- Every layer re-raises exceptions (after recording metrics)
- `yield from` ensures exceptions propagate
- No error swallowing

### ✅ Retry & Backoff
- **Database**: 3 retries with exponential backoff
- **Services**: Configurable retries (default: 3)
- **Queue consumers**: Exponential backoff after 5 failures

### ✅ Circuit Breakers
- **Service calls**: Open after 5 failures, fail fast
- **Queue consumers**: Back off 1s → 2s → 4s → ... → 60s
- **Auto-recovery**: Reset on first success

### ✅ Comprehensive Metrics
- **Dependency errors**: Track which dependency failed
- **Request errors**: Track which service had errors
- **Workload errors**: Track overall system health
- **Circuit breaker**: Track when circuits open/close

### ✅ Graceful Degradation
- **Cache failures**: Fall back to database (don't fail request)
- **Queue publish failures**: Log warning but continue
- **Other failures**: Fail request but don't crash simulation

---

## 6. Before vs After Our Fix

### Before Fix (Bug)
```
DB fails (Layer 1)
  ↓
Exception to Layer 3
  ↓
Exception caught at line 806
  ↓
Error metrics recorded
  ↓
Exception SWALLOWED (no raise)
  ↓
Function returns normally
  ↓
Caller thinks: SUCCESS ✗
  ↓
Queue message DELETED (data loss!)
  ↓
service.requests{status="success"} ✗ WRONG
```

### After Fix (Correct)
```
DB fails (Layer 1)
  ↓
Exception to Layer 3
  ↓
Exception caught at line 806
  ↓
Error metrics recorded
  ↓
Exception RE-RAISED (line 832) ✓
  ↓
Exception to Layer 4
  ↓
Caller knows: FAILURE ✓
  ↓
Queue message KEPT (will retry)
  ↓
service.requests{status="error"} ✓ CORRECT
```

---

## 7. Real-World Behavior Match

Our error handling now matches real-world production systems:

| Behavior | Real World | Our Simulation |
|----------|-----------|----------------|
| Fail fast on network partition | ✅ | ✅ |
| Retry with exponential backoff | ✅ | ✅ |
| Circuit breakers prevent cascading failures | ✅ | ✅ |
| Failed queue messages return for retry | ✅ | ✅ |
| Error metrics at every layer | ✅ | ✅ |
| Graceful degradation (cache) | ✅ | ✅ |
| No silent failures | ✅ | ✅ After fix |

---

## Date

December 15, 2025
