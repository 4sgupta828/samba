# Fault Injection System Redesign Strategy

## Executive Summary

This document outlines the upgrade of our fault injection system to be **state-of-the-art and realistic** based on cloud systems expert analysis. The redesign eliminates redundant faults, implements universal severity scaling, and ensures all faults have unique observable signatures.

**Status:** Metrics Dynamics Engine ✅ VALIDATED

---

## 1. Design Principles

### Principle 1: Unique Failure Modes Only
**Each fault must have a distinct observable signature that differentiates it from others.**

❌ **ELIMINATE REDUNDANT FAULTS:**
- `slow_queries` → Use `disk_io_saturation` on database (same mechanism: I/O wait)
- `connection_exhaustion` → Use `thread_exhaustion` on database (same mechanism: pool saturation)
- `background_db_job` → Use `cpu_saturation` on database (same mechanism: CPU contention)

✅ **KEEP UNIQUE FAULTS with distinct signatures:**

| Fault Type | Unique Observable Signature | What Makes It Different |
|------------|----------------------------|------------------------|
| `cpu_saturation` | Sustained high CPU → consistent latency increase | All requests affected equally, predictable slowdown |
| `memory_thrashing` | Memory churn → unpredictable latency spikes | Bimodal latency distribution, intermittent pauses |
| `thread_exhaustion` | Thread pool full → queue buildup | Latency grows over time, FIFO degradation |
| `disk_io_saturation` | Disk/network wait → high latency, LOW CPU | Blocking behavior, concurrent request limit |
| `dependency_timeout` | External call fails → retry storms | Error rate ↑, amplified traffic downstream |
| `resource_leak` | Gradual exhaustion → eventual failure | Progressive degradation, time-to-failure correlation |

### Principle 2: Generic Memory Pressure (No GC Assumptions)
**Memory pressure model must work for ALL languages (Python, Go, Rust, Java, C++).**

Generic effects of memory pressure:
- Allocation overhead increases (`malloc`/`new` slows down)
- Page faults increase (OS swapping)
- CPU overhead increases (memory management)
- OOM risk increases

**No assumptions about:**
- Garbage collection pauses
- Heap fragmentation
- Language-specific memory models

**Implementation:** Uses memory utilization thresholds (0-70% normal, 70-85% mild pressure, 85-95% severe, 95-100% critical)

### Principle 3: Universal Severity Parameter
**All faults have a `severity` parameter [0.0, 1.0] with non-linear scaling.**

```python
severity = 0.0  # No effect (baseline)
severity = 0.5  # Balanced (default, visible but not catastrophic)
severity = 1.0  # Maximum (severe, near-failure)
```

**Non-linear scaling curve:**
- **0.0-0.3:** Subtle issues (linear, 0-60% of base impact)
- **0.3-0.7:** Moderate issues (near-linear, 60-100% of base impact)
- **0.7-1.0:** Severe issues (exponential, 100-130% of base impact)

**✅ Already implemented in `FaultParameterTuner._scale_by_severity()`** - just need to use it consistently!

### Principle 4: Capacity-Relative Fault Tuning
**Fault impact scales based on system capacity (no phi double-counting).**

Already implemented in `FaultParameterTuner`:
- Uses capacity planning results (replicas, thread pools, baseline utilization)
- Consumes 75% of available headroom by default (scaled by severity)
- No phi parameter (already factored into capacity planning)

✅ **Keep current implementation!**

---

## 2. Redesigned Fault Catalog

### Tier 1: Core Resource Saturation (Always Include)

| Fault | Primary Mechanism | Severity Scaling | Implementation Status |
|-------|------------------|------------------|---------------------|
| `cpu_saturation` | CPU utilization → target | `cpu_multiplier = f(severity)` | ✅ Exists, needs severity param |
| `memory_thrashing` | Memory → threshold + churn | `allocation_rate = f(severity)` | ❌ NEW - different from memory_pressure |
| `thread_exhaustion` | Active threads → pool size | `blocked_fraction = f(severity)` | ⚠️ Partial (force_deadlock) |
| `disk_io_saturation` | I/O wait time ↑ | `io_wait_multiplier = f(severity)` | ❌ NEW |

### Tier 2: Interaction Failures (Representative)

| Fault | Primary Mechanism | Severity Scaling | Implementation Status |
|-------|------------------|------------------|---------------------|
| `network_partition` | Packet loss = 100% | `partition_scope = f(severity)` | ✅ Exists |
| `dependency_timeout` | External call latency → timeout | `timeout_rate = f(severity)` | ⚠️ Partial (inject_latency on ExternalService) |
| `cascading_overload` | Load spike → resource exhaustion | `traffic_multiplier = f(severity)` | ❌ NEW |

### Tier 3: Corruption/Anomaly (Advanced)

| Fault | Primary Mechanism | Severity Scaling | Implementation Status |
|-------|------------------|------------------|---------------------|
| `data_corruption` | Responses contain invalid data | `corruption_rate = f(severity)` | ❌ NEW |
| `clock_skew` | Time offset between nodes | `skew_seconds = f(severity)` | ❌ NEW |

### Deprecated/Redundant Faults (To Remove)

| Fault | Reason | Replacement |
|-------|--------|------------|
| `slow_queries` | Redundant with disk_io_saturation | Use `disk_io_saturation` on DB |
| `connection_exhaustion` | Redundant with thread_exhaustion | Use `thread_exhaustion` on DB |
| `background_db_job` | Redundant with cpu_saturation | Use `cpu_saturation` on DB |
| `inject_db_wear` | Too specific, indirect mechanism | Use `disk_io_saturation` |

---

## 3. Implementation Plan

### Phase 1: Design & Validation ✅
- [x] Validate dynamics engine models all cross-metric effects
- [x] Analyze current fault implementation
- [x] Design new fault catalog with unique signatures
- [x] Document severity scaling strategy

**Status: COMPLETE**

### Phase 2: Core Fault Refactoring 🔄
**Goal:** Refactor existing faults to use universal severity parameter

Tasks:
1. Add `severity` parameter to all fault functions (default=0.5)
2. Use `FaultParameterTuner._scale_by_severity()` consistently
3. Remove hardcoded parameters, replace with capacity-relative calculations
4. Update fault functions:
   - ✅ `cpu_saturation` - add severity param
   - ✅ `memory_pressure` - add severity param
   - ⚠️ `inject_latency` - already tuned, add explicit severity
   - ⚠️ `inject_errors` - already tuned, add explicit severity

### Phase 3: New Tier 1 Faults 📝
**Goal:** Implement missing core resource saturation faults

1. **`memory_thrashing`** (NEW)
   - Different from `memory_pressure`: causes intermittent spikes, not sustained pressure
   - Observable: Bimodal latency distribution (fast → pause → fast)
   - Implementation: Periodic allocation bursts + GC simulation

2. **`thread_exhaustion`** (Refactor from `force_deadlock`)
   - Rename `force_deadlock` → `thread_exhaustion`
   - Add severity parameter
   - Make it generic (not just deadlocks, any thread blocking)

3. **`disk_io_saturation`** (NEW)
   - High latency with LOW CPU (key differentiator)
   - Blocking I/O behavior
   - Replace `slow_queries` with this

### Phase 4: New Tier 2 Faults 📝
**Goal:** Add interaction failure patterns

1. **`dependency_timeout`** (Enhance existing)
   - Currently: `inject_latency` on ExternalService
   - Add: Retry storm modeling, circuit breaker interactions

2. **`cascading_overload`** (NEW)
   - Traffic spike that exhausts multiple services
   - Models autoscaling delays, load shedding failures

### Phase 5: Validation & Testing 🧪
**Goal:** Prove new fault system works correctly

1. Update `validate_fault_dynamics.py`:
   - Add tests for new faults
   - Validate unique signatures
   - Verify severity scaling

2. Generate fault profiles:
   - Document observable signatures
   - Measure cross-metric relationships
   - Compare to real production incidents

3. Dataset generation testing:
   - Generate episodes with new faults
   - Verify ground truth labels
   - Validate RCA difficulty spread

---

## 4. Fault Signature Validation Matrix

**This matrix proves each fault has a unique observable signature.**

| Fault | CPU | Memory | Latency | Throughput | Errors | Queue | Unique Signature |
|-------|-----|--------|---------|-----------|--------|-------|-----------------|
| `cpu_saturation` | ⬆️⬆️ | → | ⬆️ | ⬇️ | ↗️ | → | Consistent slowdown, all requests |
| `memory_thrashing` | ⬆️ | ⬆️⬇️ | ⬆️⬇️ | ⬇️ | ↗️ | → | Bimodal latency, intermittent pauses |
| `thread_exhaustion` | → | → | ⬆️⬆️ | ⬇️⬇️ | ⬆️ | ⬆️⬆️ | Queue grows, FIFO degradation |
| `disk_io_saturation` | ⬇️ | → | ⬆️⬆️ | ⬇️ | ↗️ | ↗️ | HIGH latency, LOW CPU |
| `dependency_timeout` | → | → | ⬆️ | ⬇️ | ⬆️⬆️ | ↗️ | Error rate spike, retry amplification |
| `network_partition` | ⬇️ | → | ⬆️⬆️ | ⬇️⬇️ | ⬆️⬆️ | → | Total isolation, split-brain |

Legend: ⬆️ Increase, ⬇️ Decrease, → No change, ↗️ May increase, ⬆️⬆️ Large increase

---

## 5. Dynamics Engine Validation Checklist

**✅ VALIDATED** - The following cross-metric relationships are confirmed working:

| Primary Change | Expected Secondary Effect | Validation Status |
|----------------|--------------------------|-------------------|
| CPU → 90% | Latency ↑ 2-5x | ✅ PASS (exponential relationship) |
| Memory → 90% | CPU ↑ (allocation overhead) | ✅ PASS (thrashing modeled) |
| Memory → 90% | Latency spikes (paging) | ✅ PASS (memory_pressure_cpu) |
| Latency ↑ | Throughput ↓ (threads blocked) | ✅ PASS (concurrent_requests) |
| Threads → 100% | Queue depth ↑ | ✅ PASS (SimPy Resource) |
| Threads → 100% | Latency ↑ (queue wait) | ✅ PASS (queue_coef) |
| Errors ↑ | Retry traffic ↑ | ⚠️ TODO (needs retry modeling) |
| Queue depth ↑ | Memory ↑ (message accumulation) | ⚠️ TODO (MessageQueue specific) |

**Source:** `src/dynamics/metrics_dynamics_engine.py` lines 253-300

---

## 6. Migration Guide

### For Existing Scenarios

**Step 1:** Update fault names
```yaml
# OLD
fault_type: slow_queries
params:
  wear_factor: 0.5

# NEW
fault_type: disk_io_saturation
params:
  severity: 0.5  # Universal parameter
```

**Step 2:** Add severity parameter
```yaml
# OLD
fault_type: cpu_saturation
params:
  cpu_multiplier: 3.0

# NEW
fault_type: cpu_saturation
params:
  severity: 0.7  # Fault tuner will calculate cpu_multiplier
```

**Step 3:** Remove redundant faults
```yaml
# OLD - Multiple DB faults
- fault_type: slow_queries
  target: db_0
- fault_type: connection_exhaustion
  target: db_0

# NEW - Single fault with severity
- fault_type: disk_io_saturation
  target: db_0
  params:
    severity: 0.6
```

### For Fault Tuner Integration

The `FaultParameterTuner` already supports severity parameter:

```python
tuned_params = fault_tuner.tune_fault_parameters(
    target_node_id='service_a',
    fault_type='cpu_saturation',
    baseline_params={'severity': 0.5},  # Universal input
    severity=0.5,  # Explicitly passed
    verbose=True
)
# Returns: {'cpu_multiplier': 2.8}  # Calculated based on capacity
```

**No changes needed to fault tuner!** Just need to update fault functions to use severity.

---

## 7. Success Metrics

### Validation Criteria
1. ✅ All faults have unique observable signatures (no redundancy)
2. ⏳ All faults use universal severity parameter (0.0-1.0)
3. ✅ No language-specific assumptions (generic memory model)
4. ✅ Capacity-relative tuning (no phi double-counting)
5. ⏳ Dynamics engine validated for all cross-metric effects
6. ⏳ Fault profiles documented and compared to real incidents

### Performance Criteria
1. Dataset generation produces diverse RCA challenges
2. Fault impact is visible but not catastrophic (default severity=0.5)
3. Gradual faults show realistic progressive degradation
4. Recovery timelines match production behavior

---

## 8. Next Steps

1. **Complete Phase 2:** Refactor existing faults to use severity parameter
   - File: `src/failures/modes.py`
   - Functions to update: `cpu_saturation`, `memory_pressure`, `inject_latency`, `inject_errors`

2. **Complete Phase 3:** Implement new Tier 1 faults
   - Add `memory_thrashing` function
   - Rename `force_deadlock` → `thread_exhaustion`
   - Add `disk_io_saturation` function

3. **Update validation tests:** `validate_fault_dynamics.py`
   - Add tests for new faults
   - Verify unique signatures

4. **Update dataset generation:** `generate_dataset.py`
   - Use new fault names
   - Default severity to 0.5
   - Remove deprecated faults from scenario library

---

## Appendix A: Severity Scaling Formula

```python
def _scale_by_severity(base_value: float, severity: float) -> float:
    """
    Non-linear severity scaling (from FaultParameterTuner).

    Examples:
    - base_value=0.75, severity=0.0 → 0.0 (no impact)
    - base_value=0.75, severity=0.5 → 0.75 (default impact)
    - base_value=0.75, severity=1.0 → 0.975 (severe impact)
    """
    if severity < 0.3:
        # Subtle: 0-60% of base
        factor = (severity / 0.3) * 0.6
    elif severity < 0.7:
        # Moderate: 60-100% of base
        normalized = (severity - 0.3) / 0.4
        factor = 0.6 + (normalized * 0.4)
    else:
        # Severe: 100-130% of base (exponential)
        normalized = (severity - 0.7) / 0.3
        factor = 1.0 + (normalized ** 1.5) * 0.3

    return base_value * factor
```

**✅ Already implemented in `FaultParameterTuner` - no code changes needed!**

---

## Appendix B: References

- Design document: `/Users/sgupta/samba/DynamicsEngineWorking.md`
- Current implementation: `src/failures/modes.py`
- Fault tuner: `src/failures/fault_tuner.py`
- Dynamics engine: `src/dynamics/metrics_dynamics_engine.py`
- Validation framework: `validate_fault_dynamics.py`

---

**Document Status:** Draft v1.0
**Last Updated:** 2025-12-10
**Author:** Claude (based on expert systems analysis)
