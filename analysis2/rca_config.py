"""
rca_config.py

Centralized configuration for RCA thresholds with statistical defaults.
Reduces brittleness by making thresholds explicit, configurable, and statistically grounded.
"""

from dataclasses import dataclass
from typing import Dict, Any
import numpy as np


@dataclass
class RCAThresholds:
    """
    Configurable thresholds for RCA detection.

    Design philosophy:
    - Use relative thresholds (percentiles, ratios) over absolute values
    - Make all thresholds explicit and configurable
    - Provide statistical justification for defaults
    """

    # === Network Partition Detection ===

    # Queue backlog growth (use effect size + percentile instead of absolute)
    queue_growth_min_effect_size: float = 3.0  # Cohen's d: "large" effect
    queue_growth_significance_level: float = 0.95  # Statistical significance

    # Was the consumer active? (percentile-based)
    consumer_activity_percentile: float = 0.5  # Must be above median baseline RPS

    # === Healthy Node Filtering ===

    # Pod coverage threshold (what fraction of pods must be degraded?)
    pod_coverage_threshold: float = 0.5  # Majority rule

    # Service-level symptom detection (relative to baseline)
    service_symptom_min_effect_size: float = 0.5  # Cohen's d: "medium" effect

    # External blame threshold (relative to caller count)
    guilt_ratio_threshold: float = 0.1  # At least 10% of callers blaming

    # Severity comparison (percentile-based)
    severity_comparison_percentile: float = 90  # Top 10% of all scores
    min_absolute_severity: float = 5.0  # But at least this to avoid noise

    # Signal strength ratios (relative comparisons)
    temporal_to_symptom_ratio: float = 2.0  # Temporal 2x stronger than symptoms
    trace_to_symptom_ratio: float = 3.0  # Traces 3x stronger than symptoms

    # === Zombie Pod Detection ===

    # Thread saturation (relative to limit)
    thread_saturation_threshold: float = 0.8  # 80% of max threads

    # Throughput comparison (effect size based)
    throughput_drop_min_effect_size: float = 3.0  # Large effect size
    throughput_near_zero_percentile: float = 10  # Below 10th percentile = near-zero
    throughput_near_zero_absolute: float = 0.1  # RPS < 0.1 = near-zero

    # Activity baseline (percentile-based)
    was_active_percentile: float = 50  # Above median baseline = active
    was_active_absolute: float = 1.0  # RPS > 1.0 = active

    # === Self-Health Detection ===

    # Resource saturation
    resource_saturation_threshold: float = 0.9  # 90% of resource limit

    # Effect sizes for degradation detection
    min_effect_size_small: float = 0.5  # Cohen's d: small-medium
    min_effect_size_medium: float = 1.0  # Cohen's d: medium
    min_effect_size_large: float = 2.0  # Cohen's d: large
    min_effect_size_very_large: float = 3.0  # Cohen's d: very large

    # Error rate thresholds
    error_rate_minor: float = 0.05  # 5% errors = minor issue
    error_rate_moderate: float = 0.1  # 10% errors = moderate issue
    error_rate_severe: float = 0.2  # 20% errors = severe issue

    # === Error Proxy Detection (for components without error_rate) ===

    # Cache hit rate degradation (relative drop)
    cache_hit_rate_drop_threshold: float = 0.2  # 20% drop (e.g., 95% -> 75%)
    cache_min_baseline_percentile: float = 10  # Must have >10th percentile traffic

    # Database query errors (effect size based)
    db_error_min_effect_size: float = 1.0  # Cohen's d: medium effect
    db_min_baseline_percentile: float = 10  # Must have >10th percentile traffic

    # Queue timeout failures (effect size + primary symptom check)
    # CRITICAL: Only use if queue itself is faulty, not just buffering
    queue_timeout_min_effect_size: float = 1.0  # Cohen's d: medium effect
    queue_min_baseline_percentile: float = 10  # Must have >10th percentile traffic

    # External service errors (effect size based)
    # Lower threshold since external failures are critical
    external_error_min_effect_size: float = 0.8  # Cohen's d: small-medium
    external_min_baseline_percentile: float = 10  # Must have >10th percentile traffic

    # Error proxy value: When degradation detected, treat as this error rate
    error_proxy_value: float = 0.5  # 50% error rate equivalent

    def __init__(self, overrides: Dict[str, Any] = None):
        """
        Create threshold config with optional overrides.

        Args:
            overrides: Dictionary of threshold names to override values
        """
        if overrides:
            for key, value in overrides.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def get_dynamic_threshold(self,
                              baseline: np.ndarray,
                              metric_name: str,
                              percentile: float = None) -> float:
        """
        Calculate dynamic threshold from baseline distribution.

        Args:
            baseline: Baseline metric values
            metric_name: Name of metric (for context)
            percentile: Which percentile to use (default depends on metric)

        Returns:
            Threshold value based on baseline statistics
        """
        if len(baseline) == 0:
            return 0.0

        # Use appropriate percentile for different metrics
        if percentile is None:
            if 'rps' in metric_name or 'throughput' in metric_name:
                percentile = self.was_active_percentile
            elif 'severity' in metric_name or 'score' in metric_name:
                percentile = self.severity_comparison_percentile
            else:
                percentile = 50  # Default to median

        return np.percentile(baseline, percentile)

    def is_near_zero(self, current: np.ndarray, baseline: np.ndarray) -> bool:
        """
        Check if current value is near-zero using percentile comparison.

        More robust than absolute threshold.
        """
        if len(current) == 0 or len(baseline) == 0:
            return False

        curr_median = np.median(current)
        baseline_threshold = np.percentile(baseline, self.throughput_near_zero_percentile)

        return curr_median < baseline_threshold

    def has_large_effect(self, baseline: np.ndarray, current: np.ndarray,
                        metric_type: str = 'queue') -> bool:
        """
        Check if change from baseline to current has large effect size.

        Uses Cohen's d for normal cases, but handles special cases:
        - Zero-variance baseline (e.g., queue always empty)
        - Absolute growth when relative doesn't apply

        Args:
            baseline: Baseline metric values
            current: Current metric values
            metric_type: Type of metric ('queue', 'latency', etc.)
        """
        if len(baseline) == 0 or len(current) == 0:
            return False

        baseline_mean = np.mean(baseline)
        current_mean = np.mean(current)

        # Special case: Zero or near-zero baseline (e.g., queue always empty)
        # Use absolute growth threshold instead of Cohen's d
        baseline_std = np.std(baseline)
        if baseline_mean < 1.0 and baseline_std < 1.0:
            if metric_type == 'queue':
                # For queues starting near-zero: any substantial backlog is significant
                # Pragmatic threshold: mean > 10 messages (adjustable via min)
                min_significant_backlog = 10.0
                return current_mean > min_significant_backlog
            else:
                # For other metrics: use simple absolute threshold
                return abs(current_mean - baseline_mean) > 1.0

        # Normal case: Use Cohen's d
        pooled_std = np.sqrt((baseline_std**2 + np.std(current)**2) / 2)

        if pooled_std < 1e-6:  # Both have zero variance
            return abs(current_mean - baseline_mean) > 0.1

        cohens_d = abs(current_mean - baseline_mean) / pooled_std
        return cohens_d >= self.queue_growth_min_effect_size


# Global default configuration
DEFAULT_THRESHOLDS = RCAThresholds()


def get_thresholds(overrides: Dict[str, Any] = None) -> RCAThresholds:
    """
    Get threshold configuration with optional overrides.

    Example:
        config = get_thresholds({'pod_coverage_threshold': 0.4})
    """
    return RCAThresholds(overrides)
