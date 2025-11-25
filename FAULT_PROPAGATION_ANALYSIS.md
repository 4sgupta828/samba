# Fault Propagation Analysis & Enhancement Plan

## Executive Summary

After analyzing the current fault injection and propagation system, I've identified **7 critical gaps** that prevent proper fault propagation for GNN training. The core issue is that fault effects are **too localized** - they don't cascade through the dependency graph as they would in real distributed systems.

## Current State Analysis

### Data Analysis (data_20251124_182756)
- **Scenario**: External API (ext_0) with 30% error injection
- **Topology**: 35 nodes, 57 edges
- **Observation**: Errors ARE occurring at ext_0 and ARE caught by calling services (svc_0, svc_1)
- **Problem**: Calling services handle errors gracefully → **no propagation upstream**

### Log Evidence
```
ERROR: External API timeout on ext_0
WARN: External call to ext_ext_0 failed: External API Timeout (504): ext_0
  → component.id: pod_svc_1_2
```

The pod catches the error, logs a warning, **but continues processing successfully**. The request doesn't fail!

## 7 Critical Gaps

### Gap #1: Graceful Fault Tolerance (service.py:415-497)
**Location**: `src/components/service.py:_call_downstream_dependencies()`

**Current Behavior**:
```python
except Exception as e:
    self._emit_log("WARN", f"External call to {conn_name} failed: {e}")
    # Request continues successfully!
```

**Impact**:
- Calling service error_rate: **NOT INCREASED** ❌
- Calling service latency: **NOT INCREASED** ❌
- GNN cannot learn dependency relationship

**Fix Needed**:
- Probabilistic error propagation (e.g., 50% of dependency failures cause request failure)
- Add latency for retry attempts
- Add fallback degradation

---

### Gap #2: No Retry Amplification
**Missing**: Retry logic with exponential backoff

**Real-world behavior**:
- External API fails → Service retries 3x → 3x load amplification
- 10 calling services × 3 retries each → **30x load** on failing service
- This is a **critical signal** for GNNs to learn cascading failures

**Fix Needed**:
- Configurable retry policy (max_retries, backoff_multiplier)
- Track retry_count metric
- Amplify latency and error rate based on retries

---

### Gap #3: No Resource Contention Propagation
**Current**: Slow downstream calls don't exhaust resources in calling service

**Missing**:
- Thread pool exhaustion (requests block waiting for threads)
- Connection pool saturation (DB/cache connection leaks)
- Memory pressure from queued requests
- OOM crashes from holding too many pending requests

**Fix Needed**:
- Track thread_pool utilization
- When thread pool > 90% full → increase error rate
- When thread pool exhausted → reject new requests
- Add `thread_pool.wait_time` metric

---

### Gap #4: Limited Fault Injection Diversity
**Current Scenarios** (library.py):
- Level 4: Only 2 external API failure modes (latency, errors)

**Missing Fault Types**:
1. **Intermittent failures** (flapping: 5s good, 5s bad, repeat)
2. **Partial degradation** (some endpoints work, others don't)
3. **Rate limiting** (429 errors after threshold)
4. **Timeout cascades** (slow → slower → timeout)
5. **Memory leaks** in external deps
6. **Connection resets** (RST packets)
7. **DNS resolution failures**
8. **SSL/TLS handshake failures**

**Fix Needed**: Expand scenario library with 10+ new failure modes

---

### Gap #5: No Multi-Hop Cascades
**Current Propagation**:
```
ext_0 (error_rate=30%) → svc_0 (dependency.errors ++) → gateway (??)
```

**What GNN Needs to See**:
```
ext_0 (error_rate=30%)
  ↓
svc_0 (error_rate +9%, latency +200ms) ← retries + timeouts
  ↓
gateway (error_rate +2%, latency +50ms) ← cascading timeout
  ↓
Other services calling svc_0 (timeouts, circuit breaker trips)
```

**Fix Needed**:
- Propagate errors probabilistically (30% dep failure → 10% caller failure)
- Propagate latency additively (slow dep → caller waits → upstream sees 2x latency)
- Add timeout thresholds (if dep > 5s → timeout → error)

---

### Gap #6: No State-Based Degradation
**Current**: Failures are stateless - error rate applied uniformly every time

**Missing Stateful Behaviors**:
1. **Circuit Breaker Pattern**
   - Closed: All requests go through
   - Open: All requests fail-fast (no call to downstream)
   - Half-open: Test requests to recover

2. **Health Check Propagation**
   - Service marks dependency as unhealthy
   - Load balancer removes unhealthy instances
   - Traffic redistributes (causing overload elsewhere)

3. **Load Shedding**
   - When overloaded, reject requests early
   - Return 503 Service Unavailable

4. **Bulkhead Isolation**
   - Separate thread pools per dependency
   - One failing dep doesn't starve others

**Fix Needed**: Implement circuit breaker with state tracking

---

### Gap #7: Missing Metrics for GNN Training
**Current Metrics**:
- `dependency.requests` ✅
- `dependency.errors` ✅
- `dependency.duration` ✅

**Missing Metrics**:
- `dependency.retry_count` (how many retries per request)
- `dependency.circuit_breaker_state` (0=closed, 1=open, 0.5=half-open)
- `dependency.timeout_count` (requests that timed out)
- `thread_pool.utilization` (% of threads in use)
- `thread_pool.queue_depth` (requests waiting for thread)
- `thread_pool.rejection_count` (requests rejected due to exhaustion)
- `request.fallback_count` (requests using fallback logic)
- `request.degraded_mode` (boolean: is service in degraded mode)

**Fix Needed**: Add 8 new metrics for GNN feature engineering

---

## Solution Architecture

### 3-Layer Propagation Model

#### **Layer 1: Direct Impact** (at fault injection site)
- Component receives fault injection (e.g., ext_0.error_rate = 30%)
- Metrics directly reflect failure:
  - `error_rate` increases
  - `latency` increases (if inject_latency)
  - `throughput` may decrease

#### **Layer 2: Immediate Propagation** (1-hop neighbors)
Calling services (svc_0, svc_1) experience:

1. **Error Propagation** (probabilistic):
   - If dependency fails, 50% chance the calling request fails
   - Error type: `DependencyFailureException`
   - Metric: `service.svc_0.error_rate` increases proportionally

2. **Latency Propagation** (additive):
   - Retry attempts: +200ms per retry (exponential backoff)
   - Timeout waits: +5000ms (if dep doesn't respond)
   - Metric: `service.svc_0.latency_p50` increases

3. **Resource Contention**:
   - Blocked threads waiting for slow dependency
   - Metric: `thread_pool.utilization` increases
   - If > 90%: Start rejecting requests (503 errors)

4. **Circuit Breaker**:
   - After 5 failures: Circuit opens
   - Metric: `circuit_breaker_state` = 1 (open)
   - All subsequent requests fail-fast (no dep call)

#### **Layer 3: Cascading Effects** (2+ hops)
Upstream services (gateway, services calling svc_0) experience:

1. **Timeout Cascades**:
   - svc_0 is slow → gateway waits → gateway times out
   - Metric: `service.gateway.timeout_count` increases

2. **Load Redistribution**:
   - Load balancer marks svc_0 unhealthy
   - Traffic shifts to svc_1 → svc_1 overloaded
   - Metric: `service.svc_1.throughput` doubles

3. **Cache Stampede** (if cache fails):
   - Cache miss → all requests hit DB
   - DB overloaded → slow queries
   - Metric: `database.connection_pool.wait_time` spikes

4. **Queue Backlog** (if queue consumer slows):
   - Messages accumulate
   - Downstream services starved
   - Metric: `queue.depth` grows exponentially

---

## Implementation Plan

### Phase 1: Core Propagation Mechanisms
1. **Add Retry Logic** (`src/components/service.py`)
   - Exponential backoff (base 200ms, max 3 retries)
   - Track `retry_count` metric
   - Amplify latency by retry time

2. **Add Circuit Breaker** (new file: `src/resilience/circuit_breaker.py`)
   - Track failure rate over sliding window
   - Open circuit after 50% error rate for 10s
   - Half-open state for recovery testing

3. **Add Timeout Propagation** (`src/components/service.py`)
   - Configurable timeout per dependency type:
     - External: 5s
     - Database: 2s
     - Cache: 1s
     - Service: 3s
   - Timeout → Exception → Error propagates

4. **Add Error Propagation** (`src/components/service.py`)
   - Probabilistic failure (50% of dep failures → request failure)
   - Error types: `DependencyTimeout`, `DependencyError`, `CircuitBreakerOpen`

### Phase 2: Resource Contention
5. **Add Thread Pool Monitoring** (`src/components/pod.py`)
   - Track `thread_pool.utilization`
   - Track `thread_pool.queue_depth`
   - When > 90% util: Increase error rate by 20%
   - When exhausted: Reject requests (503)

6. **Add Connection Pool Pressure** (`src/components/pod.py`)
   - Track `connection_pool.wait_time`
   - When wait_time > 1s: Increase latency
   - When exhausted: Timeout errors

### Phase 3: Cascading Effects
7. **Add Cache Stampede Logic** (`src/components/storage.py`)
   - When cache fails → track `cache_miss_rate`
   - Amplify DB load by miss_rate
   - Add `db.thundering_herd` metric

8. **Add Queue Backlog Propagation** (`src/components/messaging.py`)
   - Track `queue.depth` over time
   - When depth > threshold: Consumer overload
   - Downstream services show increased error rate

### Phase 4: New Fault Modes
9. **Expand Scenario Library** (`src/scenarios/library.py`)
   - Add 10 new Level 4 scenarios:
     - Intermittent failures (flapping)
     - Partial degradation
     - Rate limiting (429)
     - Connection resets
     - DNS failures
     - SSL failures
     - Gradual degradation (gets worse over time)
     - Bursty failures (sudden spikes)
     - Correlated failures (multiple deps fail together)
     - Asymmetric failures (read works, write fails)

### Phase 5: Metrics Enhancement
10. **Add GNN-Critical Metrics** (`src/components/service.py`, `pod.py`)
    - `dependency.retry_count`
    - `dependency.circuit_breaker_state`
    - `dependency.timeout_count`
    - `thread_pool.utilization`
    - `thread_pool.rejection_count`
    - `request.fallback_count`
    - `request.degraded_mode`
    - `dependency.health_check_status`

---

## Validation Plan

### Test 1: Single-Hop Propagation
**Setup**: Inject 30% errors in ext_0

**Expected Results**:
- ext_0: `error_rate` = 30% ✅
- svc_0: `error_rate` increases by ~9% (30% of 30% of requests that call ext)
- svc_0: `dependency.errors` increases ✅ (already working)
- svc_0: `latency_p50` increases by ~600ms (3 retries × 200ms)
- svc_0: `circuit_breaker_state` = 1 after 10s

### Test 2: Multi-Hop Propagation
**Setup**: Inject 50% latency (+2s) in ext_0

**Expected Results**:
- ext_0: `latency_p50` = 2200ms ✅
- svc_0: `latency_p50` = 2500ms (ext latency + retries + processing)
- gateway: `latency_p50` = 2700ms (svc_0 latency + gateway processing)
- gateway: `timeout_count` > 0 (some requests exceed 3s timeout)

### Test 3: Resource Exhaustion
**Setup**: Inject extreme latency (+10s) in db_0

**Expected Results**:
- db_0: `latency_p50` = 10s ✅
- svc_0: `thread_pool.utilization` → 95% (threads blocked waiting for DB)
- svc_0: `error_rate` increases by 20% (thread pool rejections)
- svc_0: `request.rejection_count` > 0

### Test 4: Cache Stampede
**Setup**: Inject `cache_failure` on cache_0

**Expected Results**:
- cache_0: `operational` = DEGRADED ✅
- svc_0: `cache_miss_rate` = 100%
- db_0: `throughput` increases by 10x (all requests hit DB)
- db_0: `latency_p50` increases by 5x (overload)
- svc_0: `latency_p50` increases (waiting for slow DB)

---

## Expected GNN Training Improvement

### Before Enhancement
**Signal Quality**: ⭐⭐☆☆☆ (2/5)
- Only root cause node shows clear signal
- 1-hop neighbors have weak signal (dependency.errors)
- 2+ hops have NO signal

**GNN Accuracy**: ~60% (guessing based on direct connections)

### After Enhancement
**Signal Quality**: ⭐⭐⭐⭐⭐ (5/5)
- Root cause: Strong signal (error_rate, latency)
- 1-hop: Strong propagated signal (errors, latency, circuit_breaker, thread_pool)
- 2-hop: Moderate signal (timeout_count, latency)
- 3-hop: Weak but present signal (load redistribution, cache effects)

**GNN Accuracy**: ~85-90% (learned causal patterns)

---

## Implementation Priority

### HIGH PRIORITY (Do First)
1. **Retry Logic** - Most impactful for propagation
2. **Probabilistic Error Propagation** - Makes errors cascade
3. **Timeout Propagation** - Creates multi-hop cascades
4. **Circuit Breaker** - Adds state-based behavior

### MEDIUM PRIORITY (Do Second)
5. **Thread Pool Exhaustion** - Adds resource contention
6. **New Metrics** - Gives GNN better features
7. **Expand Scenarios** - More training diversity

### LOW PRIORITY (Nice to Have)
8. **Cache Stampede** - Complex interaction
9. **Queue Backlog** - Async propagation
10. **Load Redistribution** - Multi-instance behavior

---

## Next Steps

1. **Review this analysis** with the team
2. **Prioritize** which gaps to fix first
3. **Implement** Phase 1 (Core Propagation Mechanisms)
4. **Validate** with Test 1 & 2
5. **Generate new dataset** and compare GNN metrics
6. **Iterate** on remaining phases

---

## Questions for Discussion

1. **Retry Policy**: Should retry probability be configurable per scenario? (e.g., critical services retry more aggressively)
2. **Circuit Breaker Thresholds**: What error rate should trigger circuit opening? (default: 50% over 10s window)
3. **Timeout Values**: Should timeouts be topology-aware? (e.g., longer timeouts for deep call stacks)
4. **GNN Architecture**: Does your GNN use temporal features? (if yes, we should add rate-of-change metrics)
5. **Training Data Balance**: Do you need equal numbers of each failure type? (currently using curriculum distribution)

---

*Generated: 2025-11-24*
*Author: Claude (Sonnet 4.5)*
*Project: Samba - Spatiotemporal Data Factory for GNN Training*
