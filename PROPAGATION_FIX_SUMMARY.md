# Fault Propagation Investigation - Fix Summary

## Root Causes Identified

### 1. Scenario Lookup Bug - FIXED ✅

**Problem**: Random sampling couldn't find specific fault scenarios
**Affected**: memory_leak, inject_latency (service), enable_background_job
**Fix**: Replaced random sampling with direct search in generate_dataset.py
**Status**: VERIFIED WORKING

### 2. Topology Selection Issue - ROOT CAUSE ✅

**Problem**: Fault targets sometimes selected at edges of topology with few upstream callers

**Example - Failed Episode (cpu_saturation ep_1)**:
- Root cause: svc_2
- Upstream callers: 1 (only gateway)
- Downstream calls: 11 (7 services + 1 DB + 3 pods)
- **Result**: Only 2 nodes analyzed (svc_2 + gateway)
- **Why**: No propagation because svc_2 is at end of call chain

**Example - Successful Episode (cpu_saturation ep_0)**:
- Root cause: svc_5
- Upstream callers: 2 (svc_1, svc_6)
- These callers have their own callers
- **Result**: 9 nodes analyzed up to distance 3
- **Why**: svc_5 is mid-chain, propagation flows upstream

### 3. Analyzer Logic is CORRECT

The propagation analyzer uses reverse graph traversal, which is correct:
- Edge A -> B means "A calls B"
- Reverse graph finds who calls root cause (upstream dependencies)
- When root cause is slow, callers wait → upstream impact
- This is the correct propagation direction for most faults

## The Real Issue

**Topology randomness + poor fault target selection**

When a service with few upstream callers is selected as fault target:
- Limited upstream propagation
- Appears as "no propagation" but is actually correct behavior
- Just not interesting for training GNN

## Solution

Add topology validation BEFORE accepting a fault target:

```python
def validate_fault_target_connectivity(graph, target_node, min_upstream_callers=2):
    """
    Ensure fault target has sufficient upstream callers for propagation.

    Args:
        graph: NetworkX DiGraph
        target_node: Node to inject fault into
        min_upstream_callers: Minimum number of direct upstream callers

    Returns:
        (is_valid, reason)
    """
    # Count direct upstream callers (who calls this node)
    callers = list(graph.predecessors(target_node))
    num_callers = len(callers)

    if num_callers < min_upstream_callers:
        return False, f"Only {num_callers} upstream callers (need {min_upstream_callers})"

    # Check if callers are themselves called (2nd order propagation)
    second_order_callers = set()
    for caller in callers:
        second_order_callers.update(graph.predecessors(caller))

    if len(second_order_callers) < 1:
        return False, "Upstream callers have no callers themselves"

    # Check target is not gateway (entry point)
    node_data = graph.nodes[target_node]
    if node_data.get('role') == 'gateway':
        return False, "Gateway cannot be fault target (no upstream)"

    return True, "Target has good connectivity"
```

Add check in generate_dataset.py before fault injection:

```python
# After selecting fault target, validate connectivity
is_valid, reason = validate_fault_target_connectivity(nx_graph, target_id)
if not is_valid:
    if verbose:
        print(f"  Rejecting target {target_id}: {reason}")
    # Try another target or regenerate topology
    continue
```

## Additional Improvements

1. **Prefer mid-chain services**: Select targets with high betweenness centrality
2. **Verify traffic flow**: Ensure target receives >10% of total requests
3. **Multiple targets**: Try multiple candidates if first fails validation
4. **Logging**: Track rejection reasons to tune thresholds

## Expected Impact

After implementing topology validation:
- **Partial propagation cases**: 67% → 95%+ consistency
- **Failed episodes**: Retry with better target selection
- **Training quality**: Higher quality propagation patterns for GNN

## Status

- ✅ Scenario lookup fixed
- ✅ Root cause identified
- 🔄 Topology validation implementation needed
- ⏳ Full test suite rerun pending
