"""
Configuration for impact analysis system.

This module contains all thresholds, parameters, and settings for the
statistical impact detection system. Centralizing these allows for easy
tuning and experimentation.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class StatisticalConfig:
    """Statistical test parameters."""

    # Significance level for hypothesis tests (p-value threshold)
    alpha: float = 0.05

    # Minimum effect size (Cohen's d) to consider meaningful
    # 0.2 = small, 0.5 = medium, 0.8 = large
    min_effect_size: float = 0.3

    # Baseline stability thresholds
    baseline_cv_max: float = 0.5  # Max coefficient of variation for stable baseline
    baseline_trend_max: float = 0.3  # Max Kendall tau correlation for trend detection

    # Data requirements
    min_samples_before: int = 10  # Minimum samples in baseline period
    min_samples_after: int = 10   # Minimum samples in fault period
    max_missing_pct: float = 0.3  # Max % of missing/null values allowed

    # Use robust statistics (median/IQR) instead of mean/std for noisy metrics
    use_robust_stats: bool = True

    # Outlier detection threshold (IQR multiplier)
    outlier_iqr_multiplier: float = 3.0

    # Change point detection sensitivity (penalty parameter)
    changepoint_penalty: int = 10


@dataclass
class MetricWeights:
    """
    Importance weights for different metric types.

    Higher weights = more important for determining impact.
    Range: 0.0 to 1.0
    """

    # Critical: Direct user-facing impact
    error_metrics: float = 1.0
    rejection_metrics: float = 1.0
    timeout_metrics: float = 1.0

    # High: Performance degradation
    latency_p99: float = 0.9
    latency_p90: float = 0.7
    latency_p50: float = 0.5
    duration_metrics: float = 0.8

    # Medium: Resource exhaustion indicators
    queue_depth_metrics: float = 0.7
    pool_metrics: float = 0.6
    thread_metrics: float = 0.6

    # Medium: Throughput/capacity
    throughput_metrics: float = 0.6
    request_count_metrics: float = 0.5

    # Lower: Resource usage (can be high without immediate impact)
    cpu_metrics: float = 0.4
    memory_metrics: float = 0.4

    # Lower: Cache metrics (degradation may not indicate failure)
    cache_metrics: float = 0.3
    hit_rate_metrics: float = 0.4

    # Default for unknown metrics
    default_weight: float = 0.5

    def get_weight(self, metric_name: str) -> float:
        """Get weight for a specific metric by pattern matching."""
        metric_lower = metric_name.lower()

        # Critical metrics
        if 'error' in metric_lower:
            return self.error_metrics
        if 'reject' in metric_lower or 'refused' in metric_lower:
            return self.rejection_metrics
        if 'timeout' in metric_lower:
            return self.timeout_metrics

        # Latency/duration
        if 'p99' in metric_lower:
            return self.latency_p99
        if 'p90' in metric_lower:
            return self.latency_p90
        if 'p50' in metric_lower or 'median' in metric_lower:
            return self.latency_p50
        if 'latency' in metric_lower or 'duration' in metric_lower:
            return self.duration_metrics

        # Resource exhaustion
        if 'queue' in metric_lower:
            return self.queue_depth_metrics
        if 'pool' in metric_lower:
            return self.pool_metrics
        if 'thread' in metric_lower:
            return self.thread_metrics

        # Throughput
        if 'throughput' in metric_lower:
            return self.throughput_metrics
        if 'requests' in metric_lower or 'rps' in metric_lower:
            return self.request_count_metrics

        # Resources
        if 'cpu' in metric_lower:
            return self.cpu_metrics
        if 'memory' in metric_lower or 'mem' in metric_lower:
            return self.memory_metrics

        # Cache
        if 'cache' in metric_lower:
            return self.cache_metrics
        if 'hit_rate' in metric_lower or 'hit.rate' in metric_lower:
            return self.hit_rate_metrics

        return self.default_weight


@dataclass
class MetricBehaviorConfig:
    """
    Defines expected behavior of metrics during degradation.

    This helps the analyzer know which direction of change indicates impact:
    - increase_bad: Metric increases when degraded (latency, errors)
    - decrease_bad: Metric decreases when degraded (throughput, hit rate)
    - either_bad: Change in either direction indicates issues (variance metrics)
    """

    increase_bad_patterns: List[str] = field(default_factory=lambda: [
        'latency', 'duration', 'error', 'reject', 'refused', 'timeout',
        'queue', 'wait', 'retry', 'retransmit', 'age', 'eviction',
        'gc_pause', 'pause', 'blocked', 'dropped', 'loss', 'backlog'
    ])

    decrease_bad_patterns: List[str] = field(default_factory=lambda: [
        'throughput', 'requests', 'rps', 'qps', 'tps',
        'hit_rate', 'success_rate', 'availability',
        'active', 'healthy', 'capacity'
    ])

    either_bad_patterns: List[str] = field(default_factory=lambda: [
        'jitter', 'variance', 'stddev', 'coefficient'
    ])

    def get_expected_behavior(self, metric_name: str) -> str:
        """
        Determine expected behavior for a metric.

        Returns:
            'increase_bad', 'decrease_bad', 'either_bad', or 'stable'
        """
        metric_lower = metric_name.lower()

        if any(pattern in metric_lower for pattern in self.increase_bad_patterns):
            return 'increase_bad'

        if any(pattern in metric_lower for pattern in self.decrease_bad_patterns):
            return 'decrease_bad'

        if any(pattern in metric_lower for pattern in self.either_bad_patterns):
            return 'either_bad'

        # Default: assume increase is bad (conservative)
        return 'increase_bad'


@dataclass
class ImpactScoringConfig:
    """
    Configuration for aggregating multiple signals into impact score.

    Impact score: 0.0 = definitely impacted, 1.0 = definitely healthy
    """

    # Thresholds for classification
    impacted_threshold: float = 0.3  # Below this = impacted
    healthy_threshold: float = 0.7   # Above this = healthy
    # Between thresholds = uncertain/borderline

    # Confidence level multipliers
    high_confidence_multiplier: float = 1.0
    medium_confidence_multiplier: float = 0.7
    low_confidence_multiplier: float = 0.3

    # Multi-metric aggregation
    require_multiple_metrics: bool = True  # Require >1 metric for high confidence
    min_metrics_for_high_confidence: int = 3

    # Special handling
    root_cause_override: bool = True  # Always mark root cause as impacted
    no_metrics_default_score: float = 0.5  # Score when no metrics available


@dataclass
class ChangeDetectionConfig:
    """Configuration for change point detection algorithms."""

    enabled: bool = True

    # Ruptures library parameters
    model: str = 'rbf'  # 'rbf', 'l1', 'l2', 'normal', 'ar'
    penalty: int = 10  # Higher = fewer change points detected

    # Tolerance for matching fault injection time (simulation seconds)
    fault_time_tolerance: int = 5

    # Minimum magnitude of change to consider significant
    min_change_magnitude: float = 0.2  # As fraction of baseline


@dataclass
class ImpactAnalysisConfig:
    """Master configuration for impact analysis."""

    statistical: StatisticalConfig = field(default_factory=StatisticalConfig)
    metric_weights: MetricWeights = field(default_factory=MetricWeights)
    metric_behavior: MetricBehaviorConfig = field(default_factory=MetricBehaviorConfig)
    scoring: ImpactScoringConfig = field(default_factory=ImpactScoringConfig)
    change_detection: ChangeDetectionConfig = field(default_factory=ChangeDetectionConfig)

    # Global settings
    verbose: bool = False  # Enable detailed logging
    parallel_processing: bool = False  # Process nodes in parallel (for large graphs)

    def to_dict(self) -> Dict:
        """Convert config to dictionary for serialization."""
        return {
            'statistical': self.statistical.__dict__,
            'metric_weights': self.metric_weights.__dict__,
            'metric_behavior': {
                'increase_bad_patterns': self.metric_behavior.increase_bad_patterns,
                'decrease_bad_patterns': self.metric_behavior.decrease_bad_patterns,
                'either_bad_patterns': self.metric_behavior.either_bad_patterns,
            },
            'scoring': self.scoring.__dict__,
            'change_detection': self.change_detection.__dict__,
            'verbose': self.verbose,
            'parallel_processing': self.parallel_processing,
        }


# Default configuration instance
DEFAULT_CONFIG = ImpactAnalysisConfig()


def get_config() -> ImpactAnalysisConfig:
    """Get the default configuration."""
    return DEFAULT_CONFIG


def create_custom_config(**kwargs) -> ImpactAnalysisConfig:
    """
    Create a custom configuration by overriding defaults.

    Example:
        config = create_custom_config(
            statistical={'alpha': 0.01, 'min_effect_size': 0.5},
            scoring={'impacted_threshold': 0.2}
        )
    """
    config = ImpactAnalysisConfig()

    if 'statistical' in kwargs:
        for key, value in kwargs['statistical'].items():
            setattr(config.statistical, key, value)

    if 'metric_weights' in kwargs:
        for key, value in kwargs['metric_weights'].items():
            setattr(config.metric_weights, key, value)

    if 'metric_behavior' in kwargs:
        for key, value in kwargs['metric_behavior'].items():
            setattr(config.metric_behavior, key, value)

    if 'scoring' in kwargs:
        for key, value in kwargs['scoring'].items():
            setattr(config.scoring, key, value)

    if 'change_detection' in kwargs:
        for key, value in kwargs['change_detection'].items():
            setattr(config.change_detection, key, value)

    if 'verbose' in kwargs:
        config.verbose = kwargs['verbose']

    if 'parallel_processing' in kwargs:
        config.parallel_processing = kwargs['parallel_processing']

    return config
