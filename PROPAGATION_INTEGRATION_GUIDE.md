# Fault Propagation Integration Guide

## Overview

This guide explains how to integrate the enhanced fault propagation system into your existing services. The new system adds:

1. ✅ **Retry Logic** with exponential backoff
2. ✅ **Circuit Breakers** to prevent cascading failures
3. ✅ **Timeout Detection** for slow dependencies
4. ✅ **Probabilistic Error Propagation** (50% of dep failures → request failure)
5. ✅ **Enhanced Metrics** for GNN training

## Architecture

```
Service Request
    ↓
[Circuit Breaker Check] → OPEN? → Reject (CircuitBreakerOpenException)
    ↓ CLOSED
[Retry Loop] (up to 3 attempts)
    ↓
[Timeout Check] → Exceeded? → DependencyTimeoutException
    ↓
[Actual Dependency Call]
    ↓
Success → Circuit Breaker: record_success()
    ↓
Failure → [Probabilistic Propagation]
    ↓                    ↓
Propagate (50%)    Handle Gracefully (50%)
```

## Integration Steps

### Step 1: Add Propagation Mixin to ApiService

**Location**: `src/components/service.py`

**Change**:
```python
# BEFORE
from .base_component import EnrichedComponent

class ApiService(EnrichedComponent):
    def __init__(self, env, component_id, service_name):
        super().__init__(env, component_id, f"ApiService:{service_name}")
        self.service_name = service_name
        ...
```

```python
# AFTER
from .base_component import EnrichedComponent
from src.resilience.service_propagation_mixin import ServicePropagationMixin

class ApiService(EnrichedComponent, ServicePropagationMixin):
    def __init__(self, env, component_id, service_name):
        # Initialize parent classes
        EnrichedComponent.__init__(self, env, component_id, f"ApiService:{service_name}")
        ServicePropagationMixin.__init__(self, env)  # NEW!

        self.service_name = service_name
        ...

        # Initialize propagation metrics AFTER meter is created
        self._initialize_propagation_metrics(service_name)  # NEW!
```

### Step 2: Wrap Dependency Calls with Propagation Logic

**Location**: `src/components/service.py:_call_downstream_dependencies()`

#### External Service Calls

**BEFORE** (lines 427-497):
```python
elif conn_name.startswith('ext_'):
    external_service = conn_target
    if random.random() < 0.3:
        try:
            ext_start = self.env.now
            yield self.env.process(external_service.handle_request(
                ext_request_type,
                should_trace=should_trace_ext,
                parent_span_context=ext_span_ctx
            ))
            ext_latency = (self.env.now - ext_start) * 1000

            # Record success metrics...

        except Exception as e:
            # Record error metrics...
            self._emit_log("WARN", f"External call to {conn_name} failed: {e}")
            # Request continues! NO PROPAGATION! ❌
```

**AFTER**:
```python
elif conn_name.startswith('ext_'):
    external_service = conn_target
    if random.random() < 0.3:
        ext_start = self.env.now

        # Define the actual call as a generator function
        def make_external_call():
            yield self.env.process(external_service.handle_request(
                ext_request_type,
                should_trace=should_trace_ext,
                parent_span_context=ext_span_ctx
            ))

        try:
            # NEW: Wrap with propagation logic (retry, circuit breaker, timeout)
            yield from self.call_dependency_with_propagation(
                dep_name=conn_name,
                dep_type='external',
                call_func=make_external_call,
                span=span
            )

            ext_latency = (self.env.now - ext_start) * 1000

            # Record success metrics (same as before)
            self.dependency_requests_counter.add(1, {
                "status": "success",
                "dependency_type": "external",
                "dependency_id": external_service.id,
                "dependency_name": conn_name,
                "component.id": self.id
            })
            self.dependency_latency.record(ext_latency, {
                "dependency_type": "external",
                "dependency_id": external_service.id,
                "dependency_name": conn_name,
                "component.id": self.id
            })

        except (DependencyFailureException, CircuitBreakerOpenException, DependencyTimeoutException) as e:
            # NEW: Error propagates! Request FAILS! ✅
            ext_latency = (self.env.now - ext_start) * 1000

            # Record error metrics
            self.dependency_requests_counter.add(1, {
                "status": "error",
                "dependency_type": "external",
                "dependency_id": external_service.id,
                "dependency_name": conn_name,
                "component.id": self.id
            })
            self.dependency_errors_counter.add(1, {
                "error_type": type(e).__name__,
                "dependency_type": "external",
                "dependency_id": external_service.id,
                "dependency_name": conn_name,
                "component.id": self.id
            })

            # Propagate error upstream (THIS IS THE KEY CHANGE!)
            self._emit_log("ERROR", f"External call to {conn_name} failed after retries: {e}")
            raise
```

#### Service-to-Service Calls

**Apply similar changes to internal service calls** (lines 375-425):

```python
# Internal service calls (dep_*)
if conn_name.startswith('dep_'):
    target_service = conn_target
    if random.random() < 0.7:
        dep_start = self.env.now

        def make_service_call():
            yield self.env.process(target_service.handle_request(
                dep_request_type,
                should_trace=should_trace_dep,
                parent_span_context=dep_span_ctx
            ))

        try:
            # NEW: Wrap with propagation
            yield from self.call_dependency_with_propagation(
                dep_name=conn_name,
                dep_type='service',
                call_func=make_service_call,
                span=span
            )

            dep_latency = (self.env.now - dep_start) * 1000
            # No dependency metrics for internal services (they emit their own)

        except (DependencyFailureException, CircuitBreakerOpenException, DependencyTimeoutException) as e:
            # Error propagates!
            self._emit_log("ERROR", f"Service call to {conn_name} failed: {e}")
            raise
```

### Step 3: Import New Exception Types

**Location**: Top of `src/components/service.py`

```python
from src.resilience.service_propagation_mixin import (
    ServicePropagationMixin,
    DependencyFailureException,
    DependencyTimeoutException,
    CircuitBreakerOpenException
)
```

### Step 4: Configure Propagation Behavior (Optional)

By default, the mixin uses `STANDARD_PROPAGATION` config:
- 50% error propagation probability
- 3 retry attempts
- Exponential backoff (200ms base)
- Circuit breaker at 50% error rate

To customize per service:

```python
from src.resilience.propagation_config import PropagationConfig, AGGRESSIVE_PROPAGATION

class ApiService(EnrichedComponent, ServicePropagationMixin):
    def __init__(self, env, component_id, service_name):
        EnrichedComponent.__init__(self, env, component_id, f"ApiService:{service_name}")

        # Use aggressive propagation for critical services
        ServicePropagationMixin.__init__(self, env, propagation_config=AGGRESSIVE_PROPAGATION)

        # ... rest of init
```

## New Metrics for GNN

After integration, you'll get these new metrics:

### Circuit Breaker Metrics
- **`service.{name}.dependency.circuit_breaker_state`**: State per dependency
  - 0.0 = CLOSED (normal)
  - 0.5 = HALF_OPEN (testing recovery)
  - 1.0 = OPEN (failing fast)

### Retry Metrics
- **`service.{name}.dependency.retries`**: Number of retry attempts
  - Labels: `dependency_name`, `dependency_type`, `attempt`

### Timeout Metrics
- **`service.{name}.dependency.timeouts`**: Number of timeouts
  - Labels: `dependency_name`, `dependency_type`

### Propagation Metrics
- **`service.{name}.errors.propagated`**: Errors that cascaded upstream
  - Labels: `dependency_name`, `dependency_type`, `error_type`

### Circuit Breaker Rejections
- **`service.{name}.dependency.circuit_breaker_rejections`**: Requests rejected by open circuit
  - Labels: `dependency_name`, `dependency_type`

## Expected Impact on Training Data

### Before Integration
```
ext_0 fails (30% error rate)
  ↓
svc_0: dependency.errors++ (but request succeeds!)
  ↓
gateway: NO SIGNAL ❌
```

**GNN sees**: Only ext_0 has clear signal. No propagation.

### After Integration
```
ext_0 fails (30% error rate)
  ↓
svc_0:
  - Retries 3x → latency +600ms
  - 50% of failures propagate → error_rate +4.5%
  - Circuit breaker opens after 10s → circuit_breaker_state=1.0
  ↓
gateway:
  - Sees svc_0 failures → error_rate +1-2%
  - Sees svc_0 latency → latency +200ms
  - May timeout svc_0 → timeout_count++
```

**GNN sees**: Clear propagation through 2-3 hops! ✅

## Testing the Integration

### Test 1: Verify Retry Logic

```bash
# Generate episode with external API error injection
python generate_dataset.py -n 1 -v

# Check logs for retry attempts
grep "dependency_retry" data/*/ep_0/logs.jsonl | head -5

# Expected: Multiple retry attempts per failed request
```

### Test 2: Verify Circuit Breaker

```bash
# Check circuit breaker state metrics
cat data/*/ep_0/metrics.jsonl | jq 'select(.name == "service.svc_0.dependency.circuit_breaker_state")'

# Expected: State transitions from 0.0 (closed) → 1.0 (open) after failures
```

### Test 3: Verify Error Propagation

```bash
# Compare error rates before/after propagation
echo "=== ext_0 (root cause) ==="
cat data/*/ep_0/metrics.jsonl | jq 'select(.labels.component == "ext_0" and .name == "error_rate")' | head -5

echo "=== svc_0 (1-hop) ==="
cat data/*/ep_0/metrics.jsonl | jq 'select(.labels.component == "svc_0" and .name == "error_rate")' | head -5

echo "=== gateway (2-hop) ==="
cat data/*/ep_0/metrics.jsonl | jq 'select(.labels.component == "gateway" and .name == "error_rate")' | head -5

# Expected: All three components show increased error rates
```

## Rollback Plan

If integration causes issues:

1. **Revert service.py changes**:
   ```bash
   git checkout HEAD -- src/components/service.py
   ```

2. **Keep resilience modules** (for future use):
   - `src/resilience/` directory remains
   - Can be integrated later with bug fixes

## Next Steps

1. ✅ Integrate mixin into `ApiService` class
2. ✅ Wrap external service calls
3. ✅ Wrap service-to-service calls
4. ⏳ Generate new dataset
5. ⏳ Compare metrics before/after
6. ⏳ Train GNN and measure accuracy improvement

## Questions?

See `FAULT_PROPAGATION_ANALYSIS.md` for detailed analysis of why these changes are needed.

---

**Generated**: 2025-11-24
**Author**: Claude (Sonnet 4.5)
**Project**: Samba - Fault Propagation Enhancement
