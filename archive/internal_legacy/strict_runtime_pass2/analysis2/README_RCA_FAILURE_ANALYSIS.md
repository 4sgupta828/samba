# RCA Failure Analysis Tool

Analyzes RCA failures to understand why ground truth was not ranked as #1 and provides concrete parameter adjustment recommendations.

## Usage

### Single Episode Analysis

```bash
python3 analyze_rca_failure.py <episode_directory>
```

Example:
```bash
python3 analyze_rca_failure.py ../data/batch_run_20251215_164016/data_20251215_170338/ep_0
```

### Batch Analysis

To analyze multiple episodes from a batch run:

```bash
# Find all failed RCA episodes and analyze them
find ../data/batch_run_20251215_164016 -name "rca_analysis.json" -type f | while read rca_file; do
    episode_dir=$(dirname "$rca_file")

    # Check if RCA failed (ground truth not in top-5)
    found_in_top_k=$(python3 -c "import json; print(json.load(open('$rca_file'))['found_in_top_k'])")

    if [ "$found_in_top_k" = "False" ]; then
        echo "Analyzing failed RCA: $episode_dir"
        python3 analyze_rca_failure.py "$episode_dir"
    fi
done
```

### Quick Batch Script

Create a file called `analyze_all_failures.sh`:

```bash
#!/bin/bash
# Analyze all RCA failures in a batch run directory

BATCH_DIR=${1:?"Usage: $0 <batch_run_directory>"}

echo "Scanning for RCA failures in: $BATCH_DIR"
echo ""

failure_count=0
success_count=0

for data_dir in "$BATCH_DIR"/data_*/; do
    for ep_dir in "$data_dir"ep_*/; do
        rca_file="$ep_dir/rca_analysis.json"

        if [ -f "$rca_file" ]; then
            # Check if RCA failed
            found_in_top_k=$(python3 -c "import json; f=open('$rca_file'); data=json.load(f); print(data['found_in_top_k']); f.close()" 2>/dev/null)

            if [ "$found_in_top_k" = "False" ]; then
                echo "Analyzing: $ep_dir"
                python3 analyze_rca_failure.py "$ep_dir"
                failure_count=$((failure_count + 1))
                echo ""
            else
                success_count=$((success_count + 1))
            fi
        fi
    done
done

echo "================================"
echo "Analysis Complete"
echo "  RCA Failures Analyzed: $failure_count"
echo "  RCA Successes: $success_count"
echo "================================"
```

Make it executable:
```bash
chmod +x analyze_all_failures.sh
```

Run it:
```bash
./analyze_all_failures.sh ../data/batch_run_20251215_164016
```

## Output Files

For each analyzed episode, the script generates:

1. **`rca_failure_analysis.md`** - Human-readable markdown report
2. **`rca_failure_analysis.json`** - Machine-readable JSON report

Both files are saved in the same episode directory.

## Report Contents

The analysis report includes:

### 1. Executive Summary
- Current rank of ground truth
- Score gap with top-ranked candidate
- Number of issues found
- Projected improvement with recommended fixes

### 2. Ground Truth Analysis
- Score component breakdown
- Trace evidence analysis
- Health evidence analysis
- Comparison with top-ranked candidates

### 3. Root Cause Issues
Identifies specific problems such as:
- **health_filter_false_negative**: Component marked healthy despite strong evidence
- **missing_symptoms**: No symptoms detected for faulty component
- **low_integrated_score**: Health score too low
- **trace_score_underweighted**: Trace evidence not weighted enough
- **false_positive_ranked_higher**: Victim components ranked higher than root cause

### 4. Recommendations
Concrete parameter adjustments organized by priority:
- **Critical**: Must-fix issues that completely break RCA
- **High**: Important fixes that significantly improve accuracy
- **Medium**: Nice-to-have improvements

Each recommendation includes:
- Parameter name
- Current value
- Recommended value
- Rationale
- Expected impact

### 5. Projected Impact
Shows what the ranking would be if recommended adjustments were applied:
- Adjusted scores for all candidates
- New projected rank for ground truth
- Score improvement estimate

## Example Output

```
✓ Analysis complete!
  - Markdown report: ../data/.../ep_0/rca_failure_analysis.md
  - JSON report: ../data/.../ep_0/rca_failure_analysis.json

Summary:
  - Ground truth ranked #8
  - Found 6 issues (1 critical)
  - 3 high-priority recommendations
  - Projected improvement: Rank 8 -> Rank 1
  - Score improvement: 2.50 -> 152.50 (+150.00)
```

## Common Issues Detected

### 1. Health Filter False Negatives
**Symptom**: Ground truth marked as healthy despite authoritative trace evidence showing degradation

**Recommendation**: Override health filter when authoritative trace shows >2x degradation

### 2. Missing Symptoms for Infrastructure Components
**Symptom**: Caches, queues, and databases often don't show direct metrics degradation

**Recommendation**: Use indirect signals (downstream impact, trace data) as symptoms

### 3. Underweighted Trace Evidence
**Symptom**: Authoritative trace evidence not prioritized over symptom-based health scores

**Recommendation**: Multiply trace score by 5x when authoritative, add flat bonus

### 4. False Positives (Victim Services)
**Symptom**: Downstream services with cascading failures ranked higher than root cause

**Recommendation**: Penalize non-authoritative trace evidence by 70%

## Aggregate Analysis

To get aggregate statistics across all failures:

```bash
# Count issues by type
find ../data/batch_run_20251215_164016 -name "rca_failure_analysis.json" -type f -exec \
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); \
  print('\n'.join([i['issue_type'] for i in data['root_cause_issues']]))" {} \; | \
  sort | uniq -c | sort -rn
```

To extract all recommendations:

```bash
find ../data/batch_run_20251215_164016 -name "rca_failure_analysis.json" -type f -exec \
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); \
  print('\n'.join([r['recommendation_id'] + ': ' + r['title'] for r in data['recommendations']]))" {} \;
```

## Integration with RCA Code

The parameter names in the recommendations (e.g., `health_filter.override_on_authoritative_trace`)
are designed to match the RCA configuration structure. You can use these to:

1. Update your RCA configuration files
2. Create A/B tests with different parameter values
3. Build automated tuning systems

## Troubleshooting

**Error: Directory not found**
- Ensure the episode directory path is correct
- Check that the directory contains `rca_analysis.json`

**Error: Ground truth node not found**
- Verify the `label.json` file contains the correct ground truth
- Check that the ground truth node exists in `rca_analysis.json` all_candidates list

**No output files generated**
- Check write permissions in the episode directory
- Ensure Python 3 is installed and in PATH
