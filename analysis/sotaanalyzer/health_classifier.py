"""
Health Classification Module

Nuanced health classification for nodes based on:
- Metric type and criticality
- Severity scores and patterns
- Impact distribution across metrics
- Context-aware thresholds
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class HealthClassification:
    """Health classification result for a node."""
    node_id: str
    health_status: str  # 'HEALTHY', 'DEGRADED', 'IMPACTED', 'CRITICAL'
    confidence: float  # 0.0-1.0
    reasoning: str

    # Detailed breakdown
    overall_severity_score: float
    critical_metrics_count: int
    high_metrics_count: int
    impacted_metrics_count: int
    total_metrics: int

    # Key indicators
    has_error_increase: bool
    has_latency_degradation: bool
    has_saturation: bool
    has_resource_exhaustion: bool

    def to_dict(self) -> Dict:
        return asdict(self)


class HealthClassifier:
    """
    Classifies node health using nuanced, context-aware thresholds.

    Philosophy:
    - A single critical error metric can make a node CRITICAL
    - Multiple minor impacts can accumulate to IMPACTED
    - Low severity + few metrics affected = DEGRADED
    - Very low impact = HEALTHY
    """

    def __init__(self):
        # Base thresholds (can be overridden)
        self.severity_thresholds = {
            'HEALTHY': 0.05,      # < 0.05: essentially no impact
            'DEGRADED': 0.15,     # 0.05-0.15: minor degradation
            'IMPACTED': 0.40,     # 0.15-0.40: significant impact
            'CRITICAL': 0.40      # >= 0.40: critical impact
        }

    def classify_node_health(
        self,
        node_id: str,
        overall_severity_score: float,
        metrics_by_severity: Dict[str, int],  # severity_class -> count
        ranked_metrics: List[Dict],
        total_metrics: int
    ) -> HealthClassification:
        """
        Classify node health with nuanced logic.

        Args:
            node_id: Node identifier
            overall_severity_score: Overall severity score (0-1)
            metrics_by_severity: Count of metrics by severity class
            ranked_metrics: List of metric impact details
            total_metrics: Total number of metrics analyzed

        Returns:
            HealthClassification with detailed reasoning
        """
        critical_count = metrics_by_severity.get('CRITICAL', 0)
        high_count = metrics_by_severity.get('HIGH', 0)
        medium_count = metrics_by_severity.get('MEDIUM', 0)
        low_count = metrics_by_severity.get('LOW', 0)

        impacted_count = critical_count + high_count + medium_count

        # Analyze metric types
        has_error_increase = self._check_metric_type(ranked_metrics, 'error')
        has_latency_degradation = self._check_metric_type(ranked_metrics, 'latency')
        has_saturation = self._check_metric_type(ranked_metrics, 'saturation')
        has_resource_exhaustion = self._check_metric_type(ranked_metrics, 'resource')

        # Classification logic
        health_status, confidence, reasoning = self._determine_health_status(
            overall_severity_score=overall_severity_score,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            impacted_count=impacted_count,
            total_metrics=total_metrics,
            has_error_increase=has_error_increase,
            has_latency_degradation=has_latency_degradation,
            has_saturation=has_saturation,
            has_resource_exhaustion=has_resource_exhaustion
        )

        return HealthClassification(
            node_id=node_id,
            health_status=health_status,
            confidence=confidence,
            reasoning=reasoning,
            overall_severity_score=overall_severity_score,
            critical_metrics_count=critical_count,
            high_metrics_count=high_count,
            impacted_metrics_count=impacted_count,
            total_metrics=total_metrics,
            has_error_increase=has_error_increase,
            has_latency_degradation=has_latency_degradation,
            has_saturation=has_saturation,
            has_resource_exhaustion=has_resource_exhaustion
        )

    def _check_metric_type(self, ranked_metrics: List[Dict], metric_category: str) -> bool:
        """
        Check if any top metrics match the category and show significant impact.

        Args:
            ranked_metrics: List of metric details
            metric_category: 'error', 'latency', 'saturation', 'resource'

        Returns:
            True if category has significant impact
        """
        if not ranked_metrics:
            return False

        # Check top 3 metrics
        for metric_info in ranked_metrics[:3]:
            metric_name = metric_info.get('metric_name', '').lower()
            severity_class = metric_info.get('severity_class', 'NEGLIGIBLE')

            # Must be at least MEDIUM severity
            if severity_class not in ['CRITICAL', 'HIGH', 'MEDIUM']:
                continue

            # Check category match
            if metric_category == 'error':
                if any(kw in metric_name for kw in ['error', 'fail', 'reject', 'timeout']):
                    return True
            elif metric_category == 'latency':
                if any(kw in metric_name for kw in ['latency', 'duration', 'p99', 'p95']):
                    return True
            elif metric_category == 'saturation':
                if any(kw in metric_name for kw in ['queue', 'pool', 'active', 'utilization']):
                    return True
            elif metric_category == 'resource':
                if any(kw in metric_name for kw in ['cpu', 'memory', 'disk', 'network']):
                    return True

        return False

    def _determine_health_status(
        self,
        overall_severity_score: float,
        critical_count: int,
        high_count: int,
        medium_count: int,
        impacted_count: int,
        total_metrics: int,
        has_error_increase: bool,
        has_latency_degradation: bool,
        has_saturation: bool,
        has_resource_exhaustion: bool
    ) -> tuple[str, float, str]:
        """
        Determine health status using nuanced rules.

        Returns:
            (health_status, confidence, reasoning)
        """
        # Rule 1: Critical error metrics → CRITICAL
        if critical_count > 0 and has_error_increase:
            return (
                'CRITICAL',
                0.95,
                f"Critical error metrics detected ({critical_count} metrics)"
            )

        # Rule 2: Multiple critical metrics → CRITICAL
        if critical_count >= 2:
            return (
                'CRITICAL',
                0.90,
                f"Multiple critical metrics ({critical_count} critical)"
            )

        # Rule 3: High severity score with errors → CRITICAL
        if overall_severity_score >= 0.6 and has_error_increase:
            return (
                'CRITICAL',
                0.85,
                f"High severity ({overall_severity_score:.2f}) with error increase"
            )

        # Rule 4: Very high severity → CRITICAL
        if overall_severity_score >= 0.7:
            return (
                'CRITICAL',
                0.85,
                f"Very high severity score ({overall_severity_score:.2f})"
            )

        # Rule 5: Multiple high-severity metrics → IMPACTED
        if high_count >= 2 or (critical_count >= 1 and high_count >= 1):
            return (
                'IMPACTED',
                0.80,
                f"Multiple high-severity metrics ({critical_count} critical, {high_count} high)"
            )

        # Rule 6: Moderate severity with multiple impacted metrics → IMPACTED
        if overall_severity_score >= 0.3 and impacted_count >= 3:
            return (
                'IMPACTED',
                0.75,
                f"Moderate severity ({overall_severity_score:.2f}) affecting {impacted_count} metrics"
            )

        # Rule 7: Significant latency or saturation → IMPACTED
        if overall_severity_score >= 0.25 and (has_latency_degradation or has_saturation):
            return (
                'IMPACTED',
                0.70,
                f"Latency or saturation issues (severity: {overall_severity_score:.2f})"
            )

        # Rule 8: Low-moderate severity → DEGRADED
        if overall_severity_score >= 0.1 or impacted_count >= 1:
            impact_fraction = impacted_count / total_metrics if total_metrics > 0 else 0

            if impact_fraction >= 0.3:
                # Many metrics affected but low severity
                return (
                    'DEGRADED',
                    0.70,
                    f"Widespread minor impact ({impact_fraction*100:.0f}% of metrics)"
                )
            else:
                # Few metrics affected
                return (
                    'DEGRADED',
                    0.65,
                    f"Minor impact detected ({impacted_count} metrics, severity: {overall_severity_score:.2f})"
                )

        # Rule 9: Minimal impact → HEALTHY
        if overall_severity_score < 0.05:
            return (
                'HEALTHY',
                0.90,
                f"No significant impact (severity: {overall_severity_score:.3f})"
            )

        # Rule 10: Default (edge cases) → HEALTHY with low confidence
        return (
            'HEALTHY',
            0.50,
            f"Minimal impact detected (severity: {overall_severity_score:.3f})"
        )

    def get_healthy_nodes(
        self,
        node_classifications: List[HealthClassification]
    ) -> List[str]:
        """
        Get list of healthy node IDs.

        Args:
            node_classifications: List of HealthClassification objects

        Returns:
            List of node IDs classified as HEALTHY
        """
        return [
            nc.node_id
            for nc in node_classifications
            if nc.health_status == 'HEALTHY'
        ]

    def get_impacted_nodes(
        self,
        node_classifications: List[HealthClassification],
        min_status: str = 'DEGRADED'
    ) -> List[str]:
        """
        Get list of impacted node IDs.

        Args:
            node_classifications: List of HealthClassification objects
            min_status: Minimum status to consider as impacted (DEGRADED, IMPACTED, CRITICAL)

        Returns:
            List of node IDs with at least min_status
        """
        status_hierarchy = ['HEALTHY', 'DEGRADED', 'IMPACTED', 'CRITICAL']
        min_level = status_hierarchy.index(min_status)

        return [
            nc.node_id
            for nc in node_classifications
            if status_hierarchy.index(nc.health_status) >= min_level
        ]
