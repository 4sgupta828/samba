# Whitebox RCA Bug Fix Summary

## Problem
The whitebox RCA was **not ranking tenant_service (the ground truth) at position 1** in `data/batch_run/data_20251215_015616/ep_0`, even though fault propagation and effects existed.

## Root Cause Analysis

### The Issue
Metrics in the simulation data have multiple dimensions (e.g., `request_type`: GET, PUT, POST, DELETE). The aggregation code was treating each `(timestamp, request_type)` tuple as a separate sample and **averaging** them, which diluted error counts during the fault period.

### Example at t=75s:
```
Before fix (averaging):
- GET: 32 errors
- PUT: 1 error
- POST: 1 error
→ Mean: (32 + 1 + 1) / 3 = 11.3 errors ❌

After fix (summing):
- Total: 32 + 1 + 1 = 34 errors ✅
```

### Impact
- **Before fix:** Error rate appeared to DECREASE during fault (33 → 15.8 = 0.48x)
- **After fix:** Error rate correctly INCREASES during fault (33 → 46 = 1.39x)

This caused `tenant_service` to appear healthy and not rank at position 1.

## The Fix

**Location:** `run_rca_batch.py:236-283`

**Changes:**
1. **Group metrics by timestamp first** before extracting values
2. **Classify metrics** as counters (errors, requests) vs gauges (latency, CPU)
3. **Aggregate appropriately:**
   - **Counters:** SUM across dimensions (e.g., total errors across all request types)
   - **Gauges:** AVERAGE across dimensions (e.g., average latency across request types)

**Code snippet:**
```python
# Determine if this is a counter or gauge metric
is_counter = any(keyword in signal_name for keyword in [
    'error', 'request', 'rps', 'count', 'total'
])

# Group by timestamp
timestamp_groups = metric_rows.groupby('sim_time')
values_list = []

for timestamp, time_group in timestamp_groups:
    time_values = []
    # ... extract values ...

    # Aggregate values at this timestamp
    if time_values:
        if is_counter:
            aggregated_value = sum(time_values)  # Sum for counters
        else:
            aggregated_value = np.mean(time_values)  # Average for gauges
        values_list.append(aggregated_value)
```

## Results

### Before Fix:
```
Top Result: billing_service (Score: 16.02)
Ground Truth: tenant_service
Status: ❌ NOT FOUND in top 5
```

### After Fix:
```
Top Result: tenant_service (Score: 101.9)
Ground Truth: tenant_service
Status: ✅ SUCCESS - EXACT MATCH (Rank 1)

Score breakdown:
- Integrated score: 10.0
- Pod contribution: 10.0 (coverage: 100%, pattern: Service-wide degradation 4/4 pods)
- Symptoms: Error rate increased 4599.0%
```

## Verification

Tested with `debug_aggregation.py`:
```
Before fix:
  Baseline mean: 33.0000
  Current mean:  15.8244  ← Wrong!
  Increase: 0.48x

After fix:
  Baseline mean: 33.0000
  Current mean:  45.9896  ← Correct!
  Increase: 1.39x
```

## Impact on Other Metrics

This fix affects ALL metrics that have dimensional breakdowns:
- `service.X.errors` (by request_type)
- `service.X.requests` (by request_type)
- `service.X.latency` (by request_type)
- Any metric with dimensional labels

Counter metrics now correctly SUM, while gauge metrics correctly AVERAGE across dimensions.

## Conclusion

The bug was caused by incorrect aggregation of multi-dimensional metrics. The fix ensures that counter metrics are summed and gauge metrics are averaged across dimensions at each timestamp, which correctly reflects the true system behavior during faults.
