# Reprocess Feature

## Overview

The `--reprocess` flag allows you to clear all previous analysis results and re-run the analysis from scratch. This is useful when you want to:

- Re-analyze episodes with updated algorithms or configurations
- Clear failed analyses and try again
- Regenerate all output files with fresh results

## Usage

### Basic Usage

```bash
python3 run_rca_batch.py <directory> [top_k] --reprocess
```

### Examples

**Reprocess single dataset:**
```bash
python3 run_rca_batch.py ../data/batch_run/data_20251212_135332/ 5 --reprocess
```

**Reprocess entire batch:**
```bash
python3 run_rca_batch.py ../data/batch_run 5 --reprocess
```

**Using wrapper script:**
```bash
./run_batch_analysis.sh ../data/batch_run 5 --reprocess
```

## What It Does

When you use `--reprocess`, the script will:

1. **Find all episodes** in the specified directory
2. **Clear old files** from each episode:
   - `RCAInvestigated.marker`
   - `RCAFailed.marker`
   - `rca_analysis.json`
3. **Re-run analysis** on all episodes (no skipping)
4. **Generate fresh results** with new marker files and JSON outputs

## Example Output

```
================================================================================
BATCH WHITEBOX RCA ANALYSIS
================================================================================
Base directory: ../data/batch_run
Top-K candidates: 5
Mode: REPROCESS (clearing old markers and outputs)
================================================================================

Found 18 episodes

🔄 Clearing old markers and outputs...
   Cleared 18 episode(s)

  Already investigated: 0
  Already failed: 0
  To process: 18

[1/18]
...processing...
```

## Comparison: Normal vs Reprocess Mode

### Normal Mode (Default)
```bash
python3 run_rca_batch.py ../data/batch_run 5
```

Output:
```
Found 18 episodes
  Already investigated: 17
  Already failed: 0
  To process: 1
```

Only processes episodes without markers (1 episode).

### Reprocess Mode
```bash
python3 run_rca_batch.py ../data/batch_run 5 --reprocess
```

Output:
```
Found 18 episodes

🔄 Clearing old markers and outputs...
   Cleared 18 episode(s)

  Already investigated: 0
  Already failed: 0
  To process: 18
```

Clears all markers and processes all episodes (18 episodes).

## Files Removed

For each episode directory, the following files are removed:

| File | Description |
|------|-------------|
| `RCAInvestigated.marker` | Success marker (created when ground truth found in top-K) |
| `RCAFailed.marker` | Failure marker (created on errors) |
| `rca_analysis.json` | Detailed analysis results |

## Use Cases

1. **Algorithm Updates**: After modifying the RCA engine or improving heuristics
2. **Configuration Changes**: After adjusting top-K, thresholds, or other parameters
3. **Failed Analysis Recovery**: When you want to retry episodes that previously failed
4. **Fresh Start**: When you need to completely regenerate all analysis outputs
5. **Testing**: When validating changes across the entire dataset

## Safety Notes

- **Data Loss**: Original marker files and JSON outputs will be permanently deleted
- **Processing Time**: Reprocessing large batches may take considerable time
- **Source Data**: Original episode data (metrics.jsonl, topology.json, label.json) is never modified
- **Backups**: Consider backing up important `rca_analysis.json` files before reprocessing

## Alternative: Manual Cleanup

If you prefer manual control, you can remove files manually:

```bash
# Remove all markers
find ../data/batch_run -name "RCA*.marker" -delete

# Remove all analysis outputs
find ../data/batch_run -name "rca_analysis.json" -delete

# Then run normal analysis
python3 run_rca_batch.py ../data/batch_run 5
```

## Integration with Wrapper Script

The wrapper script automatically passes the `--reprocess` flag:

```bash
./run_batch_analysis.sh ../data/batch_run 5 --reprocess
```

This provides a convenient one-liner for reprocessing entire batch directories.
