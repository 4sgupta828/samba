# The Deeper Issue: Pod-Level Faults Are Invisible

## Critical Discovery

I checked the ONE case where billing_service IS the root cause (data_20251212_143703):

```
Fault type: hot_shard (traffic skew to one pod)

Service-level (what RCA sees):
  - self_score: 0.0
  - symptoms: []

Pod-level (pod_forensics):
  - pod_billing_service_2: score=2.59, symptoms=['thread_pool_active +104%', 'internal_error_rate +63%']
  - pod_billing_service_0: score=0.0, healthy
  - pod_billing_service_1: score=0.0, healthy
```

**The Problem**: When 1 of 3 pods is degraded, service-level aggregation hides it:
- Aggregated CPU: (1.0 + 1.0 + 2.0) / 3 = 1.33x (below detection threshold)
- Service-level self_score: 0.0 (no symptoms detected)

**Current behavior**: RCA ranks billing_service #1 based purely on guilt_ratio (0.8 × 100 = 80 points)

**Why it "works"**: By luck, guilt_ratio correctly identifies billing_service when it IS the root cause.

**Why it fails**: Guilt_ratio ALSO identifies billing_service in 16 other cases when it's NOT the root cause.

## The Real Architectural Problems

### Problem #1: Service-Level Aggregation Hides Pod-Level Faults

**Location**: `run_rca_batch.py:267-323` (aggregate_pods_to_services)

```python
# Aggregates all pod metrics by concatenating arrays
all_values = []
for pod_id in pod_ids:
    if metric_name in pod_data[pod_id]:
        all_values.extend(pod_data[pod_id][metric_name])  # Concat all samples

service_metrics[metric_name] = np.array(all_values)
```

**The Issue**:
- Healthy pod: CPU = [1.0, 1.0, 1.0, ...] (100 samples)
- Degraded pod: CPU = [5.0, 5.0, 5.0, ...] (100 samples)
- Aggregated: CPU = [1.0, 1.0, ..., 5.0, 5.0, ...] (200 samples)
- Mean: 3.0 (appears as moderate load, not severe)

**Result**:
- A hot-shard fault (5x CPU on 1 pod) becomes 1.67x at service level
- Falls below detection threshold (2x)
- Appears healthy

### Problem #2: Pod Forensics Exists But Isn't Used in Scoring

**Location**: `run_rca_batch.py:560-615` (analyze_pod_forensics)

The code DOES analyze pods individually and stores results in `pod_forensics`:
```python
pod_forensics = {
    'degraded_pods': [...],  # Has the actual fault data!
    'healthy_pods': [...],
    'pattern': 'Outlier pods detected (1/3 degraded)'
}
```

But this is ONLY used for display (`story`), NOT for scoring!

**Location**: `whitebox_rca.py:189-196` (final_score calculation)

```python
final_score = (
    (guilt_ratio * 100.0) +
    (self_score * 5.0) +      # ← Service-level only, misses pod faults!
    ...
)
```

No use of pod_forensics data in scoring.

### Problem #3: Two Types of Root Causes, One Broken Algorithm

**Type A: Service-Wide Faults** (CPU saturation, memory leak affecting all pods)
- Shows up in service-level metrics ✓
- Self-symptoms detected ✓
- Current RCA should work ✓

**Type B: Pod-Level Faults** (hot shard, single pod crash, network partition)
- Hidden in service-level aggregation ✗
- Self-symptoms NOT detected ✗
- Current RCA relies on guilt_ratio ✗

**Result**:
- Type A faults: RCA fails because guilt_ratio dominates self-symptoms
- Type B faults: RCA "works" by accident (guilt_ratio is the only signal)

## Why the Current Algorithm is Accidentally Right Sometimes

### Case: billing_service hot_shard (Type B)
```
Service-level: self_score=0.0 (fault hidden)
Guilt: 0.8 (callers see degradation)
Final score: 80 (from guilt alone)
Result: Ranked #1 ✓ (correct by luck)
```

### Case: notification_service CPU saturation (Type A)
```
Service-level: self_score=3.6 (fault visible)
Guilt: 0.0 (early in cascade, no blame yet)
Final score: 18 (from self alone)

billing_service (victim):
  Service-level: self_score=0.0
  Guilt: 0.8
  Final score: 80

Result: billing_service ranked #1 ✗ (wrong, victim dominates)
```

**The pattern**: Guilt_ratio works for Type B faults, but creates false positives everywhere else.

## The Real First Principles Solution

### Principle #1: Check Pod-Level Health First

```python
def has_internal_fault(node):
    # Check service-level symptoms
    if self_score > threshold:
        return True, 'service-wide'

    # Check pod-level symptoms
    pod_forensics = analyze_pods(node)
    if pod_forensics.degraded_count > 0:
        return True, 'pod-level'

    # Check authoritative traces
    if trace_info.is_authoritative:
        return True, 'trace-confirmed'

    return False, None
```

### Principle #2: Integrate Pod Forensics into Scoring

```python
# Calculate effective self-score
if node has pods:
    service_self_score = analyze_service_metrics(node)
    pod_self_score = max(pod.self_score for pod in pods)  # Worst pod

    effective_self_score = max(service_self_score, pod_self_score)
else:
    effective_self_score = service_self_score

# Use effective_self_score in final score
if effective_self_score < threshold:
    skip  # No internal fault at any level
```

### Principle #3: Guilt is Still Secondary

Even with pod forensics, guilt should not dominate:

```python
base_score = effective_self_score * 10  # 0-100 (primary)
confirmation = guilt_ratio * 20          # 0-20 (secondary)
final_score = base_score + confirmation
```

**Rationale**:
- Type A faults: High service_self_score → high base_score → correct
- Type B faults: High pod_self_score → high base_score → correct
- Victims: Low effective_self_score → filtered out → correct

## The Fixed Architecture

```python
def analyze_incident_v3(...):
    candidates = []

    for node in topology.nodes:
        # PHASE 1: Multi-level self-health check
        service_self_score = analyze_service_metrics(node)
        pod_forensics = analyze_pod_metrics(node) if has_pods(node) else None

        # Effective self-score: worst of service or any pod
        if pod_forensics:
            pod_self_score = max(pod.self_score for pod in pod_forensics.degraded_pods) if pod_forensics.degraded_pods else 0.0
            effective_self_score = max(service_self_score, pod_self_score)
        else:
            effective_self_score = service_self_score

        # PHASE 2: Trace validation
        trace_info = analyze_traces(node)
        is_authoritative = trace_info.self_time_degradation > 2.0
        is_victim = (trace_info.total_time > 3.0 and
                    trace_info.self_time < 1.5)

        # HARD FILTER: Must have internal fault
        if effective_self_score < 2.0 and not is_authoritative:
            continue  # No internal fault detected

        # HARD FILTER: Eliminate victims
        if is_victim:
            continue

        # PHASE 3: Scoring (balanced)
        base_score = effective_self_score * 10  # Primary signal

        if is_authoritative:
            base_score += 50

        guilt_ratio = calculate_guilt(node)
        confirmation = guilt_ratio * 20  # Secondary signal

        final_score = base_score + confirmation

        candidates.append({
            'node': node,
            'score': final_score,
            'effective_self_score': effective_self_score,
            'service_self_score': service_self_score,
            'pod_self_score': pod_self_score if pod_forensics else None,
            ...
        })

    return sorted(candidates, key=lambda x: x['score'], reverse=True)
```

## Expected Results After Fix

### Type A Fault: notification_service CPU saturation
```
notification_service:
  - effective_self_score: 3.6 (service-wide)
  - base_score: 36
  - guilt: 0.0 → +0
  - final: 36 → Rank #1 ✓

billing_service (victim):
  - effective_self_score: 0.0
  - FILTERED OUT ✓
```

### Type B Fault: billing_service hot_shard
```
billing_service:
  - service_self_score: 0.0
  - pod_self_score: 2.59 (pod_2 degraded)
  - effective_self_score: 2.59
  - base_score: 25.9
  - guilt: 0.8 → +16
  - final: 41.9 → Rank #1 ✓

Other services:
  - effective_self_score: 0.0
  - FILTERED OUT ✓
```

## Summary

**The bug is NOT just weight tuning** - it's a fundamental architectural issue:

1. **Pod-level aggregation hides faults** (hot shards become invisible)
2. **Pod forensics data exists but isn't used in scoring**
3. **Guilt_ratio compensates for missing pod data** (works by accident)
4. **Creates 16 false positives** when victims also have high guilt

**The fix requires**:
1. Integrate pod_forensics into self-health scoring
2. Use `max(service_score, pod_score)` as effective self-score
3. Make effective_self_score the primary signal (not guilt)
4. Reduce guilt_ratio to confirmatory role

**This is not patching - it's fixing the missing integration between pod-level and service-level analysis.**
