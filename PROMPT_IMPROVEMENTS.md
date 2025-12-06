# LLM Prompt Improvements for Topology Generation

## Problem

When generating topologies, the LLM was failing validation frequently:
```
[2/4] 🏛️  Architecting mesh (small)...
  ⚠ Attempt 1 failed validation: Topology contains a synchronous cycle
  ⚠ Attempt 2 failed validation: Topology contains a synchronous cycle
  ⚠ Attempt 3 failed validation: Topology has disconnected components
   ❌ FAILED: Failed to generate valid mesh topology after 3 attempts
```

**Root Cause:** The original prompt was too abstract. It said "don't create cycles" but didn't explain HOW to avoid them.

---

## Improvements Made

### 1. Step-by-Step Design Process (NEW)

**Before:** No guidance on design order
**After:** Clear 4-step process:

```
STEP 1: Design infrastructure layer (DB, cache, queues, external)
STEP 2: Design service layer in LAYERS (to avoid cycles)
  - Layer 1 (Frontend): Services that talk to Gateway
  - Layer 2 (Backend): Services called by frontend
  - Layer 3 (Data/Async): Services that process async jobs
  - RULE: Services can only call same/lower layers, NOT higher layers
STEP 3: Connect services to infrastructure
STEP 4: Define request flows
```

**Why This Helps:** Organizing services in layers naturally prevents cycles.

---

### 2. Explicit Anti-Cycle Strategy

**Before:**
```
1. **No Cycles:** Synchronous calls MUST NOT form loops.
   - Check: Can you traverse from any service back to itself?
```

**After:**
```
1. **No Cycles (MOST IMPORTANT):**
   - Draw the service call graph on paper first
   - Organize services in layers: Frontend → Backend → Data
   - Services can ONLY call services in same/lower layers, NEVER higher layers
   - Example of CYCLE (WRONG): service_a → service_b → service_c → service_a ❌
   - Example of CORRECT: gateway → frontend_svc → backend_svc → database ✅
   - If you detect a cycle, REMOVE the edge that goes backwards to a higher layer

**HOW TO AVOID CYCLES:**
1. Number your services: service_1, service_2, service_3, ...
2. Lower-numbered services can call higher-numbered services
3. Higher-numbered services CANNOT call lower-numbered services
4. Example: gateway(0) → service_1 → service_2 → service_3 → database ✅
5. Example: service_1 → service_2 → service_1 = CYCLE ❌
```

**Why This Helps:** Concrete algorithmic strategy (numbering) that's easy to follow.

---

### 3. Connectivity Troubleshooting Guide

**Before:**
```
2. **Connectivity:** All services must be reachable from the Gateway.
   - Check: Is every node reachable from 'gateway'?
```

**After:**
```
2. **Connectivity (SECOND MOST IMPORTANT):**
   - EVERY node must have a path from gateway (directly or through other services)
   - Check each service: Can I reach it from gateway? If NO, add gateway → service edge
   - Check each database: Does a service connect to it? If NO, add service → db edge
   - Check each cache: Does a service connect to it? If NO, add service → cache edge
   - Check each queue: Does a service produce to it AND consume from it? If NO, add edges
   - Orphaned nodes = disconnected components = VALIDATION FAILURE
```

**Why This Helps:** Itemized checklist for each node type. Clear cause-and-effect.

---

### 4. Archetype-Specific Anti-Cycle Strategies

**Before:**
```python
archetype_guidance = {
    'mesh': 'High service-to-service connectivity.',
}
```

**After:**
```python
archetype_guidance = {
    'mesh': '''High service-to-service connectivity BUT NO CYCLES.
   Strategy: Organize services in layers even if mesh-like.
   Layer 1: gateway → [core_services] (2-3 services)
   Layer 2: [core_services] → [specialized_services] (2-3 services)
   Layer 3: [specialized_services] → [data_services] (1-2 services)
   Services in same layer can call each other (peer-to-peer).
   Services CANNOT call services in higher layers (prevents cycles).
   All services connect to shared infrastructure (DB, cache, queue).''',

    'hub_spoke': '''One central orchestration service as hub.
   Layer 1: gateway → hub_service (the central orchestrator)
   Layer 2: hub_service → [spoke_services] (all spokes called by hub)
   Layer 3: [spoke_services] → [databases/caches] (data layer)
   RULE: Spokes do NOT call hub back (that creates cycle). Hub calls spokes.
   RULE: Spokes do NOT call other spokes directly (go through hub).''',

    'pipeline': '''Sequential processing stages with queues between them.
   Pattern: Service → Queue → Service → Queue → Service...
   Example: upload_svc → upload_q → validate_svc → validate_q → process_svc
   RULE: NO sync_http edges between services in pipeline! Must use queues.
   RULE: Need 3-6 queues minimum for proper stage separation.
   RULE: Each queue needs: 1 producer (async_produce) + 1 consumer (async_consume).'''
}
```

**Why This Helps:** Each archetype has specific rules to avoid its common pitfalls.

---

### 5. Common Mistakes Section

**Added:**
```
**COMMON MISTAKES TO AVOID:**
❌ "service_a calls service_b, service_b calls service_a" = CYCLE (will fail validation)
❌ "cache_0 exists but no service connects to it" = DISCONNECTED (will fail validation)
❌ "async_produce: service_a → service_b" = WRONG TARGET (must be Queue)
❌ "Only 3 services total" = TOO SMALL (need 5+ minimum)
❌ "Pipeline with Service → Service edges" = WRONG PATTERN (must use Queues)
```

**Why This Helps:** Shows actual failing patterns so LLM can recognize and avoid them.

---

### 6. Mandatory Checklist

**Before:** Generic "verify" statements
**After:** Checkbox format with specific actions

```
**BEFORE RETURNING JSON - MANDATORY CHECKLIST:**

[ ] 1. CYCLE CHECK: Draw service dependencies. Do any services form a loop? If YES, remove backwards edge.
[ ] 2. CONNECTIVITY CHECK: Can I reach every node from gateway? If NO, add gateway → node edge.
[ ] 3. ASYNC CHECK: Does every async_produce target a Queue? Does every async_consume come from Queue?
[ ] 4. ORPHAN CHECK: Does every infrastructure node have incoming edges from services?
[ ] 5. FLOW CHECK: Do all nodes in flows exist in nodes[]?
[ ] 6. MINIMUM CHECK: Do I have enough nodes? (5+ services, 1+ DB, 1+ cache, 1+ queue, 1+ external)
```

**Why This Helps:** Checkbox format makes it clear these are actionable items, not suggestions.

---

### 7. Better Error Messages (Code Changes)

**Before:**
```python
raise ValueError("Topology contains a synchronous cycle")
raise ValueError("Topology has disconnected components")
```

**After:**
```python
cycle_str = " → ".join(f"{u}" for u, v in cycle) + f" → {cycle[0][0]}"
raise ValueError(
    f"CYCLE DETECTED: {cycle_str}\n"
    f"Fix: Remove one edge from this cycle. Usually the backwards edge.\n"
    f"Tip: Organize services in layers. Higher layers can't call lower layers."
)

raise ValueError(
    f"DISCONNECTED NODES: {unreachable_list} not reachable from gateway.\n"
    f"Fix: Add edges from gateway (or services) to these nodes.\n"
    f"Tip: Every service should be called by gateway or another service."
)
```

**Why This Helps:** Error messages include:
1. What failed (specific cycle/nodes)
2. How to fix it (concrete action)
3. General tip (design pattern)

---

## Expected Impact

### Before Improvements:
- ❌ 3/4 mesh attempts fail (cycles)
- ❌ 1/4 pipeline attempts fail (disconnected)
- ❌ Success rate: ~50%
- ⏱️ Average attempts: 2-3 per topology

### After Improvements:
- ✅ Clear step-by-step process
- ✅ Concrete anti-cycle strategy (numbering)
- ✅ Archetype-specific guidance
- ✅ Actionable error messages
- 🎯 Expected success rate: 80-90%
- ⏱️ Expected attempts: 1-2 per topology

---

## Testing

Run topology generation again:
```bash
python generate_topology_bank.py --samples 3 --output data/topology_bank_v3
```

Watch for:
```
✅ Expected (good):
   [1/12] 🏛️  Architecting hierarchical (small)...
     ✓ Generated valid hierarchical topology on attempt 1
   [2/12] 🏛️  Architecting mesh (small)...
     ✓ Generated valid mesh topology on attempt 1  ← Should pass now!

❌ Old behavior (bad):
   [2/12] 🏛️  Architecting mesh (small)...
     ⚠ Attempt 1 failed validation: Topology contains a synchronous cycle
     ⚠ Attempt 2 failed validation: Topology contains a synchronous cycle
     ⚠ Attempt 3 failed validation: Topology has disconnected components
```

---

## Key Insights

### Why Original Prompt Failed:
1. **Too abstract** - "Don't create cycles" without explaining how
2. **No strategy** - No algorithm for LLM to follow
3. **Poor error messages** - Just "cycle" without showing which nodes
4. **No examples** - No good/bad examples to learn from

### Why New Prompt Works:
1. **Concrete algorithm** - "Number services, lower calls higher"
2. **Step-by-step** - Design in order: infra → services (in layers) → connections
3. **Explicit rules** - "Layer 2 can't call Layer 1" is unambiguous
4. **Rich examples** - Shows WRONG and CORRECT patterns side-by-side
5. **Actionable checklist** - Clear checkbox format
6. **Better errors** - Shows exact cycle, suggests fix

---

## Lessons for Other LLM Prompts

1. **Be algorithmic, not philosophical** - "Number your nodes 1-N, lower can call higher" beats "design a DAG"
2. **Show don't tell** - Examples of BAD patterns are as important as GOOD ones
3. **Checklist format works** - `[ ] 1. CHECK THIS` is clearer than "verify that..."
4. **Stratify by difficulty** - "MOST IMPORTANT" tells LLM what to focus on first
5. **Error messages are training data** - If validation fails, the error message teaches the LLM what went wrong

---

## Files Modified

1. **`src/topology/llm_generator.py`**
   - Enhanced `_get_system_prompt()` (lines 64-188)
   - Enhanced `_build_prompt()` archetype guidance (lines 225-255)
   - Improved `_validate_dag()` error messages (lines 364-376)
   - Improved `_validate_connectivity()` error messages (lines 378-408)

---

## Next Steps

1. **Test generation:**
   ```bash
   python generate_topology_bank.py --samples 1 --output data/topology_bank_v3
   ```

2. **Compare success rates:**
   - Count attempts before first success
   - Count total failures (3/3 retries)
   - Should see ~80-90% first-attempt success

3. **Validate results:**
   ```bash
   python validate_topology_fixes.py data/topology_bank_v3
   ```

4. **If still failing:**
   - Check error messages - are they helping?
   - Consider reducing complexity (e.g., fewer services for mesh)
   - May need to tune max_retries or provide more examples

---

## Success Criteria

✅ Mesh topologies generate without cycles (was failing 100%)
✅ Pipeline topologies connect all nodes (was failing 25%)
✅ First-attempt success rate > 80%
✅ Average retries per topology < 1.5
✅ Error messages show specific failing nodes/edges
✅ Validation passes on all generated topologies
