"""
statistical_utils.py

Provides robust statistical methods for anomaly detection:
- Mann-Whitney U test (non-parametric significance)
- Cohen's d (Effect Size) to measure magnitude of change
"""

import numpy as np
from scipy import stats
from dataclasses import dataclass

@dataclass
class StatResult:
    significant: bool
    p_value: float
    effect_size: float  # Cohen's d
    effect_category: str # 'negligible', 'small', 'medium', 'large'

def calculate_effect_size(baseline: np.ndarray, current: np.ndarray) -> float:
    """
    Calculates Cohen's d: (mean_current - mean_baseline) / pooled_std
    Robust to sample size differences.
    """
    if len(baseline) < 2 or len(current) < 2:
        return 0.0

    mean_b, mean_c = np.mean(baseline), np.mean(current)
    var_b, var_c = np.var(baseline, ddof=1), np.var(current, ddof=1)
    n_b, n_c = len(baseline), len(current)

    # Pooled Standard Deviation
    pooled_var = ((n_b - 1) * var_b + (n_c - 1) * var_c) / (n_b + n_c - 2)
    pooled_std = np.sqrt(pooled_var)

    if pooled_std == 0:
        return 0.0
        
    return (mean_c - mean_b) / pooled_std

def compare_distributions(baseline: np.ndarray, current: np.ndarray, alpha=0.05) -> StatResult:
    """
    Compares two time windows to determine if a significant shift occurred.
    """
    # Clean NaNs
    baseline = baseline[~np.isnan(baseline)]
    current = current[~np.isnan(current)]

    if len(baseline) < 5 or len(current) < 5:
        return StatResult(False, 1.0, 0.0, 'insufficient_data')

    # 1. Significance Test (Mann-Whitney U is robust to non-normal data like latency)
    try:
        _, p_value = stats.mannwhitneyu(baseline, current, alternative='two-sided')
    except ValueError:
        p_value = 1.0

    # 2. Magnitude Test (Cohen's d)
    effect_size = calculate_effect_size(baseline, current)
    abs_d = abs(effect_size)

    # Categorize
    if abs_d < 0.2: category = 'negligible'
    elif abs_d < 0.5: category = 'small'
    elif abs_d < 0.8: category = 'medium'
    else: category = 'large'

    # A shift is "Significant" if p-value is low AND effect size is non-negligible
    is_significant = (p_value < alpha) and (abs_d >= 0.3)

    return StatResult(is_significant, p_value, effect_size, category)