"""
Time Series Statistical Analysis Module

Provides comprehensive statistical characterization of time series data including:
- Location statistics (mean, median, trimmed mean)
- Spread statistics (std, IQR, MAD, CV)
- Shape statistics (skewness, kurtosis, normality tests)
- Temporal properties (stationarity, trend, autocorrelation)
- Pattern characteristics (burstiness, volatility)
"""

import numpy as np
from scipy import stats
from typing import Dict, Optional, Tuple
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)


def compute_location_stats(data: np.ndarray) -> Dict:
    """
    Compute location (central tendency) statistics.

    Args:
        data: 1D array of values

    Returns:
        Dictionary with mean, median, trimmed_mean, mode
    """
    if len(data) == 0:
        return {
            'mean': np.nan,
            'median': np.nan,
            'trimmed_mean': np.nan,
            'mode': np.nan
        }

    # Remove NaN values
    clean_data = data[~np.isnan(data)]

    if len(clean_data) == 0:
        return {
            'mean': np.nan,
            'median': np.nan,
            'trimmed_mean': np.nan,
            'mode': np.nan
        }

    result = {
        'mean': float(np.mean(clean_data)),
        'median': float(np.median(clean_data)),
        'trimmed_mean': float(stats.trim_mean(clean_data, proportiontocut=0.1)),
    }

    # Mode (for discrete or binned data)
    try:
        mode_result = stats.mode(clean_data, keepdims=True)
        result['mode'] = float(mode_result.mode[0])
    except:
        result['mode'] = result['median']  # Fall back to median

    return result


def compute_spread_stats(data: np.ndarray) -> Dict:
    """
    Compute spread (dispersion) statistics.

    Args:
        data: 1D array of values

    Returns:
        Dictionary with std, iqr, mad, cv, range, min, max
    """
    if len(data) == 0:
        return {
            'std': np.nan,
            'iqr': np.nan,
            'mad': np.nan,
            'cv': np.nan,
            'range': np.nan,
            'min': np.nan,
            'max': np.nan
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) == 0:
        return {
            'std': np.nan,
            'iqr': np.nan,
            'mad': np.nan,
            'cv': np.nan,
            'range': np.nan,
            'min': np.nan,
            'max': np.nan
        }

    mean_val = np.mean(clean_data)
    std_val = np.std(clean_data, ddof=1) if len(clean_data) > 1 else 0.0

    # IQR (Interquartile Range)
    q75, q25 = np.percentile(clean_data, [75, 25])
    iqr = q75 - q25

    # MAD (Median Absolute Deviation)
    median_val = np.median(clean_data)
    mad = np.median(np.abs(clean_data - median_val))

    # Coefficient of Variation
    cv = std_val / mean_val if mean_val != 0 else np.inf

    return {
        'std': float(std_val),
        'iqr': float(iqr),
        'mad': float(mad),
        'cv': float(cv),
        'range': float(np.max(clean_data) - np.min(clean_data)),
        'min': float(np.min(clean_data)),
        'max': float(np.max(clean_data))
    }


def compute_shape_stats(data: np.ndarray) -> Dict:
    """
    Compute distribution shape statistics.

    Args:
        data: 1D array of values

    Returns:
        Dictionary with skewness, kurtosis, normality test results
    """
    if len(data) < 3:
        return {
            'skewness': np.nan,
            'kurtosis': np.nan,
            'is_normal': False,
            'normality_test': 'insufficient_data'
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 3:
        return {
            'skewness': np.nan,
            'kurtosis': np.nan,
            'is_normal': False,
            'normality_test': 'insufficient_data'
        }

    skewness = float(stats.skew(clean_data))
    kurtosis = float(stats.kurtosis(clean_data))

    # Normality test (Shapiro-Wilk for n < 5000, else Anderson-Darling)
    is_normal = False
    test_name = 'none'
    p_value = np.nan

    if len(clean_data) >= 3:
        if len(clean_data) < 5000:
            try:
                statistic, p_value = stats.shapiro(clean_data)
                is_normal = p_value > 0.05
                test_name = 'shapiro_wilk'
            except:
                pass
        else:
            try:
                result = stats.anderson(clean_data, dist='norm')
                # Use 5% significance level (index 2)
                is_normal = result.statistic < result.critical_values[2]
                test_name = 'anderson_darling'
                p_value = float(result.statistic)
            except:
                pass

    return {
        'skewness': skewness,
        'kurtosis': kurtosis,
        'is_normal': is_normal,
        'normality_test': test_name,
        'normality_p_value': float(p_value) if not np.isnan(p_value) else None
    }


def test_stationarity(data: np.ndarray) -> Dict:
    """
    Test if time series is stationary using Augmented Dickey-Fuller test.

    Args:
        data: 1D array of time series values

    Returns:
        Dictionary with stationarity test results
    """
    if len(data) < 10:
        return {
            'is_stationary': None,
            'adf_statistic': np.nan,
            'adf_p_value': np.nan,
            'adf_test': 'insufficient_data'
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 10:
        return {
            'is_stationary': None,
            'adf_statistic': np.nan,
            'adf_p_value': np.nan,
            'adf_test': 'insufficient_data'
        }

    try:
        from statsmodels.tsa.stattools import adfuller

        result = adfuller(clean_data, autolag='AIC')
        adf_statistic = result[0]
        p_value = result[1]

        # p < 0.05 means we reject null hypothesis (non-stationary)
        # So stationary if p < 0.05
        is_stationary = p_value < 0.05

        return {
            'is_stationary': is_stationary,
            'adf_statistic': float(adf_statistic),
            'adf_p_value': float(p_value),
            'adf_test': 'completed'
        }
    except ImportError:
        return {
            'is_stationary': None,
            'adf_statistic': np.nan,
            'adf_p_value': np.nan,
            'adf_test': 'statsmodels_not_available'
        }
    except Exception as e:
        return {
            'is_stationary': None,
            'adf_statistic': np.nan,
            'adf_p_value': np.nan,
            'adf_test': f'error: {str(e)}'
        }


def detect_trend(data: np.ndarray) -> Dict:
    """
    Detect trend in time series using Mann-Kendall test and linear regression.

    Args:
        data: 1D array of time series values

    Returns:
        Dictionary with trend detection results
    """
    if len(data) < 3:
        return {
            'has_trend': False,
            'trend_direction': 'none',
            'trend_slope': 0.0,
            'mk_p_value': np.nan,
            'mk_test': 'insufficient_data'
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 3:
        return {
            'has_trend': False,
            'trend_direction': 'none',
            'trend_slope': 0.0,
            'mk_p_value': np.nan,
            'mk_test': 'insufficient_data'
        }

    # Linear regression for trend slope
    x = np.arange(len(clean_data))
    slope, intercept = np.polyfit(x, clean_data, 1)

    # Mann-Kendall test
    try:
        tau, p_value = stats.kendalltau(x, clean_data)
        has_trend = p_value < 0.05
        trend_direction = 'increasing' if tau > 0 else 'decreasing' if tau < 0 else 'none'

        return {
            'has_trend': has_trend,
            'trend_direction': trend_direction,
            'trend_slope': float(slope),
            'mk_tau': float(tau),
            'mk_p_value': float(p_value),
            'mk_test': 'completed'
        }
    except Exception as e:
        # Fall back to simple slope
        trend_direction = 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'none'
        return {
            'has_trend': abs(slope) > 0.01,  # Arbitrary threshold
            'trend_direction': trend_direction,
            'trend_slope': float(slope),
            'mk_tau': np.nan,
            'mk_p_value': np.nan,
            'mk_test': f'error: {str(e)}'
        }


def compute_autocorrelation(data: np.ndarray, max_lag: int = 5) -> Dict:
    """
    Compute autocorrelation function (ACF) values.

    Args:
        data: 1D array of time series values
        max_lag: Maximum lag to compute (default: 5)

    Returns:
        Dictionary with ACF values and lag-1 autocorrelation
    """
    if len(data) < 10:
        return {
            'acf_values': [],
            'autocorr_lag1': np.nan,
            'ljung_box_p_value': np.nan
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 10:
        return {
            'acf_values': [],
            'autocorr_lag1': np.nan,
            'ljung_box_p_value': np.nan
        }

    try:
        from statsmodels.tsa.stattools import acf
        from statsmodels.stats.diagnostic import acorr_ljungbox

        # Compute ACF
        max_lag = min(max_lag, len(clean_data) // 2 - 1)
        acf_values = acf(clean_data, nlags=max_lag, fft=True)

        # Ljung-Box test for autocorrelation (test if any ACF is significant)
        lb_result = acorr_ljungbox(clean_data, lags=[max_lag], return_df=False)
        lb_p_value = float(lb_result[1][0])

        return {
            'acf_values': [float(x) for x in acf_values[1:]],  # Exclude lag 0 (always 1)
            'autocorr_lag1': float(acf_values[1]) if len(acf_values) > 1 else np.nan,
            'ljung_box_p_value': lb_p_value
        }
    except ImportError:
        # Fall back to simple correlation
        if len(clean_data) > 1:
            lag1_corr = np.corrcoef(clean_data[:-1], clean_data[1:])[0, 1]
        else:
            lag1_corr = np.nan

        return {
            'acf_values': [],
            'autocorr_lag1': float(lag1_corr) if not np.isnan(lag1_corr) else np.nan,
            'ljung_box_p_value': np.nan
        }
    except Exception as e:
        return {
            'acf_values': [],
            'autocorr_lag1': np.nan,
            'ljung_box_p_value': np.nan
        }


def compute_burstiness(data: np.ndarray) -> float:
    """
    Compute burstiness parameter: B = (σ - μ) / (σ + μ)

    B ranges from -1 (regular) to 1 (bursty)
    B ≈ 0: Poisson-like (random)
    B > 0: Bursty (high variance, clustered events)
    B < 0: Regular (low variance, periodic)

    Args:
        data: 1D array of values (e.g., inter-arrival times)

    Returns:
        Burstiness parameter
    """
    if len(data) < 2:
        return 0.0

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 2:
        return 0.0

    mean = np.mean(clean_data)
    std = np.std(clean_data, ddof=1)

    if mean + std == 0:
        return 0.0

    burstiness = (std - mean) / (std + mean)
    return float(burstiness)


def compute_volatility(data: np.ndarray, window: int = 5) -> Dict:
    """
    Compute volatility (rolling standard deviation).

    Args:
        data: 1D array of time series values
        window: Window size for rolling computation

    Returns:
        Dictionary with mean volatility and volatility time series
    """
    if len(data) < window:
        return {
            'mean_volatility': np.nan,
            'volatility_series': []
        }

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < window:
        return {
            'mean_volatility': np.nan,
            'volatility_series': []
        }

    # Rolling standard deviation
    volatility = np.array([
        np.std(clean_data[max(0, i-window+1):i+1], ddof=1)
        for i in range(window-1, len(clean_data))
    ])

    return {
        'mean_volatility': float(np.mean(volatility)),
        'volatility_series': [float(x) for x in volatility]
    }


def compute_spikiness(data: np.ndarray) -> float:
    """
    Compute spikiness as coefficient of variation of first differences.

    High spikiness indicates rapid, large fluctuations.

    Args:
        data: 1D array of time series values

    Returns:
        Spikiness measure
    """
    if len(data) < 2:
        return 0.0

    clean_data = data[~np.isnan(data)]

    if len(clean_data) < 2:
        return 0.0

    # First differences
    diffs = np.diff(clean_data)

    if len(diffs) == 0:
        return 0.0

    mean_diff = np.mean(np.abs(diffs))
    std_diff = np.std(diffs, ddof=1)

    if mean_diff == 0:
        return 0.0

    spikiness = std_diff / mean_diff
    return float(spikiness)


def characterize_timeseries(data: np.ndarray, period_label: str = "") -> Dict:
    """
    Comprehensive time series characterization.

    Computes all statistical properties: location, spread, shape,
    temporal properties, and pattern characteristics.

    Args:
        data: 1D array of time series values
        period_label: Optional label (e.g., "baseline", "fault")

    Returns:
        Dictionary with complete characterization
    """
    if len(data) == 0:
        return {
            'n_samples': 0,
            'period': period_label,
            'location': {},
            'spread': {},
            'shape': {},
            'temporal': {},
            'patterns': {}
        }

    result = {
        'n_samples': len(data),
        'period': period_label,
        'location': compute_location_stats(data),
        'spread': compute_spread_stats(data),
        'shape': compute_shape_stats(data),
        'temporal': {},
        'patterns': {}
    }

    # Temporal properties
    stationarity = test_stationarity(data)
    trend = detect_trend(data)
    acf = compute_autocorrelation(data)

    result['temporal'] = {
        'is_stationary': stationarity.get('is_stationary'),
        'adf_p_value': stationarity.get('adf_p_value'),
        'has_trend': trend.get('has_trend'),
        'trend_direction': trend.get('trend_direction'),
        'trend_slope': trend.get('trend_slope'),
        'mk_p_value': trend.get('mk_p_value'),
        'autocorr_lag1': acf.get('autocorr_lag1'),
        'acf_values': acf.get('acf_values'),
        'ljung_box_p_value': acf.get('ljung_box_p_value')
    }

    # Pattern characteristics
    burstiness = compute_burstiness(data)
    volatility = compute_volatility(data)
    spikiness = compute_spikiness(data)

    result['patterns'] = {
        'burstiness': burstiness,
        'mean_volatility': volatility.get('mean_volatility'),
        'spikiness': spikiness
    }

    return result
