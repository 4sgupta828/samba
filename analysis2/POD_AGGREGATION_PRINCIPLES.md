# Pod-Level Aggregation: The Right Approach

## The Problem Statement

Given a service with N pods, where some are degraded:
- 1/10 pods degraded at 10x severity → What's the service-level score?
- 5/10 pods degraded at 2x severity → What's the service-level score?
- 10/10 pods degraded at 2x severity → What's the service-level score?

**Insight**: Both **severity** and **coverage** matter. The service impact is:
```
Impact = Severity × Coverage
```

## Three Approaches (All Wrong)

### Approach 1: Mean (Current)
```python
all_pod_scores = [1.0, 1.0, 1.0, 10.0]  # 1 degraded pod
service_score = mean(all_pod_scores) = 3.25
```

**Problem**: 1 degraded pod looks like entire service is moderately degraded. Loses the distribution information.

### Approach 2: Max (My First Fix)
```python
service_score = max(all_pod_scores) = 10.0
```

**Problem**: 1 outlier pod makes entire service look severely degraded. Over-weights outliers.

### Approach 3: Weighted Mean
```python
degraded_pods = [p for p in pods if p.score > 2.0]
service_score = mean(degraded_pod_scores) if degraded_pods else 0
```

**Problem**: Loses coverage information. 1/10 vs 10/10 degraded looks the same.

## The Right Approach: Coverage-Weighted Severity

### Formula
```python
# Step 1: Identify degraded pods
threshold = 2.0  # Minimum score to be considered degraded
degraded_pods = [p for p in pods if p.self_score >= threshold]

# Step 2: Calculate coverage (what fraction is affected?)
coverage = len(degraded_pods) / len(pods)  # 0.0 to 1.0

# Step 3: Calculate average severity among degraded pods
if degraded_pods:
    avg_severity = mean(p.self_score for p in degraded_pods)
else:
    avg_severity = 0.0

# Step 4: Weight severity by coverage
effective_service_score = avg_severity * coverage

# Step 5: Blend with service-level metrics (if available)
final_score = max(
    service_level_score,  # From aggregated metrics
    effective_service_score  # From pod distribution
)
```

### Examples

**Case 1: Hot shard (1/3 pods degraded at 10x)**
```python
degraded_pods = [pod_2]  # score=10.0
coverage = 1/3 = 0.33
avg_severity = 10.0
effective_score = 10.0 × 0.33 = 3.33

Compare to:
- Mean approach: 3.67 (similar, but lost distribution)
- Max approach: 10.0 (over-weighted)
- Coverage-weighted: 3.33 (captures both severity AND limited scope)
```

**Case 2: Service-wide CPU saturation (3/3 pods at 5x)**
```python
coverage = 3/3 = 1.0
avg_severity = 5.0
effective_score = 5.0 × 1.0 = 5.0

Max approach: 5.0 (same)
Coverage-weighted: 5.0 (correct - entire service degraded)
```

**Case 3: Partial degradation (5/10 pods at 3x)**
```python
coverage = 5/10 = 0.5
avg_severity = 3.0
effective_score = 3.0 × 0.5 = 1.5

Max approach: 3.0 (over-estimates)
Coverage-weighted: 1.5 (correct - half the service affected)
```

## Handling Different Pod Health Statuses

### Variance in Degradation Levels

Scenario: 10 pods with varying degradation
```
pod_0: score=0.0 (healthy)
pod_1: score=0.5 (healthy)
pod_2: score=2.0 (mild)
pod_3: score=2.5 (mild)
pod_4: score=5.0 (moderate)
pod_5: score=5.5 (moderate)
pod_6: score=10.0 (severe)
pod_7: score=0.0 (healthy)
pod_8: score=0.0 (healthy)
pod_9: score=0.0 (healthy)
```

**Coverage-weighted approach**:
```python
threshold = 2.0
degraded_pods = [pod_2, pod_3, pod_4, pod_5, pod_6]  # 5 pods
coverage = 5/10 = 0.5
avg_severity = (2.0 + 2.5 + 5.0 + 5.5 + 10.0) / 5 = 5.0
effective_score = 5.0 × 0.5 = 2.5
```

**Interpretation**: Half the service is degraded at moderate-to-severe levels → Score 2.5 (correctly reflects partial but significant impact)

### Multi-Tier Severity

For more nuance, could use weighted tiers:
```python
def calculate_tiered_pod_score(pods):
    severe = [p for p in pods if p.score >= 8.0]
    moderate = [p for p in pods if 4.0 <= p.score < 8.0]
    mild = [p for p in pods if 2.0 <= p.score < 4.0]

    total = len(pods)

    # Weight by tier and coverage
    score = (
        (len(severe) / total) * 10.0 +    # Severe pods contribute full weight
        (len(moderate) / total) * 5.0 +   # Moderate pods contribute half
        (len(mild) / total) * 2.0         # Mild pods contribute less
    )

    return score
```

## Percentile-Based Approach (Alternative)

Instead of threshold-based, use percentiles to capture distribution:

```python
def calculate_percentile_pod_score(pods):
    all_scores = [p.self_score for p in pods]

    # Use P90 or P95 - high enough to catch severe issues,
    # but not fooled by single outliers
    p95 = np.percentile(all_scores, 95)
    p90 = np.percentile(all_scores, 90)
    p75 = np.percentile(all_scores, 75)

    # Weighted combination - higher percentiles get more weight
    effective_score = (p95 * 0.5 + p90 * 0.3 + p75 * 0.2)

    return effective_score
```

**Benefits**:
- Captures distribution automatically
- Not sensitive to exact threshold choice
- 1 outlier → P95 high, P75 low → moderate score
- Widespread degradation → All percentiles high → high score

## Integration with Service-Level Metrics

The final architecture should blend both:

```python
def calculate_effective_service_score(node):
    # 1. Service-level (from aggregated metrics)
    service_score = analyze_service_level_metrics(node)

    # 2. Pod-level (from individual pod analysis)
    if node has pods:
        pods = get_pod_health(node)

        # Option A: Coverage-weighted
        pod_score = calculate_coverage_weighted_score(pods)

        # Option B: Percentile-based
        # pod_score = calculate_percentile_pod_score(pods)

        # Blend: Use whichever signal is stronger
        effective_score = max(service_score, pod_score)
    else:
        effective_score = service_score

    return effective_score
```

**Why max()**:
- If service-wide degradation → both signals high → max() correct
- If pod-level degradation → pod_score high, service_score low → max() catches it
- If healthy → both low → max() correct

## Recommended Implementation

```python
def analyze_pod_level_health(pods, threshold=2.0):
    """
    Analyze pod-level health with coverage weighting.

    Returns:
        {
            'effective_score': float,  # Coverage-weighted score
            'coverage': float,         # Fraction of pods affected
            'avg_severity': float,     # Average severity among degraded pods
            'degraded_count': int,
            'pattern': str             # Description of pattern
        }
    """
    if not pods:
        return {
            'effective_score': 0.0,
            'coverage': 0.0,
            'avg_severity': 0.0,
            'degraded_count': 0,
            'pattern': 'No pods'
        }

    # Identify degraded pods
    degraded = [p for p in pods if p.self_score >= threshold]

    if not degraded:
        return {
            'effective_score': 0.0,
            'coverage': 0.0,
            'avg_severity': 0.0,
            'degraded_count': 0,
            'pattern': 'All pods healthy'
        }

    # Calculate metrics
    coverage = len(degraded) / len(pods)
    avg_severity = sum(p.self_score for p in degraded) / len(degraded)
    max_severity = max(p.self_score for p in degraded)

    # Coverage-weighted effective score
    effective_score = avg_severity * coverage

    # Classify pattern
    if coverage >= 0.8:
        pattern = f"Service-wide degradation ({len(degraded)}/{len(pods)} pods)"
    elif coverage >= 0.5:
        pattern = f"Partial degradation ({len(degraded)}/{len(pods)} pods)"
    elif coverage >= 0.2:
        pattern = f"Multiple pods affected ({len(degraded)}/{len(pods)} pods)"
    else:
        pattern = f"Outlier pods ({len(degraded)}/{len(pods)} pods)"

    return {
        'effective_score': effective_score,
        'coverage': coverage,
        'avg_severity': avg_severity,
        'max_severity': max_severity,
        'degraded_count': len(degraded),
        'total_count': len(pods),
        'pattern': pattern
    }


def calculate_final_service_health(node, baseline_data, current_data):
    """
    Calculate final service health integrating both service and pod levels.
    """
    # Service-level analysis (from aggregated metrics)
    service_metrics = current_data.get(node, {})
    service_self_score = analyze_metrics(service_metrics)

    # Pod-level analysis
    pod_analysis = None
    if has_pods(node):
        pods = []
        for pod_node in get_pod_nodes(node):
            pod_metrics = current_data.get(pod_node, {})
            pod_self_score = analyze_metrics(pod_metrics)
            pods.append({'id': pod_node, 'self_score': pod_self_score})

        pod_analysis = analyze_pod_level_health(pods)

    # Integrate both signals
    if pod_analysis:
        # Use whichever signal is stronger
        effective_score = max(
            service_self_score,
            pod_analysis['effective_score']
        )

        # Metadata for explanation
        metadata = {
            'source': 'pod-level' if pod_analysis['effective_score'] > service_self_score else 'service-level',
            'service_score': service_self_score,
            'pod_score': pod_analysis['effective_score'],
            'pod_coverage': pod_analysis['coverage'],
            'pod_pattern': pod_analysis['pattern']
        }
    else:
        effective_score = service_self_score
        metadata = {
            'source': 'service-level',
            'service_score': service_self_score
        }

    return effective_score, metadata
```

## Example Results

### Hot Shard (1/3 pods degraded at 10x)
```python
service_score = 0.0  # Aggregated metrics look healthy
pod_analysis = {
    'effective_score': 3.33,  # 10.0 * 0.33
    'coverage': 0.33,
    'avg_severity': 10.0,
    'pattern': 'Outlier pods (1/3 pods)'
}
final = max(0.0, 3.33) = 3.33 ✓

Interpretation: Significant but localized issue
```

### Service-Wide CPU Saturation (3/3 pods at 5x)
```python
service_score = 5.0  # Visible in aggregated metrics
pod_analysis = {
    'effective_score': 5.0,  # 5.0 * 1.0
    'coverage': 1.0,
    'avg_severity': 5.0,
    'pattern': 'Service-wide degradation (3/3 pods)'
}
final = max(5.0, 5.0) = 5.0 ✓

Interpretation: Entire service degraded
```

### Partial Degradation (2/10 pods at 8x)
```python
service_score = 1.2  # Slightly elevated
pod_analysis = {
    'effective_score': 1.6,  # 8.0 * 0.2
    'coverage': 0.2,
    'avg_severity': 8.0,
    'pattern': 'Multiple pods affected (2/10 pods)'
}
final = max(1.2, 1.6) = 1.6 ✓

Interpretation: Limited but severe issue
```

## Summary

**Key principles**:
1. **Coverage matters**: 1/10 pods ≠ 10/10 pods degraded
2. **Weight by fraction affected**: `effective_score = severity × coverage`
3. **Preserve distribution information**: Don't lose signal about how widespread the issue is
4. **Blend service + pod signals**: Use `max()` to catch both service-wide and pod-level faults
5. **Provide pattern classification**: Help operators understand the degradation pattern

**Not**: `max(pod_scores)` - over-weights outliers
**Not**: `mean(pod_scores)` - dilutes outliers
**Yes**: `mean(degraded_pod_scores) × (degraded_count / total_count)` - captures both severity and coverage
