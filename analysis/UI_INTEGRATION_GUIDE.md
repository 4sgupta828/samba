# UI Integration Guide: Hide Healthy Nodes Feature

## Overview

The "Hide Healthy Nodes" checkbox in the UI now uses the new statistical impact analyzer to intelligently filter out nodes that were not impacted by the fault.

## How It Works

### 1. Node Classification

When you load an episode, the analyzer classifies each node into one of three categories:

- **Impacted** (impact_score < 0.3): Node showed measurable degradation
- **Healthy** (impact_score > 0.7): Node metrics remained stable
- **Uncertain** (0.3 ≤ score ≤ 0.7): Mixed signals or insufficient data

### 2. Hide Healthy Nodes

When you check "Hide Healthy Nodes" in the UI:
- ✅ Nodes classified as **Healthy** are hidden from the graph
- ✅ Nodes classified as **Impacted** remain visible
- ✅ Nodes classified as **Uncertain** remain visible (conservative approach)

### 3. UI Display

The info bar shows:
```
Showing full topology (25 nodes) | Impacted: 5, Healthy: 15, Uncertain: 5 (15 healthy nodes hidden)
```

## Configuring the Threshold

The "healthy" threshold determines which nodes get hidden. You can tune this in **`analysis/impact_config.py`**.

### Default Configuration

```python
@dataclass
class ImpactScoringConfig:
    impacted_threshold: float = 0.3  # Below this = impacted
    healthy_threshold: float = 0.7   # Above this = healthy
```

### Adjusting the Threshold

#### Option 1: Edit Config File (Recommended)

Edit `analysis/impact_config.py`:

```python
@dataclass
class ImpactScoringConfig:
    impacted_threshold: float = 0.3
    healthy_threshold: float = 0.8  # Changed from 0.7
```

**Effect:**
- Higher threshold (0.8) = **More conservative** = Fewer nodes classified as healthy = Less hiding
- Lower threshold (0.6) = **More aggressive** = More nodes classified as healthy = More hiding

#### Option 2: Programmatic Override

Edit `viz/data_loader.py` around line 334:

```python
from analysis.impact_config import create_custom_config

# Create custom config
custom_config = create_custom_config(
    scoring={
        'healthy_threshold': 0.75,  # Custom threshold
        'impacted_threshold': 0.25
    }
)

health_analysis = detect_node_impacts(
    metrics_df=metrics_df,
    graph=topology_graph,
    label_data=label,
    config=custom_config  # Use custom config
)
```

## Examples

### Example 1: More Aggressive Hiding

**Goal:** Hide more nodes to focus on clearly impacted ones

```python
# In analysis/impact_config.py
healthy_threshold: float = 0.6  # Lower threshold
```

**Result:**
- Before: 10 nodes hidden (very confident they're healthy)
- After: 18 nodes hidden (moderately confident they're healthy)

### Example 2: More Conservative (Show More Nodes)

**Goal:** Only hide nodes we're very confident are healthy

```python
# In analysis/impact_config.py
healthy_threshold: float = 0.85  # Higher threshold
```

**Result:**
- Before: 10 nodes hidden
- After: 3 nodes hidden (only hide when extremely confident)

### Example 3: Custom Metric Weights

If you want cache metrics to be considered more important (affecting classification):

```python
# In analysis/impact_config.py
@dataclass
class MetricWeights:
    cache_metrics: float = 0.6  # Increased from 0.3
    hit_rate_metrics: float = 0.7  # Increased from 0.4
```

## Understanding Impact Scores

The impact score is computed from statistical analysis of ALL available metrics:

| Score | Meaning | Example |
|-------|---------|---------|
| 0.0 - 0.2 | Strong evidence of impact | Multiple metrics show significant degradation |
| 0.2 - 0.3 | Moderate evidence | Some metrics degraded with good confidence |
| 0.3 - 0.5 | Weak/mixed signals | Unclear or conflicting evidence |
| 0.5 - 0.7 | Likely healthy | Most metrics stable, weak evidence of impact |
| 0.7 - 0.9 | Strong evidence healthy | Metrics stable with high confidence |
| 0.9 - 1.0 | Very strong evidence | All metrics completely stable |

## Tuning Recommendations

### Scenario 1: Training RCA Models

**Goal:** Generate high-quality training data with clear labels

**Recommendation:**
```python
scoring={
    'healthy_threshold': 0.75,  # Conservative - only hide clearly healthy
    'impacted_threshold': 0.25   # Aggressive - catch any potential impact
}
```

**Why:** Better to include borderline nodes in training than to miss actually impacted nodes.

### Scenario 2: Incident Analysis

**Goal:** Quickly identify the propagation path

**Recommendation:**
```python
scoring={
    'healthy_threshold': 0.65,  # Aggressive - hide more
    'impacted_threshold': 0.35   # Conservative - focus on clear impacts
}
```

**Why:** Focus on nodes that clearly show impact to trace propagation.

### Scenario 3: Debugging/Research

**Goal:** Understand analyzer behavior

**Recommendation:**
```python
scoring={
    'healthy_threshold': 0.5,  # Make everything impacted or healthy
    'impacted_threshold': 0.5
}
config.verbose = True  # Enable detailed logging
```

**Why:** Eliminate "uncertain" category to force binary classification.

## Checking Current Configuration

To see what thresholds are currently being used:

```python
# In Python or Jupyter notebook
from analysis.impact_config import get_config

config = get_config()
print(f"Healthy threshold: {config.scoring.healthy_threshold}")
print(f"Impacted threshold: {config.scoring.impacted_threshold}")
```

Or check the UI info bar - it shows the config used:

```
Impacted: 5, Healthy: 15, Uncertain: 5
```

## Advanced: Runtime Configuration

For experiments, you can create different configs for different scenarios:

```python
# In viz/data_loader.py

# Choose config based on use case
USE_CASE = "incident_analysis"  # or "training", "debugging"

if USE_CASE == "training":
    config = create_custom_config(
        scoring={'healthy_threshold': 0.75, 'impacted_threshold': 0.25}
    )
elif USE_CASE == "incident_analysis":
    config = create_custom_config(
        scoring={'healthy_threshold': 0.65, 'impacted_threshold': 0.35}
    )
else:
    config = None  # Use defaults

health_analysis = detect_node_impacts(..., config=config)
```

## Testing Your Configuration

Use the test script to see how different thresholds affect classification:

```bash
python test_ui_integration.py
```

This shows how many nodes fall into each category with your current config.

## Summary

✅ **Default behavior:** Hides nodes with impact_score > 0.7 (high confidence healthy)

✅ **Configurable:** Edit `analysis/impact_config.py` to tune threshold

✅ **Conservative by default:** Shows uncertain nodes (better to show false positive than hide false negative)

✅ **Metric-agnostic:** Uses ALL available metrics, not just latency and errors

✅ **Statistical rigor:** Based on hypothesis testing and effect sizes, not arbitrary thresholds
