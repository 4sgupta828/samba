# Impact Analysis System

Comprehensive, metric-agnostic statistical system for detecting which nodes are impacted by faults in distributed systems.

## Overview

This system **automatically discovers and analyzes ALL available metrics** for each node to determine if it was impacted by a fault, using rigorous statistical methods instead of arbitrary thresholds.

## Key Features

- **✅ Metric-Agnostic**: Automatically discovers all metrics for each node (no hard-coding)
- **✅ Statistical Rigor**: Uses hypothesis testing, effect size calculation, and confidence scoring
- **✅ Intelligent Weighting**: Critical metrics (errors, timeouts) weighted higher than cache metrics
- **✅ Baseline Validation**: Checks if baseline period is stable before comparison
- **✅ Multi-Signal Fusion**: Combines evidence from multiple metrics
- **✅ Configurable**: All thresholds in centralized config file

## Architecture

### Modules

1. **`impact_config.py`** - Centralized configuration for all thresholds and parameters
2. **`statistical_utils.py`** - Statistical helper functions (hypothesis tests, effect size, etc.)
3. **`impact_analyzer.py`** - Main analyzer that orchestrates the analysis

### Improvements Over Old System

| Aspect | Old (`viz/health_analyzer.py`) | New (`analysis/impact_analyzer.py`) |
|--------|--------------------------------|-------------------------------------|
| **Metrics** | Hard-coded latency + error_rate | Auto-discovers ALL metrics |
| **Statistics** | Simple mean comparison | Hypothesis testing + effect size |
| **Baseline** | Assumed valid | Validates stability first |
| **Thresholds** | Hard-coded 15% | Configurable, evidence-based |
| **Output** | Binary healthy/impacted | Continuous score + confidence |
| **Missing Data** | Assumes healthy | Conservative scoring |
| **Location** | UI (`viz/`) | Backend (`analysis/`) |

## Usage

### Basic Usage

```python
from analysis.impact_analyzer import detect_node_impacts
import pandas as pd
import networkx as nx

# Load your data
metrics_df = pd.read_json('metrics.jsonl', lines=True)
graph = nx.DiGraph()  # Your topology graph
label_data = {
    'root_cause_node': 'service-auth',
    'fault_start_time': 30.0
}

# Run analysis
results = detect_node_impacts(
    metrics_df=metrics_df,
    graph=graph,
    label_data=label_data
)

# Get results
print(f"Impacted nodes: {results['impacted_nodes']}")
print(f"Healthy nodes: {results['healthy_nodes']}")
print(f"Uncertain nodes: {results['uncertain_nodes']}")

# Detailed per-node results
for node_id, node_result in results['node_results'].items():
    print(f"{node_id}: {node_result.classification} "
          f"(score={node_result.impact_score:.2f}, "
          f"confidence={node_result.confidence})")
```

### Custom Configuration

```python
from analysis.impact_config import create_custom_config
from analysis.impact_analyzer import detect_node_impacts

# Create custom config with stricter thresholds
config = create_custom_config(
    statistical={
        'alpha': 0.01,  # More stringent significance level
        'min_effect_size': 0.5  # Require medium effect size
    },
    scoring={
        'impacted_threshold': 0.25,  # More sensitive to impact
        'healthy_threshold': 0.75
    }
)

# Run with custom config
results = detect_node_impacts(
    metrics_df=metrics_df,
    graph=graph,
    label_data=label_data,
    config=config
)
```

### Verbose Mode (for Debugging)

```python
from analysis.impact_config import get_config

config = get_config()
config.verbose = True

results = detect_node_impacts(
    metrics_df=metrics_df,
    graph=graph,
    label_data=label_data,
    config=config
)
```

## Configuration Reference

### Statistical Parameters (`config.statistical`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `alpha` | 0.05 | Significance level for hypothesis tests |
| `min_effect_size` | 0.3 | Minimum Cohen's d to consider meaningful |
| `baseline_cv_max` | 0.5 | Max coefficient of variation for stable baseline |
| `baseline_trend_max` | 0.3 | Max Kendall tau for trend detection |
| `min_samples_before` | 10 | Minimum samples in baseline period |
| `min_samples_after` | 10 | Minimum samples in fault period |

### Metric Weights (`config.metric_weights`)

| Metric Type | Default Weight | Examples |
|-------------|----------------|----------|
| Error metrics | 1.0 (highest) | `error_rate`, `component.errors.total` |
| Rejection metrics | 1.0 | `db.connections.rejected`, `refused` |
| Latency p99 | 0.9 | `latency_p99`, `duration_p99` |
| Queue depth | 0.7 | `thread_pool.queue`, `connection_pool.queue_depth` |
| CPU/Memory | 0.4 | `cpu.usage`, `memory.usage` |
| Cache metrics | 0.3 (lowest) | `cache.hit_rate` |

### Scoring Parameters (`config.scoring`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `impacted_threshold` | 0.3 | Below this = impacted |
| `healthy_threshold` | 0.7 | Above this = healthy |
| `min_metrics_for_high_confidence` | 3 | Metrics needed for high confidence |

## Statistical Methods

### 1. Baseline Stability Validation

Before comparing periods, validates that baseline is stable using:
- **Coefficient of Variation (CV)**: Measures relative variability
- **Kendall's Tau**: Detects trends in baseline

### 2. Distribution Shift Detection

Tests if distributions are significantly different:
- **Mann-Whitney U Test** (default): Non-parametric, robust to non-normal data
- **Independent t-test**: For normally distributed data

### 3. Effect Size Calculation

Measures magnitude of change using **Cohen's d**:
- 0.2 = small effect
- 0.5 = medium effect
- 0.8 = large effect

### 4. Variance Testing

Detects if variance increased (instability) using **Levene's test**

### 5. Change Point Detection

Detects structural breaks in time series using **ruptures** library (optional)

### 6. Multi-Metric Aggregation

Combines evidence from multiple metrics using weighted voting:
- Each metric contributes based on importance weight
- Confidence level scales contribution
- Multiple weak signals combine into strong signal

## Output Format

### Top-Level Results

```python
{
    'healthy_nodes': {'node1', 'node2', ...},
    'impacted_nodes': {'root_cause', 'downstream', ...},
    'uncertain_nodes': {'node_with_mixed_signals', ...},
    'node_scores': {'node1': 0.85, 'node2': 0.15, ...},
    'node_results': {...}  # Detailed per-node results
}
```

### Per-Node Result

```python
NodeImpactResult(
    node_id='service-auth',
    impact_score=0.12,  # 0=impacted, 1=healthy
    classification='impacted',
    confidence='high',
    metrics_analyzed=['latency_p99', 'error_rate', 'cpu.usage', ...],
    metric_results={
        'latency_p99': MetricAnalysisResult(
            metric_name='latency_p99',
            impact_score=0.15,
            confidence='high',
            evidence={
                'statistically_significant': True,
                'p_value': 0.001,
                'effect_size': 1.2,  # Large effect
                'direction': 'increase',
                'matches_degradation': True,
                ...
            },
            statistics={
                'before_mean': 45.2,
                'after_mean': 152.8,
                'pct_change': 238.1,
                ...
            }
        ),
        ...
    },
    reason='statistical_analysis'
)
```

## Integration with Existing Code

### ✅ Already Integrated in `viz/data_loader.py`

The new analyzer is already integrated and being used:

```python
# Current implementation (lines 321-327):
from analysis.impact_analyzer import detect_node_impacts
health_analysis = detect_node_impacts(
    metrics_df=metrics_df,
    graph=topology_graph,
    label_data=label,
    config=None  # Uses default config from analysis/impact_config.py
)
```

The analyzer returns results with additional features:
- Topology-aware analysis (checks graph reachability)
- Entry point detection (gateway nodes never hidden)
- Three-way classification (healthy/impacted/uncertain)

## Dependencies

- `numpy`
- `pandas`
- `scipy`
- `networkx`
- `ruptures` (optional, for change point detection)

Install missing dependencies:
```bash
pip install ruptures
```

## Tuning Guide

### If Too Many False Positives (nodes marked impacted but aren't):

1. Increase `scoring.impacted_threshold` (e.g., 0.3 → 0.25)
2. Increase `statistical.min_effect_size` (e.g., 0.3 → 0.5)
3. Decrease metric weights for less critical metrics

### If Too Many False Negatives (impacted nodes marked healthy):

1. Decrease `scoring.impacted_threshold` (e.g., 0.3 → 0.4)
2. Decrease `statistical.min_effect_size` (e.g., 0.3 → 0.2)
3. Increase `statistical.alpha` (e.g., 0.05 → 0.10) for more lenient tests

### If Too Many Uncertain Nodes:

1. Adjust `scoring.healthy_threshold` and `scoring.impacted_threshold` closer together
2. Lower `scoring.min_metrics_for_high_confidence`

## Future Enhancements

- [ ] Parallel processing for large graphs
- [ ] Auto-tuning based on historical data
- [x] Integration with graph topology (use distance from root cause as prior) ✅ **Implemented**
- [x] Gateway/entry point detection (never hide critical nodes) ✅ **Implemented**
- [ ] Time-series forecasting for expected values
- [ ] Anomaly detection algorithms (Isolation Forest, LOF)
- [ ] Export results for ML training pipelines
- [ ] Aggregate metrics from compute agents to parent services
