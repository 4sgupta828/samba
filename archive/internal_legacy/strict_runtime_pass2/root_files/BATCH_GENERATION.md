# Batch Dataset Generation Guide

This guide explains how to use the `batch_generate_datasets.py` script to generate comprehensive datasets for GNN training across all fault types and topologies.

## Overview

The batch generation script automates dataset generation by:
- Iterating through all fault types from the scenario library
- Testing each fault type against all topologies in the topology bank
- Handling timeouts (10-minute default per run)
- Recovering from failures gracefully
- Tracking progress and logging results
- Saving failed runs for later retry

## Fault Types Covered

The script covers 16 fault configurations across 4 difficulty levels:

### Level 1: Simple Service Failures
- `cpu_saturation` on service
- `memory_leak` on service
- `inject_latency` on service

### Level 2: Database Bottlenecks
- `slow_queries` on database
- `connection_exhaustion` on database
- `enable_background_job` on database

### Level 3: Complex Interactions
- `cache_failure` on cache
- `inject_latency` on cache
- `queue_consumer_slowdown` on queue
- `hot_shard` on service
- `force_deadlock` on service
- `noisy_neighbor` on service

### Level 4: External Dependencies & Network
- `inject_latency` on external
- `inject_errors` on external
- `network_partition` on network

## Available Topologies

Current topology bank (in `data/topology_bank/`):
- `hierarchical_medium_0` - Hierarchical service architecture
- `hub_spoke_medium_0` - Hub-and-spoke pattern
- `mesh_medium_0` - Mesh network topology
- `pipeline_medium_0` - Pipeline processing architecture

**Total combinations**: 16 fault types × 4 topologies = **64 configurations**

## Usage

### Basic Usage - Generate All Combinations

Generate 5 episodes per fault-topology combination:

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 5 \
  --output data/batch_run \
  --yes
```

This will generate **320 total episodes** (64 configs × 5 episodes).

### Filtered Generation

Generate only specific fault types:

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 3 \
  --filter-fault cpu_saturation \
  --output data/cpu_only \
  --yes
```

Generate only for specific topology:

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 3 \
  --filter-topology hierarchical_medium_0 \
  --output data/hierarchical_only \
  --yes
```

Combine filters:

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 10 \
  --filter-fault network_partition \
  --filter-topology mesh_medium_0 \
  --output data/network_partition_mesh \
  --yes
```

### Timeout Configuration

Adjust timeout (default is 600s = 10 minutes):

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 5 \
  --timeout 900 \
  --output data/longer_timeout \
  --yes
```

### Retry Failed Runs

If some runs fail or timeout, retry them later:

```bash
# First run generates batch_results_failed.json
python3 batch_generate_datasets.py --episodes-per-config 5 --output data/batch1 --yes

# Retry failed runs
python3 batch_generate_datasets.py \
  --retry batch_results_failed.json \
  --timeout 1200 \
  --yes
```

### Verbose Output

Enable detailed logging for debugging:

```bash
python3 batch_generate_datasets.py \
  --episodes-per-config 1 \
  --filter-fault cpu_saturation \
  --filter-topology hierarchical_medium_0 \
  --verbose \
  --yes
```

## Output Files

The script generates several output files:

### Result Files (in current directory)

- `batch_results_results.json` - Complete results for all runs
- `batch_results_failed.json` - Failed runs (for retry)

### Dataset Output (in specified output directory)

Each run creates a timestamped directory structure:

```
data/batch_run/
└── data_20251208_104814/
    ├── dataset_metadata.json
    └── ep_0/
        ├── label.json              # Ground truth labels
        ├── topology.json           # Network topology
        ├── metrics.jsonl           # Time-series metrics
        ├── logs.jsonl              # Component logs
        ├── fault_propagation.json  # Propagation analysis
        ├── capacity_planning.json  # Resource config
        ├── performance_timing.json # Execution timing
        └── run_parameters.json     # Replay config
```

## Results File Format

`batch_results_results.json` contains:

```json
{
  "timestamp": "2025-12-08T10:48:59.535067",
  "total_runs": 64,
  "successful": 60,
  "failed": 4,
  "results": [
    {
      "fault_type": "cpu_saturation",
      "fault_role": "service",
      "level": 1,
      "topology": "hierarchical_medium_0",
      "episodes": 5,
      "success": true,
      "error": "",
      "duration": 46.86,
      "timestamp": "2025-12-08T10:48:59.534127",
      "metadata": {...}
    }
  ]
}
```

## Time Estimates

Based on test runs:
- Average duration per episode: ~45-50 seconds
- For 5 episodes per config: ~4 minutes per config
- For all 64 configs with 5 episodes: ~4-5 hours total
- With 10-minute timeout: maximum ~11 hours

## Tips for Large Batch Runs

1. **Run in background or screen session**:
   ```bash
   screen -S batch_gen
   python3 batch_generate_datasets.py --episodes-per-config 5 --output data/full_batch --yes
   # Ctrl+A, D to detach
   # screen -r batch_gen to reattach
   ```

2. **Monitor progress**:
   ```bash
   # Check results file periodically
   watch -n 30 'tail -20 batch_results_results.json'

   # Count completed episodes
   find data/batch_run -name "label.json" | wc -l
   ```

3. **Split into smaller batches**:
   ```bash
   # Level 1 only
   python3 batch_generate_datasets.py --filter-fault cpu_saturation --episodes-per-config 5 --yes
   python3 batch_generate_datasets.py --filter-fault memory_leak --episodes-per-config 5 --yes

   # Or by topology
   python3 batch_generate_datasets.py --filter-topology hierarchical_medium_0 --episodes-per-config 5 --yes
   ```

4. **Handle failures gracefully**:
   - Failed runs are automatically saved to `batch_results_failed.json`
   - Use `--retry` to rerun failed configurations
   - Consider increasing timeout for problematic configs

## Common Issues

### Timeout Exceeded
Some configurations may take longer. Increase timeout:
```bash
--timeout 1200  # 20 minutes
```

### Memory Issues
If running out of memory, reduce parallel operations or run smaller batches.

### Simulation Bugs
The script continues on errors and logs them. Check `batch_results_failed.json` for patterns.

## Full Production Run Example

Generate complete training dataset:

```bash
# Run full batch (overnight recommended)
nohup python3 batch_generate_datasets.py \
  --episodes-per-config 10 \
  --timeout 900 \
  --output data/gnn_training_dataset \
  --results-file production_results.json \
  --yes > batch_generation.log 2>&1 &

# Monitor progress
tail -f batch_generation.log

# Check completion
cat production_results_results.json | jq '.successful, .failed'

# Retry any failures
python3 batch_generate_datasets.py \
  --retry production_results_failed.json \
  --timeout 1200 \
  --yes
```

This will generate **640 training episodes** (64 configs × 10 episodes) suitable for GNN training.

## Notes

- Each episode is isolated in its own process for clean state
- Results are saved periodically (every 10 runs) to prevent data loss
- The script uses colored output for better visibility
- All runs log to both stdout and results JSON
- Failed runs can be retried with different timeouts
- The `--yes` flag skips confirmation prompts (useful for automation)
