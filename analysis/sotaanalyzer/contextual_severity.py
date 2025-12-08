"""
Contextual Severity Scoring

Fixes the 0→X problem by considering:
1. Absolute magnitude (not just relative change)
2. Service throughput normalization for error rates
3. Metric type-specific thresholds
4. Both relative AND absolute change

The Problem:
- 0→0.01 and 0→10.0 both show as "10000% increase"
- This treats all 0→X transitions equally, which is wrong
- A single error might be negligible for high-throughput services
- But catastrophic for low-throughput services

The Solution:
- Compute both relative (%) and absolute (delta) changes
- Normalize error rates by throughput (errors/request)
- Apply metric-specific absolute thresholds
- Weight severity by BOTH relative and absolute impact
"""

import numpy as np
from typing import Dict, Tuple, Optional


def compute_contextual_severity(
    metric_name: str,
    baseline_mean: float,
    fault_mean: float,
    baseline_std: float,
    fault_std: float,
    relative_change_pct: float,
    cohens_d: float,
    throughput_context: Optional[Dict] = None
) -> Tuple[float, str, Dict]:
    """
    Compute contextual severity score that properly handles 0→X transitions.

    Args:
        metric_name: Name of the metric
        baseline_mean: Baseline period mean
        fault_mean: Fault period mean
        baseline_std: Baseline period std dev
        fault_std: Fault period std dev
        relative_change_pct: Percentage change (may be 10000 for 0→X)
        cohens_d: Cohen's d effect size
        throughput_context: Optional dict with throughput info
            - 'requests_per_sec': float
            - 'baseline_requests': float
            - 'fault_requests': float

    Returns:
        (adjusted_severity_score, reasoning, details_dict)
    """
    metric_lower = metric_name.lower()

    # Classify metric type
    is_error_metric = any(kw in metric_lower for kw in ['error', 'fail', 'reject', 'timeout'])
    is_latency_metric = any(kw in metric_lower for kw in ['latency', 'duration', 'p99', 'p95', 'time'])
    is_saturation_metric = any(kw in metric_lower for kw in ['queue', 'pool', 'active', 'utilization'])
    is_resource_metric = any(kw in metric_lower for kw in ['cpu', 'memory', 'disk'])

    # Compute absolute change
    absolute_delta = fault_mean - baseline_mean

    # Initialize scoring components
    absolute_score = 0.0
    relative_score = 0.0
    context_score = 0.0
    reasoning_parts = []

    # === Handle Error Metrics (Special Case) ===
    if is_error_metric:
        return _score_error_metric(
            baseline_mean, fault_mean, absolute_delta,
            relative_change_pct, throughput_context
        )

    # === Handle Latency Metrics ===
    elif is_latency_metric:
        return _score_latency_metric(
            baseline_mean, fault_mean, absolute_delta,
            relative_change_pct, cohens_d
        )

    # === Handle Saturation Metrics ===
    elif is_saturation_metric:
        return _score_saturation_metric(
            baseline_mean, fault_mean, absolute_delta,
            relative_change_pct
        )

    # === Handle Resource Metrics ===
    elif is_resource_metric:
        return _score_resource_metric(
            baseline_mean, fault_mean, absolute_delta,
            relative_change_pct
        )

    # === Generic Metrics ===
    else:
        return _score_generic_metric(
            baseline_mean, fault_mean, absolute_delta,
            relative_change_pct, cohens_d
        )


def _score_error_metric(
    baseline_mean: float,
    fault_mean: float,
    absolute_delta: float,
    relative_change_pct: float,
    throughput_context: Optional[Dict]
) -> Tuple[float, str, Dict]:
    """
    Score error metrics with throughput normalization.

    Key insight: 1 error/sec is:
    - CRITICAL if only handling 10 req/sec (10% error rate)
    - NEGLIGIBLE if handling 1000 req/sec (0.1% error rate)
    """
    # Case 1: Baseline = 0 (errors appearing from healthy state)
    if baseline_mean == 0:
        # Errors appearing is always bad, but how bad?

        # If we have throughput context, compute error rate
        if throughput_context and 'fault_requests' in throughput_context:
            fault_requests = throughput_context['fault_requests']
            if fault_requests > 0:
                error_rate = fault_mean / fault_requests

                # Threshold-based severity
                if error_rate >= 0.10:  # ≥10% error rate
                    score = 1.0
                    reasoning = f"Errors appeared from healthy state: {fault_mean:.1f} errors ({error_rate*100:.1f}% error rate) - CRITICAL"
                elif error_rate >= 0.05:  # 5-10%
                    score = 0.8
                    reasoning = f"Errors appeared: {fault_mean:.1f} errors ({error_rate*100:.1f}% error rate) - HIGH"
                elif error_rate >= 0.01:  # 1-5%
                    score = 0.6
                    reasoning = f"Errors appeared: {fault_mean:.1f} errors ({error_rate*100:.1f}% error rate) - MEDIUM"
                else:  # <1%
                    score = 0.3
                    reasoning = f"Errors appeared: {fault_mean:.1f} errors ({error_rate*100:.1f}% error rate) - LOW"

                return score, reasoning, {
                    'absolute_errors': fault_mean,
                    'error_rate': error_rate,
                    'throughput': fault_requests,
                    'adjustment': 'throughput_normalized'
                }

        # No throughput context - use absolute count thresholds
        if fault_mean >= 10.0:  # ≥10 errors
            score = 0.9
            reasoning = f"Errors appeared from healthy state: {fault_mean:.1f} errors/sample - HIGH"
        elif fault_mean >= 5.0:  # 5-10 errors
            score = 0.7
            reasoning = f"Errors appeared: {fault_mean:.1f} errors/sample - MEDIUM-HIGH"
        elif fault_mean >= 1.0:  # 1-5 errors
            score = 0.5
            reasoning = f"Errors appeared: {fault_mean:.1f} errors/sample - MEDIUM"
        else:  # <1 error per sample
            score = 0.3
            reasoning = f"Few errors appeared: {fault_mean:.2f} errors/sample - LOW"

        return score, reasoning, {
            'absolute_errors': fault_mean,
            'adjustment': 'absolute_threshold'
        }

    # Case 2: Baseline > 0 (errors increased)
    else:
        increase_factor = fault_mean / baseline_mean

        # Consider both relative increase and absolute level
        if increase_factor >= 3.0 and fault_mean >= 5.0:
            score = 0.9
            reasoning = f"Error rate tripled: {baseline_mean:.1f}→{fault_mean:.1f} ({increase_factor:.1f}x)"
        elif increase_factor >= 2.0 and fault_mean >= 3.0:
            score = 0.7
            reasoning = f"Error rate doubled: {baseline_mean:.1f}→{fault_mean:.1f} ({increase_factor:.1f}x)"
        elif increase_factor >= 1.5:
            score = 0.5
            reasoning = f"Error rate increased: {baseline_mean:.1f}→{fault_mean:.1f} ({increase_factor:.1f}x)"
        else:
            score = 0.3
            reasoning = f"Minor error increase: {baseline_mean:.1f}→{fault_mean:.1f}"

        return score, reasoning, {
            'baseline_errors': baseline_mean,
            'fault_errors': fault_mean,
            'increase_factor': increase_factor
        }


def _score_latency_metric(
    baseline_mean: float,
    fault_mean: float,
    absolute_delta: float,
    relative_change_pct: float,
    cohens_d: float
) -> Tuple[float, str, Dict]:
    """
    Score latency metrics.

    Thresholds (typical for microservices):
    - <10ms: acceptable
    - 10-100ms: moderate
    - 100-1000ms: degraded
    - >1000ms: critical
    """
    # Absolute thresholds (milliseconds)
    if baseline_mean == 0 and fault_mean > 0:
        # Latency appearing from zero (unusual but possible)
        if fault_mean >= 1000:
            return 0.9, f"High latency appeared: {fault_mean:.0f}ms", {'absolute_ms': fault_mean}
        elif fault_mean >= 100:
            return 0.6, f"Moderate latency appeared: {fault_mean:.0f}ms", {'absolute_ms': fault_mean}
        else:
            return 0.3, f"Low latency appeared: {fault_mean:.0f}ms", {'absolute_ms': fault_mean}

    # Normal case: latency increased
    # Consider both relative and absolute change
    if fault_mean >= 1000:  # >1s is always critical
        score = min(1.0, 0.7 + abs(cohens_d) * 0.1)
        reasoning = f"Critical latency: {baseline_mean:.0f}ms→{fault_mean:.0f}ms (+{absolute_delta:.0f}ms)"
    elif fault_mean >= 500:  # 500ms-1s
        score = 0.7
        reasoning = f"High latency: {baseline_mean:.0f}ms→{fault_mean:.0f}ms (+{absolute_delta:.0f}ms)"
    elif absolute_delta >= 100:  # +100ms is significant
        score = 0.6
        reasoning = f"Significant latency increase: +{absolute_delta:.0f}ms ({baseline_mean:.0f}→{fault_mean:.0f}ms)"
    elif relative_change_pct >= 50:  # >50% increase
        score = 0.5
        reasoning = f"Moderate latency increase: {relative_change_pct:.0f}% ({baseline_mean:.0f}→{fault_mean:.0f}ms)"
    else:
        score = 0.3
        reasoning = f"Minor latency change: {baseline_mean:.0f}→{fault_mean:.0f}ms"

    return score, reasoning, {
        'baseline_ms': baseline_mean,
        'fault_ms': fault_mean,
        'delta_ms': absolute_delta
    }


def _score_saturation_metric(
    baseline_mean: float,
    fault_mean: float,
    absolute_delta: float,
    relative_change_pct: float
) -> Tuple[float, str, Dict]:
    """
    Score saturation metrics (queue depth, pool utilization, etc.).

    Key: absolute levels matter more than relative change.
    """
    if baseline_mean == 0:
        # Saturation appearing from zero
        if fault_mean >= 100:
            return 0.9, f"High saturation appeared: {fault_mean:.0f}", {'absolute': fault_mean}
        elif fault_mean >= 50:
            return 0.7, f"Moderate saturation appeared: {fault_mean:.0f}", {'absolute': fault_mean}
        elif fault_mean >= 10:
            return 0.5, f"Some saturation appeared: {fault_mean:.0f}", {'absolute': fault_mean}
        else:
            return 0.3, f"Low saturation appeared: {fault_mean:.1f}", {'absolute': fault_mean}

    # Normal case: consider absolute level
    if fault_mean >= 100:
        score = 0.9
        reasoning = f"Critical saturation: {fault_mean:.0f}"
    elif fault_mean >= 50:
        score = 0.7
        reasoning = f"High saturation: {baseline_mean:.0f}→{fault_mean:.0f}"
    elif absolute_delta >= 20:
        score = 0.6
        reasoning = f"Significant saturation increase: +{absolute_delta:.0f}"
    else:
        score = 0.4
        reasoning = f"Moderate saturation: {baseline_mean:.0f}→{fault_mean:.0f}"

    return score, reasoning, {
        'baseline': baseline_mean,
        'fault': fault_mean,
        'delta': absolute_delta
    }


def _score_resource_metric(
    baseline_mean: float,
    fault_mean: float,
    absolute_delta: float,
    relative_change_pct: float
) -> Tuple[float, str, Dict]:
    """
    Score resource metrics (CPU%, memory%, etc.).

    Assume percentage scale (0-100).
    """
    if baseline_mean == 0:
        # Resource usage appearing from zero
        if fault_mean >= 90:
            return 0.9, f"Critical resource usage appeared: {fault_mean:.0f}%", {'absolute_pct': fault_mean}
        elif fault_mean >= 70:
            return 0.7, f"High resource usage appeared: {fault_mean:.0f}%", {'absolute_pct': fault_mean}
        elif fault_mean >= 50:
            return 0.5, f"Moderate resource usage appeared: {fault_mean:.0f}%", {'absolute_pct': fault_mean}
        else:
            return 0.3, f"Resource usage appeared: {fault_mean:.0f}%", {'absolute_pct': fault_mean}

    # Normal case: resource usage increased
    if fault_mean >= 90:
        score = 0.9
        reasoning = f"Critical resource usage: {fault_mean:.0f}%"
    elif fault_mean >= 80:
        score = 0.8
        reasoning = f"High resource usage: {baseline_mean:.0f}%→{fault_mean:.0f}%"
    elif fault_mean >= 70:
        score = 0.6
        reasoning = f"Elevated resource usage: {baseline_mean:.0f}%→{fault_mean:.0f}%"
    elif absolute_delta >= 20:
        score = 0.5
        reasoning = f"Resource usage increased: +{absolute_delta:.0f}%"
    else:
        score = 0.3
        reasoning = f"Minor resource increase: {baseline_mean:.0f}%→{fault_mean:.0f}%"

    return score, reasoning, {
        'baseline_pct': baseline_mean,
        'fault_pct': fault_mean,
        'delta_pct': absolute_delta
    }


def _score_generic_metric(
    baseline_mean: float,
    fault_mean: float,
    absolute_delta: float,
    relative_change_pct: float,
    cohens_d: float
) -> Tuple[float, str, Dict]:
    """
    Score generic metrics using Cohen's d and relative change.
    """
    # For generic metrics, rely on effect size
    abs_cohens_d = abs(cohens_d) if not np.isnan(cohens_d) else 0.0

    if baseline_mean == 0:
        # Appearing from zero - use Cohen's d if available
        if abs_cohens_d >= 1.2:
            score = 0.8
            reasoning = f"Very large change from zero: {fault_mean:.2f} (d={cohens_d:.2f})"
        elif abs_cohens_d >= 0.8:
            score = 0.6
            reasoning = f"Large change from zero: {fault_mean:.2f} (d={cohens_d:.2f})"
        elif fault_mean >= 10:
            score = 0.5
            reasoning = f"Moderate value appeared: {fault_mean:.2f}"
        else:
            score = 0.3
            reasoning = f"Small value appeared: {fault_mean:.2f}"
    else:
        # Use Cohen's d as primary indicator
        if abs_cohens_d >= 1.2:
            score = 0.8
        elif abs_cohens_d >= 0.8:
            score = 0.6
        elif abs_cohens_d >= 0.5:
            score = 0.5
        elif abs_cohens_d >= 0.2:
            score = 0.3
        else:
            score = 0.1

        direction = "increased" if fault_mean > baseline_mean else "decreased"
        reasoning = f"Metric {direction}: {baseline_mean:.2f}→{fault_mean:.2f} (d={cohens_d:.2f})"

    return score, reasoning, {
        'baseline': baseline_mean,
        'fault': fault_mean,
        'cohens_d': cohens_d
    }
