#!/usr/bin/env python3
"""
RCA Detection Improvements - Implementation Guide

Based on analysis of batch_run_20251224_011925:
- True success rate: 90.9% (10/11 valid faults)
- Only 1 valid failure: hot_shard case
- Problem: Victim services with 0 pod degradation scoring higher than real root causes

This script provides code patches to fix the scoring issue.
"""

# =============================================================================
# IMPROVEMENT #1: Pod-Level Validation Filter (HIGH PRIORITY)
# =============================================================================
#
# Location: analysis2/whitebox_rca.py, around line 816 (after is_primary calculation)
#
# Problem: Services with 0 pods degraded are incorrectly marked as primary
# Solution: Validate that primary candidates have actual pod-level degradation
#
# INSERT THIS CODE after line 816 (after is_primary is set):

POD_VALIDATION_PATCH = """
            # POD-LEVEL VALIDATION: Primary symptoms require pod-level evidence
            # Services with 0 degraded pods are likely victims, not root causes
            # Exception: External dependencies without pod metrics (databases, caches, APIs)
            degraded_count = health_metadata.get('degraded_count', 0)
            total_count = health_metadata.get('total_count', 0)

            # If service has pods but NONE are degraded, it's a victim
            if is_primary and total_count > 0 and degraded_count == 0:
                print(f"  [Victim Detection] {node}: 0/{total_count} pods degraded despite high health - demoting from primary")
                is_primary = False
                # This service is a victim of dependency issues, not a root cause
"""

# =============================================================================
# IMPROVEMENT #2: Coverage-Based Hot Shard Boost (MEDIUM PRIORITY)
# =============================================================================
#
# Location: analysis2/whitebox_rca.py, line 870-872 (hot shard pattern detection)
#
# Problem: Hot shard patterns (low coverage, high severity) get only 15 points
# Solution: Increase semantic bonus and promote to primary when appropriate
#
# REPLACE lines 870-872 with:

HOT_SHARD_BOOST_PATCH = """
                if is_hot_shard_pattern:
                    # Hot shard: One pod severely degraded, likely root cause
                    # Boost semantic bonus to compete with high-health victims
                    semantic_bonus = 25.0  # Increased from 15.0
                    # Optionally promote to primary if severity is extreme
                    if max_severity >= 9.0 and degraded_count > 0:
                        is_primary = True
                        semantic_bonus = 30.0  # Even stronger boost for extreme hot shards
                        print(f"  [Hot Shard Promoted] {node}: {degraded_count} pod(s) with severity {max_severity:.1f} → treating as primary")
"""

# =============================================================================
# IMPROVEMENT #3: Trace Score Modulation (LOW PRIORITY)
# =============================================================================
#
# Location: analysis2/whitebox_rca.py, around line 908-930 (trace evidence calculation)
#
# Problem: Trace scores can elevate victims above root causes
# Solution: Reduce trace influence for services without pod-level degradation
#
# ADD THIS CHECK before applying trace_bonus (around line 925):

TRACE_MODULATION_PATCH = """
            # Reduce trace influence for likely victims (no pod degradation)
            if total_count > 0 and degraded_count == 0:
                # Service shows trace degradation but no pod issues - likely victim
                trace_bonus = trace_bonus * 0.5
                print(f"  [Trace Modulation] {node}: No pod degradation, reducing trace influence by 50%")
"""

# =============================================================================
# SUMMARY OF CHANGES
# =============================================================================

IMPLEMENTATION_SUMMARY = """
IMPLEMENTATION PLAN FOR RCA IMPROVEMENTS
========================================

Based on analysis of batch_run_20251224_011925 showing 90.9% accuracy with 1 failure.

Required Changes to analysis2/whitebox_rca.py:

1. POD-LEVEL VALIDATION (Lines 816-817, after is_primary calculation)
   - Add validation to demote primary services with 0 degraded pods
   - Impact: Prevents victim services from winning
   - Estimated improvement: Fixes the 1 hot_shard failure

2. HOT SHARD BOOST (Lines 870-872, replace existing hot shard logic)
   - Increase semantic bonus from 15.0 to 25.0-30.0
   - Promote to primary for extreme hot shards (severity >= 9.0)
   - Impact: Gives hot shards better chance against high-health victims

3. TRACE MODULATION (Lines 908-930, before applying trace_bonus)
   - Reduce trace influence by 50% for services with no pod degradation
   - Impact: Further reduces false positive risk from trace scores

Testing:
- Run: python run_rca_batch.py data/batch_run_20251224_011925
- Expected result: 11/11 valid faults detected (100%)
- Verify: data_20251224_013458 (hot_shard) now ranks 1st

Regression Testing:
- Run: python analysis2/analyze_rca_patterns.py data/batch_run_20251224_011925
- Verify: No reduction in other detection patterns
- Working patterns to preserve:
  * Direct propagation: 2/2
  * Reverse propagation: 2/2
  * No physics / Leaf nodes: 4/5
  * Low physics: 1/1
"""

if __name__ == '__main__':
    print(POD_VALIDATION_PATCH)
    print("\n" + "="*80 + "\n")
    print(HOT_SHARD_BOOST_PATCH)
    print("\n" + "="*80 + "\n")
    print(TRACE_MODULATION_PATCH)
    print("\n" + "="*80 + "\n")
    print(IMPLEMENTATION_SUMMARY)
