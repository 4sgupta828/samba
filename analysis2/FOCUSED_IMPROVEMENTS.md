# Focused Improvements for Whitebox RCA

## Goal
Make `whitebox_rca.py` the **production-ready main RCA tool** by adding **only what's truly needed** for accuracy, not replicating batch_rca_discovery unnecessarily.

## Current Performance Analysis

### What's Working Well ✅
- **Fast execution**: 2.9s per episode (acceptable for production)
- **Clean architecture**: Modular design with clear separation
- **Service-level aggregation**: Correctly maps pods to services
- **Basic heuristics**: Resource saturation and limp mode detection work
- **Hub bias correction**: Guilt ratio prevents false database accusations

### What's Broken ❌
- **38.9% accuracy** (7/18 correct) - **NOT PRODUCTION READY**
- **No temporal analysis** - Cannot determine causality
- **Only uses metrics** - Ignoring logs and traces
- **Weak scoring** - Simple additive formula

---

## Root Cause Analysis of Our Low Accuracy

### Analysis of Failure Cases

Looking at our 11 failures (out of 18 episodes):

**Pattern 1: Wrong candidate wins (8 cases)**
- Example: Ground truth = `notification_service`, Top result = `billing_service`
- **Root cause**: Simpler scoring doesn't distinguish between:
  - Actual root cause (degraded first, caused others)
  - Victim service (degraded second, caused by others)

**Pattern 2: No anomalies detected (3 cases)**
- **Root cause**: Threshold too high (score > 10.0) filters out subtle faults
- Missing: Low-level persistent degradation patterns

**Key Insight:** We're not losing because of missing complexity - we're losing because we **can't tell who degraded first**.

---

## The 3 Critical Improvements (Must Have)

### 1. Temporal Causality Analysis ⭐⭐⭐ CRITICAL

**Problem:** Currently treats all degradation as simultaneous.

**Example of Current Failure:**
```
Service A and Service B both degraded.
A calls B.
Current algorithm: Can't tell if A caused B or B caused A.
Result: Picks based on score (often wrong).
```

**Solution:** Track when each node first showed degradation.

**Implementation:**
```python
def detect_first_impact_time(baseline, current, fault_start_time, metrics_df):
    """
    For each node, find the earliest time it showed anomaly.

    Uses CHANGEPOINT DETECTION (not simple thresholds) to avoid noise.

    Returns: {node_id: first_impact_time}
    """
    from statistical_utils import detect_changepoint

    first_impacts = {}

    for node_id in current.keys():
        # Get time-series data for this node from metrics_df
        node_data = metrics_df[metrics_df['component_id'] == node_id]

        earliest_time = float('inf')

        # Check critical metrics for changepoints
        critical_metrics = ['cpu_usage', 'memory_usage', 'avg_latency',
                          'internal_error_rate', 'thread_pool_active']

        for metric_name in critical_metrics:
            metric_data = node_data[node_data['name'].str.contains(metric_name, na=False)]
            if len(metric_data) == 0:
                continue

            # Sort by time and extract values
            metric_data = metric_data.sort_values('sim_time')
            times = metric_data['sim_time'].values
            values = metric_data['value'].values

            # Use PELT/BinSeg changepoint detection (from statistical_utils.py)
            has_changepoint = detect_changepoint(values)

            if has_changepoint:
                # Find the time of the changepoint
                # Split data at fault_start and check for changes after
                post_fault_idx = np.searchsorted(times, fault_start_time)
                if post_fault_idx < len(times):
                    # Use robust changepoint detection on post-fault window
                    post_fault_values = values[post_fault_idx:]
                    post_fault_times = times[post_fault_idx:]

                    if len(post_fault_values) > 5:
                        # Detect when the change occurred
                        changepoint_idx = detect_changepoint_index(post_fault_values)
                        if changepoint_idx:
                            impact_time = post_fault_times[changepoint_idx]
                            earliest_time = min(earliest_time, impact_time)

        if earliest_time < float('inf'):
            first_impacts[node_id] = earliest_time

    return first_impacts
```

**Critical Note:** Use changepoint detection (PELT/BinSeg from statistical_utils.py), NOT simple threshold crossing. Thresholds are noisy and will give false positives on normal variance.

**Scoring Impact (Graph-Aware):**
```python
# Add graph-aware temporal score
temporal_score = 0
if node_id in first_impacts:
    # Calculate relative impact time
    earliest_time = min(first_impacts.values())
    relative_time = first_impacts[node_id] - earliest_time

    # Check if this node is upstream of other degraded nodes
    downstream_victims = []
    for victim_id in first_impacts:
        if victim_id != node_id:
            # Check if there's a path from node_id to victim_id
            if nx.has_path(topology, node_id, victim_id):
                victim_time = first_impacts[victim_id]
                # Victim degraded AFTER this node?
                if victim_time > first_impacts[node_id]:
                    downstream_victims.append(victim_id)

    # Score based on timing + causality
    if relative_time < 5:  # Degraded within 5s of earliest
        base_score = 10.0
        # Boost if downstream nodes degraded later (causal evidence)
        if len(downstream_victims) > 0:
            temporal_score = base_score + (len(downstream_victims) * 2)  # +2 per victim
        else:
            temporal_score = base_score
    elif relative_time < 15:
        temporal_score = 5.0
    else:
        temporal_score = 0  # Likely victim, not cause

final_score = (guilt_ratio * 100) + (self_score * 5) + impact_bonus + temporal_score
```

**Key Refinement:** Not just "who degraded first" but "who degraded first AND has downstream victims who degraded later". This prevents scoring unrelated nodes that happened to degrade early.

**Expected Impact:**
- Fix ~60% of wrong rankings (can now distinguish cause from effect)
- **Estimated accuracy improvement: 38% → 60%+**

**Effort:** 1 week

---

### 2. Trace-Based Latency Analysis ⭐⭐⭐ CRITICAL

**Problem:** Metrics show "latency increased" but not WHERE in the request chain.

**Example of Current Failure:**
```
Frontend → API → Database
All three show high latency.
Current: Picks API (middle node, highest score).
Reality: Database is root cause, others are victims of its slowness.
```

**Solution:** Use traces to see request flow and pinpoint where latency originates.

**Implementation:**
```python
def analyze_trace_latency(traces_file, fault_start_time):
    """
    Extract actual latencies from distributed traces.

    Key distinction: SELF TIME vs TOTAL TIME
    - Total time: Full span duration (includes waiting on dependencies)
    - Self time: Time spent in this component's logic (excludes child spans)

    Returns: Which component's INTERNAL processing added latency.
    """
    # Load traces (JSONL format)
    traces = []
    with open(traces_file) as f:
        for line in f:
            trace = json.loads(line)
            traces.append(trace)

    # Split into baseline vs fault period
    baseline_traces = [t for t in traces if t['timestamp'] < fault_start_time]
    fault_traces = [t for t in traces if t['timestamp'] >= fault_start_time]

    component_latencies = {}

    # Build trace tree to calculate self-time
    for component_id in get_components_from_traces(traces):
        # Extract spans for this component
        baseline_spans = extract_component_spans(baseline_traces, component_id)
        fault_spans = extract_component_spans(fault_traces, component_id)

        # Calculate TOTAL duration (full span)
        baseline_total_p99 = np.percentile([s['duration_ms'] for s in baseline_spans], 99)
        fault_total_p99 = np.percentile([s['duration_ms'] for s in fault_spans], 99)

        # Calculate SELF duration (subtract child spans)
        baseline_self_durations = []
        for span in baseline_spans:
            self_time = calculate_self_time(span, baseline_traces)
            baseline_self_durations.append(self_time)

        fault_self_durations = []
        for span in fault_spans:
            self_time = calculate_self_time(span, fault_traces)
            fault_self_durations.append(self_time)

        baseline_self_p99 = np.percentile(baseline_self_durations, 99) if baseline_self_durations else 0
        fault_self_p99 = np.percentile(fault_self_durations, 99) if fault_self_durations else 0

        component_latencies[component_id] = {
            # Total time metrics
            'baseline_total_p99': baseline_total_p99,
            'fault_total_p99': fault_total_p99,
            'total_degradation_factor': fault_total_p99 / baseline_total_p99 if baseline_total_p99 > 0 else 1.0,

            # Self time metrics (AUTHORITATIVE for root cause)
            'baseline_self_p99': baseline_self_p99,
            'fault_self_p99': fault_self_p99,
            'self_time_degradation_factor': fault_self_p99 / baseline_self_p99 if baseline_self_p99 > 0 else 1.0,
        }

    return component_latencies

def calculate_self_time(span, all_traces):
    """
    Calculate self time: duration minus child span durations.

    Example:
    Parent span: 100ms total
    Child span 1: 40ms
    Child span 2: 30ms
    Self time: 100 - 40 - 30 = 30ms (time in parent's logic)
    """
    total_time = span['duration_ms']
    child_time = 0

    # Find child spans (same trace_id, this span is parent)
    for trace in all_traces:
        if trace.get('trace_id') == span.get('trace_id'):
            if trace.get('parent_span_id') == span.get('span_id'):
                child_time += trace.get('duration_ms', 0)

    return max(0, total_time - child_time)
```

**Critical: Self-Time Calculation**
- Service A total: 100ms, but 95ms waiting on Service B → Self-time: 5ms (healthy)
- Service B total: 95ms, self-time: 95ms (no children) → Root cause!

This is why trace analysis is authoritative.

**Scoring Impact (Authoritative):**
```python
# Trace analysis is AUTHORITATIVE - supersedes heuristics
trace_evidence_score = 0
trace_is_authoritative = False

if component_id in trace_latencies:
    degradation = trace_latencies[component_id]['degradation_factor']

    # Check if this component's INTERNAL processing is slow
    # (not just waiting on dependencies)
    if trace_latencies[component_id].get('self_time_degradation_factor', 1.0) > 2.0:
        # This component itself is slow (authoritative evidence)
        trace_evidence_score = 15.0
        trace_is_authoritative = True
    elif degradation > 5.0:
        # Total latency is high (but might be waiting on deps)
        trace_evidence_score = 10.0
    elif degradation > 2.0:
        trace_evidence_score = 5.0

# Use trace data to override heuristics
if trace_is_authoritative:
    # If traces definitively show this component is slow,
    # don't rely on "Limp Mode" heuristic
    self_score = max(self_score, 8.0)  # Ensure high self-score

final_score = (guilt_ratio * 100) + (self_score * 5) + impact_bonus + temporal_score + trace_evidence_score
```

**Key Refinement:** Traces are the ground truth. If traces show a component's internal processing is slow (not just waiting), that's authoritative evidence. Override heuristics like "Limp Mode" when we have trace data.

**Expected Impact:**
- Correctly identify bottlenecks in request chains
- Distinguish between "slow because I'm slow" vs "slow because waiting on dependency"
- **Estimated accuracy improvement: +10-15%**

**Effort:** 1-2 weeks

---

### 3. Improved Threshold and Scoring ⭐⭐ HIGH

**Problem:** Fixed threshold (score > 10.0) misses subtle faults.

**Current Issue:**
```python
if final_score > 10.0:  # Hard threshold
    rankings.append(node)
# Result: Misses 3 episodes with subtle degradation
```

**Solution:** Adaptive thresholds + relative ranking.

**Implementation:**
```python
# Remove hard threshold - rank ALL nodes
rankings = []
for node in self.topology.nodes:
    final_score = calculate_score(node)  # Always calculate
    rankings.append({
        'node': node,
        'score': final_score,
        # ... other fields
    })

# Sort by score descending
sorted_rankings = sorted(rankings, key=lambda x: x['score'], reverse=True)

# Return top N candidates (even if scores are low)
return sorted_rankings  # Let top-K filtering happen at validation time
```

**Scoring Formula Refinement:**
```python
# Current formula is okay, but add normalization
final_score = (
    guilt_ratio * 100.0 +           # External evidence (0-100)
    self_score * 5.0 +              # Internal evidence (0-50)
    impact_bonus +                   # Traffic (0-3)
    temporal_score +                 # When degraded (0-10)
    trace_evidence_score            # Trace latency (0-10)
)

# Normalize to 0-1 probability
probability = sigmoid(final_score / 50.0)  # Calibrate denominator based on data
```

**Expected Impact:**
- Catch subtle faults (fix "no anomalies" cases)
- Better relative ranking
- **Estimated accuracy improvement: +5-10%**

**Effort:** 3-5 days

---

## The 2 Important Improvements (Should Have)

### 4. Log Error Correlation ⭐⭐ IMPORTANT

**Problem:** Ignoring error logs means missing explicit failure signals.

**Value:** Logs contain smoking guns like:
- "OutOfMemoryError"
- "Connection pool exhausted"
- "Deadlock detected"
- "Timeout after 5000ms"

**Implementation:**
```python
def analyze_error_logs(logs_file, fault_start_time):
    """
    Extract error patterns from logs.

    Focus on: Error rate spikes, specific error types
    """
    logs = load_logs(logs_file)

    # Count errors per component before/after fault
    error_counts = defaultdict(lambda: {'baseline': 0, 'fault': 0})

    for log in logs:
        component_id = log['labels'].get('component.id')
        level = log.get('level', 'INFO')
        timestamp = log['timestamp']

        if level in ['ERROR', 'FATAL']:
            if timestamp < fault_start_time:
                error_counts[component_id]['baseline'] += 1
            else:
                error_counts[component_id]['fault'] += 1

    # Calculate error rate increase
    error_evidence = {}
    for component_id, counts in error_counts.items():
        baseline_rate = counts['baseline']
        fault_rate = counts['fault']

        if baseline_rate == 0 and fault_rate > 5:
            # New errors appeared
            error_evidence[component_id] = {
                'score': 10.0,
                'reason': f'New errors: {fault_rate} errors in fault period'
            }
        elif fault_rate > baseline_rate * 5:
            # 5x error increase
            error_evidence[component_id] = {
                'score': 5.0,
                'reason': f'Error spike: {baseline_rate} → {fault_rate}'
            }

    return error_evidence
```

**Expected Impact:**
- Catch error-driven failures (OOM, connection pool exhaustion)
- **Estimated accuracy improvement: +5-8%**

**Effort:** 1 week

---

### 5. Dependency Health Check ⭐⭐ IMPORTANT

**Problem:** Can't distinguish "I'm sick because I'm broken" vs "I'm sick because my dependency is broken".

**Strong Evidence Pattern:**
```
If (Node degraded) AND (All dependencies healthy):
    → Strong evidence: Node is root cause

If (Node degraded) AND (Dependencies also degraded):
    → Weak evidence: Node might be victim
```

**Implementation:**
```python
def check_dependency_health(node_id, topology, self_scores):
    """
    Check if all dependencies of this node are healthy.
    """
    dependencies = list(topology.successors(node_id))

    if not dependencies:
        # Leaf node (no dependencies)
        return {
            'is_leaf': True,
            'all_deps_healthy': True,  # Vacuously true
            'leaf_score': 10.0
        }

    healthy_count = 0
    for dep in dependencies:
        dep_score = self_scores.get(dep, 0)
        if dep_score < 2.0:  # Dependency is healthy
            healthy_count += 1

    all_healthy = (healthy_count == len(dependencies))

    return {
        'is_leaf': False,
        'all_deps_healthy': all_healthy,
        'dependency_health_score': 10.0 if all_healthy else 0.0
    }
```

**Scoring Impact:**
```python
dep_health = check_dependency_health(node_id, topology, self_scores)

final_score = (
    guilt_ratio * 100.0 +
    self_score * 5.0 +
    impact_bonus +
    temporal_score +
    trace_evidence_score +
    dep_health['dependency_health_score'] +  # +10 if all deps healthy
    dep_health.get('leaf_score', 0)          # +10 if leaf node
)
```

**Expected Impact:**
- Better distinguish root cause from cascading effects
- **Estimated accuracy improvement: +5%**

**Effort:** 3-4 days

---

## What We DON'T Need (Explicitly Excluding)

### ❌ Probabilistic Bayesian Scoring
**Why skip:** Current additive scoring works fine. Adding Bayesian complexity won't improve accuracy significantly (maybe 2-3%), not worth the complexity.

### ❌ Fault Signature Library
**Why skip:** Pattern matching is nice-to-have, not critical. We already detect saturation/limp mode. Signatures would add 3-5% accuracy at most.

### ❌ Network Partition Detection
**Why skip:** Rare case. Only helps in <5% of scenarios. Can add later if needed.

### ❌ Multi-level Health Classification
**Why skip:** Binary "degraded or not" is sufficient. Nuanced levels don't improve root cause detection.

### ❌ Convergence Counting
**Why skip:** Guilt ratio already handles this. Convergence analysis would be redundant.

### ❌ Pod Outlier Detection
**Why skip:** Service-level aggregation already works. Pod forensics are over-engineering.

---

## Implementation Roadmap

### Phase 1: Critical Path (2-3 weeks)
**Goal:** Get to 60%+ accuracy

**Week 1: Temporal Analysis**
- [ ] Add metrics_df time-series preservation to DatasetAdapter
- [ ] Implement changepoint-based first impact detection (use statistical_utils.py)
- [ ] Add graph-aware temporal scoring (check downstream victims)
- [ ] Test temporal causality on known cascading failures

**Week 2: Trace Analysis**
- [ ] Add traces.jsonl loading to DatasetAdapter
- [ ] Implement trace parser (JSONL → span objects)
- [ ] Implement self-time calculation (key for root cause attribution)
- [ ] Calculate baseline vs fault latency distributions (p99, not just mean)
- [ ] Make trace evidence authoritative (override heuristics when available)

**Week 3: Scoring Refinement**
- [ ] Remove hard threshold (score > 10.0)
- [ ] Integrate temporal + trace scores into formula
- [ ] Tune weights: `temporal_score` weight = ?, `trace_score` weight = ?
- [ ] Run full evaluation on 18 episodes
- [ ] Analyze remaining failures (is it data quality or algorithm?)

**Expected Result:** 60-70% top-5 accuracy

**Success Criteria:**
- Can correctly order A→B causality when A degraded first
- Can identify database as root cause when it has high self-time
- No "no anomalies" failures (eliminated by threshold removal)

### Phase 2: Refinement (1-2 weeks)
**Goal:** Get to 70%+ accuracy

**Week 4:**
- [ ] Add log error correlation
- [ ] Add dependency health checking
- [ ] Final tuning

**Expected Result:** 70-80% top-5 accuracy

---

## Success Metrics

### Performance Target
- **Execution time:** < 10 seconds per episode (allow 3x slowdown for 2x accuracy)
- **Current:** 2.9s → **Target:** < 10s

### Accuracy Target
- **Current:** 38.9% (7/18)
- **After Phase 1:** 60-70% (11-13/18)
- **After Phase 2:** 70-80% (13-15/18)

### Production Readiness
- ✅ Handles all data sources (metrics, traces, logs)
- ✅ Service-level aggregation
- ✅ Marker file system
- ✅ Comprehensive output
- ✅ 70%+ accuracy

---

## Effort Breakdown

| Improvement | Effort | Impact | Priority |
|-------------|--------|--------|----------|
| Temporal analysis | 1 week | +20% | P0 - MUST |
| Trace latency | 1-2 weeks | +15% | P0 - MUST |
| Scoring refinement | 3-5 days | +10% | P0 - MUST |
| Log error correlation | 1 week | +8% | P1 - SHOULD |
| Dependency health | 3-4 days | +5% | P1 - SHOULD |
| **TOTAL** | **4-5 weeks** | **+58%** | **Target: 70%** |

---

## The Plan Forward

### Immediate Next Steps:
1. ✅ Document created (this file)
2. 🔲 Implement temporal analysis first (biggest impact)
3. 🔲 Add trace loading and analysis
4. 🔲 Test and tune on full dataset
5. 🔲 Add log correlation if needed
6. 🔲 Production deployment

### Decision Points:
- **After Phase 1:** Evaluate accuracy. If 65%+, proceed to Phase 2.
- **After Phase 2:** Evaluate accuracy. If 75%+, declare production ready.

### Fallback Plan:
If accuracy < 60% after Phase 1, investigate:
- Are we loading data correctly?
- Are thresholds calibrated properly?
- Do we need more sophisticated scoring?

---

## Conclusion

**The whitebox RCA needs 3 critical improvements:**
1. **Temporal analysis** - Know who degraded first
2. **Trace analysis** - Know where latency originates
3. **Better thresholds** - Don't miss subtle faults

**We DON'T need:**
- Complex probabilistic models
- Extensive signature libraries
- Multi-level classifications
- Pod-level forensics

**Implementation:** 4-5 weeks of focused work will get us from 38% → 70%+ accuracy, making whitebox_rca production-ready as the main RCA tool.

**Keep it simple. Add only what's needed. Ship it.**
