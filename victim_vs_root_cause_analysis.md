# Distinguishing Root Cause from Victim: Problem Statement & Solution

## Problem Statement

**Core Issue**: The RCA treats all symptoms equally without understanding causal relationships.

**Specific Case (audit_queue vs audit_service)**:
```
Fault Injection:
  Component: audit_queue (MessageQueue)
  Fault: queue_consumer_slowdown (+200ms processing latency)
  
Observed Symptoms:
  1. audit_queue: queue_in_flight increased (d=0.67) → Score: 16.81, Rank #3
  2. audit_service: latency increased (d=1.06) → Score: 33.65, Rank #1
  
Causal Reality:
  audit_queue (root cause) → audit_service (victim)
  
RCA Behavior:
  Victim ranks ABOVE root cause (wrong!)
```

**Why This Happens**:
- Both components show symptoms
- audit_service has stronger symptom magnitude (d=1.06 > 0.67)
- RCA scores purely on symptom strength, ignoring causality
- No mechanism to identify that audit_service is a downstream victim

## Root Cause vs Victim Characteristics

| Property | Root Cause | Victim |
|----------|------------|--------|
| Fault Location | Internal to component | External (in dependency) |
| Symptom Type | Primary (resource/internal) | Secondary (performance/external) |
| Temporal Order | Breaks FIRST | Breaks LATER (after propagation) |
| Dependency | Depended upon | Depends on faulty component |
| Symptom Semantics | queue_in_flight ↑, CPU saturation | latency ↑, errors ↑ |

## Causality Signals (Ranked by Reliability)

### 1. Structural Causality ⭐⭐⭐ (Highest Reliability)
**Principle**: Use topology to infer causal direction

```
If A → B (A depends on B) and both show symptoms:
  - B is more likely root cause (A is victim)
  - Exception: Some faults propagate upstream (e.g., thundering herd)
  
If A ← B (B depends on A) and both show symptoms:
  - A is more likely root cause (B is victim)
```

**For queue_consumer_slowdown**:
```
audit_service --consumes--> audit_queue
Both have symptoms
Direction: audit_service DEPENDS ON audit_queue
Conclusion: audit_queue = root cause, audit_service = victim ✓
```

**Confidence**: High (topology is ground truth)

### 2. Symptom Semantics ⭐⭐⭐ (High Reliability)
**Principle**: Symptom type reveals causality

**Symptom Taxonomy**:
```
Primary Symptoms (Internal State):
  - Resource saturation: CPU ↑, memory ↑, threads ↑
  - Queue state: queue_depth ↑, queue_in_flight ↑
  - Internal errors: OOM, connection pool exhaustion
  → More likely ROOT CAUSE

Secondary Symptoms (External Performance):
  - Performance degradation: latency ↑, throughput ↓
  - External errors: 5xx errors, timeouts
  → Could be ROOT CAUSE or VICTIM (ambiguous)
```

**Causality Rule**:
```
If A has PRIMARY symptom + B has SECONDARY symptom + A→B dependency:
  → A = root cause, B = victim
```

**For queue_consumer_slowdown**:
```
audit_queue: queue_in_flight ↑ (PRIMARY - internal queue state)
audit_service: latency ↑ (SECONDARY - performance)
Dependency: audit_service → audit_queue
Conclusion: audit_queue = root cause ✓
```

**Confidence**: High for clear patterns, Medium for ambiguous cases

### 3. Temporal Causality ⭐⭐ (Medium Reliability)
**Principle**: Root cause breaks FIRST, victims break LATER

**Implementation**: Changepoint detection on time series
```
For each symptomatic component:
  1. Detect symptom onset time (changepoint)
  2. Compare onset times
  3. Earlier onset → higher root cause likelihood
```

**For queue_consumer_slowdown**:
```
Expected:
  t=180s: audit_queue.queue_in_flight starts increasing
  t=190s: audit_service.latency starts increasing (delayed)
  
If audit_queue breaks first → boost its score
```

**Challenges**:
- Requires fine-grained time series
- Gradual faults make onset detection hard
- Some faults propagate instantly

**Confidence**: Medium (depends on fault progression speed)

### 4. Fault Pattern Matching ⭐⭐ (Medium Reliability)
**Principle**: Known fault signatures reveal causality

**Queue Consumer Slowdown Pattern**:
```
IF:
  - Component is MessageQueue
  - queue_in_flight ↑ (processing delay)
  - Consumer component shows latency ↑
  - Topology: consumer depends on queue
THEN:
  - Queue is root cause
  - Consumer is victim
```

**Confidence**: High when pattern matches, N/A otherwise

## Proposed Solution: Multi-Signal Causality Scoring

### Architecture

```python
class CausalityAnalyzer:
    """Distinguishes root cause from victim using multiple signals."""
    
    def analyze_component_pair(self, comp_a, comp_b, graph):
        """
        Computes causality score between two symptomatic components.
        Positive score = A more likely root cause
        Negative score = B more likely root cause
        """
        score = 0
        evidence = []
        
        # Signal 1: Structural Causality (HIGHEST WEIGHT)
        if graph.has_edge(comp_a.id, comp_b.id):  # A depends on B
            score -= 4
            evidence.append(f"{comp_a.id} depends on {comp_b.id} → B likely root cause")
        elif graph.has_edge(comp_b.id, comp_a.id):  # B depends on A
            score += 4
            evidence.append(f"{comp_b.id} depends on {comp_a.id} → A likely root cause")
        
        # Signal 2: Symptom Semantics (HIGH WEIGHT)
        a_primary = has_primary_symptoms(comp_a)
        b_primary = has_primary_symptoms(comp_b)
        
        if a_primary and not b_primary:
            score += 3
            evidence.append(f"{comp_a.id} has primary symptoms, {comp_b.id} has secondary → A likely root cause")
        elif b_primary and not a_primary:
            score -= 3
            evidence.append(f"{comp_b.id} has primary symptoms, {comp_a.id} has secondary → B likely root cause")
        
        # Signal 3: Temporal (if available)
        onset_a = comp_a.symptom_onset_time
        onset_b = comp_b.symptom_onset_time
        if onset_a and onset_b and abs(onset_a - onset_b) > 10:  # >10s difference
            if onset_a < onset_b:
                score += 2
                evidence.append(f"{comp_a.id} broke first → A likely root cause")
            else:
                score -= 2
                evidence.append(f"{comp_b.id} broke first → B likely root cause")
        
        # Signal 4: Pattern Matching
        pattern_score = check_fault_patterns(comp_a, comp_b)
        score += pattern_score
        
        return CausalityResult(score, evidence)

def has_primary_symptoms(component):
    """Checks if component has primary (internal) symptoms."""
    primary_indicators = [
        'cpu_usage', 'memory_usage', 'thread_pool_active',
        'queue_depth', 'queue_in_flight', 'queue_utilization',
        'connection_pool_exhausted', 'disk_io_saturation'
    ]
    symptoms = set(component.symptoms)
    return any(indicator in str(symptoms) for indicator in primary_indicators)

def apply_victim_penalty(rankings, graph):
    """
    Applies penalty to components that are victims of faulty dependencies.
    """
    for candidate in rankings:
        # Get all dependencies of this candidate
        dependencies = list(graph.predecessors(candidate.id))
        
        for dep_id in dependencies:
            dep_candidate = find_candidate(rankings, dep_id)
            if dep_candidate and dep_candidate.has_symptoms:
                # Analyze causality
                causality = analyze_component_pair(candidate, dep_candidate, graph)
                
                if causality.score < -2:  # Strong evidence dep is root cause
                    # Apply victim penalty
                    penalty = calculate_victim_penalty(candidate, dep_candidate)
                    candidate.score *= penalty
                    candidate.victim_info = {
                        'likely_root_cause': dep_id,
                        'evidence': causality.evidence,
                        'penalty_applied': penalty
                    }
```

### Application to Queue Consumer Slowdown

```python
# Analysis
comp_a = audit_service  # latency ↑ (d=1.06), score=33.65
comp_b = audit_queue    # queue_in_flight ↑ (d=0.67), score=16.81

causality_score = 0

# Signal 1: Structural
# audit_service → audit_queue (service depends on queue)
causality_score -= 4  # Queue is root cause

# Signal 2: Symptom Semantics  
# audit_queue: queue_in_flight ↑ (PRIMARY)
# audit_service: latency ↑ (SECONDARY)
causality_score -= 3  # Queue is root cause

# Signal 3: Temporal (if detectable)
# audit_queue broke slightly before audit_service
causality_score -= 2  # Queue is root cause

# Total: -9 (strong evidence audit_queue is root cause)

# Apply victim penalty to audit_service
audit_service.score *= 0.3  # 33.65 → 10.10
audit_service.victim_of = "audit_queue"

# Result: audit_queue (16.81) now ranks ABOVE audit_service (10.10) ✓
```

## Implementation Plan

### Phase 1: Structural Causality (Quick Win)
**File**: `self_health_analyzer.py` or new `causality_analyzer.py`

```python
def apply_structural_causality_penalties(candidates, topology):
    """Apply victim penalty based on dependency structure."""
    for candidate in candidates:
        if not candidate.has_symptoms:
            continue
            
        # Check if any of its dependencies also have symptoms
        for dep_id in topology.predecessors(candidate.id):
            dep = find_candidate(candidates, dep_id)
            if dep and dep.has_symptoms:
                # Check if dependency has primary symptoms
                if has_primary_symptoms(dep):
                    # This candidate is likely a victim
                    victim_penalty = 0.5  # Reduce score by 50%
                    candidate.score *= victim_penalty
                    candidate.add_explanation(
                        f"Victim penalty: Depends on {dep_id} which has primary symptoms"
                    )
                    break
```

### Phase 2: Symptom Semantics
**File**: `self_health_analyzer.py`

Add symptom categorization:
```python
PRIMARY_SYMPTOM_INDICATORS = {
    'cpu_usage', 'memory_usage', 'thread_pool_active',
    'queue_depth', 'queue_in_flight', 'queue_utilization',
    'garbage_collection_time', 'disk_io_wait'
}

SECONDARY_SYMPTOM_INDICATORS = {
    'avg_latency', 'internal_error_rate', 'timeout_rate'
}
```

### Phase 3: Temporal Analysis (Future)
Requires time-series changepoint detection per component.

### Phase 4: Pattern Library (Future)
Encode known fault patterns with causality rules.

===

Summary                                                                                                                                                                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                                                                                                                                                                            
  I've created a comprehensive proposal for solving the root cause vs victim problem. Here are the key points:                                                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                                                                                                                                            
  Problem Root Cause                                                                                                                                                                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                                                                                                                                                            
  The RCA ranks audit_service #1 (victim) above audit_queue #3 (root cause) because:                                                                                                                                                                                                                                                                                                                        
  1. Both show symptoms                                                                                                                                                                                                                                                                                                                                                                                     
  2. audit_service has stronger symptom magnitude (d=1.06 vs 0.67)                                                                                                                                                                                                                                                                                                                                          
  3. No causality inference - treats all symptoms equally                                                                                                                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                                                                                                                                                                            
  Proposed Solution: Multi-Signal Causality Analysis                                                                                                                                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                                                                                                                                                            
  Three complementary signals (ranked by reliability):                                                                                                                                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                                                                                                                                                            
  1. Structural Causality ⭐⭐⭐ (Highest)                                                                                                                                                                                                                                                                                                                                                                  
    - Use topology: audit_service → audit_queue                                                                                                                                                                                                                                                                                                                                                             
    - Service depends on queue → queue is root cause                                                                                                                                                                                                                                                                                                                                                        
    - Easiest to implement, highest reliability                                                                                                                                                                                                                                                                                                                                                             
  2. Symptom Semantics ⭐⭐⭐ (High)                                                                                                                                                                                                                                                                                                                                                                        
    - Primary symptoms (queue_in_flight, CPU, memory) = internal issues                                                                                                                                                                                                                                                                                                                                     
    - Secondary symptoms (latency, errors) = performance effects                                                                                                                                                                                                                                                                                                                                            
    - Primary + dependency → root cause                                                                                                                                                                                                                                                                                                                                                                     
  3. Fault Pattern Matching ⭐⭐ (Medium)                                                                                                                                                                                                                                                                                                                                                                   
    - Known patterns: queue_in_flight ↑ + consumer latency ↑ = queue fault                                                                                                                                                                                                                                                                                                                                  
    - High confidence when pattern matches                                                                                                                                                                                                                                                                                                                                                                  
                                                                                                                                                                                                                                                                                                                                                                                                            
  Implementation (Phase 1 - Quick Win)                                                                                                                                                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                                                                                                                                                            
  New file: causality_analyzer.py with:                                                                                                                                                                                                                                                                                                                                                                     
  - CausalityAnalyzer class                                                                                                                                                                                                                                                                                                                                                                                 
  - apply_victim_penalties() function                                                                                                                                                                                                                                                                                                                                                                       
  - Applies 30-70% penalty to victims based on confidence                                                                                                                                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                                                                                                                                                                            
  Expected result for audit_queue:                                                                                                                                                                                                                                                                                                                                                                          
  Before: audit_service (33.65) > audit_queue (16.81)                                                                                                                                                                                                                                                                                                                                                       
  After:  audit_queue (16.81) > audit_service (10.10) ✓                                                                                                                                                                                                                                                                                                                                                     
                                                                                                                                                                                                                                                                                                                                                                                                            
  Why This Works                                                                                                                                                                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                                                                                                                                            
  For queue_consumer_slowdown:                                                                                                                                                                                                                                                                                                                                                                              
  - Structural: audit_service → audit_queue (-4 points)                                                                                                                                                                                                                                                                                                                                                     
  - Symptoms: queue_in_flight (primary) vs latency (secondary) (-3 points)                                                                                                                                                                                                                                                                                                                                  
  - Pattern: Matches queue consumer slowdown pattern (-4 points)                                                                                                                                                                                                                                                                                                                                            
  - Total: -11 points (high confidence queue is root cause)                                                                                                                                                                                                                                                                                                                                                 
  - Apply 70% penalty to audit_service → drops from #1 to #4                                                                                                                                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                                                                                                                                                            
  Would you like me to implement Phase 1 (structural causality + symptom semantics)?    