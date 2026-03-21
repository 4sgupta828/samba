# Whitebox RCA Algorithm: Technical Deep Dive

## Table of Contents
1. [Overview & Philosophy](#overview--philosophy)
2. [Architecture](#architecture)
3. [Configuration System](#configuration-system)
4. [Detection Phases](#detection-phases)
5. [Scoring & Ranking](#scoring--ranking)
6. [Healthy Node Filtering](#healthy-node-filtering)
7. [Special Cases](#special-cases)
8. [Configuration & Tuning](#configuration--tuning)

---

## Overview & Philosophy

### Core Principle
**First-principles causal reasoning using internal symptoms (self-health) as primary evidence, external evidence (blame propagation) as confirmation.**

### Design Goals
1. **Statistical Rigor**: Use effect sizes, percentiles, and significance tests instead of magic numbers
2. **Configurability**: All thresholds centralized and overridable
3. **Robustness**: Handle edge cases (zero baselines, outliers, zombie pods) gracefully
4. **Multi-Signal Fusion**: Combine symptoms, temporal, traces, and topology evidence
5. **False Positive Reduction**: Aggressive filtering of healthy nodes with multi-layer safeguards

### Key Innovation: Multi-Level Analysis
```
Infrastructure Level (Network Partition)
    ↓
Service Level (Aggregated Metrics)
    ↓
Pod Level (Individual Instances)
```

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│ WhiteboxRCAEngine                                           │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 1.5: Temporal Causality (TemporalAnalyzer)    │ │
│  │ - Changepoint detection                              │ │
│  │ - Time-series correlation                            │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 1.6: Trace Analysis (TraceAnalyzer)           │ │
│  │ - Self-time vs total-time decomposition             │ │
│  │ - Victim detection                                    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 2: Network Partition Detection                │ │
│  │ - Async edge: Queue backlog explosion               │ │
│  │ - Sync edge: 100% error rate                        │ │
│  │ → Early return: global_network                       │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 2.5: Graph Propagation (CallerCalleeDisamb)   │ │
│  │ - Edge-level blame attribution                       │ │
│  │ - Traffic spike vs callee fault                      │ │
│  │ - Retry storm detection                              │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 3: Global Ranking with Scoring                │ │
│  │ - Integrated health (Service + Pod coverage-weighted)│ │
│  │ - Guilt ratio with hub bias correction              │ │
│  │ - Probabilistic blame discounting (proxy filtering) │ │
│  │ - Multi-signal fusion                                │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Phase 4: Healthy Node Filtering                     │ │
│  │ - 4-layer safeguard system                           │ │
│  │ - Aggressive noise reduction                         │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

Supporting Analyzers:
┌─────────────────────────────┐
│ SelfHealthAnalyzer          │
│ - Resource saturation       │
│ - Performance degradation   │
│ - Deadlock patterns (2 types)│
│ - Zombie pod detection      │
└─────────────────────────────┘
```

---

## Configuration System

### Design: `rca_config.py`

**Philosophy**: Make brittleness explicit, not hidden.

```python
@dataclass
class RCAThresholds:
    """
    All thresholds in one place with statistical justification.

    Design principles:
    1. Prefer percentiles over absolutes
    2. Use effect sizes (Cohen's d) for changes
    3. Use ratios for signal comparison
    4. Document rationale for each threshold
    """

    # === Network Partition Detection ===
    queue_growth_min_effect_size: float = 3.0
    # Rationale: Cohen's d >= 3.0 is "very large effect"
    # Means queue growth is 3+ standard deviations from baseline

    consumer_activity_percentile: float = 50.0
    # Rationale: Consumer must be above median baseline RPS
    # Avoids false positives on idle consumers

    # === Healthy Node Filtering ===
    pod_coverage_threshold: float = 0.5
    # Rationale: Majority rule - < 50% pods degraded = outliers
    # Can be reduced to 0.4 or 0.3 for smaller pod counts

    severity_comparison_percentile: float = 90.0
    # Rationale: Top 10% of all scores = statistically significant
    # Relative to current incident, not absolute

    temporal_to_symptom_ratio: float = 2.0
    # Rationale: Temporal signal 2x stronger than symptoms
    # Indicates strong causal timing correlation

    # === Zombie Pod Detection ===
    thread_saturation_threshold: float = 0.8
    # Rationale: >80% threads used = near-saturation
    # Industry standard for resource exhaustion warning
```

### Configuration Override

```python
# Default configuration
engine = WhiteboxRCAEngine(topology)

# Custom configuration
custom_config = {
    'pod_coverage_threshold': 0.4,  # More sensitive for small pod counts
    'severity_comparison_percentile': 85.0  # Top 15% instead of 10%
}
engine = WhiteboxRCAEngine(topology, threshold_config=custom_config)
```

### Dynamic Thresholds

```python
def get_dynamic_threshold(baseline: np.ndarray,
                         metric_name: str,
                         percentile: float = None) -> float:
    """
    Calculate threshold from baseline distribution.

    Adapts to:
    - High vs low traffic systems
    - Different metric scales
    - System-specific baselines
    """
    if percentile is None:
        # Choose appropriate percentile based on metric type
        if 'rps' in metric_name:
            percentile = 50  # Median for activity
        elif 'severity' in metric_name:
            percentile = 90  # Top 10% for significance

    return np.percentile(baseline, percentile)
```

### Statistical Methods

**Cohen's d (Effect Size)**
```python
def has_large_effect(baseline: np.ndarray,
                    current: np.ndarray,
                    metric_type: str = 'queue') -> bool:
    """
    Use effect size instead of arbitrary thresholds.

    Cohen's d interpretation:
    - 0.2: small effect
    - 0.5: medium effect
    - 0.8: large effect
    - 3.0: very large effect (our threshold for queues)
    """
    baseline_mean = np.mean(baseline)
    current_mean = np.mean(current)

    # Edge case: Zero-variance baseline
    if baseline_mean < 1.0 and np.std(baseline) < 1.0:
        if metric_type == 'queue':
            # Pragmatic: any backlog > 10 messages is significant
            return current_mean > 10.0

    # Standard Cohen's d calculation
    pooled_std = np.sqrt((np.std(baseline)**2 + np.std(current)**2) / 2)
    cohens_d = abs(current_mean - baseline_mean) / pooled_std

    return cohens_d >= 3.0  # Very large effect
```

---

## Detection Phases

### Phase 1: Self-Health Analysis

**Objective**: Identify nodes with internal degradation (root cause candidates).

#### Node-Level Symptoms

**Resource Saturation**
```python
# CPU, Memory, Thread Pool, DB Connections
for metric in ['cpu_usage', 'memory_usage', 'thread_pool_active']:
    stat = compare_distributions(baseline[metric], current[metric])

    if stat.significant and stat.effect_size > 0.5:
        # Check for limit saturation
        if metric == 'thread_pool_active':
            if current_max > limits['max_threads'] * 0.8:
                symptoms.append("Thread Pool Saturation")
                resource_score = 10.0  # Critical
```

**Performance Degradation**
```python
# Latency, Error Rate, Queue Depth
if avg_latency increased:
    if effect_size > 3.0:
        performance_score = 10.0
    else:
        performance_score = effect_size * 3.0
```

**Deadlock Patterns (2 Types)**

*Pattern A: Limp Mode*
```python
# High latency + LOW CPU = Process hung
if latency↑ AND cpu↓:
    symptoms.append("Potential Deadlock (High Latency / Low CPU)")
    score = 10.0
```

*Pattern B: Zombie Pod*
```python
# Thread saturation + Zero throughput = All threads blocked
if threads > 80% AND rps_current < 0.1 AND rps_baseline > 1.0:
    symptoms.append("Zombie Pod (Thread Deadlock)")
    score = 10.0
```

#### Pod-Level Integration

**Coverage-Weighted Scoring**
```python
def calculate_integrated_health_score():
    """
    Combine service-level and pod-level signals.

    Key insight: Partial pod degradation needs coverage weighting.
    """
    # Analyze each pod
    for pod in service_pods:
        pod_score = self_analyzer.analyze(pod)
        if pod_score > 2.0:
            degraded_pods.append(pod)

    # Coverage-weighted score
    coverage = len(degraded_pods) / len(total_pods)
    avg_severity = mean([p.score for p in degraded_pods])

    pod_score = avg_severity × coverage

    # Use whichever signal is stronger
    integrated_score = max(service_score, pod_score)

    return integrated_score, {
        'source': 'pod-level' if pod_score > service_score else 'service-level',
        'coverage': coverage,
        'pattern': classify_pattern(coverage)
    }
```

**Pattern Classification**
- Coverage >= 80%: "Service-wide degradation"
- Coverage >= 50%: "Partial degradation"
- Coverage >= 20%: "Multiple pods affected"
- Coverage < 20%: "Outlier pods"

#### Zombie Pod Capacity Loss Detection

```python
def detect_zombie_pods():
    """
    Count pods with throughput drop (zombie pattern).

    Adds capacity degradation bonus to ranking.
    """
    zombie_count = 0
    for pod in service_pods:
        base_rps = mean(baseline[pod]['inbound_rps'])
        curr_rps = mean(current[pod]['inbound_rps'])

        # Was active, now zero throughput
        if base_rps > 1.0 and curr_rps < 0.1:
            zombie_count += 1

    if zombie_count > 0:
        capacity_loss_pct = (zombie_count / total_pods) * 100
        capacity_bonus = min(20.0, zombie_count * 5.0)

        return capacity_bonus, {
            'zombie_pods': zombie_count,
            'capacity_loss_pct': capacity_loss_pct
        }
```

---

### Phase 2: Network Partition Detection

**Objective**: Detect infrastructure-level failures that appear as "no symptoms" at node level.

**Early Return Strategy**: If network partition detected, return `global_network` immediately with score=100.

#### Async Edge Detection (Queue-Consumer)

**Symptoms of Network Partition**:
1. Queue backlog explosion (producer still sending, consumer can't pull)
2. Consumer had baseline activity (not an idle system)
3. Large statistical effect size

```python
def detect_async_partition(queue, consumer):
    """
    Network partition blocks consumer from pulling from queue.
    """
    # 1. Check if consumer was active (percentile-based)
    baseline_rps = baseline[consumer]['inbound_rps']
    activity_threshold = percentile(baseline_rps, 50)  # Median
    was_active = mean(baseline_rps) > activity_threshold

    # 2. Check queue growth (effect size)
    baseline_depth = baseline[queue]['queue_depth']
    current_depth = current[queue]['queue_depth']

    # Handle zero-baseline case
    if mean(baseline_depth) < 1.0 and std(baseline_depth) < 1.0:
        # Use pragmatic threshold: > 10 messages = significant
        has_large_growth = mean(current_depth) > 10.0
    else:
        # Use Cohen's d
        has_large_growth = cohens_d(baseline_depth, current_depth) >= 3.0

    # 3. Verify current depth is significantly high
    baseline_p90 = percentile(baseline_depth, 90)
    is_significantly_high = mean(current_depth) > max(baseline_p90 * 2, 10)

    if was_active AND has_large_growth AND is_significantly_high:
        return NETWORK_PARTITION_DETECTED
```

**Why This Works**:
- Consumer can't have symptoms (it's not processing anything)
- Queue can't have symptoms (it's just storing messages)
- Only the EDGE behavior reveals the problem

#### Sync Edge Detection (HTTP/DB/Cache)

**Symptoms of Network Partition**:
1. 100% error rate (all requests failing)
2. RPS still exists (caller trying but failing)
3. Was healthy in baseline

```python
def detect_sync_partition(caller, callee):
    """
    Network partition causes all calls to fail.
    """
    dep_error_rate = current[caller]['dependency_error_rate']
    dep_rps = current[caller]['outbound_rps']

    # High error rate (>95%) but RPS exists
    if mean(dep_error_rate) > 0.95 and mean(dep_rps) > 0.1:
        # Confirm was healthy in baseline
        baseline_error = baseline[caller]['dependency_error_rate']
        if mean(baseline_error) < 0.1:
            return NETWORK_PARTITION_DETECTED
```

---

### Phase 2.5: Graph Propagation (Blame Attribution)

**Objective**: Determine who blames whom using caller-callee edge analysis.

#### Edge Analysis (CallerCalleeDisambiguator)

**Patterns Detected**:

1. **Traffic Spike (DDoS)**
```python
# RPS up significantly, latency follows
if rps↑ (effect_size > 2.0):
    return EdgeVerdict(
        blames_caller=True,
        reason="Traffic Spike",
        confidence=0.9
    )
```

2. **Callee Fault**
```python
# Latency/errors up, RPS stable/down
if (latency↑ OR errors↑) AND rps_stable:
    return EdgeVerdict(
        blames_callee=True,
        reason="Callee Degradation",
        confidence=0.95
    )
```

3. **Retry Storm**
```python
# RPS up AND errors up
if rps↑ AND errors↑:
    return EdgeVerdict(
        blames_callee=True,  # Callee failed first
        reason="Retry Storm",
        confidence=0.8
    )
```

#### Guilt Ratio (Hub Bias Correction)

**Problem**: High-fan-in nodes (e.g., databases) get blamed more just because they have more callers.

**Solution**: Normalize by caller count.

```python
def calculate_guilt_ratio(node):
    """
    Probability node is faulty based on callers.

    P_in = (Sum of caller blame weights) / (Number of callers)
    """
    callers = predecessors(node)
    votes = [v for v in incoming_votes if v.target == node]
    vote_sum = sum(v.weight for v in votes)

    if len(callers) > 0:
        guilt_ratio = vote_sum / len(callers)

        # Dampen for small N (Law of Large Numbers)
        if len(callers) < 5:
            guilt_ratio *= 0.8
    else:
        guilt_ratio = 0.0

    return guilt_ratio
```

#### Probabilistic Blame Discounting (Proxy/Middleman Filtering)

**Problem**: Middleman services blame downstream dependencies but aren't the root cause.

**Solution**: Discount blame if node is also blaming others.

```python
def calculate_adjusted_guilt(node):
    """
    Net fault probability: P_root ≈ P_in × (1 - P_out)

    If I'm blaming downstream with high confidence,
    I'm likely just a conduit, not the root cause.
    """
    # P_in: Guilt from incoming blame
    guilt_ratio = calculate_guilt_ratio(node)

    # P_out: Max confidence of my outgoing blame
    my_outgoing = outgoing_blame[node]
    max_outgoing_conf = max(my_outgoing) if my_outgoing else 0.0

    # Discount factor (max 80% discount for shared faults)
    discount_factor = 1.0 - (max_outgoing_conf * 0.8)

    # Adjusted guilt
    adjusted_guilt = guilt_ratio * discount_factor

    return adjusted_guilt, discount_factor
```

---

## Scoring & Ranking

### Final Score Formula

**First Principles Design**: Internal evidence PRIMARY, external evidence SECONDARY.

```python
final_score = base_score + confirmation_score

# Base Score (0-100 points): Internal Evidence
base_score = integrated_score × 10.0

# Bonuses
if is_trace_authoritative:
    base_score += 50.0  # Strong confirmation

# Penalties
if is_victim (high total_time, low self_time):
    base_score *= 0.1  # 90% penalty

if is_healthy (filtered by safeguards):
    base_score *= 0.05  # 95% penalty

# Confirmation Score (0-40 points): External Evidence
confirmation_score = (
    (adjusted_guilt × 20.0) +        # 0-20: Adjusted guilt (with proxy discount)
    (temporal_score × 2.0) +          # 0-40: Temporal causality
    impact_bonus +                    # 0-3: Log of traffic volume
    capacity_degradation_bonus        # 0-20: Zombie pod capacity loss
)
```

### Component Breakdown

**Integrated Score** (0-10):
- Service-level self-health OR
- Pod-level coverage-weighted score
- Whichever is stronger

**Guilt Ratio** (0-1):
- Normalized by caller count (hub bias correction)
- Dampened for small N
- Discounted by outgoing blame (proxy filtering)

**Temporal Score** (0-20):
- Changepoint detection
- Timing correlation with fault injection
- Higher = stronger causal evidence

**Trace Score** (0-∞):
- Self-time vs total-time decomposition
- Authoritative flag for high confidence
- Used for victim detection

**Impact Bonus** (0-3):
- Log₁₀(traffic_volume)
- Prioritizes high-impact nodes

**Capacity Degradation Bonus** (0-20):
- Zombie pod count × 5 points
- Indicates service capacity loss

---

## Healthy Node Filtering

### Objective
Eliminate false positives: nodes with outlier pod symptoms but no real service impact.

### 4-Layer Safeguard System

**Only filter if ALL conditions met:**

```python
if pod_only_detection AND coverage < 50% AND no_service_symptoms AND no_external_blame:
    # Apply 4 safeguards - filter only if ALL fail

    # SAFEGUARD 1: Severe Pod Degradation
    all_scores = [self_scores[n] for n in topology.nodes]
    severity_threshold = percentile(all_scores, 90)  # Top 10%

    if max_severity >= severity_threshold AND max_severity > 5.0:
        DONT_FILTER  # Severe pod is significant

    # SAFEGUARD 2: Temporal Correlation
    elif temporal_score > 0 AND integrated_score > 0:
        temporal_ratio = temporal_score / integrated_score
        if temporal_ratio > 2.0:  # Temporal 2x stronger
            DONT_FILTER  # Strong timing correlation

    # SAFEGUARD 3: Trace Analysis
    elif is_trace_authoritative OR (trace_score / integrated_score > 3.0):
        DONT_FILTER  # Traces confirm involvement

    # SAFEGUARD 4: Capacity Loss
    elif zombie_pods > 0:
        DONT_FILTER  # Capacity degradation detected

    else:
        FILTER_AS_HEALTHY  # All safeguards passed
```

### Rationale

**Why 4 layers?**

Each safeguard catches a different failure mode:
1. **Severity**: Catches extremely degraded pods even if isolated
2. **Temporal**: Catches pods that degrade at fault injection time
3. **Trace**: Catches pods showing latency in distributed traces
4. **Capacity**: Catches zombie pods reducing effective capacity

**Conservative by design**: Only filter when we're very confident it's noise.

---

## Special Cases

### 1. Zero-Variance Baselines

**Problem**: Can't use Cohen's d when baseline std = 0 (e.g., queue always empty).

**Solution**: Fallback to pragmatic absolute thresholds.

```python
if baseline_mean < 1.0 and baseline_std < 1.0:
    if metric_type == 'queue':
        return current_mean > 10.0  # Any backlog > 10 msgs
    else:
        return abs(current_mean - baseline_mean) > 1.0
```

### 2. Zombie Pods (Deadlocked Threads)

**Problem**: Zombie pods don't serve traffic, so they don't appear in service metrics.

**Detection**: Thread saturation + zero throughput + was previously active.

```python
if threads > 80% AND rps_current < 0.1 AND rps_baseline > 1.0:
    symptoms.append("Zombie Pod")
    score = 10.0
```

**Service-Level**: Count zombies and add capacity loss bonus.

### 3. Network Partitions

**Problem**: Neither endpoint has symptoms (consumer can't process, queue just stores).

**Detection**: Edge-level behavior (queue explosion + consumer was active).

**Result**: Return `global_network` immediately with score=100 (authoritative).

### 4. Low Pod Coverage but True Root Cause

**Problem**: 1/4 pods degraded with no service symptoms - could be root cause OR noise.

**Solution**: 4-layer safeguards check severity, temporal, traces, and capacity loss before filtering.

---

## Configuration & Tuning

### Common Tuning Scenarios

#### Small Pod Counts (2-3 pods)

**Problem**: 1/2 pods = 50% coverage, might be filtered.

**Solution**: Lower coverage threshold.

```python
config = {
    'pod_coverage_threshold': 0.3,  # 30% instead of 50%
}
```

#### High-Traffic Systems

**Problem**: Absolute thresholds (like 10 messages) might be too low.

**Solution**: Already handled via percentile-based thresholds. No tuning needed.

#### Low-Traffic Systems

**Problem**: Percentile-based thresholds might be too sensitive.

**Solution**: Increase min_absolute_severity.

```python
config = {
    'min_absolute_severity': 10.0,  # Higher floor
}
```

#### Noisy Environments

**Problem**: Too many false positives.

**Solution**: Increase effect size requirements.

```python
config = {
    'queue_growth_min_effect_size': 5.0,  # Even larger effect required
    'severity_comparison_percentile': 95.0,  # Top 5% only
}
```

### Observability

**Diagnostic Information** (in rankings output):
```json
{
  "node": "service_name",
  "score": 45.2,
  "integrated_score": 3.5,
  "guilt_adjusted": 0.76,
  "discount_factor": 0.8,
  "is_healthy": false,
  "health_filter_reason": null,
  "health_metadata": {
    "source": "pod-level",
    "coverage": 0.75,
    "zombie_pods": 2,
    "capacity_loss_pct": 50.0
  },
  "temporal_score": 8.5,
  "trace_score": 12.0,
  "symptoms": ["Thread Pool Saturation", "Latency increased"]
}
```

---

## Algorithm Complexity

### Time Complexity

- **Phase 1 (Self-Health)**: O(N) where N = number of nodes
- **Phase 2 (Network Partition)**: O(E) where E = number of edges
- **Phase 2.5 (Graph Propagation)**: O(E)
- **Phase 3 (Ranking)**: O(N log N) for sorting
- **Phase 4 (Filtering)**: O(N)

**Total**: O(N log N + E)

### Space Complexity

- Metrics storage: O(N × M × T) where M = metrics per node, T = time samples
- Rankings: O(N)
- Edge verdicts: O(E)

**Total**: O(N × M × T + E)

**Practical**: Handles topologies with 100s of nodes and 1000s of edges efficiently.

---

## References

**Statistical Methods**:
- Cohen's d: https://en.wikipedia.org/wiki/Effect_size#Cohen's_d
- Percentile-based thresholds: Robust statistics literature

**Graph Analysis**:
- PageRank-inspired guilt propagation
- Hub bias correction: Similar to TF-IDF normalization

**Domain Knowledge**:
- Thread deadlock patterns: Standard OS diagnostics
- Queue backlog explosion: Common network partition symptom
- Capacity degradation: Kubernetes pod health concepts

---

## Summary

**Key Innovations**:

1. **Multi-Level Detection**: Infrastructure → Service → Pod
2. **Statistical Rigor**: Effect sizes, percentiles, not magic numbers
3. **Configuration System**: All thresholds explicit and overridable
4. **4-Layer Safeguards**: Aggressive noise reduction without missing true positives
5. **Special Case Handling**: Network partitions, zombie pods, zero baselines
6. **Probabilistic Discounting**: Filters middlemen/proxies automatically

**Result**: Robust, configurable, statistically-grounded RCA that generalizes across different systems and fault types.
