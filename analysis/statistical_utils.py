"""
Statistical utility functions for impact detection.

This module provides robust statistical methods for:
- Hypothesis testing
- Effect size calculation
- Baseline stability validation
- Change point detection
- Outlier detection
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
from scipy import stats
from scipy.stats import mannwhitneyu, ttest_ind, levene, kendalltau, variation
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)


def validate_baseline_stability(
    baseline_data: np.ndarray,
    cv_threshold: float = 0.5,
    trend_threshold: float = 0.3
) -> Dict:
    """
    Validate that baseline period is stable enough for comparison.

    A stable baseline should have:
    1. Low coefficient of variation (CV < threshold)
    2. No strong trend (|Kendall's tau| < threshold)

    Args:
        baseline_data: Time series data from baseline period
        cv_threshold: Maximum coefficient of variation for stability
        trend_threshold: Maximum absolute Kendall tau for trend detection

    Returns:
        Dictionary with:
        - is_stable: Boolean indicating if baseline is stable
        - cv: Coefficient of variation
        - trend_statistic: Kendall's tau correlation
        - reason: Explanation if unstable
    """
    if len(baseline_data) < 3:
        return {
            'is_stable': False,
            'reason': 'insufficient_data',
            'cv': None,
            'trend_statistic': None
        }

    # Remove NaN values
    clean_data = baseline_data[~np.isnan(baseline_data)]
    if len(clean_data) < 3:
        return {
            'is_stable': False,
            'reason': 'insufficient_valid_data',
            'cv': None,
            'trend_statistic': None
        }

    # Calculate coefficient of variation
    # Special case: if all values are identical (constant), CV is 0 (perfectly stable)
    try:
        std = np.std(clean_data)
        mean = np.mean(clean_data)

        if std == 0:
            # All values are constant - perfectly stable!
            cv = 0.0
        elif mean == 0:
            # Mean is 0 but has variance - this IS unstable
            cv = 999
        else:
            cv = variation(clean_data)
            if np.isnan(cv) or np.isinf(cv):
                cv = 999  # Very high variability
    except:
        cv = 999

    # Test for trend using Kendall's tau
    try:
        time_indices = np.arange(len(clean_data))
        trend_result = kendalltau(time_indices, clean_data)
        trend_stat = abs(trend_result.statistic)
        if np.isnan(trend_stat):
            trend_stat = 0
    except:
        trend_stat = 0

    # Determine stability
    is_stable = True
    reasons = []

    if cv > cv_threshold:
        is_stable = False
        reasons.append(f'high_variability (CV={cv:.2f} > {cv_threshold})')

    if trend_stat > trend_threshold:
        is_stable = False
        reasons.append(f'strong_trend (tau={trend_stat:.2f} > {trend_threshold})')

    return {
        'is_stable': is_stable,
        'cv': float(cv),
        'trend_statistic': float(trend_stat),
        'reason': '; '.join(reasons) if reasons else 'stable'
    }


def test_distribution_shift(
    before: np.ndarray,
    after: np.ndarray,
    alpha: float = 0.05,
    prefer_nonparametric: bool = True
) -> Dict:
    """
    Test if two distributions are significantly different.

    Uses Mann-Whitney U test (non-parametric) by default, as it's more robust
    to non-normal distributions. Falls back to t-test for normal distributions
    if prefer_nonparametric=False.

    Args:
        before: Baseline data
        after: Post-fault data
        alpha: Significance level
        prefer_nonparametric: Use Mann-Whitney U instead of t-test

    Returns:
        Dictionary with test results
    """
    # Clean data
    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    if len(before_clean) < 2 or len(after_clean) < 2:
        return {
            'significant': False,
            'p_value': 1.0,
            'test_used': 'insufficient_data',
            'statistic': 0.0
        }

    try:
        if prefer_nonparametric:
            # Mann-Whitney U test (non-parametric)
            # Tests if after distribution is greater than before
            statistic, p_value = mannwhitneyu(
                after_clean,
                before_clean,
                alternative='two-sided'
            )
            test_used = 'mann_whitney_u'
        else:
            # Check normality first
            if len(before_clean) >= 8 and len(after_clean) >= 8:
                _, p_norm_before = stats.shapiro(before_clean[:50])  # Limit for efficiency
                _, p_norm_after = stats.shapiro(after_clean[:50])
                is_normal = p_norm_before > 0.05 and p_norm_after > 0.05
            else:
                is_normal = False

            if is_normal:
                # Independent samples t-test
                statistic, p_value = ttest_ind(after_clean, before_clean)
                test_used = 't_test'
            else:
                # Fall back to Mann-Whitney U
                statistic, p_value = mannwhitneyu(
                    after_clean,
                    before_clean,
                    alternative='two-sided'
                )
                test_used = 'mann_whitney_u'

        return {
            'significant': p_value < alpha,
            'p_value': float(p_value),
            'test_used': test_used,
            'statistic': float(statistic)
        }

    except Exception as e:
        return {
            'significant': False,
            'p_value': 1.0,
            'test_used': 'failed',
            'statistic': 0.0,
            'error': str(e)
        }


def calculate_effect_size(before: np.ndarray, after: np.ndarray) -> float:
    """
    Calculate Cohen's d effect size.

    Effect size interpretation:
    - 0.2: Small effect
    - 0.5: Medium effect
    - 0.8: Large effect

    Args:
        before: Baseline data
        after: Post-fault data

    Returns:
        Cohen's d value (can be negative if after < before)
    """
    # Clean data
    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    if len(before_clean) < 2 or len(after_clean) < 2:
        return 0.0

    try:
        # Calculate means
        mean_before = np.mean(before_clean)
        mean_after = np.mean(after_clean)

        # Calculate pooled standard deviation
        std_before = np.std(before_clean, ddof=1)
        std_after = np.std(after_clean, ddof=1)

        n_before = len(before_clean)
        n_after = len(after_clean)

        # Pooled standard deviation
        pooled_std = np.sqrt(
            ((n_before - 1) * std_before**2 + (n_after - 1) * std_after**2) /
            (n_before + n_after - 2)
        )

        if pooled_std == 0:
            return 0.0

        # Cohen's d
        cohens_d = (mean_after - mean_before) / pooled_std

        return float(cohens_d)

    except:
        return 0.0


def categorize_effect_size(effect_size: float) -> str:
    """
    Categorize effect size magnitude.

    Args:
        effect_size: Cohen's d value

    Returns:
        Category: 'negligible', 'small', 'medium', 'large', 'very_large'
    """
    abs_effect = abs(effect_size)

    if abs_effect < 0.2:
        return 'negligible'
    elif abs_effect < 0.5:
        return 'small'
    elif abs_effect < 0.8:
        return 'medium'
    elif abs_effect < 1.2:
        return 'large'
    else:
        return 'very_large'


def test_variance_change(
    before: np.ndarray,
    after: np.ndarray,
    alpha: float = 0.05
) -> Dict:
    """
    Test if variance changed significantly between periods.

    Increased variance can indicate instability even if mean is unchanged.
    Uses Levene's test (robust to non-normality).

    Args:
        before: Baseline data
        after: Post-fault data
        alpha: Significance level

    Returns:
        Dictionary with test results
    """
    # Clean data
    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    if len(before_clean) < 3 or len(after_clean) < 3:
        return {
            'variance_changed': False,
            'variance_increased': False,
            'p_value': 1.0,
            'before_var': 0.0,
            'after_var': 0.0
        }

    try:
        # Levene's test for equality of variances
        statistic, p_value = levene(before_clean, after_clean)

        before_var = np.var(before_clean)
        after_var = np.var(after_clean)

        return {
            'variance_changed': p_value < alpha,
            'variance_increased': after_var > before_var,
            'p_value': float(p_value),
            'before_var': float(before_var),
            'after_var': float(after_var),
            'variance_ratio': float(after_var / before_var) if before_var > 0 else 0.0
        }

    except:
        return {
            'variance_changed': False,
            'variance_increased': False,
            'p_value': 1.0,
            'before_var': 0.0,
            'after_var': 0.0
        }


def calculate_robust_statistics(
    before: np.ndarray,
    after: np.ndarray
) -> Dict:
    """
    Calculate robust statistics (median, IQR) that are less sensitive to outliers.

    Args:
        before: Baseline data
        after: Post-fault data

    Returns:
        Dictionary with robust statistics for both periods
    """
    # Clean data
    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    result = {}

    if len(before_clean) > 0:
        result['before_median'] = float(np.median(before_clean))
        result['before_q25'] = float(np.percentile(before_clean, 25))
        result['before_q75'] = float(np.percentile(before_clean, 75))
        result['before_iqr'] = result['before_q75'] - result['before_q25']
    else:
        result['before_median'] = 0.0
        result['before_iqr'] = 0.0

    if len(after_clean) > 0:
        result['after_median'] = float(np.median(after_clean))
        result['after_q25'] = float(np.percentile(after_clean, 25))
        result['after_q75'] = float(np.percentile(after_clean, 75))
        result['after_iqr'] = result['after_q75'] - result['after_q25']
    else:
        result['after_median'] = 0.0
        result['after_iqr'] = 0.0

    # Calculate robust change metric (change in medians relative to baseline IQR)
    if result['before_iqr'] > 0:
        result['robust_change'] = (
            (result['after_median'] - result['before_median']) / result['before_iqr']
        )
    else:
        result['robust_change'] = 0.0

    return result


def detect_outliers(
    data: np.ndarray,
    iqr_multiplier: float = 3.0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect outliers using IQR method.

    Args:
        data: Input data
        iqr_multiplier: IQR multiplier for outlier bounds (default 3.0 for extreme outliers)

    Returns:
        Tuple of (cleaned_data, outlier_mask)
    """
    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 4:
        return clean_data, np.zeros(len(clean_data), dtype=bool)

    q25 = np.percentile(clean_data, 25)
    q75 = np.percentile(clean_data, 75)
    iqr = q75 - q25

    lower_bound = q25 - iqr_multiplier * iqr
    upper_bound = q75 + iqr_multiplier * iqr

    outlier_mask = (clean_data < lower_bound) | (clean_data > upper_bound)

    return clean_data[~outlier_mask], outlier_mask


def detect_changepoint_at_boundary(
    time_series: np.ndarray,
    boundary_index: int,
    tolerance: int = 5,
    penalty: int = 10
) -> bool:
    """
    Detect if there's a structural change point near the fault injection time.

    Uses the ruptures library for change point detection.

    Args:
        time_series: Complete time series (before + after)
        boundary_index: Index where fault was injected
        tolerance: How close changepoint must be to boundary (indices)
        penalty: Penalty parameter for changepoint detection (higher = fewer changepoints)

    Returns:
        True if changepoint detected near boundary
    """
    try:
        import ruptures as rpt
    except ImportError:
        # Ruptures not installed, skip change point detection
        return False

    if len(time_series) < 10:
        return False

    # Clean data
    clean_series = time_series[~np.isnan(time_series)]
    if len(clean_series) < 10:
        return False

    try:
        # Use Pelt algorithm with RBF kernel (works well for various change types)
        algo = rpt.Pelt(model='rbf').fit(clean_series)
        changepoints = algo.predict(pen=penalty)

        # Check if any changepoint is within tolerance of boundary
        for cp in changepoints:
            if abs(cp - boundary_index) <= tolerance:
                return True

        return False

    except Exception:
        # If change point detection fails, return False
        return False


def calculate_rate_from_counter(
    df: pd.DataFrame,
    value_column: str,
    time_column: str
) -> np.ndarray:
    """
    Calculate rate of change for counter metrics.

    Counters are cumulative, so we need to calculate the derivative.

    Args:
        df: DataFrame with counter data
        value_column: Column containing counter values
        time_column: Column containing timestamps

    Returns:
        Array of rates (value per time unit)
    """
    if len(df) < 2:
        return np.array([])

    df = df.sort_values(time_column)
    values = df[value_column].values
    times = df[time_column].values

    # Calculate rate: delta_value / delta_time
    rates = []
    for i in range(1, len(values)):
        delta_value = values[i] - values[i-1]
        delta_time = times[i] - times[i-1]

        if delta_time > 0 and delta_value >= 0:  # Counters should be monotonic
            rate = delta_value / delta_time
            rates.append(rate)

    return np.array(rates)


def determine_change_direction(before: np.ndarray, after: np.ndarray) -> str:
    """
    Determine the direction of change between two periods.

    Args:
        before: Baseline data
        after: Post-fault data

    Returns:
        'increase', 'decrease', or 'no_change'
    """
    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    if len(before_clean) == 0 or len(after_clean) == 0:
        return 'no_change'

    before_median = np.median(before_clean)
    after_median = np.median(after_clean)

    # Use robust comparison (median) with small threshold
    threshold = 0.05  # 5% change threshold
    pct_change = (after_median - before_median) / before_median if before_median > 0 else 0

    if pct_change > threshold:
        return 'increase'
    elif pct_change < -threshold:
        return 'decrease'
    else:
        return 'no_change'


def is_degradation_pattern(
    direction: str,
    expected_behavior: str
) -> bool:
    """
    Determine if the observed change matches expected degradation pattern.

    Args:
        direction: Observed direction ('increase', 'decrease', 'no_change')
        expected_behavior: Expected pattern ('increase_bad', 'decrease_bad', 'either_bad')

    Returns:
        True if change matches degradation pattern
    """
    if direction == 'no_change':
        return False

    if expected_behavior == 'increase_bad':
        return direction == 'increase'

    if expected_behavior == 'decrease_bad':
        return direction == 'decrease'

    if expected_behavior == 'either_bad':
        return direction in ['increase', 'decrease']

    return False


def compute_confidence_level(
    p_value: float,
    effect_size: float,
    n_before: int,
    n_after: int,
    min_samples: int = 10
) -> str:
    """
    Compute confidence level for a statistical test result.

    Args:
        p_value: P-value from statistical test
        effect_size: Cohen's d effect size
        n_before: Sample size in baseline period
        n_after: Sample size in post-fault period
        min_samples: Minimum samples required for medium confidence

    Returns:
        'high', 'medium', or 'low'
    """
    # Check sample sizes
    if n_before < min_samples or n_after < min_samples:
        return 'low'

    # Very significant and large effect
    if p_value < 0.01 and abs(effect_size) > 0.8:
        return 'high'

    # Significant with medium effect
    if p_value < 0.05 and abs(effect_size) > 0.5:
        return 'high'

    # Significant but small effect
    if p_value < 0.05 and abs(effect_size) > 0.2:
        return 'medium'

    # Borderline significance
    if p_value < 0.1:
        return 'medium'

    # Not significant
    return 'low'
