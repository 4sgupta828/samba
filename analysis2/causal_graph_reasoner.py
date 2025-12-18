"""
causal_graph_reasoner.py

The "Physics Engine" of RCA with queue-aware propagation.

SOTA Features:
1. Validates failure propagation using RELATIVE metric factors
2. Calculates Physics Coverage (blast radius explanation)
3. Queue-aware propagation: Skips queues that are just buffering
4. Narrative generation with causal chains
"""

import networkx as nx
import numpy as np
from typing import Dict, List, Set, Any
from dataclasses import dataclass, field
from config_extractor import CausalConstants

@dataclass
class CausalLink:
    source: str
    target: str
    mechanism: str  # 'latency', 'error', 'timeout', 'capacity', 'weak'
    valid: bool
    evidence: str

@dataclass
class CausalHypothesis:
    root_cause_node: str
    symptom_type: str
    coverage_score: float
    explained_nodes: Set[str] = field(default_factory=set)
    broken_links: List[CausalLink] = field(default_factory=list)
    narrative: List[str] = field(default_factory=list)

class CausalGraphReasoner:
    def __init__(self, topology: nx.DiGraph):
        self.topology = topology

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

    def calculate_global_coverage(self, candidates: List[str], health_scores: Dict, baseline: Dict, current: Dict) -> Dict[str, CausalHypothesis]:
        """For every candidate, calculate how much of the system it explains."""

        total_symptomatic = {n for n, h in health_scores.items() if h.self_degradation_score > 2.0}

        results = {}
        for candidate in candidates:
            h = self._trace_blast_radius(candidate, health_scores, baseline, current)

            if total_symptomatic:
                explained = h.explained_nodes.intersection(total_symptomatic)
                h.coverage_score = len(explained) / len(total_symptomatic)
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
            callers = list(self.topology.predecessors(curr))

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
                return np.mean(vals) if len(vals) > 0 else 0.0
            return 0.0

        # Latency metrics
        callee_lat_base = get_service_metric(baseline, callee, 'duration')
        callee_lat_curr = get_service_metric(current, callee, 'duration')
        callee_lat_growth = calc_growth(callee_lat_base, callee_lat_curr)

        caller_dep_base = get_service_metric(baseline, caller, 'dependency.duration')
        caller_dep_curr = get_service_metric(current, caller, 'dependency.duration')
        caller_dep_growth = calc_growth(caller_dep_base, caller_dep_curr)

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
