"""
temporal_analyzer.py

Temporal Causality Analysis for RCA.
Uses changepoint detection to determine WHEN each node first showed degradation,
then uses graph topology to determine causal relationships.

Key insight: If Node A degraded first AND downstream nodes degraded later,
A is likely the root cause (not just coincidentally degraded early).
"""

import numpy as np
import networkx as nx
import pandas as pd
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from statistical_utils import detect_changepoint


class TemporalAnalyzer:
    """
    Analyzes temporal patterns to establish causality.
    """

    def __init__(self, topology: nx.DiGraph):
        self.topology = topology

    def detect_first_impact_times(
        self,
        metrics_df: pd.DataFrame,
        fault_start_time: float
    ) -> Dict[str, float]:
        """
        For each node, find the earliest time it showed anomaly.

        Uses CHANGEPOINT DETECTION (not simple thresholds) to avoid noise.

        Args:
            metrics_df: Full DataFrame with time-series data
            fault_start_time: When the fault was injected

        Returns:
            {node_id: first_impact_time}
        """
        first_impacts = {}

        # Critical metrics that indicate degradation
        # Use generic terms that match actual metric names
        critical_metrics = [
            'cpu',
            'memory',
            'latency',
            'duration',
            'error',
            'thread_pool'
        ]

        # Get unique nodes in the data
        nodes = metrics_df['component_id'].unique()

        for node_id in nodes:
            if node_id not in self.topology.nodes:
                continue

            # Get all metrics for this node
            node_data = metrics_df[metrics_df['component_id'] == node_id]

            earliest_time = float('inf')

            # Check each critical metric for changepoints
            for metric_name in critical_metrics:
                # Filter to this specific metric
                metric_data = node_data[node_data['name'].str.contains(metric_name, na=False, case=False)]

                if len(metric_data) == 0:
                    continue

                # Sort by time
                metric_data = metric_data.sort_values('sim_time')
                times = metric_data['sim_time'].values
                values = metric_data['value'].values

                # Only analyze post-fault period
                post_fault_mask = times >= fault_start_time
                if not np.any(post_fault_mask):
                    continue

                post_fault_times = times[post_fault_mask]
                post_fault_values = values[post_fault_mask]

                if len(post_fault_values) < 5:
                    continue

                # Detect changepoint in post-fault window
                impact_time = self._find_changepoint_time(
                    post_fault_times,
                    post_fault_values
                )

                if impact_time is not None:
                    earliest_time = min(earliest_time, impact_time)

            if earliest_time < float('inf'):
                first_impacts[node_id] = earliest_time

        return first_impacts

    def _find_changepoint_time(
        self,
        times: np.ndarray,
        values: np.ndarray
    ) -> Optional[float]:
        """
        Find the time when a changepoint occurred in the time series.

        Returns:
            Timestamp of changepoint, or None if no significant change detected
        """
        if len(values) < 5:
            return None

        # Try ruptures library for PELT/BinSeg
        try:
            import ruptures as rpt

            # Use Binary Segmentation for speed
            algo = rpt.Binseg(model="l2").fit(values)
            breakpoints = algo.predict(n_bkps=1)

            # breakpoints returns indices (last point is always len(values))
            if breakpoints and len(breakpoints) > 1:
                idx = breakpoints[0]
                # Ensure it's not at the very edge
                if 1 < idx < len(values) - 1:
                    return times[idx]
        except (ImportError, Exception):
            pass

        # Fallback: Simple threshold-based detection
        # Look for sustained increase
        window_size = min(5, len(values) // 3)
        baseline_mean = np.mean(values[:window_size])
        baseline_std = np.std(values[:window_size])

        if baseline_std == 0:
            baseline_std = 0.01  # Avoid division by zero

        # Scan forward looking for sustained shift
        for i in range(window_size, len(values) - window_size):
            window = values[i:i+window_size]
            window_mean = np.mean(window)

            # Check for shift > 2 std devs
            if abs(window_mean - baseline_mean) > 2 * baseline_std:
                return times[i]

        return None

    def calculate_temporal_scores(
        self,
        first_impacts: Dict[str, float],
        self_scores: Dict[str, float]
    ) -> Dict[str, Dict]:
        """
        Calculate graph-aware temporal scores.

        Key logic: Node scores higher if it:
        1. Degraded early (within 5s of first degradation)
        2. Has downstream nodes that degraded AFTER it (causal evidence)

        Args:
            first_impacts: {node_id: first_impact_time}
            self_scores: {node_id: self_degradation_score} (to filter healthy nodes)

        Returns:
            {node_id: {'temporal_score': float, 'downstream_victims': [...]}}
        """
        if not first_impacts:
            return {}

        scores = {}

        # Find the earliest degradation time
        earliest_time = min(first_impacts.values())

        for node_id, impact_time in first_impacts.items():
            # Skip nodes that aren't actually degraded
            if self_scores.get(node_id, 0) < 1.0:
                continue

            # Calculate relative timing
            relative_time = impact_time - earliest_time

            # Find downstream nodes in the topology
            downstream_victims = []

            for other_id in first_impacts:
                if other_id == node_id:
                    continue

                # Check if there's a path from node_id to other_id
                if nx.has_path(self.topology, node_id, other_id):
                    other_time = first_impacts[other_id]

                    # Did the downstream node degrade AFTER this node?
                    if other_time > impact_time:
                        # Also check if downstream node is actually degraded
                        if self_scores.get(other_id, 0) >= 1.0:
                            downstream_victims.append(other_id)

            # Calculate temporal score based on timing + causality
            if relative_time < 5.0:  # Degraded within 5s of earliest
                base_score = 10.0
                # Boost for each downstream victim (causal evidence)
                if len(downstream_victims) > 0:
                    temporal_score = base_score + (len(downstream_victims) * 2.0)
                else:
                    temporal_score = base_score
            elif relative_time < 15.0:
                # Degraded later but still early
                temporal_score = 5.0 if downstream_victims else 2.0
            else:
                # Likely victim, not cause
                temporal_score = 0.0

            scores[node_id] = {
                'temporal_score': temporal_score,
                'impact_time': impact_time,
                'relative_time': relative_time,
                'downstream_victims': downstream_victims,
                'victim_count': len(downstream_victims)
            }

        return scores

    def analyze(
        self,
        metrics_df: pd.DataFrame,
        fault_start_time: float,
        self_scores: Dict[str, float]
    ) -> Dict[str, Dict]:
        """
        Main entry point: Detect first impacts and calculate temporal scores.

        Args:
            metrics_df: Full time-series DataFrame
            fault_start_time: When fault was injected
            self_scores: Self-degradation scores to filter healthy nodes

        Returns:
            {node_id: {'temporal_score': float, 'downstream_victims': [], ...}}
        """
        # Detect when each node first showed degradation
        first_impacts = self.detect_first_impact_times(metrics_df, fault_start_time)

        # Calculate scores with graph-aware causality
        temporal_scores = self.calculate_temporal_scores(first_impacts, self_scores)

        return temporal_scores
