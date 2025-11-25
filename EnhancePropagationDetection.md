# Enhanced Fault Propagation Detection - SOTA Approach

## Problem Statement

The current `analyze_fault_propagation.py` uses a simplistic approach:
- Picks 5 arbitrary time points (baseline, fault_start+20, mid-ramp, etc.)
- Compares means at these snapshots
- Uses simple multiplier-based assessment
- Doesn't capture pattern changes (spikiness, variance, autocorrelation)
- No statistical rigor

**This is insufficient for validating fault injection quality and training GNN models for RCA.**

## Goal

Given a root cause from `label.json`, map out the effect of that fault on **all connected nodes** in the topology with:
- **Quantitative metrics** (not just multipliers)
- Analysis of **all metrics** at all nodes
- **Ranked list** of impacted metrics per node
- **Detailed impact measures** using SOTA statistical methods
- Analysis **centered from root cause outward** (graph-aware)

This will validate that the fault injection system produces high-quality training data for GNN-based RCA models.

---

## Proposed SOTA Approach

### 1. Baseline Characterization

For each metric in baseline period (0 to fault_start_time), compute:

#### Location Statistics
- Mean, median, trimmed mean (10%)
- Mode (for multimodal distributions)

#### Spread Statistics
- Standard deviation, IQR (Interquartile Range)
- MAD (Median Absolute Deviation)
- Coefficient of Variation (CV = σ/μ)
- Range, min, max

#### Distribution Shape
- Skewness (asymmetry)
- Kurtosis (tail heaviness)
- Normality tests: Shapiro-Wilk, Anderson-Darling

#### Temporal Properties
- Autocorrelation Function (ACF) - detect temporal dependencies
- Partial Autocorrelation (PACF)
- Stationarity test: Augmented Dickey-Fuller (ADF)
- Trend detection: Mann-Kendall test

#### Pattern Characteristics
- Burstiness parameter: B = (σ - μ) / (σ + μ)
- Volatility: rolling standard deviation
- Spikiness: CV of first differences
- Sample entropy: predictability measure

### 2. Fault State Characterization

Compute identical statistics for fault period (fault_start_time to end).

### 3. Multi-Dimensional Change Detection

#### A. Location Shift Detection
- **Mann-Whitney U test**: Non-parametric test for distribution shift
- **Welch's t-test**: If data is approximately normal
- **Kolmogorov-Smirnov test**: Full distribution comparison
- **Permutation test**: Robust alternative

**Output**: p-value, test statistic, significance (α = 0.05)

#### B. Scale Shift Detection
- **Levene's test**: Variance change detection
- **Ansari-Bradley test**: Non-parametric scale test
- **Mood's median test**: Robust scale comparison

**Output**: Variance ratio, p-value, significance

#### C. Distribution Shape Change
- **Kullback-Leibler divergence**: Information-theoretic distance
- **Wasserstein distance**: Earth Mover's Distance
- **Anderson-Darling two-sample test**: Sensitive to tail differences

**Output**: Distance measures, divergence values

#### D. Pattern Change Detection
- **Autocorrelation change**: Compare ACF structures (Ljung-Box test)
- **Volatility change**: Compare rolling variance
- **Spectral analysis**: Power Spectral Density (PSD) comparison
- **Entropy change**: Sample entropy, approximate entropy

**Output**: ACF distance, volatility ratio, spectral divergence, entropy change

#### E. Changepoint Detection
- **PELT** (Pruned Exact Linear Time): Optimal changepoint location
- **Binary Segmentation**: Fast approximate detection
- **E-Divisive**: Non-parametric changepoint detection
- **Bayesian Changepoint**: With uncertainty quantification

**Output**: Changepoint time, confidence, detection method

### 4. Effect Size Quantification

#### Magnitude Measures
- **Cohen's d**: (μ_fault - μ_baseline) / σ_pooled
  - Small: 0.2, Medium: 0.5, Large: 0.8
- **Cliff's delta**: Non-parametric effect size
- **Glass's delta**: Use baseline σ only
- **Hedge's g**: Bias-corrected Cohen's d

#### Percentage Changes
- Mean shift: (μ_fault - μ_baseline) / μ_baseline × 100%
- Median shift: (median_fault - median_baseline) / median_baseline × 100%
- Variance ratio: σ²_fault / σ²_baseline
- IQR ratio: IQR_fault / IQR_baseline

#### Distribution Distances
- **KL divergence**: Quantifies information loss
- **Wasserstein distance**: "Work" to transform distributions
- **Jensen-Shannon divergence**: Symmetric version of KL

#### Pattern Change Scores
- **Autocorrelation distance**: Sum of squared differences in ACF
- **Spectral divergence**: Compare power spectral densities
- **Volatility ratio**: σ_rolling_fault / σ_rolling_baseline
- **Burstiness change**: B_fault - B_baseline

### 5. Graph-Aware Fault Propagation Analysis

#### Algorithm

```
1. Load topology graph from topology.json
2. Identify root_cause_node from label.json
3. BFS traversal by hop distance from root cause:

   For each node at distance d:
     a. Extract ALL available metrics for this node

     b. For EACH metric:
        i.   Split time series into baseline/fault periods
        ii.  Compute baseline characterization (all stats)
        iii. Compute fault characterization (all stats)
        iv.  Run all change detection tests
        v.   Compute all effect sizes
        vi.  Detect changepoints
        vii. Assign impact severity score

     c. Rank metrics by composite impact score
     d. Generate detailed impact report

4. Track propagation timing:
   - When did each node first show statistically significant impact?
   - What was the delay from root cause?
   - How does impact correlate with graph distance?

5. Generate propagation graph with quantitative edge weights
```

#### Impact Severity Score (Composite)

```python
severity_score = weighted_sum([
    statistical_significance_score,  # From p-values of tests
    effect_size_score,              # Normalized Cohen's d, Cliff's delta
    distribution_distance_score,     # Normalized KL, Wasserstein
    pattern_change_score,           # ACF distance, volatility change
    metric_criticality_weight       # error=1.0, latency=0.9, resource=0.4
])
```

**Score ranges**: 0.0 (no impact) to 1.0 (maximum impact)

**Classification**:
- `severity >= 0.7`: CRITICAL
- `0.5 <= severity < 0.7`: HIGH
- `0.3 <= severity < 0.5`: MEDIUM
- `0.1 <= severity < 0.3`: LOW
- `severity < 0.1`: NEGLIGIBLE

### 6. Output Format

#### Per-Node Report

```json
{
  "node_id": "svc_2",
  "node_type": "Service",
  "distance_from_root": 1,
  "first_impact_time": 125.0,
  "impact_delay_seconds": 5.0,
  "overall_severity": "HIGH",
  "overall_severity_score": 0.78,

  "metrics": [
    {
      "metric_name": "service.svc_2.duration.p99",
      "rank": 1,
      "severity_score": 0.92,
      "severity_class": "CRITICAL",

      "baseline": {
        "period": [0, 120],
        "n_samples": 24,
        "location": {
          "mean": 45.2,
          "median": 43.1,
          "trimmed_mean": 44.8
        },
        "spread": {
          "std": 8.3,
          "iqr": 12.1,
          "mad": 6.2,
          "cv": 0.18
        },
        "shape": {
          "skewness": 0.3,
          "kurtosis": 2.8,
          "is_normal": true
        },
        "temporal": {
          "is_stationary": true,
          "has_trend": false,
          "trend_slope": 0.02,
          "autocorr_lag1": 0.12,
          "burstiness": -0.05
        }
      },

      "fault": {
        "period": [120, 600],
        "n_samples": 96,
        "location": {
          "mean": 152.8,
          "median": 148.3,
          "trimmed_mean": 151.2
        },
        "spread": {
          "std": 42.1,
          "iqr": 58.3,
          "mad": 31.2,
          "cv": 0.28
        },
        "shape": {
          "skewness": 0.8,
          "kurtosis": 3.4,
          "is_normal": false
        },
        "temporal": {
          "is_stationary": false,
          "has_trend": true,
          "trend_slope": 0.15,
          "autocorr_lag1": 0.45,
          "burstiness": 0.21
        }
      },

      "changes": {
        "location_shift": {
          "mann_whitney_u": {
            "statistic": 234.0,
            "p_value": 0.0001,
            "significant": true
          },
          "welch_t_test": {
            "statistic": 12.3,
            "p_value": 0.0001,
            "significant": true
          },
          "cohens_d": 3.2,
          "cohens_d_interpretation": "large",
          "cliffs_delta": 0.85,
          "mean_pct_change": 238.1,
          "median_pct_change": 244.0
        },

        "scale_shift": {
          "levene_test": {
            "statistic": 18.5,
            "p_value": 0.0003,
            "significant": true
          },
          "variance_ratio": 25.7,
          "iqr_ratio": 4.8,
          "cv_change": 0.10
        },

        "distribution_shift": {
          "ks_test": {
            "statistic": 0.82,
            "p_value": 0.0001,
            "significant": true
          },
          "kl_divergence": 2.45,
          "wasserstein_distance": 107.6,
          "anderson_darling": {
            "statistic": 12.3,
            "p_value": 0.0001,
            "significant": true
          }
        },

        "pattern_changes": {
          "autocorr_distance": 0.33,
          "volatility_ratio": 5.1,
          "spectral_divergence": 1.2,
          "burstiness_change": 0.26,
          "entropy_change": -0.45,
          "interpretation": "Became more volatile and bursty, less predictable"
        },

        "changepoint": {
          "detected": true,
          "time": 123.5,
          "delay_from_fault": 3.5,
          "confidence": 0.95,
          "method": "PELT"
        }
      },

      "interpretation": "Latency increased 3.2x with high statistical significance. Variance increased 25x indicating instability. Pattern became bursty and unpredictable."
    }
    // ... more metrics ranked by severity
  ],

  "summary": {
    "total_metrics_analyzed": 15,
    "metrics_with_critical_impact": 3,
    "metrics_with_high_impact": 5,
    "metrics_with_medium_impact": 4,
    "metrics_with_low_impact": 2,
    "metrics_unchanged": 1,
    "primary_impact_type": "latency_degradation",
    "secondary_impact_type": "variance_increase",
    "tertiary_impact_type": "error_rate_increase"
  }
}
```

#### Propagation Summary

```json
{
  "episode_id": "ep_0",
  "root_cause": {
    "node_id": "ext_0",
    "node_type": "ExternalService",
    "fault_type": "inject_errors",
    "fault_start_time": 120,
    "fault_params": {"error_rate": 0.3}
  },

  "propagation_statistics": {
    "total_nodes_analyzed": 40,
    "nodes_critically_impacted": 5,
    "nodes_highly_impacted": 8,
    "nodes_moderately_impacted": 12,
    "nodes_unimpacted": 15,

    "impact_by_distance": {
      "0": {"critical": 1, "high": 0, "medium": 0, "low": 0},
      "1": {"critical": 2, "high": 3, "medium": 2, "low": 1},
      "2": {"critical": 1, "high": 3, "medium": 5, "low": 2},
      "3": {"critical": 1, "high": 2, "medium": 5, "low": 4}
    },

    "propagation_timing": {
      "first_impact_time": 123.5,
      "first_impact_node": "svc_6",
      "median_propagation_delay": 8.2,
      "max_propagation_delay": 45.0
    }
  },

  "node_reports": [
    // Per-node reports as above
  ],

  "validation": {
    "fault_injection_working": true,
    "root_cause_clearly_impacted": true,
    "propagation_detected": true,
    "blast_radius": 25,
    "quality_score": 0.85,
    "issues": []
  }
}
```

---

## Implementation Architecture

### Module Structure

```
analysis/
├── timeseries_stats.py          # Time series statistical analysis
├── distribution_analysis.py     # Distribution comparison methods
├── changepoint_detection.py     # Changepoint detection algorithms
├── effect_size.py               # Effect size calculations
├── pattern_analysis.py          # ACF, spectral, entropy analysis
├── metric_impact_analyzer.py    # Per-metric impact analysis
├── propagation_analyzer.py      # Graph-aware propagation analysis
├── reporting.py                 # Output formatting and visualization
└── config.py                    # Configuration and thresholds
```

### Core Dependencies

**Essential**:
- `numpy`: Array operations, basic statistics
- `scipy`: Statistical tests (mannwhitneyu, levene, ks_2samp, etc.)
- `pandas`: Time series manipulation
- `statsmodels`: Time series analysis (ACF, PACF, ADF test)
- `ruptures`: Changepoint detection (PELT, Binary Segmentation)
- `networkx`: Graph operations

**Optional/Advanced**:
- `pyentrp`: Entropy measures (sample entropy, approximate entropy)
- `pyts`: Advanced time series features
- `arch`: GARCH models for volatility analysis

---

## Advantages Over Current Approach

| Aspect | Current (analyze_fault_propagation.py) | New (SOTA) |
|--------|----------------------------------------|------------|
| **Temporal** | 5 arbitrary snapshots | Full time series analysis |
| **Location** | Simple mean comparison | Mean, median, trimmed mean + tests |
| **Spread** | Not analyzed | Std, IQR, MAD, CV, variance tests |
| **Distribution** | Not analyzed | KL divergence, Wasserstein, K-S test |
| **Patterns** | Not analyzed | ACF, spectral, entropy, burstiness |
| **Changepoints** | Not detected | PELT, Binary Seg, Bayesian |
| **Effect Size** | Simple multiplier | Cohen's d, Cliff's delta, Glass's delta |
| **Statistics** | No hypothesis tests | Multiple tests with p-values |
| **Output** | Vague "HIGH/MEDIUM" | Quantitative scores with interpretation |
| **Graph-aware** | Basic BFS | Propagation timing, delay analysis |

**Result**:
- ✅ Validates fault injection quality
- ✅ Provides rich training data for GNN models
- ✅ Enables debugging of fault propagation
- ✅ Publishable with SOTA methods

---

## Testing Strategy

1. **Unit Tests**: Test each statistical method independently
2. **Synthetic Data**: Test on known distributions and changes
3. **Real Episodes**: Validate on actual episode data
4. **Comparison**: Compare results with existing impact_analyzer.py
5. **Performance**: Ensure analysis completes in reasonable time

---

## Success Criteria

✅ **Statistical Rigor**: Multiple hypothesis tests with proper p-values
✅ **Comprehensive**: Captures location, scale, shape, and pattern changes
✅ **Quantitative**: Precise effect sizes, not vague multipliers
✅ **Graph-Aware**: Propagation analysis from root cause outward
✅ **Timing-Aware**: Detects when impact started (changepoint)
✅ **Ranked Output**: Prioritizes most severely impacted metrics
✅ **Actionable**: Can validate fault injection quality
✅ **Scalable**: Works on episodes with 40+ nodes, 1000+ time points

---

## Future Enhancements

- **Causal Analysis**: Granger causality tests for propagation paths
- **Forecasting**: ARIMA/Prophet to predict expected values
- **Anomaly Detection**: Isolation Forest, LOF for outlier detection
- **Multi-Episode Analysis**: Learn typical propagation patterns
- **Auto-Tuning**: Learn optimal thresholds from labeled data
- **Visualization**: Interactive propagation graphs with time sliders
- **Real-Time**: Streaming changepoint detection
