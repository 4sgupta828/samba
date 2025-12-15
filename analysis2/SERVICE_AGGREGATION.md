# Service-Level Aggregation

## Overview

The whitebox RCA engine now aggregates pod-level detections to service-level results, ensuring ground truth matching at the correct granularity.

## Problem

In Kubernetes-based topologies with multiple pod replicas:
- **RCA Engine**: Detects issues at the pod level (e.g., `pod_notification_service_2`)
- **Ground Truth**: Labeled at the service level (e.g., `notification_service`)
- **Mismatch**: Direct comparison fails even when detection is correct

## Solution

The engine now:
1. Analyzes anomalies at the pod level (fine-grained detection)
2. Aggregates results to the parent service level
3. Reports service names with affected pod details
4. Compares against ground truth at service level

## How It Works

### 1. Pod-Level Analysis
The RCA engine first identifies problematic pods:
```
pod_notification_service_2 (Score: 19.3)
pod_notification_service_0 (Score: 18.5)
pod_notification_service_1 (Score: 17.8)
```

### 2. Service-Level Aggregation
Pods are grouped by their `parent_service` attribute:
```python
notification_service:
  - Affected pods: [pod_notification_service_2, pod_notification_service_0, pod_notification_service_1]
  - Aggregated score: (avg + max) / 2 = 19.0
  - Combined symptoms: Union of all pod symptoms
```

### 3. Service-Level Reporting
Output shows service with pod details:
```
Ground Truth: notification_service
Top Result:   notification_service (Score: 19.0)
   Affected pods: pod_notification_service_2, pod_notification_service_0, pod_notification_service_1
✅ EXACT MATCH (Rank 1/5)
```

## Topology Requirements

The topology must have:
- **Pod nodes** with `parent_service` attribute pointing to service
- **Service nodes** representing logical services

Example topology structure:
```json
{
  "nodes": [
    {
      "id": "notification_service",
      "type": "Service",
      "role": "service"
    },
    {
      "id": "pod_notification_service_0",
      "type": "Pod",
      "role": "pod",
      "parent_service": "notification_service"
    },
    {
      "id": "pod_notification_service_1",
      "type": "Pod",
      "role": "pod",
      "parent_service": "notification_service"
    }
  ]
}
```

## Score Aggregation

The service-level score is calculated as:
```
avg_score = sum(pod_scores) / pod_count
max_score = max(pod_scores)
final_score = (avg_score + max_score) / 2
```

This approach:
- **Considers severity**: Max score captures the worst affected pod
- **Considers breadth**: Average score reflects overall service health
- **Balanced view**: Blend prevents false positives from single outliers

## Output Format

### Console Output
```
Ground Truth: tenant_service
Top Result:   tenant_service (Score: 51.2)
   Affected pods: pod_tenant_service_3, pod_tenant_service_0, pod_tenant_service_1
✅ IN TOP-5 (Rank 1/5)

📜 Causal Narrative:
  🔴 ROOT CAUSE: pod_tenant_service_3
     Internal Symptoms: memory_usage increased (d=3.08)
  ⬇️ Propagation:
     - node_3 calls pod_tenant_service_3 (Potential cascading latency)
```

### JSON Output
```json
{
  "ground_truth": "tenant_service",
  "found_in_top_k": true,
  "rank": 1,
  "service_level_candidates": [
    {
      "node": "tenant_service",
      "score": 51.2,
      "pod_count": 4,
      "affected_pods": [
        "pod_tenant_service_3",
        "pod_tenant_service_0",
        "pod_tenant_service_1",
        "pod_tenant_service_2"
      ],
      "symptoms": [...],
      "story": [...]
    }
  ],
  "pod_level_candidates": [...]
}
```

## Benefits

1. **Accurate Matching**: Ground truth comparison at correct granularity
2. **Detailed Diagnostics**: Still shows which specific pods are affected
3. **Better Accuracy**: Improves metrics by matching at service level
4. **Intuitive Results**: Reports align with how operators think (services, not pods)
5. **Flexible**: Works with topologies that have pods, services, or both

## Fallback Behavior

If a node doesn't have a `parent_service` attribute:
- The node is treated as its own service
- Aggregation groups by node ID itself
- Works seamlessly with non-pod topologies (VMs, containers, etc.)

## Impact on Accuracy

Before service aggregation:
```
Success rate: 0/18 (0.0%)
Issue: Comparing pod_tenant_service_3 vs tenant_service
```

After service aggregation:
```
Success rate: 7/18 (38.9%)
Improvement: Comparing tenant_service vs tenant_service ✅
```

## Implementation Details

### Key Functions

1. **`aggregate_to_service_level()`** (run_rca_batch.py:279)
   - Groups pod results by parent service
   - Calculates aggregated scores
   - Combines symptoms and blame information

2. **`_load_topology()`** (run_rca_batch.py:105)
   - Loads topology with full node attributes
   - Preserves `parent_service` relationships
   - Maintains type and role information

### Integration

The aggregation happens automatically in `process_episode()`:
```python
# 1. Analyze at pod level
pod_results = engine.analyze_incident(baseline, current)

# 2. Aggregate to service level
service_results = aggregate_to_service_level(pod_results, topology)

# 3. Compare against ground truth
is_match = (service_results[0]['node'] == ground_truth)
```

No changes required to the core RCA engine - aggregation is a post-processing step.
