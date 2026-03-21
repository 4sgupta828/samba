"""
Pod-Level Analysis Module

Analyzes individual pods within a service to detect:
- Outlier pods (using IQR-based detection)
- Hot pods (traffic imbalance)
- Noisy neighbor effects (co-location issues)
- Per-pod metric anomalies
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class PodOutlier:
    """Represents an outlier pod for a specific metric."""
    pod_id: str
    metric_name: str
    pod_value: float
    service_median: float
    service_iqr: float
    deviation_score: float  # How many IQRs away from median
    severity: str  # 'MILD', 'MODERATE', 'SEVERE'

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HotPodAnalysis:
    """Analysis of traffic imbalance across pods."""
    service_id: str
    total_pods: int
    hot_pods: List[str]
    load_imbalance_factors: Dict[str, float]  # pod_id -> imbalance factor
    is_imbalanced: bool
    max_imbalance: float

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class NoisyNeighborAnalysis:
    """Analysis of compute node co-location issues."""
    pod_id: str
    compute_node_id: str
    colocated_pods: List[str]  # Other pods on same compute node
    colocated_outliers: List[str]  # Colocated pods that are also outliers
    is_noisy_neighbor: bool
    evidence_score: float

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ServicePodAnalysis:
    """Complete pod-level analysis for a service."""
    service_id: str
    total_pods: int
    outlier_pods: List[PodOutlier]
    hot_pod_analysis: Optional[HotPodAnalysis]
    noisy_neighbor_analysis: List[NoisyNeighborAnalysis]

    # Aggregated service-level metrics (from pods)
    aggregated_severity_score: float
    aggregation_method: str  # 'average', 'majority', 'max'
    pod_consensus: float  # What fraction of pods show impact?

    consistent_impact: bool  # True if all/most pods impacted similarly

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['outlier_pods'] = [o.to_dict() for o in self.outlier_pods]
        result['hot_pod_analysis'] = self.hot_pod_analysis.to_dict() if self.hot_pod_analysis else None
        result['noisy_neighbor_analysis'] = [n.to_dict() for n in self.noisy_neighbor_analysis]
        return result


class PodAnalyzer:
    """Analyzer for pod-level forensics within services."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_data: Dict,
        outlier_threshold: float = 1.5  # IQR multiplier
    ):
        """
        Initialize pod analyzer.

        Args:
            metrics_df: DataFrame with all metrics
            topology_data: Topology data with nodes and edges
            outlier_threshold: IQR multiplier for outlier detection (1.5 is standard)
        """
        self.metrics_df = metrics_df
        self.topology_data = topology_data
        self.outlier_threshold = outlier_threshold

        # Build pod-to-service mapping
        self.pod_to_service = {}
        self.service_to_pods = defaultdict(list)

        for node in topology_data['nodes']:
            if node['type'] == 'Pod':
                pod_id = node['id']
                service_name = node.get('service_name')
                if service_name:
                    self.pod_to_service[pod_id] = service_name
                    self.service_to_pods[service_name].append(pod_id)

        # Build pod-to-compute-node mapping
        self.pod_to_compute_node = {}
        self.compute_node_to_pods = defaultdict(list)

        for node in topology_data['nodes']:
            if node['type'] == 'Pod':
                pod_id = node['id']
                compute_node = node.get('compute_node_id')
                if compute_node:
                    self.pod_to_compute_node[pod_id] = compute_node
                    self.compute_node_to_pods[compute_node].append(pod_id)

    def detect_outlier_pods(
        self,
        service_id: str,
        metric_name: str,
        fault_start_time: float
    ) -> List[PodOutlier]:
        """
        Detect outlier pods for a specific metric using IQR method.

        Uses fault period metrics (after fault_start_time).

        Args:
            service_id: Service to analyze
            metric_name: Metric to check
            fault_start_time: When fault was injected

        Returns:
            List of PodOutlier objects
        """
        pods = self.service_to_pods.get(service_id, [])
        if len(pods) < 3:
            # Need at least 3 pods for meaningful outlier detection
            return []

        # Get fault-period values for each pod
        pod_values = {}

        for pod_id in pods:
            # Get metric values for this pod during fault period
            mask = (
                (self.metrics_df['labels'].apply(lambda x: x.get('component.id') == pod_id)) &
                (self.metrics_df['name'] == metric_name) &
                (self.metrics_df['labels'].apply(lambda x: x.get('sim.time', 0) >= fault_start_time))
            )

            pod_data = self.metrics_df[mask]

            if len(pod_data) == 0:
                continue

            # Extract values (handle both simple and summary metrics)
            if 'value' in pod_data.columns:
                values = pod_data['value'].values
            elif 'summary' in pod_data.columns:
                values = pod_data['summary'].apply(
                    lambda x: x.get('mean', np.nan) if isinstance(x, dict) else np.nan
                ).values
            else:
                continue

            # Use median as representative value
            pod_values[pod_id] = np.median(values[~np.isnan(values)])

        if len(pod_values) < 3:
            return []

        # IQR-based outlier detection
        values_array = np.array(list(pod_values.values()))
        q1 = np.percentile(values_array, 25)
        q3 = np.percentile(values_array, 75)
        iqr = q3 - q1
        median = np.median(values_array)

        if iqr == 0:
            # All pods have same value, no outliers
            return []

        outliers = []

        for pod_id, value in pod_values.items():
            # Calculate deviation in IQRs
            if value > q3:
                deviation = (value - q3) / iqr
            elif value < q1:
                deviation = (q1 - value) / iqr
            else:
                deviation = 0

            if deviation >= self.outlier_threshold:
                # Classify severity
                if deviation >= 3.0:
                    severity = 'SEVERE'
                elif deviation >= 2.0:
                    severity = 'MODERATE'
                else:
                    severity = 'MILD'

                outliers.append(PodOutlier(
                    pod_id=pod_id,
                    metric_name=metric_name,
                    pod_value=value,
                    service_median=median,
                    service_iqr=iqr,
                    deviation_score=deviation,
                    severity=severity
                ))

        return outliers

    def analyze_hot_pods(
        self,
        service_id: str,
        fault_start_time: float
    ) -> Optional[HotPodAnalysis]:
        """
        Check if some pods are handling disproportionate load (hot pods).

        Args:
            service_id: Service to analyze
            fault_start_time: When fault was injected

        Returns:
            HotPodAnalysis or None
        """
        pods = self.service_to_pods.get(service_id, [])
        if len(pods) < 2:
            return None

        # Get request counts for each pod during fault period
        request_counts = {}

        for pod_id in pods:
            # Try service-level request metric
            mask = (
                (self.metrics_df['labels'].apply(lambda x: x.get('component.id') == pod_id)) &
                (self.metrics_df['name'].str.contains('request', case=False, na=False)) &
                (self.metrics_df['labels'].apply(lambda x: x.get('sim.time', 0) >= fault_start_time))
            )

            pod_data = self.metrics_df[mask]

            if len(pod_data) == 0:
                continue

            # Sum total requests
            if 'value' in pod_data.columns:
                total = pod_data['value'].sum()
            else:
                total = 0

            request_counts[pod_id] = total

        if len(request_counts) < 2:
            return None

        # Calculate imbalance factors
        avg_requests = np.mean(list(request_counts.values()))

        if avg_requests == 0:
            return None

        imbalance_factors = {
            pod_id: count / avg_requests
            for pod_id, count in request_counts.items()
        }

        # Identify hot pods (>1.5x average load)
        hot_pods = [
            pod_id for pod_id, factor in imbalance_factors.items()
            if factor > 1.5
        ]

        max_imbalance = max(imbalance_factors.values()) if imbalance_factors else 1.0

        return HotPodAnalysis(
            service_id=service_id,
            total_pods=len(pods),
            hot_pods=hot_pods,
            load_imbalance_factors=imbalance_factors,
            is_imbalanced=len(hot_pods) > 0,
            max_imbalance=max_imbalance
        )

    def analyze_noisy_neighbors(
        self,
        outlier_pods: List[PodOutlier],
        hot_pods: Set[str]
    ) -> List[NoisyNeighborAnalysis]:
        """
        Check if outlier pods (excluding hot pods) are affected by noisy neighbors.

        Args:
            outlier_pods: List of detected outlier pods
            hot_pods: Set of hot pod IDs (to exclude)

        Returns:
            List of NoisyNeighborAnalysis for pods with noisy neighbor evidence
        """
        results = []

        # Get unique outlier pod IDs (excluding hot pods)
        outlier_pod_ids = set(o.pod_id for o in outlier_pods) - hot_pods

        for pod_id in outlier_pod_ids:
            compute_node = self.pod_to_compute_node.get(pod_id)
            if not compute_node:
                continue

            # Find all pods on same compute node
            colocated = [p for p in self.compute_node_to_pods[compute_node] if p != pod_id]

            if not colocated:
                continue

            # Check how many colocated pods are ALSO outliers
            colocated_outliers = [p for p in colocated if p in outlier_pod_ids]

            # Evidence score: fraction of colocated pods that are outliers
            evidence_score = len(colocated_outliers) / len(colocated) if colocated else 0

            # Noisy neighbor if >30% of colocated pods are also outliers
            is_noisy = evidence_score > 0.3

            results.append(NoisyNeighborAnalysis(
                pod_id=pod_id,
                compute_node_id=compute_node,
                colocated_pods=colocated,
                colocated_outliers=colocated_outliers,
                is_noisy_neighbor=is_noisy,
                evidence_score=evidence_score
            ))

        return results

    def analyze_service(
        self,
        service_id: str,
        pod_severity_scores: Dict[str, float],
        fault_start_time: float,
        key_metrics: List[str] = None
    ) -> ServicePodAnalysis:
        """
        Complete pod-level analysis for a service.

        Args:
            service_id: Service to analyze
            pod_severity_scores: Dict mapping pod_id -> severity score
            fault_start_time: When fault was injected
            key_metrics: List of key metrics to check for outliers (if None, use common ones)

        Returns:
            ServicePodAnalysis with complete results
        """
        pods = self.service_to_pods.get(service_id, [])

        if len(pods) == 0:
            # Not a multi-pod service
            return ServicePodAnalysis(
                service_id=service_id,
                total_pods=0,
                outlier_pods=[],
                hot_pod_analysis=None,
                noisy_neighbor_analysis=[],
                aggregated_severity_score=pod_severity_scores.get(service_id, 0.0),
                aggregation_method='direct',
                pod_consensus=1.0,
                consistent_impact=True
            )

        # Default key metrics to check
        if key_metrics is None:
            key_metrics = [
                'service.errors',
                'service.requests',
                'service.latency',
                'container.cpu.usage_pct',
                'container.memory.usage_mb',
                'thread_pool.queue_depth',
                'connection_pool.connections.active'
            ]

        # 1. Detect outlier pods across key metrics
        all_outliers = []
        for metric in key_metrics:
            outliers = self.detect_outlier_pods(service_id, metric, fault_start_time)
            all_outliers.extend(outliers)

        # 2. Analyze hot pods (traffic imbalance)
        hot_pod_analysis = self.analyze_hot_pods(service_id, fault_start_time)
        hot_pods = set(hot_pod_analysis.hot_pods) if hot_pod_analysis else set()

        # 3. Analyze noisy neighbors
        noisy_neighbor_analysis = self.analyze_noisy_neighbors(all_outliers, hot_pods)

        # 4. Aggregate severity scores (use average - prod system behavior)
        pod_scores = [pod_severity_scores.get(pod_id, 0.0) for pod_id in pods]
        aggregated_score = np.mean(pod_scores) if pod_scores else 0.0

        # 5. Pod consensus (what fraction show significant impact?)
        impacted_pods = sum(1 for score in pod_scores if score >= 0.3)
        pod_consensus = impacted_pods / len(pods) if pods else 0.0

        # 6. Consistent impact? (low variance in pod scores)
        consistent_impact = False
        if len(pod_scores) >= 2:
            score_std = np.std(pod_scores)
            score_mean = np.mean(pod_scores)
            cv = score_std / score_mean if score_mean > 0 else 0
            consistent_impact = cv < 0.5  # Coefficient of variation < 0.5

        return ServicePodAnalysis(
            service_id=service_id,
            total_pods=len(pods),
            outlier_pods=all_outliers,
            hot_pod_analysis=hot_pod_analysis,
            noisy_neighbor_analysis=noisy_neighbor_analysis,
            aggregated_severity_score=aggregated_score,
            aggregation_method='average',
            pod_consensus=pod_consensus,
            consistent_impact=consistent_impact
        )
