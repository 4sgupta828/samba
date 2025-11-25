"""
Changepoint Detection Module

Detects structural breaks in time series data to identify when
a fault starts affecting a metric.

Methods:
- PELT (Pruned Exact Linear Time) - optimal detection
- Binary Segmentation - fast approximate detection
- E-Divisive - non-parametric detection
- Simple threshold-based detection (fallback)
"""

import numpy as np
from typing import Dict, List, Optional
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)


def detect_changepoint_pelt(data: np.ndarray, min_size: int = 5, penalty: float = 3.0) -> Dict:
    """
    Detect changepoint using PELT algorithm (requires ruptures library).

    PELT is optimal for detecting changes in mean and variance.

    Args:
        data: Time series data
        min_size: Minimum segment size
        penalty: Penalty value for model selection (higher = fewer changepoints)

    Returns:
        Dictionary with changepoint location and confidence
    """
    if len(data) < min_size * 2:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'insufficient_data'
        }

    try:
        import ruptures as rpt

        # Remove NaN values but track indices
        clean_indices = ~np.isnan(data)
        clean_data = data[clean_indices]

        if len(clean_data) < min_size * 2:
            return {
                'detected': False,
                'location': None,
                'confidence': 0.0,
                'method': 'insufficient_data'
            }

        # Detect changepoint
        model = "l2"  # L2 cost function (mean and variance)
        algo = rpt.Pelt(model=model, min_size=min_size).fit(clean_data)
        changepoints = algo.predict(pen=penalty)

        # Remove the last index (end of series)
        changepoints = [cp for cp in changepoints if cp < len(clean_data)]

        if len(changepoints) == 0:
            return {
                'detected': False,
                'location': None,
                'confidence': 0.0,
                'method': 'pelt'
            }

        # Get first changepoint
        cp_index = changepoints[0]

        # Map back to original indices
        original_indices = np.where(clean_indices)[0]
        cp_location = int(original_indices[cp_index])

        # Estimate confidence based on magnitude of change
        before = clean_data[:cp_index]
        after = clean_data[cp_index:]

        if len(before) > 0 and len(after) > 0:
            mean_diff = abs(np.mean(after) - np.mean(before))
            std_before = np.std(before, ddof=1) if len(before) > 1 else 1.0
            confidence = min(1.0, mean_diff / (std_before + 1e-10))
        else:
            confidence = 0.0

        return {
            'detected': True,
            'location': cp_location,
            'confidence': float(confidence),
            'method': 'pelt',
            'all_changepoints': [int(original_indices[cp]) for cp in changepoints]
        }

    except ImportError:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'ruptures_not_available'
        }
    except Exception as e:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': f'error: {str(e)}'
        }


def detect_changepoint_binary_segmentation(
    data: np.ndarray,
    min_size: int = 5,
    n_bkps: int = 1
) -> Dict:
    """
    Detect changepoint using Binary Segmentation (requires ruptures library).

    Fast approximate algorithm for changepoint detection.

    Args:
        data: Time series data
        min_size: Minimum segment size
        n_bkps: Number of changepoints to detect

    Returns:
        Dictionary with changepoint location and confidence
    """
    if len(data) < min_size * 2:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'insufficient_data'
        }

    try:
        import ruptures as rpt

        clean_indices = ~np.isnan(data)
        clean_data = data[clean_indices]

        if len(clean_data) < min_size * 2:
            return {
                'detected': False,
                'location': None,
                'confidence': 0.0,
                'method': 'insufficient_data'
            }

        # Binary Segmentation
        model = "l2"
        algo = rpt.Binseg(model=model, min_size=min_size).fit(clean_data)
        changepoints = algo.predict(n_bkps=n_bkps)

        # Remove the last index
        changepoints = [cp for cp in changepoints if cp < len(clean_data)]

        if len(changepoints) == 0:
            return {
                'detected': False,
                'location': None,
                'confidence': 0.0,
                'method': 'binary_segmentation'
            }

        cp_index = changepoints[0]
        original_indices = np.where(clean_indices)[0]
        cp_location = int(original_indices[cp_index])

        # Confidence estimation
        before = clean_data[:cp_index]
        after = clean_data[cp_index:]

        if len(before) > 0 and len(after) > 0:
            mean_diff = abs(np.mean(after) - np.mean(before))
            std_before = np.std(before, ddof=1) if len(before) > 1 else 1.0
            confidence = min(1.0, mean_diff / (std_before + 1e-10))
        else:
            confidence = 0.0

        return {
            'detected': True,
            'location': cp_location,
            'confidence': float(confidence),
            'method': 'binary_segmentation'
        }

    except ImportError:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'ruptures_not_available'
        }
    except Exception as e:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': f'error: {str(e)}'
        }


def detect_changepoint_threshold(
    data: np.ndarray,
    expected_location: Optional[int] = None,
    window: int = 5,
    threshold_std: float = 2.0
) -> Dict:
    """
    Simple threshold-based changepoint detection (fallback method).

    Detects when data exceeds baseline mean + threshold_std * baseline_std
    for sustained period.

    Args:
        data: Time series data
        expected_location: Expected changepoint location (e.g., fault_start_time)
        window: Window size for smoothing
        threshold_std: Number of standard deviations for threshold

    Returns:
        Dictionary with changepoint location and confidence
    """
    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 10:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'insufficient_data'
        }

    # If expected location is given, use it to define baseline
    if expected_location is not None and expected_location < len(data):
        baseline = data[:expected_location]
        baseline_clean = baseline[~np.isnan(baseline)]

        if len(baseline_clean) < 3:
            # Fall back to first 20% as baseline
            baseline_end = max(3, len(data) // 5)
            baseline_clean = data[:baseline_end]
            baseline_clean = baseline_clean[~np.isnan(baseline_clean)]
    else:
        # Use first 20% as baseline
        baseline_end = max(3, len(data) // 5)
        baseline_clean = data[:baseline_end]
        baseline_clean = baseline_clean[~np.isnan(baseline_clean)]

    if len(baseline_clean) < 2:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'insufficient_baseline'
        }

    baseline_mean = np.mean(baseline_clean)
    baseline_std = np.std(baseline_clean, ddof=1)

    # Compute threshold
    threshold = baseline_mean + threshold_std * baseline_std

    # Find first sustained exceedance
    cp_location = None
    for i in range(len(baseline_clean), len(data) - window):
        window_data = data[i:i+window]
        window_clean = window_data[~np.isnan(window_data)]

        if len(window_clean) >= window // 2:
            if np.mean(window_clean) > threshold:
                cp_location = i
                break

    if cp_location is None:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'threshold',
            'threshold': float(threshold)
        }

    # Confidence based on how much threshold is exceeded
    after_data = data[cp_location:]
    after_clean = after_data[~np.isnan(after_data)]
    after_mean = np.mean(after_clean) if len(after_clean) > 0 else baseline_mean

    if baseline_std > 0:
        confidence = min(1.0, abs(after_mean - baseline_mean) / (threshold_std * baseline_std))
    else:
        confidence = 1.0 if after_mean > threshold else 0.0

    return {
        'detected': True,
        'location': cp_location,
        'confidence': float(confidence),
        'method': 'threshold',
        'threshold': float(threshold),
        'baseline_mean': float(baseline_mean),
        'after_mean': float(after_mean)
    }


def detect_changepoint(
    data: np.ndarray,
    expected_location: Optional[int] = None,
    method: str = 'auto'
) -> Dict:
    """
    Detect changepoint using best available method.

    Tries methods in order: PELT > Binary Segmentation > Threshold

    Args:
        data: Time series data
        expected_location: Expected changepoint (e.g., fault_start_time index)
        method: 'auto', 'pelt', 'binary_seg', or 'threshold'

    Returns:
        Dictionary with changepoint detection results
    """
    if len(data) < 10:
        return {
            'detected': False,
            'location': None,
            'confidence': 0.0,
            'method': 'insufficient_data'
        }

    if method == 'pelt' or method == 'auto':
        result = detect_changepoint_pelt(data)
        if result['detected'] or method == 'pelt':
            return result

    if method == 'binary_seg' or method == 'auto':
        result = detect_changepoint_binary_segmentation(data)
        if result['detected'] or method == 'binary_seg':
            return result

    # Fall back to threshold method
    return detect_changepoint_threshold(data, expected_location)


def validate_changepoint_at_boundary(
    data: np.ndarray,
    boundary: int,
    window: int = 5
) -> Dict:
    """
    Validate if there's a significant change at a known boundary.

    Useful when you know when the fault was injected and want to
    verify if the metric actually changed at that time.

    Args:
        data: Time series data
        boundary: Index of expected boundary (e.g., fault_start_time)
        window: Window size for comparison

    Returns:
        Dictionary with validation results
    """
    if boundary < window or boundary >= len(data) - window:
        return {
            'validated': False,
            'change_detected': False,
            'mean_diff': 0.0,
            'std_diff': 0.0,
            'reason': 'boundary_out_of_range'
        }

    # Get data before and after boundary
    before = data[max(0, boundary-window):boundary]
    after = data[boundary:min(len(data), boundary+window)]

    before_clean = before[~np.isnan(before)]
    after_clean = after[~np.isnan(after)]

    if len(before_clean) < 2 or len(after_clean) < 2:
        return {
            'validated': False,
            'change_detected': False,
            'mean_diff': 0.0,
            'std_diff': 0.0,
            'reason': 'insufficient_data_around_boundary'
        }

    # Compare statistics
    mean_before = np.mean(before_clean)
    mean_after = np.mean(after_clean)
    std_before = np.std(before_clean, ddof=1)
    std_after = np.std(after_clean, ddof=1)

    mean_diff = abs(mean_after - mean_before)
    std_diff = abs(std_after - std_before)

    # Check if change is significant (> 1 std of baseline)
    change_detected = mean_diff > std_before

    return {
        'validated': True,
        'change_detected': change_detected,
        'mean_before': float(mean_before),
        'mean_after': float(mean_after),
        'mean_diff': float(mean_diff),
        'std_before': float(std_before),
        'std_after': float(std_after),
        'std_diff': float(std_diff),
        'mean_pct_change': float((mean_after - mean_before) / mean_before * 100) if mean_before != 0 else np.inf
    }
