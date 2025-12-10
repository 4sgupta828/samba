# Fault Injection Redesign - Implementation Plan

## Current Status

✅ **Completed:**
1. First principles design (see `FaultInjectionDesign.md`)
2. Validation framework (`validate_fault_dynamics.py`)
3. Gold standard documentation (`FAULT_VALIDATION_GUIDE.md`)

🚧 **In Progress:**
- Working cpu_saturation implementation (using cpu_cost_multiplier)
- Capacity-aware tuning (using component profiles)

❌ **Needs Work:**
- Dynamics engine validation
- Remove phi from fault tuning
- Eliminate redundant faults
- Add severity parameter

---

## Phase 1: Validate Dynamics Engine (CRITICAL)

**Priority: HIGHEST - This proves everything else works**

### Tasks:

1. **Implement metric collection in validator**
   ```python
   # In validate_fault_dynamics.py
   def collect_metrics(self, component, duration) -> List[MetricSnapshot]:
       # Collect CPU, memory, latency, throughput, errors, queue depth
       # Return time series of all metrics
   ```

2. **Create minimal test topology**
   ```python
   # Simple service → database topology
   # No complex dependencies
   # Just enough to test each fault type
   ```

3. **Run validation for cpu_saturation first**
   ```bash
   python validate_fault_dynamics.py --fault cpu_saturation
   ```

   **Expected result:**
   - CPU → 85% (primary) ✓
   - Latency ↑ 2-4x (secondary) ✓
   - Throughput ↓ 0.6-0.8x (secondary) ✓

4. **If validation passes:** ✅ Dynamics engine works!
   **If validation fails:** ❌ Fix dynamics engine before continuing

---

## Phase 2: Remove Phi from Fault Tuning

**Priority: HIGH - Eliminates double-counting**

### Current Problem:

```python
# fault_tuner.py (WRONG - double counting phi)
self.target_utilization = 0.60 + (0.15 * (1.0 - self.phi))
```

### Fix:

```python
# fault_tuner.py (CORRECT - capacity-relative)
class FaultParameterTuner:
    def __init__(self, ..., capacity_configs, ...):
        # NO phi parameter!

    def tune_fault_parameters(self, target_node_id, ...):
        # Get baseline from capacity planning
        node_config = self.capacity_configs[target_node_id]
        baseline_latency = get_component_profile(node_role).p50

        # Calculate current utilization
        current_util = (node_rps * baseline_latency / 1000) / total_threads

        # Target: Use 75% of available headroom
        available_headroom = 1.0 - current_util
        target_util = current_util + (available_headroom * 0.75)

        # Calculate multiplier to reach target
        cpu_multiplier = target_util / current_util

        return {'cpu_multiplier': cpu_multiplier}
```

---

## Phase 3: Add Severity Parameter

**Priority: MEDIUM - Enables fault intensity scaling**

### Design:

```python
# In scenario_library.py
@dataclass
class EpisodeConfig:
    fault_type: str
    fault_severity: float = 0.5  # NEW: 0.0-1.0, default=0.5 (balanced)
    # ... rest

# In fault_tuner.py
def tune_fault_parameters(self, ..., severity: float):
    # Calculate baseline target
    base_cpu_multiplier = target_util / current_util

    # Scale by severity (non-linear)
    if severity < 0.5:
        # Mild faults: linear scaling
        scaled_multiplier = 1.0 + (base_cpu_multiplier - 1.0) * (severity / 0.5) * 0.5
    else:
        # Severe faults: exponential scaling
        factor = (severity - 0.5) / 0.5
        scaled_multiplier = base_cpu_multiplier * (0.9 + factor * 0.1) ** 2

    return {'cpu_multiplier': scaled_multiplier, 'severity': severity}
```

---

## Phase 4: Eliminate Redundant Faults

**Priority: LOW - Cleanup**

### Remove These:

```python
# src/scenarios/library.py

# ❌ REMOVE (redundant with cpu_saturation on DB):
# - slow_queries
# - background_db_job
# - connection_exhaustion (redundant with thread_exhaustion)

# ❌ REMOVE (redundant with inject_latency):
# - cache_failure (just dependency_timeout on cache)

# ✅ KEEP (unique signatures):
# - cpu_saturation (high CPU, consistent latency)
# - memory_pressure (allocation overhead, bimodal latency)
# - thread_exhaustion (queue buildup, eventual rejections)
# - io_bottleneck (high latency, LOW CPU)
# - network_partition (complete isolation)
# - dependency_timeout (retries, traffic amplification)
```

---

## Phase 5: Implement All Unique Faults

**Priority: MEDIUM - Complete fault catalog**

For each fault:
1. Implement primary effect (set metric directly)
2. Rely on dynamics for secondary effects
3. Add to validation framework
4. Document in fault profile

```python
# Example: memory_pressure
def inject_memory_pressure(pod, severity):
    # PRIMARY: Set memory target
    baseline_memory = pod.memory_baseline
    available_headroom = pod.memory_capacity - baseline_memory
    target_memory = baseline_memory + (available_headroom * severity * 0.9)

    pod.memory_target = target_memory

    # SECONDARY (automatic via dynamics):
    # - Allocation overhead increases CPU
    # - Memory thrashing causes latency spikes
    # - OOM risk increases at high levels
```

---

## Phase 6: Production Validation

**Priority: LOW - After all else works**

Compare simulated faults with real production incidents:

1. **Collect real incident data**
   - CPU spike: What happened to latency? Throughput?
   - Memory leak: What was the pattern?
   - Thread exhaustion: How did errors manifest?

2. **Run equivalent simulation**
   - Inject same fault type and severity
   - Measure same metrics

3. **Compare behavior**
   - Do patterns match?
   - Are magnitudes similar?
   - Do cross-effects align?

4. **Tune severity curves**
   - Adjust scaling based on real data
   - Update validation criteria

---

## Success Criteria

✅ **We're done when:**
1. All faults pass validation (dynamics engine proven correct)
2. No phi double-counting (capacity-relative only)
3. Severity parameter works (0.5 = balanced, scales non-linearly)
4. Only unique faults remain (redundant ones removed)
5. Fault profiles documented (gold standard reference)
6. Fault behavior matches real systems (validated against production)

---

## Immediate Next Steps (Priority Order)

1. **[TODAY]** Implement metric collection in validator
2. **[TODAY]** Validate cpu_saturation (prove dynamics works)
3. **[TOMORROW]** Remove phi from fault_tuner.py
4. **[TOMORROW]** Add severity parameter to cpu_saturation
5. **[THIS WEEK]** Validate all other faults
6. **[THIS WEEK]** Remove redundant faults
7. **[NEXT WEEK]** Compare with real incidents (if available)

---

## Questions to Answer

- [ ] Does dynamics engine correctly model CPU → latency?
- [ ] Does dynamics engine correctly model memory → CPU overhead?
- [ ] Does dynamics engine correctly model thread exhaustion → queueing?
- [ ] Do our faults match real distributed system failures?
- [ ] Are severity curves realistic (0.5 = balanced)?

---

## Files Modified

```
src/failures/fault_tuner.py        # Remove phi, add severity
src/failures/training_injector.py  # Use cpu_cost_multiplier
src/components/base_component.py   # Has cpu_cost_multiplier ✓
src/components/pod.py               # Applies cpu_cost_multiplier ✓
src/scenarios/library.py            # Add severity, remove redundant
validate_fault_dynamics.py          # New validation framework ✓
```

---

## Philosophy

> **"First principles → Validation → Implementation"**

We don't implement faults and hope they work.
We design faults, validate dynamics, then implement with confidence.

**This is the rigorous, engineering approach to fault injection.**
