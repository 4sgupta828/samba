"""
Root Cause Detection Module

Implements SOTA root cause analysis:
- Leaf node identification
- Healthy dependency analysis
- Multi-path convergence
- Temporal causality validation
- Network partition detection
- Probabilistic ranking
"""

import numpy as np
import networkx as nx
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, deque


@dataclass
class RootCauseCandidate:
    """A potential root cause with evidence."""
    node_id: str
    node_type: str
    probability: float  # 0.0-1.0
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    rank: int

    # Evidence components
    is_leaf_node: bool
    all_dependencies_healthy: bool
    impacted_first: bool
    convergence_score: float  # How many paths converge to this node
    severity_score: float
    centrality_score: float
    signature_match_score: float
    temporal_consistency: bool

    # Supporting data
    convergence_path_count: int
    first_impact_time: Optional[float]
    dependencies: List[str]
    dependency_health: Dict[str, str]
    fault_signature: Dict

    reasoning: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class NetworkPartition:
    """Detected network partition."""
    affected_nodes: List[str]
    partition_time: float
    evidence_score: float
    description: str

    def to_dict(self) -> Dict:
        return asdict(self)


class RootCauseDetector:
    """
    Systematic root cause detection using multi-layered analysis.
    """

    def __init__(
        self,
        topology_graph: nx.DiGraph,
        fault_start_time: float,
        adaptive_time_window: Optional[float] = None
    ):
        """
        Initialize root cause detector.

        Args:
            topology_graph: System topology as directed graph
            fault_start_time: When fault was injected
            adaptive_time_window: Time window for "simultaneous" impacts (auto if None)
        """
        self.graph = topology_graph
        self.fault_start_time = fault_start_time

        # Adaptive time window (based on sample interval)
        self.time_window = adaptive_time_window or self._compute_adaptive_window()

    def _compute_adaptive_window(self) -> float:
        """
        Compute adaptive time window based on topology size.

        Larger topologies need larger windows due to propagation delays.
        """
        num_nodes = len(self.graph.nodes())

        if num_nodes <= 10:
            return 5.0  # Small topology: 5s window
        elif num_nodes <= 30:
            return 10.0  # Medium: 10s
        else:
            return 15.0  # Large: 15s

    def identify_leaf_nodes(self) -> Set[str]:
        """
        Identify leaf nodes (no outgoing dependencies).

        Leaf nodes include:
        - External services
        - Databases
        - Caches
        - Message queues
        - Internal services with no dependencies
        """
        leaf_nodes = set()

        for node_id in self.graph.nodes():
            node_data = self.graph.nodes[node_id]
            node_type = node_data.get('type', '')

            # Type-based leaf detection
            if node_type in ['ExternalService', 'Database', 'Cache', 'MessageQueue']:
                leaf_nodes.add(node_id)
                continue

            # Degree-based: no outgoing edges (ignoring async_consume)
            outgoing = [
                target for source, target, edge_data in self.graph.edges(node_id, data=True)
                if edge_data.get('type') != 'async_consume'  # Queues are consumers
            ]

            if len(outgoing) == 0:
                leaf_nodes.add(node_id)

        return leaf_nodes

    def get_node_dependencies(self, node_id: str) -> List[str]:
        """
        Get direct dependencies of a node.

        Dependencies are nodes that this node calls/depends on.
        """
        dependencies = []

        for source, target, edge_data in self.graph.edges(data=True):
            edge_type = edge_data.get('type', '')

            # Reverse edges for most types (impact flows backwards)
            if source == node_id and edge_type != 'async_consume':
                dependencies.append(target)
            # For async_consume, consumer depends on queue
            elif target == node_id and edge_type == 'async_consume':
                dependencies.append(source)

        return dependencies

    def identify_root_cause_candidates(
        self,
        impacted_nodes: List[str],
        healthy_nodes: List[str],
        node_health_map: Dict[str, str]
    ) -> List[str]:
        """
        Identify root cause candidates.

        UPDATED LOGIC (removes leaf node bias):
        A node is a candidate if:
        1. It is impacted (not healthy)
        2. AND at least SOME of its dependencies are healthy (not necessarily ALL)
           - This allows both leaf nodes AND non-leaf nodes with partial dependency failures
           - Removes the bias toward leaf nodes

        The old logic was:
        - Leaf node → ALWAYS a candidate
        - Non-leaf node → candidate only if ALL dependencies are healthy

        This created a strong bias toward leaf nodes because they were automatically
        included even if they had minimal impact.

        Args:
            impacted_nodes: List of impacted node IDs
            healthy_nodes: List of healthy node IDs
            node_health_map: Mapping of node_id -> health_status

        Returns:
            List of root cause candidate node IDs (unique)
        """
        candidates = set()  # Use set to avoid duplicates

        for node_id in impacted_nodes:
            dependencies = self.get_node_dependencies(node_id)

            # Case 1: No dependencies (leaf node)
            if len(dependencies) == 0:
                candidates.add(node_id)
                continue

            # Case 2: Has dependencies - check if at least some are healthy
            # This means the node is showing problems that aren't fully explained
            # by its dependencies being down
            healthy_dep_count = sum(
                1 for dep in dependencies
                if dep in healthy_nodes or node_health_map.get(dep, 'UNKNOWN') == 'HEALTHY'
            )

            # Candidate if:
            # - All dependencies are healthy (original case), OR
            # - More than 50% of dependencies are healthy (new: allows partial propagation)
            if healthy_dep_count >= len(dependencies) * 0.5:
                candidates.add(node_id)

        return list(candidates)

    def compute_shortest_paths(
        self,
        impacted_nodes: List[str],
        candidates: List[str]
    ) -> Dict[str, List[Tuple[str, int]]]:
        """
        Compute shortest paths from impacted nodes to each candidate.

        Args:
            impacted_nodes: List of impacted node IDs
            candidates: List of root cause candidate IDs

        Returns:
            Dict mapping candidate_id -> [(impacted_node, path_length), ...]
        """
        # Build propagation graph (reversed for impact flow)
        propagation_graph = self._build_propagation_graph()

        candidate_paths = defaultdict(list)

        for impacted_node in impacted_nodes:
            for candidate in candidates:
                # Skip if candidate is the impacted node itself
                if impacted_node == candidate:
                    candidate_paths[candidate].append((impacted_node, 0))
                    continue

                # Try to find path
                try:
                    path_length = nx.shortest_path_length(
                        propagation_graph,
                        source=candidate,
                        target=impacted_node
                    )
                    candidate_paths[candidate].append((impacted_node, path_length))
                except nx.NetworkXNoPath:
                    # No path exists
                    pass

        return candidate_paths

    def _build_propagation_graph(self) -> nx.DiGraph:
        """
        Build propagation graph where edges show impact flow direction.

        For most edges, reverse them (impact flows upstream).
        For async_consume, keep original (queue impacts consumers).
        """
        prop_graph = nx.DiGraph()

        for source, target, edge_data in self.graph.edges(data=True):
            edge_type = edge_data.get('type', '')

            if edge_type == 'async_consume':
                # Keep original: queue -> consumer
                prop_graph.add_edge(source, target, **edge_data)
            else:
                # Reverse: impact flows from provider to consumers
                prop_graph.add_edge(target, source, **edge_data)

        return prop_graph

    def compute_centrality_scores(self) -> Dict[str, float]:
        """
        Compute graph centrality scores for all nodes.

        Uses betweenness centrality (how many shortest paths pass through node).
        """
        try:
            # Use undirected graph for centrality (bidirectional influence)
            undirected = self.graph.to_undirected()
            centrality = nx.betweenness_centrality(undirected, normalized=True)
            return centrality
        except:
            # Fallback: use in-degree as proxy
            return {
                node: self.graph.in_degree(node) / max(1, len(self.graph.nodes()))
                for node in self.graph.nodes()
            }

    def match_fault_signature(
        self,
        node_id: str,
        ranked_metrics: List[Dict],
        expected_fault_type: Optional[str] = None
    ) -> Tuple[float, Dict]:
        """
        Check if node's metric changes match expected fault signature.

        Args:
            node_id: Node to check
            ranked_metrics: Top impacted metrics for this node
            expected_fault_type: Expected fault type (if known)

        Returns:
            (signature_match_score, fault_signature_dict)
        """
        if not ranked_metrics:
            return 0.0, {}

        # Extract top metrics
        top_metric_names = [m['metric_name'].lower() for m in ranked_metrics[:3]]

        # Common fault signatures
        signatures = {
            'cpu_saturation': ['cpu', 'thread', 'queue'],
            'memory_exhaustion': ['memory', 'heap', 'oom'],
            'slow_queries': ['latency', 'duration', 'query'],
            'inject_errors': ['error', 'fail', 'reject'],
            'inject_latency': ['latency', 'duration', 'time'],
            'connection_limit': ['pool', 'connection', 'reject'],
            'network_partition': ['error', 'timeout', 'unavailable']
        }

        # If expected fault type is known, check match
        if expected_fault_type:
            expected_keywords = signatures.get(expected_fault_type, [])
            matches = sum(
                1 for metric in top_metric_names
                if any(kw in metric for kw in expected_keywords)
            )
            match_score = matches / max(1, len(expected_keywords))

            return match_score, {
                'expected_fault_type': expected_fault_type,
                'matched_metrics': matches,
                'top_metrics': top_metric_names[:3]
            }

        # If unknown, detect most likely signature
        best_match_score = 0.0
        best_signature = None

        for sig_name, keywords in signatures.items():
            matches = sum(
                1 for metric in top_metric_names
                if any(kw in metric for kw in keywords)
            )
            score = matches / max(1, len(keywords))

            if score > best_match_score:
                best_match_score = score
                best_signature = sig_name

        return best_match_score, {
            'detected_signature': best_signature,
            'confidence': best_match_score,
            'top_metrics': top_metric_names[:3]
        }

    def detect_network_partition(
        self,
        node_reports: List[Dict],
        impacted_nodes: List[str]
    ) -> Optional[NetworkPartition]:
        """
        Detect if a network partition is the root cause.

        Network partition indicators:
        - Multiple nodes showing 100% error rates to dependencies
        - No clear single root cause
        - Widespread simultaneous impact
        """
        # Check for nodes with 100% dependency errors
        high_error_nodes = []

        for report in node_reports:
            if report['node_id'] not in impacted_nodes:
                continue

            # Check for dependency error metrics
            for metric in report.get('ranked_metrics', [])[:5]:
                metric_name = metric.get('metric_name', '').lower()

                if 'dependency' in metric_name and 'error' in metric_name:
                    # Check if error rate is very high
                    fault_mean = metric.get('fault_mean', 0)
                    baseline_mean = metric.get('baseline_mean', 0)

                    if fault_mean > 0.8:  # >80% error rate
                        high_error_nodes.append(report['node_id'])
                        break

        # Network partition if >30% of impacted nodes have dependency errors
        if len(high_error_nodes) >= max(3, len(impacted_nodes) * 0.3):
            # Find earliest impact time
            impact_times = [
                r.get('first_impact_time')
                for r in node_reports
                if r['node_id'] in high_error_nodes and r.get('first_impact_time')
            ]

            partition_time = min(impact_times) if impact_times else self.fault_start_time

            return NetworkPartition(
                affected_nodes=high_error_nodes,
                partition_time=partition_time,
                evidence_score=len(high_error_nodes) / len(impacted_nodes),
                description=f"Network partition detected affecting {len(high_error_nodes)} nodes"
            )

        return None

    def rank_root_cause_candidates(
        self,
        candidates: List[str],
        candidate_paths: Dict[str, List[Tuple[str, int]]],
        node_severity_scores: Dict[str, float],
        node_first_impact_times: Dict[str, Optional[float]],
        node_ranked_metrics: Dict[str, List[Dict]],
        centrality_scores: Dict[str, float],
        impacted_node_count: int,
        expected_fault_type: Optional[str] = None
    ) -> List[RootCauseCandidate]:
        """
        Rank root cause candidates using probabilistic scoring.

        Args:
            candidates: List of candidate node IDs
            candidate_paths: Shortest paths to each candidate
            node_severity_scores: Severity scores for each node
            node_first_impact_times: First impact time for each node
            node_ranked_metrics: Top metrics for each node
            centrality_scores: Graph centrality scores
            impacted_node_count: Total number of impacted nodes
            expected_fault_type: Expected fault type (if known from ground truth)

        Returns:
            Ranked list of RootCauseCandidate objects
        """
        leaf_nodes = self.identify_leaf_nodes()
        earliest_impact = min(
            (t for t in node_first_impact_times.values() if t is not None),
            default=None
        )

        ranked_candidates = []

        for candidate in candidates:
            # Factor 1: Convergence score (path-based)
            paths = candidate_paths.get(candidate, [])
            convergence_score = len(paths) / max(1, impacted_node_count)

            # Factor 2: Severity score
            severity_score = node_severity_scores.get(candidate, 0.0)

            # Factor 3: Temporal precedence
            first_impact = node_first_impact_times.get(candidate)
            impacted_first = (
                first_impact is not None and
                earliest_impact is not None and
                abs(first_impact - earliest_impact) <= self.time_window
            )
            time_score = 1.0 if impacted_first else 0.5

            # Factor 4: Centrality
            centrality_score = centrality_scores.get(candidate, 0.0)

            # Factor 5: Fault signature match
            ranked_metrics = node_ranked_metrics.get(candidate, [])
            signature_score, fault_sig = self.match_fault_signature(
                candidate, ranked_metrics, expected_fault_type
            )

            # Temporal consistency check
            temporal_consistent = self._check_temporal_consistency(
                candidate, paths, node_first_impact_times
            )

            # Compute composite probability
            probability = self._compute_probability(
                convergence_score=convergence_score,
                severity_score=severity_score,
                time_score=time_score,
                centrality_score=centrality_score,
                signature_score=signature_score,
                temporal_consistent=temporal_consistent
            )

            # Determine confidence level
            if probability >= 0.7:
                confidence = 'HIGH'
            elif probability >= 0.4:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'

            # Get dependencies and their health
            dependencies = self.get_node_dependencies(candidate)
            dep_health = {}  # Would be populated from health classifier

            # Build reasoning
            reasoning = self._build_reasoning(
                is_leaf=candidate in leaf_nodes,
                convergence_score=convergence_score,
                impacted_first=impacted_first,
                path_count=len(paths),
                severity_score=severity_score
            )

            # Get node type
            node_type = self.graph.nodes[candidate].get('type', 'Unknown')

            ranked_candidates.append(RootCauseCandidate(
                node_id=candidate,
                node_type=node_type,
                probability=probability,
                confidence=confidence,
                rank=0,  # Will be set after sorting
                is_leaf_node=candidate in leaf_nodes,
                all_dependencies_healthy=len(dependencies) == 0,  # Simplified
                impacted_first=impacted_first,
                convergence_score=convergence_score,
                severity_score=severity_score,
                centrality_score=centrality_score,
                signature_match_score=signature_score,
                temporal_consistency=temporal_consistent,
                convergence_path_count=len(paths),
                first_impact_time=first_impact,
                dependencies=dependencies,
                dependency_health=dep_health,
                fault_signature=fault_sig,
                reasoning=reasoning
            ))

        # Sort by probability
        ranked_candidates.sort(key=lambda c: c.probability, reverse=True)

        # Assign ranks
        for i, candidate in enumerate(ranked_candidates, start=1):
            candidate.rank = i

        return ranked_candidates

    def _check_temporal_consistency(
        self,
        candidate_id: str,
        paths: List[Tuple[str, int]],
        node_first_impact_times: Dict[str, Optional[float]]
    ) -> bool:
        """
        Check if impact times are consistent with candidate being root cause.

        UPDATED LOGIC (stricter temporal ordering):
        - Root cause MUST be impacted first (or within a small time window)
        - Then hop-1 nodes (direct dependencies/dependents)
        - Then hop-2 nodes, and so on
        - This enforces causal propagation patterns

        Old logic was too lenient and only checked if nodes were impacted "around the same time".
        """
        if not paths:
            return True

        candidate_time = node_first_impact_times.get(candidate_id)
        if candidate_time is None:
            return False

        # Group paths by distance from candidate
        paths_by_distance = defaultdict(list)
        for impacted_node, distance in paths:
            impacted_time = node_first_impact_times.get(impacted_node)
            if impacted_time is not None:
                paths_by_distance[distance].append((impacted_node, impacted_time))

        # Check temporal ordering by distance (hop count)
        # Nodes at distance 0 (the candidate itself) should be first
        # Nodes at distance 1 should be impacted after distance 0
        # Nodes at distance 2 should be impacted after distance 1, etc.

        max_distance = max(paths_by_distance.keys()) if paths_by_distance else 0
        inconsistent_count = 0
        total_checks = 0

        for dist in range(max_distance + 1):
            nodes_at_dist = paths_by_distance.get(dist, [])

            for node_id, node_time in nodes_at_dist:
                # Distance 0 is the candidate itself - skip
                if dist == 0:
                    continue

                # Check: This node should be impacted AFTER the candidate
                # Use time_window as tolerance (e.g., 5-10s)
                if node_time < candidate_time - self.time_window:
                    inconsistent_count += 1

                total_checks += 1

                # Also check hop-by-hop ordering:
                # Nodes at distance N should be impacted after nodes at distance N-1
                if dist > 1:
                    prev_nodes = paths_by_distance.get(dist - 1, [])
                    if prev_nodes:
                        # Get earliest impact time at previous hop
                        earliest_prev = min(t for _, t in prev_nodes)
                        # Current node should be impacted after (or around) previous hop
                        # Allow more tolerance for multi-hop propagation
                        if node_time < earliest_prev - (self.time_window * 0.5):
                            inconsistent_count += 1

        if total_checks == 0:
            return True

        # Stricter threshold: consider inconsistent if >10% violations (was 20%)
        return inconsistent_count < total_checks * 0.1

    def _compute_probability(
        self,
        convergence_score: float,
        severity_score: float,
        time_score: float,
        centrality_score: float,
        signature_score: float,
        temporal_consistent: bool
    ) -> float:
        """
        Compute composite probability from weighted factors.

        UPDATED WEIGHTS (emphasizes temporal ordering and severity):
        - Temporal ordering is now MORE important (30% -> time + consistency)
        - Severity is emphasized (25% -> 30%)
        - Convergence is slightly reduced (30% -> 25%)
        - Centrality and signature remain supportive (10% each)
        """
        # Updated weights to emphasize temporal causality
        weights = {
            'convergence': 0.25,  # Reduced from 0.30
            'severity': 0.30,     # Increased from 0.25
            'time': 0.25,         # Same (temporal precedence)
            'centrality': 0.10,   # Same
            'signature': 0.10     # Same
        }

        probability = (
            convergence_score * weights['convergence'] +
            severity_score * weights['severity'] +
            time_score * weights['time'] +
            centrality_score * weights['centrality'] +
            signature_score * weights['signature']
        )

        # STRICTER penalty for temporal inconsistency (0.7 -> 0.5)
        # If temporal ordering is violated, this is a major red flag
        if not temporal_consistent:
            probability *= 0.5

        return min(1.0, probability)

    def _build_reasoning(
        self,
        is_leaf: bool,
        convergence_score: float,
        impacted_first: bool,
        path_count: int,
        severity_score: float
    ) -> str:
        """Build human-readable reasoning for candidate."""
        reasons = []

        if is_leaf:
            reasons.append("leaf node")

        if convergence_score > 0.5:
            reasons.append(f"{path_count} impact paths converge here")

        if impacted_first:
            reasons.append("impacted first")

        if severity_score > 0.7:
            reasons.append("critical severity")
        elif severity_score > 0.4:
            reasons.append("high severity")

        return "; ".join(reasons) if reasons else "candidate root cause"
