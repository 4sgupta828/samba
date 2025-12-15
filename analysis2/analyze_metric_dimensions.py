"""
Analyze which metrics have dimensional labels that could cause aggregation issues.
"""

import json
from collections import defaultdict
from pathlib import Path

episode_dir = Path("../data/batch_run/data_20251215_015616/ep_0")
metrics_file = episode_dir / "metrics.jsonl"

# Track which metrics have which label dimensions
metric_dimensions = defaultdict(set)
metric_sample_counts = defaultdict(lambda: defaultdict(int))

print("Analyzing metric dimensions...")

with open(metrics_file) as f:
    for line in f:
        try:
            metric = json.loads(line)
            name = metric.get('name')
            labels = metric.get('labels', {})

            if not name:
                continue

            # Track dimensional labels (excluding component ID and timestamp)
            skip_labels = {'component.id', 'component.type', 'sim.time', 'service.id', 'service.name'}
            dimensions = {k for k in labels.keys() if k not in skip_labels}

            if dimensions:
                metric_dimensions[name].update(dimensions)

                # Count samples per timestamp for metrics with request_type
                if 'request_type' in labels:
                    timestamp = labels.get('sim.time', 0)
                    component = labels.get('component.id', 'unknown')
                    key = f"{name}:{component}:{timestamp}"
                    metric_sample_counts[key]['count'] += 1

        except:
            pass

print(f"\n{'='*80}")
print("METRICS WITH DIMENSIONAL LABELS (that need special aggregation)")
print(f"{'='*80}\n")

for metric_name in sorted(metric_dimensions.keys()):
    dimensions = metric_dimensions[metric_name]
    print(f"{metric_name}")
    print(f"  Dimensions: {', '.join(sorted(dimensions))}")

print(f"\n{'='*80}")
print("METRICS WITH request_type DIMENSION (most affected by bug)")
print(f"{'='*80}\n")

request_type_metrics = [m for m, dims in metric_dimensions.items() if 'request_type' in dims]
for metric in sorted(request_type_metrics):
    print(f"  - {metric}")

print(f"\n{'='*80}")
print("SAMPLE: Metrics with multiple samples per timestamp")
print(f"{'='*80}\n")

multi_sample_timestamps = {k: v['count'] for k, v in metric_sample_counts.items() if v['count'] > 1}
if multi_sample_timestamps:
    # Show a few examples
    for key in sorted(multi_sample_timestamps.keys())[:5]:
        count = multi_sample_timestamps[key]
        metric_name, component, timestamp = key.split(':', 2)
        print(f"  {metric_name} @ t={timestamp} for {component}: {count} samples")
