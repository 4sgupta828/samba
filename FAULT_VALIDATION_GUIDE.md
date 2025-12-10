# Fault Dynamics Validation Framework

## Purpose

This is our **GOLD STANDARD** for understanding fault behavior. It:

1. ✅ **Validates dynamics engine** - Proves cross-metric effects work correctly
2. ✅ **Documents fault behavior** - Creates reference profiles for each fault
3. ✅ **Ensures realism** - Verifies simulation matches real distributed systems
4. ✅ **Enables tuning** - Provides data for calibrating fault parameters
5. ✅ **Prevents regressions** - Automated tests catch breaking changes

---

## Usage

### Run Full Validation Suite

```bash
python validate_fault_dynamics.py
```

**Output:**
- Console report of all validations
- `fault_dynamics_validation_results.json` with detailed profiles

### Expected Results

```
FAULT DYNAMICS VALIDATION - Gold Standard
================================================================================

Testing: cpu_saturation (severity=0.5)
────────────────────────────────────────────────────────────────────────────────
[Test] CPU Saturation
  Expected: CPU↑ → Latency↑, Throughput↓

Primary Effect:
  ✓ CPU: 40% → 85% (+45%, target achieved)

Secondary Effects:
  ✓ Latency: 50ms → 125ms (2.5x, within expected 2-4x range)
  ✓ Throughput: 100 RPS → 70 RPS (0.7x, expected degradation)
  ✓ Error rate: 0% → 2% (acceptable timeouts)

Cross-Metric Validation:
  ✓ CPU ↑ 45% → Latency ↑ 2.5x ✓ (expected 2-4x)
  ✓ Latency ↑ 2.5x → Throughput ↓ 0.7x ✓ (expected 0.6-0.8x)

✅ PASSED - cpu_saturation behaves as expected
```

---

## Validation Matrix

### What Each Fault Should Show

| Fault Type | Primary Effect | Secondary Effects | Validation Criteria |
|------------|---------------|-------------------|---------------------|
| **cpu_saturation** | CPU → 85% | Latency ↑ 2-4x<br>Throughput ↓ 0.6-0.8x<br>Errors ↑ 0-5% | CPU reaches target<br>Latency increases<br>Proportional relationship |
| **memory_pressure** | Memory → 90% | CPU ↑ 1.2-1.5x (overhead)<br>Latency P99/P50 ↑ 3-5x<br>Intermittent spikes | Memory reaches target<br>Bimodal latency<br>CPU overhead visible |
| **thread_exhaustion** | Threads → 95% | Queue depth ↑ >0<br>Latency ↑ (queue wait)<br>Rejections start | Threads saturated<br>Queue grows<br>Eventual errors |
| **io_bottleneck** | I/O wait ↑ | Latency ↑ 3-5x<br>CPU ↓ 0.5-0.7x<br>Throughput ↓ 0.4-0.6x | **High latency + LOW CPU**<br>(Distinguishes from CPU sat) |
| **network_partition** | Packet loss = 100% | Errors → 90-100%<br>Timeouts → ∞<br>Split state | Complete isolation<br>Timeout behavior<br>No cross-partition calls |
| **dependency_timeout** | Timeout rate → X% | Errors ↑ proportional<br>Retry traffic ↑ 1.5-2x<br>Latency ↑ 1.5-2.5x | Errors match timeout rate<br>Traffic amplification<br>Downstream sees spike |

---

## Cross-Metric Relationship Table

This is what the dynamics engine MUST model correctly:

### Services

| If This Changes | Then This Changes | Expected Relationship | Tolerance |
|-----------------|-------------------|----------------------|-----------|
| CPU ↑ 50% | Latency | ↑ 1.5-3.0x | ±20% |
| CPU ↑ 50% | Throughput | ↓ 0.6-0.8x | ±15% |
| Memory ↑ to 90% | CPU | ↑ 1.2-1.5x (overhead) | ±15% |
| Memory ↑ to 90% | Latency P99/P50 | ↑ 3-5x (bimodal) | ±30% |
| Threads → 100% | Queue depth | ↑ >0 | Must increase |
| Threads → 100% | Latency | ↑ proportional to queue | ±25% |
| Latency ↑ 2x | Throughput | ↓ 0.5-0.7x (threads blocked) | ±20% |
| Errors ↑ 30% | Retry traffic | ↑ 1.3-1.6x | ±15% |

### Databases

| If This Changes | Then This Changes | Expected Relationship | Tolerance |
|-----------------|-------------------|----------------------|-----------|
| Query latency ↑ 2x | Connection hold time | ↑ 2x | ±10% |
| Query latency ↑ 2x | Client thread blocking | Increases | Must occur |
| Connections → max | New query wait time | ↑ significantly | Must block |
| Connections → max | Client errors | ↑ (timeouts) | Must occur |

### Queues

| If This Changes | Then This Changes | Expected Relationship | Tolerance |
|-----------------|-------------------|----------------------|-----------|
| Consumer rate ↓ 50% | Queue depth | ↑ over time | Must grow |
| Queue depth ↑ 1000 | Message age | ↑ linearly | ±20% |
| Message age > visibility timeout | Redelivery rate | ↑ | Must occur |
| Queue depth → max | Publisher backpressure | Activates | Must occur |

---

## How to Add New Fault Validations

### 1. Define Expected Behavior

```python
def _validate_new_fault(self, severity: float) -> FaultProfile:
    """
    Validate [fault name].

    Expected behavior:
    - PRIMARY: [What you directly set]
    - SECONDARY:
      * [Effect 1 from dynamics]
      * [Effect 2 from dynamics]
      * [Effect 3 from dynamics]
    """
```

### 2. Run Isolated Test

```python
# Create minimal topology
# Inject fault only (no other faults)
# Run for sufficient duration (baseline → fault → recovery)
```

### 3. Collect All Metrics

```python
metrics = []
for t in [baseline, fault, recovery]:
    metrics.append(MetricSnapshot(
        timestamp=t,
        cpu_utilization=measure_cpu(),
        memory_utilization=measure_memory(),
        avg_latency_ms=measure_latency_avg(),
        p99_latency_ms=measure_latency_p99(),
        throughput_rps=measure_throughput(),
        error_rate=measure_errors(),
        active_threads=measure_threads(),
        queue_depth=measure_queue()
    ))
```

### 4. Validate Relationships

```python
# Check primary effect achieved
assert fault_metrics['cpu'] >= target_cpu * 0.95

# Check secondary effects in expected range
passed, msg = self.validate_cross_metric_relationship(
    'cpu', +0.5,  # Primary change
    'latency', (1.5, 3.0),  # Expected secondary change
    actual_latency_change  # Measured change
)
```

---

## Integration with Fault Tuning

Once validated, use profiles to tune fault parameters:

```python
# From validation profile
profile = validator.results['cpu_saturation']

# We learned: CPU ↑ 50% → Latency ↑ 2.5x
cpu_to_latency_factor = 2.5 / 0.5  # = 5.0

# Use in fault tuner
def tune_cpu_saturation(target_cpu_increase):
    expected_latency_increase = target_cpu_increase * cpu_to_latency_factor
    # Adjust severity if latency would be too high
    if expected_latency_increase > 5.0:
        return 'reduce_severity'
```

---

## Success Criteria

✅ **Validation passes when:**
1. Primary effect achieves target (±5%)
2. All secondary effects fall within expected ranges
3. Cross-metric relationships are proportional
4. No unexpected effects occur
5. Recovery returns to baseline (±10%)

❌ **Validation fails when:**
1. Primary effect not achieved
2. Secondary effects outside expected range
3. Cross-metric relationships broken (e.g., CPU ↑ but latency ↓)
4. Unexpected effects observed
5. Recovery doesn't restore baseline

---

## Next Steps

1. **Implement metric collection** in validation framework
2. **Run validation suite** for all faults
3. **Document actual relationships** (may differ from expectations)
4. **Tune fault parameters** based on validated profiles
5. **Add to CI/CD** as regression tests

---

## Philosophy

> **"We don't inject faults to break systems. We inject faults to understand how systems break."**

This validation framework ensures:
- Our faults are **realistic** (match real system behavior)
- Our dynamics are **accurate** (cross-effects modeled correctly)
- Our training data is **trustworthy** (GNN learns real patterns)

**If validation fails → Fix dynamics engine, not fault injection.**
