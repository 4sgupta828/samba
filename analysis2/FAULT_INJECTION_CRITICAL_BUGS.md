# Critical Fault Injection Bugs - Root Cause Analysis

**Date**: 2025-12-15
**Status**: CRITICAL BLOCKER for RCA Testing
**Impact**: 50% of fault injections don't create observable symptoms in metrics

## Executive Summary

The fault injection system has **a critical architectural bug** where gradual fault injection for `inject_latency` and `inject_errors` modifies the wrong attributes, causing faults to have no effect on components with dynamics engines. Additionally, several hardcoded configuration values don't scale across different topologies and system sizes.

### Critical Issues Found

1. ❌ **CRITICAL BUG**: `inject_latency` and `inject_errors` gradual injection doesn't work with dynamics engine
2. ⚠️ **Scaling Issue**: Hardcoded latency bounds don't work for all topology sizes
3. ⚠️ **Design Issue**: Memory thrashing has hardcoded timing parameters
4. ℹ️ **Potential Issue**: Capacity planner may underestimate burst capacity

---

## Issue 1: CRITICAL BUG - Gradual Latency/Error Injection Broken

### The Problem

**Root Cause**: The `apply_infrastructure_change` mechanism modifies legacy component attributes (`injected_latency_ms`, `forced_error_rate`) instead of the dynamics engine fault attributes (`dynamics.fault_latency_additive_ms`, `dynamics.fault_error_additive`).

### Evidence

#### File: `src/components/base_component.py:397-402`

```python
param_mapping = {
    'latency_ms': 'injected_latency_ms',      # ❌ WRONG: Legacy attribute
    'error_rate': 'forced_error_rate',        # ❌ WRONG: Legacy attribute
    'cpu_cost_multiplier': 'cpu_cost_multiplier',  # ✅ OK: Used by dynamics
}
```

**Problem**: `apply_infrastructure_change` sets `injected_latency_ms` and `forced_error_rate` on the base component.

#### File: `src/failures/modes.py:32-50`

```python
def inject_latency(component: SimulatedComponent, params: Dict[str, Any]):
    """ADDITIVE FAULT: Adds fixed latency on top of natural latency."""
    latency_ms = params.get("latency_ms", 500)

    # For components with dynamics engine, set dynamics fault
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_latency_additive_ms = latency_ms  # ✅ Correct attribute
        component._emit_log("WARN", f"Latency injection (dynamics): +{latency_ms}ms")

    # ALSO set direct attribute for components that use it directly (like ExternalService)
    if hasattr(component, 'injected_latency_ms'):
        component.injected_latency_ms = latency_ms
        component._emit_log("WARN", f"Latency injection (direct): +{latency_ms}ms")
```

**The Disconnect**: The `inject_latency` function correctly sets `dynamics.fault_latency_additive_ms` for components with dynamics, but `apply_infrastructure_change` modifies `injected_latency_ms` instead.

#### File: `src/dynamics/metrics_dynamics_engine.py:371-372`

```python
# Apply ADDITIVE fault (e.g., inject_latency)
target_latency += self.fault_latency_additive_ms  # ✅ Reads from dynamics attribute
```

**Result**: Gradual latency injection has NO EFFECT because:
1. `training_injector.py:512-517` calls `apply_infrastructure_change('latency_ms', delta, ...)`
2. This sets `component.injected_latency_ms`
3. But dynamics engine reads from `component.dynamics.fault_latency_additive_ms`
4. The fault is never applied to metrics!

### Same Issue with inject_errors

#### File: `src/failures/modes.py:562-580`

```python
def inject_errors(component: SimulatedComponent, params: Dict[str, Any]):
    """ADDITIVE FAULT: Adds base error rate on top of natural errors."""
    error_rate = params.get("error_rate", 0.1)

    # For components with dynamics engine, set dynamics fault
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_error_additive = error_rate  # ✅ Correct attribute

    # ALSO set direct attribute for components that use it directly
    if hasattr(component, 'forced_error_rate'):
        component.forced_error_rate = error_rate
```

#### File: `src/dynamics/metrics_dynamics_engine.py:401-402`

```python
# Apply ADDITIVE fault (e.g., inject_errors) - adds base error rate
target_error += self.fault_error_additive  # ✅ Reads from dynamics attribute
```

**Same problem**: `apply_infrastructure_change('error_rate', delta, ...)` sets `component.forced_error_rate`, but dynamics reads from `component.dynamics.fault_error_additive`.

### Impact

- **inject_latency faults don't create latency increases**: Metrics show 74.75ms baseline vs 74.75ms fault (no change)
- **inject_errors faults don't create error rate increases**: Metrics show no error rate changes
- **50% RCA failure rate**: 8 out of 9 failures due to this bug

### The Fix

**Option 1: Update param_mapping to use dynamics attributes (RECOMMENDED)**

```python
# File: src/components/base_component.py:397-402
param_mapping = {
    'latency_ms': 'dynamics.fault_latency_additive_ms',  # ✅ Use dynamics
    'error_rate': 'dynamics.fault_error_additive',       # ✅ Use dynamics
    'cpu_cost_multiplier': 'cpu_cost_multiplier',
}
```

And update the setter logic to handle nested attributes:

```python
# File: src/components/base_component.py:404-410
if '.' in actual_param:
    # Handle nested attributes like 'dynamics.fault_latency_additive_ms'
    parts = actual_param.split('.')
    obj = self
    for part in parts[:-1]:
        obj = getattr(obj, part)
        if obj is None:
            print(f"[{self.id}] WARNING: Cannot access nested attribute '{actual_param}'")
            return
    actual_param_name = parts[-1]
else:
    obj = self
    actual_param_name = actual_param

if not hasattr(obj, actual_param_name):
    print(f"[{self.id}] WARNING: Object does not have parameter '{actual_param_name}'")
    return

initial_value = getattr(obj, actual_param_name)
target_value = initial_value + delta

# ... apply gradual change to obj with actual_param_name
```

**Option 2: Make training_injector bypass apply_infrastructure_change**

For `inject_latency` and `inject_errors`, directly manipulate `dynamics.fault_latency_additive_ms` and `dynamics.fault_error_additive` in the gradual change loop instead of using `apply_infrastructure_change`.

---

## Issue 2: Hardcoded Latency Bounds Don't Scale

### The Problem

**File**: `src/failures/fault_tuner.py:283`

```python
# Bound to reasonable range
required_added_latency_ms = max(200.0, min(1000.0, required_added_latency_ms))
tuned['latency_ms'] = int(required_added_latency_ms)
```

**Issue**: The bounds `[200ms, 1000ms]` are hardcoded and don't scale with:
- Topology size (small vs large systems)
- Service capacity (1 replica vs 50 replicas)
- Baseline latency (10ms service vs 500ms service)

### Example Failure Case

**Scenario**: Microservice with:
- 1 replica
- 10 threads per replica
- Baseline latency: 50ms
- Target RPS: 5 (low traffic)

**Calculated latency**: 50ms (correct for this small system)
**After bounds**: 200ms (4x too high, causes catastrophic failure)

### The Fix

Make bounds **capacity-relative** instead of absolute:

```python
# File: src/failures/fault_tuner.py:283
# Calculate bounds based on baseline latency and capacity
min_latency_ms = baseline_latency_ms * 1.5  # At least 50% increase
max_latency_ms = baseline_latency_ms * 10.0  # At most 10x increase

required_added_latency_ms = max(min_latency_ms, min(max_latency_ms, required_added_latency_ms))
tuned['latency_ms'] = int(required_added_latency_ms)
```

**Rationale**: A service with 20ms baseline latency should be bounded to [30ms, 200ms], not [200ms, 1000ms].

---

## Issue 3: Memory Thrashing Has Hardcoded Timing Parameters

### The Problem

**File**: `src/failures/modes.py:385-390`

```python
# Burst frequency: How often to thrash (seconds between bursts)
base_period_sec = 10.0  # ❌ Hardcoded: every 10 seconds
burst_period_sec = base_period_sec * (1.5 - severity)

# Burst duration: How long each allocation burst lasts
base_duration_sec = 2.0  # ❌ Hardcoded: 2 second burst
burst_duration_sec = base_duration_sec * (0.5 + severity)
```

**Issue**: For systems with different characteristics:
- **High-frequency systems** (1000+ RPS): 10s period = rare thrashing, won't show symptoms
- **Low-frequency systems** (5 RPS): 2s burst = dominates all requests, too severe
- **Large capacity systems**: Fixed timing doesn't account for recovery capacity

### Impact

- `memory_thrashing` has inconsistent metric impact (RCA_IMPROVEMENTS_SUMMARY.md line 128)
- Some systems show no degradation, others show negative impact (0.78x latency - counterintuitive)

### The Fix

Make timing **capacity-aware**:

```python
# File: src/failures/modes.py:385-390
# Calculate burst period based on RPS and capacity
# Goal: Thrash frequently enough to impact metrics, but not so often that system can't recover
rps = getattr(component, '_estimated_rps', 10.0)  # Get from capacity planning
base_period_sec = max(5.0, min(30.0, 100.0 / rps))  # Higher RPS = shorter period

# Burst duration should be proportional to request duration
avg_latency_sec = getattr(component.dynamics, 'latency_ms', 100.0) / 1000.0
base_duration_sec = max(1.0, avg_latency_sec * 10.0)  # Cover ~10 requests
```

---

## Issue 4: Capacity Planner May Underestimate Burst Capacity

### The Problem

**File**: `src/core/capacity_planner.py:266-270`

```python
# BURST FACTOR: Account for P95 production spikes (not just mean)
burst_factor = 1.3  # ❌ Hardcoded

# DRAIN MARGIN: Consumer must exceed production to drain queue
drain_margin = 1.2  # ❌ Hardcoded
```

**Issue**: These constants assume:
- All workloads have 1.3x burst factor (P95/P50 ratio)
- All queues need 20% drain margin

In reality:
- **Bursty workloads** (e.g., cron jobs): P95/P50 ratio can be 3-5x
- **Stable workloads** (e.g., streaming): P95/P50 ratio ~1.1x
- **Large queues** with high latency variance: Need >20% margin

### Impact

- Async consumers may be **under-provisioned** for bursty workloads
- Queues can build up even without faults, masking fault symptoms
- RCA may incorrectly blame queue consumers when capacity planning was wrong

### The Fix

Make burst/drain factors **workload-aware**:

```python
# File: src/core/capacity_planner.py:266-273
# Calculate burst factor from workload characteristics
workload_pattern = self.semantic_map.get('workload_pattern', 'steady')

if workload_pattern == 'bursty' or workload_pattern == 'diurnal':
    burst_factor = 2.0  # Higher variance
elif workload_pattern == 'steady':
    burst_factor = 1.2  # Low variance
else:
    burst_factor = 1.5  # Conservative default

# Drain margin scales with latency variance
# High latency systems need more headroom to absorb variance
drain_margin = 1.2 + (effective_processing_ms / 1000.0)  # +0.1 per 100ms latency
```

---

## Summary of Fixes

| Issue | Priority | Files to Change | Estimated Effort |
|-------|----------|-----------------|------------------|
| **Gradual latency/error injection** | 🔴 CRITICAL | `base_component.py` | 1-2 hours |
| **Hardcoded latency bounds** | 🟠 HIGH | `fault_tuner.py` | 30 minutes |
| **Memory thrashing timing** | 🟡 MEDIUM | `modes.py` | 1 hour |
| **Capacity burst factors** | 🟢 LOW | `capacity_planner.py` | 30 minutes |

### Expected Impact After Fixes

**Current**: 9/18 (50%) RCA success rate
**Expected**: 15-16/18 (83-89%) RCA success rate

Remaining failures:
- `global_network` (not in topology) - 1 case (expected)
- Edge cases with partial symptoms - 1-2 cases

---

## Testing Plan

### 1. Unit Test for Gradual Injection

```python
# Test that apply_infrastructure_change actually affects dynamics
def test_gradual_latency_injection():
    component = create_test_component_with_dynamics()

    # Apply gradual latency injection
    component.apply_infrastructure_change('latency_ms', delta=500.0, duration=10.0)

    # Advance simulation
    env.run(until=env.now + 5.0)

    # Check that dynamics fault is set
    assert component.dynamics.fault_latency_additive_ms > 0, "Fault not applied to dynamics!"

    # Check that metrics show increased latency
    component.dynamics.update(dt=1.0, external_throughput=10.0)
    assert component.dynamics.latency_ms > component.dynamics.config.latency_base + 200, "Latency not increased!"
```

### 2. Integration Test with generate_dataset.py

```bash
# Generate single episode with inject_latency fault
python generate_dataset.py \
  --episodes 1 \
  --output data/test_latency_fix \
  --force-fault-type inject_latency \
  --verbose

# Check that metrics show latency increase
python validate_simulation_data.py data/test_latency_fix/ep_0 --check-fault-impact
```

### 3. Batch RCA Test

```bash
# Generate batch with all fault types
python batch_generate_datasets.py --episodes 18

# Run RCA batch analysis
cd analysis2
python run_rca_batch.py ../data/batch_run/data_20251215_*

# Expected: >80% success rate
```

---

## References

- **RCA_IMPROVEMENTS_SUMMARY.md**: Documents 50% failure rate due to missing symptoms
- **SYMPTOM_DETECTION_GAPS.md**: Identifies latency/error detection as root cause
- **base_component.py:397-458**: Gradual infrastructure change implementation
- **modes.py:32-598**: Fault mode implementations
- **fault_tuner.py:209-297**: Latency fault tuning logic
- **capacity_planner.py:222-300**: Async consumer capacity calculation
- **metrics_dynamics_engine.py:162-407**: Dynamics fault application

---

## Next Steps

1. **Fix critical bug** (Issue 1): Update `param_mapping` to use dynamics attributes
2. **Test fix**: Run unit tests and integration tests
3. **Fix scaling issues** (Issues 2-4): Update bounds and constants
4. **Re-run batch RCA**: Validate 80%+ success rate
5. **Update documentation**: Document new capacity-aware parameters
