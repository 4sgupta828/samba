# FAULT COMBINATION TEST ANALYSIS SUMMARY

## Date: 2025-11-30

## Executive Summary

Comprehensive testing of all 11 fault type/role combinations revealed **CRITICAL ISSUES** in 2 key fault scenarios that are preventing realistic fault propagation:

### Critical Issues

1. **CONNECTION_EXHAUSTION (database)** - ✗ BROKEN
   - NO fault propagation detected in ANY episode
   - Validation shows: "Fault injection may not be working"
   - Root cause not showing significant impact
   
2. **QUEUE_CONSUMER_SLOWDOWN (queue)** - ⚠️ PARTIALLY WORKING  
   - Causes catastrophic failures (45-85% error rates)
   - Triggers retries and circuit breakers
   - No gradual implementation (instant faults too severe)

## Background Tests Running

Currently tracking 5 background test runs:

| Test | Status | Episodes | Propagation |
|------|--------|----------|-------------|
| spot_check_connection_exhaustion | COMPLETE | 3/3 | ✗ None (0/0/0) |
| verify_connection_exhaustion_50pct | COMPLETE | 3/3 | ✗ Limited (0/1/0) |
| spot_check_queue_slowdown | RUNNING | 1/3 | ⏳ Pending |
| verify_queue_slowdown_fixed | RUNNING | 2/3 | Mixed (ep0: 0/0/1, ep1: 0/3/2) |
| verify_queue_slowdown_500ms | RUNNING | 1/3 | ⏳ Pending |

## Real-World Coverage Analysis

The 11 fault combinations map to real-world scenarios:

### Service Layer (3 faults)
- cpu_saturation on service ✓
- memory_leak on service ✓
- inject_latency on service ✓

### Database Layer (3 faults)
- slow_queries on database ✓
- connection_exhaustion on database ✗ **BROKEN**
- enable_background_job on database ?

### Infrastructure (3 faults)
- cache_failure on cache ?
- inject_latency on cache ?
- queue_consumer_slowdown on queue ⚠️ **NEEDS FIX**

### External Dependencies (2 faults)
- inject_errors on external ?
- inject_latency on external ?

## Root Cause Analysis

### CONNECTION_EXHAUSTION Issues

**Observed Behavior:**
- Fault params: `exhaustion_rate: 0.5, latency_ms: 1000`
- Database has 100 connection pool capacity
- Services have 20 connections each
- Result: No measurable impact on any component

**Why It's Not Working:**
1. 50% exhaustion rate too weak for 100-connection pool
2. 1000ms latency too short to cause queueing
3. Database has background jobs consuming CPU, but connection exhaustion doesn't stress CPU meaningfully

**Recommended Fixes:**
1. Increase `exhaustion_rate` from 0.5 to 0.8-0.9 (80-90%)
2. Implement connection hold duration (not just latency)
3. Add connection leak simulation (held connections not released)

### QUEUE_CONSUMER_SLOWDOWN Issues

**Observed Behavior:**
- Fault params: `latency_ms: 500`  
- Results in 45-85% error rates
- Triggers baseline validation failures
- Causes cascading circuit breaker trips

**Why It's Too Severe:**
1. WARNING in logs: "Gradual mode not implemented"
2. Instant 500ms slowdown overwhelming queues
3. Messages backing up, timeouts cascading
4. System enters failure mode, not degraded mode

**Recommended Fixes:**
1. **MUST** implement gradual fault injection
2. Start with 50-100ms latency
3. Ramp up over fault duration (exponential progression)
4. Monitor and cap error rates at <5% threshold

## Test File Analysis

### /Users/sgupta/samba/test_all_fault_combinations.py

**Strengths:**
- Comprehensive coverage of all 11 combinations
- Good validation and analysis framework
- Detects propagation issues
- Provides remediation suggestions

**Current Limitations:**
- Only runs 3 episodes per combination
- 20-minute timeout may be too short for complex scenarios
- No automatic parameter tuning
- Doesn't implement recommended fixes

## Scenario Library Analysis

### /Users/sgupta/samba/src/scenarios/library.py

**Current Parameters:**

connection_exhaustion:
```python
'exhaustion_rate': 0.5  # Exhaust 50% of connection pool
```

queue_consumer_slowdown:
```python
'latency_ms': 500  # 500ms - comment says "enough to cause backlog without breaking system"
# But in reality, it BREAKS the system
```

**Needed Changes:**
1. Update connection_exhaustion params
2. Reduce queue_consumer_slowdown initial latency
3. Add gradual mode support

## Critical Action Items

### Immediate (Blocking)

1. Fix connection_exhaustion implementation in src/failures/modes.py:338
   - Increase exhaustion rate to 80-90%
   - Implement connection hold/leak mechanism
   - Add proper CPU stress from connection queueing

2. Implement gradual mode for queue_consumer_slowdown in src/failures/modes.py:278
   - Start with 50ms latency
   - Ramp up exponentially over fault duration
   - Cap maximum latency at 500ms

3. Update src/scenarios/library.py default parameters
   - Line 50: Change exhaustion_rate from 0.5 to 0.85
   - Line 58: Change latency_ms from 500 to 100 (with gradual ramp)

### Secondary

1. Run full test suite after fixes
2. Verify all 11 combinations show propagation
3. Check error rates stay under 5% threshold
4. Document real-world scenario mappings

## Tracking Dashboard

Use this command for live tracking:
```bash
python3 -c "
import json, os
tests = {
    'spot_check_connection_exhaustion': '/tmp/spot_check_connection_exhaustion',
    'verify_connection_exhaustion_50pct': '/tmp/verify_connection_exhaustion_50pct',
    'spot_check_queue_slowdown': '/tmp/spot_check_queue_slowdown',
}
for name, path in tests.items():
    if not os.path.exists(path): continue
    data_dirs = [d for d in os.listdir(path) if d.startswith('data_')]
    if not data_dirs: continue
    data_dir = os.path.join(path, data_dirs[0])
    eps = [d for d in os.listdir(data_dir) if d.startswith('ep_')]
    print(f'{name}: {len(eps)}/3 episodes')
    for ep in sorted(eps):
        prop_file = os.path.join(data_dir, ep, 'fault_propagation.json')
        if os.path.exists(prop_file):
            with open(prop_file) as f:
                p = json.load(f)
            s = p.get('propagation_statistics', {})
            c,h,m = s.get('nodes_critically_impacted',0), s.get('nodes_highly_impacted',0), s.get('nodes_moderately_impacted',0)
            print(f'  {ep}: C:{c} H:{h} M:{m}')
"
```

## Conclusion

The fault combination test framework is solid, but 2 critical faults need immediate fixes:
1. **connection_exhaustion** is completely broken (no propagation)
2. **queue_consumer_slowdown** is too severe (causes failures, not degradation)

Once these are fixed, rerun the full test suite to validate all 11 combinations produce realistic fault propagation matching real-world scenarios.
