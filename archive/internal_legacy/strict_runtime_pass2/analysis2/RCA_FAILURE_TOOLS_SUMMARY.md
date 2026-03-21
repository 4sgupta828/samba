# RCA Failure Analysis Tools - Complete Guide

This package provides comprehensive tools for analyzing RCA failures and generating actionable parameter adjustment recommendations.

## 📦 What's Included

### 1. `analyze_rca_failure.py` - Single Episode Analysis
**Purpose**: Analyzes a single RCA failure episode to identify root causes and recommend fixes.

**Usage**:
```bash
python3 analyze_rca_failure.py <episode_directory>
```

**Example**:
```bash
python3 analyze_rca_failure.py ../data/batch_run_20251215_164016/data_20251215_170338/ep_0
```

**Output**:
- `rca_failure_analysis.md` - Human-readable report
- `rca_failure_analysis.json` - Machine-readable data

### 2. `analyze_all_failures.sh` - Batch Analysis
**Purpose**: Automatically analyzes all RCA failures in a batch run directory.

**Usage**:
```bash
./analyze_all_failures.sh <batch_run_directory>
```

**Example**:
```bash
./analyze_all_failures.sh ../data/batch_run_20251215_164016
```

**What it does**:
- Scans all episodes in the batch directory
- Identifies which episodes had RCA failures (ground truth not in top-k)
- Runs `analyze_rca_failure.py` on each failure
- Reports summary statistics

### 3. `summarize_failures.py` - Aggregate Analysis
**Purpose**: Aggregates results across all analyzed failures to identify patterns.

**Usage**:
```bash
python3 summarize_failures.py <batch_run_directory>
```

**Example**:
```bash
python3 summarize_failures.py ../data/batch_run_20251215_164016
```

**Output**:
- `rca_failures_summary.md` - Aggregate report
- `rca_failures_summary.json` - Aggregate statistics

**Provides**:
- Common issue patterns
- Fault type correlations
- Most impactful recommendations
- Statistical summaries

## 🚀 Quick Start Workflow

### Step 1: Analyze All Failures
```bash
cd analysis2
./analyze_all_failures.sh ../data/batch_run_20251215_164016
```

This generates individual analysis reports for each failed episode.

### Step 2: Generate Aggregate Summary
```bash
python3 summarize_failures.py ../data/batch_run_20251215_164016
```

This creates a summary report across all failures.

### Step 3: Review Results
```bash
# View the aggregate summary
cat ../data/batch_run_20251215_164016/rca_failures_summary.md

# View individual failure reports
cat ../data/batch_run_20251215_164016/data_*/ep_*/rca_failure_analysis.md
```

## 📊 Understanding the Reports

### Individual Episode Analysis

Each episode analysis includes:

1. **Executive Summary**
   - Current rank vs expected rank
   - Score gap analysis
   - Number of issues found
   - Projected improvement

2. **Ground Truth Analysis**
   - Score component breakdown
   - Trace evidence (latency degradation)
   - Health evidence (symptoms)
   - Comparison with top-ranked candidates

3. **Root Cause Issues**
   - `health_filter_false_negative`: Marked healthy despite evidence
   - `missing_symptoms`: No symptoms detected
   - `low_integrated_score`: Health score too low
   - `trace_score_underweighted`: Trace evidence not weighted enough
   - `false_positive_ranked_higher`: Victim services ranked higher

4. **Recommendations**
   - Concrete parameter adjustments
   - Priority levels (critical/high/medium)
   - Expected impact estimates

5. **Projected Impact**
   - Simulated scores with recommended fixes
   - New projected ranking

### Aggregate Summary

The aggregate summary provides:

1. **Overall Statistics**
   - Average actual rank
   - Average projected improvement
   - Score gap distributions

2. **Failure Patterns**
   - By fault type
   - By component role
   - Common issue combinations

3. **Top Priority Actions**
   - Most frequently needed fixes
   - Highest impact recommendations

## 🔧 Common Issues and Fixes

### Issue 1: Health Filter False Negatives
**When**: Ground truth marked healthy despite authoritative trace evidence

**Fix**:
```python
# Recommended parameter adjustments
health_filter.override_on_authoritative_trace = True
health_filter.min_trace_degradation_to_override = 2.0
```

**Impact**: Prevents false negatives for components with strong trace evidence but no direct symptoms.

### Issue 2: Trace Score Underweighted
**When**: Authoritative trace evidence not prioritized

**Fix**:
```python
# Recommended parameter adjustments
scoring.trace_score_multiplier = 5.0  # When authoritative
scoring.authoritative_trace_bonus = 50.0
```

**Impact**: Gives authoritative trace evidence (like 6x latency increase) higher priority.

### Issue 3: Missing Symptoms for Infrastructure
**When**: Caches, queues, databases don't show direct metric degradation

**Fix**:
```python
# Recommended parameter adjustments
symptom_detection.cache.enable_indirect_signals = True
symptom_detection.cache.trace_as_symptom_threshold = 2.0
symptom_detection.queue.enable_indirect_signals = True
symptom_detection.database.enable_indirect_signals = True
```

**Impact**: Uses downstream impact and trace data as symptoms for infrastructure components.

### Issue 4: False Positives (Victim Services)
**When**: Downstream services ranked higher than root cause

**Fix**:
```python
# Recommended parameter adjustments
scoring.non_authoritative_trace_penalty = 0.3
scoring.victim_detection_from_trace = True
```

**Impact**: Reduces scores for victim services with cascading failures.

## 📈 Example Output

```
Analyzing failed RCA: ../data/batch_run_20251215_164016/data_20251215_170338/ep_0
Analyzing RCA failure...

✓ Analysis complete!
  - Markdown report: .../ep_0/rca_failure_analysis.md
  - JSON report: .../ep_0/rca_failure_analysis.json

Summary:
  - Ground truth ranked #8
  - Found 6 issues (1 critical)
  - 3 high-priority recommendations
  - Projected improvement: Rank 8 -> Rank 1
  - Score improvement: 2.50 -> 152.50 (+150.00)

================================
Analysis Complete
  RCA Failures Analyzed: 15
  RCA Successes: 85
================================
```

## 🔍 Advanced Usage

### Filter by Issue Type

Find all episodes with health filter false negatives:
```bash
find ../data/batch_run_20251215_164016 -name "rca_failure_analysis.json" -exec \
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); \
  issues=[i for i in data['root_cause_issues'] if i['issue_type']=='health_filter_false_negative']; \
  print(sys.argv[1]) if issues else None" {} \;
```

### Extract Parameter Recommendations

Get all unique parameter recommendations:
```bash
find ../data/batch_run_20251215_164016 -name "rca_failure_analysis.json" -exec \
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); \
  params=[p['parameter'] for r in data['recommendations'] for p in r['parameter_adjustments']]; \
  print('\n'.join(set(params)))" {} \; | sort -u
```

### Calculate Success Rate Improvement

Compare current vs projected ranks:
```bash
find ../data/batch_run_20251215_164016 -name "rca_failure_analysis.json" -exec \
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); \
  actual=data['rca_summary']['actual_rank']; \
  projected=data['projected_impact']['ground_truth_projected_rank']; \
  print(f'{actual},{projected}')" {} \; | \
  awk -F',' '{actual+=$1; proj+=$2; count++} END {print "Avg Actual:", actual/count, "Avg Projected:", proj/count}'
```

## 🔄 Integration with RCA System

### Option 1: Manual Configuration Update
1. Review the recommendations in the summary report
2. Update your RCA configuration file with recommended parameters
3. Re-run RCA on test data
4. Verify improvement

### Option 2: Automated A/B Testing
```python
# Example: Test different parameter configurations
configs = [
    {'name': 'baseline', 'params': {}},
    {'name': 'high_trace_weight', 'params': {'trace_score_multiplier': 5.0}},
    {'name': 'override_health', 'params': {'override_on_authoritative_trace': True}},
]

for config in configs:
    run_rca_with_config(config['params'])
    analyze_results(config['name'])
```

### Option 3: Dynamic Tuning
Use the JSON output to build an automated tuning system that adjusts parameters based on failure patterns.

## 📝 Files Generated

For each episode:
```
ep_0/
├── rca_analysis.json           # Original RCA output
├── label.json                  # Ground truth
├── topology.json               # System topology
├── rca_failure_analysis.md     # Human-readable analysis (NEW)
└── rca_failure_analysis.json   # Machine-readable analysis (NEW)
```

For batch run:
```
batch_run_20251215_164016/
├── rca_failures_summary.md     # Aggregate analysis (NEW)
└── rca_failures_summary.json   # Aggregate statistics (NEW)
```

## 🐛 Troubleshooting

**Problem**: "Directory not found"
- Check the path is correct
- Ensure you're running from the correct directory

**Problem**: "No RCA failure analyses found"
- Run `analyze_rca_failure.py` first
- Check that episodes have `rca_analysis.json` files

**Problem**: "Ground truth node not found"
- Verify `label.json` contains correct ground truth
- Check that ground truth exists in `rca_analysis.json`

**Problem**: Scripts not executable
```bash
chmod +x analyze_rca_failure.py
chmod +x analyze_all_failures.sh
chmod +x summarize_failures.py
```

## 📚 Further Reading

- See `README_RCA_FAILURE_ANALYSIS.md` for detailed documentation
- Check individual episode reports for specific failure patterns
- Review aggregate summary for system-wide issues

## 💡 Tips

1. **Start with aggregate summary** to understand overall patterns
2. **Drill down into individual failures** for specific cases
3. **Prioritize critical and high-priority recommendations**
4. **Test parameter changes incrementally**
5. **Re-run analysis after changes** to verify improvement

## 📧 Questions?

If you have questions about:
- Specific recommendations: Review the rationale in the report
- Parameter meanings: Check the RCA configuration documentation
- Implementation: See the integration examples above
