# Final RCA Design: First Principles + Proper Pod Integration

## Core Insight

The RCA failure has TWO root causes:
1. **Guilt ratio dominates scoring** (allows victims to rank #1)
2. **Pod-level degradation is invisible** (aggregation dilutes signal)

Both must be fixed together.

## The Right Formula

### Service Health Score (Integrated)

```python
def calculate_integrated_health_score(node):
    """
    Calculate health score integrating service-level AND pod-level signals.
    Properly weights by coverage to avoid over/under-weighting outliers.
    """

    # 1. Service-level health (from aggregated metrics)
    service_score = analyze_service_metrics(node)

    # 2. Pod-level health (coverage-weighted)
    if node has pods:
        pods = analyze_all_pods(node)

        # Identify degraded pods (threshold = 2.0)
        degraded = [p for p in pods if p.self_score >= 2.0]

        if degraded:
            coverage = len(degraded) / len(pods)  # Fraction affected
            avg_severity = mean(p.self_score for p in degraded)

            # Coverage-weighted score
            pod_score = avg_severity * coverage

            # Examples:
            #   1/3 pods at 10x → 10 * 0.33 = 3.33
            #   3/3 pods at 5x  → 5 * 1.0 = 5.0
            #   2/10 pods at 8x → 8 * 0.2 = 1.6
        else:
            pod_score = 0.0
    else:
        pod_score = 0.0

    # 3. Use whichever signal is stronger
    integrated_score = max(service_score, pod_score)

    return integrated_score, {
        'service_score': service_score,
        'pod_score': pod_score,
        'pod_coverage': coverage if pod_score > 0 else 0.0
    }
```

**Why this works**:
- Service-wide faults → High `service_score` → Detected ✓
- Pod-level faults → High `pod_score` (weighted by coverage) → Detected ✓
- Single outlier pod → Low coverage → Lower `pod_score` → Appropriately weighted ✓
- Healthy service → Both scores low → Filtered out ✓

### Final RCA Scoring Formula

```python
def score_root_cause_candidate(node):
    """
    Score a potential root cause using logical stages, not arbitrary weights.
    """

    # PHASE 1: Integrated health check
    integrated_score, metadata = calculate_integrated_health_score(node)

    # HARD FILTER: Must have internal degradation
    if integrated_score < 2.0:
        return None  # Cannot be root cause - no internal symptoms

    # PHASE 2: Trace validation (distinguish root cause from victim)
    trace_info = analyze_traces(node)

    if trace_info.self_time_degradation > 2.0:
        # AUTHORITATIVE: Internal processing is slow
        is_authoritative = True
        trace_boost = 50
    elif (trace_info.total_time_degradation > 3.0 and
          trace_info.self_time_degradation < 1.5):
        # VICTIM: High total-time, normal self-time = waiting on deps
        return None  # Filter out victims
    else:
        is_authoritative = False
        trace_boost = 0

    # PHASE 3: Calculate base score (internal evidence = primary)
    base_score = integrated_score * 10  # 0-100 points

    if is_authoritative:
        base_score += trace_boost  # Strong confirmation

    # PHASE 4: Guilt ratio (external evidence = confirmatory)
    guilt_ratio = calculate_guilt_ratio(node)
    confirmation_bonus = guilt_ratio * 20  # 0-20 points (NOT 0-100!)

    # PHASE 5: Final score
    final_score = base_score + confirmation_bonus

    return {
        'node': node,
        'score': final_score,
        'integrated_score': integrated_score,
        'guilt_ratio': guilt_ratio,
        'is_authoritative': is_authoritative,
        'metadata': metadata
    }
```

## Comparison: Old vs New

### Old Formula (Broken)
```python
final_score = (
    guilt_ratio * 100 +     # 0-100 points - DOMINATES
    self_score * 5 +        # 0-50 points - service-level only
    trace_score * 2         # 0-20 points
)
```

**Problems**:
- Guilt dominates (100 points) even with `self_score=0`
- Pod-level faults invisible (only uses service-level `self_score`)
- Victims can score 80+ points

### New Formula (Fixed)
```python
# Step 1: Integrated health (service + pod, coverage-weighted)
integrated_score = max(service_score, avg_severity * coverage)

# Step 2: Hard filter
if integrated_score < 2.0:
    skip

# Step 3: Victim detection
if high_total_time and low_self_time:
    skip

# Step 4: Score
base_score = integrated_score * 10  # 0-100 points - PRIMARY
confirmation = guilt_ratio * 20      # 0-20 points - SECONDARY
final_score = base_score + confirmation
```

**Fixes**:
- Internal evidence (integrated_score) is primary
- Pod-level faults visible through coverage-weighted aggregation
- Guilt is confirmatory, not dominant
- Victims filtered out by trace analysis

## Expected Results

### Case 1: notification_service CPU saturation (service-wide)

**Before**:
```
notification_service:
  - service_score: 3.6, guilt: 0.0
  - final: 18 points → Rank #6 ✗

billing_service (victim):
  - service_score: 0.0, guilt: 0.8
  - final: 80 points → Rank #1 ✗
```

**After**:
```
notification_service:
  - integrated_score: 3.6 (service-wide, all pods affected)
  - base: 36, guilt: 0, final: 36 → Rank #1 ✓

billing_service (victim):
  - integrated_score: 0.0 (no internal symptoms at any level)
  - FILTERED OUT ✓
```

### Case 2: billing_service hot_shard (pod-level)

**Before**:
```
billing_service:
  - service_score: 0.0 (hidden by aggregation)
  - guilt: 0.8
  - final: 80 points → Rank #1 ✓ (correct by luck)
```

**After**:
```
billing_service:
  - service_score: 0.0
  - pod_score: 10.0 * 0.33 = 3.33 (1/3 pods degraded)
  - integrated_score: 3.33
  - base: 33, guilt: 16, final: 49 → Rank #1 ✓ (correct by design)
```

### Case 3: victim with outlier pod

**Scenario**: Service is victim (waiting on deps), but happens to have 1 noisy pod
```
victim_service:
  - service_score: 0.0
  - pod_score: 8.0 * 0.1 = 0.8 (1/10 pods slightly elevated)
  - integrated_score: 0.8
  - FILTERED OUT (< 2.0 threshold) ✓
```

**Key**: Coverage weighting prevents single outlier from triggering false positive.

## Implementation Changes

### File: `run_rca_batch.py`

**Add new function**:
```python
def calculate_integrated_health_score(self, node, baseline_data, current_data):
    """
    Calculate health score integrating service-level and pod-level signals.
    """
    # Service-level
    service_metrics_base = baseline_data.get(node, {})
    service_metrics_curr = current_data.get(node, {})
    service_health = self.self_analyzer.analyze(node, ..., service_metrics_base, service_metrics_curr)
    service_score = service_health.self_degradation_score

    # Pod-level
    pod_score = 0.0
    pod_metadata = {}

    if self.topology.nodes[node].get('type') == 'Service':
        # Find all pods for this service
        pod_ids = [n for n in self.topology.nodes
                  if self.topology.nodes[n].get('parent_service') == node]

        if pod_ids:
            degraded_pods = []
            for pod_id in pod_ids:
                pod_base = baseline_data.get(pod_id, {})
                pod_curr = current_data.get(pod_id, {})
                pod_health = self.self_analyzer.analyze(pod_id, ..., pod_base, pod_curr)

                if pod_health.self_degradation_score >= 2.0:
                    degraded_pods.append({
                        'id': pod_id,
                        'score': pod_health.self_degradation_score,
                        'symptoms': pod_health.symptoms
                    })

            if degraded_pods:
                coverage = len(degraded_pods) / len(pod_ids)
                avg_severity = sum(p['score'] for p in degraded_pods) / len(degraded_pods)
                pod_score = avg_severity * coverage

                pod_metadata = {
                    'coverage': coverage,
                    'avg_severity': avg_severity,
                    'degraded_count': len(degraded_pods),
                    'total_count': len(pod_ids)
                }

    # Integrate
    integrated_score = max(service_score, pod_score)

    return integrated_score, {
        'service_score': service_score,
        'pod_score': pod_score,
        **pod_metadata
    }
```

### File: `whitebox_rca.py`

**Modify lines 189-196**:
```python
# OLD:
final_score = (
    (guilt_ratio * 100.0) +
    (self_score * 5.0) +
    ...
)

# NEW:
# Calculate integrated score (service + pod, coverage-weighted)
integrated_score, metadata = self.calculate_integrated_health_score(node)

# Hard filter: Must have internal symptoms
if integrated_score < 2.0 and not is_trace_authoritative:
    continue

# Victim detection
if (trace_info.get('total_time_degradation', 1.0) > 3.0 and
    trace_info.get('self_time_degradation', 1.0) < 1.5):
    continue  # Filter out victims

# Score: Internal evidence primary, guilt confirmatory
base_score = integrated_score * 10  # 0-100

if is_trace_authoritative:
    base_score += 50

confirmation = guilt_ratio * 20  # 0-20 (reduced from 100)

final_score = base_score + confirmation
```

## Key Principles (Final)

1. **Internal evidence is mandatory**: `integrated_score >= 2.0` OR authoritative traces
2. **Coverage-weighted pod aggregation**: `avg_severity × coverage` (not max, not mean)
3. **Victim detection is mandatory**: Filter out high total-time + low self-time
4. **Guilt is confirmatory**: 0-20 points, not 0-100 points
5. **Logical stages, not arbitrary weights**: Filter → Validate → Score

## Testing Validation

After implementing these changes:

**Expected outcomes**:
- billing_service false positives: 17/18 → 0/18
- Top-1 accuracy: 6% (1/18) → >70% (13/18)
- Top-5 accuracy: 67% (12/18) → >90% (16/18)

**Critical tests**:
1. Service-wide faults still detected (notification_service case)
2. Pod-level faults still detected (billing_service hot_shard case)
3. Victims filtered out (all 16 false positive cases)
4. Single outlier pods don't trigger false positives (coverage weighting works)

## Summary

This is **not patching** - it's a fundamental redesign:

**Before**: Weighted sum with arbitrary weights, pod data ignored
**After**: Logical stages with coverage-weighted integration

The fix addresses BOTH root causes:
1. Guilt ratio dominance → Fixed by making it confirmatory (20 points vs 100)
2. Pod aggregation → Fixed by coverage-weighted integration

**The formula is now principled, not empirical.**
