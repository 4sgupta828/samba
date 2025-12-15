# Network Partition Handling - Complete Verification

## Summary

This document verifies that network partition faults are correctly handled for **ALL** synchronous and asynchronous call types in the system.

## Call Types Verified

### 1. ✅ Service → Database (Sync)

**Location**: `pod.py:_execute_db_logic` (line 1133)

```python
# Check for network partition BEFORE making database call
self._check_network_partition(db.id)
```

**Behavior**:
- ✅ Checks partition before each DB call
- ✅ Retries 3 times with exponential backoff (configurable)
- ✅ Raises exception after final failure
- ✅ Exception propagates to `_handle_request_internal`
- ✅ Exception re-raised at line 832 (our fix)
- ✅ Request fails properly

**Example Fault**:
```
Network partition: analytics_service <-> analytics_db
Result: All DB calls fail, service requests marked as ERROR
```

---

### 2. ✅ Service → Cache (Sync)

**Location**: `pod.py:_execute_cache_logic` (line 955)

```python
# Check for network partition BEFORE making cache call
self._check_network_partition(cache.id)
```

**Behavior**:
- ✅ Checks partition before cache operations
- ✅ On failure: Treats as cache MISS (not fatal!)
- ✅ Falls back to database (cache-aside pattern)
- ⚠️ Does NOT fail the request (by design)
- ✅ Records cache error metrics

**Example Fault**:
```
Network partition: auth_service <-> auth_cache
Result: Cache misses, falls back to database, request succeeds (correct!)
```

**Why cache failures don't fail requests**:
- Cache is a performance optimization, not required for correctness
- Cache-aside pattern: always fall back to authoritative source (DB)
- Prevents cascading failures from cache outages

---

### 3. ✅ Service → Service (Sync)

**Location**: `pod.py:_execute_service_calls` (line 1228)
**Uses**: `call_dependency_with_propagation` from `ServicePropagationMixin`

```python
yield from self.call_dependency_with_propagation(
    dep_name=conn_name,
    dep_type='service',
    call_func=make_service_call,
    span=span,
    source_id=self.id,
    target_id=conn_target.id  # ← Used for partition check
)
```

**Propagation Logic** (`service_propagation_mixin.py:207`):
```python
# Check for network partition FIRST (before circuit breaker)
if source_id and target_id:
    try:
        check_network_partition(source_id, target_id, self._emit_log)
    except Exception as e:
        # Add span event and re-raise
        raise
```

**Behavior**:
- ✅ Checks partition BEFORE circuit breaker
- ✅ Checks partition BEFORE retries
- ✅ Raises `NetworkPartitionError` immediately
- ✅ Exception wrapped in `DependencyFailureException`
- ✅ Circuit breaker records failure
- ✅ Exception propagates to caller
- ✅ Request fails properly

**Example Fault**:
```
Network partition: gateway <-> billing_service
Result: Gateway's requests to billing fail, gateway returns 500 to client
```

---

### 4. ✅ Service → External API (Sync)

**Location**: `pod.py:_execute_external_calls` (line 1534)
**Uses**: `call_dependency_with_propagation` from `ServicePropagationMixin`

```python
yield from self.call_dependency_with_propagation(
    dep_name=conn_name,
    dep_type='external',
    call_func=make_external_call,
    span=span,
    source_id=self.id,
    target_id=conn_target.id  # ← Used for partition check
)
```

**Behavior**: Same as service-to-service (uses same propagation logic)
- ✅ Checks partition before call
- ✅ Raises exception immediately
- ✅ Circuit breaker tracks failures
- ✅ Request fails properly

**Example Fault**:
```
Network partition: payment_service <-> stripe_api
Result: Payment processing fails, user sees payment error
```

---

### 5. ✅ Service → Queue (Async - Publish)

**Location**: `pod.py:_execute_queue_publish` (line 1601)

```python
# Check for network partition BEFORE publishing to queue
self._check_network_partition(queue.id)
```

**Behavior**:
- ✅ Checks partition before publish
- ✅ Raises exception if partition exists
- ✅ Request fails (message not sent)
- ⚠️ Logged as warning, doesn't fail request (by design for async)

**Example Fault**:
```
Network partition: order_service <-> fulfillment_queue
Result: Orders not sent to queue, but order creation may succeed
```

---

### 6. ✅ Queue → Service (Async - Consume)

**Location**: `pod.py:_consume_from_queue` (line 455)

```python
# Check for network partition BEFORE consuming from queue
self._check_network_partition(queue.id)
```

**Behavior** (with our new circuit breaker fix):
- ✅ Checks partition before receiving messages
- ✅ Consumer backs off after 5 consecutive failures
- ✅ Exponential backoff (1s → 2s → 4s → ... → 60s)
- ✅ Auto-recovers when partition heals
- ✅ Prevents infinite retry loops

**Example Fault**:
```
Network partition: analytics_service <-> events_queue
Result: Consumer can't receive messages, backs off, queue depth increases
```

---

## Network Partition Check Implementation

**Function**: `src/components/network.py:check_network_partition`

```python
def check_network_partition(source_id: str, target_id: str, emit_log_func=None):
    """
    Check if network partition blocks communication.

    Raises:
        NetworkPartitionError: If partition blocks this communication
    """
    from src.simulation import Simulation
    network_link = Simulation.get_global_network()

    if network_link and network_link.partition_rules:
        for (partition_source, partition_target) in network_link.partition_rules:
            # Check if source and target match partition rule
            source_matches = (source_id == partition_source or
                            partition_source in source_id or
                            source_id.startswith(f"pod_{partition_source}"))

            target_matches = (target_id == partition_target or
                            partition_target in target_id or
                            target_id.startswith(f"pod_{partition_target}"))

            if source_matches and target_matches:
                error_msg = f"Network partition blocks communication from {source_id} to {target_id}"
                if emit_log_func:
                    emit_log_func("ERROR", error_msg)
                raise NetworkPartitionError(error_msg)
```

**Key Features**:
- ✅ Checks global partition rules
- ✅ Matches source and target (supports pod prefixes)
- ✅ Raises `NetworkPartitionError` when blocked
- ✅ Logs error message with context

---

## Exception Flow for All Call Types

### Sync Calls (Service, Database, External API)

```
1. Component calls dependency
   ↓
2. check_network_partition(source, target)
   ↓ [if partition exists]
3. raise NetworkPartitionError
   ↓
4. Caught by retry logic (DB) OR propagation mixin (service/external)
   ↓
5. Retries (if configured)
   ↓ [all retries failed]
6. Exception propagates to _execute_*_logic
   ↓
7. Exception propagates to _execute_processing_pipeline
   ↓
8. Exception propagates to _handle_request_internal
   ↓
9. Exception caught at line 806
   ↓
10. Error metrics recorded
   ↓
11. Exception RE-RAISED at line 832 ← OUR FIX
   ↓
12. Exception propagates to caller
   ↓
13. Request FAILS (not silent success)
```

### Async Calls (Queue Consume)

```
1. Consumer tries to receive message from queue
   ↓
2. check_network_partition(pod, queue)
   ↓ [if partition exists]
3. raise NetworkPartitionError
   ↓
4. Caught by _consume_from_queue (line 481)
   ↓
5. Increment consecutive_failures counter
   ↓
6. [if failures >= 5]
   ↓
7. Circuit breaker: exponential backoff
   ↓
8. Wait 1s, 2s, 4s, 8s, ... (max 60s)
   ↓
9. Periodically retry
   ↓ [when partition heals]
10. First success resets circuit breaker
   ↓
11. Normal processing resumes
```

---

## Test Scenarios

### Scenario 1: Service-to-Database Partition

```yaml
Fault: network_partition
  source: analytics_service
  target: analytics_db
  bidirectional: true

Expected Behavior:
  - DB calls fail after 3 retries (~300ms)
  - service.analytics_service.dependency.requests{status="error"} ← Tracked
  - service.analytics_service.requests{status="error"} ← OUR FIX
  - HTTP requests fail with 500
  - Queue processing backs off after 5 failures
  - CPU usage drops (circuit breaker working)
```

### Scenario 2: Service-to-Service Partition

```yaml
Fault: network_partition
  source: gateway
  target: billing_service
  bidirectional: true

Expected Behavior:
  - Gateway calls to billing fail immediately (no retries by default)
  - Circuit breaker opens after 5 failures
  - Future requests rejected by circuit breaker (fail fast)
  - service.gateway.dependency.requests{status="error"} ← Tracked
  - Gateway returns 503 to clients
  - Circuit breaker auto-recovers when partition heals
```

### Scenario 3: Service-to-External-API Partition

```yaml
Fault: network_partition
  source: payment_service
  target: stripe_api
  bidirectional: false  # Unidirectional from service

Expected Behavior:
  - Payment API calls fail
  - Circuit breaker opens
  - Payments fail gracefully
  - Error metrics tracked
  - Customers see payment error
```

### Scenario 4: Queue Consumer Partition

```yaml
Fault: network_partition
  source: analytics_service
  target: events_queue
  bidirectional: true

Expected Behavior:
  - Consumer can't receive messages
  - After 5 failures, circuit breaker opens
  - Backoff: 1s → 2s → 4s → 8s → 16s → 32s → 60s (max)
  - Queue depth increases (messages pile up)
  - When partition heals, consumer resumes
  - Backlog is processed
```

---

## Verification Checklist

| Call Type | Partition Check | Exception Raised | Retries | Circuit Breaker | Request Fails | Metrics Tracked |
|-----------|----------------|------------------|---------|-----------------|---------------|-----------------|
| Service → Database | ✅ Line 1133 | ✅ | ✅ 3x | ❌ (uses retry) | ✅ | ✅ |
| Service → Cache | ✅ Line 955 | ✅ | ❌ | ❌ | ⚠️ Fallback | ✅ |
| Service → Service | ✅ Mixin 207 | ✅ | ✅ Configurable | ✅ | ✅ | ✅ |
| Service → External | ✅ Mixin 207 | ✅ | ✅ Configurable | ✅ | ✅ | ✅ |
| Queue → Service | ✅ Line 455 | ✅ | ✅ Backoff | ✅ | ✅ | ✅ |
| Service → Queue | ✅ Line 1601 | ✅ | ❌ | ❌ | ⚠️ Warning | ✅ |

**Legend**:
- ✅ = Implemented correctly
- ❌ = Not applicable (by design)
- ⚠️ = Special behavior (not a failure)

---

## Summary

### ✅ ALL synchronous call types properly handle network partitions:

1. **Database calls**: Retry 3x, then fail request
2. **Cache calls**: Fall back to DB (cache-aside pattern)
3. **Service calls**: Circuit breaker + retry, then fail request
4. **External API calls**: Circuit breaker + retry, then fail request
5. **Queue consume**: Circuit breaker with exponential backoff
6. **Queue publish**: Fail with warning (async nature)

### ✅ Key Improvements from Our Fix:

1. **Exception propagation** (line 832): Requests now fail instead of silent success
2. **Circuit breaker for queues** (line 440-486): Prevents infinite retry loops
3. **Exponential backoff**: 1s → 2s → 4s → ... → 60s max
4. **Auto-recovery**: Circuit breaker resets when calls succeed

### ✅ Real-World Behavior Match:

- Fails fast when dependencies unavailable
- Circuit breakers prevent cascading failures
- Exponential backoff reduces load on failed systems
- Auto-recovery when systems heal
- Proper error visibility (no silent failures)

---

## Date

December 15, 2025
