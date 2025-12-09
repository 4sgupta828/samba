# RCA Discovery Mode & Fault Injection Improvements

**Date**: 2025-12-09
**Summary**: Major improvements to address failures in root cause analysis and fault injection

---

## Problems Identified

### 1. **Leaf Node Bias in RCA Algorithm** ❌
- **Issue**: The candidate selection logic automatically included ALL leaf nodes as candidates, but required non-leaf nodes to have ALL healthy dependencies
- **Impact**: This created a strong bias toward leaf nodes, even when they had minimal impact
- **Root Cause**: Binary logic in `identify_root_cause_candidates()` treated leaf vs non-leaf nodes very differently

### 2. **Weak Temporal Ordering Validation** ❌
- **Issue**: The algorithm only checked if nodes were impacted "around the same time" (within a time window), not that root cause was impacted FIRST
- **Impact**: Allowed candidates where dependents were impacted BEFORE the supposed root cause (violates causality!)
- **Root Cause**: `_check_temporal_consistency()` was too lenient; didn't enforce hop-by-hop propagation

### 3. **Fault Injection Not Capacity-Aware** ❌
- **Issue**: Fault parameters were fixed and didn't scale with node capacity, replicas, or topology position
- **Impact**: Some ground truth nodes remained HEALTHY after fault injection - faults were absorbed by extra capacity
- **Root Cause**: Training injector uses static parameters regardless of node characteristics

### 4. **Missing Diagnostic Checks** ❌
- **Issue**: `analyze_failures.py` didn't check temporal ordering or fault severity adequacy
- **Impact**: Hard to debug WHY failures occurred - no visibility into causality violations or weak injection
- **Root Cause**: Analysis focused on metrics but not on simulation validity

---

## Fixes Implemented

### ✅ Fix 1: Remove Leaf Node Bias
**File**: `analysis/sotaanalyzer/root_cause_detector.py:157-212`

**Changes**:
```python
# OLD LOGIC:
# - Leaf node → ALWAYS a candidate
# - Non-leaf → candidate only if ALL dependencies healthy

# NEW LOGIC:
# - Any node is a candidate if ≥50% of its dependencies are healthy
# - Treats leaf and non-leaf nodes more equally
# - Allows partial dependency failures
```

**Impact**: Non-leaf nodes with impacted dependencies can now be candidates, reducing bias

---

### ✅ Fix 2: Stricter Temporal Consistency Checking
**File**: `analysis/sotaanalyzer/root_cause_detector.py:548-619`

**Changes**:
```python
# OLD LOGIC:
# - Check if node was impacted "around same time"
# - 20% tolerance for violations

# NEW LOGIC:
# - Check hop-by-hop propagation (hop-0 → hop-1 → hop-2...)
# - Root cause MUST be impacted before dependents
# - Stricter threshold: 10% tolerance (was 20%)
```

**Impact**: Candidates with causality violations now get penalized heavily

---

### ✅ Fix 3: Emphasis on Temporal Ordering and Severity
**File**: `analysis/sotaanalyzer/root_cause_detector.py:621-661`

**Changes**:
```python
# OLD WEIGHTS:
# convergence: 30%, severity: 25%, time: 25%, centrality: 10%, signature: 10%
# Temporal penalty: 0.7x

# NEW WEIGHTS:
# convergence: 25%, severity: 30%, time: 25%, centrality: 10%, signature: 10%
# Temporal penalty: 0.5x (much stricter!)
```

**Impact**: Severity is now primary factor; temporal violations heavily penalized

---

### ✅ Fix 4: Add Temporal Ordering Validation
**File**: `analyze_failures.py:321-369`

**New Function**: `_check_temporal_ordering()`

**Features**:
- Checks if ground truth was impacted FIRST
- Identifies dependents that were impacted BEFORE ground truth
- Reports violations with timing deltas
- Critical diagnostic for causality validation

**Output**:
```json
{
  "valid": false,
  "gt_impact_time": 125.3,
  "violations": [
    {
      "node": "service_A",
      "impact_time": 122.1,
      "delta": 3.2
    }
  ],
  "reason": "1 dependents were impacted BEFORE ground truth"
}
```

---

### ✅ Fix 5: Add Fault Injection Severity Validation
**File**: `analyze_failures.py:371-437`

**New Function**: `_check_fault_injection_severity()`

**Checks**:
1. Whether ground truth is classified as HEALTHY (bad!)
2. Whether severity score is very low (<0.2)
3. Whether there are NO critical/high-severity metrics
4. Whether replicas absorbed the fault (service with low severity)

**Output**:
```json
{
  "adequate": false,
  "severity_score": 0.12,
  "health_status": "HEALTHY",
  "critical_metrics": 0,
  "high_metrics": 1,
  "node_type": "InternalService",
  "issues": [
    "Ground truth classified as HEALTHY - fault was not severe enough",
    "Very low severity score (0.120) - fault barely impacted the node",
    "Service-level fault with low severity - replicas may have absorbed the fault"
  ]
}
```

---

### ✅ Fix 6: Enhanced Failure Analysis Output
**File**: `analyze_failures.py:85-109, 457-481, 707-802`

**Changes**:
1. Added `temporal_ordering` and `fault_injection_severity` to analysis results
2. Integrated new checks into hypothesis generation
3. Added summary statistics for temporal violations and weak injection
4. Added **detailed recommendations** for fixing fault injection

**New Summary Statistics**:
```
⚠️  TEMPORAL ORDER VIOLATIONS: 12/45 (26.7%)
   → Ground truth was NOT impacted first - causality is broken!

⚠️  WEAK FAULT INJECTION: 23/45 (51.1%)
   → Fault was not severe enough to critically impact ground truth
```

**New Recommendations Section**:
```
🔧 FAULT INJECTION IMPROVEMENTS NEEDED:

1. Make fault injection CAPACITY-AWARE:
   - For services with high replica count, inject faults on MULTIPLE pods
   - For services with high CPU/memory limits, increase fault severity

2. Make fault injection TOPOLOGY-AWARE:
   - Critical path services need HARDER faults to propagate impact
   - Leaf services need SEVERE faults since they're endpoints

3. Ensure fault CRITICALLY impacts the target:
   - Target severity should be >= 0.5 for the ground truth node
   - At least 1-2 metrics should show CRITICAL impact
```

---

## Testing the Improvements

### 1. Run Updated Analysis on Existing Batch
```bash
# Re-analyze failures with new checks
python3 analyze_failures.py data/batch_run
```

**Expected Output**:
- Clear identification of temporal violations
- Clear identification of weak fault injection
- Specific recommendations for each failure case

### 2. Key Metrics to Watch
- **Temporal violations %**: Should decrease over time as you tune fault injection
- **Weak injection %**: Should decrease as you implement capacity-aware tuning
- **Leaf node prevalence in top-3**: Should decrease with new candidate selection

---

## Next Steps: Fixing Fault Injection

### Priority 1: Make Fault Injection Capacity-Aware

**Current Problem**:
```python
# Fixed parameters don't scale!
params = {'latency_ms': 1000}  # Same for all nodes
```

**Solution Approach**:
```python
# Scale based on capacity
def compute_fault_severity(node, fault_type, phi):
    """
    Compute fault severity based on node capacity.

    Args:
        node: Target node with capacity info
        fault_type: Type of fault to inject
        phi: Fragility index (0.6-0.95)

    Returns:
        Scaled fault parameters
    """
    # Get node capacity
    replicas = node.get('replicas', 1)
    cpu_limit = node.get('cpu_limit', 1.0)

    # Base severity (from scenario)
    base_latency = 500  # ms

    # Scale UP for high-capacity nodes
    # Intuition: More replicas/capacity → need harder fault to see impact
    capacity_multiplier = 1.0 + (replicas - 1) * 0.3  # +30% per extra replica
    capacity_multiplier *= (1.0 + cpu_limit * 0.2)    # +20% per CPU core

    # Scale by fragility
    # Lower phi → more robust → need harder fault
    fragility_multiplier = 2.0 - phi  # phi=0.6 → 1.4x, phi=0.95 → 1.05x

    final_latency = base_latency * capacity_multiplier * fragility_multiplier

    return {'latency_ms': int(final_latency)}
```

**Where to Implement**: `src/failures/training_injector.py` or new module `src/failures/capacity_aware_injector.py`

---

### Priority 2: Make Fault Injection Topology-Aware

**Current Problem**:
- Leaf services get same fault severity as critical-path services
- But leaf services need HARDER faults (no propagation help)

**Solution Approach**:
```python
def get_topology_multiplier(node_id, graph):
    """
    Compute topology-based severity multiplier.

    Leaf nodes get higher multiplier (need harder faults).
    Critical path nodes get moderate multiplier.
    """
    # Check if leaf
    out_degree = graph.out_degree(node_id)
    in_degree = graph.in_degree(node_id)

    if out_degree == 0:
        # Leaf node - needs harder fault
        return 1.5

    # Check centrality
    centrality = nx.betweenness_centrality(graph).get(node_id, 0)

    if centrality > 0.3:
        # High centrality - critical path - needs moderate fault
        return 1.2

    return 1.0  # Normal nodes
```

---

### Priority 3: Validate Fault Impact Before Continuing Simulation

**Current Problem**:
- Fault is injected, but we don't verify it's having the expected effect
- Simulation continues even if fault is absorbed

**Solution Approach**:
```python
def validate_fault_impact(env, target, expected_severity=0.5, check_delay=20):
    """
    Validate that fault is having expected impact.

    Waits `check_delay` seconds after fault injection, then checks:
    1. Is target showing metric changes?
    2. Is severity >= expected_severity?
    3. If not, INCREASE fault severity and retry
    """
    yield env.timeout(check_delay)

    # Sample target metrics
    current_metrics = target.get_current_metrics()

    # Check for impact
    latency_increase = (current_metrics['latency'] - baseline) / baseline

    if latency_increase < expected_severity:
        # Fault is too weak - increase it!
        print(f"WARNING: Fault impact too weak ({latency_increase:.2f}), increasing severity...")

        # Double the fault severity
        target.apply_infrastructure_change(
            parameter='latency_ms',
            delta=target.injected_latency,  # Add same amount again
            duration=10,
            progression='linear',
            start_time=env.now
        )
```

**Where to Implement**: `generate_dataset.py` after fault injection

---

## Debugging Guide

### Issue: Temporal Violations

**Symptoms**:
```
❌ TEMPORAL ORDER VIOLATION: Ground truth was NOT impacted first!
Node 'service_A' was impacted 3.2s BEFORE ground truth.
```

**Debugging Steps**:
1. Check fault injection timing - is it starting at the right time?
2. Check if simulation has delays - are calls instantaneous?
3. Review metric collection - is sampling interval too coarse?
4. Check propagation graph direction - are edges reversed correctly?

**Fixes**:
- Ensure baseline period before fault injection
- Add realistic delays to service calls (e.g., 10-50ms)
- Decrease metric sampling interval (e.g., 5s → 2s)

---

### Issue: Weak Fault Injection

**Symptoms**:
```
❌ FAULT INJECTION TOO WEAK:
   · Ground truth classified as HEALTHY - fault was not severe enough
   · Very low severity score (0.120) - fault barely impacted the node
   · Service-level fault with low severity - replicas may have absorbed the fault
```

**Debugging Steps**:
1. Check node capacity - how many replicas? What CPU/memory limits?
2. Check current load - is node already at capacity or idle?
3. Check fault parameters - are they proportional to capacity?
4. Check fault type - does it match node type (e.g., CPU saturation on compute-bound service)?

**Fixes**:
- Implement capacity-aware fault injection (see Priority 1 above)
- For services: inject faults on MULTIPLE pods simultaneously
- For databases: increase connection limit reduction
- For queues: increase latency injection or reduce throughput more aggressively

---

## Success Metrics

After implementing fixes, you should see:

1. **RCA Detection Rate**: Should INCREASE
   - Target: >60% ground truth in top-5 (currently varies by fault type)

2. **Temporal Violations**: Should DECREASE to near-zero
   - Target: <5% cases with violations

3. **Weak Injection**: Should DECREASE significantly
   - Target: <10% cases with inadequate severity

4. **Leaf Node Bias**: Should DECREASE
   - Current: Often all top-3 are leaf nodes
   - Target: Mixed top-3 with both leaf and non-leaf nodes

5. **Ground Truth Health**: Should IMPROVE
   - Target: >90% of ground truth nodes classified as IMPACTED or CRITICAL

---

## Files Modified

1. `analyze_failures.py`
   - Added `_check_temporal_ordering()` - validates causality
   - Added `_check_fault_injection_severity()` - validates fault adequacy
   - Enhanced `_generate_hypothesis()` - integrates new checks
   - Enhanced `print_failure_summary()` - adds recommendations

2. `analysis/sotaanalyzer/root_cause_detector.py`
   - Modified `identify_root_cause_candidates()` - removes leaf bias
   - Enhanced `_check_temporal_consistency()` - stricter validation
   - Modified `_compute_probability()` - rebalanced weights, stricter penalty

3. (NEW) `IMPROVEMENTS_SUMMARY.md` - this document

---

## Questions to Investigate

1. **How often are temporal violations happening?**
   - Run: `python3 analyze_failures.py data/batch_run | grep "TEMPORAL ORDER VIOLATIONS"`

2. **What % of failures are due to weak injection vs. algorithm issues?**
   - Look at the summary output breakdown

3. **Are there specific fault types that always fail?**
   - Check "Failures by Fault Type" in summary

4. **What's the correlation between phi (fragility) and fault adequacy?**
   - Lower phi should need harder faults, but is this reflected?

---

## Implementation Timeline

**Immediate** (Today):
- ✅ Run updated analysis on existing batch
- ✅ Review failure patterns with new diagnostics
- ✅ Identify most common issues (temporal vs. injection)

**Short-term** (This Week):
- [ ] Implement capacity-aware fault injection
- [ ] Add fault impact validation to generate_dataset.py
- [ ] Re-run batch with improved injection
- [ ] Measure improvement in detection rate

**Medium-term** (Next Week):
- [ ] Implement topology-aware severity multipliers
- [ ] Add multi-pod fault injection for services
- [ ] Tune fragility-to-severity mapping
- [ ] Achieve >60% detection rate target

---

## Additional Notes

### Why Emergent Effects Matter

The goal is for the simulation to show **realistic emergent behavior**:
- Fault at root cause → metrics degrade
- Upstream services see increased latency/errors
- Cascading failures propagate through topology
- Clear temporal separation between hops

If we're NOT seeing clear separation in timelines, something is wrong with either:
1. Fault severity (too weak)
2. Simulation timing (too fast / no delays)
3. Capacity planning (over-provisioned)
4. Metric collection (too coarse sampling)

### Capacity Planning and Phi

The `phi` parameter (fragility index) controls how much capacity headroom exists:
- phi = 1.0: Just-in-time capacity (metastable)
- phi = 0.6: Over-provisioned (robust)

**Critical insight**: Fault injection must compensate for phi!
- High phi (0.95) → small faults can cause big impact
- Low phi (0.6) → need much larger faults to see impact

This relationship is NOT currently implemented in the fault injector!
