"""
causal_graph_reasoner.py

The "Physics Engine" acting as a Validation Layer.
1. Validates individual edges (Did A really break B?) using Relative Metrics.
2. Calculates Explanatory Power (How much of the blast radius does this node explain?)
"""

import networkx as nx
import numpy as np
from typing import Dict, List, Set, Any, Tuple
from dataclasses import dataclass, field
from config_extractor import CausalConstants

@dataclass
class CausalLink:
    source: str
    target: str
    mechanism: str # 'latency', 'error', 'timeout'
    valid: bool
    evidence: str

@dataclass
class CausalHypothesis:
    root_cause_node: str
    coverage_score: float # 0.0 to 1.0
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

        # Check if this is a queue node
        return node_type == 'MessageQueue' or node_role == 'queue' or 'queue' in node_id.lower()

    def _has_queue_fault(self, queue_id: str, health_scores: Dict) -> bool:
        """
        Check if a queue has a real fault (not just normal buffering).

        A queue has a real fault if:
        1. Capacity limits hit (near max capacity)
        2. Queue failures (message drops, connection issues)
        3. Queue-level latency (slow queue operations affecting all clients)

        Returns True if the queue itself is broken, False if just buffering.
        """
        if queue_id not in health_scores:
            return False

        health = health_scores[queue_id]
        symptoms = health.symptoms

        # Check symptoms for real queue faults
        for symptom in symptoms:
            symptom_lower = symptom.lower()

            # Real queue faults (marked by our symptom detector)
            if 'queue fault' in symptom_lower:
                return True

            # Capacity saturation
            if 'capacity' in symptom_lower or 'saturation' in symptom_lower:
                return True

            # Queue errors/failures
            if 'error' in symptom_lower and 'queue' in symptom_lower:
                return True

            # Queue-level latency (not just depth increase)
            if 'latency' in symptom_lower and 'queue' in symptom_lower:
                return True

        # If only symptom is "buffering (producer/consumer imbalance)", not a queue fault
        for symptom in symptoms:
            if 'buffering' in symptom.lower() and 'imbalance' in symptom.lower():
                return False

        # Default: If queue has symptoms but none of the above, conservatively say no fault
        return False

    def validate_edge(self, callee: str, caller: str,
                     baseline: Dict, current: Dict,
                     health_scores: Dict) -> Tuple[float, str]:
        """
        Returns a 'Physics Confidence' score (0.0 to 1.0) for a specific link.
        Used by Disambiguator to weight votes.
        """
        link = self._verify_propagation(callee, caller, baseline, current, health_scores)

        if link.valid:
            return 1.0, link.evidence
        else:
            # Physics mismatch: We return a low score (0.2) instead of 0.0.
            # This allows the "Voting System" to still function if the signal is massive
            # but physics calculation failed due to data noise.
            return 0.2, "Physics Mismatch (Weak propagation)"

    def calculate_global_coverage(self,
                                candidates: List[str],
                                health_scores: Dict,
                                baseline: Dict,
                                current: Dict) -> Dict[str, CausalHypothesis]:
        """
        For every candidate, calculate how much of the system symptoms it explains.
        Returns map: {node_id: Hypothesis}
        """
        # Define Total System Pain (Nodes that deviated significantly)
        total_symptomatic = {
            n for n, h in health_scores.items()
            if h.self_degradation_score > 2.0
        }

        results = {}
        for candidate in candidates:
            # Trace the blast radius upstream
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

        Queue-aware propagation:
        - Skips queues as intermediate nodes in blast radius UNLESS the queue itself has real issues
        - Queues are passive buffers, not active components that cause faults
        - Only includes queues if they have: capacity limits, failures, or queue-level latency
        """
        h = CausalHypothesis(
            root_cause_node=root,
            coverage_score=0.0
        )
        h.explained_nodes.add(root)

        # Get primary symptom from symptoms list if available
        root_symptoms = []
        if root in health_scores:
            root_symptoms = health_scores[root].symptoms
        root_type = root_symptoms[0] if root_symptoms else "unknown"
        h.narrative.append(f"ROOT: {root} ({root_type})")

        queue = [root]
        visited = {root}

        while queue:
            curr = queue.pop(0)
            callers = list(self.topology.predecessors(curr))

            for caller in callers:
                if caller in visited:
                    continue

                # Check if caller is a queue - if so, apply queue-aware logic
                if self._is_queue_node(caller):
                    # Only include queue in blast radius if it has real issues
                    if not self._has_queue_fault(caller, health_scores):
                        # Queue is just buffering normally - skip it and continue to producers/consumers
                        # Don't add to explained_nodes, but mark as visited to avoid loops
                        visited.add(caller)
                        h.narrative.append(f"  -> Skipped queue {caller} (normal buffering)")
                        continue

                link = self._verify_propagation(curr, caller, baseline, current, health_scores)

                if link.valid:
                    h.explained_nodes.add(caller)
                    h.narrative.append(f"  -> Propagated to {caller}: {link.evidence}")
                    visited.add(caller)
                    queue.append(caller)
                else:
                    h.broken_links.append(link)

        return h

    def _verify_propagation(self, callee: str, caller: str,
                          baseline: Dict, current: Dict,
                          health_scores: Dict) -> CausalLink:
        """
        Verifies propagation using RELATIVE comparisons against baseline.
        """
        # Helpers
        def get_mean(data, node, metric):
            vals = data.get(node, {}).get(metric, [])
            return np.mean(vals) if len(vals) > 0 else 0.0

        def calc_growth(base, curr):
            epsilon = 0.01
            return (curr + epsilon) / (base + epsilon)

        # 1. Fetch Metrics
        callee_base_lat = get_mean(baseline, callee, 'avg_latency')
        callee_curr_lat = get_mean(current, callee, 'avg_latency')
        caller_base_dep = get_mean(baseline, caller, 'dependency_latency')
        caller_curr_dep = get_mean(current, caller, 'dependency_latency')

        callee_base_err = get_mean(baseline, callee, 'internal_error_rate')
        callee_curr_err = get_mean(current, callee, 'internal_error_rate')
        caller_base_dep_err = get_mean(baseline, caller, 'dependency_error_rate')
        caller_curr_dep_err = get_mean(current, caller, 'dependency_error_rate')

        # 2. Calculate Growth Factors
        callee_lat_growth = calc_growth(callee_base_lat, callee_curr_lat)
        caller_dep_growth = calc_growth(caller_base_dep, caller_curr_dep)

        # 3. Context Check (Limp Mode / Deadlock)
        callee_health = health_scores.get(callee)
        is_deadlocked = False
        if callee_health:
            # Check if any symptom contains "deadlock" or "limp"
            symptoms_lower = [s.lower() for s in callee_health.symptoms]
            is_deadlocked = any('deadlock' in s or 'limp' in s for s in symptoms_lower)

        # --- PHYSICS CHECKS ---

        # A. TIMEOUT / DEADLOCK
        if is_deadlocked:
            if caller_dep_growth > CausalConstants.DEADLOCK_GROWTH_THRESHOLD:
                return CausalLink(callee, caller, 'timeout', True,
                                f"Deadlock Propagation (Wait {caller_dep_growth:.1f}x)")

        # B. LATENCY (Backpressure)
        if callee_lat_growth > CausalConstants.MIN_LATENCY_GROWTH:
            # Caller must reflect diluted growth
            required_growth = 1.0 + ((callee_lat_growth - 1.0) * CausalConstants.LATENCY_DILUTION_FACTOR)
            if caller_dep_growth > required_growth:
                return CausalLink(callee, caller, 'latency', True,
                                f"Latency Match (Callee {callee_lat_growth:.1f}x -> Caller {caller_dep_growth:.1f}x)")

        # C. ERRORS (Bubbling)
        callee_err_delta = callee_curr_err - callee_base_err
        caller_err_delta = caller_curr_dep_err - caller_base_dep_err

        if callee_err_delta > CausalConstants.MIN_ERROR_DELTA:
            if caller_err_delta > 0:
                return CausalLink(callee, caller, 'error', True,
                                f"Error Bubbling (+{callee_err_delta:.1%} -> +{caller_err_delta:.1%})")

        return CausalLink(callee, caller, 'unknown', False, "Physics Mismatch")
