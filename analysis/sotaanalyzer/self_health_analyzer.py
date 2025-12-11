"""
Self-Health Analyzer

Distinguishes between self-degradation (internal issues) and dependency-degradation
(issues caused by downstream services).

This is critical for identifying root cause service nodes that have internal faults
but also impact their dependencies.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SelfHealthAnalysis:
    """Analysis of a node's self-health vs dependency-health."""
    node_id: str

    # Self metrics (internal health)
    has_self_degradation: bool
    self_cpu_increase: float
    self_memory_increase: float
    self_thread_queue_buildup: float
    self_latency_increase: float  # Excluding dependency latency
    self_error_increase: float    # Excluding dependency errors

    # Dependency metrics (downstream health)
    has_dependency_degradation: bool
    dependency_latency_increase: float
    dependency_error_increase: float

    # Resource exhaustion indicators
    has_resource_exhaustion: bool
    resource_exhaustion_type: Optional[str]  # 'cpu', 'memory', 'threads', 'mixed'

    # Classification
    is_likely_root_cause: bool  # True if has self-degradation
    is_likely_victim: bool       # True if only dependency-degradation

    # Supporting evidence
    self_degradation_score: float  # 0-1: how strong is self degradation
    dependency_degradation_score: float  # 0-1: how strong is dependency degradation

    reasoning: str

    def to_dict(self) -> Dict:
        return {
            'node_id': self.node_id,
            'has_self_degradation': self.has_self_degradation,
            'self_cpu_increase': self.self_cpu_increase,
            'self_memory_increase': self.self_memory_increase,
            'self_thread_queue_buildup': self.self_thread_queue_buildup,
            'self_latency_increase': self.self_latency_increase,
            'self_error_increase': self.self_error_increase,
            'has_dependency_degradation': self.has_dependency_degradation,
            'dependency_latency_increase': self.dependency_latency_increase,
            'dependency_error_increase': self.dependency_error_increase,
            'has_resource_exhaustion': self.has_resource_exhaustion,
            'resource_exhaustion_type': self.resource_exhaustion_type,
            'is_likely_root_cause': self.is_likely_root_cause,
            'is_likely_victim': self.is_likely_victim,
            'self_degradation_score': self.self_degradation_score,
            'dependency_degradation_score': self.dependency_degradation_score,
            'reasoning': self.reasoning
        }


class SelfHealthAnalyzer:
    """
    Analyzes node health to distinguish self-degradation from dependency-degradation.

    Key insight: Root cause nodes show INTERNAL health degradation, not just
    downstream issues.
    """

    # Metric categorization (using flexible keywords for partial matching)
    SELF_RESOURCE_METRICS = [
        'cpu',  # Matches: cpu_utilization, container.cpu.utilization, etc.
        'memory',  # Matches: memory_utilization, memory.usage, etc.
        'thread',  # Matches: thread_pool_active_threads, thread_pool.threads.active
        'queue'   # Matches: thread_pool_queue_size, thread_pool.queue.depth
    ]

    SELF_LATENCY_METRICS = [
        'latency',  # Generic latency (but NOT dependency.latency)
        'duration',
        'response_time'
    ]

    SELF_ERROR_METRICS = [
        'error_rate',  # NOT dependency errors
        'failure_rate',  # NOT dependency failures
        'internal_error'
    ]

    DEPENDENCY_LATENCY_METRICS = [
        'dependency.latency',
        'dependency_latency',
        'outgoing.latency',
        'outgoing_request_latency'
    ]

    DEPENDENCY_ERROR_METRICS = [
        'dependency.error',
        'dependency_error',
        'outgoing.error',
        'outgoing_request_error'
    ]

    # Thresholds
    RESOURCE_EXHAUSTION_THRESHOLD = 0.8  # 80% utilization
    SIGNIFICANT_INCREASE_THRESHOLD = 0.3  # 30% increase
    SEVERE_INCREASE_THRESHOLD = 0.5       # 50% increase

    def analyze_node_self_health(
        self,
        node_id: str,
        ranked_metrics: List[Dict],
        node_type: str = 'Service'
    ) -> SelfHealthAnalysis:
        """
        Analyze a node's self-health vs dependency-health.

        Args:
            node_id: Node identifier
            ranked_metrics: List of metric changes with baseline/fault values
            node_type: Type of node (Service, Database, etc.)

        Returns:
            SelfHealthAnalysis with detailed breakdown
        """
        # Categorize metrics (exclude dependency keywords when looking for self metrics)
        dependency_keywords = ['dependency', 'outgoing', 'downstream']

        self_cpu = self._find_metric_change(ranked_metrics, ['cpu'], exclude_metrics=dependency_keywords)
        self_memory = self._find_metric_change(ranked_metrics, ['memory'], exclude_metrics=dependency_keywords)
        self_threads = self._find_metric_change(ranked_metrics, ['thread', 'queue'], exclude_metrics=dependency_keywords)
        self_latency = self._find_metric_change(ranked_metrics, self.SELF_LATENCY_METRICS, exclude_metrics=dependency_keywords)
        self_errors = self._find_metric_change(ranked_metrics, self.SELF_ERROR_METRICS, exclude_metrics=dependency_keywords)

        dep_latency = self._find_metric_change(ranked_metrics, self.DEPENDENCY_LATENCY_METRICS)
        dep_errors = self._find_metric_change(ranked_metrics, self.DEPENDENCY_ERROR_METRICS)

        # Check for resource exhaustion
        has_resource_exhaustion, resource_type = self._check_resource_exhaustion(
            self_cpu, self_memory, self_threads
        )

        # Compute self degradation score
        self_degradation_score = self._compute_self_degradation_score(
            self_cpu, self_memory, self_threads, self_latency, self_errors
        )

        # Compute dependency degradation score
        dep_degradation_score = self._compute_dependency_degradation_score(
            dep_latency, dep_errors
        )

        # Classification
        has_self_degradation = self_degradation_score > 0.3
        has_dependency_degradation = dep_degradation_score > 0.3

        # Root cause likelihood:
        # - Root cause: has self-degradation (with or without dependency issues)
        # - Victim: only has dependency-degradation, no self issues
        is_likely_root_cause = has_self_degradation
        is_likely_victim = has_dependency_degradation and not has_self_degradation

        # Build reasoning
        reasoning = self._build_reasoning(
            has_self_degradation,
            has_dependency_degradation,
            has_resource_exhaustion,
            resource_type,
            self_degradation_score,
            dep_degradation_score
        )

        return SelfHealthAnalysis(
            node_id=node_id,
            has_self_degradation=has_self_degradation,
            self_cpu_increase=self_cpu,
            self_memory_increase=self_memory,
            self_thread_queue_buildup=self_threads,
            self_latency_increase=self_latency,
            self_error_increase=self_errors,
            has_dependency_degradation=has_dependency_degradation,
            dependency_latency_increase=dep_latency,
            dependency_error_increase=dep_errors,
            has_resource_exhaustion=has_resource_exhaustion,
            resource_exhaustion_type=resource_type,
            is_likely_root_cause=is_likely_root_cause,
            is_likely_victim=is_likely_victim,
            self_degradation_score=self_degradation_score,
            dependency_degradation_score=dep_degradation_score,
            reasoning=reasoning
        )

    def _find_metric_change(
        self,
        ranked_metrics: List[Dict],
        target_metrics: List[str],
        exclude_metrics: Optional[List[str]] = None
    ) -> float:
        """
        Find the maximum relative change for any metric in the target list.

        Args:
            ranked_metrics: List of metrics with changes
            target_metrics: Keywords to match (e.g., 'cpu', 'memory')
            exclude_metrics: Keywords to exclude (e.g., 'dependency', 'outgoing')

        Returns:
            Relative increase (0-1+) or 0 if not found.
        """
        max_change = 0.0
        exclude_metrics = exclude_metrics or []

        for metric in ranked_metrics:
            metric_name = metric.get('metric_name', '').lower()

            # Skip if metric matches exclusion keywords
            if any(excl.lower() in metric_name for excl in exclude_metrics):
                continue

            # Check if this metric matches any target
            if any(target.lower() in metric_name for target in target_metrics):
                baseline = metric.get('baseline_mean', 0)
                fault = metric.get('fault_mean', 0)

                if baseline > 0:
                    relative_change = (fault - baseline) / baseline
                    max_change = max(max_change, relative_change)
                elif fault > baseline:
                    # If baseline is 0 but fault is not, this is a significant change
                    max_change = max(max_change, 1.0)

        return max_change

    def _check_resource_exhaustion(
        self,
        cpu_increase: float,
        memory_increase: float,
        thread_increase: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if node shows resource exhaustion.

        Returns (has_exhaustion, exhaustion_type)
        """
        exhaustion_types = []

        # Check each resource (increases above 80% baseline are concerning)
        if cpu_increase >= self.RESOURCE_EXHAUSTION_THRESHOLD:
            exhaustion_types.append('cpu')

        if memory_increase >= self.RESOURCE_EXHAUSTION_THRESHOLD:
            exhaustion_types.append('memory')

        if thread_increase >= self.RESOURCE_EXHAUSTION_THRESHOLD:
            exhaustion_types.append('threads')

        if exhaustion_types:
            if len(exhaustion_types) > 1:
                return True, 'mixed'
            else:
                return True, exhaustion_types[0]

        return False, None

    def _compute_self_degradation_score(
        self,
        cpu: float,
        memory: float,
        threads: float,
        latency: float,
        errors: float
    ) -> float:
        """
        Compute aggregate self-degradation score (0-1).

        Weights:
        - Resource exhaustion: 60% (increased from 40% - primary indicator)
        - Self latency: 20%
        - Self errors: 20%

        Resource exhaustion (CPU/memory/threads) is the PRIMARY indicator of
        internal faults like memory pressure, CPU exhaustion, etc.
        """
        # Resource score (max of cpu, memory, threads)
        resource_score = max(cpu, memory, threads)

        # Normalize to 0-1
        # FIXED: Cap at 1.0x (100%) for resource metrics - any 100% increase is critical
        # For memory pressure faults, 100% memory increase should be score 1.0
        resource_score = min(1.0, resource_score)
        # Keep /2.0 for latency/errors as they can vary more widely
        latency_score = min(1.0, latency / 2.0)
        error_score = min(1.0, errors / 2.0)

        # Weighted combination - resources dominate (60%)
        return (
            resource_score * 0.6 +
            latency_score * 0.2 +
            error_score * 0.2
        )

    def _compute_dependency_degradation_score(
        self,
        dep_latency: float,
        dep_errors: float
    ) -> float:
        """
        Compute aggregate dependency-degradation score (0-1).
        """
        # Normalize to 0-1
        latency_score = min(1.0, dep_latency / 2.0)
        error_score = min(1.0, dep_errors / 2.0)

        # Equal weight
        return (latency_score + error_score) / 2.0

    def _build_reasoning(
        self,
        has_self_deg: bool,
        has_dep_deg: bool,
        has_resource_exhaustion: bool,
        resource_type: Optional[str],
        self_score: float,
        dep_score: float
    ) -> str:
        """Build human-readable reasoning."""
        reasons = []

        if has_resource_exhaustion:
            reasons.append(f"{resource_type} exhaustion detected")

        if has_self_deg:
            reasons.append(f"self-degradation (score: {self_score:.2f})")

        if has_dep_deg:
            reasons.append(f"dependency issues (score: {dep_score:.2f})")

        if not has_self_deg and has_dep_deg:
            reasons.append("likely victim (only downstream issues)")
        elif has_self_deg:
            reasons.append("likely root cause (internal issues)")

        return "; ".join(reasons) if reasons else "no significant degradation"
