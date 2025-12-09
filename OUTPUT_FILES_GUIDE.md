# RCA Output Files Guide

## Files Created Per Episode

After running batch RCA discovery, each episode directory will contain:

```
data/batch_run/data_YYYYMMDD_HHMMSS/ep_0/
├── label.json                      # Original ground truth
├── topology.json                   # System topology
├── metrics.jsonl                   # Time-series metrics
├── RCAInvestigated.marker          # ✨ NEW: Validation summary (small)
└── rca_analysis.json               # ✨ NEW: Complete analysis (large)
```

## File Descriptions

### RCAInvestigated.marker (~300 bytes)

**Quick validation summary** - check this first to see if RCA succeeded.

**Example:**
```json
{
  "success": false,
  "ground_truth": "analytics_service",
  "ground_truth_service": null,
  "top_k": 5,
  "top_k_candidates": [
    "session_cache",
    "events_queue",
    "user_db"
  ],
  "rank": null,
  "confidence": null,
  "matched_as": null,
  "pod_details": null,
  "total_candidates": 7
}
```

**Fields:**
- `success`: true if ground truth in top-K
- `ground_truth`: Actual root cause from label.json
- `ground_truth_service`: Service name if ground truth is a pod
- `top_k`: How many candidates were checked (default: 5)
- `top_k_candidates`: The top-K candidates identified
- `rank`: Position of ground truth (if found)
- `confidence`: Probability score (if found)
- `matched_as`: "direct" or "service" (how it matched)
- `pod_details`: Pod breakdown if service-level match
- `total_candidates`: Total number of candidates found

**Quick checks:**
```bash
# Count successes
jq -r 'select(.success == true) | .success' data/batch_run/*/ep_*/RCAInvestigated.marker | wc -l

# Count failures
jq -r 'select(.success == false) | .success' data/batch_run/*/ep_*/RCAInvestigated.marker | wc -l

# Show success rate by fault type
for marker in data/batch_run/*/ep_*/RCAInvestigated.marker; do
    ep_dir=$(dirname "$marker")
    success=$(jq -r '.success' "$marker")
    fault=$(jq -r '.fault_type' "$ep_dir/label.json")
    echo "$fault,$success"
done | sort | uniq -c
```

### rca_analysis.json (~200-300 KB)

**Complete detailed analysis** - all data for deep debugging and analysis.

**Structure:**
```json
{
  "analysis_mode": "discovery",
  "episode_id": "0",

  "root_cause_candidates": [
    {
      "node_id": "session_cache",
      "node_type": "ExternalCache",
      "probability": 0.395,
      "confidence": "LOW",
      "rank": 1,
      "is_leaf_node": true,
      "convergence_score": 0.3125,
      "severity_score": 0.187,
      "centrality_score": 0.041,
      "first_impact_time": 80.0,
      "fault_signature": {
        "expected_fault_type": "cpu_saturation",
        "matched_metrics": 0,
        "top_metrics": ["cache.hit_rate", "component.errors.total"]
      },
      "reasoning": "leaf node; impacted first"
    }
  ],

  "network_partition": null,

  "service_impact_summary": [
    {
      "service_id": "upload_service",
      "total_pods": 3,
      "aggregated_severity_score": 0.456,
      "pod_consensus": 1.0,
      "consistent_impact": true
    }
  ],

  "healthy_nodes": ["gateway", "user_service"],
  "degraded_nodes": ["email_service"],
  "impacted_nodes": ["upload_service"],
  "critical_nodes": ["redis_cache"],

  "node_reports": [
    {
      "node_id": "redis_cache",
      "node_type": "Cache",
      "overall_severity_score": 0.567,
      "ranked_metrics": [
        {
          "metric_name": "cache.hit_rate",
          "severity_class": "CRITICAL",
          "baseline_mean": 0.95,
          "fault_mean": 0.23
        }
      ],
      "health_classification": {
        "health_status": "CRITICAL",
        "confidence": 0.95,
        "reasoning": "Critical error metrics detected"
      },
      "pod_analysis": {
        "total_pods": 3,
        "outlier_pods": []
      }
    }
  ],

  "total_nodes_analyzed": 43,
  "analysis_timestamp": "2025-12-08T23:36:15.123456"
}
```

**Key Sections:**

1. **root_cause_candidates**: All candidates ranked by probability
   - Detailed scoring breakdown
   - Fault signatures
   - Timing information
   - Reasoning

2. **network_partition**: Network partition detection (if found)

3. **service_impact_summary**: Service-level impact aggregation
   - Pod consensus
   - Severity scores
   - Hot pods and outliers

4. **Health classifications**: Nodes grouped by health status
   - healthy_nodes
   - degraded_nodes
   - impacted_nodes
   - critical_nodes

5. **node_reports**: Detailed per-node analysis
   - All metrics with severity scores
   - Health classification reasoning
   - Pod-level analysis (if applicable)
   - First impact time
   - Ranked metrics

**Common queries:**

```bash
# Get top 3 candidates
jq -r '.root_cause_candidates[:3] | .[] | "\(.rank). \(.node_id) (\(.probability))"' rca_analysis.json

# Get all critical nodes
jq -r '.critical_nodes[]' rca_analysis.json

# Check if network partition detected
jq -r '.network_partition' rca_analysis.json

# Get service-level summary
jq -r '.service_impact_summary[] | "\(.service_id): \(.aggregated_severity_score)"' rca_analysis.json

# Find nodes with high severity
jq -r '.node_reports[] | select(.overall_severity_score > 0.5) | "\(.node_id): \(.overall_severity_score)"' rca_analysis.json
```

## RCAFailed.marker (~500 bytes)

**Error tracking** - created when script crashes/fails on an episode.

**Example:**
```json
{
  "failed_at": "2025-12-08T18:30:45.123456",
  "error": "FileNotFoundError: metrics.jsonl not found",
  "error_type": "FileNotFoundError",
  "traceback": "Traceback (most recent call last):\n  File..."
}
```

**Purpose:** Helps identify episodes with data issues or bugs.

## Usage Examples

### Check Results

```bash
# Total processed
ls data/batch_run/*/ep_*/RCAInvestigated.marker | wc -l

# Successes
grep -l '"success": true' data/batch_run/*/ep_*/RCAInvestigated.marker | wc -l

# Errors
ls data/batch_run/*/ep_*/RCAFailed.marker 2>/dev/null | wc -l
```

### Analyze Failures

```bash
# Show episodes where ground truth wasn't in top-5
for marker in data/batch_run/*/ep_*/RCAInvestigated.marker; do
    success=$(jq -r '.success' "$marker")
    if [ "$success" = "false" ]; then
        ep=$(dirname "$marker")
        gt=$(jq -r '.ground_truth' "$marker")
        top=$(jq -r '.top_k_candidates | join(", ")' "$marker")
        echo "$ep: GT=$gt, Top5=$top"
    fi
done
```

### Extract Statistics

```bash
# Success rate by rank
for marker in data/batch_run/*/ep_*/RCAInvestigated.marker; do
    jq -r 'select(.rank != null) | .rank' "$marker"
done | sort | uniq -c

# Average confidence of successful detections
jq -s 'map(select(.success == true) | .confidence) | add / length' data/batch_run/*/ep_*/RCAInvestigated.marker

# Most common top candidate
jq -r '.top_k_candidates[0]' data/batch_run/*/ep_*/RCAInvestigated.marker | sort | uniq -c | sort -rn | head -10
```

### Compare with Ground Truth

```bash
# Show ground truth vs top-1 candidate
for ep in data/batch_run/*/ep_*; do
    if [ -f "$ep/RCAInvestigated.marker" ]; then
        gt=$(jq -r '.ground_truth' "$ep/label.json")
        top1=$(jq -r '.top_k_candidates[0]' "$ep/RCAInvestigated.marker")
        success=$(jq -r '.success' "$ep/RCAInvestigated.marker")
        echo "$success | GT: $gt | Top1: $top1"
    fi
done | column -t -s '|'
```

## File Sizes

Typical file sizes for a 900-second episode:
- **label.json**: ~1-2 KB
- **topology.json**: ~50-100 KB
- **metrics.jsonl**: ~10-50 MB (depends on node count)
- **RCAInvestigated.marker**: ~300 bytes
- **rca_analysis.json**: ~200-300 KB
- **RCAFailed.marker**: ~500 bytes (if errors)

For 60 episodes:
- Total RCA output: ~15-20 MB (markers + analysis files)
- Storage efficient compared to raw metrics

## Integration

### Load in Python

```python
import json

# Load marker
with open('ep_0/RCAInvestigated.marker') as f:
    marker = json.load(f)

print(f"Success: {marker['success']}")
print(f"Ground truth: {marker['ground_truth']}")
print(f"Top 5: {marker['top_k_candidates']}")

# Load full analysis
with open('ep_0/rca_analysis.json') as f:
    analysis = json.load(f)

print(f"Total candidates: {len(analysis['root_cause_candidates'])}")
print(f"Critical nodes: {analysis['critical_nodes']}")
```

### Aggregate Statistics

```python
import json
from pathlib import Path

results = []
for marker_file in Path('data/batch_run').rglob('RCAInvestigated.marker'):
    with open(marker_file) as f:
        marker = json.load(f)
        results.append(marker)

success_rate = sum(1 for r in results if r['success']) / len(results)
print(f"Success rate: {success_rate:.1%}")

avg_candidates = sum(r['total_candidates'] for r in results) / len(results)
print(f"Avg candidates per episode: {avg_candidates:.1f}")
```
