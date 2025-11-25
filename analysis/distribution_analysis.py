"""
Distribution Analysis Module

Provides methods for comparing distributions between baseline and fault periods:
- Location shift tests (Mann-Whitney U, Welch's t-test, K-S test)
- Scale shift tests (Levene's test, Ansari-Bradley)
- Distribution distance measures (KL divergence, Wasserstein distance)
"""

import numpy as np
from scipy import stats
from scipy.spatial import distance
from typing import Dict, Tuple
import warnings

# Suppress common warnings from scipy
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', message='Ties preclude use of exact statistic')
warnings.filterwarnings('ignore', message='p-value capped')
warnings.filterwarnings('ignore', message='p-value floored')


def mann_whitney_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Mann-Whitney U test for distribution shift (non-parametric).

    Tests if two independent samples come from the same distribution.
    Null hypothesis: distributions are identical
    Alternative: distributions are different (two-sided)

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, and significance
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 3 or len(fault_clean) < 3:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': 'insufficient_data'
        }

    try:
        statistic, p_value = stats.mannwhitneyu(
            baseline_clean, fault_clean,
            alternative='two-sided'
        )

        return {
            'statistic': float(statistic),
            'p_value': float(p_value),
            'significant': p_value < 0.05,
            'test': 'mann_whitney_u'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': f'error: {str(e)}'
        }


def welch_t_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Welch's t-test for difference in means (allows unequal variances).

    Suitable for normally distributed data with possibly different variances.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, and significance
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': 'insufficient_data'
        }

    try:
        statistic, p_value = stats.ttest_ind(
            baseline_clean, fault_clean,
            equal_var=False  # Welch's t-test
        )

        return {
            'statistic': float(statistic),
            'p_value': float(p_value),
            'significant': p_value < 0.05,
            'test': 'welch_t_test'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': f'error: {str(e)}'
        }


def kolmogorov_smirnov_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Kolmogorov-Smirnov two-sample test.

    Tests if two samples come from the same distribution.
    More sensitive to differences in the middle of the distribution.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, and significance
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 3 or len(fault_clean) < 3:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': 'insufficient_data'
        }

    try:
        statistic, p_value = stats.ks_2samp(baseline_clean, fault_clean)

        return {
            'statistic': float(statistic),
            'p_value': float(p_value),
            'significant': p_value < 0.05,
            'test': 'kolmogorov_smirnov'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': f'error: {str(e)}'
        }


def anderson_darling_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Anderson-Darling two-sample test.

    Tests if two samples come from the same distribution.
    More sensitive to differences in the tails.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, and significance
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 3 or len(fault_clean) < 3:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': 'insufficient_data'
        }

    try:
        result = stats.anderson_ksamp([baseline_clean, fault_clean])

        # Critical values at different significance levels
        # Typically: [25%, 10%, 5%, 2.5%, 1%]
        # Use 5% significance level (index 2)
        significant = result.statistic > result.critical_values[2]

        return {
            'statistic': float(result.statistic),
            'p_value': float(result.significance_level),
            'significant': significant,
            'test': 'anderson_darling'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': f'error: {str(e)}'
        }


def levene_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Levene's test for equality of variances.

    Tests if two samples have equal variances.
    Null hypothesis: variances are equal
    Alternative: variances are different

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, significance, and variance ratio
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'variance_ratio': np.nan,
            'test': 'insufficient_data'
        }

    try:
        statistic, p_value = stats.levene(baseline_clean, fault_clean)

        var_baseline = np.var(baseline_clean, ddof=1)
        var_fault = np.var(fault_clean, ddof=1)
        variance_ratio = var_fault / var_baseline if var_baseline > 0 else np.inf

        return {
            'statistic': float(statistic),
            'p_value': float(p_value),
            'significant': p_value < 0.05,
            'variance_ratio': float(variance_ratio),
            'test': 'levene'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'variance_ratio': np.nan,
            'test': f'error: {str(e)}'
        }


def ansari_bradley_test(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Ansari-Bradley test for equality of scale (non-parametric).

    Tests if two samples have the same scale (spread).

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with test statistic, p-value, and significance
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 3 or len(fault_clean) < 3:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': 'insufficient_data'
        }

    try:
        statistic, p_value = stats.ansari(baseline_clean, fault_clean)

        return {
            'statistic': float(statistic),
            'p_value': float(p_value),
            'significant': p_value < 0.05,
            'test': 'ansari_bradley'
        }
    except Exception as e:
        return {
            'statistic': np.nan,
            'p_value': np.nan,
            'significant': False,
            'test': f'error: {str(e)}'
        }


def compute_kl_divergence(baseline: np.ndarray, fault: np.ndarray, bins: int = 30) -> float:
    """
    Compute Kullback-Leibler divergence between two distributions.

    KL(P || Q) measures how much information is lost when Q is used to
    approximate P. Not symmetric.

    Args:
        baseline: Baseline period data (P)
        fault: Fault period data (Q)
        bins: Number of bins for histogram estimation

    Returns:
        KL divergence value (0 = identical, higher = more different)
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return np.nan

    try:
        # Create histograms with same bins
        combined = np.concatenate([baseline_clean, fault_clean])
        bin_edges = np.linspace(combined.min(), combined.max(), bins + 1)

        hist_baseline, _ = np.histogram(baseline_clean, bins=bin_edges, density=True)
        hist_fault, _ = np.histogram(fault_clean, bins=bin_edges, density=True)

        # Add small epsilon to avoid log(0)
        epsilon = 1e-10
        hist_baseline = hist_baseline + epsilon
        hist_fault = hist_fault + epsilon

        # Normalize
        hist_baseline = hist_baseline / hist_baseline.sum()
        hist_fault = hist_fault / hist_fault.sum()

        # Compute KL divergence
        kl_div = np.sum(hist_baseline * np.log(hist_baseline / hist_fault))

        return float(kl_div)
    except Exception as e:
        return np.nan


def compute_wasserstein_distance(baseline: np.ndarray, fault: np.ndarray) -> float:
    """
    Compute Wasserstein distance (Earth Mover's Distance).

    Measures the minimum "work" required to transform one distribution
    into another. Symmetric and respects the metric structure.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Wasserstein distance (0 = identical, higher = more different)
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return np.nan

    try:
        wd = stats.wasserstein_distance(baseline_clean, fault_clean)
        return float(wd)
    except Exception as e:
        return np.nan


def compute_jensen_shannon_divergence(baseline: np.ndarray, fault: np.ndarray, bins: int = 30) -> float:
    """
    Compute Jensen-Shannon divergence (symmetric version of KL).

    JS(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
    where M = 0.5 * (P + Q)

    Args:
        baseline: Baseline period data
        fault: Fault period data
        bins: Number of bins for histogram estimation

    Returns:
        JS divergence value (0 = identical, 1 = completely different)
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return np.nan

    try:
        # Create histograms with same bins
        combined = np.concatenate([baseline_clean, fault_clean])
        bin_edges = np.linspace(combined.min(), combined.max(), bins + 1)

        hist_baseline, _ = np.histogram(baseline_clean, bins=bin_edges, density=True)
        hist_fault, _ = np.histogram(fault_clean, bins=bin_edges, density=True)

        # Add small epsilon to avoid log(0)
        epsilon = 1e-10
        hist_baseline = hist_baseline + epsilon
        hist_fault = hist_fault + epsilon

        # Normalize
        hist_baseline = hist_baseline / hist_baseline.sum()
        hist_fault = hist_fault / hist_fault.sum()

        # Compute JS divergence
        js_div = distance.jensenshannon(hist_baseline, hist_fault) ** 2

        return float(js_div)
    except Exception as e:
        return np.nan


def test_location_shift(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Comprehensive location shift testing.

    Runs multiple tests to detect if the central tendency changed.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with results from multiple location tests
    """
    return {
        'mann_whitney_u': mann_whitney_test(baseline, fault),
        'welch_t_test': welch_t_test(baseline, fault),
        'ks_test': kolmogorov_smirnov_test(baseline, fault),
        'anderson_darling': anderson_darling_test(baseline, fault)
    }


def test_scale_shift(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Comprehensive scale shift testing.

    Runs multiple tests to detect if the variance/spread changed.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with results from multiple scale tests
    """
    return {
        'levene': levene_test(baseline, fault),
        'ansari_bradley': ansari_bradley_test(baseline, fault)
    }


def compute_distribution_distances(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compute multiple distribution distance measures.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with various distance measures
    """
    return {
        'kl_divergence': compute_kl_divergence(baseline, fault),
        'wasserstein_distance': compute_wasserstein_distance(baseline, fault),
        'jensen_shannon_divergence': compute_jensen_shannon_divergence(baseline, fault)
    }


def compare_distributions(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Comprehensive distribution comparison.

    Runs all location tests, scale tests, and distance measures.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with complete comparison results
    """
    return {
        'location_tests': test_location_shift(baseline, fault),
        'scale_tests': test_scale_shift(baseline, fault),
        'distances': compute_distribution_distances(baseline, fault)
    }
