"""
Deterministic Capacity Planner.
Right-sizes infrastructure based on semantic request flows and fragility.
Handles Async Queues, Poisson Bursts, and Circular Dependencies.

FIXED: Async consumer capacity now ensures queue stability using queueing theory.
       Phi applies to headroom above stability threshold, not baseline capacity.
"""
import math
import networkx as nx
from typing import Dict, Any, List, Tuple, Set
import logging
from src.validation.component_profiles import get_component_profile, get_network_latency
from src.core.constants import get_profile_multiplier

logger = logging.getLogger(__name__)

class CapacityPlanner:
    def __init__(self, graph: nx.DiGraph, semantic_map: Dict = None):
        self.graph = graph
        self.semantic_map = semantic_map or {}
        self.validation_warnings = []

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

        # PASS 1: Tune Services & Gateways (The Clients) first
        # We need their thread/connection pool sizes finalized before we can size the DBs
        client_roles = ['service', 'gateway']
        for node_id, metrics in node_metrics.items():
            if node_id == 'workload': continue
            if node_id not in self.graph.nodes: continue

            role = self.graph.nodes[node_id].get('role', 'service')
            if role in client_roles:
                tuned_configs[node_id] = self._tune_node(node_id, role, metrics, phi, tuned_configs, node_metrics)

        # PASS 2: Tune Infrastructure (Databases, Caches, Queues)
        # Now we can accurately sum up the upstream client demand
        infra_roles = ['database', 'cache', 'queue']
        for node_id, metrics in node_metrics.items():
            if node_id == 'workload': continue
            if node_id not in self.graph.nodes: continue

            role = self.graph.nodes[node_id].get('role', 'service')
            if role in infra_roles:
                # Pass the already-computed tuned_configs so DB can look up its clients
                tuned_configs[node_id] = self._tune_node(node_id, role, metrics, phi, tuned_configs)

        # ANALYTICAL VALIDATION: Check capacity is sufficient
        validation_passed = self._validate_capacity(node_metrics, tuned_configs, phi)
        if not validation_passed:
            logger.error("Capacity validation failed! System may be unstable at baseline.")
            for warning in self.validation_warnings:
                logger.error(f"  - {warning}")

        return tuned_configs

    def _is_async_consumer(self, node_id: str) -> bool:
        """
        Detect if a service is an async consumer (consumes from queue).
        Returns True if node has incoming async_consume edges.
        """
        for pred, _, edge_data in self.graph.in_edges(node_id, data=True):
            if edge_data.get('type') == 'async_consume':
                return True
        return False

    def _get_upstream_queues(self, node_id: str) -> List[str]:
        """Get list of queues this service consumes from."""
        queues = []
        for pred, _, edge_data in self.graph.in_edges(node_id, data=True):
            if edge_data.get('type') == 'async_consume':
                queues.append(pred)
        return queues

    def _calculate_production_rate_to_queue(self, queue_id: str, node_metrics: Dict) -> float:
        """
        Calculate total production rate to a queue from all producers.
        Returns RPS that will be enqueued.
        """
        total_production = 0.0
        for pred, _, edge_data in self.graph.in_edges(queue_id, data=True):
            if edge_data.get('type') == 'async_produce':
                # Get the calculated RPS for this producer
                producer_rps = node_metrics.get(pred, {}).get('rps', 0.0)
                total_production += producer_rps

        return total_production

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
                    # Continue tracking visited nodes to prevent infinite recursion in cycles
                    self._traverse_flow(consumer, infra_load, flow_map, stats, phi, visited.copy())
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

            mult = get_profile_multiplier(child_sem_profile)

            child_effective_time = child_profile_base.p99 * mult

            child_dep_latency = self._estimate_dependency_latency(child, phi, visited.copy())

            # Assume sequential execution for worst-case timeout budgeting
            total_dep_latency += (net_latency + child_effective_time + child_dep_latency)

        return total_dep_latency

    def _tune_async_consumer(
        self,
        node_id: str,
        role: str,
        metrics: Dict,
        phi: float,
        node_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Tune async consumer using queue stability theory.
        Ensures consumer capacity exceeds production rate with margin for queue draining.
        """
        rps = metrics['rps']
        if rps <= 0:
            rps = 0.1

        # Get production rate to queues this consumer reads from
        queues = self._get_upstream_queues(node_id)
        total_production_rps = 0.0
        for queue_id in queues:
            production = self._calculate_production_rate_to_queue(queue_id, node_metrics)
            total_production_rps += production

        # Use the higher of calculated RPS or production rate
        # (flow calculation should match production, but be safe)
        effective_rps = max(rps, total_production_rps)

        logger.info(f"Async consumer {node_id}: flow_rps={rps:.1f}, production_rps={total_production_rps:.1f}, using={effective_rps:.1f}")

        # Get component profiles
        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50

        # Get semantic profile multiplier
        resource_profile = "standard"
        if self.semantic_map and 'services' in self.semantic_map:
            svc_data = self.semantic_map['services'].get(node_id, {})
            resource_profile = svc_data.get('profile', 'standard')
        latency_multiplier = get_profile_multiplier(resource_profile)

        effective_processing_ms = base_processing_ms * latency_multiplier

        # BURST FACTOR: Account for P95 production spikes (not just mean)
        # Workloads are bursty; P95 can be 1.3-1.5x mean
        burst_factor = 1.3

        # DRAIN MARGIN: Consumer must exceed production to drain queue
        # Need 20% excess capacity to handle accumulated backlog
        drain_margin = 1.2

        # REQUIRED consumption rate for queue stability
        required_consumer_rps = effective_rps * burst_factor * drain_margin

        logger.info(f"  → Required consumer capacity: {required_consumer_rps:.1f} RPS (burst={burst_factor}, drain={drain_margin})")

        # --- Horizontal Scaling: Calculate baseline stable replicas ---
        cpu_per_req_ms = res_prof.cpu_ms_per_request * latency_multiplier
        max_rps_per_pod = min(1000.0 / max(0.1, cpu_per_req_ms), 500.0)

        # Minimum replicas for stability (no phi reduction here!)
        baseline_stable_replicas = math.ceil(required_consumer_rps / max_rps_per_pod)
        baseline_stable_replicas = max(1, baseline_stable_replicas)

        # PHI ONLY AFFECTS HEADROOM ABOVE STABILITY
        # phi=0.0 → 2.0x headroom above baseline
        # phi=1.0 → 1.0x headroom (no extra, exactly at stability)
        headroom_multiplier = 1.0 + (1.0 * (1.0 - phi))

        final_replicas = max(1, int(baseline_stable_replicas * headroom_multiplier))

        logger.info(f"  → Replicas: baseline_stable={baseline_stable_replicas}, with phi headroom={final_replicas}")

        # --- Vertical Tuning: Thread Pool ---
        pod_rps = required_consumer_rps / final_replicas

        # For async consumers, use P95 latency (more variance than sync)
        # Include dependency latency
        chain_latency = self._estimate_dependency_latency(node_id, phi)
        p95_latency_ms = (effective_processing_ms + chain_latency) * 1.5  # P95 ≈ 1.5x P50

        # Little's Law with P95 latency
        concurrency_per_pod = math.ceil(pod_rps * (p95_latency_ms / 1000.0))

        # Pool headroom for async consumers: less aggressive reduction
        # phi=0.0 → 1.5x, phi=1.0 → 1.1x (minimum margin for variance)
        pool_headroom = 1.1 + (0.4 * (1.0 - phi))

        threads = max(10, int(concurrency_per_pod * pool_headroom))

        logger.info(f"  → Threads: {threads} (concurrency={concurrency_per_pod}, pool_headroom={pool_headroom:.2f})")

        # DB connections
        has_db_dependency = any(
            self.graph.nodes[succ].get('role') == 'database'
            for succ in self.graph.successors(node_id)
        )
        db_connections = max(5, int(threads * 0.8)) if has_db_dependency else 0

        # Timeouts
        total_expected_ms = effective_processing_ms + chain_latency
        timeout_margin = 1.05 + (0.45 * (1.0 - phi))
        timeout_sec = (total_expected_ms * timeout_margin) / 1000.0

        config = {
            'desired_replicas': final_replicas,
            'thread_pool_size': threads,
            'db_connection_pool_capacity': db_connections,
            'timeouts': {
                'database_call_seconds': max(0.2, timeout_sec),
                'service_call_seconds': max(0.2, timeout_sec),
                'external_api_seconds': max(1.0, timeout_sec * 2)
            },
            '_capacity_rationale': {
                'archetype': 'async_consumer',
                'production_rps': total_production_rps,
                'required_consumer_rps': required_consumer_rps,
                'baseline_stable_replicas': baseline_stable_replicas,
                'burst_factor': burst_factor,
                'drain_margin': drain_margin
            }
        }

        return config

    def _tune_node(self, node_id: str, role: str, metrics: Dict, phi: float, existing_configs: Dict[str, Any], node_metrics: Dict[str, Any] = None) -> Dict[str, Any]:
        """Calculates resource parameters."""
        # ARCHETYPE DETECTION: Route async consumers to specialized handler
        if role in ['service', 'gateway'] and self._is_async_consumer(node_id):
            logger.info(f"Detected async consumer: {node_id}")
            return self._tune_async_consumer(node_id, role, metrics, phi, node_metrics or {})

        rps = metrics['rps']
        if rps <= 0: rps = 0.1

        # Poisson Buffer
        headroom = 1.15 + (2.85 * (1.0 - phi))

        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50

        # 1. Determine Semantic Profile & Multiplier
        resource_profile = "standard"
        if self.semantic_map and 'services' in self.semantic_map:
            svc_data = self.semantic_map['services'].get(node_id, {})
            resource_profile = svc_data.get('profile', 'standard')

        latency_multiplier = get_profile_multiplier(resource_profile)

        # Effective local processing time
        effective_processing_ms = base_processing_ms * latency_multiplier

        config = {}

        if role == 'service' or role == 'gateway':
            # --- Horizontal Scaling ---
            cpu_per_req_ms = res_prof.cpu_ms_per_request * latency_multiplier
            max_rps_per_pod = min(1000.0 / max(0.1, cpu_per_req_ms), 500.0)

            # Use original Poisson headroom for sync services (it was correct!)
            # phi=0.0 → 4.0x, phi=1.0 → 1.15x
            tuned_replicas = math.ceil((rps / max_rps_per_pod) * headroom)

            # FIXED: Improve min_replicas logic (remove hard 50 RPS cliff)
            # Use gradual scaling based on RPS
            if rps < 5:
                min_replicas = 1  # Very low load
            elif rps < 50:
                min_replicas = 2  # Moderate load, need HA
            else:
                # High load: need more replicas for HA
                # Scale gradually: 50-150 RPS → 3, 150+ → 4
                min_replicas = min(4, 3 + int((rps - 50) / 100))

            config['desired_replicas'] = max(min_replicas, tuned_replicas)

            # --- Vertical Tuning (Threads per Pod) ---
            pod_rps = rps / config['desired_replicas']

            # [FIX 1] Calculate Cumulative Latency (Local + Downstream Wait)
            chain_latency = self._estimate_dependency_latency(node_id, phi)
            total_thread_occupancy_ms = effective_processing_ms + chain_latency

            # Little's Law: Threads = RPS * Total_Time_Thread_Is_Blocked
            concurrency_per_pod = math.ceil(pod_rps * (total_thread_occupancy_ms / 1000.0))

            # Pool Headroom
            pool_headroom = 1.0 + (1.5 * (1.0 - phi))

            # Ensure minimum floor of 10 threads
            config['thread_pool_size'] = max(10, int(concurrency_per_pod * pool_headroom))

            # Only allocate DB connection pool if this service actually connects to a database
            has_db_dependency = any(
                self.graph.nodes[succ].get('role') == 'database'
                for succ in self.graph.successors(node_id)
            )
            if has_db_dependency:
                config['db_connection_pool_capacity'] = max(5, int(config['thread_pool_size'] * 0.8))
            else:
                config['db_connection_pool_capacity'] = 0  # No DB connections needed

            # --- [FIX 2] Strict Timeout Tuning ---
            # Calculate Total Expected Latency (P99 chain + local)
            total_expected_ms = effective_processing_ms + chain_latency

            # STRICT Margin: Max 1.5x (Robust) down to 1.05x (Critical)
            # We do NOT multiply by 3.0 or 4.0 anymore to avoid compounding.
            timeout_margin = 1.05 + (0.45 * (1.0 - phi))

            timeout_sec = (total_expected_ms * timeout_margin) / 1000.0

            config['timeouts'] = {
                'database_call_seconds': max(0.2, timeout_sec),
                'service_call_seconds': max(0.2, timeout_sec),
                'external_api_seconds': max(1.0, timeout_sec * 2)
            }

        elif role == 'database':
            # --- FIX: Database Vertical Scaling based on Client Demand ---

            # 1. Calculate concurrency-based demand (Active Queries)
            system_concurrency = rps * (base_processing_ms / 1000.0)
            base_capacity = int(system_concurrency * headroom * 2)

            # 2. Calculate connection-based demand (Persistent Pools)
            # We MUST support the sum of all configured upstream connection pools
            # ONLY count services that actually connect to this database (predecessors in graph)
            client_demand = 0
            for pred in self.graph.predecessors(node_id):
                # Look up the CONFIG we just generated in Pass 1
                pred_config = existing_configs.get(pred, {})

                client_pool = pred_config.get('db_connection_pool_capacity', 0)

                # Skip services with 0 pool (they don't connect to any DB)
                if client_pool > 0:
                    # Count connections from ALL replicas
                    replicas = pred_config.get('desired_replicas', 1)
                    client_demand += (client_pool * replicas)

            # The DB capacity is the MAX of active query needs or holding open idle connections
            # We add 50 as a safety floor
            total_capacity = max(50, base_capacity, int(client_demand * 1.2))

            config['connection_pool_capacity'] = total_capacity

            # CPU Cores
            queries_per_core = 1000.0 / res_prof.cpu_ms_per_request
            needed_cores = math.ceil((rps / queries_per_core) * headroom)
            config['cpu_cores'] = max(2, int(needed_cores))

        return config

    def _validate_capacity(
        self,
        node_metrics: Dict[str, Any],
        tuned_configs: Dict[str, Dict[str, Any]],
        phi: float
    ) -> bool:
        """
        Analytical validation using queueing theory (M/M/c model).
        Checks if provisioned capacity is sufficient to avoid saturation.
        Returns False if validation fails (system will be unstable at baseline).
        """
        self.validation_warnings = []
        all_valid = True

        for node_id, metrics in node_metrics.items():
            if node_id == 'workload': continue
            if node_id not in self.graph.nodes: continue
            if node_id not in tuned_configs: continue

            role = self.graph.nodes[node_id].get('role', 'service')
            if role not in ['service', 'gateway']: continue

            config = tuned_configs[node_id]
            rps = metrics.get('rps', 0.0)
            if rps <= 0: continue

            # Get processing rate (mu = service rate per replica)
            latency_prof, res_prof = get_component_profile(role)
            base_processing_ms = latency_prof.p50

            # Apply semantic profile
            resource_profile = "standard"
            if self.semantic_map and 'services' in self.semantic_map:
                svc_data = self.semantic_map['services'].get(node_id, {})
                resource_profile = svc_data.get('profile', 'standard')
            latency_multiplier = get_profile_multiplier(resource_profile)

            effective_processing_ms = base_processing_ms * latency_multiplier

            # Service rate per replica (requests per second)
            mu = 1000.0 / max(1.0, effective_processing_ms)

            # Number of replicas (servers in M/M/c model)
            c = config.get('desired_replicas', 1)

            # Total system capacity
            total_capacity = c * mu

            # Utilization (rho)
            rho = rps / total_capacity if total_capacity > 0 else 999.0

            # Check stability
            is_async_consumer = self._is_async_consumer(node_id)

            if rho >= 1.0:
                # Queue will grow unbounded - CRITICAL
                self.validation_warnings.append(
                    f"CRITICAL: {node_id} is UNSTABLE (rho={rho:.2f}≥1.0). "
                    f"RPS={rps:.1f}, capacity={total_capacity:.1f} ({c} × {mu:.1f} req/s). "
                    f"Queue will grow unbounded!"
                )
                all_valid = False

            elif rho >= 0.9:
                # Very high utilization - likely to saturate
                self.validation_warnings.append(
                    f"WARNING: {node_id} near saturation (rho={rho:.2f}). "
                    f"RPS={rps:.1f}, capacity={total_capacity:.1f}. "
                    f"Will likely fail under burst load."
                )
                all_valid = False

            elif rho >= 0.8:
                # High utilization - risky for phi > 0.5
                if phi > 0.5 or is_async_consumer:
                    self.validation_warnings.append(
                        f"WARNING: {node_id} high utilization (rho={rho:.2f}) with phi={phi:.2f}. "
                        f"{'Async consumer ' if is_async_consumer else ''}may struggle with bursts."
                    )
                    # Don't fail, just warn

            else:
                # Utilization is acceptable
                logger.debug(f"✓ {node_id}: rho={rho:.2f}, capacity OK")

            # Additional check for async consumers: thread pool saturation
            if is_async_consumer:
                threads = config.get('thread_pool_size', 10)
                threads_per_replica = threads  # Each replica has full thread pool

                # Thread utilization (using Little's Law)
                chain_latency = self._estimate_dependency_latency(node_id, phi)
                total_latency_sec = (effective_processing_ms + chain_latency) / 1000.0

                required_threads_per_replica = (rps / c) * total_latency_sec
                thread_util = required_threads_per_replica / threads_per_replica if threads_per_replica > 0 else 999.0

                if thread_util >= 0.9:
                    self.validation_warnings.append(
                        f"WARNING: {node_id} thread pool near saturation (util={thread_util:.2f}). "
                        f"Has {threads} threads, needs ~{required_threads_per_replica:.0f} per replica."
                    )
                    # Don't fail for thread saturation, queue will just grow

        return all_valid
