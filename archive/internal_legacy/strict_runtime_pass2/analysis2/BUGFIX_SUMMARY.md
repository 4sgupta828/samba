# Bug Fix Summary: Memory Thrashing & False Positives

## Date: 2025-12-17

## Issues Identified

### Issue #1: Memory Thrashing Fault Not Working

**Symptom:**
- Memory thrashing fault applied to `clinical_dashboard_service` showed NO observable impact in metrics
- Ground truth validation failed with "No symptoms detected"
- RCA could not detect the fault (rank=null, found_in_top_k=false)

**Root Cause:**
Memory thrashing fault was being applied to a `Service` component, but the implementation only supports `ComputeAgent`/`Pod` components. The fault silently failed with a log warning:

```
"memory_thrashing can only be applied to ComputeAgent/Pod components."
```

The `training_injector.py` had multiple hardcoded lists of `pod_level_faults` that did NOT include `memory_thrashing`, so the fault was never propagated to the actual pods.

**Evidence:**
- Log analysis: Found error message in logs.jsonl
- Metric analysis: Memory metrics for clinical_dashboard_service pods showed NO change during fault period
  - pod_clinical_dashboard_service_0: -1.6 MB (-0.8%)
  - pod_clinical_dashboard_service_1: -1.7 MB (-0.8%)
  - pod_clinical_dashboard_service_2: +8.9 MB (+4.5%)
  - pod_clinical_dashboard_service_3: +1.1 MB (+0.5%)
- Expected behavior: Should see periodic memory bursts of ~50-100MB with severity=0.5

**Fix Applied:**

1. **Created centralized constant** in `training_injector.py`:
```python
POD_LEVEL_FAULTS = [
    'cpu_saturation',
    'memory_leak',
    'memory_pressure',
    'memory_thrashing',  # ADDED
    'inject_latency',
    'inject_errors'
]
```

2. **Replaced 7 hardcoded lists** throughout training_injector.py with references to `POD_LEVEL_FAULTS`:
   - Line 190 (gradual failure application)
   - Line 471 (instant failure application)
   - Line 492 (infrastructure change application)
   - Line 653 (instant revert)
   - Line 680 (revert application)
   - Line 777 (gradual revert)

**Impact:**
- Memory thrashing faults will now properly apply to all pods when targeting a Service
- Fault will spawn background processes that periodically allocate/deallocate memory
- Observable symptoms: bimodal latency distribution, CPU spikes, memory oscillation

---

### Issue #2: False Positives in Whitebox RCA

**Symptom:**
- RCA detected `clinical_db` as top suspect with cpu_usage increased (d=0.54)
- But statistical analysis shows p-value=0.1001 (NOT significant at α=0.05)
- Change was only +1.5% CPU (34.1% vs 32.6%), which is operationally trivial

**Root Cause:**
The `compare_distributions` function in `statistical_utils.py` had **insufficient rigor**:

1. **No baseline stability check**: Never validated that baseline was stable before comparison
2. **Too lenient effect size threshold**: Accepted d > 0.2 (small effects) as significant
3. **Weak combined logic**: `(p < 0.05 AND d > 0.2) OR changepoint` - too easy to trigger
4. **Small sample size**: Only required 5 samples per window

**Evidence:**
```
clinical_db CPU Analysis:
  Baseline: 32.60% ± 2.17% (CV=0.07, n=11) [STABLE]
  Fault:    34.10% ± 2.86% (n=48)
  Change:   +1.50% (+4.6%)
  Cohen's d: 0.54 [medium effect]
  p-value: 0.1001 [NOT significant!]
  Verdict: NOT Significant
```

Despite p-value > 0.05, the RCA flagged this as a symptom because:
- The old code had: `(p_value < alpha and category != 'negligible') or cp_detected`
- With lenient thresholds, small natural variations triggered false positives

**Fix Applied:**

Enhanced `compare_distributions` with **STRICT statistical rigor**:

1. **Baseline stability check** (NEW):
```python
baseline_cv = baseline_std / abs(baseline_mean)
if baseline_cv > 0.5:
    return StatResult(False, 1.0, 0.0, 'unstable_baseline', confidence='very_low')
```

2. **Increased minimum sample size**: 5 → 10 samples (better statistical power)

3. **Stricter effect size threshold**: 0.2 → 0.5 (small → medium minimum)

4. **Stricter combined logic**:
```python
# OLD: (p_value < alpha and category != 'negligible') or cp_detected
# NEW: (p_value < alpha and abs(effect_size) >= 0.5) or (cp_detected and abs(effect_size) >= 0.8)
```

5. **Enhanced confidence scoring**:
   - High: d > 1.0 AND changepoint AND p < 0.01
   - Medium: d > 0.8 AND p < 0.05
   - Low: d >= 0.5 (borderline cases)

**Impact:**
- False positives from benign operational variance will be filtered out
- Requires BOTH statistical significance (p < 0.05) AND meaningful effect (d >= 0.5)
- Changepoints must be backed by large effects (d >= 0.8) to be considered alone
- Unstable baselines (CV > 0.5) will be rejected outright

---

## Testing Recommendations

### Test Memory Thrashing Fix

1. Generate new dataset with memory_thrashing fault:
```bash
cd ../src
python3 generate_dataset.py -n 1 --fault-type memory_thrashing --fault-role service -o ../data/test_memory_thrashing
```

2. Verify fault application in logs:
```bash
grep -i "memory thrashing" ../data/test_memory_thrashing/*/ep_0/logs.jsonl
```

3. Check for periodic memory bursts in metrics:
```bash
# Should see oscillating memory usage patterns
python3 ../analysis2/visualize_metrics.py --episode ../data/test_memory_thrashing/*/ep_0 --metric memory_usage
```

### Test False Positive Fix

1. Reprocess existing dataset with new statistical rigor:
```bash
cd ../analysis2
python3 run_rca_single.py ../data/batch_run_20251217_185609/data_20251217_185857/ep_0
```

2. Verify false positives are filtered:
- `clinical_db` should NO LONGER appear as top suspect (d=0.54, p=0.1001)
- Only nodes with d >= 0.5 AND p < 0.05 should be flagged

3. Check ground truth validation:
```bash
jq '.ground_truth_validation' ../data/batch_run_20251217_185609/data_20251217_185857/ep_0/rca_analysis.json
```

---

## Files Modified

1. `/Users/sgupta/samba/src/failures/training_injector.py`
   - Added POD_LEVEL_FAULTS constant
   - Replaced 7 hardcoded lists with constant reference
   - Added 'memory_thrashing' to pod-level faults

2. `/Users/sgupta/samba/analysis2/statistical_utils.py`
   - Enhanced compare_distributions with strict statistical rigor
   - Added baseline stability check (CV threshold)
   - Increased minimum sample size (5 → 10)
   - Increased minimum effect size (0.2 → 0.5)
   - Stricter combined significance logic
   - Enhanced confidence scoring

---

## Expected Outcomes

### Memory Thrashing
- **Before:** Silent failure, no observable impact
- **After:** Observable periodic memory bursts, bimodal latency, CPU spikes

### False Positives
- **Before:** clinical_db flagged with d=0.54, p=0.1001
- **After:** clinical_db filtered out (p > 0.05, effect too small)

### RCA Accuracy
- **Before:** Ground truth not in top-k, false positives dominate
- **After:** Ground truth should rank higher, fewer false positives

---

## Notes

1. The memory_thrashing fix is **backwards compatible** - existing faults on Pods will continue to work
2. The statistical rigor improvements may **reduce recall** slightly (miss subtle faults) but will significantly **improve precision** (fewer false alarms)
3. The stricter thresholds (d >= 0.5) are appropriate for production RCA where false alarms are costly
4. For research/testing scenarios where sensitivity is critical, consider using a configurable threshold
