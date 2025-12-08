# Solution to the 0→X Problem

## Problem Statement

The current system treats all 0→X transitions equally:
- 0→0.01 shows as "10000% increase"
- 0→10.0 shows as "10000% increase"

This is misleading because:
1. **Context matters**: 1 error might be negligible for high-throughput services but catastrophic for low-throughput
2. **Absolute magnitude matters**: 0.01→0.02 (100% increase) is less important than 50→100 (100% increase)
3. **Metric type matters**: 1ms latency increase is different from 1 error

## Solution Implemented

### Module: `contextual_severity.py`

This module provides a new function `compute_contextual_severity()` that:

1. **Considers Absolute Magnitude**
   - Not just "X% increase" but "increased BY Y units"
   - Example: 0→1 error vs 0→100 errors

2. **Normalizes by Throughput** (for error metrics)
   - 10 errors / 100 requests = 10% error rate (CRITICAL)
   - 10 errors / 10,000 requests = 0.1% error rate (LOW)

3. **Uses Metric-Specific Thresholds**
   - **Error metrics**: Threshold by error rate or absolute count
   - **Latency metrics**: <10ms good, 10-100ms moderate, >1000ms critical
   - **Saturation metrics**: Absolute levels (queue depth > 100 = critical)
   - **Resource metrics**: Percentage thresholds (>90% = critical)

4. **Weights Both Relative AND Absolute**
   - Latency +100ms is significant even if only 20% increase
   - Latency +1000ms is critical regardless of percentage

## How It Works

### Example 1: Error Metrics

**Scenario A**: Low-throughput service
```python
baseline_mean = 0.0  # No errors
fault_mean = 2.0     # 2 errors per sample
throughput = 20 requests/sample

error_rate = 2/20 = 10%
→ Score: 1.0 (CRITICAL)
→ Reasoning: "10% error rate - CRITICAL"
```

**Scenario B**: High-throughput service
```python
baseline_mean = 0.0
fault_mean = 2.0
throughput = 2000 requests/sample

error_rate = 2/2000 = 0.1%
→ Score: 0.3 (LOW)
→ Reasoning: "0.1% error rate - LOW"
```

### Example 2: Latency Metrics

**Scenario A**: Small absolute increase
```python
baseline = 10ms
fault = 15ms
delta = +5ms
relative = 50%

→ Score: 0.3 (LOW)
→ Reasoning: "Minor latency change: 10→15ms"
```

**Scenario B**: Large absolute increase
```python
baseline = 100ms
fault = 250ms
delta = +150ms
relative = 150%

→ Score: 0.6 (MEDIUM-HIGH)
→ Reasoning: "Significant latency increase: +150ms"
```

**Scenario C**: Critical absolute level
```python
baseline = 500ms
fault = 1500ms
delta = +1000ms

→ Score: 0.9 (CRITICAL)
→ Reasoning: "Critical latency: >1000ms"
```

## Integration Points

### Option 1: Direct Integration (Recommended)

Modify `compute_severity_score()` in `metric_impact_analyzer.py`:

```python
from analysis.sotaanalyzer.contextual_severity import compute_contextual_severity

def compute_severity_score(
    metric_name: str,
    distribution_comparison: Dict,
    effect_sizes: Dict,
    pattern_changes: Dict,
    changepoint: Dict,
    baseline_characterization: Dict,  # NEW
    fault_characterization: Dict,     # NEW
    throughput_context: Optional[Dict] = None  # NEW
) -> Tuple[float, str]:
    """Enhanced severity scoring with contextual awareness."""

    # Extract key values
    baseline_mean = baseline_characterization['location']['mean']
    fault_mean = fault_characterization['location']['mean']
    baseline_std = baseline_characterization['spread']['std']
    fault_std = fault_characterization['spread']['std']

    relative_change = effect_sizes.get('mean_pct_change', 0.0)
    cohens_d = effect_sizes.get('cohens_d', 0.0)

    # Use contextual severity (handles 0→X properly)
    contextual_score, reasoning, details = compute_contextual_severity(
        metric_name,
        baseline_mean,
        fault_mean,
        baseline_std,
        fault_std,
        relative_change,
        cohens_d,
        throughput_context
    )

    # Blend with existing statistical scores
    # ... rest of scoring logic
```

### Option 2: Post-Processing Adjustment

Add adjustment layer after existing scoring:

```python
# After computing raw severity_score
if is_zero_to_x_transition(baseline_mean, fault_mean):
    adjusted_score, reasoning = adjust_zero_to_x_score(
        metric_name, baseline_mean, fault_mean,
        raw_score, throughput_context
    )
```

### Option 3: Parallel Scoring System

Run both systems and compare:

```python
# Existing system
legacy_score = compute_severity_score_legacy(...)

# New contextual system
contextual_score = compute_contextual_severity(...)

# Use contextual for 0→X, legacy for others
if baseline_mean == 0 and fault_mean > 0:
    final_score = contextual_score
else:
    final_score = legacy_score
```

## Throughput Context Collection

To enable error rate normalization, collect throughput during analysis:

```python
def analyze_all_node_metrics(
    metrics_df: pd.DataFrame,
    node_id: str,
    fault_start_time: float
) -> Dict[str, MetricImpactResult]:
    """Enhanced with throughput context."""

    # First, get request metrics to compute throughput
    request_metrics = metrics_df[
        (metrics_df['labels'].apply(lambda x: x.get('component.id') == node_id)) &
        (metrics_df['name'].str.contains('request', case=False))
    ]

    if len(request_metrics) > 0:
        baseline_requests = request_metrics[
            request_metrics['labels'].apply(lambda x: x.get('sim.time', 0) < fault_start_time)
        ]['value'].sum()

        fault_requests = request_metrics[
            request_metrics['labels'].apply(lambda x: x.get('sim.time', 0) >= fault_start_time)
        ]['value'].sum()

        throughput_context = {
            'baseline_requests': baseline_requests,
            'fault_requests': fault_requests,
            'requests_per_sec': fault_requests / 120  # Assuming 120s fault window
        }
    else:
        throughput_context = None

    # Pass to metric analysis
    for metric_name in node_metrics:
        result = analyze_metric_impact(
            metric_name, times, values, fault_start_time,
            throughput_context=throughput_context  # NEW
        )
```

## Testing

Test cases to validate:

### Test 1: Error Rate Normalization
```python
# Low throughput
assert score_error(baseline=0, fault=2, throughput=20) > 0.8  # 10% rate

# High throughput
assert score_error(baseline=0, fault=2, throughput=2000) < 0.4  # 0.1% rate
```

### Test 2: Latency Thresholds
```python
assert score_latency(baseline=0, fault=5) < 0.4     # 5ms = LOW
assert score_latency(baseline=0, fault=500) > 0.6   # 500ms = HIGH
assert score_latency(baseline=0, fault=1500) > 0.8  # 1.5s = CRITICAL
```

### Test 3: Saturation Levels
```python
assert score_saturation(baseline=0, fault=5) < 0.4    # 5 items = LOW
assert score_saturation(baseline=0, fault=50) > 0.6   # 50 items = HIGH
assert score_saturation(baseline=0, fault=150) > 0.8  # 150 items = CRITICAL
```

## Benefits

✅ **Accuracy**: 0→0.01 no longer equals 0→100
✅ **Context-Aware**: Error rates normalized by throughput
✅ **Intuitive**: Uses domain-specific thresholds (10ms, 100ms, 1s)
✅ **Flexible**: Works with or without throughput context
✅ **Gradual**: Can be integrated incrementally

## Status

- ✅ **Module Created**: `contextual_severity.py`
- ⏳ **Integration Pending**: Needs update to `metric_impact_analyzer.py`
- ⏳ **Throughput Collection**: Needs update to data collection
- ⏳ **Testing**: Needs validation on real episodes

## Next Steps

1. **Quick Win**: Integrate for error metrics only (highest impact)
2. **Phase 2**: Add latency and saturation metrics
3. **Phase 3**: Collect throughput context systematically
4. **Phase 4**: Validate on large dataset and tune thresholds

## Example Usage

```python
from analysis.sotaanalyzer.contextual_severity import compute_contextual_severity

# Error metric with throughput
score, reasoning, details = compute_contextual_severity(
    metric_name="service.errors",
    baseline_mean=0.0,
    fault_mean=5.0,
    baseline_std=0.0,
    fault_std=2.0,
    relative_change_pct=10000.0,  # Bogus infinity value
    cohens_d=3.5,
    throughput_context={
        'fault_requests': 1000.0,
        'requests_per_sec': 10.0
    }
)

print(f"Score: {score}")  # 0.6
print(f"Reasoning: {reasoning}")  # "Errors appeared: 5.0 errors (0.5% error rate) - MEDIUM"
```

This fixes the 0→X problem systematically and provides a path for gradual integration.
