# Simulation Data Validation

This document describes how to validate simulation episode data to ensure completeness and correctness.

## Overview

The `validate_simulation_data.py` script performs comprehensive validation checks on simulation episodes to detect:

- Missing or empty required files (metrics.jsonl, logs.jsonl, traces.jsonl, etc.)
- Incomplete simulation runs (early termination, crashes)
- Invalid metrics timeline (wrong start/end times, gaps)
- Missing expected metric types
- Corrupted or truncated data files

## Common Issues Detected

### Empty Logs/Traces
When logs.jsonl and traces.jsonl are 0 bytes, it typically indicates the simulation crashed during initialization before telemetry was fully set up.

### Invalid Metrics Timeline
Metrics should:
- Start at sim.time ≈ 0 (after warmup period)
- End at sim.time ≈ episode_end (typically 300s)
- Cover the full episode duration without large gaps

If metrics start at negative times or end too early, the simulation likely failed during setup or runtime.

### Missing Completion Markers
The simulation.log should contain completion indicators like:
- "Flush complete"
- "CausalityTracker: Ended Incident"
- "Telemetry shutdown complete"

If these are missing, the simulation did not complete normally.

## Usage

### Validate a Single Episode

```bash
python validate_simulation_data.py data/batch_run/data_20251209_114103/ep_0
```

Output:
```
Validating single episode: ep_0

✗ ep_0: FAILED (7 errors)
  ❌ Empty file (0 bytes): logs.jsonl
  ❌ Empty file (0 bytes): traces.jsonl
  ❌ Metrics start too early: sim.time=-40.0 (expected >= 0)
  ❌ Metrics end too early: sim.time=-40.0 (expected ~300, minimum 270.0)
  ❌ logs.jsonl is empty (0 bytes)
  ❌ traces.jsonl is empty (0 bytes)
  ❌ Simulation did not complete normally (no completion marker found)
```

### Validate a Dataset

Validate all episodes in a single dataset run:

```bash
python validate_simulation_data.py data/batch_run/data_20251208_105310
```

Output:
```
Validating dataset: data_20251208_105310

✓ ep_0

================================================================================
VALIDATION SUMMARY
================================================================================
Total episodes: 1
Valid episodes: 1
Invalid episodes: 0

✅ All episodes valid!
```

### Validate Batch Runs

Validate all dataset runs in a batch directory:

```bash
python validate_simulation_data.py data/batch_run --batch
```

Output:
```
Found 61 data runs to validate

================================================================================
Validating: data_20251208_105225
================================================================================
✓ ep_0

✅ data_20251208_105225: All episodes valid

[... more runs ...]

================================================================================
BATCH VALIDATION SUMMARY
================================================================================
Total runs validated: 61
  Valid runs: 60
  Invalid runs: 1

Total episodes: 61
  Valid episodes: 60
  Invalid episodes: 1

Invalid runs should be regenerated or removed:
  ❌ data_20251209_114103: 1 invalid episode(s)
```

### Verbose Mode

For detailed validation output on all episodes (including passing ones):

```bash
python validate_simulation_data.py data/batch_run/data_20251208_105310 -v
```

## Automatic Validation

The validation is automatically run after dataset generation:

```bash
python generate_dataset.py -n 10 -o data/test
```

At the end of generation, you'll see:

```
============================================================
VALIDATING GENERATED DATASET
============================================================
✓ ep_0
✓ ep_1
...
✅ All 10 episodes passed validation

============================================================
Dataset generation complete!
  Run ID: data_20251209_153045
  Total episodes: 10
  Metadata: data/test/data_20251209_153045/dataset_metadata.json
============================================================
```

If any episodes fail validation, they will be listed with warnings.

## Validation Checks

The validator performs the following checks:

### 1. Required Files
- label.json (episode metadata)
- topology.json (topology structure)
- metrics.jsonl (time-series metrics)
- logs.jsonl (component logs)
- traces.jsonl (distributed traces)
- simulation.log (simulation execution log)
- topology_state.jsonl (topology state changes)

### 2. File Sizes
- All required files must be non-empty (> 0 bytes)
- Files below expected minimum sizes trigger warnings

### 3. Label JSON Structure
- All required fields present (episode, level, scenario, fault info, timeline)
- Topology metadata complete
- Timeline has all expected phases

### 4. Metrics Timeline
- Metrics start at appropriate time (near 0 after warmup)
- Metrics cover full episode duration
- No large gaps in timeline
- Expected metric types present (CPU, memory, latency, requests)

### 5. Logs and Traces
- Files contain valid JSON lines
- Logs have entries from multiple components
- Traces have valid span data

### 6. Simulation Completion
- simulation.log contains completion markers
- No critical errors or exceptions (some warnings are acceptable)
- Simulation reached expected end time

## Exit Codes

- **0**: All episodes valid
- **1**: One or more episodes invalid

Use in CI/CD:
```bash
if python validate_simulation_data.py data/batch_run --batch; then
    echo "All datasets valid"
else
    echo "Some datasets invalid, check output"
    exit 1
fi
```

## Cleaning Up Invalid Data

To remove invalid datasets:

```bash
# Find invalid datasets
python validate_simulation_data.py data/batch_run --batch > validation_report.txt

# Remove invalid runs (be careful!)
# Review the report first, then:
# rm -rf data/batch_run/data_20251209_114103
```

## Integration with Other Scripts

The validation module can be imported and used in other scripts:

```python
from pathlib import Path
from validate_simulation_data import validate_episode, validate_dataset

# Validate single episode
is_valid = validate_episode(Path("data/run/ep_0"), verbose=True)

# Validate dataset
results = validate_dataset(Path("data/run"), verbose=False)
print(f"Valid: {results['valid_episodes']}/{results['total_episodes']}")
```

## Troubleshooting

### High False Positive Rate

If many valid episodes are marked invalid, check:
- Minimum file size thresholds (may be too strict)
- Expected metric types (may not match your topology)
- Timeline expectations (episode duration may vary)

Adjust thresholds in `validate_simulation_data.py` as needed.

### Missing Metrics

Some topologies may not generate all expected metric types. This is a warning, not an error. Common reasons:
- No CPU-intensive components (no cpu.utilization metrics)
- No database queries (no query latency metrics)
- Lightweight topology (fewer metric types)

### Acceptable Warnings

Some simulation logs contain expected warnings that don't indicate failures:
- "Mathematical validation FAILED" followed by "KEEPING DATASET" (intentional diversity)
- "No module named 'telemetry.validator'" (known import issue)
- Validation errors for baseline health checks (kept for training diversity)

These are filtered out and won't cause validation failures.
