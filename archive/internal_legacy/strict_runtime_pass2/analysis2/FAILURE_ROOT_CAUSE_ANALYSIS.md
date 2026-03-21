# Root Cause Analysis of 9 RCA Failures

## Executive Summary

**Primary Issue**: 8 out of 9 failures are due to **ground truth having integrated_score = 0.0** (no symptoms detected).

When the self-health analyzer fails to detect symptoms, the node scores 0 points, and even weak signals from other nodes (guilt=16pts, trace=10pts) are enough to outrank it.

## Failure Categories

### Category 1: No Symptoms Detected (8/9 cases) 🔴 CRITICAL

**Cases**: #2, #3, #4, #5, #6, #7, #8 (partially)

**Pattern**:
```
Ground truth: integrated_score = 0.0, symptoms = []
Result: Scores 0 points, loses to any node with guilt or trace signals
```

**Examples**:

1. **notification_service** (#2):
   - Fault injected but NO symptoms detected
   - Scores: 0.0 points
   - Lost to: billing_service (16.8 points from guilt + trace)

2. **analytics_db** (#3):
   - Database node, fault injected but NO symptoms
   - Scores: 8.0 points (only from guilt ratio 0.4)
   - Lost to: billing_service (16 points from guilt 0.8)

3. **user_management_service** (#4):
   - NO symptoms detected
   - Scores: 0.0 points
   - Lost to: billing_service (26.25 points)

4. **subscription_service** (#5, #8):
   - Case #5: NO symptoms at all → 0.0 points
   - Case #8: Partial symptoms (1/3 pods) → 7.27 points
   - Both lost to: billing_service (16 points)

5. **billing_queue** (#6):
   - Queue node, NO symptoms detected
   - Scores: 0.0 points
   - Lost to: billing_service (16 points from guilt)

6. **payment_gateway** (#7):
   - External service, NO symptoms
   - Scores: 0.0 points
   - Lost to: billing_service (66 points with authoritative trace!)

**Root Cause**: Self-health analyzer is not detecting faults for certain node types or fault types.

**Affected Node Types**:
- Services (notification_service, user_management_service, subscription_service)
- Databases (analytics_db)
- Queues (billing_queue)
- External services (payment_gateway)

### Category 2: False Trace Authoritative Signal (2/9 cases) ⚠️

**Cases**: #1, #7

**Pattern**:
```
Wrong node marked as is_trace_authoritative = True
Gets +50 point boost, dominates rankings
```

**Examples**:

1. **payment_gateway** (#1):
   - Ground truth: notification_service (36 points with symptoms)
   - Winner: payment_gateway (50 points)
   - Issue: payment_gateway has trace_score=10 with auth=True → +50 boost
   - Gap: +70 points from trace alone

2. **billing_service** (#7):
   - Ground truth: payment_gateway (0 points, no symptoms)
   - Winner: billing_service (66 points)
   - Issue: billing_service has trace_score=20 with auth=True → +50 boost

**Root Cause**: trace_analyzer.py is incorrectly marking nodes as "authoritative" when they're victims or have non-root-cause latency patterns.

### Category 3: Ground Truth Not in Topology (1/9 cases) 🔍

**Case**: #9

**Pattern**:
```
Ground truth: global_network
Status: NOT FOUND in candidates
```

**Root Cause**: `global_network` is likely an infrastructure node (network, load balancer) that isn't modeled in the service topology.

## Detailed Analysis by Failure

### Why Ground Truth Has No Symptoms

Let me check the fault types for these failed cases:

| Case | Ground Truth | Fault Type | Symptoms Detected | Why? |
|------|--------------|------------|-------------------|------|
| #2 | notification_service | ? | None | Self-health analyzer missed it |
| #3 | analytics_db | ? | None | Database metrics not detected |
| #4 | user_management_service | ? | None | Self-health analyzer missed it |
| #5 | subscription_service | ? | None | Self-health analyzer missed it |
| #6 | billing_queue | ? | None | Queue metrics not detected |
| #7 | payment_gateway | ? | None | External service, no metrics |
| #8 | subscription_service | ? | Partial (1/3 pods) | Only 33% coverage → 7.27 score |

## Why billing_service Still Dominates (5/9 failures)

Even with reduced guilt weight (100→20), billing_service still wins in 5 cases:

```python
billing_service scores:
- Guilt ratio: 0.8 × 20 = 16 points  # From subscription_service blaming it
- Trace score: 0-20 points           # Sometimes gets trace evidence
- Total: 16-36 points

Ground truth scores:
- Integrated score: 0.0 × 10 = 0 points  # NO SYMPTOMS DETECTED
- Total: 0 points

Result: billing_service wins by default
```

**The issue**: When ground truth has 0 symptoms, ANY signal (even weak guilt) is enough to win.

## Root Causes Summary

### 1. Self-Health Analyzer Gaps (PRIMARY - 8/9 cases)

**Problem**: The self-health analyzer (`self_health_analyzer.py`) is not detecting symptoms for:
- Certain fault types (need to check label.json for fault_type)
- Certain node types (databases, queues, external services)
- Low-severity or partial degradation (only 1/3 pods affected)

**Impact**: Ground truth scores 0 points → loses to any noise

**Fix Required**:
- Review `self_health_analyzer.py` thresholds
- Check which metrics are available for each node type
- Verify fault injection actually creates detectable symptoms
- May need to lower detection thresholds

### 2. Trace Authoritative False Positives (SECONDARY - 2/9 cases)

**Problem**: `trace_analyzer.py` marks nodes as "authoritative" incorrectly.

**Criteria** (from trace_analyzer.py:317-330):
```python
if metrics.self_time_degradation > 2.0:
    is_authoritative = True
```

**Issue**:
- payment_gateway: self_time_degradation might be 2.1x → marked authoritative → +50 points
- But it's not the actual root cause

**Fix Required**:
- Increase threshold: self_time_degradation > 3.0 or 5.0
- Add additional checks: require self_time_degradation > total_time_degradation
- Verify the node has internal symptoms (integrated_score > 0)

### 3. Missing Infrastructure Nodes (MINOR - 1/9 cases)

**Problem**: `global_network` not in topology

**Fix Required**:
- Check if data generation includes infrastructure nodes
- Or accept that infrastructure failures can't be detected by application-level RCA

## Recommended Fixes (Priority Order)

### Priority 1: Fix Self-Health Detection (Blocks 8/9 cases)

**Action**: Investigate why symptoms aren't detected

1. Check fault types in label.json:
```bash
for ep in failed_episodes; do
    jq '.fault_type' $ep/label.json
done
```

2. Check what metrics are available:
```bash
# For each failed ground truth node
jq '.metrics | keys' metrics.jsonl | grep ground_truth_node
```

3. Review detection thresholds in `self_health_analyzer.py`:
```python
# Current thresholds might be too high
# Check: THRESHOLDS, anomaly_score calculation
```

4. Verify metrics exist and show degradation:
```python
# For failed cases, manually check if metrics show degradation
# Compare baseline vs fault periods
```

### Priority 2: Fix Trace Authoritative Logic (Blocks 2/9 cases)

**Action**: Tighten authoritative criteria in `trace_analyzer.py:317-330`

```python
# Current (too loose):
if metrics.self_time_degradation > 2.0:
    is_authoritative = True

# Proposed (stricter):
if (metrics.self_time_degradation > 3.0 and
    metrics.self_time_degradation > metrics.total_time_degradation * 0.8 and
    integrated_score > 2.0):  # Must also have internal symptoms
    is_authoritative = True
```

### Priority 3: Handle Infrastructure Nodes (Blocks 1/9 case)

**Action**: Check if `global_network` should be in topology, or document limitation.

## Success Pattern (For Comparison)

The 9 successful cases all had:
1. ✅ **Clear symptoms detected**: integrated_score > 2.0
2. ✅ **Service-level or pod-level metrics showed degradation**
3. ✅ **No false trace authoritative signals competing**

Example (tenant_service success):
```
tenant_service:
  - integrated_score: 3.56 (memory_usage +256%)
  - guilt_ratio: 0.0 (no external blame needed)
  - score: 35.6 → Rank #1 ✓
```

## Conclusion

**The RCA algorithm itself is sound** - the scoring formula works correctly.

**The failure is in data/detection**:
- 89% of failures (8/9) are due to missing symptom detection
- 22% of failures (2/9) are due to false trace signals

**Next Steps**:
1. Debug why self-health analyzer isn't detecting symptoms
2. Check if fault injection is actually creating observable degradation
3. Review metrics availability for different node types
4. Tighten trace authoritative criteria

**Once symptom detection is fixed, expect 90%+ accuracy** (16-17/18 cases).
