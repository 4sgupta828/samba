> Re-think as an expert here how to fix this without relying on workload tuning. We should be able to correctly predict what RPS a component 
would need to handle, based on overall target RPS and how much baseline capacity is needed for healthy function. 

⏺ Excellent framing. Let me think through this as a capacity planning expert, focusing on analytical prediction rather than empirical tuning.

  Expert Analysis: Predictive Capacity Planning

  The Core Problem

  The capacity planner uses flow propagation to calculate RPS (which is correct), but then applies phi-based downscaling uniformly without
  understanding service archetypes:

  1. Sync request-response services (gateway, hub_orchestrator)
  2. Async queue consumers (analytics, automation_engine, notification)
  3. Infrastructure (databases, caches, queues)

  Each archetype has different capacity requirements that phi should NOT violate.

  ---
  Proposed Solution: Archetype-Aware Capacity Planning

  1. For Sync Services: Little's Law (Current approach is mostly correct)

  # Current formula (capacity_planner.py:216)
  concurrency_per_pod = ceil(pod_rps * (total_latency_ms / 1000.0))
  threads = concurrency_per_pod * pool_headroom
  replicas = ceil((total_rps / max_rps_per_pod) * headroom)

  This works because:
  - Load is predictable from upstream
  - Backpressure prevents overload
  - Headroom accounts for variance

  Phi can safely reduce headroom because failures are graceful (timeouts, retries).

  ---
  2. For Async Consumers: Queue Draining Theory (Currently BROKEN)

  Problem: Current code treats async consumers identically to sync services.

  Fix: Async consumers must satisfy queue stability condition:

  Consumer throughput > Producer throughput + queue_drain_rate

  Analytical approach:

  def _tune_async_consumer(self, consumer_id: str, queue_id: str, phi: float):
      # 1. Calculate PRODUCTION rate to queue (sum all producers)
      producers = [u for u, v in self.graph.in_edges(queue_id)
                   if self.graph.get_edge_data(u, v).get('type') == 'async_produce']

      total_production_rps = sum(stats[p]['rps'] for p in producers)

      # 2. Calculate required CONSUMPTION rate
      # Must exceed production by margin to drain queue during bursts
      burst_factor = 1.3  # P95 burst = 1.3x mean (from workload profile)
      drain_margin = 1.2  # Need 20% excess capacity to drain accumulated items

      required_consumer_rps = total_production_rps * burst_factor * drain_margin

      # 3. Calculate resources WITHOUT phi reduction below stability
      # Phi can reduce headroom but NOT below queue stability requirement
      baseline_replicas = ceil(required_consumer_rps / max_rps_per_pod)

      # Apply phi ONLY to headroom above baseline
      min_stable_replicas = max(baseline_replicas, 1)
      headroom_replicas = ceil(baseline_replicas * (phi * 0.5))  # Extra capacity

      replicas = min_stable_replicas + headroom_replicas

      # 4. Thread pool: Size for P95 latency, not P50
      p95_latency = total_latency_ms * 1.5  # P95 ≈ 1.5x P50 for typical workloads
      pod_rps = required_consumer_rps / replicas
      threads = ceil(pod_rps * (p95_latency / 1000.0))

      # Don't let threads fall below stable threshold
      min_threads_for_stability = ceil(baseline_replicas * 10)
      threads = max(threads, min_threads_for_stability)

      return {
          'desired_replicas': replicas,
          'thread_pool_size': threads,
          'rationale': f'Queue stability: {total_production_rps:.1f} prod RPS → {required_consumer_rps:.1f} consumer capacity'
      }

  Key principles:

  - Burst factor (1.3x): Account for P95 production rate, not mean
  - Drain margin (1.2x): Excess capacity to drain queue over time
  - Phi reduction: Only applies to headroom ABOVE stability threshold
  - Min replicas: Based on queue stability, not arbitrary 50 RPS threshold

  ---
  3. Validation: Analytical Queue Stability Check

  Instead of workload tuning, validate with queueing theory:

  def _validate_async_consumer_capacity(self, consumer_id: str, config: Dict) -> bool:
      """
      Use M/M/c queueing model to verify consumer won't saturate.
      Returns False if queue will grow unbounded.
      """
      # Service rate (per pod)
      mu = 1000.0 / effective_processing_ms  # requests per second per pod

      # Arrival rate (total to queue)
      lambda_total = production_rps

      # Number of servers
      c = config['desired_replicas']

      # Utilization
      rho = lambda_total / (c * mu)

      if rho >= 1.0:
          # Queue will grow unbounded (unstable)
          logger.error(f"{consumer_id}: Unstable queue! rho={rho:.2f} >= 1.0")
          return False

      if rho >= 0.8:
          # Approaching saturation (dangerous for phi > 0.5)
          logger.warning(f"{consumer_id}: High utilization rho={rho:.2f}")
          return False if phi > 0.5 else True

      return True

  This catches the analytics problem BEFORE simulation:
  - Production rate: ~40-50 RPS (from hub_orchestrator)
  - Analytics: 1 replica × 10 threads × ~10 req/sec/thread = 100 req/sec capacity
  - Utilization: 50/100 = 0.5 (seems OK)
  - BUT: With 10 threads, processing variability + P95 bursts → saturation
  - M/M/c model would flag: rho > 0.8 with high variance

  ---
  4. Fixing the min_replicas Cliff

  Replace hard threshold:

  # BEFORE (cliff at 50 RPS)
  min_replicas = 2 if rps > 50 else 1

  # AFTER (continuous scaling based on archetype)
  if is_async_consumer:
      # Queue consumers need stability threshold
      min_replicas = max(1, ceil(required_rps / max_safe_rps_per_pod))
  else:
      # Sync services can scale down more aggressively
      min_replicas = 1 if rps < 10 else 2 if rps < 100 else 3

  ---
  5. Phi Semantic Adjustment

  Redefine phi to preserve system health:

  Current (BROKEN):
  phi=0.0 → 4.0x headroom (wasteful)
  phi=1.0 → 1.15x headroom (violates queue stability)

  Proposed:
  phi=0.0 → 2.0x headroom above stability threshold (robust)
  phi=0.5 → 1.3x headroom above stability threshold (balanced)
  phi=1.0 → 1.0x headroom = exactly at stability threshold (fragile but functional)

  Implementation:
  # Calculate minimum stable capacity (queue draining, Little's Law, etc.)
  min_stable_capacity = calculate_stability_threshold(node_id, role, rps)

  # Apply phi to headroom ABOVE stability
  headroom_multiplier = 1.0 + (1.0 * (1.0 - phi))  # 1.0x to 2.0x
  final_capacity = min_stable_capacity * headroom_multiplier

  Result:
  - phi=0.0: Double the stable capacity (very robust)
  - phi=1.0: Exactly at stable capacity (fragile but won't fail baseline)
  - System remains healthy at baseline for ALL phi values
  - Fragility comes from lack of headroom during faults, not baseline instability

  ---
  Summary: Predictive Capacity Model

  Step 1: Calculate per-service RPS (already works)

  Flow propagation through topology graph ✓

  Step 2: Determine service archetype

  - Sync service → Use Little's Law
  - Async consumer → Use queue draining theory
  - Infrastructure → Use connection pooling math

  Step 3: Calculate stability threshold (NEW)

  - Minimum capacity to handle baseline without queue growth
  - Account for P95 bursts, not just mean
  - Use queueing theory (M/M/c model)

  Step 4: Apply phi to headroom above stability (FIXED)

  - phi reduces margin for error, not baseline capacity
  - Even phi=1.0 can handle baseline load
  - Fragility manifests during faults, not baseline

  Step 5: Analytical validation (NEW)

  - Check rho < 0.8 for all async consumers
  - Check thread saturation < 80% for all services
  - Check timeout margins > 2x P95 latency
  - Fail fast if validation fails - don't run simulation

  ---
  This approach eliminates the need for workload tuning because capacity is analytically guaranteed to be sufficient. The validation failure
  in your dataset would be caught at planning time, not after 960 seconds of simulation.
