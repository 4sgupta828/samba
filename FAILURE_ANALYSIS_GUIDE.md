# Deep Failure Analysis Guide

## Overview

The failure analysis script (`analyze_failures.py`) performs comprehensive root cause analysis on why RCA failed to detect the ground truth in each case. It examines topology, metrics, connections, and generates actionable hypotheses.

## Usage

```bash
# Analyze all failures
python3 analyze_failures.py data/batch_run

# Save to file
python3 analyze_failures.py data/batch_run > failure_report.txt

# Analyze specific dataset
python3 analyze_failures.py data/my_dataset
```

## Key Findings from Current Batch

### Critical Issues Identified

**1. Service-Level Blind Spot (73% of failures)**
```
Service-level faults: 27/37 (73.0%)
```
- **Root Cause**: Algorithm cannot detect service-level root causes
- **Why**: Services show less severe metrics than their impacted dependencies
- **Impact**: 0/24 success rate on service faults

**2. Leaf Node Bias**
- All top-3 candidates are often leaf nodes
- Algorithm over-prioritizes:
  - Databases (devices_db appears 8x as false positive)
  - Caches (payment_gateway 5x, session_cache 2x)
  - Queues
- **Why**: Leaf nodes have no dependencies, so "all dependencies healthy" rule triggers

**3. Downstream Confusion**
```
⚠️  CONNECTED FALSE POSITIVES: 2 of top-3 false positives are connected to ground truth
```
- False positives are often direct dependencies of the true root cause
- They show MORE severe symptoms than the root cause
- Example: `entertainment_service` → `devices_db`
  - GT severity: 0.226
  - FP severity: 0.510
  - FP is leaf, GT is not → FP wins

### Pattern Analysis

#### Failure Pattern: Service with Database Dependency

**Typical Case:**
```
Ground Truth: entertainment_service (Service, severity 0.226)
Top-3: devices_db, device_cache, automation_db (all Leaf nodes)

Connection: entertainment_service → devices_db (direct)
           entertainment_service → device_cache (direct)

Why we missed it:
1. ✅ Service has dependencies (not a leaf)
2. ❌ Dependencies are impacted (violates "healthy dependencies" rule)
3. ❌ Dependencies show higher severity (look worse)
4. ❌ Dependencies are leaf nodes (scoring boost)
Result: Dependencies ranked higher than true root cause
```

**Fix Needed:**
- Don't automatically disqualify services with impacted dependencies
- Add "impact flow" analysis: does impact flow FROM this node?
- Weight temporal ordering more heavily
- Add service-specific detection rules

#### Failure Pattern: Weak Fault Signature

**Typical Case:**
```
Ground Truth: analytics_service (cpu_saturation)
Metrics:
  - Critical: 0
  - High: 0
  - Severity: 0.226

Top Impacted Metric: container.cpu.utilization (NEGLIGIBLE)
```

**Why we missed it:**
- CPU saturation not manifesting in collected metrics
- Possible reasons:
  1. Metrics not granular enough
  2. Saturation happens but doesn't cross threshold
  3. Service continues functioning (degraded, not failed)

**Fix Needed:**
- Add more CPU-specific metrics
- Lower thresholds for CPU utilization changes
- Add derivative metrics (rate of change)
- Consider resource saturation patterns

## Per-Failure Analysis Structure

Each failure analysis includes:

### 1. Basic Info
```
Ground Truth: entertainment_service
Fault Type: cpu_saturation
Ground Truth Detected: No (or rank if detected)
Top 3 Candidates: devices_db, device_cache, automation_db
```

### 2. Ground Truth Metrics
```
Severity Score: 0.226
Health Status: DEGRADED
Critical Metrics: 0
High Metrics: 0
Top Impacted Metrics:
  - service.entertainment_service.dependency.errors: LOW
  - thread_pool.threads.active: LOW
  - container.cpu.utilization: NEGLIGIBLE
```

**Use this to check:**
- Did GT show significant impact?
- Are the right metrics being collected?
- Is the fault signature visible?

### 3. Topology Analysis
```
GT Type: Service
GT Role: service
Is Leaf: False
Dependencies: 7 nodes
Dependents: 1 nodes
```

**Use this to check:**
- GT node type (service vs infrastructure)
- Connectivity (leaf nodes easier to detect)
- Impact propagation potential

### 4. Connection Analysis
```
Connections (GT → False Positives):
  devices_db:
    Graph Distance: 1
    Direct Paths: 1 found
      - entertainment_service → devices_db
    Shared Compute: []
    Async Connections: 0 found
    Has Connection: True
```

**Shows:**
- **Direct Paths**: Sync call chains
- **Shared Compute**: Co-located pods (noisy neighbor potential)
- **Async Connections**: Queue-based relationships
- **Graph Distance**: Topology proximity

**Patterns to look for:**
- Direct connection: FP is victim of GT
- No connection: FP is unrelated (algorithm confused)
- Shared compute: Noisy neighbor interference

### 5. Root Cause Hypotheses

**Algorithm generates hypotheses like:**

```
1. ⚠️  SERVICE-LEVEL FAULT: Ground truth is a InternalService.
   Algorithm currently struggles with service-level faults (0% success rate).

2. ⚠️  CONNECTED FALSE POSITIVES: 2 of top-3 false positives are connected to ground truth.
   These are likely heavily impacted downstream components.

3. ⚠️  LEAF NODE BIAS: All top-3 candidates are leaf nodes.
   Algorithm may be over-prioritizing leaf nodes in scoring.

4. ❌ WEAK FAULT SIGNATURE: Ground truth has no critical or high-severity metrics.
   The fault may not be manifesting in observable metrics.
```

## Using Analysis for Algorithm Improvements

### Priority 1: Fix Service-Level Detection

**Current Problem:**
- 27/37 failures (73%) are service-level faults
- 0/24 service faults detected successfully

**Solution Approaches:**

1. **Add Temporal "Fan-Out" Detection**
```python
# If a service's dependencies start failing shortly after the service
# shows any impact, the service is likely the root cause
def detect_fanout_pattern(service, dependencies, impact_times):
    service_impact = impact_times[service]
    dep_impacts = [impact_times[d] for d in dependencies]

    # Check if dependencies impacted shortly after service
    time_deltas = [d - service_impact for d in dep_impacts]
    if all(0 < delta < 30 for delta in time_deltas):  # Within 30s
        return True  # Fanout pattern detected
```

2. **Relax "Healthy Dependencies" Rule for Services**
```python
# Don't disqualify services just because their dependencies are impacted
# Instead, check if service was impacted BEFORE dependencies
if node_type == 'Service':
    if all_dependencies_impacted:
        # Check temporal ordering
        if node_impacted_first:
            is_candidate = True  # Possible root cause
```

3. **Add Service-Specific Scoring Boost**
```python
# Services propagate impact, so they deserve higher scores
# when they have impacted dependencies
if node_type == 'Service' and has_impacted_dependencies:
    if impacted_before_dependencies:
        score_boost = 0.3  # Significant boost
```

### Priority 2: Reduce Leaf Node Bias

**Current Problem:**
- Leaf nodes over-represented in top candidates
- Scoring heavily favors "no dependencies" or "all dependencies healthy"

**Solution:**
```python
# Adjust scoring weights
weights = {
    'convergence': 0.30,  # How many paths lead here
    'severity': 0.25,     # How severe is impact
    'time': 0.25,         # Was it impacted first
    'centrality': 0.10,   # Graph centrality
    'signature': 0.10,    # Fault signature match
    'leaf_penalty': -0.05  # NEW: Penalize leaf nodes slightly
}

# Or: boost non-leaf nodes that are impacted
if not is_leaf and is_impacted:
    score += 0.1  # Boost for non-leaf impacted nodes
```

### Priority 3: Improve Fault Signature Detection

**Current Problem:**
- Weak signatures for CPU saturation, memory leaks, deadlocks

**Solutions:**

1. **CPU Saturation:**
```python
# Look for these specific patterns:
cpu_saturation_signals = [
    'container.cpu.utilization > 0.8',  # High CPU
    'thread_pool.threads.active > 0.9',  # Thread pool exhausted
    'service.requests.duration increasing',  # Latency creeping up
    'service.requests.rate decreasing'  # Throughput dropping
]
```

2. **Memory Leak:**
```python
# Look for increasing memory over time
memory_leak_signals = [
    'container.memory.usage increasing monotonically',
    'heap.used increasing without decrease',
    'gc.pause_time increasing',  # GC working harder
    'service.requests.duration increasing'  # Side effect
]
```

3. **Deadlock:**
```python
# Look for thread contention patterns
deadlock_signals = [
    'thread_pool.threads.active high but throughput low',
    'connection_pool.connections.active high',
    'service.requests.duration very high',
    'service.requests.rate very low'
]
```

### Priority 4: Context-Aware Candidate Selection

**Add topology context:**
```python
# For each candidate, analyze its position in topology
def score_candidate(node, topology, impacted_nodes):
    score = base_score(node)

    # If node has impacted dependents (nodes that call it)
    dependents = topology.predecessors(node)
    impacted_dependents = [d for d in dependents if d in impacted_nodes]

    if impacted_dependents:
        # This node could be spreading impact
        score += 0.2 * (len(impacted_dependents) / len(dependents))

    # If node has impacted dependencies (nodes it calls)
    dependencies = topology.successors(node)
    impacted_dependencies = [d for d in dependencies if d in impacted_nodes]

    if impacted_dependencies and node_is_service(node):
        # Service with impacted dependencies - check temporal
        if was_impacted_first(node, impacted_dependencies):
            score += 0.3  # Likely root cause

    return score
```

## Quick Reference: Common Hypotheses

| Hypothesis | Meaning | Fix |
|------------|---------|-----|
| SERVICE-LEVEL FAULT | GT is a service, algorithm can't detect | Add service-specific rules |
| CONNECTED FALSE POSITIVES | FPs are victims of GT | Check temporal ordering, boost GT |
| LEAF NODE BIAS | All FPs are leaf nodes | Reduce leaf node scoring advantage |
| WEAK FAULT SIGNATURE | GT has low severity metrics | Add fault-specific detection |
| LOW IMPACT | GT severity < 0.1 | Check if metrics are adequate |
| CLASSIFIED HEALTHY | GT marked as healthy | Adjust health classification thresholds |
| FALSE POSITIVES MORE SEVERE | FPs show worse metrics than GT | Weight temporal ordering more |

## Workflow

### 1. Run Batch RCA
```bash
python3 batch_rca_discovery.py data/batch_run
```

### 2. Analyze Failures
```bash
python3 analyze_failures.py data/batch_run > failures.txt
```

### 3. Identify Patterns
```bash
# Count common hypotheses
grep "SERVICE-LEVEL FAULT" failures.txt | wc -l
grep "LEAF NODE BIAS" failures.txt | wc -l
grep "WEAK FAULT SIGNATURE" failures.txt | wc -l
```

### 4. Implement Fixes
```python
# Edit: analysis/sotaanalyzer/root_cause_detector.py
# Make changes based on failure patterns
```

### 5. Re-run and Compare
```bash
# Clear old results
find data/batch_run -name "RCA*.marker" -delete

# Re-run with improvements
python3 batch_rca_discovery.py data/batch_run

# Compare results
python3 analyze_batch_results.py data/batch_run
```

### 6. Track Improvements
Keep a log of what you changed and the impact:

```
2025-12-09: Baseline
- Success rate: 31.7%
- Service detection: 0/24

2025-12-10: Added temporal fanout detection
- Success rate: 45.0% (+13.3%)
- Service detection: 8/24 (+8)

2025-12-11: Reduced leaf node bias
- Success rate: 52.0% (+7%)
- Service detection: 12/24 (+4)
```

## Summary

**Key Insights:**
1. 73% of failures are service-level faults (algorithm blind spot)
2. Leaf node bias causes false positives
3. Connected false positives are impacted victims, not root causes
4. Temporal ordering underweighted in scoring

**Next Steps:**
1. Implement service-level detection (biggest impact)
2. Adjust leaf node scoring
3. Add fault-specific signatures
4. Weight temporal ordering more heavily

The failure analysis provides the data needed to systematically improve the RCA algorithm! 🔍
