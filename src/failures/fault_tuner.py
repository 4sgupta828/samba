"""
Fault Parameter Tuner - Makes fault injection capacity-aware.

This module scales fault parameters based on node capacity, replicas, and topology
position to ensure faults have meaningful impact regardless of the system's scale.

Key insight: A static 500ms latency fault might be absorbed by a service with
5 replicas and 200 threads, but would cripple a service with 1 replica and 10 threads.
"""
import networkx as nx
from typing import Dict, Any
from src.core.logging_setup import get_logger
from src.validation.component_profiles import get_component_profile


class FaultParameterTuner:
    """
    Tunes fault parameters based on capacity planning results.

    Uses queueing theory and resource saturation principles to ensure
    faults are strong enough to cause visible degradation.

    Formula (for latency-based faults):
        To drive a service to target_utilization:
        required_latency = (thread_pool_size × target_util / RPS) - baseline_latency

    For other fault types, we use heuristics based on capacity and fragility.
    """

    def __init__(
        self,
        nx_graph: nx.DiGraph,
        capacity_configs: Dict[str, Dict[str, Any]],
        target_rps: float
    ):
        """
        Initialize the fault tuner.

        Args:
            nx_graph: Topology graph
            capacity_configs: Output from CapacityPlanner (tuned node configs)
            target_rps: Global target RPS

        Note: No phi parameter! Phi is already factored into capacity planning
        (thread pools, replicas, timeouts). Using it again would be double-counting.
        """
        self.graph = nx_graph
        self.capacity_configs = capacity_configs
        self.target_rps = target_rps
        self.logger = get_logger(__name__)

        # Track current target node for profile lookup
        self.current_target_node = None

        # Target utilization strategy (capacity-relative, no phi):
        # We calculate baseline utilization from capacity planning, then
        # consume 75% of available headroom to show visible fault impact
        # without causing catastrophic queue explosion
        self.headroom_consumption = 0.75  # Use 75% of available headroom

    def tune_fault_parameters(
        self,
        target_node_id: str,
        fault_type: str,
        baseline_params: Dict[str, Any],
        severity: float = 0.5,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Tune fault parameters for a specific node based on its capacity.

        Args:
            target_node_id: Node to inject fault into
            fault_type: Type of fault (e.g., 'cpu_saturation', 'inject_latency')
            baseline_params: Original fault parameters from scenario library
            severity: Fault intensity [0.0-1.0], default 0.5 (balanced)
                     0.0-0.3: Subtle, 0.3-0.7: Moderate, 0.7-1.0: Severe
            verbose: Print tuning details

        Returns:
            Tuned fault parameters including severity
        """
        # Store current target for profile lookup
        self.current_target_node = target_node_id

        # Get node configuration
        if target_node_id not in self.capacity_configs:
            if verbose:
                self.logger.warning(f"Node {target_node_id} not in capacity configs, using baseline params")
            return baseline_params

        node_config = self.capacity_configs[target_node_id]
        node_role = self.graph.nodes[target_node_id].get('role', 'service')

        # Get node metrics
        replicas = node_config.get('desired_replicas', 1)
        threads_per_replica = node_config.get('thread_pool_size', 10)

        # For databases, use connection_pool_capacity as the thread pool size
        # Databases don't have replicas or thread_pool_size in the same way services do
        if node_role == 'database':
            # Database thread pool = connection pool capacity (or cpu_cores * multiplier)
            connection_pool_capacity = node_config.get('connection_pool_capacity', None)
            cpu_cores = node_config.get('cpu_cores', None)

            if connection_pool_capacity:
                total_threads = connection_pool_capacity
            elif cpu_cores:
                # Estimate connection pool from CPU cores (typical ratio: 25-50 connections per core)
                total_threads = cpu_cores * 25
            else:
                # Fallback to default
                total_threads = 50
        else:
            # For services/pods, use replicas * thread_pool_size
            total_threads = replicas * threads_per_replica

        # Estimate node RPS (rough heuristic based on topology position)
        node_rps = self._estimate_node_rps(target_node_id)

        if verbose:
            print(f"\n[Fault Parameter Tuning]")
            print(f"  Target: {target_node_id} ({node_role})")
            print(f"  Fault type: {fault_type}")
            print(f"  Severity: {severity:.2f} ({'subtle' if severity < 0.3 else 'moderate' if severity < 0.7 else 'severe'})")
            if node_role == 'database':
                print(f"  Capacity: connection_pool={node_config.get('connection_pool_capacity', 'N/A')}, cpu_cores={node_config.get('cpu_cores', 'N/A')}")
                print(f"  Total threads/connections: {total_threads}")
            else:
                print(f"  Capacity: {replicas} replicas × {threads_per_replica} threads = {total_threads} total threads")
            print(f"  Estimated RPS: {node_rps:.1f}")
            print(f"  Strategy: Capacity-relative (no phi, {self.headroom_consumption*100:.0f}% base headroom)")

        # Tune parameters based on fault type
        tuned_params = baseline_params.copy()

        if fault_type in ['inject_latency', 'cpu_saturation', 'queue_consumer_slowdown']:
            tuned_params = self._tune_latency_fault(
                baseline_params, total_threads, node_rps, severity, verbose
            )

        elif fault_type == 'inject_errors':
            tuned_params = self._tune_error_rate_fault(
                baseline_params, replicas, severity, verbose
            )

        elif fault_type == 'memory_leak':
            tuned_params = self._tune_memory_leak_fault(
                baseline_params, total_threads, node_rps, severity, verbose
            )

        elif fault_type == 'memory_pressure':
            tuned_params = self._tune_memory_pressure_fault(
                baseline_params, node_config, severity, verbose
            )

        elif fault_type == 'memory_thrashing':
            tuned_params = self._tune_memory_thrashing_fault(
                baseline_params, node_config, severity, verbose
            )

        elif fault_type == 'thread_exhaustion':
            tuned_params = self._tune_thread_exhaustion_fault(
                baseline_params, total_threads, node_rps, severity, verbose
            )

        elif fault_type == 'disk_io_saturation':
            tuned_params = self._tune_disk_io_saturation_fault(
                baseline_params, node_config, node_rps, severity, verbose
            )

        elif fault_type == 'force_deadlock':
            tuned_params = self._tune_deadlock_fault(
                baseline_params, threads_per_replica, severity, verbose
            )

        elif fault_type == 'hot_shard':
            tuned_params = self._tune_hot_shard_fault(
                baseline_params, replicas, severity, verbose
            )

        elif fault_type == 'cache_failure':
            tuned_params = self._tune_cache_failure_fault(
                baseline_params, severity, verbose
            )

        elif fault_type == 'noisy_neighbor':
            tuned_params = self._tune_noisy_neighbor_fault(
                baseline_params, node_config, severity, verbose
            )

        elif fault_type in ['slow_queries', 'connection_exhaustion']:
            # Database faults - estimate based on client connection pools
            tuned_params = self._tune_database_fault(
                target_node_id, baseline_params, severity, verbose
            )

        else:
            # Unknown fault type - use baseline params
            if verbose:
                print(f"  ℹ️  No tuning heuristic for '{fault_type}', using baseline params")

        if verbose:
            print(f"  Baseline params: {baseline_params}")
            print(f"  Tuned params: {tuned_params}")

        return tuned_params

    def _tune_latency_fault(
        self,
        baseline_params: Dict[str, Any],
        total_threads: int,
        node_rps: float,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune latency-based and CPU faults using queueing theory and actual component profiles.

        Uses ACTUAL baseline latency from component profiles, not assumptions.

        For CPU saturation (first principles):
            We want: utilization = target_util
            Currently: utilization = (RPS × base_latency) / threads
            To reach target: need CPU_multiplier such that:
                (RPS × base_latency × CPU_multiplier) / threads = target_util
                → CPU_multiplier = (threads × target_util) / (RPS × base_latency)

        For inject_latency faults:
            utilization = (RPS × latency) / thread_pool_size
            → latency = (thread_pool_size × target_util) / RPS
        """
        tuned = baseline_params.copy()

        if node_rps < 1.0 or total_threads < 1:
            # Very low traffic or no threads - use baseline params
            return tuned

        # Get ACTUAL baseline latency from component profile (not an assumption!)
        node_role = self.graph.nodes.get(self.current_target_node, {}).get('role', 'service')
        try:
            latency_profile, _ = get_component_profile(node_role)
            baseline_latency_ms = latency_profile.p50  # Use p50 as baseline
        except:
            # Fallback if profile not found
            baseline_latency_ms = 100.0

        baseline_latency_sec = baseline_latency_ms / 1000.0

        # Calculate current baseline utilization using Little's Law
        # Utilization = (Arrival Rate × Service Time) / Servers
        current_util = (node_rps * baseline_latency_sec) / total_threads

        # Calculate target utilization (capacity-relative, no phi!)
        # Scale headroom consumption by severity
        # severity=0.5 → 75% headroom, severity=1.0 → ~100% headroom
        scaled_headroom_consumption = self._scale_by_severity(self.headroom_consumption, severity)

        available_headroom = 1.0 - current_util
        target_util = current_util + (available_headroom * scaled_headroom_consumption)

        # Calculate required CPU multiplier to reach target utilization
        if current_util > 0:
            required_cpu_multiplier = target_util / current_util
        else:
            required_cpu_multiplier = 2.0  # Default if can't calculate

        # Apply bounds
        # Min: 1.5x (subtle but noticeable)
        # Max: 5.0x (severe but not infinite)
        required_cpu_multiplier = max(1.5, min(5.0, required_cpu_multiplier))

        # Update cpu_multiplier for cpu_saturation faults
        if 'cpu_multiplier' in tuned:
            tuned['cpu_multiplier'] = required_cpu_multiplier

        # For inject_latency faults, calculate added latency
        if 'latency_ms' in tuned:
            # Calculate latency to reach target utilization
            required_total_latency_sec = (total_threads * self.target_utilization) / node_rps
            required_added_latency_ms = max(0, (required_total_latency_sec - baseline_latency_sec) * 1000)
            # Bound to reasonable range
            required_added_latency_ms = max(200.0, min(1000.0, required_added_latency_ms))
            tuned['latency_ms'] = int(required_added_latency_ms)

        if verbose:
            print(f"  Fault tuning:")
            print(f"    Baseline latency (from profile): {baseline_latency_ms:.1f}ms")
            print(f"    Baseline utilization: {current_util*100:.1f}%")
            print(f"    Available headroom: {available_headroom*100:.1f}%")
            print(f"    Target utilization: {target_util*100:.1f}% (baseline + {self.headroom_consumption*100:.0f}% of headroom)")
            if 'cpu_multiplier' in tuned:
                print(f"    CPU multiplier: {required_cpu_multiplier:.2f}x")
            if 'latency_ms' in tuned:
                print(f"    Added latency: {tuned['latency_ms']}ms")

        return tuned

    def _tune_error_rate_fault(
        self,
        baseline_params: Dict[str, Any],
        replicas: int,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune error rate based on number of replicas and severity.

        More replicas = need higher error rate to cause visible impact
        (load balancer can route around a single failing replica)
        """
        tuned = baseline_params.copy()

        if 'error_rate' not in tuned:
            return tuned

        baseline_error_rate = tuned['error_rate']

        # Scale error rate based on replicas
        # With 1 replica: use baseline
        # With 5 replicas: need ~2x error rate to have same impact
        replica_multiplier = 1.0 + (0.2 * (replicas - 1))

        # Scale by severity using non-linear function
        scaled_error_rate = self._scale_by_severity(baseline_error_rate, severity)

        tuned_error_rate = scaled_error_rate * replica_multiplier

        # Bounds: 10% to 80% error rate
        tuned_error_rate = max(0.10, min(0.80, tuned_error_rate))

        tuned['error_rate'] = tuned_error_rate

        if verbose:
            print(f"  Error rate tuning:")
            print(f"    Baseline: {baseline_error_rate:.1%}")
            print(f"    Severity scaling: {scaled_error_rate:.1%}")
            print(f"    Replica multiplier: {replica_multiplier:.2f}x")
            print(f"    Final: {tuned_error_rate:.1%}")

        return tuned

    def _tune_memory_leak_fault(
        self,
        baseline_params: Dict[str, Any],
        total_threads: int,
        node_rps: float,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune memory leak rate based on request throughput and severity.

        Goal: Cause OOM within reasonable time (~60-120s)
        Severity controls how quickly memory pressure builds.
        """
        tuned = baseline_params.copy()

        if 'leak_mb_per_request' not in tuned:
            return tuned

        baseline_leak = tuned['leak_mb_per_request']

        # Estimate requests processed in 90 seconds
        requests_in_90s = node_rps * 90.0

        # Assume pod has ~1000MB memory budget before OOM
        # Scale target by severity (subtle: 400MB, moderate: 700MB, severe: 950MB)
        base_target_mb = 700.0
        target_total_leak_mb = self._scale_by_severity(base_target_mb, severity)

        tuned_leak = target_total_leak_mb / requests_in_90s if requests_in_90s > 0 else baseline_leak

        # Bounds: 0.1 to 2.0 MB per request
        tuned_leak = max(0.1, min(2.0, tuned_leak))

        tuned['leak_mb_per_request'] = tuned_leak

        if verbose:
            print(f"  Memory leak tuning:")
            print(f"    Requests in 90s: {requests_in_90s:.0f}")
            print(f"    Target leak (severity scaled): {target_total_leak_mb:.0f}MB")
            print(f"    Leak rate: {tuned_leak:.2f} MB/request")

        return tuned

    def _tune_deadlock_fault(
        self,
        baseline_params: Dict[str, Any],
        threads_per_replica: int,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune deadlock thread percentage based on severity.

        Goal: Lock enough threads to cause visible contention but not total deadlock.
        Severity controls what percentage of threads are locked.
        """
        tuned = baseline_params.copy()

        if 'thread_percentage' not in tuned:
            return tuned

        # Base lock percentage: 70%
        # Scale by severity: subtle (40-60%), moderate (60-80%), severe (80-90%)
        base_lock_percentage = 0.70
        target_lock_percentage = self._scale_by_severity(base_lock_percentage, severity)

        # Bounds: 40% to 90%
        target_lock_percentage = max(0.40, min(0.90, target_lock_percentage))

        tuned['thread_percentage'] = target_lock_percentage

        if verbose:
            print(f"  Deadlock tuning:")
            print(f"    Thread pool size: {threads_per_replica}")
            print(f"    Lock percentage: {target_lock_percentage:.1%}")
            print(f"    → {int(threads_per_replica * target_lock_percentage)} threads locked per replica")

        return tuned

    def _tune_hot_shard_fault(
        self,
        baseline_params: Dict[str, Any],
        replicas: int,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune hot shard skew factor based on replica count and severity.

        With more replicas, a single hot shard is less impactful.
        Severity controls how much traffic is skewed to the hot shard.
        """
        tuned = baseline_params.copy()

        if 'skew_factor' not in tuned:
            return tuned

        # Scale skew factor based on replicas
        # With 1 replica: hot shard doesn't make sense (only one target)
        # With 3 replicas: 80% to one = very hot
        # With 5 replicas: need 90% to one to have similar impact

        if replicas <= 1:
            # Hot shard requires multiple replicas
            return tuned

        # Target: Route (1 - 1/N) of traffic to hot shard, where N = replicas
        balanced_fraction = 1.0 / replicas  # What each replica should get
        base_skew = 1.0 - balanced_fraction + 0.10  # Add 10% base extra skew

        # Scale by severity
        skew_factor = self._scale_by_severity(base_skew, severity)

        # Bounds: 0.6 to 0.95
        skew_factor = max(0.60, min(0.95, skew_factor))

        tuned['skew_factor'] = skew_factor

        if verbose:
            print(f"  Hot shard tuning:")
            print(f"    Replicas: {replicas}")
            print(f"    Balanced fraction: {balanced_fraction:.1%}")
            print(f"    Skew factor: {skew_factor:.1%}")

        return tuned

    def _tune_database_fault(
        self,
        target_node_id: str,
        baseline_params: Dict[str, Any],
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune database faults based on client connection pool sizes and severity.

        For DB faults to be impactful, they need to saturate client connection pools.
        Severity controls how aggressively we degrade database performance.
        """
        tuned = baseline_params.copy()

        # Find all services that connect to this database
        client_services = [
            src for src, tgt in self.graph.edges()
            if tgt == target_node_id and self.graph.nodes[src].get('role') == 'service'
        ]

        if not client_services:
            return tuned

        # Sum up total client connection pool capacity
        total_client_connections = 0
        for client in client_services:
            if client in self.capacity_configs:
                client_config = self.capacity_configs[client]
                replicas = client_config.get('desired_replicas', 1)
                conns_per_replica = client_config.get('db_connection_pool_capacity', 10)
                total_client_connections += replicas * conns_per_replica

        if verbose:
            print(f"  Database fault tuning:")
            print(f"    Connected clients: {len(client_services)}")
            print(f"    Total client connections: {total_client_connections}")

        # For slow_queries: Set latency to saturate connections
        if 'wear_factor' in tuned:
            # Wear factor controls query latency multiplier
            # Base: 0.5 (moderate), scale by severity and connection pool size
            base_wear = 0.5 + (total_client_connections / 200.0)
            wear_factor = self._scale_by_severity(base_wear, severity)

            # Bounds: 0.4 to 0.9
            wear_factor = max(0.4, min(0.9, wear_factor))
            tuned['wear_factor'] = wear_factor

            if verbose:
                print(f"    Wear factor: {wear_factor:.2f}")

        return tuned

    def _scale_by_severity(self, base_value: float, severity: float) -> float:
        """
        Scale a parameter by severity with non-linear progression.

        Severity scaling (non-linear):
        - 0.0-0.3: Subtle issues (linear, 0-60% of base)
        - 0.3-0.7: Moderate issues (near-linear, 60-100% of base)
        - 0.7-1.0: Severe issues (exponential, 100-130% of base)

        Args:
            base_value: Base parameter value (e.g., 0.75 for headroom consumption)
            severity: Fault intensity [0.0-1.0]

        Returns:
            Scaled value
        """
        if severity < 0.3:
            # Subtle: linear scaling from 0 to 60% of base
            factor = (severity / 0.3) * 0.6
        elif severity < 0.7:
            # Moderate: linear from 60% to 100% of base
            normalized = (severity - 0.3) / 0.4
            factor = 0.6 + (normalized * 0.4)
        else:
            # Severe: exponential from 100% to 130% of base
            normalized = (severity - 0.7) / 0.3
            factor = 1.0 + (normalized ** 1.5) * 0.3

        return base_value * factor

    def _estimate_node_rps(self, node_id: str) -> float:
        """
        Estimate RPS for a node based on topology position.

        Heuristic:
        - Frontend services: ~global_rps
        - Mid-tier services: ~global_rps / depth
        - Databases: Sum of client RPS * query_rate
        """
        is_frontend = self.graph.nodes[node_id].get('is_frontend', False)

        if is_frontend:
            return self.target_rps

        # Count predecessors (services that call this node)
        predecessors = list(self.graph.predecessors(node_id))

        if not predecessors:
            # No predecessors = likely a frontend or isolated node
            return self.target_rps * 0.5

        # Rough heuristic: RPS = global_rps / (number of predecessors + 1)
        # This assumes traffic is split across downstream services
        estimated_rps = self.target_rps / (len(predecessors) + 1.0)

        return estimated_rps

    def _tune_disk_io_saturation_fault(
        self,
        baseline_params: Dict[str, Any],
        node_config: Dict[str, Any],
        node_rps: float,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune disk I/O saturation I/O wait time based on database capacity.

        Key insight: I/O saturation is capacity-relative. A database with 1000 connection
        pool and high RPS can absorb higher I/O latency than a small database.

        CRITICAL CONSTRAINT: Must prevent congestion collapse!
        - I/O wait that's too high creates massive queue buildup (e.g., 886/1065 connections stuck)
        - Once in congestion collapse, system CANNOT recover naturally
        - Even with fault removed, CPU stays at 100%, dynamics computes target_latency > 10,000ms
        - System stays stuck at latency_max forever

        Strategy:
        - Calculate baseline query latency and throughput capacity
        - Scale I/O wait to push utilization toward saturation without total collapse
        - Use VERY conservative bounds to prevent queue explosion
        - Severity controls how close to saturation we get
        """
        tuned = baseline_params.copy()

        # Get database capacity metrics
        connection_pool = node_config.get('connection_pool_capacity', 100)

        # Get baseline latency from component profile
        node_role = self.graph.nodes.get(self.current_target_node, {}).get('role', 'database')
        try:
            latency_profile, _ = get_component_profile(node_role)
            baseline_latency_ms = latency_profile.p50
        except:
            baseline_latency_ms = 20.0  # Fallback for databases

        # Calculate baseline utilization
        # Utilization = (RPS × Latency) / Capacity
        baseline_latency_sec = baseline_latency_ms / 1000.0
        if node_rps > 0 and connection_pool > 0:
            baseline_util = (node_rps * baseline_latency_sec) / connection_pool
        else:
            baseline_util = 0.3  # Conservative default

        # Target utilization: consume headroom based on severity
        scaled_headroom = self._scale_by_severity(self.headroom_consumption, severity)
        available_headroom = max(0.1, 1.0 - baseline_util)
        target_util = min(0.95, baseline_util + (available_headroom * scaled_headroom))

        # Calculate required I/O wait to reach target utilization
        # target_util = (RPS × (baseline_latency + io_wait)) / connection_pool
        # → io_wait = (connection_pool × target_util / RPS) - baseline_latency
        if node_rps > 0:
            required_total_latency_sec = (connection_pool * target_util) / node_rps
            io_wait_sec = max(0, required_total_latency_sec - baseline_latency_sec)
            io_wait_ms = io_wait_sec * 1000
        else:
            # Fallback: use severity-based scaling
            io_wait_ms = baseline_latency_ms * self._scale_by_severity(3.0, severity)

        # Apply bounds based on severity
        # CRITICAL: These bounds must be EXTREMELY conservative for capacity-limited systems
        # Even "moderate" severity should allow recovery, not cause total collapse
        # After testing: 200ms still causes congestion collapse on capacity-limited systems
        # Reduced by 50% to prevent queue explosion
        # Subtle (0.0-0.3): 10-40ms (0.5x-2x baseline 20ms latency)
        # Moderate (0.3-0.7): 40-100ms (2x-5x baseline)
        # Severe (0.7-1.0): 100-250ms (5x-12.5x baseline)
        if severity < 0.3:
            io_wait_ms = max(10.0, min(40.0, io_wait_ms))
        elif severity < 0.7:
            io_wait_ms = max(40.0, min(100.0, io_wait_ms))
        else:
            io_wait_ms = max(100.0, min(250.0, io_wait_ms))

        tuned['severity'] = severity
        # Always set io_wait_ms to override the fault implementation's internal calculation
        tuned['io_wait_ms'] = io_wait_ms

        if verbose:
            print(f"  Disk I/O saturation tuning:")
            print(f"    Connection pool: {connection_pool}")
            print(f"    Baseline latency: {baseline_latency_ms:.1f}ms")
            print(f"    Baseline utilization: {baseline_util*100:.1f}%")
            print(f"    Target utilization: {target_util*100:.1f}%")
            print(f"    I/O wait: {io_wait_ms:.1f}ms")

        return tuned

    def _tune_thread_exhaustion_fault(
        self,
        baseline_params: Dict[str, Any],
        total_threads: int,
        node_rps: float,
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune thread exhaustion based on thread pool size, RPS, and baseline utilization.

        Key insight: Must account for baseline utilization!
        Exhausting 30% of capacity means nothing if baseline is only 10%.
        We need to exhaust enough to push total utilization to target level.

        Formula:
        - Estimate baseline_util from RPS and latency
        - Calculate target_util from severity
        - Exhaust: target_util - baseline_util (as % of capacity)
        """
        tuned = baseline_params.copy()

        if total_threads < 1:
            return tuned

        # Step 1: Estimate baseline utilization
        # For databases: utilization ≈ (RPS × avg_query_time) / capacity
        # For services: utilization ≈ (RPS × avg_latency) / capacity
        # Use conservative estimate: assume ~10-15ms per operation
        avg_operation_time_ms = 10.0  # Conservative estimate
        baseline_util = (node_rps * avg_operation_time_ms / 1000.0) / total_threads
        baseline_util = max(0.0, min(0.5, baseline_util))  # Clamp to 0-50% (sanity check)

        # Step 2: Calculate target utilization based on severity
        # Severity 0.0 → 40% utilization (subtle)
        # Severity 0.5 → 70% utilization (moderate)
        # Severity 1.0 → 95% utilization (severe)
        if severity < 0.3:
            # Subtle: 40-60% utilization
            target_util = 0.40 + (severity / 0.3) * 0.20
        elif severity < 0.7:
            # Moderate: 60-85% utilization
            normalized = (severity - 0.3) / 0.4
            target_util = 0.60 + (normalized * 0.25)
        else:
            # Severe: 85-95% utilization
            normalized = (severity - 0.7) / 0.3
            target_util = 0.85 + (normalized * 0.10)

        # Step 3: Calculate exhaustion needed
        # Need to exhaust: (target - baseline) as % of total capacity
        exhaustion_pct = target_util - baseline_util
        exhaustion_pct = max(0.10, min(0.85, exhaustion_pct))  # Ensure reasonable bounds

        exhausted_threads = int(total_threads * exhaustion_pct)
        exhausted_threads = max(1, exhausted_threads)  # At least 1 thread

        tuned['exhausted_threads'] = exhausted_threads
        tuned['severity'] = severity

        if verbose:
            print(f"  Thread exhaustion tuning (baseline-aware):")
            print(f"    Total threads/connections: {total_threads}")
            print(f"    Estimated RPS: {node_rps:.1f}")
            print(f"    Estimated baseline utilization: {baseline_util*100:.1f}%")
            print(f"    Target utilization (severity={severity:.2f}): {target_util*100:.1f}%")
            print(f"    Exhaustion needed: {exhaustion_pct*100:.1f}%")
            print(f"    Exhausted threads: {exhausted_threads}")
            print(f"    Expected total utilization: {(baseline_util + exhaustion_pct)*100:.1f}%")
            print(f"    Remaining free capacity: {total_threads - exhausted_threads - int(baseline_util * total_threads)} threads")

        return tuned

    def _tune_memory_pressure_fault(
        self,
        baseline_params: Dict[str, Any],
        node_config: Dict[str, Any],
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune memory pressure based on pod memory limits and severity.

        Memory pressure increases memory allocation, pushing toward OOM.
        """
        tuned = baseline_params.copy()

        # Memory pressure is primarily controlled by severity
        # The fault implementation scales memory_multiplier internally
        tuned['severity'] = severity

        if verbose:
            print(f"  Memory pressure tuning:")
            print(f"    Severity: {severity:.2f}")
            print(f"    Note: Memory pressure scales internally based on severity")

        return tuned

    def _tune_memory_thrashing_fault(
        self,
        baseline_params: Dict[str, Any],
        node_config: Dict[str, Any],
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune memory thrashing (memory + swap saturation) based on severity.

        Memory thrashing causes page faults and swap I/O, degrading performance.
        """
        tuned = baseline_params.copy()

        # Memory thrashing is controlled by severity
        # Higher severity = more aggressive thrashing
        tuned['severity'] = severity

        if verbose:
            print(f"  Memory thrashing tuning:")
            print(f"    Severity: {severity:.2f}")
            print(f"    Note: Memory thrashing scales internally based on severity")

        return tuned

    def _tune_cache_failure_fault(
        self,
        baseline_params: Dict[str, Any],
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune cache failure based on severity.

        Cache failure is binary (cache up/down) but we can control error rate.
        Severity affects how often cache operations fail.
        """
        tuned = baseline_params.copy()

        # Cache failure can have partial failures based on severity
        # severity=0.5 → 50% of cache ops fail, rest fall back to DB
        # severity=1.0 → 100% cache ops fail
        cache_error_rate = self._scale_by_severity(0.50, severity)
        cache_error_rate = max(0.30, min(1.0, cache_error_rate))

        tuned['error_rate'] = cache_error_rate
        tuned['severity'] = severity

        if verbose:
            print(f"  Cache failure tuning:")
            print(f"    Severity: {severity:.2f}")
            print(f"    Cache error rate: {cache_error_rate*100:.0f}%")

        return tuned

    def _tune_noisy_neighbor_fault(
        self,
        baseline_params: Dict[str, Any],
        node_config: Dict[str, Any],
        severity: float,
        verbose: bool
    ) -> Dict[str, Any]:
        """
        Tune noisy neighbor CPU pinning based on severity.

        Noisy neighbor pins CPU to high percentage, causing contention.
        Severity controls how much CPU the noisy neighbor consumes.
        """
        tuned = baseline_params.copy()

        # Scale CPU pinning percentage based on severity
        # Subtle (0.3): 60-70% CPU
        # Moderate (0.5): 80-90% CPU
        # Severe (1.0): 95-100% CPU
        if severity < 0.3:
            cpu_percent = 60.0 + (severity / 0.3) * 10.0
        elif severity < 0.7:
            cpu_percent = 70.0 + ((severity - 0.3) / 0.4) * 20.0
        else:
            cpu_percent = 90.0 + ((severity - 0.7) / 0.3) * 10.0

        cpu_percent = max(60.0, min(100.0, cpu_percent))

        tuned['cpu_percent'] = cpu_percent
        tuned['severity'] = severity

        if verbose:
            print(f"  Noisy neighbor tuning:")
            print(f"    Severity: {severity:.2f}")
            print(f"    CPU pinning: {cpu_percent:.0f}%")

        return tuned
