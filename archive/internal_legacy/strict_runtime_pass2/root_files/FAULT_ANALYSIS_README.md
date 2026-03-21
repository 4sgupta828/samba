# Fault Propagation Analysis Tool

Analyzes how faults propagate through distributed system topologies and affect dependent services.

## Overview

This tool analyzes episode data to trace how a fault in a root cause component propagates through the system's dependency graph, affecting metrics of all dependent nodes. It provides:

- **Layered analysis**: Shows impact at each hop from the root cause
- **Quantified impact**: Reports latency multipliers, throughput changes, etc.
- **Timeline tracking**: Analyzes metrics at key time points during fault injection
- **Dependency chains**: Identifies which services are affected and how

## Usage

### Basic Usage

```bash
python analyze_fault_propagation.py <episode_directory>
```

Example:
```bash
python analyze_fault_propagation.py data/data_20251125_092902/ep_1
```

### JSON Output

For programmatic analysis or visualization:

```bash
python analyze_fault_propagation.py data/data_20251125_092902/ep_1 --json > analysis.json
```

## What It Analyzes

### 1. Root Cause Impact

The tool identifies the root cause node from `label.json` and analyzes its baseline vs fault metrics:

- Database: Query latency, connections, CPU utilization
- Service: Request duration, dependency latencies, thread pool metrics
- Cache: Hit rate, miss rate
- Gateway: Request duration, dependency calls

### 2. Propagation Layers

Dependencies are organized into layers by distance from root cause:

- **Layer 0**: The root cause node itself
- **Layer 1**: Services directly depending on root cause
- **Layer 2**: Services depending on Layer 1 services
- And so on...

### 3. Metrics Tracked

For each affected node, the tool tracks:

- **Latency metrics**: p50, p90, p99 response times
- **Resource metrics**: CPU utilization, memory usage
- **Concurrency metrics**: Thread pool active threads, queue depths
- **Connection metrics**: Active connections, connection pool utilization

### 4. Impact Quantification

Changes are reported as:
- **Multipliers**: e.g., "3.4x" means latency increased 3.4 times
- **Percentages**: e.g., "+245%" change from baseline
- **Absolute values**: Shows baseline → fault values

## Example Output

```
================================================================================
FAULT PROPAGATION ANALYSIS
================================================================================
Episode: 1
Scenario: Database query slowdown
Root Cause: db_1 (database)
Fault Type: slow_queries
Timeline: Fault starts at 120s, full effect at 360s
================================================================================

Found 6 nodes in dependency chain

────────────────────────────────────────────────────────────────────────────────
LAYER 0: ROOT CAUSE
────────────────────────────────────────────────────────────────────────────────
Nodes: db_1

📊 db_1 (SqlDatabase)
   ──────────────────────────────────────────────────────────────────────

   Metric: db.query.latency
   📈 At t=140s: p50
      Baseline: 19.39
      Fault:    355.90
      Change:   18.4x (+1735.4%)

────────────────────────────────────────────────────────────────────────────────
LAYER 1: 1 hop(s) from root cause
────────────────────────────────────────────────────────────────────────────────
Nodes: svc_1, svc_3, svc_5

📊 svc_1 (Service)
   ──────────────────────────────────────────────────────────────────────

   Metric: service.svc_1.duration
   📈 At t=140s: p90
      Baseline: 862.20
      Fault:    2957.08
      Change:   3.4x (+243.0%)

   Metric: service.svc_1.dependency.duration
   📈 At t=140s: p50
      Baseline: 84.26
      Fault:    505.90
      Change:   6.0x (+500.4%)
```

## Understanding the Results

### Propagation Chain

The analysis shows how impact cascades through layers:

1. **Root cause**: Database queries slow from 19ms → 356ms (18.4x)
2. **Layer 1**: Services calling the database see their dependency calls slow 6-7x
3. **Layer 2**: Gateway sees end-to-end latency increase 4.6x as it calls Layer 1 services

### Key Indicators

- **High multipliers** (>5x): Severe impact, service likely experiencing failures
- **Moderate multipliers** (2-5x): Significant degradation, user-visible impact
- **Low multipliers** (<2x): Minor impact, may be within acceptable bounds

### Thread Pool Exhaustion

If you see thread pool metrics drop dramatically (e.g., from 30+ active threads to 1), this indicates:
- Slow operations are tying up all worker threads
- New requests cannot be processed
- Service is effectively blocked

## Episode Directory Structure

The tool expects this structure:

```
episode_directory/
├── label.json           # Fault metadata (root cause, type, timeline)
├── topology.json        # System topology (nodes, edges, dependencies)
└── metrics.jsonl        # Time-series metrics for all components
```

## Integration with Other Tools

### Visualization

The JSON output can be consumed by visualization tools:

```bash
python analyze_fault_propagation.py ep_1 --json | jq '.propagation'
```

### Batch Analysis

Analyze multiple episodes:

```bash
for ep in data/*/ep_*; do
    echo "Analyzing $ep"
    python analyze_fault_propagation.py "$ep" --json > "${ep}_analysis.json"
done
```

### Comparison

Compare impact across different fault types:

```bash
grep -r "multiplier" */ep_*_analysis.json | sort -t: -k3 -nr
```

## Troubleshooting

### No metrics found

If you see "No significant metric changes detected" for nodes that should be affected:

1. Check that metrics.jsonl exists and contains data
2. Verify the time range includes both baseline and fault periods
3. Ensure node IDs in topology.json match component.id in metrics

### Incomplete dependency chain

If expected dependencies are missing:

1. Verify topology.json edges are correctly defined
2. Check that edge types are not in the filtered list (pod_pool, pod_placement are skipped)
3. Ensure the max_depth parameter (default: 5) is sufficient

### Large files causing memory issues

For very large metrics files:

1. The tool loads all metrics into memory for fast access
2. Consider filtering metrics.jsonl by time range before analysis
3. Use `jq` to pre-filter to relevant components

## Advanced Usage

### Custom Time Points

Edit the `fault_times` list in `analyze_propagation_chain()` to analyze different time points:

```python
fault_times = [
    fault_start_time,
    fault_start_time + 10,   # 10s after start
    fault_start_time + 30,   # 30s after start
    fault_full_effect_time,  # Full effect
]
```

### Additional Metrics

Add metrics to the `metrics_to_check` dictionary for new node types:

```python
"CustomService": [
    "custom.metric.name",
    "custom.{}.pattern"
]
```

## See Also

- `generate_dataset.py`: Generates episode data with fault injection
- `viz/app.py`: Web-based visualization of propagation
- Episode data format documentation
