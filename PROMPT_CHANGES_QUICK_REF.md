# Prompt Changes - Quick Reference

## What Changed

### System Prompt (Lines 64-188)

| Section | Before | After |
|---------|--------|-------|
| **Structure** | Abstract constraints | Step-by-step design process |
| **Cycle Prevention** | "Don't create cycles" | "Number services, lower→higher only" |
| **Connectivity** | "Must be reachable" | Checklist per node type |
| **Examples** | None | WRONG ❌ vs CORRECT ✅ patterns |
| **Checklist** | Vague verify statements | `[ ]` checkbox format |

### Key Additions

1. **STEP-BY-STEP PROCESS:**
   ```
   STEP 1: Infrastructure (DB, cache, queues)
   STEP 2: Services in LAYERS (no backwards calls)
   STEP 3: Connect to infrastructure
   STEP 4: Define flows
   ```

2. **ANTI-CYCLE ALGORITHM:**
   ```
   1. Number services: 1, 2, 3, ...
   2. Lower → Higher only
   3. Never Higher → Lower (creates cycle)
   ```

3. **COMMON MISTAKES:**
   ```
   ❌ service_a → service_b → service_a = CYCLE
   ❌ cache exists but no service connects = DISCONNECTED
   ❌ async_produce: service → service = WRONG (must be Queue)
   ```

4. **MANDATORY CHECKLIST:**
   ```
   [ ] 1. CYCLE CHECK: Any loops? Remove backwards edge
   [ ] 2. CONNECTIVITY CHECK: All reachable from gateway?
   [ ] 3. ASYNC CHECK: async_produce → Queue?
   [ ] 4. ORPHAN CHECK: Infrastructure has incoming edges?
   [ ] 5. FLOW CHECK: All flow nodes exist?
   [ ] 6. MINIMUM CHECK: Enough nodes? (5+ services)
   ```

### Archetype Guidance (Lines 225-255)

**Mesh - Added anti-cycle strategy:**
```
Layer 1: gateway → [core_services]
Layer 2: [core_services] → [specialized_services]
Layer 3: [specialized_services] → [data_services]
RULE: Services CANNOT call services in higher layers
```

**Hub-Spoke - Added explicit rules:**
```
RULE: Spokes do NOT call hub back (creates cycle)
RULE: Spokes do NOT call other spokes (go through hub)
```

**Pipeline - Added queue requirements:**
```
RULE: NO sync_http between services! Must use queues
RULE: Need 3-6 queues minimum
```

### Error Messages (Lines 364-408)

**Cycle Detection:**
```python
# Before:
"Topology contains a synchronous cycle"

# After:
"CYCLE DETECTED: service_a → service_b → service_c → service_a
Fix: Remove one edge from this cycle. Usually the backwards edge.
Tip: Organize services in layers. Higher layers can't call lower layers."
```

**Connectivity:**
```python
# Before:
"Topology has disconnected components"

# After:
"DISCONNECTED NODES: cache_0, db_1, queue_2 not reachable from gateway.
Fix: Add edges from gateway (or services) to these nodes.
Tip: Every service should be called by gateway or another service."
```

---

## Why This Helps

### Problem: Mesh Topologies Failed with Cycles
**Root Cause:** LLM created bi-directional edges (service_a ↔ service_b)
**Solution:** Layer strategy - organize services in layers, no backwards calls
**Result:** LLM now knows to design: gateway → Layer1 → Layer2 → Layer3

### Problem: Pipeline Topologies Disconnected
**Root Cause:** LLM forgot to connect some queues/services
**Solution:** Explicit connectivity checklist for each node type
**Result:** LLM checks each queue has producer AND consumer

### Problem: Generic Error Messages
**Root Cause:** "cycle" doesn't tell LLM which edges to remove
**Solution:** Show exact cycle path and suggest fix
**Result:** LLM sees "service_a → service_b → service_a" and knows to remove service_b → service_a

---

## Testing

Run generation again:
```bash
python generate_topology_bank.py --samples 1 --output data/topology_bank_v3
```

Expected output:
```
[1/4] 🏛️  Architecting hierarchical (small)...
  ✓ Generated valid hierarchical topology on attempt 1  ✅

[2/4] 🏛️  Architecting mesh (small)...
  ✓ Generated valid mesh topology on attempt 1  ✅ (was failing 3/3)

[3/4] 🏛️  Architecting pipeline (small)...
  ✓ Generated valid pipeline topology on attempt 1  ✅ (was failing 1/2)

[4/4] 🏛️  Architecting hub_spoke (small)...
  ✓ Generated valid hub_spoke topology on attempt 1  ✅
```

---

## Files Changed

1. `src/topology/llm_generator.py` - All improvements
2. `PROMPT_IMPROVEMENTS.md` - Detailed explanation
3. `PROMPT_CHANGES_QUICK_REF.md` - This file

---

## Key Insight

**The LLM is good at following algorithms, not abstract principles.**

❌ Bad: "Design a DAG" (too abstract)
✅ Good: "Number your nodes 1-N, lower can call higher" (algorithmic)

❌ Bad: "Ensure connectivity" (how?)
✅ Good: "Check each queue: does it have 1 producer AND 1 consumer?" (checklist)

**Rule:** If a human needs an example to understand it, so does an LLM.
