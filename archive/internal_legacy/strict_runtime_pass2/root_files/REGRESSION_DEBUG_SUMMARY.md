# Regression Debug Summary

**Date**: 2025-12-01
**Issues Found**: 2 regressions after request mix changes

---

## Issue 1: Causal Analysis Sort Error ✅ FIXED

### Error
```
Warning: Causal analysis failed: '<' not supported between instances of 'NoneType' and 'int'
```

### Root Cause
In `analysis/causal_chain_analyzer.py:414`, the code sorts analyses by `distance_from_root`:
```python
sorted_analyses = sorted(
    analyses.items(),
    key=lambda x: (x[1].distance_from_root, x[0])
)
```

When `distance_from_root` is `None`, Python cannot compare `None < int`, causing the error.

### Fix
Handle `None` values in the sort key:
```python
sorted_analyses = sorted(
    analyses.items(),
    key=lambda x: (x[1].distance_from_root if x[1].distance_from_root is not None else float('inf'), x[0])
)
```

**Status**: ✅ Fixed in `analysis/causal_chain_analyzer.py:414`

---

## Issue 2: High Error Rate with PUT/DELETE Requests ❌ PARTIALLY FIXED

### Error
```
✗ Mathematical validation FAILED: Node 'svc_0': Error rate 76.56% exceeds 1.00%
Episode 0 failed baseline validation (attempt 3/3)
```

### Root Cause
After adding PUT and DELETE request types to the request mix:
```python
request_type_distribution = {
    'GET': 0.60,
    'POST': 0.30,
    'PUT': 0.07,     # NEW
    'DELETE': 0.03    # NEW
}
```

The system experienced 76% error rate during the baseline period (before fault injection).

### Investigation
1. **No errors in logs** - logs showed no ERROR/WARN messages
2. **High error rate in metrics** - metrics showed 76% of requests failing
3. **Timeline**: Fault starts at 180s, but errors occurred 0-180s (baseline)
4. **Workload**: 80 RPS baseline, which is BELOW safe capacity of 105 RPS

### Hypothesis
PUT and DELETE requests are:
1. Not properly registered with the gateway's `request_to_service_map`
2. Being rejected/dropped by the workload generator or gateway
3. Causing routing failures

### Temporary Fix
Disabled PUT and DELETE in the request mix:
```python
request_type_distribution = {
    'GET': 0.70,    # Increased from 60%
    'POST': 0.30,   # Same
    # 'PUT': 0.07,    # DISABLED - not working yet
    # 'DELETE': 0.03  # DISABLED - not working yet
}
```

Also reverted services to support only GET/POST:
```python
supported_request_types=['GET', 'POST']  # Was: ['GET', 'POST', 'PUT', 'DELETE']
```

**Status**: ⚠️ Temporarily fixed by disabling PUT/DELETE

---

## Testing Results

### Before Fix
```bash
python generate_dataset.py -n 1 --fault-type cache_failure

# Result:
✗ Mathematical validation FAILED: Error rate 76.56%
WARNING: Episode 0 could not be generated after 3 attempts
```

### After Fix
```bash
python generate_dataset.py -n 1 --fault-type cache_failure

# Result:
Episode 0 completed successfully
Dataset generation complete!
```

---

## Current State

### Working ✅
- GET requests (70% of traffic)
- POST requests (30% of traffic)
- Request mix properly distributed across services
- Single frontend handles multiple request types
- Causal analysis sorts correctly with None values

### Not Working ❌
- PUT requests
- DELETE requests
- Full REST API support

---

## Next Steps to Enable PUT/DELETE

### 1. Verify Gateway Registration
Check if PUT/DELETE are properly registered in `request_to_service_map`:

```python
# In src/components/networking.py
def register_service(self, service, request_types: List[str]):
    for request_type in request_types:
        self.request_to_service_map[request_type] = service
```

**Action**: Add logging to see if PUT/DELETE are being registered

### 2. Verify Workload Generator Support
Check if workload generator actually sends PUT/DELETE:

```python
# In src/workloads/generator.py
# Does it filter out unsupported request types?
```

**Action**: Add logging to see what request types are being sent

### 3. Check Request Routing Logic
Verify gateway can route PUT/DELETE:

```python
# In src/components/networking.py
def get_service_for_request(self, request_type: str):
    return self.request_to_service_map.get(request_type)
```

**Action**: Add fallback or logging for unmapped types

### 4. Update Service Default Pipeline
Services might need different pipelines for different methods:
- GET: cache_check → db_query (read-heavy)
- POST: db_query → queue_publish (write-heavy)
- PUT: db_query → cache_invalidate (update)
- DELETE: db_query → cache_invalidate (delete)

**Action**: Consider method-specific pipelines

---

## Files Modified

1. **`analysis/causal_chain_analyzer.py`** (Line 414)
   - Fixed: None handling in sort key

2. **`generate_dataset.py`** (Lines 75-80)
   - Temporary: Disabled PUT/DELETE in request mix
   - Changed: 60/30/7/3 → 70/30 distribution

3. **`src/topology/generator.py`** (Line 93)
   - Temporary: Reverted to `['GET', 'POST']` only

---

## Debugging Commands

```bash
# Test with only GET/POST (should work)
python generate_dataset.py -n 1 --topology-size 5

# Check request mix in output
cat data/data_*/ep_0/safe_workload_analysis.json | jq '.routing_distribution.request_mix'

# Check for errors in baseline
python3 << 'EOF'
import json
with open('data/data_*/ep_0/.validation_failed', 'r') as f:
    print(json.dumps(json.load(f), indent=2))
EOF

# Check logs for routing issues
grep "No service registered" data/data_*/ep_0/logs.jsonl
grep "PUT\|DELETE" data/data_*/ep_0/logs.jsonl
```

---

## Summary

**Fixed**:
1. ✅ Causal analysis None comparison error
2. ⚠️ High error rate (by disabling PUT/DELETE)

**Remaining Work**:
- Investigate why PUT/DELETE cause 76% error rate
- Implement proper PUT/DELETE support in gateway
- Re-enable PUT/DELETE in request mix
- Test with full REST API support

**Current Workaround**:
- Use GET (70%) and POST (30%) only
- System is stable with these two request types
- Datasets can be generated successfully

---

**Document Version**: 1.0
**Last Updated**: 2025-12-01
**Status**: Partially Fixed - PUT/DELETE Disabled
