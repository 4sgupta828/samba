# Whitebox RCA Improvement Roadmap

## Executive Summary

The current `whitebox_rca.py` implementation is **fundamentally incomplete** compared to `batch_rca_discovery.py` (SOTA analyzer). This document details the conceptual gaps and provides a roadmap for comprehensive improvement.

**Performance vs Completeness:**
- `whitebox_rca.py`: **2.9 seconds/episode** - Fast but incomplete
- `batch_rca_discovery.py`: **63.5 seconds/episode** - Comprehensive and accurate

**Accuracy Impact:**
- Current whitebox: **38.9% success rate** (7/18 correct)
- Missing critical analysis capabilities that would significantly improve accuracy

---

## 1. Data Sources: Critical Gap

### Current State (whitebox_rca)
```python
✅ metrics.jsonl (40K lines)     # Only data source used
❌ logs.jsonl (26K lines)        # IGNORED
❌ traces.jsonl (2K lines)       # IGNORED
❌ topology_state.jsonl (70 lines) # IGNORED
```

### Required State (batch_rca_discovery)
```python
✅ metrics.jsonl    # Time-series metrics
✅ traces.jsonl     # Distributed traces for latency analysis
✅ logs.jsonl       # Error patterns, stack traces
✅ topology_state   # Dynamic topology changes
```

### Impact
**Processing only 25% of available telemetry data** leads to:
- Missing error correlation from logs
- No request flow analysis from traces
- No dynamic topology change detection
- Incomplete root cause evidence

### Improvement Required: **CRITICAL**

**Conceptual Changes Needed:**
1. **Trace-Based Latency Analysis**
   - Extract actual request latencies from traces
   - Track latency propagation through request chains
   - Identify p50, p95, p99 degradation patterns
   - Correlate slow traces with specific services

2. **Log-Based Error Analysis**
   - Parse error messages and exceptions
   - Identify error patterns and stack traces
   - Correlate errors with metric anomalies
   - Detect error propagation chains

3. **Topology State Analysis**
   - Track dynamic topology changes
   - Detect pod restarts, scaling events
   - Identify network partition events
   - Correlate topology changes with degradation

---

## 2. Temporal Analysis: Missing Dimension

### Current State (whitebox_rca)
```python
# No temporal analysis
# Simply compares baseline vs current windows
# No concept of "who was impacted first"
```

### Required State (batch_rca_discovery)
```python
✅ First impact time tracking
✅ Temporal causality validation
✅ Propagation delay measurement
✅ Time-window adaptive analysis
✅ Temporal consistency checking
```

### Impact
Without temporal analysis:
- Cannot distinguish root cause from cascading effects
- No understanding of fault propagation timeline
- Cannot validate causality ("A caused B" requires A happened first)
- Missing critical evidence for root cause ranking

### Improvement Required: **CRITICAL**

**Conceptual Changes Needed:**

1. **First Impact Time Detection**
   ```python
   # For each node, detect when it first showed degradation
   # Example: Node A degraded at t=80s, Node B at t=85s
   # Strong evidence: A caused B (not vice versa)
   ```

2. **Temporal Causality Validation**
   ```python
   # Rule: A can only cause B if A degraded before B
   # Reject candidates that degraded after their victims
   ```

3. **Propagation Timeline Construction**
   ```python
   # Build timeline: Root → Immediate victims → Downstream victims
   # Measure propagation delays: "B degraded 5s after A"
   ```

4. **Adaptive Time Windows**
   ```python
   # Larger topologies need larger windows (propagation takes time)
   # Small topology: 10s window
   # Large topology: 30s window
   ```

---

## 3. Probabilistic Scoring: Oversimplified Approach

### Current State (whitebox_rca)
```python
# Simple additive score
final_score = (guilt_ratio * 100) + (self_score * 5) + impact_bonus

# Binary threshold: score > 10.0 = candidate
# No probabilistic reasoning
# No confidence levels
```

### Required State (batch_rca_discovery)
```python
✅ Multi-dimensional probability calculation
✅ Bayesian evidence combination
✅ Confidence levels (HIGH/MEDIUM/LOW)
✅ Evidence weighting by reliability
✅ Fault signature matching
```

### Impact
Oversimplified scoring leads to:
- Poor ranking of candidates
- No uncertainty quantification
- Equal weight to unreliable evidence
- Missing domain-specific patterns

### Improvement Required: **HIGH**

**Conceptual Changes Needed:**

1. **Multi-Dimensional Evidence**
   ```python
   probability = f(
       leaf_node_score,        # Is it a dependency endpoint?
       dependency_health,       # All dependencies healthy?
       convergence_score,       # Multiple paths point here?
       severity_score,          # How severe is degradation?
       temporal_score,          # Impacted first?
       signature_match,         # Matches known fault pattern?
       centrality_score         # Topology position
   )
   ```

2. **Bayesian Evidence Combination**
   ```python
   # Start with prior probability
   # Update with each piece of evidence
   # Strong evidence (temporal) gets high weight
   # Weak evidence (centrality) gets low weight
   ```

3. **Confidence Levels**
   ```python
   if probability > 0.7 and strong_evidence_count >= 3:
       confidence = "HIGH"
   elif probability > 0.4 and strong_evidence_count >= 2:
       confidence = "MEDIUM"
   else:
       confidence = "LOW"
   ```

4. **Fault Signature Matching**
   ```python
   # CPU saturation signature: high CPU + high threads + low errors
   # Memory leak signature: steadily increasing memory + eventual OOM
   # Deadlock signature: high latency + low CPU + no errors
   # Network partition: 100% errors + all dependencies unreachable
   ```

---

## 4. Dependency Analysis: Shallow Understanding

### Current State (whitebox_rca)
```python
# Only checks: "Did caller or callee degrade?"
# No understanding of dependency health
# No leaf node detection
```

### Required State (batch_rca_discovery)
```python
✅ Leaf node identification (no dependencies = likely root cause)
✅ Dependency health checking (all deps healthy = likely root cause)
✅ Multi-path convergence analysis
✅ Transitive dependency tracking
```

### Impact
Shallow dependency analysis causes:
- Cannot distinguish root cause from intermediate nodes
- Misses strong evidence: "All my dependencies are healthy, but I'm sick = I'm root cause"
- Cannot leverage graph structure effectively

### Improvement Required: **HIGH**

**Conceptual Changes Needed:**

1. **Leaf Node Detection**
   ```python
   # Rule: Node with no outgoing dependencies
   # Strong indicator: "If I'm sick but have no dependencies,
   #                    I must be the root cause"
   # Example: Database has no dependencies → likely root cause
   ```

2. **All Dependencies Healthy Check**
   ```python
   # For each degraded node:
   #   - Check health of ALL dependencies
   #   - If all healthy but node sick → strong root cause evidence
   #
   # Example: Service A calls Services B, C, D
   #          B, C, D all healthy, but A degraded
   #          Strong evidence: A is root cause (not B, C, or D)
   ```

3. **Multi-Path Convergence**
   ```python
   # Count how many degraded nodes point to this node
   # More paths converging = stronger evidence
   #
   # Example: Services A, B, C, D all call Database E
   #          A, B, C, D all degraded
   #          Strong evidence: E is root cause (common dependency)
   ```

4. **Transitive Dependency Tracking**
   ```python
   # Track full dependency chains
   # Example: A → B → C → D
   #          If D degraded, check entire chain
   #          Strong evidence if only D sick (rest healthy)
   ```

---

## 5. Pod-Level Analysis: Missing Aggregation Intelligence

### Current State (whitebox_rca)
```python
# Simple aggregation: average + max score
# No outlier detection
# No noisy neighbor detection
# No pod forensics
```

### Required State (batch_rca_discovery)
```python
✅ Hot pod detection (one pod much worse than others)
✅ Outlier pod identification
✅ Noisy neighbor detection (co-location issues)
✅ Pod failure pattern analysis
✅ Service-level impact aggregation
```

### Impact
Missing pod intelligence causes:
- Cannot detect single-pod failures vs service-wide issues
- Misses co-location/noisy neighbor problems
- Poor service-level aggregation quality

### Improvement Required: **MEDIUM**

**Conceptual Changes Needed:**

1. **Hot Pod Detection**
   ```python
   # Identify pods significantly worse than siblings
   # Example: Service has 4 pods
   #          3 pods: healthy
   #          1 pod: 10x worse latency
   # Evidence: Single pod issue (maybe noisy neighbor, bad deployment)
   ```

2. **Statistical Outlier Detection**
   ```python
   # For each service's pods:
   #   - Calculate mean, std of key metrics
   #   - Flag pods > 3 std deviations from mean
   #   - Different interpretation if 1 outlier vs all pods degraded
   ```

3. **Noisy Neighbor Detection**
   ```python
   # Check if outlier pods share compute nodes
   # Example: pod_A_1 and pod_B_2 both on node_X
   #          Both degraded, others healthy
   # Evidence: node_X resource contention issue
   ```

4. **Service-Level Aggregation Strategy**
   ```python
   # Current: (avg + max) / 2
   # Better: Weighted by pod impact severity
   #
   # If 1 outlier pod: Lower service score (isolated issue)
   # If all pods degraded: Higher service score (systemic issue)
   ```

---

## 6. Convergence Analysis: Missing Critical Evidence

### Current State (whitebox_rca)
```python
# No convergence analysis
# Each edge analyzed independently
# No multi-path reasoning
```

### Required State (batch_rca_discovery)
```python
✅ Multi-path convergence scoring
✅ Convergence path counting
✅ Common dependency identification
✅ Convergence-based probability boosting
```

### Impact
Missing convergence analysis loses:
- Strongest evidence for database/cache root causes
- Cannot detect "common bottleneck" patterns
- Poor ranking of hub nodes even when truly faulty

### Improvement Required: **HIGH**

**Conceptual Changes Needed:**

1. **Convergence Path Counting**
   ```python
   # Count degraded nodes pointing to candidate
   # Example: Database D
   #          Services A, B, C, E all call D
   #          A, B, C, E all degraded
   #          Convergence score: 4/5 = 0.8 (4 degraded, 5 total callers)
   #
   # Strong evidence: Most callers degraded → common dependency issue
   ```

2. **Common Dependency Identification**
   ```python
   # Find nodes that are dependencies of many degraded nodes
   # Example topology:
   #   Frontend → [Auth, User, Order] → Database
   #   Auth, User, Order all degraded
   #   Frontend: 0 convergence (source, not dependency)
   #   Database: HIGH convergence (3 degraded nodes depend on it)
   ```

3. **Convergence vs Hub Bias Balance**
   ```python
   # Current approach: guilt_ratio prevents hub false positives
   # Problem: Also prevents hub true positives!
   #
   # Solution: Use convergence score
   #   - High convergence + hub node = likely true root cause
   #   - Low convergence + hub node = likely cascading effect
   ```

---

## 7. Network Partition Detection: Completely Missing

### Current State (whitebox_rca)
```python
# No network partition detection
# Treats 100% error rates as normal degradation
```

### Required State (batch_rca_discovery)
```python
✅ Network partition detection
✅ Error pattern analysis
✅ Reachability checking
✅ Partition impact assessment
```

### Impact
Missing network partition detection causes:
- Misdiagnosis of connectivity issues as service degradation
- Cannot detect split-brain scenarios
- Poor handling of infrastructure failures

### Improvement Required: **MEDIUM**

**Conceptual Changes Needed:**

1. **Partition Detection Heuristics**
   ```python
   # Pattern: Node has 100% errors to all dependencies
   # Example: Service A calls B, C, D
   #          A → B: 100% errors
   #          A → C: 100% errors
   #          A → D: 100% errors
   # Evidence: Network partition (not A degraded)
   ```

2. **Reachability Matrix**
   ```python
   # Build matrix of which nodes can reach which
   # Identify partition boundaries
   # Example: {A, B, C} can reach each other
   #          {D, E} can reach each other
   #          No cross-group reachability
   # Evidence: Two partitions
   ```

3. **Error Pattern Analysis**
   ```python
   # 100% errors = connectivity issue
   # 50% errors = service degradation
   # Sporadic errors = transient issues
   #
   # Different root cause implications
   ```

---

## 8. Fault Signature Library: Missing Domain Knowledge

### Current State (whitebox_rca)
```python
# Basic heuristics only:
#   - Resource saturation: high CPU/memory
#   - Limp mode: high latency + low CPU
# No signature library
# No pattern matching
```

### Required State (batch_rca_discovery)
```python
✅ Comprehensive fault signature library
✅ Pattern matching engine
✅ Signature-based probability adjustment
✅ Known fault pattern recognition
```

### Impact
Missing fault signatures loses:
- Domain expertise encoding
- Pattern-based detection improvements
- Faster diagnosis of known issues

### Improvement Required: **MEDIUM**

**Conceptual Changes Needed:**

1. **Fault Signature Library**
   ```python
   signatures = {
       'cpu_saturation': {
           'metrics': ['cpu_usage', 'thread_pool_active'],
           'thresholds': {'cpu_usage': 0.8, 'threads': 0.9},
           'pattern': 'sustained_high',
           'interpretation': 'CPU exhaustion preventing request processing'
       },
       'memory_leak': {
           'metrics': ['memory_usage'],
           'pattern': 'monotonic_increase',
           'interpretation': 'Memory leak causing gradual degradation'
       },
       'deadlock': {
           'metrics': ['avg_latency', 'cpu_usage', 'error_rate'],
           'pattern': {'latency': 'critical', 'cpu': 'low', 'errors': 'low'},
           'interpretation': 'Thread deadlock or hung process'
       },
       'connection_pool_exhaustion': {
           'metrics': ['db_connections', 'db_latency', 'queue_depth'],
           'pattern': 'connection_limit_reached',
           'interpretation': 'Database connection pool exhausted'
       },
       'retry_storm': {
           'metrics': ['outbound_rps', 'dependency_errors'],
           'pattern': 'simultaneous_spike',
           'interpretation': 'Retry amplification from downstream failure'
       }
   }
   ```

2. **Pattern Matching Engine**
   ```python
   def match_signature(metrics, signature):
       score = 0
       matched_metrics = []

       for metric in signature['metrics']:
           if metric in metrics:
               if matches_pattern(metrics[metric], signature):
                   score += 1
                   matched_metrics.append(metric)

       match_percentage = score / len(signature['metrics'])
       return match_percentage, matched_metrics
   ```

3. **Signature-Based Probability Boost**
   ```python
   # If fault signature matches known pattern:
   #   - Boost probability by match percentage
   #   - Add signature name to reasoning
   #   - Increase confidence level
   ```

---

## 9. Health Classification: Binary vs Nuanced

### Current State (whitebox_rca)
```python
# Binary: degraded or not (score > threshold)
# No health levels
# No classification system
```

### Required State (batch_rca_discovery)
```python
✅ Multi-level health classification
✅ Nuanced thresholds per metric type
✅ Health categories: healthy/degraded/impacted/critical
✅ Context-aware classification
```

### Impact
Binary classification causes:
- Cannot distinguish severity levels
- Poor prioritization of candidates
- Misses subtle degradation patterns

### Improvement Required: **LOW**

**Conceptual Changes Needed:**

1. **Multi-Level Health**
   ```python
   health_levels = {
       'healthy': {
           'cpu': < 0.6,
           'latency': < 1.5x baseline,
           'errors': < 1%
       },
       'degraded': {
           'cpu': 0.6-0.8,
           'latency': 1.5-3x baseline,
           'errors': 1-5%
       },
       'impacted': {
           'cpu': 0.8-0.95,
           'latency': 3-5x baseline,
           'errors': 5-20%
       },
       'critical': {
           'cpu': > 0.95,
           'latency': > 5x baseline,
           'errors': > 20%
       }
   }
   ```

2. **Context-Aware Thresholds**
   ```python
   # Different thresholds for different node types
   # Database: Higher CPU tolerance
   # Gateway: Lower latency tolerance
   # Cache: Very low latency tolerance
   ```

---

## 10. Reasoning and Explainability: Weak

### Current State (whitebox_rca)
```python
# Basic causal narrative
# No detailed reasoning
# No evidence summary
```

### Required State (batch_rca_discovery)
```python
✅ Detailed reasoning per candidate
✅ Evidence enumeration
✅ Confidence justification
✅ Supporting data references
```

### Impact
Weak reasoning reduces:
- Operator trust in results
- Debuggability of false positives
- Understanding of analysis logic

### Improvement Required: **LOW**

**Conceptual Changes Needed:**

1. **Structured Reasoning**
   ```python
   reasoning = [
       f"Leaf node (no dependencies)",
       f"Impacted first (t={first_impact}s)",
       f"High convergence ({convergence_score:.2f})",
       f"Matches signature: {signature_name}",
       f"All dependencies healthy",
       f"Temporal consistency validated"
   ]
   ```

2. **Evidence Summary**
   ```python
   evidence = {
       'strong': [
           'Temporal causality (impacted 15s before victims)',
           'All 5 dependencies healthy',
           'Matches CPU saturation signature (100%)'
       ],
       'medium': [
           'High convergence score (4/6 paths)',
           'Severity score 0.85'
       ],
       'weak': [
           'Centrality score 0.3'
       ]
   }
   ```

---

## Implementation Priority Matrix

| Feature | Impact | Complexity | Priority | Est. Effort |
|---------|--------|------------|----------|-------------|
| Trace-based latency analysis | CRITICAL | HIGH | P0 | 2-3 weeks |
| Temporal causality analysis | CRITICAL | HIGH | P0 | 2-3 weeks |
| Probabilistic scoring | HIGH | HIGH | P1 | 1-2 weeks |
| Dependency health analysis | HIGH | MEDIUM | P1 | 1 week |
| Convergence analysis | HIGH | MEDIUM | P1 | 1 week |
| Log-based error analysis | CRITICAL | MEDIUM | P2 | 1-2 weeks |
| Pod-level forensics | MEDIUM | MEDIUM | P2 | 1 week |
| Network partition detection | MEDIUM | LOW | P3 | 3-5 days |
| Fault signature library | MEDIUM | LOW | P3 | 1 week |
| Health classification | LOW | LOW | P4 | 2-3 days |

---

## Recommended Implementation Approach

### Phase 1: Foundation (4-6 weeks)
**Goal:** Add critical missing data sources and temporal analysis

1. **Add Trace Loading & Analysis**
   - Implement TraceLatencyAnalyzer integration
   - Extract p50/p95/p99 latencies per component
   - Track latency propagation through request chains

2. **Add Temporal Analysis**
   - Detect first impact time per node
   - Validate temporal causality
   - Build propagation timeline

3. **Add Dependency Health Analysis**
   - Implement leaf node detection
   - Check all-dependencies-healthy logic
   - Build transitive dependency tracker

### Phase 2: Intelligence (3-4 weeks)
**Goal:** Add sophisticated scoring and convergence analysis

4. **Implement Probabilistic Scoring**
   - Multi-dimensional probability calculation
   - Bayesian evidence combination
   - Confidence level assignment

5. **Add Convergence Analysis**
   - Multi-path convergence scoring
   - Common dependency identification
   - Convergence-based ranking

6. **Add Pod Forensics**
   - Hot pod detection
   - Outlier analysis
   - Noisy neighbor detection

### Phase 3: Completeness (2-3 weeks)
**Goal:** Add remaining features for production readiness

7. **Add Log Analysis**
   - Error pattern extraction
   - Stack trace parsing
   - Error correlation with metrics

8. **Add Network Partition Detection**
   - Partition detection heuristics
   - Reachability matrix
   - Error pattern analysis

9. **Add Fault Signature Library**
   - Define signature patterns
   - Implement pattern matching
   - Signature-based probability adjustment

### Phase 4: Polish (1 week)
**Goal:** Improve usability and explainability

10. **Enhance Reasoning**
    - Structured evidence enumeration
    - Detailed confidence justification
    - Rich causal narratives

---

## Expected Outcomes

After full implementation:

**Performance:**
- Analysis time: **20-60 seconds/episode** (10-20x slower than current)
- Still faster than current batch_rca_discovery (63s)

**Accuracy:**
- Expected: **60-80% top-5 accuracy** (vs current 38.9%)
- Improvement: **1.5-2x better** than current

**Completeness:**
- Use **100% of telemetry** (vs current 25%)
- **10+ evidence dimensions** (vs current 3)
- **Probabilistic reasoning** (vs simple additive scoring)

**Maintainability:**
- **Modular design** (each analysis component separate)
- **Well-tested** (unit tests per component)
- **Documented** (clear reasoning explanations)

---

## Alternative: Use Existing SOTA Analyzer

**Recommendation:** Instead of rewriting whitebox_rca, consider:

1. **Use sota_propagation_analyzer directly**
   - Already implements all features above
   - Tested and production-ready
   - Comprehensive analysis

2. **Wrap sota_propagation_analyzer**
   - Add service-level aggregation wrapper
   - Add marker file system
   - Keep existing batch processing framework

3. **Benefits:**
   - **Immediate improvement** (no implementation time)
   - **Proven accuracy** (already comprehensive)
   - **Maintained codebase** (existing tests/docs)

**Trade-off:** Slower (63s vs 2.9s), but **much more accurate**

---

## Conclusion

The whitebox_rca.py implementation is **conceptually incomplete** in fundamental ways:

1. **Uses 25% of data** (metrics only, ignores logs/traces)
2. **No temporal reasoning** (cannot establish causality)
3. **Oversimplified scoring** (additive vs probabilistic)
4. **Shallow dependency analysis** (misses critical evidence)
5. **No convergence reasoning** (weak hub node handling)
6. **Missing domain knowledge** (no fault signatures)

**Recommendation:** Either **fully implement the missing features** (10-14 weeks effort) or **use the existing SOTA analyzer** (immediate, proven solution).

The choice depends on:
- **Time available:** Existing SOTA analyzer wins for immediate needs
- **Learning goals:** Full implementation wins for understanding/research
- **Performance requirements:** Current whitebox wins for speed (but at cost of accuracy)
- **Accuracy requirements:** SOTA analyzer wins for production use

For **production use**, recommend using `sota_propagation_analyzer` with service-level aggregation wrapper.
