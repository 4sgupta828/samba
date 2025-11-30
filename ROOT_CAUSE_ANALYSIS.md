# Root Cause Analysis: Unhealthy Baselines

## Problem Statement

Datasets are being generated with unhealthy baselines where the system is already failing BEFORE fault injection. This defeats the purpose of training data for root cause analysis.

## Diagnosis Summary

After deep investigation, I've identified **MULTIPLE ROOT CAUSES** that compound to create unhealthy baselines:

### 1. **Workload Generator Connection Pool Saturation**

**Configuration:**
- Connection pool size: **50 connections** (src/workloads/generator.py:45)
- Request timeout: **30 seconds**
- Baseline RPS: **80 requests/second**

**Issue:**
When the workload generator tries to send 80 RPS through a 50-connection pool, if ANY requests are slow (>625ms average latency), the pool WILL saturate:

```
Required connections = RPS × Average_Latency
50 connections = 80 RPS × 0.625s

If Average_Latency > 0.625s → Pool saturates → Timeouts → Circuit breakers open
```

### 2. **External Service Latency (200ms)**

**Code Location:** src/topology/generator.py:296

```python
if edge_type == 'sync_external':
    latency = 200.0  # External APIs are slow (200ms)
```

**Issue:**
- External services are hardcoded to 200ms latency
- Random topology generation can connect external services to frontend paths
- Example: `gateway -> svc_3 -> svc_4 -> ext_0 (200ms)`
- This creates a CONSTANT slow path even in healthy baseline

**Impact Calculation:**
```
If even 50% of requests hit the external service path:
- 40 RPS × 0.200s = 8 connections occupied by ext_0 calls
- Remaining: 42 connections for other 40 RPS
- But frontend (svc_3) makes multiple downstream calls per request
- This compounds latency and connection pool usage
```

### 3. **Circular Queue Dependencies**

**Observed Pattern** in data_20251127_114143/ep_0:
```
svc_1 -> queue_0 (async_produce)
queue_0 -> svc_1 (async_consume)
```

**Issue:**
- svc_1 both produces to AND consumes from queue_0
- This creates a **circular dependency**
- If queue_0 backs up, svc_1 can't consume fast enough
- This causes cascading failures from simulation start

### 4. **Circuit Breaker Configuration Too Sensitive**

**Configuration:** src/workloads/generator.py:69

```python
CircuitBreaker(
    failure_threshold=0.7,   # Opens at 70% failure rate
    window_size=50,          # Tracks last 50 requests
    open_duration=15.0,      # Stays open for 15s
)
```

**Issue:**
- Only needs 35 failures out of 50 requests to open
- Once open, ALL requests are rejected for 15 seconds
- This amplifies any temporary slowness into a complete outage
- During baseline (0-180s), if ext_0 causes even brief congestion → circuit opens → cascading failures

### 5. **Frontend Service Calling All Downstream Services**

**Topology Pattern:**
```
svc_3 (frontend) calls:
  -> db_1 (2ms)
  -> cache_0 (1ms)
  -> svc_0 (5ms)
  -> svc_2 (5ms)
  -> svc_1 (5ms)
  -> svc_4 (5ms) -> ext_0 (200ms)
```

**Issue:**
- With `processing_pipeline=None`, services use legacy logic (just timeout, no actual calls)
- **BUT** the workload generator itself may be experiencing slowness
- If the gateway is slow to route requests, this backs up the entire system

## Why Post-Fault Periods Show "Improvement"

This paradoxical behavior happens when:

1. **Baseline is saturated**: Connection pool full, circuit breakers open, high failure rate
2. **Fault is injected**: queue_consumer_slowdown on queue_0
3. **Unintended effect**: Less load on svc_1 (consumer slows down)
4. **Result**: Reduced overall system load → circuit breakers close → success rate improves!

This is like "curing" a traffic jam by closing lanes - reduces demand but doesn't fix the real problem.

## The Real Problem: **Workload Generator Cannot Handle Its Own Load**

The core issue is:
```
Connection Pool (50) < Baseline RPS (80) × Minimum Latency (>0.625s)
```

With external services at 200ms, the connection pool is **fundamentally undersized** for the workload.

## Solutions (in priority order)

### Solution 1: **Increase Connection Pool Size** ⭐ RECOMMENDED

**File:** `src/workloads/generator.py:45`

**Change:**
```python
# OLD
self.connection_pool_size = 50

# NEW
self.connection_pool_size = 200  # 2.5x the peak RPS to handle bursts
```

**Rationale:**
- Baseline: 80 RPS × 0.2s (max ext latency) = 16 connections minimum
- Peak: 200 RPS × 0.2s = 40 connections minimum
- Add 5x buffer for variance and bursts: 200 connections
- This ensures pool never saturates during healthy operation

### Solution 2: **Reduce External Service Latency**

**File:** `src/topology/generator.py:296`

**Change:**
```python
# OLD
if edge_type == 'sync_external':
    latency = 200.0  # External APIs are slow (200ms)

# NEW
if edge_type == 'sync_external':
    latency = 50.0  # External APIs are moderately slow (50ms)
```

**Rationale:**
- 200ms is extremely slow for typical external APIs
- 50ms is still realistic but won't saturate the connection pool
- Real-world P95 for external APIs is usually 50-100ms, not 200ms

### Solution 3: **Fix Circular Queue Dependencies**

**File:** `src/topology/generator.py:136-144`

**Change:**
```python
# D. Async Message Queues
# Pattern: Producer → Queue → Consumer
if queues and services and len(services) >= 2:
    for queue in queues:
        producer = self.rng.choice(services)
        # FIXED: Ensure consumer is different from ALL producers
        potential_consumers = [s for s in services if s != producer]

        # ADDED: Track producers to prevent circular dependencies
        producers = [producer]

        if potential_consumers:
            # FIXED: Filter out any producers
            valid_consumers = [s for s in potential_consumers if s not in producers]
            if valid_consumers:
                consumer = self.rng.choice(valid_consumers)
                # Producer publishes to queue
                self._add_edge(G, producer, queue, 'async_produce')
                # Consumer reads from queue
                self._add_edge(G, queue, consumer, 'async_consume')
```

### Solution 4: **Relax Circuit Breaker Thresholds**

**File:** `src/workloads/generator.py:69`

**Change:**
```python
# OLD
CircuitBreaker(
    failure_threshold=0.7,   # Opens at 70% failure rate
    window_size=50,
    open_duration=15.0,
)

# NEW
CircuitBreaker(
    failure_threshold=0.9,    # Opens at 90% failure rate (more tolerant)
    window_size=100,          # Larger window for smoother decisions
    open_duration=10.0,       # Shorter duration to recover faster
)
```

**Rationale:**
- 70% threshold is too aggressive - opens too easily
- 90% threshold allows temporary bursts without triggering
- Larger window (100) smooths out variance
- Shorter open duration (10s) allows faster recovery

### Solution 5: **Add Warmup Period**

**File:** `generate_dataset.py:297`

**Change:**
```python
# OLD
start_time = int(cfg.duration * 0.2)  # 20% through episode

# NEW
start_time = max(30, int(cfg.duration * 0.2))  # At least 30s warmup, or 20%
```

**Rationale:**
- System needs time to stabilize after cold start
- Connection pools, caches, queues need to reach steady state
- 30s minimum warmup ensures baseline metrics are stable

## Recommended Implementation Plan

1. **Immediate Fix** (blocks all dataset generation):
   - Increase connection pool to 200
   - Reduce external service latency to 50ms

2. **Short-term Fix** (improves quality):
   - Fix circular queue dependencies
   - Relax circuit breaker thresholds

3. **Long-term Improvement** (robustness):
   - Add warmup period
   - Add pre-simulation topology validation
   - Monitor connection pool utilization during generation

## Validation

After fixes, regenerate data_20251127_114143/ep_0 and verify:
- Baseline success rate > 80%
- Post-fault success rate < baseline (degradation)
- No circuit breaker rejections during baseline
- Connection pool utilization < 70% during baseline

## Metrics to Monitor

Add these to dataset generation output:
```
[Baseline Health Metrics]
  Connection pool utilization: 45% (avg), 72% (p95)
  Request success rate: 95%
  Circuit breaker opens: 0
  Average latency: 45ms
```

This will help catch unhealthy baselines during generation, not just validation.
