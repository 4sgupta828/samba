# External Service Fault Injection - Root Cause Analysis

## Problem Statement
Fault injection on external services (ExternalService) is not propagating to upstream services, resulting in:
- Quality Score: 0.00
- Blast Radius: 1 node (only root cause)
- No observable impact on dependent services

## Investigation Summary

### Test Results
1. **Fault injection mechanism**: ✅ WORKING
   - `forced_error_rate` correctly set to 0.3
   - Errors generated in traces (25% error rate observed)
   - Infrastructure change logs visible

2. **Error generation**: ✅ WORKING (after fix)
   - ExternalService now emits `component.errors.total` metric
   - 3,289 error log entries generated
   - 12/48 calls failed after fault applied

3. **Error propagation**: ❌ **NOT WORKING**
   - Errors don't reach upstream services
   - svc_2 (calls ext_0) shows no impact
   - No cascading failures observed

## Root Causes Found

### 1. Missing Error Metrics (FIXED)
**File**: `src/components/external.py`

**Problem**: ExternalService generated errors but didn't emit metrics
```python
# Line 66-71: Raises exception but no metric
if random.random() < total_error_rate:
    self._emit_log("ERROR", f"External API timeout on {self.id}")
    raise Exception(f"External API Timeout (504): {self.id}")
    # ❌ No error counter increment!
```

**Fix Applied**:
```python
# Added error counter in __init__
self.errors_counter = self.meter.create_counter(
    "component.errors.total",
    description=f"Total errors in {component_id}",
    unit="1"
)

# Increment on error
if random.random() < total_error_rate:
    self._emit_log("ERROR", f"External API timeout on {self.id}")
    self.errors_counter.add(1, {  # ✅ Now tracks errors
        "component.id": self.id,
        "component.type": self.type,
        "error_type": "external_timeout"
    })
    raise Exception(f"External API Timeout (504): {self.id}")
```

### 2. Pod Not Using ServicePropagationMixin (NOT FIXED)
**File**: `src/components/pod.py:16`

**Problem**: Pod class doesn't inherit from ServicePropagationMixin
```python
class Pod(EnrichedComponent):  # ❌ Missing ServicePropagationMixin
```

**Current Behavior** (`_execute_external_calls`, line 839-864):
```python
try:
    yield self.env.process(conn_target.handle_request(...))
    # Record success metrics
except Exception as e:
    self._emit_log("WARN", f"External call to {conn_name} failed: {e}")
    # Record error metrics
    # ❌ ERROR SWALLOWED - NO RE-RAISE!
```

**Expected Behavior** (with ServicePropagationMixin):
```python
# Use call_dependency_with_propagation()
yield from self.call_dependency_with_propagation(
    dep_name=conn_name,
    dep_type='external',
    call_func=lambda: conn_target.handle_request(...)
)
# ✅ Probabilistic error propagation
# ✅ Circuit breaker support
# ✅ Retry logic
# ✅ Timeout detection
```

## Impact Analysis

### What Works Now:
- ✅ Fault injection applies correctly
- ✅ External service generates errors
- ✅ Error metrics are emitted
- ✅ Traces show error status codes
- ✅ Logs capture all errors

### What's Still Broken:
- ❌ Errors don't propagate to callers
- ❌ svc_2 (depends on ext_0) shows no impact
- ❌ No cascading failures
- ❌ GNN training data lacks causal relationships
- ❌ Quality score remains 0.00

## Recommended Fixes

### Option 1: Integrate ServicePropagationMixin (RECOMMENDED)
**Pros**:
- Proper architectural solution
- Adds circuit breakers, retries, timeouts
- Probabilistic propagation (realistic)
- Works for all dependency types

**Changes Required**:
1. Make Pod inherit from ServicePropagationMixin
2. Replace direct exception handling with `call_dependency_with_propagation()`
3. Configure propagation probabilities in `PropagationConfig`

**Files to Modify**:
- `src/components/pod.py`: Add mixin inheritance
- `src/components/pod.py`: Refactor `_execute_external_calls()`, `_execute_service_calls()`, `_execute_db_logic()`

### Option 2: Add Simple Probabilistic Propagation
**Pros**:
- Minimal code changes
- Quick fix
- Focused on external services

**Changes Required**:
Add error propagation to `_execute_external_calls()`:
```python
except Exception as e:
    self._emit_log("WARN", f"External call to {conn_name} failed: {e}")
    # Record error metrics...

    # ✅ ADD: Probabilistic propagation
    EXTERNAL_ERROR_PROPAGATION_RATE = 0.3  # 30% of external errors propagate
    if random.random() < EXTERNAL_ERROR_PROPAGATION_RATE:
        self.request_errors.add(1, {...})  # Increment request error counter
        raise DependencyFailureException(f"External dependency {conn_name} failed: {e}")
    # Otherwise swallow error (degraded mode)
```

### Option 3: Always Propagate External Errors
**Pros**:
- Simplest implementation
- Maximum propagation signal
- Good for initial testing

**Cons**:
- Unrealistic (real services have resilience)
- May over-emphasize external dependencies

**Changes Required**:
Remove try/except in `_execute_external_calls()` - let errors bubble up naturally.

## Test Plan

1. **Generate new dataset** with fix applied
2. **Verify error propagation**:
   ```bash
   jq '.node_reports[] | select(.node_id == "svc_2") | .ranked_metrics[0]' \
       ep_X/fault_propagation.json
   ```
   Should show increased error rate in svc_2

3. **Check quality score**: Should be > 0.00
4. **Verify blast radius**: Should be > 1 node

## Files Changed

### Applied:
- ✅ `src/components/external.py`: Added error counter

### Pending:
- ⏳ `src/components/pod.py`: Add ServicePropagationMixin or simple propagation logic

## Related Files
- `src/resilience/service_propagation_mixin.py`: Existing propagation logic
- `src/resilience/propagation_config.py`: Configuration for propagation rates
- `src/failures/modes.py`: Fault injection modes
- `src/failures/training_injector.py`: Fault injection orchestration

## Conclusion

**The fault injection system works correctly**, but **errors are not propagating** because the Pod class handles all dependency errors gracefully without re-raising them. This is a **design issue**, not a bug in fault injection.

To fix this, we need to either:
1. Integrate ServicePropagationMixin (proper solution)
2. Add simple probabilistic propagation (quick fix)
3. Always propagate external errors (test-only solution)

The recommended approach is **Option 1** for production quality, or **Option 2** for a quick validation.
