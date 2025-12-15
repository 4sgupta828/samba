# RCA Re-Design: First Principles Analysis

## The Fundamental Problem

The current approach uses a **weighted sum** to combine all signals:
```python
final_score = (guilt_ratio * 100) + (self_score * 5) + temporal + trace
```

This is fundamentally broken because:
1. **A component with ZERO internal symptoms can rank #1** (billing_service: self_score=0.0, score=96.83)
2. **All signals are treated as equally valid** (guilt vs self-symptoms vs traces)
3. **No logical ordering** - we're just adding numbers

## First Principles: What is a Root Cause?

### Definition
**Root Cause**: The component whose **internal fault** is causing the cascade of failures.

### Necessary Conditions
1. **MUST have internal symptoms** (CPU, memory, threads, I/O degradation)
2. **MUST show degradation before or at start of cascade** (temporal causality)
3. **SHOULD have authoritative trace evidence** (high self-time, not just total-time)

### What is NOT a Root Cause
**Victim**: Component that appears degraded but is actually:
- Healthy internally (no resource saturation)
- Waiting on slow dependencies
- Shows high total-time but normal self-time in traces

### The Critical Insight
```
billing_service:
  - self_score: 0.0        ← NO internal symptoms
  - guilt_ratio: 0.8       ← Blamed by callers
  - trace: total-time up   ← Waiting on dependencies

Conclusion: VICTIM, not root cause
```

**Current bug**: Allows victims to rank #1 because guilt_ratio dominates.

## The Right Architecture: Multi-Stage Filtering

Instead of weighted sum, use **logical stages**:

### Stage 1: FILTER - Identify Candidates with Self-Health Issues
```python
candidates = []
for node in topology:
    self_score = analyze_self_health(node)

    # HARD FILTER: Must have internal symptoms
    if self_score < THRESHOLD:  # e.g., 2.0
        continue  # Skip - cannot be root cause

    candidates.append(node)
```

**Rationale**:
- If a component has no internal degradation, it CANNOT be the root cause
- Eliminates victims immediately
- This is a **logical requirement**, not a tunable parameter

### Stage 2: VALIDATE - Use Traces to Distinguish Root Cause vs Victim
```python
for candidate in candidates:
    trace_info = analyze_traces(candidate)

    if trace_info.self_time_degradation > 2.0:
        # AUTHORITATIVE: Self-time is high = internal processing slow
        candidate.confidence = 'HIGH'
        candidate.score += 50

    elif trace_info.total_time_degradation > 5.0 and trace_info.self_time_degradation < 1.5:
        # Red flag: Total-time up, self-time normal = waiting on deps
        # Even if it passed Stage 1, this is a victim
        candidate.confidence = 'VICTIM'
        candidate.score = 0  # Eliminate
```

**Rationale**:
- Traces provide authoritative evidence about WHERE latency originates
- Self-time vs total-time distinction is crucial
- Can override Stage 1 if traces show victim pattern

### Stage 3: CONFIRM - Use Guilt to Validate Impact
```python
for candidate in candidates:
    guilt_ratio = calculate_guilt(candidate)

    # Guilt is CONFIRMATORY, not primary evidence
    if guilt_ratio > 0.5:
        candidate.score += 20  # Boost confidence
    elif guilt_ratio == 0:
        candidate.score -= 10  # Reduce confidence (maybe early in cascade)
```

**Rationale**:
- High guilt means other services are impacted → confirms this is the root cause
- Low guilt doesn't eliminate candidate (might be early detection)
- Guilt validates but doesn't drive the decision

### Stage 4: RANK - Temporal Ordering and Severity
```python
# Sort by:
# 1. Temporal causality (who degraded first?)
# 2. Severity of self-symptoms
# 3. Confirmation signals (guilt, traces)

candidates.sort(key=lambda c: (
    -c.temporal_priority,  # Earlier = higher priority
    -c.self_score,         # More severe = higher
    -c.confidence_score    # More confirmed = higher
))
```

## Why This Fixes the billing_service Problem

### Current Approach
```
billing_service: (guilt=0.8)*100 + (self=0.0)*5 + trace=8*2 = 96 points ✗
notification_service: (guilt=0.0)*100 + (self=3.6)*5 + trace=0 = 18 points ✗
```
Result: Victim ranks higher than root cause

### First Principles Approach
```
Stage 1: Filter by self-health
  billing_service: self_score=0.0 → ELIMINATED ✓
  notification_service: self_score=3.6 → CANDIDATE ✓

Stage 2: Validate with traces
  notification_service: (no high self-time) → confidence=MEDIUM

Stage 3: Confirm with guilt
  notification_service: guilt=0.0 → reduce confidence

Stage 4: Rank
  notification_service: Only candidate → Rank #1 ✓
```

## The Real Issues in Current Code

### Issue #1: No Hard Filter on Self-Health
**Location**: `whitebox_rca.py:198-212`

```python
# REMOVED: Hard threshold (score > 10.0)
# Now we rank ALL nodes and let top-K filtering happen later
rankings.append({
    'node': node,
    'score': final_score,  # ← Can be 100 with self_score=0!
    ...
})
```

**Problem**: Removed the threshold entirely. ALL nodes are ranked, even with self_score=0.

**Fix**: Restore hard filter with proper logic:
```python
# Must have self-symptoms OR authoritative trace evidence
if self_score < 2.0 and not is_trace_authoritative:
    continue  # Skip this node
```

### Issue #2: Weighted Sum vs Logical Stages
**Location**: `whitebox_rca.py:189-196`

The entire approach is wrong. Should not be:
```python
final_score = sum(all_signals * weights)  # ✗ Wrong
```

Should be:
```python
# Stage 1: Filter
if not has_self_symptoms and not has_authoritative_trace:
    skip

# Stage 2: Distinguish root cause vs victim
if high_total_time and low_self_time:
    mark_as_victim, skip

# Stage 3: Score remaining candidates
score = self_severity + confirmation_bonus
```

### Issue #3: Guilt as Primary Evidence
**Location**: Philosophy of the entire engine

Guilt ratio should be **confirmatory**, not **primary**:
- Current: `guilt_ratio * 100` (0-100 points, dominates everything)
- Correct: `guilt_ratio * 20` (0-20 points, confirms but doesn't drive)

**Why**: Being blamed by callers means "impact is spreading" not "this is the root cause"

### Issue #4: No Victim Detection
**Location**: Missing entirely

The code never asks:
> "Does this component look degraded because IT'S broken, or because it's WAITING on something broken?"

Traces provide the answer (self-time vs total-time), but it's not used as a filter.

## Proposed Solution: Hybrid Scoring with Hard Filters

```python
def analyze_incident_v2(...):
    candidates = []

    for node in topology.nodes:
        # PHASE 1: Self-Health
        self_score, symptoms = analyze_self_health(node)

        # PHASE 2: Trace Analysis
        trace_info = analyze_traces(node)
        is_authoritative = trace_info.self_time_degradation > 2.0
        is_victim = (trace_info.total_time > 3.0 and
                    trace_info.self_time < 1.5)

        # HARD FILTER: Must have internal symptoms OR authoritative trace
        if self_score < 2.0 and not is_authoritative:
            continue  # Cannot be root cause

        # HARD FILTER: Eliminate confirmed victims
        if is_victim:
            continue

        # PHASE 3: Guilt (Confirmatory only)
        guilt_ratio = calculate_guilt(node)

        # PHASE 4: Temporal
        temporal_score = analyze_temporal(node)

        # SCORING (balanced, not guilt-dominated)
        base_score = self_score * 10  # 0-100 (primary signal)

        if is_authoritative:
            base_score += 50  # Authoritative trace evidence

        confirmation = (
            guilt_ratio * 20 +      # 0-20 (confirms impact)
            temporal_score * 2      # 0-20 (earlier = higher)
        )

        final_score = base_score + confirmation

        candidates.append({
            'node': node,
            'score': final_score,
            'self_score': self_score,
            'is_authoritative': is_authoritative,
            'guilt_ratio': guilt_ratio,
            ...
        })

    return sorted(candidates, key=lambda x: x['score'], reverse=True)
```

## Key Principles

1. **Self-symptoms are mandatory** (except for authoritative trace evidence)
2. **Traces distinguish root cause from victim** (self-time vs total-time)
3. **Guilt confirms impact, doesn't identify cause** (secondary signal)
4. **Temporal ordering breaks ties** (first degraded likely root cause)

## Testing the Fix

### Expected Outcomes

**Case 1**: data_20251212_135332 (notification_service with CPU saturation)
```
Before:
  billing_service: score=96 (guilt=0.8, self=0.0) ✗

After:
  billing_service: FILTERED OUT (self_score=0.0) ✓
  notification_service: score=80+ (self=3.6*10 + guilt=0*20) ✓
```

**Case 2**: data_20251212_143703 (billing_service IS root cause)
```
Before:
  billing_service: score=80+ ✓

After:
  billing_service: PASSES filter (has self-symptoms in this case)
  billing_service: score=high ✓
```

The fix should:
- Eliminate 17/18 false positives for billing_service
- Correctly identify root causes with self-symptoms
- Not break the 1 case where billing_service IS the root cause

## Summary

**Current approach**: Treats all signals equally, allows victims to dominate through guilt ratio

**First principles approach**:
1. Self-symptoms or authoritative traces are **required**
2. Victim detection is **mandatory**
3. Guilt is **confirmatory**
4. Scoring is **logical stages**, not arbitrary weighted sum

**The fix is not tuning weights - it's changing the architecture from weighted sum to staged filtering.**
