"""
Deterministic Capacity Planner.
Right-sizes infrastructure based on semantic request flows and fragility.
Handles Async Queues, Poisson Bursts, and Circular Dependencies.
"""
import math
import networkx as nx
from typing import Dict, Any, List, Tuple, Set
from src.validation.component_profiles import get_component_profile, get_network_latency

class CapacityPlanner:
    def __init__(self, graph: nx.DiGraph, semantic_map: Dict = None):
        self.graph = graph
        self.semantic_map = semantic_map or {}

    def plan_capacity(self, target_global_rps: float, phi: float) -> Dict[str, Dict[str, Any]]:
        """
        Tunes node resources based on exact semantic flows.

        Args:
            target_global_rps: Total ingress RPS.
            phi: Fragility index [0.0=Robust, 1.0=Critical].
        """
        # 1. Calculate deterministic load per node
        node_metrics = self._calculate_deterministic_load(target_global_rps, phi)

        tuned_configs = {}

        for node_id, metrics in node_metrics.items():
            if node_id == 'workload': continue
            if node_id not in self.graph.nodes: continue

            node_data = self.graph.nodes[node_id]
            role = node_data.get('role', 'service')

            # Tune the node based on its specific load
            config = self._tune_node(node_id, role, metrics, phi)
            tuned_configs[node_id] = config

        return tuned_configs

    def _calculate_deterministic_load(self, global_rps: float, phi: float) -> Dict[str, Any]:
        """Traverses flows to calculate RPS load."""
        node_stats = {n: {'rps': 0.0} for n in self.graph.nodes()}

        flows = self.semantic_map.get('request_flows', {})
        request_types = self.semantic_map.get('request_types', ['GET'])
        type_weight = 1.0 / max(1, len(request_types))

        for req_type in request_types:
            flow_map = flows.get(req_type, {})
            type_rps = global_rps * type_weight

            # Start at gateways/frontends
            entry_points = [n for n in self.graph.nodes()
                          if self.graph.nodes[n].get('is_frontend') or
                             self.graph.nodes[n].get('role') == 'gateway']

            for entry in entry_points:
                self._traverse_flow(entry, type_rps, flow_map, node_stats, phi, visited=set())

        return node_stats

    def _traverse_flow(self, node_id: str, rps: float, flow_map: Dict, stats: Dict, phi: float, visited: Set[str]):
        """Recursive traversal to accumulate RPS."""
        if node_id not in stats: return

        # Prevent infinite loops in load calculation
        if node_id in visited: return
        visited.add(node_id)

        # Add load to current node
        stats[node_id]['rps'] += rps

        successors = list(self.graph.successors(node_id))

        # 1. Explicit Service Flows (from Semantic Map)
        downstream_services = flow_map.get(node_id, [])
        for child in downstream_services:
            # 1:1 mapping: if A calls B in a flow, it calls it for every request
            self._traverse_flow(child, rps, flow_map, stats, phi, visited.copy())

        # 2. Infrastructure Dependencies (Implicit)
        infrastructure_nodes = [
            n for n in successors
            if self.graph.nodes[n].get('role') in ['database', 'cache', 'queue']
        ]

        for infra in infrastructure_nodes:
            edge_data = self.graph.get_edge_data(node_id, infra)
            edge_type = edge_data.get('type', 'sync')

            infra_load = rps

            # Logic for Caches reducing DB load
            if self.graph.nodes[infra].get('role') == 'database':
                caches = [n for n in successors if self.graph.nodes[n].get('role') == 'cache']
                if caches:
                    # Effective hit rate degrades as phi increases (fragility)
                    base_hit_rate = 0.8
                    effective_hit_rate = base_hit_rate * (1.0 - (phi * 0.2))
                    infra_load = rps * (1.0 - effective_hit_rate)

            # Logic for Queues (Decoupling)
            if self.graph.nodes[infra].get('role') == 'queue':
                stats[infra]['rps'] += infra_load

                # Propagate to consumers
                consumers = [
                    u for u, v, d in self.graph.out_edges(infra, data=True)
                    if d.get('type') == 'async_consume'
                ]
                for consumer in consumers:
                    # Pass empty set for visited to restart cycle detection for new async context
                    self._traverse_flow(consumer, infra_load, flow_map, stats, phi, visited=set())
            else:
                stats[infra]['rps'] += infra_load

    def _estimate_dependency_latency(self, node_id: str, phi: float, visited=None) -> float:
        """
        Recursively estimates P99 latency of dependencies.
        Stops at Async boundaries (Queues). Handles Circular dependencies.
        NOW APPLIES semantic profile multipliers for accurate estimation.
        """
        if visited is None: visited = set()
        if node_id in visited: return 0.0
        visited.add(node_id)

        total_dep_latency = 0.0

        successors = list(self.graph.successors(node_id))
        for child in successors:
            edge_data = self.graph.get_edge_data(node_id, child)
            edge_type = edge_data.get('type', 'sync_rpc')

            # Async calls do not add blocking latency to the caller
            if 'async' in edge_type or self.graph.nodes[child].get('role') == 'queue':
                continue

            net_latency = get_network_latency(edge_type).p99

            child_role = self.graph.nodes[child].get('role', 'service')
            child_profile_base, _ = get_component_profile(child_role)

            # Apply multiplier here too!
            # Look up semantic profile
            child_sem_profile = "standard"
            if self.semantic_map and 'services' in self.semantic_map:
                child_sem_profile = self.semantic_map['services'].get(child, {}).get('profile', 'standard')

            mult = 1.0
            if child_sem_profile == "cpu_intensive":
                mult = 2.5
            elif child_sem_profile == "io_intensive":
                mult = 1.1
            elif child_sem_profile == "latency_sensitive":
                mult = 0.8

            child_effective_time = child_profile_base.p99 * mult

            child_dep_latency = self._estimate_dependency_latency(child, phi, visited.copy())

            # Assume sequential execution for worst-case timeout budgeting
            total_dep_latency += (net_latency + child_effective_time + child_dep_latency)

        return total_dep_latency

    def _tune_node(self, node_id: str, role: str, metrics: Dict, phi: float) -> Dict[str, Any]:
        """Calculates resource parameters."""
        rps = metrics['rps']
        if rps <= 0: rps = 0.1

        # Fix B: Poisson Buffer - Increase minimum headroom
        headroom = 1.25 + (2.75 * (1.0 - phi)) # Maps phi 0->4.0x, phi 1->1.25x

        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50

        # --- CRITICAL FIX: Apply Semantic Profile Multipliers ---
        # We must match the logic in src/components/pod.py
        resource_profile = "standard"
        if self.semantic_map and 'services' in self.semantic_map:
            svc_data = self.semantic_map['services'].get(node_id, {})
            resource_profile = svc_data.get('profile', 'standard')

        # Apply multipliers used in Pod runtime
        latency_multiplier = 1.0
        if resource_profile == "cpu_intensive":
            latency_multiplier = 2.5
        elif resource_profile == "io_intensive":
            latency_multiplier = 1.1
        elif resource_profile == "latency_sensitive":
            latency_multiplier = 0.8

        # The actual expected processing time
        effective_processing_ms = base_processing_ms * latency_multiplier

        config = {}

        if role == 'service' or role == 'gateway':
            # Horizontal Scaling (Pods)
            cpu_per_req_ms = res_prof.cpu_ms_per_request * latency_multiplier  # CPU scales with time
            # Cap single pod capacity to force horizontal scaling
            max_rps_per_pod = min(1000.0 / max(0.1, cpu_per_req_ms), 500.0)

            raw_replicas = rps / max_rps_per_pod
            tuned_replicas = math.ceil(raw_replicas * headroom)

            # Ensure at least 2 replicas for high load services to reduce variance risk
            min_replicas = 2 if rps > 50 else 1
            config['desired_replicas'] = max(min_replicas, tuned_replicas)

            # Vertical Tuning (Threads per Pod)
            pod_rps = rps / config['desired_replicas']

            # Little's Law with EFFECTIVE latency
            # Demand = RPS * Latency
            concurrency_per_pod = math.ceil(pod_rps * (effective_processing_ms / 1000.0))

            # High phi -> tight pool. Low phi -> huge pool.
            pool_headroom = 1.0 + (1.5 * (1.0 - phi))

            # CRITICAL FIX: Minimum floor of 10 threads
            # 5 threads is too fragile for SimPy scheduling variance
            config['thread_pool_size'] = max(10, int(concurrency_per_pod * pool_headroom))

            # DB Connections: Ensure we don't starve DB calls
            config['db_connection_pool_capacity'] = max(5, int(config['thread_pool_size'] * 0.8))

            # Timeout Tuning (Flow-Aware)
            chain_latency = self._estimate_dependency_latency(node_id, phi)
            # Use effective local processing time
            total_expected_ms = effective_processing_ms + chain_latency

            timeout_margin = 1.2 + (3.0 * (1.0 - phi))  # Increased base margin
            timeout_sec = (total_expected_ms * timeout_margin) / 1000.0

            config['timeouts'] = {
                'database_call_seconds': max(0.2, timeout_sec),
                'service_call_seconds': max(0.2, timeout_sec),
                'external_api_seconds': max(1.0, timeout_sec * 2)
            }

        elif role == 'database':
            # DB Connections
            system_concurrency = rps * (base_processing_ms / 1000.0)
            config['connection_pool_capacity'] = max(50, int(system_concurrency * headroom * 2))

            # CPU Cores
            queries_per_core = 1000.0 / res_prof.cpu_ms_per_request
            needed_cores = math.ceil((rps / queries_per_core) * headroom)
            config['cpu_cores'] = max(2, int(needed_cores))

        return config
