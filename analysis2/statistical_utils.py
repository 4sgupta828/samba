"""
statistical_utils.py

Provides robust statistical methods for anomaly detection:
- Mann-Whitney U test (non-parametric significance)
- Cohen's d (Effect Size) with semantic categorization
- Changepoint detection (PELT/Binary Segmentation with fallback)
- Baseline stability validation
"""

import numpy as np
from scipy import stats
from dataclasses import dataclass
import warnings

# Suppress runtime warnings for clean output
warnings.filterwarnings('ignore', category=RuntimeWarning)

@dataclass
class StatResult:
    significant: bool
    p_value: float
    effect_size: float  # Cohen's d
    effect_category: str # 'negligible', 'small', 'medium', 'large'
    changepoint_detected: bool = False
    confidence: str = 'low' # 'high', 'medium', 'low'

def calculate_effect_size(baseline: np.ndarray, current: np.ndarray) -> float:
    """Calculates Cohen's d: (mean_current - mean_baseline) / pooled_std."""
    if len(baseline) < 2 or len(current) < 2:
        return 0.0

    mean_b, mean_c = np.mean(baseline), np.mean(current)
    var_b, var_c = np.var(baseline, ddof=1), np.var(current, ddof=1)
    n_b, n_c = len(baseline), len(current)

    pooled_var = ((n_b - 1) * var_b + (n_c - 1) * var_c) / (n_b + n_c - 2)
    pooled_std = np.sqrt(pooled_var)

    if pooled_std == 0:
        return 0.0
        
    return (mean_c - mean_b) / pooled_std

def categorize_effect_size(d: float) -> str:
    """Semantically categorize Cohen's d."""
    abs_d = abs(d)
    if abs_d < 0.2: return 'negligible'
    if abs_d < 0.5: return 'small'
    if abs_d < 0.8: return 'medium'
    return 'large'

def validate_baseline_stability(data: np.ndarray, cv_threshold: float = 0.5) -> bool:
    """
    Checks if baseline is stable enough for comparison.
    High CV (Coefficient of Variation) implies noise, lowering confidence.
    """
    clean_data = data[~np.isnan(data)]
    if len(clean_data) < 3: return False
    
    mean = np.mean(clean_data)
    if mean == 0: return True # Stable at zero
    
    std = np.std(clean_data)
    cv = std / abs(mean)
    
    return cv < cv_threshold

def detect_changepoint(data: np.ndarray) -> bool:
    """
    Detects if a structural break occurred in the time series.
    Tries robust PELT method (ruptures), falls back to thresholding.
    """
    # 1. Try Ruptures (SOTA method)
    try:
        import ruptures as rpt
        clean_data = data[~np.isnan(data)]
        if len(clean_data) < 10: return False
        
        # Binary segmentation is faster for simple checks
        algo = rpt.Binseg(model="l2").fit(clean_data)
        result = algo.predict(n_bkps=1)
        
        # If break is found not at the very edges, it's significant
        if result and 1 < result[0] < len(clean_data) - 1:
            return True
    except ImportError:
        pass # Fallback

    # 2. Simple Threshold Fallback (Mean shift > 3 std devs)
    if len(data) < 5: return False
    mid = len(data) // 2
    before, after = data[:mid], data[mid:]
    
    mean_b = np.mean(before)
    std_b = np.std(before)
    mean_a = np.mean(after)
    
    if std_b == 0: return abs(mean_a - mean_b) > 0
    return abs(mean_a - mean_b) > 3 * std_b

def compare_distributions(baseline: np.ndarray, current: np.ndarray, alpha=0.05) -> StatResult:
    """
    SOTA Comparison with STRICT statistical rigor to prevent false positives.

    Combines:
    - Mann-Whitney U test (non-parametric significance)
    - Cohen's d (effect size magnitude)
    - Baseline stability validation (prevents detecting noise as signal)
    - Minimum effect size thresholds (prevents flagging trivial changes)
    - Sample size validation

    STRICT criteria:
    - Requires BOTH statistical significance (p < alpha) AND meaningful effect size (d > 0.5)
    - Validates baseline is stable before comparison
    - Higher minimum effect size than standard (0.5 instead of 0.2)
    """
    # Clean NaNs
    baseline = baseline[~np.isnan(baseline)]
    current = current[~np.isnan(current)]

    # 0. Minimum sample size check (increased from 5 to 10 for better statistical power)
    if len(baseline) < 10 or len(current) < 10:
        return StatResult(False, 1.0, 0.0, 'insufficient_data')

    # 1. Baseline Stability Check (CRITICAL for avoiding false positives)
    # If baseline is too noisy, we can't reliably detect real changes
    # A high CV (>0.5) means baseline is unstable - reject comparison
    baseline_mean = np.mean(baseline)
    baseline_std = np.std(baseline)

    if baseline_mean != 0:
        baseline_cv = baseline_std / abs(baseline_mean)
        if baseline_cv > 0.5:
            # Baseline too unstable - any "change" is likely just noise
            return StatResult(False, 1.0, 0.0, 'unstable_baseline', confidence='very_low')

    # 2. Significance Test (Mann-Whitney U robust to non-normal data)
    try:
        _, p_value = stats.mannwhitneyu(baseline, current, alternative='two-sided')
    except ValueError:
        p_value = 1.0

    # 3. Magnitude (Effect Size)
    effect_size = calculate_effect_size(baseline, current)
    category = categorize_effect_size(effect_size)

    # 4. Structural Change (Did the pattern actually break?)
    combined_series = np.concatenate([baseline, current])
    cp_detected = detect_changepoint(combined_series)

    # 5. STRICT Significance Logic (prevents false positives from benign variance)
    # OLD: (p_value < alpha and category != 'negligible') or cp_detected
    # NEW: Require BOTH statistical significance AND meaningful effect size (d >= 0.5)
    #      OR very strong changepoint with large effect

    # Minimum effect size for "medium" (0.5) instead of "small" (0.2)
    # This filters out trivial changes that might be statistically significant but not practically meaningful
    has_significant_p_value = p_value < alpha
    has_meaningful_effect = abs(effect_size) >= 0.5  # STRICT: medium+ effect only
    has_strong_changepoint = cp_detected and abs(effect_size) >= 0.8  # Changepoint must be backed by large effect

    # Main logic: Need BOTH significance and meaningful effect, OR very strong changepoint
    is_significant = (has_significant_p_value and has_meaningful_effect) or has_strong_changepoint

    # 6. Confidence Score
    confidence = 'low'
    if is_significant:
        if abs(effect_size) > 1.0 and cp_detected and p_value < 0.01:
            confidence = 'high'  # Very strong evidence
        elif abs(effect_size) > 0.8 and p_value < 0.05:
            confidence = 'medium'  # Strong evidence
        # If only borderline (d=0.5-0.8), keep confidence='low'

    return StatResult(is_significant, p_value, effect_size, category, cp_detected, confidence)