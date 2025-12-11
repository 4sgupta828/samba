"""
Caller-Callee Disambiguation

When two connected nodes are both impacted, determines which is the root cause
by analyzing RPS, latency, and error patterns.

Key heuristics:
1. If RPS between them increased → caller is likely root cause (overload)
2. If latency increased but no RPS change → callee is likely root cause (slow responses)
3. If errors increased but no RPS/latency change → callee is likely root cause (failing)
4. If nothing changed but both unhealthy → shared cause (compute node, network, etc.)
"""

import networkx as nx
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd


@dataclass
class CallerCalleeAnalysis:
    """Analysis of caller-callee relationship."""
    caller_id: str
    callee_id: str
    edge_type: str

    # Traffic pattern changes
    rps_change: float         # Relative change in RPS (positive = increase)
    latency_change: float     # Relative change in latency
    error_change: float       # Relative change in error rate

    # Classification
    caller_is_root_cause_likelihood: float  # 0-1
    callee_is_root_cause_likelihood: float  # 0-1
    shared_cause_likelihood: float          # 0-1

    verdict: str  # 'caller', 'callee', 'shared', 'unclear'
    reasoning: str

    def to_dict(self) -> Dict:
        return {
            'caller_id': self.caller_id,
            'callee_id': self.callee_id,
            'edge_type': self.edge_type,
            'rps_change': self.rps_change,
            'latency_change': self.latency_change,
            'error_change': self.error_change,
            'caller_is_root_cause_likelihood': self.caller_is_root_cause_likelihood,
            'callee_is_root_cause_likelihood': self.callee_is_root_cause_likelihood,
            'shared_cause_likelihood': self.shared_cause_likelihood,
            'verdict': self.verdict,
            'reasoning': self.reasoning
        }


class CallerCalleeDisambiguator:
    """
    Disambiguates root cause between connected nodes using traffic patterns.
    """

    # Thresholds
    SIGNIFICANT_RPS_INCREASE = 0.2      # 20% RPS increase
    SIGNIFICANT_LATENCY_INCREASE = 0.3  # 30% latency increase
    SIGNIFICANT_ERROR_INCREASE = 0.1    # 10% error rate increase
    NEGLIGIBLE_CHANGE = 0.05            # 5% is negligible

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        fault_start_time: float,
        sample_interval: int = 5
    ):
        """
        Initialize disambiguator.

        Args:
            metrics_df: Time-series metrics DataFrame
            topology_graph: System topology
            fault_start_time: When fault was injected
            sample_interval: Sampling interval in seconds
        """
        self.metrics_df = metrics_df
        self.graph = topology_graph
        self.fault_start_time = fault_start_time
        self.sample_interval = sample_interval

    def analyze_relationship(
        self,
        caller_id: str,
        callee_id: str,
        caller_ranked_metrics: List[Dict],
        callee_ranked_metrics: List[Dict]
    ) -> CallerCalleeAnalysis:
        """
        Analyze caller-callee relationship to determine root cause.

        Args:
            caller_id: Caller node ID
            callee_id: Callee node ID
            caller_ranked_metrics: Metrics from caller
            callee_ranked_metrics: Metrics from callee

        Returns:
            CallerCalleeAnalysis with verdict
        """
        # Get edge type
        edge_data = self.graph.get_edge_data(caller_id, callee_id)
        edge_type = edge_data.get('type', 'unknown') if edge_data else 'unknown'

        # Analyze traffic patterns between them
        rps_change = self._analyze_rps_change(caller_id, callee_id)
        latency_change = self._analyze_latency_change(caller_id, callee_id)
        error_change = self._analyze_error_change(caller_id, callee_id)

        # Apply heuristics
        caller_likelihood, callee_likelihood, shared_likelihood, verdict, reasoning = \
            self._apply_disambiguation_heuristics(
                rps_change, latency_change, error_change,
                caller_id, callee_id
            )

        return CallerCalleeAnalysis(
            caller_id=caller_id,
            callee_id=callee_id,
            edge_type=edge_type,
            rps_change=rps_change,
            latency_change=latency_change,
            error_change=error_change,
            caller_is_root_cause_likelihood=caller_likelihood,
            callee_is_root_cause_likelihood=callee_likelihood,
            shared_cause_likelihood=shared_likelihood,
            verdict=verdict,
            reasoning=reasoning
        )

    def disambiguate_candidates(
        self,
        node_a: str,
        node_b: str,
        node_a_metrics: List[Dict],
        node_b_metrics: List[Dict]
    ) -> Tuple[str, float, str]:
        """
        Disambiguate between two candidate nodes.

        Args:
            node_a: First candidate node ID
            node_b: Second candidate node ID
            node_a_metrics: Metrics from node A
            node_b_metrics: Metrics from node B

        Returns:
            (likely_root_cause_id, confidence, reasoning)
        """
        # Check if they're connected
        edge_a_to_b = self.graph.has_edge(node_a, node_b)
        edge_b_to_a = self.graph.has_edge(node_b, node_a)

        if edge_a_to_b:
            # A calls B
            analysis = self.analyze_relationship(node_a, node_b, node_a_metrics, node_b_metrics)
            if analysis.verdict == 'caller':
                return node_a, analysis.caller_is_root_cause_likelihood, analysis.reasoning
            elif analysis.verdict == 'callee':
                return node_b, analysis.callee_is_root_cause_likelihood, analysis.reasoning
        elif edge_b_to_a:
            # B calls A
            analysis = self.analyze_relationship(node_b, node_a, node_b_metrics, node_a_metrics)
            if analysis.verdict == 'caller':
                return node_b, analysis.caller_is_root_cause_likelihood, analysis.reasoning
            elif analysis.verdict == 'callee':
                return node_a, analysis.callee_is_root_cause_likelihood, analysis.reasoning

        # No direct connection or unclear
        return None, 0.0, "No direct connection or unclear relationship"

    def _analyze_rps_change(
        self,
        caller_id: str,
        callee_id: str
    ) -> float:
        """
        Analyze RPS change between caller and callee.

        Returns relative change (positive = increase, negative = decrease).
        """
        # Look for request_rate or throughput metrics for the edge
        # This is edge-specific, so we need to find metrics like:
        # - "outgoing_requests_to_{callee}" from caller
        # - "incoming_requests_from_{caller}" from callee

        # Try to find RPS metrics
        rps_metrics = [
            f'request_rate',
            f'throughput',
            f'requests_per_second',
            f'incoming_request_rate'
        ]

        # Get callee's incoming request rate
        callee_rps_change = self._get_metric_change_for_node(
            callee_id, rps_metrics
        )

        return callee_rps_change

    def _analyze_latency_change(
        self,
        caller_id: str,
        callee_id: str
    ) -> float:
        """
        Analyze latency change for calls from caller to callee.

        Returns relative change.
        """
        latency_metrics = [
            f'request_latency',
            f'response_time',
            f'duration'
        ]

        # Check caller's outgoing latency to callee
        caller_latency = self._get_metric_change_for_node(
            caller_id, [f'dependency_latency', f'outgoing_request_latency']
        )

        # Check callee's self latency
        callee_latency = self._get_metric_change_for_node(
            callee_id, latency_metrics
        )

        # Use the max (most significant change)
        return max(caller_latency, callee_latency)

    def _analyze_error_change(
        self,
        caller_id: str,
        callee_id: str
    ) -> float:
        """
        Analyze error rate change for calls from caller to callee.

        Returns relative change.
        """
        error_metrics = [
            f'error_rate',
            f'failure_rate',
            f'request_failure_rate'
        ]

        # Check caller's outgoing errors
        caller_errors = self._get_metric_change_for_node(
            caller_id, [f'dependency_error_rate', f'outgoing_request_errors']
        )

        # Check callee's self errors
        callee_errors = self._get_metric_change_for_node(
            callee_id, error_metrics
        )

        return max(caller_errors, callee_errors)

    def _get_metric_change_for_node(
        self,
        node_id: str,
        metric_keywords: List[str]
    ) -> float:
        """
        Get relative change for metrics matching keywords.

        Returns maximum relative change found.
        """
        node_metrics = self.metrics_df[self.metrics_df['component_id'] == node_id]

        if node_metrics.empty:
            return 0.0

        max_change = 0.0

        for metric_keyword in metric_keywords:
            # Find metrics matching keyword
            matching_metrics = node_metrics[
                node_metrics['metric_name'].str.lower().str.contains(metric_keyword.lower(), na=False)
            ]

            for _, metric_data in matching_metrics.iterrows():
                metric_name = metric_data['metric_name']

                # Get baseline and fault values
                baseline_data = node_metrics[
                    (node_metrics['metric_name'] == metric_name) &
                    (node_metrics['timestamp'] < self.fault_start_time)
                ]

                fault_data = node_metrics[
                    (node_metrics['metric_name'] == metric_name) &
                    (node_metrics['timestamp'] >= self.fault_start_time)
                ]

                if not baseline_data.empty and not fault_data.empty:
                    baseline_mean = baseline_data['value'].mean()
                    fault_mean = fault_data['value'].mean()

                    if baseline_mean > 0:
                        relative_change = (fault_mean - baseline_mean) / baseline_mean
                        max_change = max(max_change, relative_change)
                    elif fault_mean > baseline_mean:
                        max_change = max(max_change, 1.0)

        return max_change

    def _apply_disambiguation_heuristics(
        self,
        rps_change: float,
        latency_change: float,
        error_change: float,
        caller_id: str,
        callee_id: str
    ) -> Tuple[float, float, float, str, str]:
        """
        Apply heuristics to determine root cause.

        Returns:
            (caller_likelihood, callee_likelihood, shared_likelihood, verdict, reasoning)
        """
        reasons = []

        # Initialize likelihoods
        caller_score = 0.0
        callee_score = 0.0
        shared_score = 0.0

        # Heuristic 1: RPS increased significantly → Caller overloading callee
        if rps_change >= self.SIGNIFICANT_RPS_INCREASE:
            caller_score += 0.6
            reasons.append(f"RPS increased {rps_change*100:.1f}% → caller overload")

        # Heuristic 2: Latency increased but RPS stable → Callee is slow
        if (latency_change >= self.SIGNIFICANT_LATENCY_INCREASE and
            abs(rps_change) < self.NEGLIGIBLE_CHANGE):
            callee_score += 0.5
            reasons.append(f"Latency up {latency_change*100:.1f}%, RPS stable → callee slow")

        # Heuristic 3: Errors increased but RPS/latency stable → Callee failing
        if (error_change >= self.SIGNIFICANT_ERROR_INCREASE and
            abs(rps_change) < self.SIGNIFICANT_RPS_INCREASE and
            latency_change < self.SIGNIFICANT_LATENCY_INCREASE):
            callee_score += 0.5
            reasons.append(f"Errors up {error_change*100:.1f}%, traffic stable → callee errors")

        # Heuristic 4: Everything increased → Could be caller overload
        if (rps_change >= self.SIGNIFICANT_RPS_INCREASE and
            latency_change >= self.SIGNIFICANT_LATENCY_INCREASE):
            caller_score += 0.3
            reasons.append("RPS + latency up → caller load")

        # Heuristic 5: Nothing changed significantly but both unhealthy → Shared cause
        if (abs(rps_change) < self.NEGLIGIBLE_CHANGE and
            latency_change < self.SIGNIFICANT_LATENCY_INCREASE and
            error_change < self.SIGNIFICANT_ERROR_INCREASE):
            shared_score += 0.6
            reasons.append("No traffic changes → likely shared cause (compute/network)")

        # Normalize likelihoods
        total = caller_score + callee_score + shared_score
        if total > 0:
            caller_likelihood = caller_score / total
            callee_likelihood = callee_score / total
            shared_likelihood = shared_score / total
        else:
            # Default: unclear
            caller_likelihood = 0.33
            callee_likelihood = 0.33
            shared_likelihood = 0.34
            reasons.append("Insufficient evidence for disambiguation")

        # Determine verdict
        if caller_likelihood > 0.5:
            verdict = 'caller'
        elif callee_likelihood > 0.5:
            verdict = 'callee'
        elif shared_likelihood > 0.5:
            verdict = 'shared'
        else:
            verdict = 'unclear'

        reasoning = "; ".join(reasons)

        return caller_likelihood, callee_likelihood, shared_likelihood, verdict, reasoning
