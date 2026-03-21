# Baseline Selection: Relative Health Approach

## The Key Insight

**The baseline doesn't need to be perfectly healthy - it just needs to be relatively healthier than the current fault period.**

From testing against labeled data, we found:
- Labeled baselines have health scores of 2-7 (not perfect)
- Current fault periods have health scores of 2-6
- **What matters**: Baseline health < Current health (relatively better)

## Problems with "Perfect Health" Criterion

Initial approach required baseline to have health_score < 0.5 (nearly perfect). This is:
1. **Too strict** - Real systems always have some noise
2. **Unnecessary** - We just need to distinguish "before fault" from "during fault"
3. **Fragile** - Fails when system has minor pre-existing issues

## The Right Approach: Relative Comparison

**Goal**: Find a period before analysis_time that is relatively healthier than current state

**Algorithm**:
1. **Known fault start** (for testing/validation):
   ```python
   baseline_start = fault_start - baseline_window_size
   baseline_end = fault_start
   ```

2. **Unknown fault start** (production):
   - Scan backward from analysis_time
   - Find period with lower health score than current
   - Use most recent relatively healthy period

**Health scoring** (0-10 scale):
- 0-2: Very stable, minimal issues
- 2-4: Some noise, still operational
- 4-7: Elevated issues, degraded performance
- 7-10: Severe degradation

## Testing Strategy

### Phase 1: Validate with Labeled Data

Use `known_fault_start` parameter to test against ground truth:

```python
selector = TimeWindowSelector(metrics_df)
windows = selector.select_windows(
    analysis_time=170s,
    known_fault_start=60s  # From label.json
)

# Validate:
# 1. baseline.end == fault_start (no overlap)
# 2. baseline_health < current_health (relatively better)
# 3. sufficient duration (>20s)
```

### Phase 2: Tune Auto-Detection

Once validation works with `known_fault_start`, tune auto-detection:
- Adjust health_threshold based on actual data
- Test relative comparison logic
- Validate overlap with labeled baselines

### Phase 3: Production Mode

Remove `known_fault_start`, rely on auto-detection:
- Find most recent period that's healthier than current
- No access to fault timing
- Purely data-driven

## Current Status

**TimeWindowSelector implemented** with:
- ✓ Percentage-based windows (robust across episodes)
- ✓ Point-in-time analysis (not episode aggregation)
- ✓ `known_fault_start` mode for testing
- ✗ Auto-detection needs tuning (currently falls back)
- ✗ Health computation needs validation

**Next Steps**:
1. Fix health computation to handle metrics structure
2. Run validation test with `known_fault_start`
3. Verify baselines are relatively healthier
4. Tune auto-detection thresholds based on results

## Implementation for Batch Runner

```python
# In run_rca_batch.py

def prepare_rca_windows(self, analysis_time=None):
    fault_start = self.label.get('fault_start_time', 0)
    fault_full_effect = self.label.get('fault_full_effect_time', fault_start + 30)

    # Suggest analysis time during steady fault state
    if analysis_time is None:
        analysis_time = fault_full_effect + 60  # 60s after full effect

    selector = TimeWindowSelector(
        metrics_df=self.metrics_df,
        episode_start=0,
        episode_end=self.metrics_df['sim_time'].max()
    )

    # For now, use known fault start (testing mode)
    # Later, switch to auto_detect_baseline=True
    windows = selector.select_windows(
        analysis_time=analysis_time,
        known_fault_start=fault_start  # Simple, reliable for testing
    )

    return windows
```

## Key Takeaway

**Don't over-engineer baseline detection yet.**

For initial implementation:
- Use simple pre-fault window when fault_start is known
- Validate this works correctly for RCA
- Only add auto-detection complexity if needed for production

The most important fix is **point-in-time analysis** (not aggregating entire episode). The baseline selection can start simple and be refined later based on actual RCA performance.
