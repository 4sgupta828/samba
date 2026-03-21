# FILTER Analysis: Trade-offs and Recommendations

## What We Implemented

### Phase 1: Time Windows ✓
- Point-in-time analysis (not episode aggregation)
- Percentage-based, data-driven
- No recovery contamination
- **Result**: Proper steady-state comparison

### Phase 2: Pod Coverage Weighting ✓
- Coverage-based confidence multipliers
- 80%+ = high confidence (1.0x)
- 50-80% = medium (0.6x)
- 30-50% = low (0.3x)
- <30% = very low (0.15x)
- **Result**: 29% → 65% accuracy

### Phase 3: Intrinsic Degradation FILTER ✓
- Reject nodes without confirmed intrinsic degradation
- Criteria: ≥50% pod coverage OR ≥0.3 service-level score
- **Result**: 0 false positives, but 7 ground truths filtered out

## The Trade-off

| Approach | GT @ Rank 1 | False Positives | GT Not Found |
|----------|-------------|-----------------|--------------|
| **No Filter** | 11/17 (64.7%) | 61 FPs | 0/17 |
| **With Filter** | 10/17 (58.8%) | **0 FPs** | **7/17** |

## Analysis: Why Ground Truths Were Filtered

**7 Filtered Cases:**
1. thread_exhaustion: patient_records_service
2. inject_errors: analytics_service (2 cases)
3. inject_latency: records_cache, insurance_api (2 cases)
4. queue_consumer_slowdown: analytics_queue
5. hot_shard: mobile_api_service

### Root Cause Analysis

**The faults ARE injected** (verified: analytics_service error rate 29% → 53%), but they don't pass our intrinsic degradation filter because:

1. **Low pod coverage** (<50% of pods affected)
   - Fault affects only specific pods/shards
   - Example: hot_shard by definition affects 1 pod

2. **Weak service-level aggregation**
   - Service-level metrics average across all pods
   - 1 pod with 100% error rate + 5 pods healthy = 17% service average
   - Doesn't meet 0.3 threshold

3. **Symptom type**
   - Error/latency injection creates SECONDARY symptoms downstream
   - Ground truth may not show INTRINSIC resource degradation
   - Just forwarding errors/latency, not exhausting resources

## The Fundamental Question

**From First Principles**: Is a node with <50% pod coverage and no service-level symptoms actually a root cause, or is it a victim?

### Case Study: inject_errors on analytics_service

**Symptoms:**
- Error rate: 29.5% → 53.2% (injected)
- Only 1/6 pods show degradation
- Service-level aggregate: weak signal

**Two Interpretations:**

**Interpretation A: This IS a root cause**
- The fault is real (error injection working)
- It's causing errors to propagate downstream
- We should detect it

**Interpretation B: This is NOT intrinsic degradation**
- Only 17% coverage (1/6 pods)
- No resource exhaustion (CPU, memory normal)
- Just forwarding errors, not generating them intrinsically
- By definition, outlier pod without service-wide impact

## The Dilemma

**Pure First Principles Approach (Strict Filter):**
- ✓ 0 false positives
- ✓ High precision (when we find something, it's right)
- ✗ Misses faults that don't show service-wide degradation
- ✗ Lower recall

**Pragmatic Approach (Weighted, No Filter):**
- ✓ Finds all faults (including weak signals)
- ✓ Higher recall
- ✗ 61 false positives
- ✗ Lower precision

## Recommendations

### Option 1: Relax Filter Criteria (Recommended)

**Adjust thresholds to balance precision/recall:**

```python
# Current (too strict):
if coverage >= 0.5 or self_score >= 0.3:
    accept

# Proposed (more lenient):
if coverage >= 0.3 or self_score >= 0.1:  # Lower thresholds
    accept
```

**Expected outcome:**
- Catch more ground truths (inject_errors, inject_latency)
- Some false positives return (but fewer than 61)
- Better precision/recall balance

### Option 2: Two-Tier Confidence Reporting

**Don't filter, but report confidence levels:**

```python
if coverage >= 0.5 or self_score >= 0.3:
    tier = "HIGH_CONFIDENCE"
elif coverage >= 0.2 or self_score >= 0.05:
    tier = "MEDIUM_CONFIDENCE"
else:
    tier = "LOW_CONFIDENCE"
```

**Report:**
- "High confidence: [list]"
- "Medium confidence: [list]"
- "Low confidence: [list]"

**Benefits:**
- User sees all candidates with confidence levels
- Can decide threshold based on use case
- No information loss

### Option 3: Improve Fault Injection (Long-term)

**For cases like hot_shard, inject_errors:**
- Make faults more observable at service level
- Increase injection rate
- Affect more pods
- Create resource exhaustion, not just error forwarding

**This is the "right" solution but requires simulation changes.**

### Option 4: Hybrid - Filter + Fallback

**Current emergency fallback:**
```python
if len(filtered_rankings) == 0:
    # Include top 3 by score
    filtered_rankings = top_3_by_score
```

**Better fallback:**
```python
if len(filtered_rankings) == 0:
    # Include nodes with ANY evidence (no filter)
    # But mark as "low confidence"
    return all_candidates_sorted(confidence="LOW")
```

## Recommendation: Option 1 + Option 2

**Implement:**
1. Relax filter thresholds (30% coverage OR 0.1 service score)
2. Add confidence tiers to output
3. Report: "10 high-confidence candidates, 5 medium-confidence, 2 low-confidence"

**Why:**
- Balances precision/recall
- Provides transparency
- User can adjust based on context (dev vs prod)
- Principled: still filtering outliers, just less aggressively

## Validation of Original Problem

**Did we solve the original false positive issue?**

**YES! The core problem was:**
- Outlier pods (1/6 pods) ranking higher than ground truth
- Recovery artifacts creating false signals
- No distinction between intrinsic and cascading

**Solutions applied:**
- ✓ Time windows: Eliminated recovery artifacts
- ✓ Pod coverage: Downweighted outlier pods
- ✓ Filter: Removed nodes without intrinsic evidence

**Original problem (9 FP cases):**
- mobile_api_service (1/3 pods) > analytics_service (ground truth)
- imaging_service (1/3 pods) > analytics_service

**After our fixes:**
- These specific cases are resolved (no more outlier pods ranking higher)
- 0 false positives with strict filter
- Some ground truths filtered out due to weak signals

## Conclusion

We successfully implemented the first principles approach from FaultIAnalysis.md:
- ✓ FILTER for intrinsic degradation
- ✓ RANK by physics coverage
- ✓ Point-in-time analysis

**The remaining challenge is calibrating the filter threshold** to balance:
- Precision (avoiding false positives)
- Recall (finding all real faults)

**Recommended next step:** Implement Option 1 + Option 2 (relaxed threshold + confidence tiers).
