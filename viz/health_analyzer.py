"""
Health analyzer for identifying healthy vs impacted nodes.

This module analyzes node metrics to determine which nodes are "healthy"
(showing no significant impact from the root cause fault) vs "impacted"
(showing degradation in their metrics after fault injection).
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Set
import networkx as nx


def detect_healthy_nodes(
    metrics_df: pd.DataFrame,
    graph: nx.DiGraph,
    label_data: Dict,
    threshold: float = 0.15
) -> Dict[str, any]:
    """
    Detect nodes that show no significant impact from the root cause.

    A node is considered "healthy" if its key metrics (latency, error rate)
    remain relatively stable after the fault starts, showing no signs of
    degradation or propagation effects.

    Args:
        metrics_df: DataFrame with time-series metrics
        graph: NetworkX graph with topology
        label_data: Label data with fault timing info
        threshold: Percentage threshold for considering a metric degraded (default 15%)

    Returns:
        Dictionary with:
        - healthy_nodes: Set of node IDs that are healthy
        - impacted_nodes: Set of node IDs that are impacted
        - node_scores: Dict mapping node_id -> health score (0=impacted, 1=healthy)
        - analysis: Detailed analysis per node
    """
    root_cause = label_data.get('root_cause_node')
    fault_start = label_data.get('fault_start_time', 0)

    # Get all nodes from topology
    all_nodes = set(graph.nodes())

    # Initialize results
    healthy_nodes = set()
    impacted_nodes = set()
    node_scores = {}
    analysis = {}

    # Key metrics to analyze
    key_metrics = [
        'latency_p99',
        'error_rate',
        'latency_p90',
        'latency_p50'
    ]

    for node_id in all_nodes:
        # Root cause is always impacted
        if node_id == root_cause:
            impacted_nodes.add(node_id)
            node_scores[node_id] = 0.0
            analysis[node_id] = {
                'status': 'impacted',
                'reason': 'root_cause',
                'score': 0.0
            }
            continue

        # Get metrics for this node
        node_metrics = metrics_df[metrics_df['component_id'] == node_id].copy()

        if node_metrics.empty:
            # No metrics available - consider healthy by default
            healthy_nodes.add(node_id)
            node_scores[node_id] = 1.0
            analysis[node_id] = {
                'status': 'healthy',
                'reason': 'no_metrics',
                'score': 1.0
            }
            continue

        # Split into before/after fault periods
        before_fault = node_metrics[node_metrics['sim_time'] < fault_start]
        after_fault = node_metrics[node_metrics['sim_time'] >= fault_start]

        if before_fault.empty or after_fault.empty:
            # Not enough data to determine health
            healthy_nodes.add(node_id)
            node_scores[node_id] = 0.8
            analysis[node_id] = {
                'status': 'healthy',
                'reason': 'insufficient_data',
                'score': 0.8
            }
            continue

        # Analyze each key metric
        degradation_detected = False
        metric_changes = {}

        for metric_name in key_metrics:
            # Check if this metric exists for this node
            metric_col = None

            # Try to find the metric in the dataframe
            # Metrics might be stored in different columns based on their type
            if metric_name == 'latency_p99':
                if 'p99' in node_metrics.columns:
                    metric_col = 'p99'
            elif metric_name == 'latency_p90':
                if 'p90' in node_metrics.columns:
                    metric_col = 'p90'
            elif metric_name == 'latency_p50':
                if 'p50' in node_metrics.columns:
                    metric_col = 'p50'
            elif metric_name == 'error_rate':
                if 'value' in node_metrics.columns:
                    # Check if this is error_rate metric by metric_name column
                    error_metrics = node_metrics[node_metrics['metric_name'].str.contains('error', case=False, na=False)]
                    if not error_metrics.empty:
                        # Analyze error rate separately
                        before_errors = error_metrics[error_metrics['sim_time'] < fault_start]['value'].mean()
                        after_errors = error_metrics[error_metrics['sim_time'] >= fault_start]['value'].mean()

                        if pd.notna(before_errors) and pd.notna(after_errors):
                            # Significant increase in errors indicates impact
                            if after_errors > before_errors * 1.5 or after_errors > 0.05:
                                degradation_detected = True
                                metric_changes['error_rate'] = {
                                    'before': before_errors,
                                    'after': after_errors,
                                    'change_pct': ((after_errors - before_errors) / max(before_errors, 0.001)) * 100
                                }
                    continue

            if metric_col and metric_col in node_metrics.columns:
                # Calculate baseline and post-fault values
                before_mean = before_fault[metric_col].mean()
                after_mean = after_fault[metric_col].mean()

                # Skip if we don't have valid data
                if pd.isna(before_mean) or pd.isna(after_mean) or before_mean == 0:
                    continue

                # Calculate percentage change
                pct_change = ((after_mean - before_mean) / before_mean)

                # Check for significant degradation
                if pct_change > threshold:
                    degradation_detected = True
                    metric_changes[metric_name] = {
                        'before': before_mean,
                        'after': after_mean,
                        'change_pct': pct_change * 100
                    }

        # Determine health status
        if degradation_detected:
            impacted_nodes.add(node_id)
            score = 0.3  # Impacted but not root cause
            status = 'impacted'
        else:
            healthy_nodes.add(node_id)
            score = 1.0
            status = 'healthy'

        node_scores[node_id] = score
        analysis[node_id] = {
            'status': status,
            'reason': 'degradation_detected' if degradation_detected else 'stable_metrics',
            'score': score,
            'metric_changes': metric_changes
        }

    return {
        'healthy_nodes': healthy_nodes,
        'impacted_nodes': impacted_nodes,
        'node_scores': node_scores,
        'analysis': analysis
    }


def get_healthy_node_ids(health_analysis: Dict) -> List[str]:
    """
    Extract list of healthy node IDs from health analysis.

    Args:
        health_analysis: Result from detect_healthy_nodes()

    Returns:
        List of node IDs that are healthy
    """
    return list(health_analysis['healthy_nodes'])


def get_impacted_node_ids(health_analysis: Dict) -> List[str]:
    """
    Extract list of impacted node IDs from health analysis.

    Args:
        health_analysis: Result from detect_healthy_nodes()

    Returns:
        List of node IDs that are impacted
    """
    return list(health_analysis['impacted_nodes'])
