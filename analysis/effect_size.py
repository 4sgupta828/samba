"""
Effect Size Calculation Module

Quantifies the magnitude of change between baseline and fault periods.

Effect sizes provide standardized measures of change that are independent
of sample size, unlike p-values.

Metrics:
- Cohen's d: Standardized mean difference
- Cliff's delta: Non-parametric effect size
- Glass's delta: Uses only baseline SD
- Hedge's g: Bias-corrected Cohen's d
- Percentage changes in location and spread
"""

import numpy as np
from typing import Dict
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)


def cohens_d(baseline: np.ndarray, fault: np.ndarray) -> float:
    """
    Compute Cohen's d effect size.

    d = (mean_fault - mean_baseline) / pooled_std

    Interpretation:
    - Small: 0.2
    - Medium: 0.5
    - Large: 0.8

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Cohen's d value
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return np.nan

    mean_baseline = np.mean(baseline_clean)
    mean_fault = np.mean(fault_clean)

    var_baseline = np.var(baseline_clean, ddof=1)
    var_fault = np.var(fault_clean, ddof=1)

    n_baseline = len(baseline_clean)
    n_fault = len(fault_clean)

    # Pooled standard deviation
    pooled_var = ((n_baseline - 1) * var_baseline + (n_fault - 1) * var_fault) / (n_baseline + n_fault - 2)
    pooled_std = np.sqrt(pooled_var)

    if pooled_std == 0:
        # Both distributions have zero variance
        if mean_baseline == mean_fault:
            return 0.0  # No change
        else:
            # Use a large but finite value instead of infinity
            # Indicates complete separation with no variance
            return 999.0 if mean_fault > mean_baseline else -999.0

    d = (mean_fault - mean_baseline) / pooled_std
    return float(d)


def glass_delta(baseline: np.ndarray, fault: np.ndarray) -> float:
    """
    Compute Glass's delta effect size.

    Similar to Cohen's d but uses only baseline SD (not pooled).
    Useful when baseline is the "control" condition.

    delta = (mean_fault - mean_baseline) / std_baseline

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Glass's delta value
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 1:
        return np.nan

    mean_baseline = np.mean(baseline_clean)
    mean_fault = np.mean(fault_clean)
    std_baseline = np.std(baseline_clean, ddof=1)

    if std_baseline == 0:
        if mean_baseline == mean_fault:
            return 0.0  # No change
        else:
            # Use a large but finite value instead of infinity
            return 999.0 if mean_fault > mean_baseline else -999.0

    delta = (mean_fault - mean_baseline) / std_baseline
    return float(delta)


def hedges_g(baseline: np.ndarray, fault: np.ndarray) -> float:
    """
    Compute Hedge's g (bias-corrected Cohen's d).

    Applies small-sample bias correction to Cohen's d.

    g = d * correction_factor
    where correction_factor = 1 - 3/(4*df - 1)

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Hedge's g value
    """
    d = cohens_d(baseline, fault)

    if np.isnan(d) or np.isinf(d):
        return d

    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    n_baseline = len(baseline_clean)
    n_fault = len(fault_clean)
    df = n_baseline + n_fault - 2

    if df <= 0:
        return d

    # Bias correction factor
    correction = 1 - (3 / (4 * df - 1))

    g = d * correction
    return float(g)


def cliffs_delta(baseline: np.ndarray, fault: np.ndarray) -> float:
    """
    Compute Cliff's delta (non-parametric effect size).

    Measures how often values in one group are larger than in the other.

    delta = (n_greater - n_less) / (n_baseline * n_fault)

    Ranges from -1 to 1:
    - 1: All fault values > all baseline values
    - 0: No difference
    - -1: All fault values < all baseline values

    Interpretation:
    - Negligible: |d| < 0.147
    - Small: 0.147 <= |d| < 0.33
    - Medium: 0.33 <= |d| < 0.474
    - Large: |d| >= 0.474

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Cliff's delta value
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) == 0 or len(fault_clean) == 0:
        return np.nan

    n_baseline = len(baseline_clean)
    n_fault = len(fault_clean)

    # Count pairs where fault > baseline and fault < baseline
    n_greater = 0
    n_less = 0

    for f_val in fault_clean:
        n_greater += np.sum(f_val > baseline_clean)
        n_less += np.sum(f_val < baseline_clean)

    total_pairs = n_baseline * n_fault

    if total_pairs == 0:
        return 0.0

    delta = (n_greater - n_less) / total_pairs
    return float(delta)


def categorize_effect_size(effect_size: float, metric: str = 'cohens_d') -> str:
    """
    Categorize effect size magnitude.

    Args:
        effect_size: Effect size value
        metric: Type of effect size ('cohens_d', 'cliffs_delta')

    Returns:
        Category: 'negligible', 'small', 'medium', 'large', or 'very_large'
    """
    if np.isnan(effect_size) or np.isinf(effect_size):
        return 'undefined'

    abs_effect = abs(effect_size)

    if metric == 'cohens_d' or metric == 'hedges_g' or metric == 'glass_delta':
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

    elif metric == 'cliffs_delta':
        if abs_effect < 0.147:
            return 'negligible'
        elif abs_effect < 0.33:
            return 'small'
        elif abs_effect < 0.474:
            return 'medium'
        else:
            return 'large'

    else:
        # Generic categorization
        if abs_effect < 0.2:
            return 'negligible'
        elif abs_effect < 0.5:
            return 'small'
        elif abs_effect < 0.8:
            return 'medium'
        else:
            return 'large'


def compute_percentage_changes(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compute percentage changes in location and spread statistics.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with percentage changes
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return {
            'mean_pct_change': np.nan,
            'median_pct_change': np.nan,
            'std_pct_change': np.nan,
            'iqr_pct_change': np.nan,
            'cv_change': np.nan
        }

    # Location changes
    mean_baseline = np.mean(baseline_clean)
    mean_fault = np.mean(fault_clean)

    # Handle division by zero for percentage changes
    if mean_baseline != 0:
        mean_pct_change = (mean_fault - mean_baseline) / abs(mean_baseline) * 100
    elif mean_fault != 0:
        # Changed from 0 to non-zero (e.g., errors appearing)
        mean_pct_change = 10000.0  # Large but finite value indicating "new appearance"
    else:
        mean_pct_change = 0.0  # Both are zero, no change

    median_baseline = np.median(baseline_clean)
    median_fault = np.median(fault_clean)

    if median_baseline != 0:
        median_pct_change = (median_fault - median_baseline) / abs(median_baseline) * 100
    elif median_fault != 0:
        median_pct_change = 10000.0
    else:
        median_pct_change = 0.0

    # Spread changes
    std_baseline = np.std(baseline_clean, ddof=1)
    std_fault = np.std(fault_clean, ddof=1)

    if std_baseline != 0:
        std_pct_change = (std_fault - std_baseline) / std_baseline * 100
    elif std_fault != 0:
        std_pct_change = 10000.0
    else:
        std_pct_change = 0.0

    q75_b, q25_b = np.percentile(baseline_clean, [75, 25])
    q75_f, q25_f = np.percentile(fault_clean, [75, 25])
    iqr_baseline = q75_b - q25_b
    iqr_fault = q75_f - q25_f

    if iqr_baseline != 0:
        iqr_pct_change = (iqr_fault - iqr_baseline) / iqr_baseline * 100
    elif iqr_fault != 0:
        iqr_pct_change = 10000.0
    else:
        iqr_pct_change = 0.0

    # Coefficient of variation change
    cv_baseline = std_baseline / abs(mean_baseline) if mean_baseline != 0 else 0.0
    cv_fault = std_fault / abs(mean_fault) if mean_fault != 0 else 0.0
    cv_change = cv_fault - cv_baseline

    # Variance ratio - handle zero baseline variance
    if std_baseline != 0:
        variance_ratio = (std_fault ** 2) / (std_baseline ** 2)
    elif std_fault != 0:
        variance_ratio = 10000.0  # Large but finite
    else:
        variance_ratio = 1.0  # Both zero, no change

    # IQR ratio
    if iqr_baseline != 0:
        iqr_ratio = iqr_fault / iqr_baseline
    elif iqr_fault != 0:
        iqr_ratio = 10000.0
    else:
        iqr_ratio = 1.0

    return {
        'mean_pct_change': float(mean_pct_change),
        'median_pct_change': float(median_pct_change),
        'std_pct_change': float(std_pct_change),
        'iqr_pct_change': float(iqr_pct_change),
        'cv_change': float(cv_change),
        'variance_ratio': float(variance_ratio),
        'iqr_ratio': float(iqr_ratio)
    }


def compute_all_effect_sizes(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compute all effect size measures.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with all effect sizes and categorizations
    """
    cohens_d_val = cohens_d(baseline, fault)
    glass_delta_val = glass_delta(baseline, fault)
    hedges_g_val = hedges_g(baseline, fault)
    cliffs_delta_val = cliffs_delta(baseline, fault)

    pct_changes = compute_percentage_changes(baseline, fault)

    return {
        'cohens_d': cohens_d_val,
        'cohens_d_category': categorize_effect_size(cohens_d_val, 'cohens_d'),
        'glass_delta': glass_delta_val,
        'glass_delta_category': categorize_effect_size(glass_delta_val, 'glass_delta'),
        'hedges_g': hedges_g_val,
        'hedges_g_category': categorize_effect_size(hedges_g_val, 'hedges_g'),
        'cliffs_delta': cliffs_delta_val,
        'cliffs_delta_category': categorize_effect_size(cliffs_delta_val, 'cliffs_delta'),
        **pct_changes
    }


def interpret_effect_size(effect_sizes: Dict) -> str:
    """
    Generate human-readable interpretation of effect sizes.

    Args:
        effect_sizes: Dictionary from compute_all_effect_sizes()

    Returns:
        Interpretation string
    """
    cohens_d_val = effect_sizes.get('cohens_d', np.nan)
    cohens_d_cat = effect_sizes.get('cohens_d_category', 'undefined')
    mean_pct = effect_sizes.get('mean_pct_change', np.nan)
    var_ratio = effect_sizes.get('variance_ratio', np.nan)

    if np.isnan(cohens_d_val):
        return "Insufficient data to compute effect size"

    direction = "increased" if cohens_d_val > 0 else "decreased"
    abs_d = abs(cohens_d_val)

    # Handle very large percentage changes (from zero baseline)
    if abs(mean_pct) >= 10000:
        pct_str = "∞" if direction == "increased" else "-∞"
        parts = [f"Mean {direction} by {pct_str}% (appeared from zero)."]
    else:
        parts = [f"Mean {direction} by {abs(mean_pct):.1f}%."]

    # Handle very large Cohen's d
    if abs_d >= 999:
        parts.append(f"Effect size: {cohens_d_cat} (Cohen's d = ∞).")
    else:
        parts.append(f"Effect size: {cohens_d_cat} (Cohen's d = {abs_d:.2f}).")

    # Handle variance ratio
    if not np.isnan(var_ratio):
        if var_ratio >= 10000:
            parts.append("Variance increased from zero (became unstable).")
        elif var_ratio > 2:
            parts.append(f"Variance increased {var_ratio:.1f}x (more unstable).")
        elif var_ratio < 0.5 and var_ratio > 0:
            parts.append(f"Variance decreased {1/var_ratio:.1f}x (more stable).")
        elif var_ratio == 0:
            parts.append("Variance became zero (completely stable).")

    return " ".join(parts)
