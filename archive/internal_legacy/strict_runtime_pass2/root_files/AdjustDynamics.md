# Dynamics Framework Fix Plan

## Problem Statement

Fault propagation is not working correctly. When `db_0` has a `slow_queries` fault:
- DB latency increases correctly (17ms → 93ms, 5x) ✓
- DB CPU barely increases (5% → 7%, only 40%) ✗
- Upstream services see latency increase but not error/CPU/memory impact ✗
- Request rates don't decrease (no backpressure) ✗
- Errors are extremely sparse (1-2 per component over 600s) ✗

## Root Cause Analysis

### Issue 1: System Over-Provisioned for Load
- **Current workload**: base_rps=50, actual ~20-50 rps
- **DB connection pool**: 100 capacity
- **Thread pools**: 50 capacity
- **Little's Law**: 20 rps × 0.100s = 2 concurrent connections needed
- **Result**: Only 2% of DB pool used, resources never exhaust

### Issue 2: Dynamics Engine Disconnected from Simulation
- Dynamics engine calculates CPU from `concurrent_requests = throughput × latency`
- But `cpu_from_concurrent_coef=0.5` is too weak
- Doesn't model:
  - Thread contention when many blocked threads
  - Context switching overhead
  - Connection pool exhaustion impact
  - Lock contention

### Issue 3: Error Thresholds Too High
- `error_latency_threshold: 200ms` (DB at 93ms, below threshold)
- `error_cpu_threshold: 80%` (DB at 7%, far below threshold)
- `error_base: 0.001` (0.1% baseline)
- Result: Error rate stays near baseline, circuit breakers never trip

### Issue 4: No Timeout-Based Error Propagation
- Requests don't timeout even when slow
- Services wait indefinitely for slow downstream
- No natural error propagation through timeouts

### Issue 5: Missing Upstream Impact Modeling
- When service calls slow DB, service's threads block
- Blocking threads should increase:
  - Service CPU (context switching, lock contention)
  - Service memory (blocked requests accumulate)
  - Service error rate (timeouts, pool exhaustion)
- Currently: latency propagates but nothing else

## Implementation Plan

### Phase 1: Create Natural Bottlenecks (HIGHEST PRIORITY)

Make resources actually exhaust under fault conditions.

**1.1 Increase Workload Intensity**
```python
# generate_dataset.py:32
def create_dynamic_workload(nx_graph, base_rps: int = 300, peak_rps: int = 800):
    # Was: base_rps=50, peak_rps=200
    # New: 6x increase to stress resources
```

**Goal**: 300 rps × 0.100s = 30 concurrent connections → will exhaust 25-connection pool

**1.2 Reduce DB Connection Pool**
```yaml
# config/simulation_config.yaml
database:
  resources:
    connection_pool_capacity: 25  # Was: 100
    # At 300 rps with 100ms latency = 30 concurrent → EXHAUSTION
```

**1.3 Reduce Compute DB Connection Pools**
```yaml
# config/simulation_config.yaml
compute:
  resources:
    db_connection_pool_capacity: 5  # Was: 10-20
    # Forces faster exhaustion when DB is slow
```

**Expected Result**: Connection pool exhaustion → "no connections available" errors → natural propagation

### Phase 2: Fix Error Thresholds and Dynamics

**2.1 Lower Error Thresholds**
```python
# src/dynamics/metrics_dynamics_engine.py:48-52
error_latency_threshold: 100.0  # Was: 200.0
error_cpu_threshold: 50.0       # Was: 80.0
error_base: 0.01                # Was: 0.001 (increase to 1% baseline)
```

**2.2 Add CPU Scaling from Resource Contention**
```python
# src/dynamics/metrics_dynamics_engine.py:252
def _compute_cpu_derivative(self) -> float:
    """
    CPU increases from:
    1. Concurrent requests (baseline)
    2. Queue depth (thread pool saturation)
    3. Resource contention (many blocked threads)
    """
    # Baseline CPU from concurrent requests
    target_cpu_from_load = (
        self.config.cpu_min +
        self.config.cpu_from_concurrent_coef * self.concurrent_requests +
        self.config.cpu_from_connections_coef * self.active_connections
    )

    # NEW: Queue depth causes CPU spike (context switching, thrashing)
    queue_contention_cpu = (self.queue_depth / 10.0) * 10.0  # 1 queued = +1% CPU

    # NEW: High concurrency relative to capacity causes contention
    # Many blocked threads → context switching overhead
    if hasattr(self, 'thread_pool_size') and self.thread_pool_size > 0:
        thread_saturation = self.concurrent_requests / self.thread_pool_size
        # Exponential increase when saturated
        contention_cpu = 20.0 * max(0, thread_saturation - 0.7) ** 2
    else:
        contention_cpu = 0.0

    target_cpu = target_cpu_from_load + queue_contention_cpu + contention_cpu

    # Apply CPU multiplier from deployments
    target_cpu *= self.cpu_multiplier

    # Apply FLOOR fault
    if self.fault_cpu_floor_percent is not None:
        target_cpu = max(target_cpu, self.fault_cpu_floor_percent)

    tau = 3.0
    return (target_cpu - self.cpu_percent) / tau
```

**2.3 Make Dynamics Read from SimPy State**
```python
# src/components/database.py:133
def _update_dynamics_loop(self):
    while True:
        yield self.env.timeout(1.0)

        queries_delta = self.queries_processed - last_queries_count
        last_queries_count = self.queries_processed

        # Read ACTUAL SimPy resource state
        active_connections = self.connection_pool.count
        queue_depth = len(self.connection_pool.queue)

        # NEW: Pass thread pool info if available
        self.dynamics.thread_pool_size = getattr(self, 'cpu_resource', None) and self.cpu_resource.capacity or 50

        self.dynamics.update(
            dt=1.0,
            external_throughput=queries_delta,
            active_connections=active_connections,
            queue_depth=queue_depth
        )
```

### Phase 3: Add Timeout-Based Error Propagation

**3.1 Add Database Query Timeout**
```python
# src/components/database.py:238
def handle_query(self, should_trace: bool = False, parent_span_context = None):
    start_time = self.env.now
    timeout = 500  # 500ms timeout for DB queries

    try:
        # Race between query completion and timeout
        result = yield self.env.process(self._handle_query_internal()) | self.env.timeout(timeout)

        if result is None:  # Timeout occurred
            self._emit_log("ERROR", f"Query timeout after {timeout}ms")
            raise TimeoutError(f"Database query timeout after {timeout}ms")

    except TimeoutError:
        # Record timeout as error
        self.query_errors_counter.add(1, {"error_type": "timeout", "component.id": self.id})
        raise

    end_time = self.env.now
    self.query_latency.record((end_time - start_time) * 1000, {"component.id": self.id})
```

**3.2 Add Service-to-DB Call Timeout**
```python
# src/components/compute.py - when calling DB
def _call_database(self, request_type: str, span):
    timeout = 1000  # 1000ms timeout for service->DB

    try:
        result = yield self.env.process(self.db.handle_query(...)) | self.env.timeout(timeout)

        if result is None:  # Timeout
            self._emit_log("ERROR", f"DB call timeout after {timeout}ms")
            raise TimeoutError(f"DB call timeout")
    except TimeoutError:
        # This error propagates to service, then to gateway
        raise
```

**Expected Result**: Slow DB → timeouts → errors propagate naturally upstream

### Phase 4: Add Upstream CPU/Memory Impact

**4.1 Track Blocked Time as CPU Usage**
```python
# src/components/service.py or compute.py
def _execute_request_logic(self, request_type: str, span):
    request_start = self.env.now

    # Call downstream (blocks if slow)
    yield from self._call_downstream_dependencies(request_type, span)

    request_duration = self.env.now - request_start

    # NEW: Long request duration = high CPU usage
    # Blocked threads consume CPU through context switching
    if request_duration > 0.5:  # If request took >500ms
        # Accumulate "blocked CPU" - models context switching overhead
        blocked_cpu_cost = (request_duration - 0.05) * 0.5  # 50% CPU cost while blocked
        self.cpu_usage_accumulator += blocked_cpu_cost
```

**4.2 Increase Memory for Blocked Requests**
```python
# In dynamics engine memory calculation:
def _compute_memory_derivative(self) -> float:
    # Base memory from concurrent requests
    memory_from_concurrent = self.config.memory_per_request_mb * self.concurrent_requests

    # NEW: Queue depth increases memory (requests accumulating)
    memory_from_queue = self.queue_depth * self.config.memory_per_request_mb * 2  # 2x for queued

    target_memory = self.config.memory_base + memory_from_concurrent + memory_from_queue

    return (target_memory - self.memory_percent) / self.config.memory_tau
```

### Phase 5: Validate Circuit Breakers Work

**5.1 Verify Circuit Breaker Logic**
```python
# src/components/service.py:181 - Already exists, should work once errors increase
if self.use_dynamics and self.dynamics:
    if self.dynamics.get_error_rate() > 0.1:  # 10% threshold
        self._emit_log("ERROR", f"Circuit breaker open due to high error rate")
        raise Exception(f"Circuit breaker open for {self.service_name}")
```

**5.2 Lower CB Threshold if Needed**
```python
# If 10% is too high:
if self.dynamics.get_error_rate() > 0.05:  # 5% threshold
```

## Expected Outcomes After Fixes

### Before (Current):
- DB latency: 17ms → 93ms
- DB CPU: 5% → 7%
- DB connections: 0 → 3.8 (out of 100)
- svc_0 latency: 175ms → 350ms
- svc_0 errors: 1 error total
- Gateway errors: constant at 1

### After (Expected):
- DB latency: 17ms → 93ms (same)
- DB CPU: 10% → 65% (from connection pool exhaustion + contention)
- DB connections: 5 → 25 (EXHAUSTED at capacity)
- DB errors: 0.1% → 15% (timeouts, connection exhaustion)
- svc_0 latency: 175ms → 500ms+ (timeouts)
- svc_0 errors: 0.1% → 20% (DB timeouts propagate)
- svc_0 CPU: 15% → 45% (blocked threads cause contention)
- svc_0 memory: 200MB → 350MB (requests queue up)
- svc_3 errors: 1% → 25% (svc_0 errors propagate)
- Gateway errors: 1% → 30% (cascading failure)
- Circuit breakers: Open at multiple levels (svc_0→DB, svc_3→svc_0)

## Implementation Order

1. ✅ **Phase 1.1**: Increase workload (generate_dataset.py) - ADJUSTED: 200 rps base (was 300)
2. ✅ **Phase 1.2**: Reduce DB connection pool (config) - 25 connections
3. ✅ **Phase 2.1**: Lower error thresholds (metrics_dynamics_engine.py)
4. ✅ **Phase 2.2**: Fix CPU calculation with contention (metrics_dynamics_engine.py)
5. ✅ **Phase 3**: Timeout handling - ADJUSTED: 1.5s DB, 0.5s cache (was 0.5s, 0.2s)
6. ✅ **Workload Connection Pool**: Increased to 200 (was 50) to match concurrency

## ⚠️ Lessons Learned from Initial Implementation

### What Went Wrong:
After initial implementation (300 rps, 0.5s timeouts, 50 connection pool), we observed:
- **1-20% success rate** (catastrophic!)
- **Circuit breaker opened immediately** at t=5s (before fault!)
- **96% request rejection rate**
- **Resources barely used** (0-6% of capacity)

### Root Causes:
1. **Workload generator under-provisioned**: 300 rps × 0.5s latency = 150 concurrent, but only 50 connections → constant rejections
2. **Timeouts too aggressive**: 500ms timeout with 400-700ms normal latency → constant timeouts
3. **Circuit breaker too sensitive**: 70% failure threshold met immediately → all requests rejected

### Corrected Configuration:
```yaml
# Balanced for fault propagation WITHOUT breaking normal operations
workload: 200 rps base (4x increase from 50, sustainable)
workload connection pool: 200 (allows 200 rps × 1s = 200 concurrent)
DB timeout: 1.5s (allows 1s normal + margin, catches 2-3s slowdowns)
Cache timeout: 0.5s (allows normal ops, catches slowdowns)
```

### Key Insight:
**Fault propagation requires stress, not breakage!** The goal is to create enough load that resources exhaust during faults, not to make the system fail even during healthy periods.

## Testing

After each phase, run:
```bash
python generate_dataset.py --num-episodes 1 --duration 600
```

Check:
```python
# Verify resource exhaustion
jq 'select(.name == "db.connections.active")' data/latest/ep_0/metrics.jsonl | jq '.value' | sort -n | tail -5

# Verify errors increased
jq 'select(.name | contains("error"))' data/latest/ep_0/metrics.jsonl | jq '{time: .labels."sim.time", name: .name, value: .value}'

# Verify CPU increased
jq 'select(.name == "db.cpu.utilization") | {time: .labels."sim.time", value: .value}' data/latest/ep_0/metrics.jsonl | tail -10
```

## Success Criteria

- [ ] DB connection pool reaches 90%+ utilization during fault
- [ ] DB error rate increases from 0.1% to 10%+
- [ ] DB CPU increases from ~5% to 50%+
- [ ] Service error rates increase proportionally to downstream errors
- [ ] Circuit breakers trip at least once during severe faults
- [ ] Gateway sees cascading errors from downstream failures
- [ ] Memory increases when requests queue up
- [ ] Request rate decreases due to backpressure (timeouts, rejections)
