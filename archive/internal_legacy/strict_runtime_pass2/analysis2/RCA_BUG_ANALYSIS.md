# RCA Failure Analysis - Bug Report

## Executive Summary

**Issue**: RCA failed to correctly identify the root cause in 6 out of 18 cases (33% failure rate). More critically, in 17 out of 18 cases, `billing_service` was incorrectly ranked #1, regardless of the actual root cause.

**Actual Performance**:
- ✗ **6/18 cases**: Ground truth NOT in top-5 (complete failure)
- ✓ **12/18 cases**: Ground truth found in top-5 (but often at ranks 2-5, not #1)
- ⚠️ **17/18 cases**: `billing_service` incorrectly ranked #1

## Root Causes

### BUG #1: Guilt Ratio is Over-Weighted (CRITICAL)

**Location**: `whitebox_rca.py:191`

```python
final_score = (
    (guilt_ratio * 100.0) +        # External evidence (0-100)  ← TOO HIGH!
    (self_score * 5.0) +           # Internal evidence (0-50)
    impact_bonus +                  # Traffic volume (0-3)
    (temporal_score * 2.0) +       # Temporal causality (0-40)
    (trace_score * 2.0)            # Trace evidence (0-40)
)
```

**Problem**:
- Guilt ratio contributes 0-100 points (dominates the score)
- If a node has 1 caller blaming it: guilt_ratio = 1.0 → 100 points
- This completely overshadows self-symptoms (max 50 points)

**Evidence**:
In all 6 failed cases:
- `billing_service` scored 80-160 points (guilt_ratio: 0.8, self_score: 0.0)
- Ground truth services scored 0-20 points (guilt_ratio: 0.0, self_score: 3-10)

**Example** (data_20251212_135332):
```
Ground truth: notification_service
  - Score: 18.74 (guilt: 0.0, self: 3.6, symptoms: CPU+thread_pool)

Wrong #1: billing_service
  - Score: 96.83 (guilt: 0.8, self: 0.0, symptoms: NONE)
```

**Why it happens**:
- `subscription_service` calls `billing_service` (sync_http edge)
- Disambiguator (correctly) detects latency increase on this edge
- `subscription_service` blames `billing_service` → guilt_ratio = 0.8
- Result: 80 points from guilt alone, despite NO self-symptoms

---

### BUG #2: Edge Blame Doesn't Verify Callee Self-Health

**Location**: `disambiguator.py:69-74`

```python
# Case B: Callee Fault (Latency/Error up, RPS stable/down)
if (lat_stat.significant or err_stat.significant) and \
   (not rps_stat.significant or rps_stat.effect_size < 0.2):
    return EdgeVerdict(
        blames_caller=False, blames_callee=True,
        reason=f"Callee Degradation (Lat d={lat_stat.effect_size:.2f}) with stable load",
        confidence=0.95
    )
```

**Problem**:
- Edge analysis only looks at caller's metrics (dependency_latency, dependency_error_rate)
- Doesn't check if callee has self-symptoms (CPU, memory, thread saturation)
- A service can be blamed even if it's healthy but waiting on its own dependencies

**Victim Chain Example**:
```
notification_service (root cause: CPU saturation)
  ↓ slow response
email_service (victim: waiting on notification_service)
  ↓ slow response
billing_service (victim: waiting on email_service)
  ↓
subscription_service blames billing_service
```

**Result**: The last victim in the chain gets blamed, not the root cause.

---

### BUG #3: Trace Score for Total-Time is Misleading

**Location**: `trace_analyzer.py:333-338` + `whitebox_rca.py:195`

```python
# trace_analyzer.py
elif metrics.total_degradation_factor > 5.0:
    trace_score = 8.0  # ← Non-authoritative evidence
    reason = f"Total latency increased {metrics.total_degradation_factor:.1f}x (may be waiting on deps)"

# whitebox_rca.py
final_score += (trace_score * 2.0)  # 8.0 * 2 = 16 points
```

**Problem**:
- Total-time degradation can mean:
  - **Root cause**: Service's own processing is slow (self-time high)
  - **Victim**: Service is waiting on slow dependencies (total-time high, self-time normal)
- The code correctly identifies this ambiguity ("may be waiting on deps")
- But still gives 8-16 points, which is enough to push victims above root causes

**Evidence**:
In data_20251212_142900 (ground truth: payment_gateway):
```
billing_service: trace_score=20.0 (total-time: 5.6x, self-time: 1.0x) ← VICTIM
payment_gateway: trace_score=0.0 (not detected)
```

---

### BUG #4: No Sanity Check for High Guilt + Zero Self-Symptoms

**Location**: `whitebox_rca.py:189-196` (missing logic)

**Problem**:
- A service with `guilt_ratio=0.8` and `self_score=0.0` can score 80+ points
- This is a clear indicator of a **victim**, not a root cause:
  - High guilt = other services are affected when calling it
  - Zero self-symptoms = it's not internally degraded
  - Conclusion: It's slow because it's waiting on dependencies

**Missing Logic**:
```python
# Should add this check:
if guilt_ratio > 0.5 and self_score < 2.0 and not is_trace_authoritative:
    # High blame but no internal symptoms = likely a victim
    # Reduce guilt_ratio weight or mark as "suspected victim"
    guilt_ratio *= 0.3  # Dampen guilt for victims
```

---

## Detailed Failure Cases

### Failed Case #1: data_20251212_135332
- **Ground truth**: notification_service (CPU saturation)
- **RCA ranked #1**: billing_service (score: 96.83)
- **Ground truth rank**: 6th (score: 18.74)

**Why it failed**:
- notification_service has clear symptoms: `cpu_usage +144%`, `thread_pool +137%`
- But guilt_ratio=0.0 (no callers blamed it directly) → only 18.74 points
- billing_service has NO symptoms but guilt_ratio=0.8 → 96.83 points

---

### Failed Case #2: data_20251212_135808
- **Ground truth**: notification_service
- **RCA ranked #1**: billing_service (score: 90.83)
- **Ground truth rank**: >5 (score: 0.76)

**Why it failed**:
- notification_service has NO symptoms detected (possible detection bug)
- billing_service gets 80+ points from guilt alone

---

### Failed Case #3: data_20251212_141017
- **Ground truth**: user_management_service
- **RCA ranked #1**: billing_service (score: 80.82)
- **Ground truth rank**: >5 (score: 1.00)

---

### Failed Case #4: data_20251212_142056
- **Ground truth**: billing_queue
- **RCA ranked #1**: billing_service (score: 81.10)
- **Ground truth rank**: >5 (score: 0.00)

---

### Failed Case #5: data_20251212_142900
- **Ground truth**: payment_gateway
- **RCA ranked #1**: billing_service (score: 160.81)
- **Ground truth rank**: >5 (score: 0.00)

**Special note**: This is the worst case - billing_service scored 160+ points!

---

### Failed Case #6: data_20251212_144418
- **Ground truth**: global_network (not found in topology)
- **RCA ranked #1**: billing_service (score: 80.80)

**Note**: Ground truth missing from candidates (possible data generation issue)

---

## Why billing_service Dominates

1. **Central Hub**: billing_service is called by multiple services
2. **Common Dependency**: When any downstream service fails, billing_service latency increases
3. **Consistent Blamer**: subscription_service → billing_service edge always shows degradation
4. **Guilt Amplification**: guilt_ratio=0.8 → 80 points, every time

**Result**: billing_service acts as a "false attractor" - it's a victim but looks like a root cause.

---

## Recommended Fixes

### Fix #1: Reduce Guilt Ratio Weight (CRITICAL)
```python
# whitebox_rca.py:191
final_score = (
    (guilt_ratio * 30.0) +         # Reduced from 100.0
    (self_score * 10.0) +          # Increased from 5.0 (prioritize self-symptoms)
    impact_bonus +
    (temporal_score * 2.0) +
    (trace_score * 2.0)
)
```

### Fix #2: Verify Callee Self-Health in Edge Blame
```python
# disambiguator.py - add self-health check
def analyze_edge(self, ..., callee_self_score=0.0):
    # ... existing logic ...

    if (lat_stat.significant or err_stat.significant):
        # Check if callee has self-symptoms
        if callee_self_score > 2.0:
            # Callee is internally degraded - blame it
            return EdgeVerdict(blames_callee=True, ...)
        else:
            # Callee is healthy - it's likely waiting on its dependencies
            # Reduce blame confidence
            return EdgeVerdict(blames_callee=True, confidence=0.3, ...)
```

### Fix #3: Dampen Non-Authoritative Trace Scores
```python
# trace_analyzer.py:333-338
elif metrics.total_degradation_factor > 5.0:
    trace_score = 3.0  # Reduced from 8.0 (non-authoritative evidence)
```

### Fix #4: Add Victim Detection Heuristic
```python
# whitebox_rca.py - after line 163
if guilt_ratio > 0.5 and self_score < 2.0 and not is_trace_authoritative:
    # High guilt but no symptoms = likely a victim
    guilt_ratio *= 0.3
    victim_flag = True
```

---

## Testing Plan

1. Re-run RCA on all 18 cases with fixes applied
2. Target metrics:
   - Top-5 accuracy: Should improve from 67% (12/18) to >85% (15/18)
   - Top-1 accuracy: Should improve from 6% (1/18) to >50% (9/18)
   - billing_service false positives: Should reduce from 17/18 to <5/18

3. Validate that billing_service is still ranked #1 when it IS the root cause (data_20251212_143703)

---

## Additional Findings

### Success Pattern Analysis
When RCA succeeds (12/18 cases), the ground truth typically has:
- **High self_score** (>5.0): Clear internal symptoms
- **Trace evidence**: Either authoritative (self-time) or strong total-time
- **Some guilt**: At least some callers are affected

### Common Failure Pattern
When RCA fails (6/18 cases), the ground truth typically has:
- **Low/zero guilt_ratio**: Not directly blamed by callers
- **Moderate self_score**: Has symptoms but not extreme
- **No trace evidence**: Traces don't show clear degradation

**Root issue**: The scoring formula over-prioritizes external evidence (guilt) over internal evidence (self-symptoms).
