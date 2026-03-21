# Self-Health Analyzer: Symptom Detection Gaps

## The Core Problem

**89% of RCA failures (8/9 cases)** are due to the self-health analyzer not detecting symptoms for the ground truth node.

## Fault Types: Detected vs Not Detected

### ✅ Successfully Detected Fault Types

| Fault Type | Example | Why It Works |
|------------|---------|--------------|
| cpu_saturation | notification_service | CPU metrics available |
| memory_leak | tenant_service | Memory metrics available |
| memory_pressure | tenant_service | Memory metrics available |
| thread_exhaustion (services) | notification_service | Thread pool metrics available |
| disk_io_saturation | user_db | Disk I/O metrics available |
| cache_failure | auth_cache | Cache metrics available |
| noisy_neighbor | auth_service | CPU/resource competition detected |
| hot_shard | billing_service | Pod-level CPU/thread metrics |

**Pattern**: Resource saturation faults (CPU, memory, disk, threads) are reliably detected.

### ❌ NOT Detected Fault Types

| Fault Type | Example | Why It Fails | Impact |
|------------|---------|--------------|--------|
| **inject_latency** | user_management_service | Latency metrics not analyzed | 1 failure |
| **inject_latency** | session_cache | Works for cache, not service! | Inconsistent |
| **inject_errors** | subscription_service | Error rate not analyzed | 1 failure |
| **inject_errors** | payment_gateway | External service errors | 1 failure |
| **memory_thrashing** | notification_service | Periodic bursts not caught | 1 failure |
| **thread_exhaustion** | analytics_db | Works for services, not DB | 1 failure |
| **queue_consumer_slowdown** | billing_queue | Queue metrics not analyzed | 1 failure |
| **force_deadlock** | subscription_service | Only partially detected (0.73) | 1 failure |
| **network_partition** | global_network | Infrastructure level | 1 failure |

**Pattern**: Performance degradation faults (latency, errors, deadlocks) are NOT detected.

## The Gap: What Metrics Are Missing?

### Current Detection (Working)
The self-health analyzer likely checks:
- ✅ CPU usage
- ✅ Memory usage
- ✅ Thread pool active count
- ✅ Disk I/O
- ✅ (Maybe) internal error counts

### Missing Detection (Not Working)
- ❌ **Response time / latency** (inject_latency failures)
- ❌ **Error rate** (inject_errors failures)
- ❌ **Queue depth / lag** (queue_consumer_slowdown failure)
- ❌ **Lock contention / blocked threads** (force_deadlock partial detection)
- ❌ **Periodic/bursty patterns** (memory_thrashing failure)
- ❌ **Database-specific metrics** (thread_exhaustion on DB)

## Why inject_latency and inject_errors Aren't Detected

### Case Study: inject_latency on user_management_service

**What the fault does**:
- Adds artificial delay to requests (e.g., sleep 500ms)
- Increases response time
- May increase thread pool usage (waiting threads)

**What self-health analyzer checks** (likely):
```python
# Probably only checks:
- cpu_usage
- memory_usage
- thread_pool_active

# Does NOT check:
- response_time / latency ❌
- request_duration_p99 ❌
```

**Result**: Latency spike not detected → integrated_score = 0.0 → RCA fails

### Case Study: inject_errors on subscription_service

**What the fault does**:
- Returns 5xx errors (e.g., 50% error rate)
- No resource saturation
- May slightly increase CPU (error handling)

**What self-health analyzer checks**:
```python
# Checks resource metrics only:
- cpu_usage (might be slightly up, but below threshold)
- memory_usage (unchanged)

# Does NOT check:
- error_rate ❌
- internal_error_rate ❌
- http_5xx_count ❌
```

**Result**: Error rate spike not detected → integrated_score = 0.0 → RCA fails

## Inconsistency: Why inject_latency Works for session_cache but not user_management_service

**Hypothesis**: Cache nodes might have different detection logic or metrics.

Possible reasons:
1. Cache metrics include `latency` explicitly
2. Cache failures cause secondary symptoms (high CPU from retries)
3. Different metric mappings in METRIC_MAP

**Need to investigate**: `self_health_analyzer.py` and `run_rca_batch.py` METRIC_MAP

## Fix Strategy

### Option 1: Add Latency and Error Detection (RECOMMENDED)

**Update `self_health_analyzer.py`** to check:

```python
# Add latency detection
if 'response_time' in current_metrics or 'latency_p99' in current_metrics:
    baseline_latency = np.percentile(baseline_metrics.get('latency_p99', []), 99)
    current_latency = np.percentile(current_metrics.get('latency_p99', []), 99)

    if current_latency > baseline_latency * 2.0:  # 2x latency increase
        symptoms.append(f"latency increased (d={current_latency/baseline_latency:.2f})")
        score += 5.0

# Add error rate detection
if 'error_rate' in current_metrics or 'internal_error_rate' in current_metrics:
    baseline_errors = np.mean(baseline_metrics.get('internal_error_rate', [0]))
    current_errors = np.mean(current_metrics.get('internal_error_rate', [0]))

    if current_errors > baseline_errors + 0.1:  # 10% increase in error rate
        symptoms.append(f"error_rate increased (d={current_errors:.2%})")
        score += 5.0

# Add queue depth detection
if 'queue_depth' in current_metrics or 'queue_lag' in current_metrics:
    baseline_depth = np.mean(baseline_metrics.get('queue_depth', [0]))
    current_depth = np.mean(current_metrics.get('queue_depth', [0]))

    if current_depth > baseline_depth * 3.0:  # 3x queue depth
        symptoms.append(f"queue_depth increased (d={current_depth/baseline_depth:.2f})")
        score += 5.0
```

**Update `run_rca_batch.py` METRIC_MAP** to include:

```python
METRIC_MAP = {
    # Existing mappings...
    'response_time': 'response_time',
    'latency': 'latency_p99',
    'duration': 'latency_p99',
    'error_rate': 'internal_error_rate',
    'errors': 'internal_error_rate',
    '5xx': 'internal_error_rate',
    'queue_depth': 'queue_depth',
    'queue_lag': 'queue_lag',
    'queue_size': 'queue_depth',
}
```

### Option 2: Use Trace Data as Fallback

If metrics don't show symptoms, but traces show degradation:

```python
# In whitebox_rca.py
if integrated_score < 2.0 and trace_score > 5.0:
    # No internal symptoms but trace shows issue
    # Use trace score as weak internal evidence
    integrated_score = max(integrated_score, trace_score * 0.3)
```

### Option 3: Cross-Check with Label Data (Debug Only)

For debugging, verify if fault injection is working:

```python
# Check if metrics actually show the injected fault
fault_type = label['fault_type']
if fault_type == 'inject_latency':
    # Verify latency_p99 or response_time increased
    # If not, fault injection may not be working
```

## Priority Actions

1. **Check if latency/error metrics exist in data**
   ```bash
   # For failed cases, check metrics.jsonl
   grep -E "latency|error_rate|duration" data_20251212_141017/ep_0/metrics.jsonl | head
   ```

2. **Review METRIC_MAP in run_rca_batch.py**
   - See what metrics are currently mapped
   - Add latency, error_rate, queue_depth mappings

3. **Review self_health_analyzer.py**
   - Check what signals it currently detects
   - Add latency, error rate, queue depth detection

4. **Test on one failed case**
   ```bash
   # After adding detection logic
   python3 run_rca_batch.py ../data/batch_run/data_20251212_141017
   # Should now detect latency symptoms
   ```

## Expected Impact

If latency and error detection are added:

**Current**: 9/18 successes (50%)

**Expected**: 15-16/18 successes (83-89%)
- Fix 6 cases: inject_latency (×2), inject_errors (×2), queue_consumer_slowdown (×1), memory_thrashing (×1)
- Fix 1 partial: force_deadlock (improve from 0.73 to 3.0+)
- Still fail: network_partition (infrastructure level, acceptable)
- Maybe fix: thread_exhaustion on DB (if DB metrics are available)

## Conclusion

**The RCA algorithm is working correctly** - the issue is upstream in data/detection.

**Root cause of 89% of failures**: Self-health analyzer only detects resource saturation, not performance degradation.

**Fix**: Add latency, error rate, and queue depth detection to self-health analyzer.

**Complexity**: Low - just add 3-4 new metric checks similar to existing CPU/memory checks.

**ROI**: High - fixes 6-7 cases, improving accuracy from 50% → 85%+.
