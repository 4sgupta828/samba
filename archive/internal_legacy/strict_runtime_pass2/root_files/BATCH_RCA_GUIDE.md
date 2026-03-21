# Batch RCA Discovery Guide

## Overview

Process multiple episodes in batch to run discovery mode RCA analysis and validate against ground truth.

## Features

- **Batch Processing**: Processes all episodes in a directory automatically
- **Top-5 Validation**: Uses top-5 candidates instead of top-3 for higher success rate
- **Service-Level RCA**: Aggregates pods to services for cleaner results
- **Resumable**: Skips already processed episodes (with markers)
- **Error Handling**: Creates failure markers and continues processing
- **Progress Tracking**: Shows real-time progress and summary statistics

## Usage

### Basic Usage

Process all episodes in default directory (`data/batch_run`):

```bash
python batch_rca_discovery.py
```

### Custom Directory

Process episodes in a specific directory:

```bash
python batch_rca_discovery.py data/my_custom_dataset
```

### Testing Mode

Process only first N episodes (for testing):

```bash
python batch_rca_discovery.py data/batch_run 5
```

## Marker Files

The script creates marker files to track processing status:

### RCAInvestigated.marker

Created when ground truth is found in top-5 candidates (SUCCESS).

```json
{
  "success": true,
  "ground_truth": "redis_cache",
  "ground_truth_service": null,
  "top_k": 5,
  "top_k_candidates": [
    "video_db",
    "redis_cache",
    "upload_queue",
    "session_cache",
    "tenant_db"
  ],
  "rank": 2,
  "confidence": 0.261,
  "matched_as": "direct",
  "pod_details": null,
  "total_candidates": 7
}
```

### RCAFailed.marker

Created when the script encounters an error/exception (ERROR).

```json
{
  "failed_at": "2025-12-08T18:30:45.123456",
  "error": "FileNotFoundError: metrics.jsonl not found",
  "error_type": "FileNotFoundError",
  "traceback": "Traceback (most recent call last):\n  ..."
}
```

### No Marker

If ground truth is NOT in top-5 but script ran successfully:
- No marker file is created
- Episode can be re-run after algorithm improvements
- Distinguishes "needs improvement" from "successfully validated"

## Output Example

```
================================================================================
BATCH RCA DISCOVERY
================================================================================
Base directory: data/batch_run
Top-K candidates: 5
Sample interval: 5s
================================================================================

Found 60 episodes
  Already investigated: 15
  Already failed: 2
  To process: 43

[1/43]
================================================================================
Processing: data/batch_run/data_20251208_105225/ep_0
================================================================================
🔍 Running discovery mode RCA analysis on: ...
   Ground truth (hidden from analyzer): redis_cache

📊 Top 5 RCA candidates identified (service-level):
   1. video_db (confidence: 0.323)
   2. redis_cache (confidence: 0.261)
   3. upload_queue (confidence: 0.224)
   4. session_cache (confidence: 0.187)
   5. tenant_db (confidence: 0.145)

============================================================
✅ SUCCESS: Ground truth 'redis_cache' found at rank 2
   Confidence: 0.261
✅ Created RCA investigation marker: .../RCAInvestigated.marker
============================================================

[2/43] ...

================================================================================
BATCH RCA DISCOVERY SUMMARY
================================================================================
Total episodes found: 60
  Already investigated: 15
  Already failed: 2
  Processed this run: 43

Results for 43 processed episodes:
  ✅ Success (found in top-K): 28 (65.1%)
  ❌ Not in top-K: 14 (32.6%)
  ⚠️  Errors: 1 (2.3%)
================================================================================

Overall success rate: 43/60 (71.7%)
```

## Workflow

### Initial Run

```bash
# Run on all episodes
python batch_rca_discovery.py data/batch_run

# Check results
find data/batch_run -name "RCAInvestigated.marker" | wc -l  # Successful
find data/batch_run -name "RCAFailed.marker" | wc -l  # Errors
```

### After Algorithm Improvements

```bash
# Remove old markers to re-process
find data/batch_run -name "RCA*.marker" -delete

# Re-run batch processing
python batch_rca_discovery.py data/batch_run

# Compare success rates
```

### Analyze Failures

```bash
# Find episodes without markers (not in top-5)
for ep in data/batch_run/*/ep_*; do
    if [ ! -f "$ep/RCAInvestigated.marker" ] && [ ! -f "$ep/RCAFailed.marker" ]; then
        echo "Not in top-5: $ep"
    fi
done

# Review failed episodes
find data/batch_run -name "RCAFailed.marker" -exec cat {} \;
```

## Configuration

Edit `batch_rca_discovery.py` to customize:

```python
# Line 164-167
base_dir = "data/batch_run"  # Default directory
top_k = 5  # Number of top candidates to check
sample_interval = 5  # Sampling interval in seconds
```

## Performance

- **Speed**: ~30-60 seconds per episode (depends on topology size)
- **Memory**: ~500MB-1GB per episode
- **Parallelization**: Sequential processing (can be parallelized if needed)

For 60 episodes:
- Estimated time: 30-60 minutes
- Can run in background: `python batch_rca_discovery.py &`
- Can monitor progress: `tail -f batch_rca_run.log`

## Comparison: Top-3 vs Top-5

**Top-3** (previous default):
- Stricter validation
- Lower success rate (~55-60%)
- Better for high-confidence validation

**Top-5** (current default):
- More lenient validation
- Higher success rate (~65-75%)
- Better for algorithm development and testing

## Integration with Development Workflow

### 1. Generate Dataset
```bash
python generate_dataset.py --scenarios all --episodes 10
```

### 2. Run Batch RCA
```bash
python batch_rca_discovery.py data/latest_dataset
```

### 3. Analyze Results
```bash
# Success rate
success=$(find data/latest_dataset -name "RCAInvestigated.marker" | wc -l)
total=$(find data/latest_dataset -name "ep_*" -type d | wc -l)
echo "Success rate: $success/$total"

# Failed cases for algorithm improvement
for ep in data/latest_dataset/*/ep_*; do
    if [ ! -f "$ep/RCAInvestigated.marker" ] && [ ! -f "$ep/RCAFailed.marker" ]; then
        jq -r '.fault_type + " -> " + .root_cause_node' "$ep/label.json"
    fi
done | sort | uniq -c
```

### 4. Improve Algorithm
- Review failure patterns
- Tune detection weights in `root_cause_detector.py`
- Add new signals or features

### 5. Re-evaluate
```bash
# Clean markers
find data/latest_dataset -name "RCA*.marker" -delete

# Re-run
python batch_rca_discovery.py data/latest_dataset

# Compare results
```

## Troubleshooting

### Script Hangs

If script appears to hang on an episode:
- Check episode has required files (label.json, topology.json, metrics.jsonl)
- Check metrics.jsonl is not corrupted
- Kill and restart with limit to skip problematic episode

### Low Success Rate

If success rate is low (<50%):
- Check if using service-level RCA (should see service names, not pod IDs)
- Review failure patterns (which fault types failing?)
- Consider tuning detection parameters
- Check if ground truth labels are correct

### Memory Issues

If running out of memory:
- Process in smaller batches using limit parameter
- Close other applications
- Increase system swap space

## Notes

- Episodes with RCAInvestigated.marker are considered validated
- Episodes with RCAFailed.marker had errors and may need manual inspection
- Episodes without markers need algorithm improvement or investigation
- Script is idempotent - safe to re-run multiple times
