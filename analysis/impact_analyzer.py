"""
Metric-agnostic impact analyzer for fault propagation detection.

This module automatically discovers and analyzes ALL available metrics for each node
to determine if it was impacted by a fault. Uses rigorous statistical methods instead
of arbitrary thresholds.

Key Features:
- Automatic metric discovery (no hard-coded metric names)
- Statistical hypothesis testing (Mann-Whitney U, t-tests)
- Effect size calculation (Cohen's d)
- Baseline stability validation
- Change point detection
- Intelligent metric weighting
- Configurable thresholds via central config
"""

import numpy as np
import pandas as pd
import networkx as nx
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

from .impact_config import ImpactAnalysisConfig, get_config
from .statistical_utils import (
    validate_baseline_stability,
    test_distribution_shift,
    calculate_effect_size,
    categorize_effect_size,
    test_variance_change,
    calculate_robust_statistics,
    detect_changepoint_at_boundary,
    calculate_rate_from_counter,
    determine_change_direction,
    is_degradation_pattern,
    compute_confidence_level,
)


@dataclass
class MetricAnalysisResult:
    """Result of analyzing a single metric."""
    metric_name: str
    impact_score: float  # 0=impacted, 1=healthy
    confidence: str  # 'high', 'medium', 'low'
    evidence: Dict
    statistics: Dict


@dataclass
class NodeImpactResult:
    """Result of analyzing all metrics for a node."""
    node_id: str
    impact_score: float  # 0=impacted, 1=healthy
    classification: str  # 'impacted', 'healthy', 'uncertain'
    confidence: str
    metrics_analyzed: List[str]
    metric_results: Dict[str, MetricAnalysisResult]
    reason: str
    is_entry_point: bool = False  # Gateway/entry nodes should never be hidden


def detect_node_impacts(
    metrics_df: pd.DataFrame,
    graph: nx.DiGraph,
    label_data: Dict,
    config: Optional[ImpactAnalysisConfig] = None
) -> Dict:
    """
    Detect which nodes are impacted by the fault.

    This is the main entry point for impact analysis.

    Args:
        metrics_df: DataFrame with time-series metrics
        graph: NetworkX graph with topology
        label_data: Label data with fault timing info
        config: Configuration (uses default if None)

    Returns:
        Dictionary with:
        - healthy_nodes: Set of node IDs that are healthy
        - impacted_nodes: Set of node IDs that are impacted
        - uncertain_nodes: Set of node IDs with uncertain classification
        - node_scores: Dict mapping node_id -> impact score
        - node_results: Dict mapping node_id -> NodeImpactResult
    """
    if config is None:
        config = get_config()

    root_cause = label_data.get('root_cause_node')
    fault_start = label_data.get('fault_start_time', 0)

    # Get all nodes from topology
    all_nodes = set(graph.nodes())

    healthy_nodes = set()
    impacted_nodes = set()
    uncertain_nodes = set()
    node_scores = {}
    node_results = {}

    if config.verbose:
        print(f"\n=== Analyzing {len(all_nodes)} nodes for fault impact ===")
        print(f"Root cause: {root_cause}")
        print(f"Fault start time: {fault_start}")

    for node_id in all_nodes:
        result = analyze_node_impact(
            node_id=node_id,
            metrics_df=metrics_df,
            fault_start=fault_start,
            root_cause=root_cause,
            graph=graph,
            config=config
        )

        node_results[node_id] = result
        node_scores[node_id] = result.impact_score

        if result.classification == 'impacted':
            impacted_nodes.add(node_id)
        elif result.classification == 'healthy':
            healthy_nodes.add(node_id)
        else:
            uncertain_nodes.add(node_id)

        if config.verbose:
            print(f"  {node_id}: {result.classification} "
                  f"(score={result.impact_score:.2f}, "
                  f"confidence={result.confidence}, "
                  f"metrics={len(result.metrics_analyzed)})")

    return {
        'healthy_nodes': healthy_nodes,
        'impacted_nodes': impacted_nodes,
        'uncertain_nodes': uncertain_nodes,
        'node_scores': node_scores,
        'node_results': node_results,
        'config_used': config.to_dict()
    }


def analyze_node_impact(
    node_id: str,
    metrics_df: pd.DataFrame,
    fault_start: float,
    root_cause: str,
    graph: nx.DiGraph,
    config: ImpactAnalysisConfig
) -> NodeImpactResult:
    """
    Analyze a single node to determine if it was impacted.

    Args:
        node_id: Node to analyze
        metrics_df: DataFrame with all metrics
        fault_start: Fault injection time
        root_cause: Root cause node ID
        graph: Topology graph
        config: Analysis configuration

    Returns:
        NodeImpactResult with detailed analysis
    """
    # Check if this is an entry point node (gateway)
    is_entry = is_entry_point_node(node_id, graph)

    # Root cause is always impacted
    if config.scoring.root_cause_override and node_id == root_cause:
        return NodeImpactResult(
            node_id=node_id,
            impact_score=0.0,
            classification='impacted',
            confidence='high',
            metrics_analyzed=[],
            metric_results={},
            reason='root_cause',
            is_entry_point=is_entry
        )

    # Check if node is reachable from root cause
    # If not reachable (neither upstream nor downstream), it cannot be impacted
    is_reachable = is_node_reachable_from_root_cause(node_id, root_cause, graph)

    if not is_reachable:
        # Node is not in the fault propagation path - mark as healthy
        return NodeImpactResult(
            node_id=node_id,
            impact_score=1.0,  # Definitely healthy
            classification='healthy',
            confidence='high',
            metrics_analyzed=[],
            metric_results={},
            reason='not_reachable_from_root_cause',
            is_entry_point=is_entry
        )

    # Get all metrics for this node
    node_metrics = metrics_df[metrics_df['component_id'] == node_id].copy()

    if node_metrics.empty:
        return NodeImpactResult(
            node_id=node_id,
            impact_score=config.scoring.no_metrics_default_score,
            classification='uncertain',
            confidence='low',
            metrics_analyzed=[],
            metric_results={},
            reason='no_metrics',
            is_entry_point=is_entry
        )

    # Discover all available metrics
    available_metrics = node_metrics['metric_name'].unique()

    if config.verbose:
        print(f"\n  Node {node_id}: Found {len(available_metrics)} metrics")

    # Analyze each metric
    metric_results = {}
    for metric_name in available_metrics:
        result = analyze_single_metric(
            node_metrics=node_metrics,
            metric_name=metric_name,
            fault_start=fault_start,
            config=config
        )

        if result is not None:
            metric_results[metric_name] = result

    if not metric_results:
        return NodeImpactResult(
            node_id=node_id,
            impact_score=config.scoring.no_metrics_default_score,
            classification='uncertain',
            confidence='low',
            metrics_analyzed=[],
            metric_results={},
            reason='no_valid_metrics',
            is_entry_point=is_entry
        )

    # Aggregate results across all metrics
    aggregate_score, aggregate_confidence = aggregate_metric_results(
        metric_results=metric_results,
        config=config
    )

    # Classify based on thresholds
    if aggregate_score < config.scoring.impacted_threshold:
        classification = 'impacted'
    elif aggregate_score > config.scoring.healthy_threshold:
        classification = 'healthy'
    else:
        classification = 'uncertain'

    return NodeImpactResult(
        node_id=node_id,
        impact_score=aggregate_score,
        classification=classification,
        confidence=aggregate_confidence,
        metrics_analyzed=list(metric_results.keys()),
        metric_results=metric_results,
        reason='statistical_analysis',
        is_entry_point=is_entry
    )


def analyze_single_metric(
    node_metrics: pd.DataFrame,
    metric_name: str,
    fault_start: float,
    config: ImpactAnalysisConfig
) -> Optional[MetricAnalysisResult]:
    """
    Analyze a single metric for a node.

    Args:
        node_metrics: DataFrame with metrics for this node
        metric_name: Name of metric to analyze
        fault_start: Fault injection time
        config: Analysis configuration

    Returns:
        MetricAnalysisResult or None if insufficient data
    """
    # Extract time series for this metric
    metric_data = extract_metric_timeseries(
        node_metrics=node_metrics,
        metric_name=metric_name,
        fault_start=fault_start,
        config=config
    )

    if not metric_data['has_sufficient_data']:
        return None

    before = metric_data['before']
    after = metric_data['after']

    # Step 1: Validate baseline stability
    baseline_check = validate_baseline_stability(
        baseline_data=before,
        cv_threshold=config.statistical.baseline_cv_max,
        trend_threshold=config.statistical.baseline_trend_max
    )

    if not baseline_check['is_stable']:
        # Unstable baseline - low confidence
        return MetricAnalysisResult(
            metric_name=metric_name,
            impact_score=0.5,
            confidence='low',
            evidence={'baseline_stable': False, 'reason': baseline_check['reason']},
            statistics={}
        )

    # Step 2: Statistical significance test
    dist_test = test_distribution_shift(
        before=before,
        after=after,
        alpha=config.statistical.alpha,
        prefer_nonparametric=True
    )

    # Step 3: Effect size
    effect = calculate_effect_size(before, after)
    effect_category = categorize_effect_size(effect)

    # Step 4: Robust statistics
    robust_stats = calculate_robust_statistics(before, after)

    # Step 5: Variance change
    variance_test = test_variance_change(
        before=before,
        after=after,
        alpha=config.statistical.alpha
    )

    # Step 6: Change direction
    direction = determine_change_direction(before, after)

    # Step 7: Expected behavior
    expected_behavior = config.metric_behavior.get_expected_behavior(metric_name)

    # Step 8: Check if pattern matches degradation
    matches_degradation = is_degradation_pattern(direction, expected_behavior)

    # Step 9: Change point detection (optional)
    changepoint_detected = False
    if config.change_detection.enabled:
        combined = np.concatenate([before, after])
        changepoint_detected = detect_changepoint_at_boundary(
            time_series=combined,
            boundary_index=len(before),
            tolerance=config.change_detection.fault_time_tolerance,
            penalty=config.change_detection.penalty
        )

    # Step 10: Compute confidence
    confidence = compute_confidence_level(
        p_value=dist_test['p_value'],
        effect_size=effect,
        n_before=len(before),
        n_after=len(after),
        min_samples=config.statistical.min_samples_before
    )

    # Step 11: Compute impact score
    impact_score = compute_impact_score(
        statistically_significant=dist_test['significant'],
        p_value=dist_test['p_value'],
        effect_size=effect,
        direction=direction,
        expected_behavior=expected_behavior,
        matches_degradation=matches_degradation,
        variance_increased=variance_test['variance_increased'],
        changepoint_detected=changepoint_detected,
        config=config
    )

    # Compile evidence
    evidence = {
        'baseline_stable': baseline_check['is_stable'],
        'statistically_significant': dist_test['significant'],
        'p_value': dist_test['p_value'],
        'test_used': dist_test['test_used'],
        'effect_size': effect,
        'effect_magnitude': effect_category,
        'direction': direction,
        'expected_behavior': expected_behavior,
        'matches_degradation': matches_degradation,
        'variance_changed': variance_test['variance_changed'],
        'variance_increased': variance_test['variance_increased'],
        'changepoint_detected': changepoint_detected,
    }

    # Compile statistics
    statistics = {
        'before_mean': float(np.mean(before)),
        'after_mean': float(np.mean(after)),
        'before_median': robust_stats['before_median'],
        'after_median': robust_stats['after_median'],
        'before_std': float(np.std(before)),
        'after_std': float(np.std(after)),
        'before_iqr': robust_stats['before_iqr'],
        'after_iqr': robust_stats['after_iqr'],
        'pct_change': ((np.mean(after) - np.mean(before)) / np.mean(before) * 100)
                      if np.mean(before) > 0 else 0,
        'robust_change': robust_stats['robust_change'],
        'n_before': len(before),
        'n_after': len(after),
    }

    return MetricAnalysisResult(
        metric_name=metric_name,
        impact_score=impact_score,
        confidence=confidence,
        evidence=evidence,
        statistics=statistics
    )


def extract_metric_timeseries(
    node_metrics: pd.DataFrame,
    metric_name: str,
    fault_start: float,
    config: ImpactAnalysisConfig
) -> Dict:
    """
    Extract time series data for a specific metric.

    Handles:
    - Histograms (with p50, p90, p99)
    - Gauges (with value)
    - Counters (converts to rate)

    Args:
        node_metrics: DataFrame with metrics for this node
        metric_name: Name of metric
        fault_start: Fault injection time
        config: Configuration

    Returns:
        Dictionary with 'has_sufficient_data', 'before', 'after'
    """
    metric_data = node_metrics[node_metrics['metric_name'] == metric_name].copy()

    if metric_data.empty:
        return {'has_sufficient_data': False}

    # Determine which column to analyze
    value_column = None

    # For histograms, prefer p99 > p90 > p50
    if 'p99' in metric_data.columns and metric_data['p99'].notna().any():
        value_column = 'p99'
    elif 'p90' in metric_data.columns and metric_data['p90'].notna().any():
        value_column = 'p90'
    elif 'p50' in metric_data.columns and metric_data['p50'].notna().any():
        value_column = 'p50'
    elif 'value' in metric_data.columns and metric_data['value'].notna().any():
        value_column = 'value'

    if value_column is None:
        return {'has_sufficient_data': False}

    # Split into before/after periods
    before_df = metric_data[metric_data['sim_time'] < fault_start]
    after_df = metric_data[metric_data['sim_time'] >= fault_start]

    # Check for sufficient data
    if len(before_df) < config.statistical.min_samples_before:
        return {'has_sufficient_data': False}
    if len(after_df) < config.statistical.min_samples_after:
        return {'has_sufficient_data': False}

    # Extract values
    before_values = before_df[value_column].dropna().values
    after_values = after_df[value_column].dropna().values

    # Check for counters (need rate calculation)
    is_counter = is_counter_metric(metric_name)

    if is_counter and 'sim_time' in metric_data.columns:
        # Calculate rate for counters
        before_rate = calculate_rate_from_counter(before_df, value_column, 'sim_time')
        after_rate = calculate_rate_from_counter(after_df, value_column, 'sim_time')

        if len(before_rate) < config.statistical.min_samples_before:
            return {'has_sufficient_data': False}
        if len(after_rate) < config.statistical.min_samples_after:
            return {'has_sufficient_data': False}

        return {
            'has_sufficient_data': True,
            'before': before_rate,
            'after': after_rate,
            'is_counter': True
        }

    # Final check on array sizes
    if len(before_values) < config.statistical.min_samples_before:
        return {'has_sufficient_data': False}
    if len(after_values) < config.statistical.min_samples_after:
        return {'has_sufficient_data': False}

    return {
        'has_sufficient_data': True,
        'before': before_values,
        'after': after_values,
        'is_counter': False
    }


def is_counter_metric(metric_name: str) -> bool:
    """Check if a metric is a counter (cumulative) vs gauge (instantaneous)."""
    counter_patterns = ['total', 'count', 'hits', 'misses', 'transmitted', 'received', 'errors']
    metric_lower = metric_name.lower()
    return any(pattern in metric_lower for pattern in counter_patterns)


def compute_impact_score(
    statistically_significant: bool,
    p_value: float,
    effect_size: float,
    direction: str,
    expected_behavior: str,
    matches_degradation: bool,
    variance_increased: bool,
    changepoint_detected: bool,
    config: ImpactAnalysisConfig
) -> float:
    """
    Compute impact score from multiple pieces of evidence.

    Score: 0.0 = definitely impacted, 1.0 = definitely healthy

    Args:
        statistically_significant: Whether distribution shift is significant
        p_value: P-value from statistical test
        effect_size: Cohen's d effect size
        direction: Change direction
        expected_behavior: Expected behavior pattern
        matches_degradation: Whether change matches expected degradation
        variance_increased: Whether variance increased
        changepoint_detected: Whether changepoint detected at fault time
        config: Configuration

    Returns:
        Impact score between 0 and 1
    """
    # Start with neutral score
    score = 0.5

    # Strong evidence of impact
    if statistically_significant and matches_degradation:
        if abs(effect_size) > 0.8:  # Large effect
            score = 0.1
        elif abs(effect_size) > 0.5:  # Medium effect
            score = 0.2
        elif abs(effect_size) > config.statistical.min_effect_size:  # Small but meaningful
            score = 0.3
        else:
            score = 0.4  # Significant but small effect

    # Moderate evidence
    elif statistically_significant and not matches_degradation:
        # Change in unexpected direction or no change
        # Check effect size to determine if this is meaningful
        if abs(effect_size) < config.statistical.min_effect_size:
            # Statistically significant but negligible effect size
            # AND doesn't match degradation pattern → HEALTHY
            score = 0.8
        elif abs(effect_size) < 0.5:
            # Small effect in wrong direction → likely healthy
            score = 0.7
        else:
            # Medium/large effect in wrong direction → could be secondary effect
            score = 0.5

    # Weak evidence or no change
    elif not statistically_significant:
        if abs(effect_size) > 0.5:
            # Large effect but not significant (maybe due to high variance)
            score = 0.5
        else:
            # No significant change - likely healthy
            score = 0.8

    # Adjust for additional evidence

    # Variance increase adds instability signal
    if variance_increased:
        score -= 0.1

    # Change point detection corroborates impact
    if changepoint_detected:
        score -= 0.1

    # Very low p-value is strong evidence
    if p_value < 0.01:
        score -= 0.05

    # Clamp to [0, 1]
    score = max(0.0, min(1.0, score))

    return score


def aggregate_metric_results(
    metric_results: Dict[str, MetricAnalysisResult],
    config: ImpactAnalysisConfig
) -> Tuple[float, str]:
    """
    Aggregate multiple metric analyses into overall node impact score.

    Uses weighted voting where:
    - Each metric contributes based on its importance weight
    - Confidence level scales the contribution
    - Multiple weak signals can combine into strong signal

    Args:
        metric_results: Dictionary of metric name -> MetricAnalysisResult
        config: Configuration

    Returns:
        Tuple of (aggregate_score, aggregate_confidence)
    """
    if not metric_results:
        return 0.5, 'low'

    total_weight = 0.0
    weighted_sum = 0.0
    high_confidence_count = 0
    medium_confidence_count = 0
    low_confidence_count = 0

    for metric_name, result in metric_results.items():
        # Get metric importance weight
        weight = config.metric_weights.get_weight(metric_name)

        # Apply confidence multiplier
        if result.confidence == 'high':
            confidence_mult = config.scoring.high_confidence_multiplier
            high_confidence_count += 1
        elif result.confidence == 'medium':
            confidence_mult = config.scoring.medium_confidence_multiplier
            medium_confidence_count += 1
        else:
            confidence_mult = config.scoring.low_confidence_multiplier
            low_confidence_count += 1

        effective_weight = weight * confidence_mult

        weighted_sum += result.impact_score * effective_weight
        total_weight += effective_weight

    if total_weight == 0:
        return 0.5, 'low'

    aggregate_score = weighted_sum / total_weight

    # Determine aggregate confidence
    total_metrics = len(metric_results)

    if high_confidence_count >= config.scoring.min_metrics_for_high_confidence:
        aggregate_confidence = 'high'
    elif high_confidence_count >= 1 or medium_confidence_count >= 2:
        aggregate_confidence = 'medium'
    else:
        aggregate_confidence = 'low'

    # If very few metrics analyzed, downgrade confidence
    if total_metrics < 2 and config.scoring.require_multiple_metrics:
        if aggregate_confidence == 'high':
            aggregate_confidence = 'medium'
        elif aggregate_confidence == 'medium':
            aggregate_confidence = 'low'

    return aggregate_score, aggregate_confidence


def is_entry_point_node(node_id: str, graph: nx.DiGraph) -> bool:
    """
    Check if a node is an entry point (gateway) that should never be hidden.

    Entry point indicators:
    - is_frontend flag set to True
    - role is 'gateway'
    - type contains 'Gateway'
    - No incoming edges (in_degree == 0)

    Args:
        node_id: Node to check
        graph: Topology graph

    Returns:
        True if node is an entry point
    """
    if node_id not in graph:
        return False

    node_data = graph.nodes[node_id]

    # Check various indicators
    is_frontend = node_data.get('is_frontend', False)
    role = node_data.get('role', '')
    node_type = node_data.get('type', '')

    # Gateway indicators
    if is_frontend:
        return True

    if role == 'gateway':
        return True

    if 'gateway' in node_type.lower():
        return True

    # Check if it's a true entry point (no incoming edges)
    if graph.in_degree(node_id) == 0:
        return True

    return False


def is_node_reachable_from_root_cause(
    node_id: str,
    root_cause: str,
    graph: nx.DiGraph
) -> bool:
    """
    Check if a node is reachable from the root cause node.

    A node is considered reachable if:
    - It's downstream from root cause (fault can propagate TO it), OR
    - It's upstream from root cause (fault can propagate FROM it)

    Args:
        node_id: Node to check
        root_cause: Root cause node
        graph: Topology graph

    Returns:
        True if node is in potential fault propagation path
    """
    if node_id == root_cause:
        return True

    if root_cause not in graph or node_id not in graph:
        # If either node not in graph, can't determine reachability
        # Conservative: assume reachable
        return True

    try:
        # Check if node is downstream (root cause can reach this node)
        descendants = nx.descendants(graph, root_cause)
        if node_id in descendants:
            return True

        # Check if node is upstream (this node can reach root cause)
        ancestors = nx.ancestors(graph, root_cause)
        if node_id in ancestors:
            return True

        return False

    except (nx.NetworkXError, KeyError):
        # Error in graph analysis - be conservative
        return True


# Convenience functions for backward compatibility

def get_healthy_node_ids(analysis_result: Dict) -> List[str]:
    """Extract list of healthy node IDs from analysis result."""
    return list(analysis_result['healthy_nodes'])


def get_impacted_node_ids(analysis_result: Dict) -> List[str]:
    """Extract list of impacted node IDs from analysis result."""
    return list(analysis_result['impacted_nodes'])


def get_uncertain_node_ids(analysis_result: Dict) -> List[str]:
    """Extract list of uncertain node IDs from analysis result."""
    return list(analysis_result.get('uncertain_nodes', []))
