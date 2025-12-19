# Time Window Implementation Summary

## What We Fixed

### Problem 1: Episode Aggregation (CRITICAL)
**Before:**
```python
base_df = metrics[metrics['sim_time'] < fault_start]          # 0-60s
curr_df = metrics[metrics['sim_time'] >= fault_start]         # 60-300s (includes recovery!)
```

**After:**
```python
# Point-in-time analysis at 170s
baseline: 0-60s (pre-fault)
current: 126-171s (steady fault state, excludes recovery)
```

**Impact:** Eliminates recovery artifacts that created artificial "outlier pods"

### Problem 2: Magic Numbers
**Before:** Hardcoded `+30s`, `+60s` constants

**After:** Everything is percentage-based or from label data:
- `baseline_window = episode_duration * 0.25` (25%)
- `current_window = episode_duration * 0.15` (15%)
- `gap = episode_duration * 0.05` (5%)
- `propagation_time = baseline_window * 1.5`
- `analysis_time = fault_start + propagation_time`

### Problem 3: Using Recovery Information
**Before:** Used `recovery_start_time` to compute analysis time

**After:** Only uses observable information:
- `fault_start_time` (observable: when incident detected)
- `fault_full_effect_time` (observable: when ramped up)
- Episode duration (observable)
- Percentage-based timing

## Implementation

### Key Components

**1. TimeWindowSelector** (`analysis2/time_window_selector.py`)
- Handles percentage-based window sizing
- Validates no overlap between baseline/current
- Provides `suggest_analysis_time()` for data-driven timing

**2. Integration** (`analysis2/run_rca_batch.py`)
- Updated `get_data_windows()` to use TimeWindowSelector
- Computes analysis_time without recovery information
- Uses known_fault_start for baseline selection

### Parameters (All Percentage-Based)

```python
selector = TimeWindowSelector(
    metrics_df=metrics_df,
    episode_start=0,
    episode_end=metrics_df['sim_time'].max(),
    baseline_pct=0.25,   # 25% of episode for baseline
    current_pct=0.15,    # 15% of episode for current
    min_gap_pct=0.05     # 5% minimum gap
)

# Analysis time suggestion
analysis_time = selector.suggest_analysis_time(
    fault_start_time=fault_start,
    target_percentile=0.6  # At 60% through episode
)

# Window selection
windows = selector.select_windows(
    analysis_time=analysis_time,
    known_fault_start=fault_start  # For evaluation only
)
```

### Example Output

For episode with:
- Duration: 295s
- Fault start: 60s
- Fault full effect: 90s

Results in:
- Baseline window: 0-60s (60s, 20% of episode)
- Current window: 126-171s (44s, 15% of episode)
- Gap: 66s (22% of episode)
- Analysis time: 170.6s (60 + 1.5×73.8)

## What's Data-Driven

✓ **Baseline window size**: 25% of episode duration
✓ **Current window size**: 15% of episode duration
✓ **Gap**: 5% minimum
✓ **Analysis time**: fault_start + (1.5 × baseline_window)
✓ **Window bounds**: Validated against episode boundaries

## What's NOT Used (Correctly)

✗ **recovery_start_time**: Not available to RCA in production
✗ **recovery_complete_time**: Not available to RCA
✗ **Fixed time constants**: No hardcoded seconds

## Next Steps

### 1. Test on False Positive Cases
Run updated RCA on the 9 false positive cases:
```bash
python analyze_false_positives.py data/batch_run_20251218_133824
```

Expected improvements:
- Fewer outlier pods (no recovery artifacts)
- Better temporal separation (gap between windows)
- More accurate health comparison (steady states)

### 2. Add Pod Coverage Filtering

In `whitebox_rca.py` (lines 426-430), add coverage-based confidence:
```python
if health_metadata.get('source') == 'pod-level':
    coverage = health_metadata.get('coverage', 0)

    if coverage >= 0.8:
        confidence = 'high'
        confidence_multiplier = 1.0
    elif coverage >= 0.5:
        confidence = 'medium'
        confidence_multiplier = 0.6
    else:
        # Outlier pods - weak evidence
        confidence = 'low'
        confidence_multiplier = 0.2
```

### 3. Measure Improvement
Compare before/after on:
- Precision (false positives eliminated)
- Recall (ground truth still found)
- MRR (mean reciprocal rank)

## Key Insights

1. **Point-in-time analysis >> Episode aggregation**
   - RCA is a snapshot, not a summary
   - Comparing steady states, not transitions

2. **Percentage-based >> Fixed time constants**
   - Robust across variable episode lengths
   - Adapts to different fault types

3. **Observable information only**
   - No recovery timing (unavailable in production)
   - Uses fault detection time + propagation

4. **Relative baselines >> Perfect health**
   - Baseline just needs to be healthier than current
   - Systems are never perfectly healthy

## Summary

The time window implementation is now:
- ✓ Point-in-time (not episode-wide)
- ✓ Percentage-based (not fixed seconds)
- ✓ Data-driven (from episode characteristics)
- ✓ Production-realistic (no recovery information)
- ✓ Validated (no overlaps, sufficient gaps)

This foundation enables proper RCA analysis without contamination from recovery artifacts or magic constants.
