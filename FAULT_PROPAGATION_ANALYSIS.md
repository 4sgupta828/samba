# Fault Propagation Analysis Report

## Executive Summary

Tested all 11 fault type/role combinations (3 episodes each) to analyze fault propagation behavior.

### Results Overview

- **✓ Full Propagation (3/11)**: All episodes show propagation
- **⚠ Partial Propagation (3/11)**: Some episodes show propagation
- **✗ Failed Generation (5/11)**: Episodes failed to generate

### Key Finding

**Fault propagation IS working** but with inconsistency issues. The main problems are:
1. Random scenario lookup failing for some combinations
2. Timeout issues for slow_queries and queue_consumer_slowdown
3. Inconsistent propagation across episodes for some fault types

---

## Detailed Results

### 1. Full Propagation (All 3/3 Episodes)

These combinations successfully propagate in every episode:

#### inject_latency on external ✓
- **Episodes**: 3/3 with propagation
- **Impact levels**: Mix of MEDIUM and LOW, one episode with CRITICAL/HIGH
- **Average affected nodes**: 3-5 beyond root cause
- **Status**: WORKING WELL

#### connection_exhaustion on database ✓
- **Episodes**: 3/3 with propagation
- **Impact levels**: Mostly LOW and MEDIUM
- **Average affected nodes**: 2-9 beyond root cause
- **Status**: WORKING WELL

#### inject_errors on external ✓
- **Episodes**: 3/3 with propagation
- **Impact levels**: Strong - mix of CRITICAL, HIGH, MEDIUM, and LOW
- **Average affected nodes**: 3-7 beyond root cause
- **Status**: WORKING EXCELLENTLY - Best propagation observed

---

### 2. Partial Propagation (Some Episodes Fail)

#### cpu_saturation on service ⚠
- **Episodes**: 2/3 with propagation
- **Failed episode**: ep_1 - only 2 nodes total, both NEGLIGIBLE impact
- **Successful episodes**: 8-9 nodes affected with LOW-MEDIUM impact
- **Issue**: Topology randomness - root cause may be isolated
- **Recommendation**: Ensure root cause service is well-connected

#### inject_latency on cache ⚠
- **Episodes**: 1/3 with propagation
- **Failed episodes**: ep_0 - 4 of 5 nodes NEGLIGIBLE, 1 MEDIUM (root only)
- **Successful episode**: ep_2 - EXCELLENT propagation (1 CRITICAL, 4 HIGH)
- **Issue**: Inconsistent - may depend on cache usage patterns or topology
- **Recommendation**: Investigate why some caches don't propagate

#### cache_failure on cache ⚠
- **Episodes**: 2/3 with propagation
- **Failed episode**: ep_0 - 3 of 4 nodes NEGLIGIBLE
- **Successful episodes**: 3 nodes LOW impact, 2 nodes with LOW+NEGLIGIBLE
- **Issue**: Cache may not be critical path in some topologies
- **Recommendation**: Ensure cache is on critical request path

---

### 3. Failed Generation

#### memory_leak on service ✗
- **Status**: 0 episodes generated
- **Root Cause**: Scenario lookup failing
- **Error**: "Could not find scenario with fault_type='memory_leak' and role='service'"
- **Issue**: Random sampling after 100 attempts can't find Level 1 scenario (10% probability)

#### inject_latency on service ✗
- **Status**: 0 episodes generated
- **Root Cause**: Scenario lookup failing (same as above)
- **Issue**: Random sampling can't reliably find Level 1 scenarios

#### enable_background_job on database ✗
- **Status**: 0 episodes generated
- **Root Cause**: Scenario lookup failing
- **Issue**: Random sampling can't reliably find specific Level 2 scenario

#### slow_queries on database ✗
- **Status**: Timeout after 10 minutes
- **Root Cause**: Simulation taking too long
- **Possible causes**:
  - Database slowdown causing cascade that never stabilizes
  - Simulation duration too long (600 seconds)
  - Infinite retry loops
  - Deadlock in simulation

#### queue_consumer_slowdown on queue ✗
- **Status**: Timeout after 10 minutes
- **Root Cause**: Simulation taking too long
- **Possible causes**:
  - Message redelivery causing exponential backlog growth
  - Visibility timeout issues
  - Simulation duration too long (900 seconds)
  - Infinite message loops

---

## Root Cause Analysis

### Issue 1: Scenario Lookup Algorithm (3 failures)

**Location**: generate_dataset.py:154-169

**Problem**: Random sampling can't reliably find specific scenarios

**Solution**: Direct search across all levels

### Issue 2: Timeout Simulations (2 failures)

**Affected**: slow_queries, queue_consumer_slowdown

**Problem**: These faults may cause cascading failures that prevent simulation completion

### Issue 3: Inconsistent Propagation (3 combinations)

**Affected**: cpu_saturation (service), inject_latency (cache), cache_failure (cache)

**Problem**: Same fault type/role sometimes propagates, sometimes doesn't

---

## Remediation Plan

### Priority 1: Fix Scenario Lookup (CRITICAL)

Replace random sampling with direct search in generate_dataset.py

### Priority 2: Investigate Timeout Issues (HIGH)

Add logging and timeout protection for slow_queries and queue_consumer_slowdown

### Priority 3: Improve Propagation Consistency (MEDIUM)

Ensure fault targets are well-connected and on critical paths
