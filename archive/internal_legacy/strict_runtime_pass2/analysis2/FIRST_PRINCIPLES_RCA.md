# First Principles Approach to RCA

## The Core Problem

**Goal**: Given an ongoing incident, identify which node's degradation is *causing* the system-wide symptoms.

**Challenge**: Distinguish root causes from victims in a distributed system where failures cascade.

## First Principles Framework

### 1. What is a Root Cause?

A root cause is a node whose degradation **causes** other nodes to degrade. Key properties:

- **Intrinsic degradation**: The node has an internal problem (not just affected by others)
- **Causal explanation**: Its degradation explains downstream impact patterns
- **Temporal primacy**: Degrades first (or early) among candidates
- **Primary symptoms**: Shows causes (resource exhaustion, bugs) not just effects

### 2. What is a Victim?

A victim is a node that degrades **because of** upstream problems:

- **Secondary symptoms**: Latency, errors without intrinsic resource issues
- **No causal explanation**: Degradation doesn't explain broader system behavior
- **Temporal lag**: Degrades later as effects cascade
- **Cascading effects**: Problems emerge from dependency failures

### 3. The Pod Coverage Problem

**Question**: When 1 pod out of 6 is degraded with no service-level symptoms, what does this tell us?

**Current behavior**: Treated as "high confidence" evidence of root cause

**First principles analysis**:
- **Service-wide degradation (≥80% pods)**: Strong signal - systemic issue in the service
- **Majority degradation (50-80% pods)**: Medium signal - could be service issue or major upstream problem
- **Outlier pods (<30% pods)**: Weak signal - more likely cascading effect or infrastructure issue

**Why outlier pods are weak evidence**:

1. **True root causes show service-wide impact**: If the service code has a bug/leak, all instances should be affected
2. **Random victims in cascades**: When upstream service is slow, random downstream pods get affected
3. **Infrastructure noise**: Node issues, noisy neighbors affect individual pods
4. **No service-level confirmation**: Without aggregate metrics degradation, can't confirm intrinsic problem

**Conclusion**: Outlier pod degradation without service-level symptoms should NOT be considered evidence of intrinsic degradation.

### 4. The Time Window Problem

**Question**: What time periods should we compare?

**Current behavior**: Aggregates entire episode (including recovery) into single analysis

**Why this is wrong**:
```
baseline_data = all data from 0-60s
current_data = all data from 60-300s  // Includes fault + recovery + post-recovery!
```

**Problems**:
1. **Mixing system states**: Fault effects + recovery artifacts + healthy state
2. **Recovery artifacts**: Pods recovering at different rates → artificial outliers
3. **Not how RCA works in production**: RCA runs at a specific moment, not over an episode

**First principles**: RCA is a **point-in-time diagnosis**, not whole-episode summarization.

**Correct approach**:
```
Given: analysis_time (when RCA is running, during incident)

baseline_window = [auto-detected healthy period before incident]
current_window = [recent metrics around analysis_time]
```

### 5. The Baseline Detection Problem

**Question**: How do we know what "healthy" looks like?

**Current behavior**: Hardcoded baseline period (0 to fault_start)

**Problems**:
1. Assumes system is healthy at episode start (may not be true)
2. Uses arbitrary time bounds
3. Doesn't verify baseline is actually healthy

**First principles**: Baseline must be **confirmed healthy** with strict criteria:

**Strict health criteria**:
- No intrinsic degradation (all nodes have low health scores)
- No symptomatic effects (no errors, latency spikes, resource exhaustion)
- Stable state (not in transition)
- Sufficient duration (enough data to establish "normal")

**Auto-detection algorithm**:
1. Scan backward from analysis_time
2. Compute health scores for sliding windows
3. Find longest contiguous healthy period
4. Validate it meets minimum duration requirements
5. Use as baseline

## The Complete Solution

### Architecture: Filter → Rank → Report

```python
# Phase 1: FILTER for intrinsic degradation
candidates = []
for node in all_nodes:
    intrinsic_evidence = assess_intrinsic_degradation(node)

    if intrinsic_evidence.strength == 'strong':
        # Service-wide degradation (≥80% pods) OR clear service-level symptoms
        candidates.append(node)
    elif intrinsic_evidence.strength == 'weak':
        # Outlier pods (<30%) with no service-level symptoms
        # REJECT - likely cascading victim
        continue

# Phase 2: RANK by causal explanation
for candidate in candidates:
    candidate.score = (
        physics_coverage * 60 +      # How much does it explain? (MOST IMPORTANT)
        symptom_type_bonus * 40 +    # Primary vs secondary symptoms
        temporal_bonus * 15          # First mover advantage (tie-breaker)
    )

candidates.sort(by=score, descending=True)

# Phase 3: REPORT with confidence
if not candidates:
    report("Unable to identify root cause - insufficient evidence")
elif candidates[0].score > candidates[1].score * 1.5:
    report(f"High confidence: {candidates[0]}")
else:
    report(f"Multiple candidates: {candidates[:3]} - need more investigation")
```

### Key Changes from Current Implementation

**1. Intrinsic Degradation Filter**

```python
# OLD: Any pod degradation is evidence
if integrated_score > 0:
    confidence = 'high'
    score = integrated_score * 5.0

# NEW: Coverage-based filtering
coverage = degraded_pods / total_pods

if coverage >= 0.8:
    # Service-wide - strong intrinsic evidence
    intrinsic_strength = 'strong'
    confidence_multiplier = 1.0
elif coverage >= 0.5:
    # Majority - medium intrinsic evidence
    intrinsic_strength = 'medium'
    confidence_multiplier = 0.6
elif coverage >= 0.3:
    # Multiple pods - weak intrinsic evidence
    intrinsic_strength = 'weak'
    confidence_multiplier = 0.3
else:
    # Outlier pods - NOT intrinsic degradation
    intrinsic_strength = 'none'
    # Filter out - don't include in candidates
    continue
```

**2. Time Window Selection**

```python
# OLD: Aggregate entire episode
base_df = metrics[metrics['time'] < fault_start]          # 0-60s
curr_df = metrics[metrics['time'] >= fault_start]         # 60-300s (includes recovery!)

# NEW: Point-in-time analysis
selector = TimeWindowSelector(metrics_df, episode_start, episode_end)
analysis_time = selector.suggest_analysis_time(fault_start)  # e.g., 150s
windows = selector.select_windows(analysis_time, auto_detect_baseline=True)

base_df = metrics[(time >= windows.baseline.start) & (time <= windows.baseline.end)]  # e.g., 20-50s
curr_df = metrics[(time >= windows.current.start) & (time <= windows.current.end)]    # e.g., 130-150s
```

**3. Percentage-Based Windows**

```python
# Robust across variable episode lengths
baseline_pct = 0.25      # 25% of episode for baseline
current_pct = 0.15       # 15% of episode for current
min_gap_pct = 0.05       # 5% gap between windows

# With minimum absolute sizes for short episodes
baseline_size = max(episode_duration * 0.25, 30s)
current_size = max(episode_duration * 0.15, 20s)
```

**4. Auto-Detected Baseline**

```python
# Scan for healthy period, don't assume
baseline = selector._auto_detect_baseline(
    before_time=analysis_time,
    health_threshold=0.5,    # Max health score to be "healthy"
    min_duration=30s
)

# Validates:
# - No errors in period
# - No CPU/memory spikes
# - No latency anomalies
# - Sufficient duration
```

## Implementation Priority

**Phase 1: Fix Time Windows** (Highest Impact)
- Implement TimeWindowSelector
- Use point-in-time analysis instead of episode aggregation
- Auto-detect baseline with health validation
- Use percentage-based windows

**Expected Impact**: Eliminates recovery artifacts, artificial outlier pods

**Phase 2: Filter Outlier Pods** (High Impact)
- Modify confidence assignment based on pod coverage
- Filter out low-coverage (<30%) pod-only degradation
- Require service-level confirmation for outlier pods

**Expected Impact**: Eliminates most false positives from cascading effects

**Phase 3: Refine Scoring** (Medium Impact)
- Adjust physics coverage weight
- Refine semantic bonus calculation
- Better temporal scoring

**Expected Impact**: Better ranking among true candidates

## Validation Approach

**Test on the 9 false positive cases:**

1. Run new window selection
2. Check if baseline is actually healthy (health_score < 0.5)
3. Check if false positive nodes still have pod degradation in new current window
4. Check if they're filtered out due to low coverage

**Expected results**:
- Cases with recovery-artifact outliers: Should disappear with proper time windows
- Cases with cascading outliers during fault: Should be filtered out by coverage threshold
- Ground truth with service-wide degradation: Should rank correctly

## Benefits of This Approach

**1. Principled**: Based on first-principles reasoning about causality
**2. Robust**: Works across variable episode lengths and configurations
**3. Production-ready**: Matches how RCA would actually be used
**4. Honest**: Reports low confidence when evidence is weak
**5. Debuggable**: Clear criteria for each decision

## Next Steps

1. Integrate TimeWindowSelector into run_rca_batch.py
2. Test on existing false positive cases
3. Validate that ground truth still ranks correctly
4. Measure improvement in precision/recall
5. Document any remaining failure modes
