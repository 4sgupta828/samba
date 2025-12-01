"""
Metric Impact Analyzer

Comprehensive analysis of a single metric's response to a fault.

Combines all statistical analysis modules to produce a complete
impact assessment for one metric.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
import warnings

# Suppress common warnings
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=UserWarning)

from .timeseries_stats import characterize_timeseries
from .distribution_analysis import compare_distributions
from .changepoint_detection import detect_changepoint, validate_changepoint_at_boundary
from .effect_size import compute_all_effect_sizes, interpret_effect_size
from .pattern_analysis import analyze_pattern_changes, interpret_pattern_changes


@dataclass
class MetricImpactResult:
    """Complete impact analysis result for a single metric."""
    metric_name: str
    severity_score: float  # 0.0 (no impact) to 1.0 (maximum impact)
    severity_class: str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NEGLIGIBLE'

    baseline_characterization: Dict
    fault_characterization: Dict

    distribution_comparison: Dict
    effect_sizes: Dict
    pattern_changes: Dict
    changepoint: Dict

    interpretation: str

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def classify_metric_type(metric_name: str) -> Tuple[str, float]:
    """
    Classify metric type and assign criticality weight.

    Args:
        metric_name: Name of the metric

    Returns:
        (metric_type, criticality_weight)
    """
    metric_lower = metric_name.lower()

    # Error metrics (highest priority)
    if any(x in metric_lower for x in ['error', 'fail', 'reject', 'timeout', 'exception']):
        return ('error', 1.0)

    # Latency metrics (high priority)
    if any(x in metric_lower for x in ['latency', 'duration', 'time', 'p99', 'p95', 'p90']):
        if 'p99' in metric_lower or 'p95' in metric_lower:
            return ('latency_p99', 0.9)
        return ('latency', 0.8)

    # Saturation metrics (medium-high priority)
    if any(x in metric_lower for x in ['queue', 'pool', 'active', 'utilization']):
        return ('saturation', 0.7)

    # Throughput metrics (medium priority)
    if any(x in metric_lower for x in ['request', 'throughput', 'rate', 'qps']):
        return ('throughput', 0.6)

    # Resource metrics (medium-low priority)
    if any(x in metric_lower for x in ['cpu', 'memory', 'disk', 'network']):
        return ('resource', 0.4)

    # Cache metrics (low priority)
    if any(x in metric_lower for x in ['cache', 'hit_rate', 'miss']):
        return ('cache', 0.3)

    # Default
    return ('other', 0.5)


def compute_severity_score(
    metric_name: str,
    distribution_comparison: Dict,
    effect_sizes: Dict,
    pattern_changes: Dict,
    changepoint: Dict
) -> Tuple[float, str]:
    """
    Compute composite severity score from all analyses.

    Args:
        metric_name: Name of metric
        distribution_comparison: Distribution comparison results
        effect_sizes: Effect size results
        pattern_changes: Pattern analysis results
        changepoint: Changepoint detection results

    Returns:
        (severity_score, severity_class)
    """
    metric_type, criticality_weight = classify_metric_type(metric_name)

    # Component scores (0-1 scale)
    scores = []

    # 1. Statistical significance score
    location_tests = distribution_comparison.get('location_tests', {})
    mann_whitney = location_tests.get('mann_whitney_u', {})
    p_value = mann_whitney.get('p_value', 1.0)

    if not np.isnan(p_value):
        # Convert p-value to score (lower p = higher score)
        if p_value < 0.001:
            stat_score = 1.0
        elif p_value < 0.01:
            stat_score = 0.8
        elif p_value < 0.05:
            stat_score = 0.6
        else:
            stat_score = max(0, 0.5 - p_value)  # Diminishing score for p > 0.05
        scores.append(('statistical_significance', stat_score, 0.3))

    # 2. Effect size score
    cohens_d = effect_sizes.get('cohens_d', np.nan)
    if not np.isnan(cohens_d):
        abs_d = abs(cohens_d)
        if abs_d >= 1.2:
            effect_score = 1.0
        elif abs_d >= 0.8:
            effect_score = 0.8
        elif abs_d >= 0.5:
            effect_score = 0.6
        elif abs_d >= 0.2:
            effect_score = 0.4
        else:
            effect_score = 0.2
        scores.append(('effect_size', effect_score, 0.3))

    # 3. Distribution distance score
    distances = distribution_comparison.get('distances', {})
    wasserstein = distances.get('wasserstein_distance', np.nan)
    kl_div = distances.get('kl_divergence', np.nan)

    if not np.isnan(wasserstein):
        # Normalize Wasserstein (rough heuristic)
        dist_score = min(1.0, wasserstein / 100.0)
        scores.append(('distribution_distance', dist_score, 0.15))
    elif not np.isnan(kl_div):
        dist_score = min(1.0, kl_div / 2.0)
        scores.append(('distribution_distance', dist_score, 0.15))

    # 4. Pattern change score
    volatility = pattern_changes.get('volatility', {})
    vol_ratio = volatility.get('volatility_ratio', np.nan)
    acf_distance = pattern_changes.get('autocorrelation', {}).get('acf_distance', np.nan)

    if not np.isnan(vol_ratio):
        # High volatility increase indicates instability
        if vol_ratio > 5:
            pattern_score = 1.0
        elif vol_ratio > 3:
            pattern_score = 0.8
        elif vol_ratio > 2:
            pattern_score = 0.6
        elif vol_ratio < 0.5:
            pattern_score = 0.4  # Decreased volatility (stabilization)
        else:
            pattern_score = 0.2
        scores.append(('pattern_change', pattern_score, 0.15))
    elif not np.isnan(acf_distance):
        # ACF change as alternative
        if acf_distance > 1.0:
            pattern_score = 0.8
        elif acf_distance > 0.5:
            pattern_score = 0.6
        else:
            pattern_score = 0.3
        scores.append(('pattern_change', pattern_score, 0.15))

    # 5. Changepoint confidence
    cp_detected = changepoint.get('detected', False)
    cp_confidence = changepoint.get('confidence', 0.0)

    if cp_detected:
        scores.append(('changepoint', cp_confidence, 0.1))

    # Compute weighted average
    if len(scores) == 0:
        raw_score = 0.0
    else:
        weighted_sum = sum(score * weight for _, score, weight in scores)
        total_weight = sum(weight for _, _, weight in scores)
        raw_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Apply metric criticality weight
    final_score = raw_score * criticality_weight

    # Classify severity
    if final_score >= 0.7:
        severity_class = 'CRITICAL'
    elif final_score >= 0.5:
        severity_class = 'HIGH'
    elif final_score >= 0.3:
        severity_class = 'MEDIUM'
    elif final_score >= 0.1:
        severity_class = 'LOW'
    else:
        severity_class = 'NEGLIGIBLE'

    return float(final_score), severity_class


def analyze_metric_impact(
    metric_name: str,
    times: np.ndarray,
    values: np.ndarray,
    fault_start_time: float
) -> MetricImpactResult:
    """
    Comprehensive impact analysis for a single metric.

    Args:
        metric_name: Name of the metric
        times: Array of timestamps
        values: Array of values corresponding to times
        fault_start_time: Time when fault was injected

    Returns:
        MetricImpactResult with complete analysis
    """
    # Find index where fault starts
    fault_indices = np.where(times >= fault_start_time)[0]

    if len(fault_indices) == 0:
        # All data is before fault
        expected_changepoint_index = len(times)
    else:
        expected_changepoint_index = fault_indices[0]

    # Split data
    baseline = values[:expected_changepoint_index]
    fault = values[expected_changepoint_index:]

    # Check if we have enough data
    # Special case: For error/failure metrics, baseline=0 and fault>0 is CRITICAL (errors appearing)
    is_error_metric = any(keyword in metric_name.lower() for keyword in ['error', 'failure', 'timeout', 'reject'])

    if len(fault) < 3:
        # Not enough fault data - truly insufficient
        return MetricImpactResult(
            metric_name=metric_name,
            severity_score=0.0,
            severity_class='NEGLIGIBLE',
            baseline_characterization={'error': 'insufficient_data'},
            fault_characterization={'error': 'insufficient_data'},
            distribution_comparison={},
            effect_sizes={},
            pattern_changes={},
            changepoint={'detected': False, 'reason': 'insufficient_data'},
            interpretation='Insufficient data for analysis'
        )

    if len(baseline) < 3:
        # Insufficient baseline data, but we have fault data
        if is_error_metric:
            # For error metrics: 0→N is CRITICAL (errors appearing from healthy state)
            # Treat baseline as all zeros
            baseline_duration = fault_start_time - times[0] if len(times) > 0 else 120
            num_baseline_samples = max(3, int(baseline_duration / 5))  # Assume 5s sampling
            baseline = np.zeros(num_baseline_samples)
        else:
            # For other metrics: can't analyze without baseline reference
            return MetricImpactResult(
                metric_name=metric_name,
                severity_score=0.0,
                severity_class='NEGLIGIBLE',
                baseline_characterization={'error': 'insufficient_baseline'},
                fault_characterization={'sufficient_data': len(fault)},
                distribution_comparison={},
                effect_sizes={},
                pattern_changes={},
                changepoint={'detected': False, 'reason': 'insufficient_baseline'},
                interpretation='Insufficient baseline data for analysis'
            )

    # 1. Characterize baseline and fault periods
    baseline_char = characterize_timeseries(baseline, period_label='baseline')
    fault_char = characterize_timeseries(fault, period_label='fault')

    # 2. Compare distributions
    dist_comparison = compare_distributions(baseline, fault)

    # 3. Compute effect sizes
    effect_sizes = compute_all_effect_sizes(baseline, fault)

    # 4. Analyze pattern changes
    pattern_changes = analyze_pattern_changes(baseline, fault)

    # 5. Detect changepoint
    changepoint = detect_changepoint(
        values,
        expected_location=expected_changepoint_index,
        method='auto'
    )

    # Convert changepoint index to actual time
    if changepoint.get('detected') and changepoint.get('location') is not None:
        cp_idx = changepoint['location']
        if 0 <= cp_idx < len(times):
            changepoint['time'] = float(times[cp_idx])
            changepoint['delay_from_fault'] = changepoint['time'] - fault_start_time

            # Only consider changepoints that occur at or after the fault
            if changepoint['time'] < fault_start_time:
                changepoint['detected'] = False
                changepoint['time'] = None
                changepoint['delay_from_fault'] = None
        else:
            changepoint['time'] = None
            changepoint['delay_from_fault'] = None

    # 6. Compute severity score
    severity_score, severity_class = compute_severity_score(
        metric_name,
        dist_comparison,
        effect_sizes,
        pattern_changes,
        changepoint
    )

    # 7. Generate interpretation
    effect_interpretation = interpret_effect_size(effect_sizes)
    pattern_interpretation = interpret_pattern_changes(pattern_changes)

    interpretation_parts = [effect_interpretation]
    if pattern_interpretation and pattern_interpretation != "Pattern characteristics remained stable":
        interpretation_parts.append(pattern_interpretation)

    interpretation = " ".join(interpretation_parts)

    return MetricImpactResult(
        metric_name=metric_name,
        severity_score=severity_score,
        severity_class=severity_class,
        baseline_characterization=baseline_char,
        fault_characterization=fault_char,
        distribution_comparison=dist_comparison,
        effect_sizes=effect_sizes,
        pattern_changes=pattern_changes,
        changepoint=changepoint,
        interpretation=interpretation
    )


def extract_metric_timeseries(
    metrics_df: pd.DataFrame,
    node_id: str,
    metric_name: str,
    value_column: str = 'value',
    summary_column: str = 'p99'
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Extract time series for a specific metric from metrics DataFrame.
    NOW MATCHES by component.id OR service.name to include pod-level metrics.

    Args:
        metrics_df: DataFrame with metrics (from metrics.jsonl)
        node_id: Component ID or Service Name
        metric_name: Metric name
        value_column: Column name for simple values
        summary_column: Which summary stat to extract (p50, p90, p99, etc.)

    Returns:
        Tuple of (times, values) or None if not found
    """
    # Filter for this component and metric
    # Match by EITHER component.id OR service.name (for aggregated pod metrics)
    mask = (
        (metrics_df['labels'].apply(
            lambda x: x.get('component.id') == node_id or x.get('service.name') == node_id
        )) &
        (metrics_df['name'] == metric_name)
    )

    metric_data = metrics_df[mask].copy()

    if len(metric_data) == 0:
        return None

    # Sort by time
    metric_data['sim_time'] = metric_data['labels'].apply(lambda x: x.get('sim.time', 0))
    metric_data = metric_data.sort_values('sim_time')

    # Get times
    times = metric_data['sim_time'].values

    # Extract values
    if value_column in metric_data.columns:
        # Simple value metrics
        values = metric_data[value_column].values
        return times, values
    elif 'summary' in metric_data.columns:
        # Summary metrics (histograms)
        values = metric_data['summary'].apply(lambda x: x.get(summary_column, np.nan) if isinstance(x, dict) else np.nan).values
        return times, values
    else:
        return None


def analyze_all_node_metrics(
    metrics_df: pd.DataFrame,
    node_id: str,
    fault_start_time: float
) -> Dict[str, MetricImpactResult]:
    """
    Analyze all available metrics for a node.
    NOW INCLUDES pod-level metrics (CPU, memory, thread pools, connection pools).

    Args:
        metrics_df: DataFrame with all metrics
        node_id: Node to analyze
        fault_start_time: When fault was injected

    Returns:
        Dictionary mapping metric_name -> MetricImpactResult
    """
    # Find all metrics for this node
    # Match by EITHER component.id OR service.name (for service-level aggregated metrics from pods)
    node_metrics = metrics_df[
        metrics_df['labels'].apply(
            lambda x: x.get('component.id') == node_id or x.get('service.name') == node_id
        )
    ]['name'].unique()

    results = {}

    for metric_name in node_metrics:
        # Extract time series
        ts_data = extract_metric_timeseries(metrics_df, node_id, metric_name)

        if ts_data is None:
            continue

        times, values = ts_data

        if len(values) < 10:
            continue

        # Analyze metric
        result = analyze_metric_impact(
            metric_name,
            times,
            values,
            fault_start_time
        )

        results[metric_name] = result

    return results


def rank_metrics_by_impact(results: Dict[str, MetricImpactResult]) -> list:
    """
    Rank metrics by severity score (most impacted first).

    Args:
        results: Dictionary of metric_name -> MetricImpactResult

    Returns:
        List of (metric_name, result) tuples sorted by severity
    """
    ranked = sorted(
        results.items(),
        key=lambda x: x[1].severity_score,
        reverse=True
    )
    return ranked
