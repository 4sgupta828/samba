# RCA Scores Reference Guide

## Overview

This document explains all scores in the Whitebox RCA output. Scores are used to rank nodes by likelihood of being the root cause.

---

## Primary Ranking Score

### `score` (Final Score)
**Range:** 0 to ~160 (typically 0-100)
**Formula:** `base_score + confirmation_score`

The final ranking score combining internal evidence (symptoms) and external evidence (blame, timing, traces).

**Interpretation:**
- **0-20**: Unlikely root cause, minimal symptoms
- **20-50**: Possible root cause, some evidence
- **50-80**: Strong candidate, clear symptoms
- **80-100**: Very strong candidate, multiple signals
- **100+**: Network partition or authoritative trace evidence

**Example:**
```json
{
  "node": "payment_service",
  "score": 67.5
}
```

---

## Internal Evidence Scores

These scores measure node's own degradation (self-health).

### `integrated_score`
**Range:** 0.0 to 10.0
**Formula:** `max(service_self_score, pod_score × coverage)`

Combined service-level and pod-level health score. Uses whichever signal is stronger.

**Components:**
- **Service-level**: Aggregated metrics across all pods
- **Pod-level**: Coverage-weighted average of degraded pods

**Interpretation:**
- **0.0-2.0**: Minimal degradation
- **2.0-5.0**: Moderate degradation
- **5.0-8.0**: Significant degradation
- **8.0-10.0**: Severe degradation (saturation, deadlock)

**Example:**
```json
{
  "integrated_score": 7.2,
  "self_score": 3.5,
  "health_metadata": {
    "source": "pod-level",
    "pod_score": 9.0,
    "coverage": 0.8
  }
}
```
Pod-level score (9.0 × 0.8 = 7.2) is stronger than service-level (3.5).

---

### `self_score` (Service Self-Score)
**Range:** 0.0 to 10.0
**Source:** `SelfHealthAnalyzer` on service-level aggregated metrics

Degradation score from service-level metrics only (ignoring pod-level).

**Detection Categories:**

1. **Resource Saturation** (0-10 points)
   - CPU usage increased
   - Memory usage increased
   - Thread pool near limit (>90%)
   - Score = `effect_size × 2.5`, capped at 10.0

2. **Performance Degradation** (0-10 points)
   - Latency increased (effect_size > 1.0)
   - Error rate increased (>5%)
   - Queue depth/lag increased
   - Score = `effect_size × 3.0` for latency

3. **Deadlock Patterns** (10 points)
   - **Limp mode**: High latency + low CPU
   - **Zombie pod**: Thread saturation + zero throughput

**Example:**
```json
{
  "self_score": 8.5,
  "symptoms": [
    "Thread Pool Saturation (49/50)",
    "Latency increased (d=3.2)"
  ]
}
```

---

### `health_metadata`
**Type:** Object
**Purpose:** Detailed health breakdown

**Fields:**

#### `source`
**Values:** `"service-level"` | `"pod-level"`
Which signal (service or pod) was stronger.

#### `pod_score`
**Range:** 0.0 to 10.0
Average severity of degraded pods (before coverage weighting).

#### `coverage`
**Range:** 0.0 to 1.0
Fraction of pods that are degraded.

**Formula:** `degraded_count / total_count`

**Interpretation:**
- **0.0-0.2**: Outlier pods (1-2 pods)
- **0.2-0.5**: Multiple pods affected
- **0.5-0.8**: Partial degradation (majority)
- **0.8-1.0**: Service-wide degradation (all pods)

#### `pattern`
**Values:**
- `"Service-wide degradation"` (≥80%)
- `"Partial degradation"` (≥50%)
- `"Multiple pods affected"` (≥20%)
- `"Outlier pods detected"` (<20%)

#### `degraded_count`
**Type:** Integer
Number of degraded pods (self_score > 2.0).

#### `total_count`
**Type:** Integer
Total number of pods for this service.

#### `max_severity`
**Range:** 0.0 to 10.0
Highest self_score among all pods.

**Purpose:** Used in healthy node filtering. Even if coverage is low, a very high max_severity (>40 in final score) prevents filtering.

#### `zombie_pods` (optional)
**Type:** Integer
Number of pods with zombie pattern (was active, now zero throughput).

#### `capacity_loss_pct` (optional)
**Range:** 0.0 to 100.0
Percentage of capacity lost due to zombie pods.

**Formula:** `(zombie_pods / total_count) × 100`

**Example:**
```json
{
  "health_metadata": {
    "source": "pod-level",
    "pod_score": 8.5,
    "coverage": 0.75,
    "pattern": "Partial degradation",
    "degraded_count": 3,
    "total_count": 4,
    "max_severity": 9.2,
    "zombie_pods": 2,
    "capacity_loss_pct": 50.0
  }
}
```

---

## External Evidence Scores

These scores measure evidence from other nodes and external signals.

### `guilt_raw` (Raw Guilt Ratio)
**Range:** 0.0 to ~10.0 (typically 0-2.0)
**Formula:** `sum(incoming_blame_weights) / caller_count`

Average blame weight from callers, normalized by number of callers (hub bias correction).

**Purpose:**
- Prevents high-fan-in nodes (databases, caches) from being over-blamed
- Normalizes by caller count using Law of Large Numbers
- Dampened by 0.8 if caller_count < 5

**Interpretation:**
- **0.0**: No callers blaming this node
- **0.1-0.5**: Weak blame from some callers
- **0.5-1.0**: Strong blame from most callers
- **1.0+**: Very strong blame from all callers

**Example:**
```json
{
  "guilt_raw": 0.85,
  "blamed_by": ["api_gateway", "user_service", "order_service"]
}
```
3 callers blaming with average weight of 0.85.

---

### `guilt_adjusted` (Adjusted Guilt)
**Range:** 0.0 to guilt_raw
**Formula:** `guilt_raw × discount_factor`

Guilt after probabilistic blame discounting (filters middlemen/proxies).

**Key Insight:** If a node is blaming downstream dependencies with high confidence, it's likely a conduit (proxy), not the root cause.

**Formula Components:**
- `P_in` = guilt_raw (probability node is faulty based on callers)
- `P_out` = max_outgoing_conf (probability node is blaming others)
- `discount_factor` = 1.0 - (P_out × 0.8)
- `guilt_adjusted` = P_in × (1 - P_out)

**Interpretation:**
- **guilt_adjusted ≈ guilt_raw**: Node not blaming others (potential root cause)
- **guilt_adjusted << guilt_raw**: Node blaming others heavily (likely proxy)

**Example:**
```json
{
  "guilt_raw": 0.90,
  "guilt_adjusted": 0.18,
  "discount_factor": 0.20,
  "max_outgoing_conf": 0.95
}
```
Node is being blamed heavily (0.90) BUT is also blaming downstream (0.95), so adjusted guilt drops to 0.18 → likely a proxy, not root cause.

---

### `discount_factor`
**Range:** 0.0 to 1.0
**Formula:** `1.0 - (max_outgoing_conf × 0.8)`

Probabilistic discount applied to guilt based on outgoing blame.

**Interpretation:**
- **1.0**: Not blaming anyone (no discount)
- **0.8-1.0**: Weak outgoing blame (small discount)
- **0.5-0.8**: Moderate outgoing blame (medium discount)
- **0.0-0.5**: Strong outgoing blame (large discount, likely proxy)

---

### `max_outgoing_conf`
**Range:** 0.0 to 1.0
**Source:** Maximum confidence among all outgoing edge verdicts

Highest confidence with which this node is blaming a downstream dependency.

**Interpretation:**
- **0.0**: Not blaming any downstream node
- **0.1-0.5**: Weak blame on dependencies
- **0.5-0.8**: Moderate blame (e.g., retry storm detection)
- **0.8-0.95**: Strong blame (e.g., callee degradation detected)
- **0.95**: Very high confidence blame

**Example:**
```json
{
  "node": "api_gateway",
  "max_outgoing_conf": 0.95,
  "blamed_by": ["load_balancer"],
  "reason": "api_gateway blames user_db with 0.95 confidence (Callee Degradation)"
}
```

---

### `temporal_score`
**Range:** 0.0 to ~20.0 (typically 0-10)
**Source:** `TemporalAnalyzer`

Score based on timing correlation between node degradation and fault injection.

**Detection Method:**
1. Changepoint detection on node metrics
2. Compare changepoint time to fault_start_time
3. Score based on temporal proximity and signal strength

**Interpretation:**
- **0.0**: No temporal correlation
- **1.0-3.0**: Weak timing correlation
- **3.0-7.0**: Moderate timing correlation
- **7.0-15.0**: Strong timing correlation (degradation coincides with fault)
- **15.0+**: Very strong temporal evidence

**Purpose:**
- Distinguishes root cause from victims
- Root cause degrades first (near fault injection time)
- Victims degrade later (downstream propagation)

**Example:**
```json
{
  "temporal_score": 12.5,
  "temporal_info": {
    "changepoint_time": 120.3,
    "fault_start_time": 120.0,
    "time_delta": 0.3
  }
}
```
Node degraded 0.3 seconds after fault injection → strong temporal evidence.

---

### `trace_score`
**Range:** 0.0 to ∞ (typically 0-50)
**Source:** `TraceAnalyzer`

Score based on distributed trace analysis (self-time vs total-time decomposition).

**Detection Method:**
1. Aggregate trace spans by service
2. Compare self-time (service's own processing) vs total-time (including dependencies)
3. High self-time degradation = root cause
4. High total-time but low self-time = victim

**Interpretation:**
- **0.0**: No trace data or no degradation
- **1.0-5.0**: Minor self-time increase
- **5.0-15.0**: Moderate self-time increase
- **15.0-30.0**: Significant self-time increase (strong root cause evidence)
- **30.0+**: Severe self-time increase

**Purpose:**
- Victim detection: `total_time↑ but self_time↓` → waiting on dependencies
- Root cause: `self_time↑` → node's own processing is slow

**Example:**
```json
{
  "trace_score": 18.5,
  "is_trace_authoritative": true,
  "trace_info": {
    "self_time_degradation": 4.2,
    "total_time_degradation": 5.1,
    "is_authoritative": true
  }
}
```
Self-time increased 4.2x → strong evidence this service is the root cause.

---

### `is_trace_authoritative`
**Type:** Boolean
**Purpose:** Indicates high-confidence trace analysis

**Criteria:**
- Sufficient trace sample count (>50 spans)
- High statistical significance
- Clear self-time vs total-time separation

**Impact:**
- If true: +50 points to base_score
- Strong confirmation signal

---

## Derived Scores (Internal Calculations)

These scores are calculated internally but not directly shown in output.

### `base_score`
**Range:** 0.0 to ~110
**Formula:** `integrated_score × 10.0 + bonuses - penalties`

Internal evidence score (node's own symptoms).

**Components:**
```python
base_score = integrated_score × 10.0

# Bonuses
if is_trace_authoritative:
    base_score += 50.0

# Penalties
if is_victim:
    base_score *= 0.1  # 90% penalty

if is_healthy:
    base_score *= 0.05  # 95% penalty
```

---

### `confirmation_score`
**Range:** 0.0 to ~60
**Formula:** `(guilt_adjusted × 20) + (temporal_score × 2) + impact_bonus + capacity_bonus`

External evidence score (blame, timing, traces).

**Components:**
- **Adjusted Guilt**: 0-20 points (proxy-discounted blame)
- **Temporal**: 0-40 points (timing correlation)
- **Impact**: 0-3 points (log₁₀ of traffic volume)
- **Capacity Loss**: 0-20 points (zombie pod bonus)

---

### `impact_bonus`
**Range:** 0.0 to ~3.0
**Formula:** `log₁₀(max(1.0, traffic_volume))`

Prioritizes high-traffic nodes.

**Purpose:**
- Tie-breaker between nodes with similar scores
- Root cause in high-traffic service has more impact

**Example:**
- 1 RPS: log₁₀(1) = 0.0
- 10 RPS: log₁₀(10) = 1.0
- 100 RPS: log₁₀(100) = 2.0
- 1000 RPS: log₁₀(1000) = 3.0

---

### `capacity_degradation_bonus`
**Range:** 0.0 to 20.0
**Formula:** `min(20.0, zombie_pods × 5.0)`

Bonus for capacity loss due to zombie pods.

**Purpose:**
- Catches services with partial pod failures
- Even if service-level metrics look healthy, capacity loss is significant

**Example:**
- 1 zombie pod: 5.0 points
- 2 zombie pods: 10.0 points
- 4 zombie pods: 20.0 points (capped)

---

## Filtering Flags

### `is_healthy`
**Type:** Boolean
**Values:** `true` | `false`

Indicates if node was flagged as healthy and penalized 95%.

**Criteria (ALL must be true to filter):**
1. Pod-level only detection (no service symptoms)
2. Low coverage (<50% pods degraded)
3. No service-level symptoms
4. No external blame (<10% guilt ratio)
5. Fails all 4 safeguards:
   - Max severity < 90th percentile
   - Temporal ratio < 2.0
   - Trace ratio < 3.0 or not authoritative
   - No zombie pods

**Example:**
```json
{
  "is_healthy": true,
  "health_filter_reason": "Outlier pod detection (1 pod(s), 25% coverage) with no service-level symptoms"
}
```

---

### `health_filter_reason`
**Type:** String | null
**Values:** Explanation string if filtered, null otherwise

Human-readable reason for why node was filtered as healthy.

---

## Special Cases

### Network Partition Score
**Value:** 100.0
**Node:** `"global_network"`

When network partition is detected, returns immediately with:
```json
{
  "node": "global_network",
  "score": 100.0,
  "integrated_score": 0.0,
  "symptoms": ["Network partition detected between components"],
  "network_partitions": [
    {
      "source": "billing_queue",
      "target": "reporting_service",
      "reason": "Blocked async consumption: queue backlog exploded..."
    }
  ]
}
```

---

## Score Interpretation Guide

### By Final Score Range

| Score | Interpretation | Action |
|-------|---------------|--------|
| 100 | Network partition (authoritative) | Investigate network infrastructure |
| 80-100 | Very strong root cause candidate | High confidence - investigate immediately |
| 60-80 | Strong root cause candidate | Good candidate - investigate |
| 40-60 | Moderate evidence | Possible root cause - investigate if top-3 |
| 20-40 | Weak evidence | Unlikely unless no better candidates |
| 0-20 | Minimal evidence | Very unlikely root cause |

### By Score Components

**High Internal, Low External:**
```json
{"score": 65, "integrated_score": 6.5, "guilt_adjusted": 0.0}
```
→ Node is degraded but not being blamed. Possible root cause or leaf node issue.

**High External, Low Internal:**
```json
{"score": 55, "integrated_score": 1.0, "guilt_adjusted": 0.9}
```
→ Heavily blamed but not degraded internally. Likely false positive or victim.

**High Both:**
```json
{"score": 95, "integrated_score": 8.5, "guilt_adjusted": 0.8}
```
→ Strong root cause candidate with multiple signals aligned.

**High Temporal:**
```json
{"score": 78, "integrated_score": 5.0, "temporal_score": 15.0}
```
→ Degradation timing matches fault injection. Strong temporal causality.

**Authoritative Trace:**
```json
{"score": 88, "integrated_score": 3.5, "trace_score": 20.0, "is_trace_authoritative": true}
```
→ Traces definitively show self-time degradation. High confidence root cause.

---

## Output Example with All Scores

```json
{
  "node": "payment_service",
  "score": 78.5,
  "integrated_score": 6.8,
  "guilt_raw": 0.75,
  "guilt_adjusted": 0.60,
  "discount_factor": 0.80,
  "max_outgoing_conf": 0.25,
  "self_score": 3.2,
  "temporal_score": 8.5,
  "trace_score": 12.0,
  "symptoms": [
    "Thread Pool Saturation (48/50)",
    "Latency increased (d=2.8)",
    "Error rate increased (12.5%)"
  ],
  "blamed_by": ["api_gateway", "order_service"],
  "health_metadata": {
    "source": "pod-level",
    "pod_score": 8.5,
    "coverage": 0.80,
    "pattern": "Partial degradation",
    "degraded_count": 4,
    "total_count": 5,
    "max_severity": 9.1,
    "zombie_pods": 0,
    "capacity_loss_pct": 0.0
  },
  "temporal_info": {
    "changepoint_time": 120.5,
    "fault_start_time": 120.0,
    "time_delta": 0.5
  },
  "trace_info": {
    "self_time_degradation": 3.2,
    "total_time_degradation": 4.1,
    "is_authoritative": true
  },
  "is_trace_authoritative": true,
  "is_healthy": false,
  "health_filter_reason": null,
  "story": [
    "🔴 ROOT CAUSE: payment_service",
    "   Internal Symptoms: Thread Pool Saturation, Latency increased",
    "   External Evidence: Blamed by 2 callers",
    "   Temporal: Degraded 0.5s after fault injection",
    "   Traces: Self-time increased 3.2x (authoritative)"
  ]
}
```

---

## Summary

### Key Scores Priority

1. **score** - Main ranking score (use this for top-N selection)
2. **integrated_score** - Internal symptoms (primary evidence)
3. **guilt_adjusted** - External blame (confirmation)
4. **temporal_score** - Timing evidence (causality)
5. **trace_score** - Distributed trace evidence (victim detection)

### Decision Tree

```
Is score = 100?
  └─ YES → Network partition (global_network)
  └─ NO  → Continue

Is integrated_score > 5.0?
  └─ YES → Strong internal symptoms
           └─ Check guilt_adjusted > 0.5? → High confidence root cause
           └─ Check temporal_score > 5.0? → Timing confirms
  └─ NO  → Check trace evidence

Is trace_score > 15.0 AND is_trace_authoritative?
  └─ YES → Trace evidence strong
  └─ NO  → Lower confidence

Is is_healthy = true?
  └─ YES → Likely false positive (filtered)
  └─ NO  → Valid candidate
```

### Confidence Level by Score Combination

**Very High Confidence (>90%):**
- integrated_score > 7.0 AND guilt_adjusted > 0.7
- is_trace_authoritative = true AND trace_score > 20
- temporal_score > 12 AND integrated_score > 5.0

**High Confidence (70-90%):**
- integrated_score > 5.0 AND guilt_adjusted > 0.5
- trace_score > 10 AND temporal_score > 5
- score > 70

**Moderate Confidence (40-70%):**
- integrated_score > 3.0 OR guilt_adjusted > 0.4
- score 40-70

**Low Confidence (<40%):**
- integrated_score < 3.0 AND guilt_adjusted < 0.3
- score < 40
- is_healthy = true

---

## Related Documentation

- **Algorithm Details**: See `WHITEBOX_RCA_ALGORITHM.md`
- **Configuration**: See `rca_config.py`
- **Threshold Tuning**: See `WHITEBOX_RCA_ALGORITHM.md` → Configuration & Tuning
