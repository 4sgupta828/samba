# SOTA Analyzer - Quick Overview

## What is this?

A **State-of-the-Art (SOTA) fault propagation analysis system** that systematically detects root causes in distributed systems using multi-layered analysis.

## Quick Start

```bash
# Blind root cause detection (without knowing the answer)
python analyze_sota.py data/episode_dir --mode discovery

# Validation against ground truth
python analyze_sota.py data/episode_dir --mode validation

# Save detailed JSON
python analyze_sota.py data/episode_dir --output results.json
```

## What It Does

1. **Pod-Level Forensics**
   - Detects outlier pods using IQR method
   - Identifies hot pods (traffic imbalance)
   - Finds noisy neighbor effects (co-location issues)

2. **Health Classification**
   - HEALTHY / DEGRADED / IMPACTED / CRITICAL
   - Context-aware rules (not just thresholds)
   - Considers metric types and severity distribution

3. **Root Cause Detection**
   - Identifies leaf nodes (DBs, caches, external services)
   - Checks if all dependencies are healthy
   - Returns top-3 candidates with probability scores

4. **Multi-Path Convergence**
   - How many impacted nodes have paths to this candidate?
   - Was it impacted first? (temporal precedence)
   - How critical is it in the topology? (betweenness centrality)

5. **Network Partition Detection**
   - Special case: no single root cause
   - Multiple nodes with 100% error rates to dependencies

## File Structure

```
analysis/sotaanalyzer/
├── __init__.py                      # Package exports
├── README.md                        # Full documentation
├── OVERVIEW.md                      # This file
├── pod_analysis.py                  # Pod-level forensics
├── health_classifier.py             # Health classification
├── root_cause_detector.py           # Root cause detection
└── sota_propagation_analyzer.py     # Main orchestrator
```

## Example Output

```
TOP ROOT CAUSE CANDIDATES
1. redis_cache (Cache)
   Probability: 0.842 (HIGH confidence)
   ✓ Leaf node (no dependencies)
   ✓ Impacted first (t=125.0s)
   ✓ 15 impact paths converge here
   ✓ Fault signature match: cache_failure

SERVICE IMPACT SUMMARY
• upload_service
  Severity: 0.961 (across 3 pods)
  Pod Consensus: 100% pods impacted
  ⚠️  2 outlier pods detected
```

## Why SOTA?

Unlike simple threshold-based systems, this analyzer:
- Works **without knowing** the root cause (blind detection)
- Uses **multiple evidence sources** (convergence, timing, topology, signatures)
- Handles **pod-level nuances** (outliers, hot pods, noisy neighbors)
- Detects **special cases** (network partitions)
- Provides **probabilistic rankings** (top-3 with confidence scores)
- Has **adaptive time windows** based on topology size

## See Also

- **Full Documentation**: `README.md` in this directory
- **CLI Tool**: `analyze_sota.py` in project root
- **Base Analysis**: `analysis/propagation_analyzer.py` (statistical foundation)
