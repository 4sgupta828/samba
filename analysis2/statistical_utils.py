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
from typing import Dict, Optional, Tuple
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

def detect_changepoint(data: np.ndarray, penalty: int = 10) -> bool:
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
    SOTA Comparison: Combines Mann-Whitney U, Cohen's d, and Changepoint detection.
    """
    # Clean NaNs
    baseline = baseline[~np.isnan(baseline)]
    current = current[~np.isnan(current)]

    if len(baseline) < 5 or len(current) < 5:
        return StatResult(False, 1.0, 0.0, 'insufficient_data')

    # 1. Significance Test (Mann-Whitney U robust to non-normal data)
    try:
        _, p_value = stats.mannwhitneyu(baseline, current, alternative='two-sided')
    except ValueError:
        p_value = 1.0

    # 2. Magnitude (Effect Size)
    effect_size = calculate_effect_size(baseline, current)
    category = categorize_effect_size(effect_size)

    # 3. Structural Change (Did the pattern actually break?)
    # Concatenate to see if a break exists at the transition
    combined_series = np.concatenate([baseline, current])
    cp_detected = detect_changepoint(combined_series)

    # 4. Final Significance Logic
    # Significant if: (Low P-value AND Non-negligible Effect) OR (Structural Changepoint Detected)
    is_significant = (p_value < alpha and category != 'negligible') or cp_detected

    # 5. Confidence Score
    confidence = 'low'
    if is_significant:
        if abs(effect_size) > 0.8 and cp_detected: confidence = 'high'
        elif abs(effect_size) > 0.5: confidence = 'medium'

    return StatResult(is_significant, p_value, effect_size, category, cp_detected, confidence)