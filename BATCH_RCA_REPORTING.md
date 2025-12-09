# Batch RCA Reporting Guide

## Overview

The batch RCA system now includes **automatic comprehensive reporting** that runs after each batch completes. The report provides detailed insights into RCA performance, success patterns, and areas for improvement.

## Automatic Reporting

When you run the batch RCA script, it automatically generates a detailed analysis report at the end:

```bash
python3 batch_rca_discovery.py data/batch_run
# ... processes all episodes ...
# Automatically runs detailed analysis and shows comprehensive report
```

## Report Sections

### 1. Overall Statistics

```
================================================================================
BATCH RCA DISCOVERY RESULTS
================================================================================
Total episodes analyzed: 60

✅ Successes (found in top-5): 19 (31.7%)
❌ Failures (not in top-5): 41 (68.3%)
```

**Key Metrics:**
- Total success rate
- Success vs failure breakdown
- No errors = all episodes processed cleanly

### 2. Rank Distribution (Visual)

```
Rank Distribution (where ground truth was found):
------------------------------------------------------------
  🥇 Rank 1:  9 episodes (47.4%) █████████
  🥇 Rank 2:  5 episodes (26.3%) █████
  🥇 Rank 3:  5 episodes (26.3%) █████

  Examples by rank:
    Rank 1: game_state_db, device_registry_db, session_cache
    Rank 2: game_state_db, devices_db, device_cache
    Rank 3: devices_db, device_cache, notification_queue
```

**Insights:**
- **Rank 1** (47.4%): High-confidence detections - these are strong signals
- **Rank 2-3** (26.3% each): Good detections but need confidence improvement
- **Rank 4-5**: If present, indicates weak but still useful detections

**What This Tells You:**
- If most successes are Rank 1: Algorithm is confident when correct ✅
- If most are Rank 3-5: Algorithm needs better discrimination 🔧
- Distribution helps tune threshold for production use

### 3. Success Rate by Fault Type

```
Success Rate by Fault Type:
  cache_failure: 4/4 (100.0%)           ← Perfect!
  inject_errors: 4/4 (100.0%)           ← Perfect!
  queue_consumer_slowdown: 4/4 (100.0%) ← Perfect!
  connection_exhaustion: 3/4 (75.0%)    ← Good
  inject_latency: 2/12 (16.7%)          ← Needs improvement
  cpu_saturation: 0/4 (0.0%)            ← Broken!
  memory_leak: 0/4 (0.0%)               ← Broken!
```

**Actionable Insights:**
- ✅ **100% success rate**: Algorithm works well for these fault types
- ⚠️ **<50% success rate**: Algorithm struggles with these patterns
- ❌ **0% success rate**: Algorithm cannot detect these faults at all

**What to Do:**
1. Focus algorithm improvements on 0% fault types first
2. Study 100% success cases to understand what signals work
3. Compare successful vs failed cases within same fault type

### 4. Success Rate by Root Cause Role

```
Success Rate by Root Cause Role:
  queue: 4/4 (100.0%)        ← Easy to detect
  cache: 5/8 (62.5%)         ← Moderately detectable
  external: 5/8 (62.5%)      ← Moderately detectable
  database: 5/12 (41.7%)     ← Challenging
  service: 0/24 (0.0%)       ← Cannot detect!
  network: 0/4 (0.0%)        ← Cannot detect!
```

**Critical Finding:**
- **Services**: 0/24 success - major blind spot! 🚨
- **Queues**: 4/4 success - best signal source
- **Network**: 0/4 success - needs specialized detection

**Implications:**
- Current algorithm biased toward infrastructure (queues, caches, DBs)
- Service-level faults require different detection approach
- May need service-specific metrics or patterns

### 5. False Positive Analysis

```
Most Common False Positives (top-1 candidates):
  devices_db: 8 times        ← Often incorrectly flagged
  payment_gateway: 5 times   ← Common red herring
  events_queue: 4 times      ← Frequently confused
```

**What This Means:**
- These components show up as top-1 but aren't the root cause
- Either: (1) They're highly impacted victims, or (2) They have noisy metrics
- Consider: Adding negative signals to downrank these in scoring

### 6. Failure Analysis

```
Failures by Ground Truth Component:
  analytics_service: 6 times  ← Never detected
  notification_service: 4 times
  global_network: 4 times
```

**Focus Areas for Improvement:**
- These are the most problematic components to detect
- Study their topology, metrics, and fault signatures
- May need component-specific detection rules

### 7. Detailed Success List

```
============================================================
Rank 1 (9 episodes):
============================================================
  1. Ground Truth: payment_gateway
     Fault Type: inject_errors
     Confidence: 0.561
     Top-5 Candidates: payment_gateway, game_state_db, game_events_queue

  2. Ground Truth: session_cache
     Fault Type: cache_failure
     Confidence: 0.555
     Top-5 Candidates: session_cache, events_queue, tenant_db

  ...
```

**Use This Section To:**
- **Study high-confidence successes** (Rank 1, confidence >0.5): What made these obvious?
- **Study low-confidence successes** (Rank 3, confidence <0.3): What signals were weak?
- **Compare similar fault types**: Why did some succeed and others fail?
- **Extract patterns**: Do certain component combinations predict success?

**Example Analysis:**

**Rank 1 Successes (9 episodes):**
- Average confidence: 0.46
- Fault types: cache_failure (4), inject_errors (3), slow_queries (1), queue_consumer_slowdown (1)
- Pattern: Strong, clear signals (errors, queue depth, cache misses)

**Rank 3 Successes (5 episodes):**
- Average confidence: 0.30
- Fault types: inject_latency (2), connection_exhaustion (1), queue_consumer_slowdown (1)
- Pattern: Subtle signals, competing hypotheses

## Manual Report Generation

Run the report anytime on any dataset:

```bash
# Default directory
python3 analyze_batch_results.py

# Custom directory
python3 analyze_batch_results.py data/my_dataset

# Save to file
python3 analyze_batch_results.py data/batch_run > results_report.txt
```

## Using Results to Improve Algorithm

### 1. Identify Blind Spots
```bash
# Find all 0% success rate fault types
python3 analyze_batch_results.py data/batch_run | grep "0.0%"
```

**Action:** Prioritize these for algorithm improvements

### 2. Study Success Patterns
```python
# Load successful cases
import json
from pathlib import Path

successes = []
for marker in Path('data/batch_run').rglob('RCAInvestigated.marker'):
    data = json.load(open(marker))
    if data.get('success'):
        successes.append(data)

# Analyze what made them successful
for s in successes:
    print(f"{s['ground_truth']}: confidence={s['confidence']:.3f}, rank={s['rank']}")
```

### 3. Compare Successes vs Failures

```bash
# Get fault types that have both successes and failures
python3 -c "
import json
from pathlib import Path
from collections import defaultdict

by_fault = defaultdict(lambda: {'success': 0, 'fail': 0})

for marker in Path('data/batch_run').rglob('RCAInvestigated.marker'):
    data = json.load(open(marker))
    label = json.load(open(marker.parent / 'label.json'))
    fault = label['fault_type']

    if data.get('success'):
        by_fault[fault]['success'] += 1
    else:
        by_fault[fault]['fail'] += 1

# Show mixed results
for fault, counts in sorted(by_fault.items()):
    if counts['success'] > 0 and counts['fail'] > 0:
        rate = counts['success'] / (counts['success'] + counts['fail'])
        print(f'{fault}: {counts[\"success\"]}/{counts[\"success\"]+counts[\"fail\"]} ({rate:.0%})')
"
```

**Then:** Deep dive into specific episodes to understand the difference

### 4. Tune Algorithm Based on Findings

**If Rank 1 is low (<40%):**
- Scoring weights may be wrong
- Top candidates are equally likely
- Need better discriminative features

**If Rank 3-5 is high (>30%):**
- Good signals but weak confidence
- Adjust scoring to boost correct candidates
- May need ensemble methods

**If certain fault types fail:**
- Add fault-specific detection rules
- Include specialized metrics
- Adjust temporal windows

## Integration with Development

### Workflow

```bash
# 1. Make algorithm changes
vim analysis/sotaanalyzer/root_cause_detector.py

# 2. Clear old results
find data/batch_run -name "RCA*.marker" -o -name "rca_analysis.json" | xargs rm -f

# 3. Re-run batch
python3 batch_rca_discovery.py data/batch_run

# 4. Compare with previous run
# Report automatically shows new results

# 5. Track improvement
echo "Date,SuccessRate,Rank1,Rank2,Rank3" >> rca_improvements.csv
python3 -c "..." >> rca_improvements.csv  # Extract metrics
```

### Metrics to Track Over Time

1. **Overall success rate** (target: >50% with top-5)
2. **Rank 1 percentage** (target: >60% of successes)
3. **Average confidence** (target: >0.5 for Rank 1)
4. **Fault type coverage** (target: >50% for each type)
5. **Service detection rate** (target: >30%, currently 0%!)

## Report Output Files

The batch script creates a comprehensive log:

```
batch_rca_full.log    ← Complete output with detailed report
```

All report data is also available programmatically:

```python
from analyze_batch_results import analyze_results

# This function returns all metrics
# (can be enhanced to return dict instead of print)
analyze_results('data/batch_run')
```

## Key Takeaways

**Current Performance (60 episodes):**
- ✅ 31.7% success rate (19/60)
- ✅ 47% of successes at Rank 1 (high confidence)
- ⚠️ 0% success on service-level faults (0/24)
- ⚠️ Only 3 candidates on average (limiting success potential)

**Top Priorities:**
1. Fix service-level fault detection (0% → >30%)
2. Improve candidate generation (3 → 5+ candidates)
3. Focus on 0% fault types (cpu_saturation, memory_leak, etc.)
4. Reduce false positives (devices_db, payment_gateway)

**Strengths:**
- Queue faults: 100% (4/4)
- Cache faults: 100% (4/4)
- Error injection: 100% (4/4)
- High Rank 1 rate when successful (47%)
