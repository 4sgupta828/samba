# Implementation Notes for Whitebox RCA Improvements

## Critical Implementation Details

### 1. Changepoint Detection (Not Thresholds!)

**Why it matters:** Simple threshold crossing (e.g., "CPU > 80%") is noisy. Normal variance causes false alarms.

**Use existing code:**
```python
# From statistical_utils.py (already exists in codebase)
from statistical_utils import detect_changepoint

# Returns True if structural break detected in time series
has_changepoint = detect_changepoint(metric_values)
```

**Implementation detail:**
- Uses PELT (Pruned Exact Linear Time) algorithm
- Detects regime changes, not just threshold crossings
- More robust to noise than simple rules

**Where to use:**
- First impact time detection
- Determining when a node's health changed

---

### 2. Graph-Aware Temporal Scoring

**Why it matters:** Node X degrading first is only meaningful if nodes that depend on X degraded AFTER X.

**Key logic:**
```python
# For each candidate node
for node_id in degraded_nodes:
    # Find nodes downstream (that depend on this node)
    downstream = [v for v in degraded_nodes
                  if nx.has_path(topology, node_id, v)]

    # Check temporal ordering
    caused_downstream = [v for v in downstream
                        if first_impacts[v] > first_impacts[node_id]]

    # Score boost for each causal relationship
    temporal_score += len(caused_downstream) * 2.0
```

**Prevents false positives:**
- Node Z degrades first but is disconnected from incident → No boost
- Node A degrades first and downstream nodes degrade later → Boosted

---

### 3. Self-Time vs Total-Time in Traces

**Critical distinction:**

```
Frontend span: 100ms total
  ├─ Auth span: 20ms (child)
  ├─ Database span: 70ms (child)
  └─ Frontend logic: 10ms (self-time = 100 - 20 - 70)
```

**Interpretation:**
- Frontend total time: 100ms (high)
- Frontend self-time: 10ms (normal)
- **Conclusion:** Frontend is slow because waiting on Database, not because Frontend logic is broken

**Implementation:**
```python
def calculate_self_time(span, trace):
    """
    Self time = Total duration - Sum(child durations)
    """
    total = span['duration_ms']

    # Find all child spans
    children = [s for s in trace['spans']
               if s['parent_span_id'] == span['span_id']]

    child_time = sum(c['duration_ms'] for c in children)

    return max(0, total - child_time)
```

**Authoritative evidence:**
- High self-time degradation → This component's logic is slow (ROOT CAUSE)
- High total time, low self-time → Waiting on dependencies (VICTIM)

---

### 4. Trace Data Structure

**Expected format (traces.jsonl):**
```json
{
  "trace_id": "abc123",
  "span_id": "span_1",
  "parent_span_id": null,
  "component_id": "frontend",
  "operation": "handle_request",
  "timestamp": 165.0,
  "duration_ms": 100.5,
  "status": "OK"
}
{
  "trace_id": "abc123",
  "span_id": "span_2",
  "parent_span_id": "span_1",
  "component_id": "database",
  "operation": "query",
  "timestamp": 165.1,
  "duration_ms": 70.2,
  "status": "OK"
}
```

**Parsing considerations:**
- Group spans by trace_id to build trace trees
- Handle missing parent_span_id (root spans)
- Filter by timestamp to separate baseline vs fault periods
- Calculate p50, p95, p99 (not just mean) for robustness

---

### 5. Metrics Time-Series Preservation

**Current issue:** DatasetAdapter loads metrics into numpy arrays but loses timestamp information.

**Required change:**
```python
class DatasetAdapter:
    def __init__(self, episode_dir: Path):
        self.episode_dir = episode_dir
        self.label = self._load_json('label.json')
        self.topology = self._load_topology()

        # NEW: Keep full DataFrame, don't immediately window it
        self.metrics_df = self._load_metrics()  # Returns DataFrame with timestamps

    def get_data_windows(self):
        # Existing logic - return windowed data
        ...

    def get_time_series(self, node_id, metric_name):
        """NEW: Get full time series for temporal analysis"""
        node_data = self.metrics_df[self.metrics_df['component_id'] == node_id]
        metric_data = node_data[node_data['name'].str.contains(metric_name)]
        return metric_data.sort_values('sim_time')
```

**Why needed:** Temporal analysis requires knowing WHEN each metric changed, not just aggregate statistics.

---

### 6. Scoring Formula Weight Tuning

**Current formula:**
```python
final_score = (guilt_ratio * 100) + (self_score * 5) + impact_bonus
```

**Updated formula:**
```python
final_score = (
    guilt_ratio * 100.0 +           # External blame (0-100)
    self_score * 5.0 +              # Internal health (0-50)
    impact_bonus +                   # Traffic volume (0-3)
    temporal_score * 2.0 +          # When degraded (0-20) - TUNABLE
    trace_score * 2.0 +             # Trace evidence (0-30) - TUNABLE
    dependency_health_score         # All deps healthy (0-10)
)
```

**Tuning methodology:**
1. Run analysis on all 18 episodes with weights [1.0, 1.0, 1.0...]
2. Analyze failures: Which evidence type would fix them?
3. Increase weight for high-impact evidence types
4. Repeat until accuracy plateaus

**Expected weights (hypothesis):**
- Temporal: **2.0-3.0** (high impact on causality)
- Trace self-time: **2.0-3.0** (authoritative when available)
- Dependency health: **1.0** (strong but not always applicable)

---

### 7. Data Availability Handling

**Problem:** Not all episodes have traces/logs.

**Graceful degradation:**
```python
def analyze_incident(baseline, current, topology, episode_dir):
    # Always available
    self_health_scores = analyze_self_health(baseline, current)

    # Conditionally available
    temporal_scores = {}
    if (episode_dir / 'metrics.jsonl').exists():
        temporal_scores = analyze_temporal(episode_dir, baseline, current)

    trace_scores = {}
    if (episode_dir / 'traces.jsonl').exists():
        trace_scores = analyze_traces(episode_dir)

    log_scores = {}
    if (episode_dir / 'logs.jsonl').exists():
        log_scores = analyze_logs(episode_dir)

    # Combine scores with weights adjusted for availability
    final_scores = combine_scores(
        self_health_scores,
        temporal_scores,
        trace_scores,
        log_scores,
        availability_flags
    )
```

**Normalization:** If traces unavailable, redistribute trace weight to other signals.

---

### 8. Performance Optimization

**Goal:** Keep analysis under 10 seconds per episode.

**Expensive operations:**
1. **Trace parsing:** ~2-3 seconds (2K traces)
   - Optimization: Parse only fault window ± 30s
   - Skip traces outside analysis window

2. **Changepoint detection:** ~1-2 seconds (40K metrics)
   - Optimization: Run only on critical metrics (cpu, latency, errors)
   - Skip metrics like "request_count" that don't indicate health

3. **Graph traversal:** ~0.1 seconds (58 nodes, 91 edges)
   - Already fast, no optimization needed

**Target breakdown:**
- Metrics loading: 1s
- Temporal analysis: 2s
- Trace analysis: 3s
- Scoring & ranking: 1s
- **Total: 7 seconds** (within budget)

---

### 9. Testing Strategy

**Unit tests:**
```python
def test_temporal_causality():
    """Test that earlier degradation scores higher"""
    # Create synthetic scenario: Node A degrades at t=5, Node B at t=10
    # A calls B
    # Expected: A scores higher (caused B)

def test_self_time_calculation():
    """Test trace self-time extraction"""
    # Create trace with parent span 100ms, child span 70ms
    # Expected: self_time = 30ms

def test_graph_aware_temporal():
    """Test that unrelated early degradation doesn't score high"""
    # Node X degrades first but disconnected
    # Node Y degrades later but has downstream victims
    # Expected: Y scores higher
```

**Integration tests:**
```python
def test_full_pipeline():
    """Run on known episode and verify top-5"""
    result = analyze_episode("data/batch_run/data_20251212_135507/ep_0")
    assert result[0]['node'] == 'tenant_service'  # Ground truth
```

---

### 10. Debugging Tools

**Add verbose mode for development:**
```python
# In process_episode():
if verbose:
    print(f"  Temporal scores: {temporal_scores}")
    print(f"  Trace scores: {trace_scores}")
    print(f"  First impacts: {first_impacts}")
    print(f"  Downstream victims per node: {downstream_victims}")
```

**Add score breakdown to output:**
```json
{
  "node": "database",
  "final_score": 85.2,
  "score_breakdown": {
    "guilt_ratio": 50.0,
    "self_score": 20.0,
    "temporal": 10.0,
    "trace": 15.0,
    "dependency_health": 10.0
  }
}
```

**Helps answer:** "Why did algorithm pick X over Y?"

---

## Common Pitfalls to Avoid

### ❌ Pitfall 1: Using Mean Instead of p99
**Wrong:** `mean_latency = np.mean(latencies)`
**Right:** `p99_latency = np.percentile(latencies, 99)`

**Why:** Mean is skewed by outliers and doesn't reflect tail latency experienced by users.

### ❌ Pitfall 2: Ignoring Disconnected Nodes
**Wrong:** "Node X degraded first → Root cause"
**Right:** "Node X degraded first AND has downstream victims → Root cause"

**Why:** Unrelated nodes can degrade coincidentally.

### ❌ Pitfall 3: Trace Total Time Without Self Time
**Wrong:** Using only `span.duration` for scoring
**Right:** Calculate `self_time = duration - child_durations`

**Why:** A service can have high total time just from waiting on slow dependencies.

### ❌ Pitfall 4: Hard-Coding Thresholds
**Wrong:** `if cpu > 0.8: score = 10`
**Right:** Use effect size and changepoint detection

**Why:** Thresholds are environment-specific and noisy.

### ❌ Pitfall 5: Parsing Traces Without Grouping
**Wrong:** Process spans independently
**Right:** Group spans by trace_id, build parent-child trees

**Why:** Self-time calculation requires understanding span hierarchies.

---

## Success Metrics (Concrete)

**After Phase 1 (3 weeks):**
- [ ] Temporal causality: Can order A→B when A degraded 5s before B
- [ ] Trace analysis: Identifies DB as root cause when DB self-time is 10x higher
- [ ] No "no anomalies" failures (all 18 episodes analyzed)
- [ ] Top-5 accuracy: **≥ 60%** (11/18 correct)
- [ ] Execution time: **< 10s per episode**

**After Phase 2 (1-2 weeks):**
- [ ] Log correlation: Catches OOM/deadlock errors from logs
- [ ] Dependency health: Boosts leaf nodes with healthy dependencies
- [ ] Top-5 accuracy: **≥ 70%** (13/18 correct)
- [ ] Ready for production deployment

---

## Next Steps

1. **Start with temporal analysis** (biggest impact, ~1 week)
2. **Add trace analysis** (second biggest, ~1-2 weeks)
3. **Tune and evaluate** (critical before adding more features)
4. **Add logs/deps if needed** (if not at 70% after above)

**Don't add everything at once.** Implement incrementally, measure impact, then decide if more features are needed.
