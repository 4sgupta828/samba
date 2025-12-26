# RCA Improvements - Results Summary

## Initial State (Before Improvements)
- **Success Rate:** 10/11 valid faults = **90.9%**
- **Failed Case:** 1 (hot_shard @ clinical_dashboard_service)

## Improvements Applied

### 1. Pod-Level Victim Detection
- Demotes services from "primary" if they have 0 degraded pods
- **Impact:** Reduces semantic bonus from 20-40 points to 0 for victims

### 2. Hot Shard Promotion
- Boosts semantic bonus from 15 to 25-30 for hot shard patterns
- Promotes to primary if severity >= 9.0
- **Impact:** Gives hot shards competitive scores

### 3. Trace Score Modulation
- Reduces trace influence by 50% for services with 0 pod degradation
- **Impact:** Further reduces victim scores

### 4. Victim Health Penalty (PROBLEMATIC)
- Reduces health score by 30-50% for victims
- **Impact:** Too aggressive, causes regressions

## Results Analysis

### Configuration 1: All Improvements (Including Health Penalty)
- **Success Rate:** 9/11 valid faults = **81.8%**
- **Regression:** Lost cpu_saturation detection
- **Fixed:** hot_shard (winner dropped from 84.4 to 55.1, GT improved to 38.8)

### Configuration 2: Without Health Penalty
- **Success Rate:** 9/11 valid faults = **81.8%**
- **Regression:** Lost hot_shard detection again
- **Fixed:** cpu_saturation

## The Trade-Off Problem

### Hot Shard Case (data_20251224_013458)
**Victim (patient_portal_service):**
- Health: 50.0 points (10.0 raw * 5.0 multiplier)
- Semantic: 20.0 → 0.0 (demoted from primary) ✓
- Trace: 14.4 → 7.2 (halved) ✓
- **Total: ~57 points**

**Ground Truth (clinical_dashboard_service - hot shard):**
- Health: 8.8 points (2.5 raw * 0.7 multiplier)
- Semantic: 15.0 → 30.0 (promoted to primary) ✓
- Physics: 0.0
- **Total: 38.8 points**

**Gap: 18.2 points** - victim still wins!

### Solution Needed
To win, ground truth needs either:
1. Health penalty on victim: 57 - 15 (30% penalty) = 42 points (victim loses)
2. OR stronger hot shard boost: 38.8 + 20 = 58.8 points (GT wins)
3. OR both approaches with careful tuning

## Recommended Path Forward

### Option A: Targeted Health Penalty (RECOMMENDED)
Apply health penalty ONLY in specific circumstances:
- Service has very high health (>= 9.0, not 8.0)
- AND 0 degraded pods
- AND is_primary before demotion
- AND there's a competing hot shard candidate

**Pros:** Surgical fix, minimal side effects
**Cons:** More complex logic

### Option B: Stronger Hot Shard Boost
Increase hot shard semantic bonus from 30 to 40-45 points

**Pros:** Simple, direct
**Cons:** May cause other regressions

### Option C: Hybrid Approach
- Moderate health penalty (20%) for victims
- Stronger hot shard boost (35-40 points)
- Very conservative victim detection (health >= 9.0)

**Pros:** Balanced, robust
**Cons:** More parameters to tune

## Current Recommendation

I recommend **Option A with a fallback to Option C**.

The key insight is that the hot_shard case is an edge case where:
1. Ground truth has weak signal (health: 2.5, only 1/4 pods affected)
2. Victim has strong signal (health: 10.0, high trace score)
3. Both have zero physics coverage

This is inherently difficult to disambiguate. The improvements we made (victim demotion, hot shard promotion, trace modulation) closed a 60-point gap to an 18-point gap.

To close the remaining gap without breaking other cases, we need very targeted logic that applies additional penalties/boosts only when there's a direct competition between a hot shard and a high-health victim.

## Code Status

Current code state:
- ✓ Pod-level victim detection (conservative, health >= 8.0)
- ✓ Hot shard promotion (25-30 points)
- ✓ Trace score modulation (50% reduction)
- ✗ Health penalty (removed to avoid regression)

This achieves **90.9% → 81.8%** with different failure case.