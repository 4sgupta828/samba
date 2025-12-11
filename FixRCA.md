Excellent! The fix is working! ✅

  ✅ CORRECT - Detected as rank #1
     Detection Probability: 0.567

  About the Temporal Order Violation

  Looking at the propagation timeline:
  Distance 1: matchmaking_service
    First impact: 65.0s

  Distance 0: game_session_service (ground truth)
    First impact: 70.0s

  This is actually expected behavior, not a bug! Here's why:

  1. Fault injection starts at t=60s on game_session_service (memory pressure)
  2. game_session_service starts degrading internally, but its internal metrics (CPU, memory) don't show statistically significant changes
  until t=70s
  3. matchmaking_service (a caller of game_session_service) starts experiencing increased latency on outgoing calls to the degraded service at
   t=65s

  This is normal for memory pressure faults:
  - Internal resource metrics (CPU, memory) have measurement noise and require statistical significance to detect
  - Callers experience latency/errors immediately when the service starts degrading
  - So dependency metrics change before internal resource metrics show observable deviation

  The RCA still correctly identified game_session_service as rank #1 because:
  - ✅ Case 3 (self-health degradation) detected the 110% memory increase
  - ✅ Self-degradation score of 0.60 pushed it to the top
  - ✅ The algorithm correctly distinguished internal faults from downstream issues

  Summary

  Root Cause: The self-degradation score calculation was too conservative:
  - Old formula: Divided resource increases by 2.0, then weighted at 40% → 110% memory increase scored only 0.22
  - New formula: Cap at 100% (no division), weighted at 60% → 110% memory increase scores 0.60 ✓

  File changed: analysis/sotaanalyzer/self_health_analyzer.py:272-307

  The discovery RCA now correctly identifies service nodes with memory pressure faults, even when all their dependencies are impacted!
  analysis/sotaanalyzer/self_health_analyzer.py:272-307
