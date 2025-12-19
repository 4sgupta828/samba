# RCA Evaluation Results: Time Windows Only

## Summary

Evaluated RCA with **improved time windows** (point-in-time analysis) but **WITHOUT pod coverage filtering** yet.

### Overall Performance

**Accuracy Metrics:**
- Ground truth @ Rank 1: **5/17 (29.4%)**
- Ground truth @ Rank 3: **9/17 (52.9%)**
- Ground truth @ Rank 5: **12/17 (70.6%)**
- MRR (Mean Reciprocal Rank): **0.463**

**False Positives:**
- Episodes with FPs: **12/17 (70.6%)**
- Total FP instances: **80**
- Average FPs per episode: **6.7**

### What Changed

**✓ Implemented:**
- Point-in-time analysis (not episode aggregation)
- Percentage-based window sizing
- Data-driven timing (no magic numbers)
- Proper separation between baseline and fault periods

**✗ Not Yet Implemented:**
- Pod coverage-based confidence filtering
- Outlier pod detection and downweighting

### Performance by Fault Type

| Fault Type | Episodes | @Rank1 | FP Count |
|------------|----------|--------|----------|
| cache_failure | 1 | ✓ | 0 |
| cpu_saturation | 1 | ✗ | 1 |
| disk_io_saturation | 1 | ✓ | 0 |
| hot_shard | 1 | ✗ | 4 |
| inject_errors | 2 | ✗ | 25 |
| inject_latency | 3 | ✗ | 31 |
| memory_leak | 1 | ✗ | 1 |
| memory_pressure | 1 | ✗ | 3 |
| memory_thrashing | 1 | ✗ | 2 |
| network_partition | 1 | ✓ | 0 |
| noisy_neighbor | 1 | ✗ | 9 |
| queue_consumer_slowdown | 1 | ✓ | 0 |
| thread_exhaustion | 2 | 1/2 | 4 |

### Analysis

**Successes (5/17 @ Rank 1):**
1. **cache_failure** - Clean ranking
2. **disk_io_saturation** - Correct identification
3. **network_partition** - Strong network detection
4. **queue_consumer_slowdown** - Good performance
5. **thread_exhaustion** (1 of 2) - Partial success

**Problem Cases:**

**High FP Count (inject_latency, inject_errors):**
- inject_latency: 31 FPs across 3 episodes
- inject_errors: 25 FPs across 2 episodes
- **Root cause**: Likely cascading latency/errors creating many candidates
- **Need**: Better symptom type distinction (primary vs secondary)

**Noisy neighbor (9 FPs):**
- Ground truth @ rank 10
- Many nodes appear degraded
- **Need**: Pod-level outlier detection

**Hot shard (4 FPs):**
- Specific pod issue not detected correctly
- **Need**: Pod coverage analysis

### Key Insight

**Time window improvements alone are not sufficient.**

While the new windows provide:
- ✓ Clean separation (no recovery contamination)
- ✓ Proper steady-state comparison
- ✓ Data-driven timing

**The core problem remains:** Outlier pods and cascading effects are still treated as high-confidence root cause evidence.

### Next Steps (Priority Order)

**1. Pod Coverage Filtering (HIGH PRIORITY)**
```python
# In whitebox_rca.py:426-430
if health_metadata.get('source') == 'pod-level':
    coverage = health_metadata.get('coverage', 0)

    if coverage >= 0.8:
        confidence = 'high'
        multiplier = 1.0
    elif coverage >= 0.5:
        confidence = 'medium'
        multiplier = 0.6
    else:
        # Outlier pods (<50% coverage)
        confidence = 'low'
        multiplier = 0.2  # Heavy discount
```

**Expected Impact:**
- Reduce false positives from outlier pods
- Better distinguish root cause (service-wide) from victims (random pods)
- Should improve precision significantly

**2. Symptom Type Weighting (MEDIUM PRIORITY)**
- Distinguish primary symptoms (errors generated) from secondary (errors received)
- Downweight nodes with only cascading symptoms
- Expected: Reduce FPs in inject_latency/inject_errors cases

**3. Physics Coverage Threshold (LOW PRIORITY)**
- Require minimum physics coverage for candidates
- Filter out nodes that don't explain system behavior
- Expected: Reduce noisy candidates

### Comparison Note

Cannot directly compare with old results because:
- Old results file format doesn't match
- Old results may not have episode_id mappings

**Recommendation**: Run old approach on same episodes to establish baseline, then compare.

### Conclusion

**Time windows are working correctly** (100% steady fault coverage validated), but **false positives persist** because we're not filtering outlier pod evidence.

**Next action:** Implement pod coverage filtering to address the core false positive issue.
