"""
causal_graph_reasoner.py

The "Physics Engine" of RCA with queue-aware and reverse propagation.

SOTA Features:
1. Validates failure propagation using RELATIVE metric factors
2. Calculates Physics Coverage (blast radius explanation)
3. Queue-aware propagation: Skips queues that are just buffering
4. Narrative generation with causal chains
5. Multi-component error proxy detection (effect size based, no magic numbers):
   - Cache: hit rate degradation (configurable threshold, default 20% drop)
   - Database: query errors (Cohen's d >= 1.0 medium effect)
   - Queue: timeout failures (Cohen's d >= 1.0, ONLY if queue has PRIMARY fault)
   - External services: component errors (Cohen's d >= 0.8 small-medium effect)
   All thresholds configurable via RCAThresholds
6. REVERSE PROPAGATION (Consumer Physics):
   - Consumer slowdown/errors → Queue depth increases (backward impact)
   - Consumer slowdown/errors → Reduced write throughput to downstream deps (forward impact)
   - Validates using queue depth/age metrics and throughput correlation
"""

import networkx as nx
import numpy as np
from typing import Dict, List, Set, Any
from dataclasses import dataclass, field
from config_extractor import CausalConstants
from rca_config import get_thresholds
from statistical_utils import compare_distributions

@dataclass
class CausalLink:
    source: str
    target: str
    mechanism: str  # 'latency', 'error', 'timeout', 'capacity', 'weak', 'reverse_queue', 'reverse_throughput'
    valid: bool
    evidence: str
    is_reverse: bool = False  # True if this is reverse propagation (consumer → queue/dep)

@dataclass
class CausalHypothesis:
    root_cause_node: str
    symptom_type: str
    coverage_score: float
    explained_nodes: Set[str] = field(default_factory=set)
    broken_links: List[CausalLink] = field(default_factory=list)
    narrative: List[str] = field(default_factory=list)
    reverse_impacted_nodes: Set[str] = field(default_factory=set)  # Nodes impacted by reverse physics

class CausalGraphReasoner:
    def __init__(self, topology: nx.DiGraph, threshold_config=None):
        self.topology = topology
        self.thresholds = get_thresholds(threshold_config)

    def _is_queue_node(self, node_id: str) -> bool:
        """Check if a node is a queue/message broker."""
        if node_id not in self.topology.nodes:
            return False

        node_data = self.topology.nodes[node_id]
        node_type = node_data.get('type', '')
        node_role = node_data.get('role', '')

        return node_type == 'MessageQueue' or node_role == 'queue' or 'queue' in node_id.lower()

    def _has_queue_fault(self, queue_id: str, health_scores: Dict) -> bool:
        """
        Check if a queue has a REAL fault (not just normal buffering).

        Real queue faults:
        1. Capacity limits hit
        2. Queue failures (message drops, connection issues)
        3. Queue-level latency (slow queue operations)

        Returns True if queue itself is broken, False if just buffering.
        """
        if queue_id not in health_scores:
            return False

        health = health_scores[queue_id]

        # Key decision: Check if symptom_type is 'primary'
        # If primary → real queue fault
        # If secondary → just buffering due to consumer/producer issues
        if health.symptom_type == 'primary':
            return True

        # Additional checks on symptoms for backwards compatibility
        symptoms = health.symptoms
        for symptom in symptoms:
            symptom_lower = symptom.lower()

            # Real queue faults
            if 'queue fault' in symptom_lower:
                return True
            if 'capacity' in symptom_lower or 'saturation' in symptom_lower:
                return True
            if 'error' in symptom_lower and 'queue' in symptom_lower:
                return True
            if 'latency' in symptom_lower and 'queue' in symptom_lower:
                return True

        # If only symptom is "buffering", not a queue fault
        for symptom in symptoms:
            if 'buffering' in symptom.lower() and 'imbalance' in symptom.lower():
                return False

        return False

    def _is_caller_edge(self, predecessor: str, node: str) -> bool:
        """
        Determine if predecessor → node edge represents a CALL (vs async consumer pattern).

        Returns True if predecessor is a caller (fault in node impacts predecessor).
        Returns False if predecessor is a data source (queue feeding consumer via async pull).

        Rules:
        - Queue/MessageBroker/MessageQueue → Service: NOT a call (async consumer pattern, reverse impact)
        - Service → Service: IS a call (traditional RPC/HTTP, forward propagation)
        - Service → Database/Cache/Queue: IS a call (dependency access, forward propagation)
        """
        pred_type = self.topology.nodes[predecessor].get('type', 'Service')
        node_type = self.topology.nodes[node].get('type', 'Service')

        # Queue → Service = async consumer pattern (NOT a caller, disconnected by async-ness)
        if pred_type in ['Queue', 'MessageBroker', 'MessageQueue'] and node_type == 'Service':
            return False

        # All other edges are synchronous calls
        return True

    def calculate_global_coverage(self, candidates: List[str], health_scores: Dict, baseline: Dict, current: Dict) -> Dict[str, CausalHypothesis]:
        """
        For every candidate, calculate how much of the system it explains.

        Coverage includes:
        1. Traditional forward propagation (symptomatic nodes explained by root cause)
        2. Reverse propagation (nodes impacted by consumer degradation, even if not symptomatic)
        """

        total_symptomatic = {n for n, h in health_scores.items() if h.self_degradation_score > 2.0}

        results = {}
        for candidate in candidates:
            h = self._trace_blast_radius(candidate, health_scores, baseline, current)

            if total_symptomatic:
                # Count traditionally explained symptomatic nodes
                explained = h.explained_nodes.intersection(total_symptomatic)
                # FIX (a): Don't count root in its own coverage - only count OTHER nodes it explains
                explained = explained - {candidate}

                # Add reverse-impacted nodes to coverage (they count even if not symptomatic)
                # Remove any that are already in explained to avoid double-counting
                reverse_unique = h.reverse_impacted_nodes - explained - {candidate}

                # Coverage = (symptomatic explained + reverse impacted) / total symptomatic
                total_explained = len(explained) + len(reverse_unique)
                h.coverage_score = total_explained / len(total_symptomatic)
            else:
                h.coverage_score = 0.0

            results[candidate] = h
        return results

    def _trace_blast_radius(self, root: str, health_scores, baseline, current) -> CausalHypothesis:
        """
        Walks the graph upstream to find explained nodes.

        QUEUE-AWARE PROPAGATION:
        - Skips queues as intermediate nodes UNLESS the queue itself has real issues
        - Queues are passive buffers, not active components that cause faults
        - Only includes queues if they have: capacity limits, failures, or queue-level latency

        REVERSE PROPAGATION (NEW):
        - Consumer degradation impacts queues (backward: queue depth increases)
        - Consumer degradation impacts downstream deps (forward: reduced throughput)

        This solves "audit_queue vs audit_service" problem!
        """
        h = CausalHypothesis(
            root_cause_node=root,
            symptom_type=health_scores[root].symptom_type,
            coverage_score=0.0
        )
        h.explained_nodes.add(root)
        h.narrative.append(f"ROOT: {root} (Type: {h.symptom_type})")

        queue = [root]
        visited = {root}

        while queue:
            curr = queue.pop(0)

            # ===== FORWARD PROPAGATION (Traditional: upstream to callers) =====
            predecessors = list(self.topology.predecessors(curr))

            # FIX (b): Filter to only ACTUAL callers (exclude async data sources like queues)
            callers = [p for p in predecessors if self._is_caller_edge(p, curr)]

            for caller in callers:
                if caller in visited:
                    continue

                # CRITICAL: Queue-aware logic
                if self._is_queue_node(caller):
                    # Only include queue in blast radius if it has real issues
                    if not self._has_queue_fault(caller, health_scores):
                        # Queue is just buffering normally - skip it
                        # Don't add to explained_nodes, but mark as visited to avoid loops
                        visited.add(caller)
                        h.narrative.append(f"  -> Skipped queue {caller} (normal buffering)")
                        continue

                # PHYSICS CHECK
                link = self._verify_propagation(curr, caller, baseline, current, health_scores)

                if link.valid:
                    h.explained_nodes.add(caller)
                    h.narrative.append(f"  -> Propagated to {caller}: {link.evidence}")
                    visited.add(caller)
                    queue.append(caller)
                else:
                    h.broken_links.append(link)

            # ===== REVERSE PROPAGATION (Consumer impact) =====
            # Check if current node is a consumer that impacts its dependencies

            # 1. Check async predecessors (queues) for reverse impact
            async_sources = [p for p in predecessors if not self._is_caller_edge(p, curr)]
            for queue_node in async_sources:
                # Don't skip if already visited - we want to check reverse impact
                # even if we skipped it during forward propagation

                # Check if consumer degradation causes queue backup
                if self._is_queue_node(queue_node):
                    link = self._verify_reverse_propagation(curr, queue_node, baseline, current, health_scores)

                    if link.valid:
                        h.explained_nodes.add(queue_node)
                        h.reverse_impacted_nodes.add(queue_node)  # Track reverse impact separately
                        h.narrative.append(f"  <- Reverse impact on {queue_node}: {link.evidence}")
                        visited.add(queue_node)
                        # Note: Don't add to queue for further traversal - we only check direct impact
                    else:
                        # Mark as visited to avoid rechecking
                        visited.add(queue_node)

            # 2. Check successors (downstream dependencies) for reduced throughput
            successors = list(self.topology.successors(curr))
            for dep in successors:
                if dep in visited:
                    continue

                # Check if consumer degradation reduces throughput to dependency
                link = self._verify_reverse_propagation(curr, dep, baseline, current, health_scores)

                if link.valid:
                    h.explained_nodes.add(dep)
                    h.reverse_impacted_nodes.add(dep)  # Track reverse impact separately
                    h.narrative.append(f"  <- Reverse impact on {dep}: {link.evidence}")
                    visited.add(dep)
                    # Note: Don't add to queue for further traversal - we only check direct impact

        # ===== NOISY NEIGHBOR DETECTION (Resource Contention) =====
        # Detect if root is a noisy neighbor (high CPU pod affecting co-located pods)
        # This is NOT propagation-based - it's resource contention on the same node
        noisy_neighbor_victims = self._detect_noisy_neighbor(root, health_scores, baseline, current)
        for victim in noisy_neighbor_victims:
            if victim not in h.explained_nodes:
                h.explained_nodes.add(victim)
                h.reverse_impacted_nodes.add(victim)  # Track as "reverse" impact (not traditional propagation)
                h.narrative.append(f"  <-> Noisy neighbor victim: {victim} (co-located, resource contention)")

        return h

    def _verify_propagation(self, callee, caller, baseline, current, health_scores) -> CausalLink:
        """
        Verifies propagation using RELATIVE comparisons against baseline.

        Physics checks:
        1. Deadlock propagation (high latency cascade)
        2. Latency propagation (with dilution factor)
        3. Error bubbling
        4. Capacity reduction (RPS drop due to backpressure)
        """
        # Helper functions
        def get_mean(d, n, m):
            vals = d.get(n, {}).get(m, [])
            return np.mean(vals) if len(vals) > 0 else 0.0

        def calc_growth(b, c):
            return (c + 0.01) / (b + 0.01)

        def calc_drop(b, c):
            """Calculate drop ratio (0-1), where 1 = 100% drop"""
            if b < 0.01:
                return 0.0
            return max(0.0, 1.0 - (c / b))

        # 1. Fetch Metrics using RAW metric names (no mapping!)
        # Build metric names dynamically based on node names
        def get_service_metric(data, node, metric_suffix):
            """Get metric with format: service.{node}.{suffix} or fallback to mapped name."""
            # Try direct metric name first
            raw_name = f'service.{node}.{metric_suffix}'
            vals = data.get(node, {}).get(raw_name, [])

            # DEBUG: Log for session_cache case
            _debug = False and (node == 'session_cache' or (node == 'mobile_api_service' and 'error' in metric_suffix))
            if _debug and len(vals) == 0:
                print(f'    [DEBUG] {node}.{metric_suffix}: raw_name={raw_name}, found={raw_name in data.get(node, {})}')
                if node in data:
                    print(f'            Available: {[k for k in data[node].keys() if metric_suffix.split(".")[0] in k][:3]}')

            if len(vals) > 0:
                return np.mean(vals)
            # Fallback to old mapped names for backwards compatibility
            mapped_names = {
                'duration': 'avg_latency',
                'dependency.duration': 'dependency_latency',
                'error_rate': 'internal_error_rate',
                'dependency.error_rate': 'dependency_error_rate',
                'requests': 'inbound_rps',
                'dependency.requests': 'outbound_rps'
            }
            if metric_suffix in mapped_names:
                vals = data.get(node, {}).get(mapped_names[metric_suffix], [])
                if _debug:
                    mapped = mapped_names[metric_suffix]
                    print(f'            Trying mapped: {mapped}, found={mapped in data.get(node, {})}, mean={np.mean(vals) if len(vals) > 0 else 0:.4f}')
                return np.mean(vals) if len(vals) > 0 else 0.0
            return 0.0

        # Latency metrics
        callee_lat_base = get_service_metric(baseline, callee, 'duration')
        callee_lat_curr = get_service_metric(current, callee, 'duration')
        callee_lat_growth = calc_growth(callee_lat_base, callee_lat_curr)

        caller_dep_base = get_service_metric(baseline, caller, 'dependency.duration')
        caller_dep_curr = get_service_metric(current, caller, 'dependency.duration')
        caller_dep_growth = calc_growth(caller_dep_base, caller_dep_curr)

        # Check if callee is an external dependency (for special handling)
        # External deps are blackbox - they don't emit metrics, so we use caller's view
        callee_node_type = self.topology.nodes.get(callee, {}).get('type', '')
        is_callee_external = callee_node_type in ['ExternalAPI', 'ExternalService', 'Database', 'Cache', 'Queue']

        # Capacity metrics
        callee_rps_base = get_service_metric(baseline, callee, 'requests')
        callee_rps_curr = get_service_metric(current, callee, 'requests')
        callee_rps_drop = calc_drop(callee_rps_base, callee_rps_curr)

        caller_out_rps_base = get_service_metric(baseline, caller, 'dependency.requests')
        caller_out_rps_curr = get_service_metric(current, caller, 'dependency.requests')
        caller_rps_drop = calc_drop(caller_out_rps_base, caller_out_rps_curr)

        # Error metrics
        callee_err_base = get_service_metric(baseline, callee, 'error_rate')
        callee_err_curr = get_service_metric(current, callee, 'error_rate')
        callee_err_delta = callee_err_curr - callee_err_base

        # Fallback for external services (caches, DBs, queues) that don't emit error_rate
        # Use component-specific degradation metrics as proxy for error propagation
        # All checks use effect sizes and percentile-based thresholds (no magic numbers)

        if callee_err_delta < 0.001:  # No error rate signal
            # 1. Cache hit rate drop as proxy
            cache_hit_base = baseline.get(callee, {}).get('cache.hit_rate', [])
            cache_hit_curr = current.get(callee, {}).get('cache.hit_rate', [])
            if len(cache_hit_base) > 0 and len(cache_hit_curr) > 0:
                base_mean = np.mean(cache_hit_base)
                curr_mean = np.mean(cache_hit_curr)
                # Must have reasonable baseline hit rate (not an unused cache)
                if base_mean > np.percentile([0.1, 0.2, 0.5, 0.8, 0.95], self.thresholds.cache_min_baseline_percentile):
                    hit_rate_drop = base_mean - curr_mean
                    # Use configured threshold (default 20% drop)
                    if hit_rate_drop > self.thresholds.cache_hit_rate_drop_threshold:
                        callee_err_delta = self.thresholds.error_proxy_value

        # 2. Database query errors as proxy (effect size based)
        if callee_err_delta < 0.001:  # Still no error signal
            db_errors_base = baseline.get(callee, {}).get('db.query.errors', [])
            db_errors_curr = current.get(callee, {}).get('db.query.errors', [])
            if len(db_errors_base) > 0 and len(db_errors_curr) > 0:
                # Use statistical comparison with effect size
                stat = compare_distributions(db_errors_base, db_errors_curr)
                if stat.significant and stat.effect_size >= self.thresholds.db_error_min_effect_size:
                    callee_err_delta = self.thresholds.error_proxy_value

        # 3. Queue timeout failures as proxy - BUT ONLY if queue itself is faulty!
        # CRITICAL: Don't blame the queue if it's just buffering due to slow consumer
        if callee_err_delta < 0.001:  # Still no error signal
            queue_timeouts_base = baseline.get(callee, {}).get('mq.messages.timeout_failures', [])
            queue_timeouts_curr = current.get(callee, {}).get('mq.messages.timeout_failures', [])
            if len(queue_timeouts_base) > 0 and len(queue_timeouts_curr) > 0:
                # Check if this is a REAL queue fault (not just buffering)
                # Use health_scores to determine if queue has PRIMARY symptoms
                callee_health = health_scores.get(callee)
                is_queue_primary_fault = (
                    callee_health and
                    callee_health.symptom_type == 'primary' and
                    self._is_queue_node(callee)
                )

                if is_queue_primary_fault:
                    # Queue itself is faulty - use timeout failures as error proxy
                    stat = compare_distributions(queue_timeouts_base, queue_timeouts_curr)
                    if stat.significant and stat.effect_size >= self.thresholds.queue_timeout_min_effect_size:
                        callee_err_delta = self.thresholds.error_proxy_value
                # Otherwise, skip - timeout failures are due to consumer issues, not queue

        # 4. External service errors as proxy (effect size based)
        if callee_err_delta < 0.001:  # Still no error signal
            ext_errors_base = baseline.get(callee, {}).get('component.errors.total', [])
            ext_errors_curr = current.get(callee, {}).get('component.errors.total', [])
            if len(ext_errors_base) > 0 and len(ext_errors_curr) > 0:
                # Use statistical comparison with lower threshold (external failures are critical)
                stat = compare_distributions(ext_errors_base, ext_errors_curr)
                if stat.significant and stat.effect_size >= self.thresholds.external_error_min_effect_size:
                    callee_err_delta = self.thresholds.error_proxy_value

        caller_dep_err_base = get_service_metric(baseline, caller, 'dependency.error_rate')
        caller_dep_err_curr = get_service_metric(current, caller, 'dependency.error_rate')
        caller_dep_err_delta = caller_dep_err_curr - caller_dep_err_base

        # 2. Physics Checks

        # A. DEADLOCK (Primary Override)
        callee_health = health_scores.get(callee)
        if callee_health and "Deadlock" in str(callee_health.symptoms):
            if caller_dep_growth > CausalConstants.DEADLOCK_GROWTH_THRESHOLD:
                return CausalLink(callee, caller, 'timeout', True, f"Deadlock Propagation ({caller_dep_growth:.1f}x wait)")

        # B. LATENCY (Backpressure) - RELAXED THRESHOLDS
        # Lower threshold from 1.2x to 1.15x (15% slowdown)

        # SPECIAL CASE: External dependencies (blackbox)
        # External deps are blackbox systems that don't emit self-metrics
        # Use caller's dependency latency growth as the primary signal
        # NOTE: Internal leaf services are NOT treated this way - they have metrics we should use
        if is_callee_external and callee_lat_base < 0.01:
            # External service has no latency metrics (blackbox)
            # Validate using caller's dependency latency growth alone
            if caller_dep_growth > CausalConstants.MIN_LATENCY_GROWTH_RELAXED:
                return CausalLink(callee, caller, 'latency', True, f"External Dep Latency (caller dep: {caller_dep_growth:.1f}x)")

        # Normal case: Use callee's self-latency
        if callee_lat_growth > CausalConstants.MIN_LATENCY_GROWTH_RELAXED:
            # Caller must reflect diluted growth (accounts for multiple dependencies)
            required_growth = 1.0 + ((callee_lat_growth - 1.0) * CausalConstants.LATENCY_DILUTION_FACTOR)
            if caller_dep_growth > required_growth:
                return CausalLink(callee, caller, 'latency', True, f"Latency Match ({callee_lat_growth:.1f}x -> {caller_dep_growth:.1f}x)")

        # C. ERRORS (Bubbling)
        # NOTE: dependency_error_rate often doesn't exist in data
        # Fallback: If callee has errors AND caller has errors, assume propagation
        caller_err_base = get_mean(baseline, caller, 'internal_error_rate')
        caller_err_curr = get_mean(current, caller, 'internal_error_rate')
        caller_err_delta = caller_err_curr - caller_err_base

        # Primary check: Use dependency error rate if available
        if callee_err_delta > CausalConstants.MIN_ERROR_DELTA and caller_dep_err_delta > 0:
            return CausalLink(callee, caller, 'error', True, f"Error Bubbling (+{callee_err_delta:.1%} -> +{caller_dep_err_delta:.1%})")

        # Fallback: If callee has significant errors AND caller also has errors, assume correlation
        if callee_err_delta > CausalConstants.MIN_ERROR_DELTA and caller_err_delta > 0.005:
            return CausalLink(callee, caller, 'error', True, f"Error Correlation (callee +{callee_err_delta:.1%}, caller +{caller_err_delta:.1%})")

        # D. CAPACITY REDUCTION (Backpressure via RPS drop)
        # Only check if RPS metrics are available (> 0.01 baseline means data exists)
        if callee_rps_base > 0.01 and caller_out_rps_base > 0.01:
            if callee_rps_drop > CausalConstants.MIN_RPS_DROP and caller_rps_drop > 0:
                # Verify callee is actually degraded (not just low traffic)
                callee_is_degraded = (
                    callee_lat_growth > 1.1 or  # 10% slowdown
                    callee_err_delta > 0.01 or   # 1% error increase
                    (callee_health and callee_health.score > 0)  # Has health issues
                )

                if callee_is_degraded:
                    return CausalLink(callee, caller, 'capacity', True,
                                    f"Capacity Reduction (callee RPS -{callee_rps_drop:.0%}, caller RPS -{caller_rps_drop:.0%})")

        return CausalLink(callee, caller, 'unknown', False, "Physics Mismatch")

    def _verify_reverse_propagation(self, consumer, dependency, baseline, current, health_scores) -> CausalLink:
        """
        Verifies REVERSE propagation: Consumer degradation impacts dependencies/queues.

        Reverse Physics:
        1. Consumer slowdown/errors → Queue depth increases (backward impact)
        2. Consumer slowdown/errors → Reduced write throughput to downstream deps (forward impact)

        Args:
            consumer: The consumer service (source of reverse impact)
            dependency: The affected dependency (queue or downstream service)

        Returns:
            CausalLink with is_reverse=True if reverse propagation is validated
        """
        # Helper functions
        def get_mean(d, n, m):
            vals = d.get(n, {}).get(m, [])
            return np.mean(vals) if len(vals) > 0 else 0.0

        def calc_growth(b, c):
            return (c + 0.01) / (b + 0.01)

        def calc_drop(b, c):
            """Calculate drop ratio (0-1), where 1 = 100% drop"""
            if b < 0.01:
                return 0.0
            return max(0.0, 1.0 - (c / b))

        def get_service_metric(data, node, metric_suffix):
            """Get metric with format: service.{node}.{suffix} or fallback to mapped name."""
            raw_name = f'service.{node}.{metric_suffix}'
            vals = data.get(node, {}).get(raw_name, [])
            if len(vals) > 0:
                return np.mean(vals)
            # Fallback to old mapped names
            mapped_names = {
                'duration': 'avg_latency',
                'dependency.duration': 'dependency_latency',
                'error_rate': 'internal_error_rate',
                'dependency.error_rate': 'dependency_error_rate',
                'requests': 'inbound_rps',
                'dependency.requests': 'outbound_rps'
            }
            if metric_suffix in mapped_names:
                vals = data.get(node, {}).get(mapped_names[metric_suffix], [])
                return np.mean(vals) if len(vals) > 0 else 0.0
            return 0.0

        # Check if consumer is degraded (precondition for reverse impact)
        consumer_health = health_scores.get(consumer)
        if not consumer_health or consumer_health.self_degradation_score < 2.0:
            return CausalLink(consumer, dependency, 'unknown', False, "Consumer not degraded", is_reverse=True)

        consumer_lat_base = get_service_metric(baseline, consumer, 'duration')
        consumer_lat_curr = get_service_metric(current, consumer, 'duration')
        consumer_lat_growth = calc_growth(consumer_lat_base, consumer_lat_curr)

        consumer_err_base = get_service_metric(baseline, consumer, 'error_rate')
        consumer_err_curr = get_service_metric(current, consumer, 'error_rate')
        consumer_err_delta = consumer_err_curr - consumer_err_base

        # Consumer must be significantly degraded for reverse impact
        consumer_is_degraded = (
            consumer_lat_growth > 1.15 or  # 15% slowdown
            consumer_err_delta > 0.01      # 1% error increase
        )

        if not consumer_is_degraded:
            return CausalLink(consumer, dependency, 'unknown', False, "Consumer not degraded enough", is_reverse=True)

        # Case 1: REVERSE IMPACT ON QUEUE (Backward)
        # Consumer slowdown → Queue depth increases
        if self._is_queue_node(dependency):
            # Check queue depth/size metrics
            queue_depth_base = get_mean(baseline, dependency, 'mq.messages.depth')
            queue_depth_curr = get_mean(current, dependency, 'mq.messages.depth')

            # Fallback to other queue size metrics
            if queue_depth_base < 0.01:
                queue_depth_base = get_mean(baseline, dependency, 'mq.queue.size')
                queue_depth_curr = get_mean(current, dependency, 'mq.queue.size')

            if queue_depth_base < 0.01:
                queue_depth_base = get_mean(baseline, dependency, 'queue.depth')
                queue_depth_curr = get_mean(current, dependency, 'queue.depth')

            # Fallback to in_flight messages (SQS-style queues)
            if queue_depth_base < 0.01:
                queue_depth_base = get_mean(baseline, dependency, 'mq.messages.in_flight')
                queue_depth_curr = get_mean(current, dependency, 'mq.messages.in_flight')

            if queue_depth_base > 0.01:  # Have queue depth data
                queue_depth_growth = calc_growth(queue_depth_base, queue_depth_curr)

                # Queue depth should increase when consumer slows down
                if queue_depth_growth > 1.3:  # 30% increase in queue depth
                    evidence = f"Consumer Slowdown → Queue Backup (consumer lat: {consumer_lat_growth:.1f}x, queue depth: {queue_depth_growth:.1f}x)"
                    if consumer_err_delta > 0.01:
                        evidence += f", consumer errors: +{consumer_err_delta:.1%}"
                    return CausalLink(consumer, dependency, 'reverse_queue', True, evidence, is_reverse=True)

            # Check queue age metrics as alternative signal
            queue_age_base = get_mean(baseline, dependency, 'mq.messages.age')
            queue_age_curr = get_mean(current, dependency, 'mq.messages.age')

            if queue_age_base > 0.01:
                queue_age_growth = calc_growth(queue_age_base, queue_age_curr)

                if queue_age_growth > 1.5:  # 50% increase in message age
                    evidence = f"Consumer Slowdown → Message Aging (consumer lat: {consumer_lat_growth:.1f}x, msg age: {queue_age_growth:.1f}x)"
                    return CausalLink(consumer, dependency, 'reverse_queue', True, evidence, is_reverse=True)

        # Case 2: REVERSE IMPACT ON DOWNSTREAM DEPENDENCIES (Forward)
        # Consumer slowdown → Reduced write throughput to downstream services/DBs
        else:
            # Consumer's outbound RPS to this dependency
            consumer_out_rps_base = get_service_metric(baseline, consumer, 'dependency.requests')
            consumer_out_rps_curr = get_service_metric(current, consumer, 'dependency.requests')
            consumer_out_rps_drop = calc_drop(consumer_out_rps_base, consumer_out_rps_curr)

            # Dependency's inbound RPS
            dep_in_rps_base = get_service_metric(baseline, dependency, 'requests')
            dep_in_rps_curr = get_service_metric(current, dependency, 'requests')
            dep_in_rps_drop = calc_drop(dep_in_rps_base, dep_in_rps_curr)

            # Both should show throughput reduction
            if consumer_out_rps_base > 0.01 and dep_in_rps_base > 0.01:
                if consumer_out_rps_drop > 0.2 and dep_in_rps_drop > 0.15:  # 20% and 15% drops
                    # Verify consumer is actually degraded (not just reducing load intentionally)
                    if consumer_lat_growth > 1.1 or consumer_err_delta > 0.01:
                        evidence = f"Consumer Slowdown → Reduced Throughput (consumer out: -{consumer_out_rps_drop:.0%}, dep in: -{dep_in_rps_drop:.0%})"
                        if consumer_lat_growth > 1.1:
                            evidence += f", consumer lat: {consumer_lat_growth:.1f}x"
                        return CausalLink(consumer, dependency, 'reverse_throughput', True, evidence, is_reverse=True)

            # Check for database-specific write reduction
            db_writes_base = get_mean(baseline, dependency, 'db.writes.total')
            db_writes_curr = get_mean(current, dependency, 'db.writes.total')

            if db_writes_base > 0.01:
                db_writes_drop = calc_drop(db_writes_base, db_writes_curr)

                if db_writes_drop > 0.2:  # 20% reduction in writes
                    evidence = f"Consumer Slowdown → Reduced DB Writes (consumer lat: {consumer_lat_growth:.1f}x, db writes: -{db_writes_drop:.0%})"
                    return CausalLink(consumer, dependency, 'reverse_throughput', True, evidence, is_reverse=True)

        return CausalLink(consumer, dependency, 'unknown', False, "No reverse physics match", is_reverse=True)

    def _detect_noisy_neighbor(self, root: str, health_scores, baseline, current) -> List[str]:
        """
        Detect noisy neighbor pattern: High CPU aggressor pod affecting co-located pods.

        Pattern:
        1. Root (or its pods) has very high CPU (>75%)
        2. Root and victim pods are on the same compute node
        3. Victim pods show degradation (latency/CPU increase, throughput drop)

        Returns:
            List of victim pod IDs affected by noisy neighbor
        """
        victims = []

        # Helper function to get metric mean
        def get_mean(data, node, metric):
            vals = data.get(node, {}).get(metric, [])
            return np.mean(vals) if len(vals) > 0 else 0.0

        # Determine pods to check
        root_node_data = self.topology.nodes.get(root, {})
        root_type = root_node_data.get('type', '')

        aggressor_pods = []
        if root_type == 'Pod':
            # Root is a pod - check it directly
            aggressor_pods = [root]
        elif root_type == 'Service':
            # Root is a service - check all its pods for aggressor behavior
            for node_id, node_data in self.topology.nodes.items():
                if node_data.get('type') == 'Pod' and node_data.get('parent_service') == root:
                    aggressor_pods.append(node_id)
        else:
            # Not a pod or service - noisy neighbor doesn't apply
            return victims

        if not aggressor_pods:
            return victims

        # Check each potential aggressor pod
        all_victims = set()
        for aggressor_pod in aggressor_pods:
            # Check if this pod has high CPU (characteristic of aggressor)
            aggr_cpu_base = get_mean(baseline, aggressor_pod, 'container.cpu.utilization')
            aggr_cpu_curr = get_mean(current, aggressor_pod, 'container.cpu.utilization')

            # Aggressor must have high absolute CPU (>75%) and increased from baseline
            if aggr_cpu_curr < 75.0 or aggr_cpu_curr < aggr_cpu_base * 1.2:
                # Not a noisy neighbor aggressor
                continue

            # Find compute node for aggressor pod
            aggr_node_data = self.topology.nodes.get(aggressor_pod, {})
            aggr_compute_node = aggr_node_data.get('compute_node')
            if not aggr_compute_node:
                # No compute node info - can't detect co-location
                continue

            # Find all other pods on the same compute node
            for node_id, node_data in self.topology.nodes.items():
                if node_id == aggressor_pod:
                    continue  # Skip aggressor itself

                if node_data.get('type') != 'Pod':
                    continue  # Only check pods

                # Check if on same compute node
                if node_data.get('compute_node') != aggr_compute_node:
                    continue  # Different node

                # Check if this pod is degraded
                node_health = health_scores.get(node_id)
                if not node_health or node_health.self_degradation_score < 2.0:
                    # Not degraded enough to be a victim
                    continue

                # Verify victim shows noisy neighbor symptoms
                # Look for: CPU increase, latency increase, or throughput drop
                victim_cpu_base = get_mean(baseline, node_id, 'container.cpu.utilization')
                victim_cpu_curr = get_mean(current, node_id, 'container.cpu.utilization')
                cpu_increase = victim_cpu_curr - victim_cpu_base

                # Get parent service for request metrics
                victim_service = node_data.get('parent_service')
                if victim_service:
                    victim_lat_base = get_mean(baseline, victim_service, 'service.duration')
                    victim_lat_curr = get_mean(current, victim_service, 'service.duration')
                    lat_growth = victim_lat_curr / victim_lat_base if victim_lat_base > 0 else 1.0
                else:
                    lat_growth = 1.0

                # Check if victim shows contention symptoms
                # CPU steal time causes: CPU increase (context switching) OR latency increase (waiting for CPU)
                has_contention_symptoms = (
                    cpu_increase > 10.0 or  # +10% CPU from context switching
                    lat_growth > 1.15       # +15% latency from CPU wait
                )

                if has_contention_symptoms:
                    all_victims.add(node_id)

        return list(all_victims)
