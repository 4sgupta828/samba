"""
Pattern Analysis Module

Analyzes temporal pattern changes between baseline and fault periods:
- Autocorrelation structure changes
- Volatility changes (rolling variance)
- Spectral density changes (frequency domain)
- Entropy changes (predictability)
"""

import numpy as np
from scipy import signal, stats
from typing import Dict, Optional
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)


def compare_autocorrelation(baseline: np.ndarray, fault: np.ndarray, max_lag: int = 5) -> Dict:
    """
    Compare autocorrelation functions between baseline and fault.

    Args:
        baseline: Baseline period data
        fault: Fault period data
        max_lag: Maximum lag to compare

    Returns:
        Dictionary with ACF comparison metrics
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 10 or len(fault_clean) < 10:
        return {
            'acf_distance': np.nan,
            'baseline_acf': [],
            'fault_acf': [],
            'interpretation': 'insufficient_data'
        }

    try:
        from statsmodels.tsa.stattools import acf

        # Compute ACF for both periods
        max_lag = min(max_lag, len(baseline_clean) // 2 - 1, len(fault_clean) // 2 - 1)

        if max_lag < 1:
            return {
                'acf_distance': np.nan,
                'baseline_acf': [],
                'fault_acf': [],
                'interpretation': 'insufficient_data'
            }

        baseline_acf = acf(baseline_clean, nlags=max_lag, fft=True)
        fault_acf = acf(fault_clean, nlags=max_lag, fft=True)

        # Compute distance (sum of squared differences, excluding lag 0)
        acf_distance = np.sum((baseline_acf[1:] - fault_acf[1:]) ** 2)

        # Interpretation
        if acf_distance < 0.1:
            interpretation = "Temporal structure unchanged"
        elif acf_distance < 0.5:
            interpretation = "Minor temporal structure change"
        elif acf_distance < 1.0:
            interpretation = "Moderate temporal structure change"
        else:
            interpretation = "Major temporal structure change"

        return {
            'acf_distance': float(acf_distance),
            'baseline_acf': [float(x) for x in baseline_acf[1:]],
            'fault_acf': [float(x) for x in fault_acf[1:]],
            'interpretation': interpretation
        }

    except ImportError:
        # Fall back to simple lag-1 correlation
        if len(baseline_clean) > 1 and len(fault_clean) > 1:
            baseline_lag1 = np.corrcoef(baseline_clean[:-1], baseline_clean[1:])[0, 1]
            fault_lag1 = np.corrcoef(fault_clean[:-1], fault_clean[1:])[0, 1]
            acf_distance = (baseline_lag1 - fault_lag1) ** 2

            return {
                'acf_distance': float(acf_distance),
                'baseline_acf': [float(baseline_lag1)],
                'fault_acf': [float(fault_lag1)],
                'interpretation': 'statsmodels_not_available_used_lag1'
            }
        else:
            return {
                'acf_distance': np.nan,
                'baseline_acf': [],
                'fault_acf': [],
                'interpretation': 'insufficient_data'
            }
    except Exception as e:
        return {
            'acf_distance': np.nan,
            'baseline_acf': [],
            'fault_acf': [],
            'interpretation': f'error: {str(e)}'
        }


def compare_volatility(baseline: np.ndarray, fault: np.ndarray, window: int = 5) -> Dict:
    """
    Compare volatility (rolling standard deviation) between periods.

    Args:
        baseline: Baseline period data
        fault: Fault period data
        window: Window size for rolling computation

    Returns:
        Dictionary with volatility comparison metrics
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < window or len(fault_clean) < window:
        return {
            'volatility_ratio': np.nan,
            'baseline_volatility': np.nan,
            'fault_volatility': np.nan,
            'interpretation': 'insufficient_data'
        }

    # Compute rolling standard deviation
    def rolling_std(data, w):
        return np.array([
            np.std(data[max(0, i-w+1):i+1], ddof=1)
            for i in range(w-1, len(data))
        ])

    baseline_vol = rolling_std(baseline_clean, window)
    fault_vol = rolling_std(fault_clean, window)

    baseline_mean_vol = np.mean(baseline_vol)
    fault_mean_vol = np.mean(fault_vol)

    volatility_ratio = fault_mean_vol / baseline_mean_vol if baseline_mean_vol > 0 else np.inf

    # Interpretation
    if volatility_ratio < 0.8:
        interpretation = "Volatility decreased (more stable)"
    elif volatility_ratio < 1.2:
        interpretation = "Volatility unchanged"
    elif volatility_ratio < 2.0:
        interpretation = "Volatility moderately increased"
    elif volatility_ratio < 5.0:
        interpretation = "Volatility highly increased"
    else:
        interpretation = "Volatility extremely increased"

    return {
        'volatility_ratio': float(volatility_ratio),
        'baseline_volatility': float(baseline_mean_vol),
        'fault_volatility': float(fault_mean_vol),
        'interpretation': interpretation
    }


def compare_spectral_density(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compare power spectral density (frequency domain analysis).

    Detects changes in the frequency content of the time series.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with spectral comparison metrics
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 10 or len(fault_clean) < 10:
        return {
            'spectral_divergence': np.nan,
            'interpretation': 'insufficient_data'
        }

    try:
        # Compute power spectral density using Welch's method
        freqs_b, psd_b = signal.welch(baseline_clean, nperseg=min(len(baseline_clean), 256))
        freqs_f, psd_f = signal.welch(fault_clean, nperseg=min(len(fault_clean), 256))

        # Interpolate to common frequency grid
        common_freqs = np.linspace(0, min(freqs_b[-1], freqs_f[-1]), 50)
        psd_b_interp = np.interp(common_freqs, freqs_b, psd_b)
        psd_f_interp = np.interp(common_freqs, freqs_f, psd_f)

        # Normalize PSDs
        psd_b_norm = psd_b_interp / (np.sum(psd_b_interp) + 1e-10)
        psd_f_norm = psd_f_interp / (np.sum(psd_f_interp) + 1e-10)

        # Compute divergence (KL or Jensen-Shannon)
        epsilon = 1e-10
        psd_b_norm = psd_b_norm + epsilon
        psd_f_norm = psd_f_norm + epsilon

        # Jensen-Shannon divergence
        from scipy.spatial import distance
        spectral_divergence = distance.jensenshannon(psd_b_norm, psd_f_norm) ** 2

        # Interpretation
        if spectral_divergence < 0.05:
            interpretation = "Frequency content unchanged"
        elif spectral_divergence < 0.15:
            interpretation = "Minor frequency content change"
        elif spectral_divergence < 0.3:
            interpretation = "Moderate frequency content change"
        else:
            interpretation = "Major frequency content change"

        return {
            'spectral_divergence': float(spectral_divergence),
            'interpretation': interpretation
        }

    except Exception as e:
        return {
            'spectral_divergence': np.nan,
            'interpretation': f'error: {str(e)}'
        }


def compute_sample_entropy(data: np.ndarray, m: int = 2, r: Optional[float] = None) -> float:
    """
    Compute sample entropy (measure of predictability/regularity).

    Lower entropy = more regular/predictable
    Higher entropy = more irregular/unpredictable

    Args:
        data: Time series data
        m: Pattern length
        r: Tolerance (default: 0.2 * std)

    Returns:
        Sample entropy value
    """
    data_clean = data[~np.isnan(data)]

    if len(data_clean) < 10:
        return np.nan

    try:
        # Try using pyentrp if available
        from pyentrp import entropy as ent
        if r is None:
            r = 0.2 * np.std(data_clean, ddof=1)
        samp_ent = ent.sample_entropy(data_clean, m, r)
        return float(samp_ent[0]) if len(samp_ent) > 0 else np.nan

    except ImportError:
        # Fall back to approximate entropy calculation
        if r is None:
            r = 0.2 * np.std(data_clean, ddof=1)

        def _maxdist(x_i, x_j):
            return max([abs(ua - va) for ua, va in zip(x_i, x_j)])

        def _phi(m):
            n = len(data_clean)
            patterns = np.array([data_clean[i:i+m] for i in range(n - m + 1)])
            C = []
            for i in range(len(patterns)):
                matches = sum([1 for j in range(len(patterns)) if _maxdist(patterns[i], patterns[j]) <= r])
                C.append(matches / len(patterns))
            return np.sum(np.log(C)) / len(C) if len(C) > 0 else 0

        try:
            return float(_phi(m) - _phi(m + 1))
        except:
            return np.nan

    except Exception as e:
        return np.nan


def compare_entropy(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compare entropy (predictability) between baseline and fault.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with entropy comparison metrics
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 10 or len(fault_clean) < 10:
        return {
            'entropy_change': np.nan,
            'baseline_entropy': np.nan,
            'fault_entropy': np.nan,
            'interpretation': 'insufficient_data'
        }

    baseline_entropy = compute_sample_entropy(baseline_clean)
    fault_entropy = compute_sample_entropy(fault_clean)

    if np.isnan(baseline_entropy) or np.isnan(fault_entropy):
        return {
            'entropy_change': np.nan,
            'baseline_entropy': baseline_entropy,
            'fault_entropy': fault_entropy,
            'interpretation': 'computation_failed'
        }

    entropy_change = fault_entropy - baseline_entropy

    # Interpretation
    if abs(entropy_change) < 0.1:
        interpretation = "Predictability unchanged"
    elif entropy_change < -0.1:
        interpretation = "Became more predictable (lower entropy)"
    else:
        interpretation = "Became less predictable (higher entropy)"

    return {
        'entropy_change': float(entropy_change),
        'baseline_entropy': float(baseline_entropy),
        'fault_entropy': float(fault_entropy),
        'interpretation': interpretation
    }


def compare_burstiness(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Compare burstiness parameter between baseline and fault.

    Burstiness B = (σ - μ) / (σ + μ)
    Ranges from -1 (regular) to 1 (bursty)

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with burstiness comparison
    """
    baseline_clean = baseline[~np.isnan(baseline)]
    fault_clean = fault[~np.isnan(fault)]

    if len(baseline_clean) < 2 or len(fault_clean) < 2:
        return {
            'burstiness_change': np.nan,
            'baseline_burstiness': np.nan,
            'fault_burstiness': np.nan,
            'interpretation': 'insufficient_data'
        }

    def compute_burstiness(data):
        mean = np.mean(data)
        std = np.std(data, ddof=1)
        if mean + std == 0:
            return 0.0
        return (std - mean) / (std + mean)

    baseline_burstiness = compute_burstiness(baseline_clean)
    fault_burstiness = compute_burstiness(fault_clean)

    burstiness_change = fault_burstiness - baseline_burstiness

    # Interpretation
    if abs(burstiness_change) < 0.1:
        interpretation = "Burstiness unchanged"
    elif burstiness_change > 0.1:
        interpretation = "Became more bursty (clustered events)"
    else:
        interpretation = "Became more regular (uniform events)"

    return {
        'burstiness_change': float(burstiness_change),
        'baseline_burstiness': float(baseline_burstiness),
        'fault_burstiness': float(fault_burstiness),
        'interpretation': interpretation
    }


def analyze_pattern_changes(baseline: np.ndarray, fault: np.ndarray) -> Dict:
    """
    Comprehensive pattern change analysis.

    Combines multiple pattern analysis methods.

    Args:
        baseline: Baseline period data
        fault: Fault period data

    Returns:
        Dictionary with all pattern change metrics
    """
    return {
        'autocorrelation': compare_autocorrelation(baseline, fault),
        'volatility': compare_volatility(baseline, fault),
        'spectral': compare_spectral_density(baseline, fault),
        'entropy': compare_entropy(baseline, fault),
        'burstiness': compare_burstiness(baseline, fault)
    }


def interpret_pattern_changes(pattern_analysis: Dict) -> str:
    """
    Generate human-readable interpretation of pattern changes.

    Args:
        pattern_analysis: Output from analyze_pattern_changes()

    Returns:
        Interpretation string
    """
    interpretations = []

    # Autocorrelation
    acf_dist = pattern_analysis.get('autocorrelation', {}).get('acf_distance', np.nan)
    if not np.isnan(acf_dist):
        if acf_dist > 0.5:
            interpretations.append("temporal structure changed significantly")

    # Volatility
    vol_ratio = pattern_analysis.get('volatility', {}).get('volatility_ratio', np.nan)
    if not np.isnan(vol_ratio):
        if vol_ratio > 2.0:
            interpretations.append(f"became {vol_ratio:.1f}x more volatile")
        elif vol_ratio < 0.5 and vol_ratio > 0:
            interpretations.append(f"became {1/vol_ratio:.1f}x less volatile")
        elif vol_ratio == 0:
            interpretations.append("became completely stable (zero volatility)")

    # Burstiness
    burst_change = pattern_analysis.get('burstiness', {}).get('burstiness_change', np.nan)
    if not np.isnan(burst_change):
        if burst_change > 0.2:
            interpretations.append("became more bursty")
        elif burst_change < -0.2:
            interpretations.append("became more regular")

    # Entropy
    entropy_change = pattern_analysis.get('entropy', {}).get('entropy_change', np.nan)
    if not np.isnan(entropy_change):
        if entropy_change > 0.1:
            interpretations.append("became less predictable")
        elif entropy_change < -0.1:
            interpretations.append("became more predictable")

    if len(interpretations) == 0:
        return "Pattern characteristics remained stable"

    return "Pattern changes: " + ", ".join(interpretations) + "."
