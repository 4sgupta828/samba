# RCA Discovery and Validation Guide

## Overview

The SOTA Propagation Analyzer now supports **service-level blind RCA discovery with automatic validation**. This allows you to:

1. Run discovery mode analysis WITHOUT knowing the root cause (blind RCA)
2. **Work at SERVICE level** - aggregates pods to avoid topology dilution
3. Check if the ground truth root cause is in the top 3 candidates
4. **Drill down to pod-level** within root cause services to identify outliers
5. Automatically mark episodes as "RCAInvestigated" if successful
6. Skip re-analysis of already investigated episodes

## Service-Level RCA Approach

### Why Service-Level?

**Problem with Pod-Level RCA:**
- Individual pods (e.g., `pod_upload_service_0`, `pod_upload_service_1`, `pod_upload_service_2`) dilute the topology
- With 3 replicas, all 3 pods might appear in top candidates, wasting valuable slots
- Pods are ephemeral - they come and go, making pod-level root causes less actionable

**Solution: Service-Level Aggregation**
- Root causes are identified at the **service level** (e.g., `upload_service`, not individual pods)
- Pods are aggregated to their parent service for detection
- Results are cleaner and more actionable (e.g., "redis_cache failed" vs "pod_redis_cache_2 failed")
- After identifying root cause service, drill down to identify outlier pods if needed

## Key Features

### Discovery Mode Analysis
- Runs root cause detection **without** using ground truth for ranking
- Uses only observable metrics, topology, and temporal patterns
- Outputs top-N candidates ranked by confidence scores

### Automatic Validation
- After discovery, validates if ground truth is in top 3 candidates
- Records rank, confidence, and success status
- Creates `RCAInvestigated.marker` file for successful detections

### Marker Files
- Prevents duplicate analysis on already-investigated episodes
- Stores validation results for future reference
- JSON format with complete validation metadata

## Usage

### Python API

```python
from analysis.sotaanalyzer.sota_propagation_analyzer import discover_and_validate_rca

# Run discovery and validation
result = discover_and_validate_rca(
    episode_dir='data/dataset_X/ep_0',
    sample_interval=5,
    output_file=None,  # Optional: save full analysis
    create_marker=True  # Create marker on success
)

# Check results
if result['validation_result']['success']:
    print(f"✅ SUCCESS: Found at rank {result['validation_result']['rank']}")
else:
    print(f"❌ FAILURE: Not in top 3")
```

### Command Line

```bash
# Test a single episode
python test_rca_discovery.py data/dataset_X/ep_0

# The script will:
# 1. Run discovery mode analysis
# 2. Validate against ground truth
# 3. Create marker file if successful
# 4. Exit with code 0 (success) or 1 (failure)
```

### Batch Processing

```bash
# Process multiple episodes
for ep in data/dataset_*/ep_0; do
    python test_rca_discovery.py "$ep"
done

# Count successes and failures
find data -name "RCAInvestigated.marker" | wc -l  # Successful
```

## Output

### Success Case (Service-Level)
```
🔍 Running discovery mode RCA analysis on: data/dataset_X/ep_0
   Ground truth (hidden from analyzer): redis_cache

📊 Top 3 RCA candidates identified (service-level):
   1. video_db (confidence: 0.323)
   2. redis_cache (confidence: 0.261)
   3. upload_queue (confidence: 0.224)

============================================================
✅ SUCCESS: Ground truth 'redis_cache' found at rank 2
   Confidence: 0.261
✅ Created RCA investigation marker: .../RCAInvestigated.marker
============================================================
```

### Success Case with Pod Details
```
📊 Top 3 RCA candidates identified (service-level):
   1. upload_service (confidence: 0.456)
      └─ 3 pods, consensus: 100%
   2. email_service (confidence: 0.368)
   3. session_cache (confidence: 0.289)

============================================================
✅ SUCCESS: Ground truth service 'upload_service' found at rank 1
   Ground truth pod: pod_upload_service_2
   Confidence: 0.456

   Pod Analysis for upload_service:
   - Total pods: 3
   - Avg severity: 0.412
   - Max severity: 0.456
   - Impact consensus: 100%
============================================================
```

### Before Service-Level (Diluted Results)
```
# OLD BEHAVIOR - pods dilute the topology:
📊 Top 3 RCA candidates identified:
   1. pod_upload_service_0 (confidence: 0.529)
   2. pod_upload_service_1 (confidence: 0.528)
   3. pod_upload_service_2 (confidence: 0.404)
# All 3 slots wasted on the same service!
```

### After Service-Level (Clean Results)
```
# NEW BEHAVIOR - aggregated to service level:
📊 Top 3 RCA candidates identified (service-level):
   1. video_db (confidence: 0.323)
   2. redis_cache (confidence: 0.261)
   3. upload_queue (confidence: 0.224)
# Clean, actionable results with diverse candidates!
```

### Already Investigated
```
⏭️  Episode already investigated: data/dataset_X/ep_0
   Previous result: SUCCESS
   Ground truth 'redis_cache' at rank 3
```

## Marker File Format

The `RCAInvestigated.marker` file contains:

```json
{
  "success": true,
  "ground_truth": "redis_cache",
  "ground_truth_service": null,
  "top_3_candidates": [
    "video_db",
    "redis_cache",
    "upload_queue"
  ],
  "rank": 2,
  "confidence": 0.261,
  "matched_as": "direct",
  "pod_details": null,
  "total_candidates": 7
}
```

### With Pod-Level Ground Truth
If the ground truth is a pod (e.g., `pod_upload_service_2`), the marker includes service mapping:

```json
{
  "success": true,
  "ground_truth": "pod_upload_service_2",
  "ground_truth_service": "upload_service",
  "top_3_candidates": [
    "upload_service",
    "email_service",
    "session_cache"
  ],
  "rank": 1,
  "confidence": 0.456,
  "matched_as": "service",
  "pod_details": {
    "pods": [...],
    "pod_count": 3,
    "avg_severity": 0.412,
    "max_severity": 0.456,
    "consensus": 1.0
  },
  "total_candidates": 9
}
```

## Technical Implementation

### Service-Level Aggregation

The analyzer aggregates pod-level data to service level using these strategies:

1. **Severity Aggregation**: Uses max severity across all pods in a service
   - If any pod is critically impacted, the service is considered critically impacted
   - More conservative than averaging, catches outlier pods

2. **Health Aggregation**: Uses worst health status across all pods
   - Health hierarchy: HEALTHY < DEGRADED < IMPACTED < CRITICAL
   - If any pod is CRITICAL, service is CRITICAL

3. **Temporal Aggregation**: Uses earliest impact time across all pods
   - Identifies when the service first showed symptoms
   - Important for temporal ordering in RCA

4. **Metric Aggregation**: Uses metrics from worst-impacted pod
   - Represents the most severe manifestation of the problem
   - Used for fault signature matching

### Pod-to-Service Mapping

Pods are mapped to services using topology attributes:
- Primary: `parent_service` attribute
- Fallback: `service_name` attribute
- Format: `pod_upload_service_0` → `upload_service`

### Result Benefits

**Before Service-Level (29 candidates):**
- `pod_upload_service_0`, `pod_upload_service_1`, `pod_upload_service_2`
- `pod_enrichment_service_0`, `pod_enrichment_service_1`, `pod_enrichment_service_2`
- `video_db`, `redis_cache`, `upload_queue`, ...
- Top 3 often dominated by pods from same service

**After Service-Level (7 candidates):**
- `upload_service` (aggregates 3 pods)
- `enrichment_service` (aggregates 3 pods)
- `video_db`, `redis_cache`, `upload_queue`, ...
- Clean, diverse top 3 with actionable results

## Functions Added

### `discover_and_validate_rca()`
**Location**: `analysis/sotaanalyzer/sota_propagation_analyzer.py:570`

Main function that orchestrates the entire workflow.

**Parameters**:
- `episode_dir`: Path to episode directory
- `sample_interval`: Time between samples (default: 5s)
- `output_file`: Optional JSON output file for full analysis
- `create_marker`: Whether to create marker file on success (default: True)

**Returns**: Dictionary with validation results and metadata

### `validate_rca_discovery()`
**Location**: `analysis/sotaanalyzer/sota_propagation_analyzer.py:509`

Validates if ground truth is in top 3 candidates.

**Parameters**:
- `result`: SOTAAnalysisResult from discovery mode
- `ground_truth_root_cause`: Actual root cause node

**Returns**: Dictionary with validation details (success, rank, confidence, etc.)

### `mark_episode_as_rca_investigated()`
**Location**: `analysis/sotaanalyzer/sota_propagation_analyzer.py:549`

Creates marker file with validation results.

**Parameters**:
- `episode_dir`: Path to episode directory
- `validation_result`: Validation results to store

## Improving RCA Detection

When you encounter failures (ground truth not in top 3), consider:

1. **Analyze the failure pattern**: Which types of faults are failing?
2. **Check the ranked candidates**: Are they reasonable alternatives?
3. **Review the scoring logic**: In `root_cause_detector.py:rank_root_cause_candidates()`
4. **Tune detection parameters**: Adjust weights in the ranking algorithm
5. **Enhance features**: Add new signals for detection (e.g., network patterns, error types)

The failure cases highlight opportunities to improve the RCA algorithm.

## Example Workflow

```bash
# 1. Generate a dataset
python generate_dataset.py --scenarios cache_failure --episodes 10

# 2. Run RCA discovery and validation on all episodes
for ep in data/latest_dataset/ep_*/; do
    python test_rca_discovery.py "$ep"
done

# 3. Analyze results
echo "Total episodes: $(ls -d data/latest_dataset/ep_*/ | wc -l)"
echo "Successful RCA: $(find data/latest_dataset -name 'RCAInvestigated.marker' | wc -l)"

# 4. Find failure cases for improvement
for ep in data/latest_dataset/ep_*/; do
    if [ ! -f "$ep/RCAInvestigated.marker" ]; then
        echo "Failed: $ep"
    fi
done
```

## Notes

- Discovery mode **never** uses ground truth for candidate ranking
- Only validation step compares results to ground truth
- Marker files prevent redundant analysis
- Exit codes: 0 (success), 1 (not in top 3), 2 (error)
