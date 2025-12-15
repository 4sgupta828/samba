# Two-Level RCA Architecture Implementation

## Summary

Implemented a clean two-level architecture where pod metrics are aggregated to service level BEFORE analysis, enabling proper blame attribution for service-to-external-service edges (like `user_management_service -> user_db`).

## Architecture Changes

### Before: Mixed Pod/Service Analysis
```
Problem:
- Topology has service-level edges: user_management_service -> user_db
- Metrics exist at pod level: pod_user_management_service_X has dependency_latency
- Analysis couldn't match edges to metrics
- Result: blamed_by always empty for database/cache failures
```

### After: Two-Level Analysis
```
LEVEL 1: Service-Level RCA
1. Aggregate pod metrics → service metrics
   - user_management_service inherits all pod_user_management_service_X metrics
   - Now has: dependency_latency, dependency_error_rate, outbound_rps
2. Analyze topology at service level
   - user_management_service -> user_db edge CAN be analyzed
   - Blame attribution works!

LEVEL 2: Pod-Level Forensics (for root cause service)
1. Identify which pods are degraded
2. Determine pattern:
   - "All pods degraded uniformly" → Service-wide issue
   - "Outlier pods detected (1/3)" → Pod-specific issue
   - "No pods degraded" → Victim of dependency
```

## Implementation

### 1. Service-Level Metric Aggregation

**File:** `run_rca_batch.py:266-322`

```python
def aggregate_pods_to_services(pod_data):
    """
    For each service with pods, combine all pod metrics.
    Standalone nodes (ExternalService, etc.) copy their metrics as-is.
    """
    service_to_pods = defaultdict(list)

    # Group pods by parent service
    for node_id in pod_data.keys():
        parent_service = topology.nodes[node_id].get('parent_service')
        if parent_service:
            service_to_pods[parent_service].append(node_id)
        else:
            service_data[node_id] = pod_data[node_id]  # Standalone

    # Aggregate all pod metrics to service
    for service_name, pod_ids in service_to_pods.items():
        all_values = []
        for pod_id in pod_ids:
            all_values.extend(pod_data[pod_id][metric_name])
        service_data[service_name][metric_name] = np.array(all_values)
```

### 2. Pod-Level Forensics

**File:** `run_rca_batch.py:351-446`

```python
def perform_pod_forensics(service_name, topology, baseline_pods, current_pods):
    """
    Analyze individual pods within a service to identify:
    - Which pods are degraded?
    - Is it uniform or outlier-driven?
    """
    service_pods = find_pods_for_service(service_name)

    for pod in service_pods:
        analyze self-degradation score

    pattern = determine_pattern(degraded_pods, total_pods)
    return {
        'pattern': "Outlier pods detected (1/3 degraded)",
        'degraded_pods': [...],
        'healthy_pods': [...]
    }
```

### 3. Updated Process Flow

**File:** `run_rca_batch.py:446-483`

```python
def process_episode():
    # Load pod-level data
    baseline_pods, current_pods = adapter.get_data_windows()

    # LEVEL 1: Aggregate to service level
    baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
    current_services = adapter.aggregate_pods_to_services(current_pods)

    # Run RCA at service level
    service_results = engine.analyze_incident(baseline_services, current_services)

    # LEVEL 2: Pod forensics for top service
    if service_results:
        top_service = service_results[0]['node']
        pod_forensics = perform_pod_forensics(top_service, ...)
        service_results[0]['pod_forensics'] = pod_forensics
```

## Results

### Performance Comparison

| Version | Accuracy | blamed_by populated? | Notes |
|---------|----------|---------------------|-------|
| v4.0 (before) | 11/18 (61.1%) | ❌ Usually empty | Edge metrics missing |
| v4.0 (two-level) | 10/18 (55.6%) | ✅ Working! | -1 episode, but blame works |

### What Improved ✅

**Blame Attribution Now Works:**
```json
// Before:
{
  "node": "user_db",
  "blamed_by": []  // ❌ Empty
}

// After:
{
  "node": "analytics_db",
  "blamed_by": ["analytics_service", "reporting_service"]  // ✅ Populated!
}
```

**Pod Forensics Added:**
```json
{
  "node": "billing_service",
  "pod_forensics": {
    "pattern": "Outlier pods detected (1/3 degraded)",
    "degraded_pods": [
      {
        "pod_id": "pod_billing_service_2",
        "self_score": 2.6,
        "symptoms": ["thread_pool_active increased", "internal_error_rate increased"]
      }
    ]
  }
}
```

### What Regressed ❌

**Accuracy dropped by 1 episode (11 → 10)**

Possible causes:
1. **Metric aggregation smoothing**: Combining all pod metrics may dilute signal from individual degraded pods
2. **Temporal/trace analysis changes**: May not handle aggregated metrics the same way
3. **Different edge analysis**: More edges are now analyzable, changing blame distribution

## Example Output

```
Ground Truth: billing_service
Top Result:   billing_service (Score: 80.8)
   Score breakdown:
     - Guilt ratio: 0.8              ← Now non-zero!
     - Self score: 0.0
     - Temporal: 0.0
     - Trace: 0.0
     - Blamed by: ['subscription_service']  ← Now populated!

   Pod Forensics:
     - Pattern: Outlier pods detected (1/3 degraded)
     - Pods: 1/3 degraded
     - Top degraded pods:
       * pod_billing_service_2: score=2.6 (thread_pool_active increased, internal_error_rate increased)
```

## Benefits

1. **Proper Blame Attribution**: Services can now blame external dependencies (databases, caches)
2. **Pod-Level Insights**: Can identify outlier pods vs service-wide issues
3. **Clean Architecture**: Clear separation between service-level RCA and pod-level forensics
4. **Consistent Analysis**: All edges analyzed at same level (service-level)

## Issues Remaining

### 1. External Services Without Metrics

**Problem**: user_db, email_service, etc. have NO metrics
- Can receive blame votes
- But can't show self-degradation symptoms
- Rely entirely on blame + trace evidence

**Impact**: Makes it hard to distinguish between:
- Database actually slow
- Caller having issues

### 2. Accuracy Regression

**-1 episode (61.1% → 55.6%)**

Need to investigate:
- Which episode did we lose?
- Was it due to metric aggregation smoothing?
- Or blame redistribution?

### 3. High Error Rates Not Triggering Blame

Example: `user_management_service` has 62.79% error rate calling user_db, but doesn't blame it.

Possible causes:
- Disambiguator needs callee metrics to confirm fault
- Without user_db metrics, can't confirm it's the callee's fault
- May need "high error rate = blame callee" heuristic even without callee metrics

## Next Steps

1. **Investigate accuracy regression**
   - Compare before/after results episode by episode
   - Identify which episode we lost and why

2. **Improve external service handling**
   - Add heuristic: "High error rate (>50%) = blame callee" even without callee metrics
   - Special scoring for ExternalService nodes based purely on blame

3. **Tune metric aggregation**
   - Consider using p99 instead of combining all values
   - Or keep track of "worst pod" metrics separately

4. **Add test coverage**
   - Unit tests for metric aggregation
   - Verify pod forensics logic

## Conclusion

The two-level architecture is architecturally correct and enables proper blame attribution, but needs tuning to maintain accuracy. The framework is now in place for:
- Proper service-level RCA
- Pod-level forensics
- Future improvements to external service handling

**Recommendation**: Keep the architecture, but investigate the -1 episode regression and tune the disambiguator for external services without metrics.
