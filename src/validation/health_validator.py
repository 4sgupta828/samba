"""
Mathematical Health Validator

Validates system health using queueing theory and rigorous mathematical criteria.
Based on Little's Law, utilization theory, and real-world component profiles.
"""
import json
from pathlib import Path
from typing import Dict, Tuple, List, Optional

try:
    import networkx as nx
except ImportError:
    # Fallback if networkx not available
    nx = None

from .component_profiles import (
    get_component_profile,
    get_network_latency,
    calculate_end_to_end_latency,
    estimate_component_capacity,
    COMPONENT_LATENCY_PROFILES,
)


class HealthMetrics:
    """Container for node-level health metrics including pod-level resources."""

    def __init__(self):
        # Request-level metrics
        self.incoming_rps: List[float] = []
        self.latency_p50: List[float] = []
        self.latency_p90: List[float] = []
        self.latency_p99: List[float] = []
        self.success_count: List[float] = []
        self.failure_count: List[float] = []
        self.circuit_breaker_opens: int = 0

        # Pod-level resource metrics (NEW)
        self.cpu_util: List[float] = []
        self.mem_util: List[float] = []
        self.mem_usage_mb: List[float] = []

        # Pod-level thread pool metrics (NEW)
        self.thread_pool_active: List[float] = []
        self.thread_pool_queue_depth: List[float] = []

        # Pod-level connection pool metrics (NEW)
        self.connection_pool_active: List[float] = []
        self.connection_pool_queue_depth: List[float] = []

    @property
    def avg_rps(self) -> float:
        return sum(self.incoming_rps) / len(self.incoming_rps) if self.incoming_rps else 0.0

    @property
    def avg_latency_p50(self) -> float:
        return sum(self.latency_p50) / len(self.latency_p50) if self.latency_p50 else 0.0

    @property
    def avg_latency_p99(self) -> float:
        return sum(self.latency_p99) / len(self.latency_p99) if self.latency_p99 else 0.0

    @property
    def total_requests(self) -> float:
        return sum(self.success_count) + sum(self.failure_count)

    @property
    def error_rate(self) -> float:
        total = self.total_requests
        return sum(self.failure_count) / total if total > 0 else 0.0

    @property
    def success_rate(self) -> float:
        total = self.total_requests
        return sum(self.success_count) / total if total > 0 else 0.0

    # Pod-level metric helpers (NEW)
    @property
    def avg_cpu_util(self) -> float:
        return sum(self.cpu_util) / len(self.cpu_util) if self.cpu_util else 0.0

    @property
    def max_cpu_util(self) -> float:
        return max(self.cpu_util) if self.cpu_util else 0.0

    @property
    def avg_mem_usage_mb(self) -> float:
        return sum(self.mem_usage_mb) / len(self.mem_usage_mb) if self.mem_usage_mb else 0.0

    @property
    def max_mem_usage_mb(self) -> float:
        return max(self.mem_usage_mb) if self.mem_usage_mb else 0.0

    @property
    def avg_thread_pool_active(self) -> float:
        return sum(self.thread_pool_active) / len(self.thread_pool_active) if self.thread_pool_active else 0.0

    @property
    def max_thread_pool_active(self) -> float:
        return max(self.thread_pool_active) if self.thread_pool_active else 0.0

    @property
    def avg_thread_pool_queue_depth(self) -> float:
        return sum(self.thread_pool_queue_depth) / len(self.thread_pool_queue_depth) if self.thread_pool_queue_depth else 0.0

    @property
    def max_thread_pool_queue_depth(self) -> float:
        return max(self.thread_pool_queue_depth) if self.thread_pool_queue_depth else 0.0

    @property
    def avg_connection_pool_active(self) -> float:
        return sum(self.connection_pool_active) / len(self.connection_pool_active) if self.connection_pool_active else 0.0

    @property
    def max_connection_pool_active(self) -> float:
        return max(self.connection_pool_active) if self.connection_pool_active else 0.0

    @property
    def avg_connection_pool_queue_depth(self) -> float:
        return sum(self.connection_pool_queue_depth) / len(self.connection_pool_queue_depth) if self.connection_pool_queue_depth else 0.0

    @property
    def max_connection_pool_queue_depth(self) -> float:
        return max(self.connection_pool_queue_depth) if self.connection_pool_queue_depth else 0.0


def analyze_request_routing_distribution(topology, workload_config_path: str = None) -> Dict:
    """
    Analyze how requests are distributed across the topology based on:
    1. Workload request mix (weights for each request type)
    2. Gateway routing (which services handle which request types)
    3. Service processing pipelines (probabilistic dependencies)

    This provides a more accurate capacity estimate than assuming all requests
    go through the slowest path.

    Args:
        topology: Topology graph or dict
        workload_config_path: Path to workload config YAML (optional)

    Returns:
        Dictionary with routing distribution analysis
    """
    import yaml
    from pathlib import Path

    # Handle both NetworkX graph and dict representation
    if nx and isinstance(topology, nx.DiGraph):
        nodes = dict(topology.nodes(data=True))
    else:
        nodes = {n['id']: n for n in topology.get('nodes', [])}

    # Find gateway
    gateway_id = None
    for node_id, attrs in nodes.items():
        if attrs.get('role') == 'gateway':
            gateway_id = node_id
            break

    if not gateway_id:
        return {'error': 'No gateway found in topology'}

    # Load workload config if provided
    request_mix = {}
    if workload_config_path and Path(workload_config_path).exists():
        try:
            with open(workload_config_path, 'r') as f:
                workload_config = yaml.safe_load(f)
                # Extract request mix weights (accumulate by type)
                for item in workload_config.get('request_mix', []):
                    request_type = item.get('type', 'GET')
                    weight = item.get('weight', 1)
                    request_mix[request_type] = request_mix.get(request_type, 0) + weight

            # Normalize weights to probabilities
            total_weight = sum(request_mix.values())
            if total_weight > 0:
                request_mix = {k: v / total_weight for k, v in request_mix.items()}
        except Exception as e:
            print(f"Warning: Could not load workload config: {e}")
            request_mix = {'GET': 1.0}  # Default
    else:
        # Default uniform distribution
        request_mix = {'GET': 1.0}

    # Analyze service pipelines to estimate dependency call probabilities
    service_routing = {}
    for node_id, attrs in nodes.items():
        if attrs.get('role') == 'service':
            pipeline = attrs.get('processing_pipeline') or []  # Handle None case

            # Calculate probabilities for each step type
            has_cache = any(step.get('type') == 'cache_check' for step in pipeline)
            has_db = any(step.get('type') == 'db_query' for step in pipeline)
            has_service_calls = any(step.get('type') == 'service_calls' for step in pipeline)
            has_external_calls = any(step.get('type') == 'external_calls' for step in pipeline)

            # Get probabilities
            service_calls_prob = next(
                (step.get('probability', 1.0) for step in pipeline if step.get('type') == 'service_calls'),
                0.0
            )
            external_calls_prob = next(
                (step.get('probability', 1.0) for step in pipeline if step.get('type') == 'external_calls'),
                0.0
            )

            service_routing[node_id] = {
                'has_cache': has_cache,
                'has_db': has_db,
                'calls_services': has_service_calls,
                'calls_external': has_external_calls,
                'service_calls_probability': service_calls_prob,
                'external_calls_probability': external_calls_prob,
            }

    return {
        'request_mix': request_mix,
        'service_routing': service_routing,
        'gateway_id': gateway_id,
        'num_services': len(service_routing),
    }


def validate_workload_generator_sizing(
    target_rps: float,
    latency_seconds: float,
    workload_pool_size: int
) -> Dict[str, any]:
    """
    Validate that the workload generator is sized to support the topology's capacity.

    The workload generator is NOT a constraint on the topology - it's a test harness
    that should be configured to support whatever RPS the topology can handle.

    Args:
        target_rps: Target RPS the topology can handle
        latency_seconds: End-to-end latency (p99)
        workload_pool_size: Actual workload generator connection pool size

    Returns:
        Dictionary with validation status and sizing recommendations
    """
    # Using Little's Law: N = λ × W
    # Add 1.5x safety factor for bursts and variance
    required_pool_size = int(target_rps * latency_seconds * 1.5)

    is_adequate = workload_pool_size >= required_pool_size
    utilization = (required_pool_size / workload_pool_size * 100) if workload_pool_size > 0 else float('inf')

    validation = {
        'is_adequate': is_adequate,
        'current_pool_size': workload_pool_size,
        'required_pool_size': required_pool_size,
        'utilization_pct': min(utilization, 100.0),
        'recommendation': 'OK' if is_adequate else f'Increase workload generator connection pool to {required_pool_size}'
    }

    if not is_adequate:
        validation['warning'] = (
            f"Workload generator undersized: has {workload_pool_size} connections, "
            f"needs {required_pool_size} for {target_rps:.0f} RPS at {latency_seconds*1000:.0f}ms latency. "
            f"Test results may be invalid."
        )

    return validation


def calculate_safe_workload(topology, target_utilization: float = 0.70, workload_config_path: str = None) -> Dict:
    """
    Calculate the maximum safe workload for a given topology using queueing theory
    and realistic component profiles, INCLUDING resource pool constraints.

    Algorithm:
    1. Read simulation config to get thread pool, connection pool sizes
    2. Find all paths from gateway to leaf nodes
    3. For each path, calculate end-to-end latency using component profiles
    4. For each node in path, estimate capacity based on component type AND pool constraints
    5. Find bottleneck node (lowest capacity considering ALL constraints)
    6. Calculate safe RPS = min(bottleneck_capacity) × target_utilization

    Args:
        topology: NetworkX directed graph or dict with nodes/edges
        target_utilization: Target utilization threshold (0.0-1.0)

    Returns:
        Dictionary with safe workload parameters including bottleneck analysis
    """
    # Import here to avoid circular dependencies
    from src.core.simulation_config import get_simulation_config

    # Read configuration for resource pool sizes
    try:
        sim_config = get_simulation_config()

        # Pod-level thread pool size
        thread_pool_size = getattr(sim_config.compute, 'thread_pool_size', 50)

        # Pod-level DB connection pool size
        db_connection_pool_size = getattr(sim_config.compute, 'db_connection_pool_capacity', 20)

        # Workload generator connection pool size
        if hasattr(sim_config, 'workload_generator'):
            workload_connection_pool_size = getattr(sim_config.workload_generator, 'connection_pool_size', 200)
        else:
            workload_connection_pool_size = 200  # Default
    except Exception as e:
        # Fallback to defaults if config not available
        print(f"Warning: Could not read simulation config, using defaults: {e}")
        thread_pool_size = 50
        db_connection_pool_size = 20
        workload_connection_pool_size = 200
    # Handle both NetworkX graph and dict representation
    if nx and isinstance(topology, nx.DiGraph):
        nodes = dict(topology.nodes(data=True))
        edges_list = list(topology.edges(data=True))
    else:
        # Dictionary representation from topology.json
        nodes = {n['id']: n for n in topology.get('nodes', [])}
        edges_list = [(e['source'], e['target'], e) for e in topology.get('edges', [])]

    # Find gateway node
    gateway = None
    for node_id, attrs in nodes.items():
        if attrs.get('role') == 'gateway':
            gateway = node_id
            break

    if not gateway:
        return {
            'safe_baseline_rps': 50,
            'safe_peak_rps': 100,
            'required_connection_pool': 100,
            'error': 'No gateway found in topology'
        }

    # Build adjacency for path finding (DIRECTED edges only)
    adjacency = {}
    edge_data_map = {}
    for source, target, attrs in edges_list:
        if source not in adjacency:
            adjacency[source] = []
        adjacency[source].append(target)
        edge_data_map[(source, target)] = attrs

    # Find all valid directed paths using DFS
    def find_all_paths(start, end, path=None):
        """
        Find all directed paths from start to end.
        Only follows edges that exist in the topology (respects direction).

        Args:
            start: Starting node ID
            end: Ending node ID
            path: Current path (for recursion, default None)

        Returns:
            List of paths, where each path is a list of node IDs
        """
        if path is None:
            path = []

        path = path + [start]

        # Base case: reached destination
        if start == end:
            return [path]

        # No outgoing edges from this node
        if start not in adjacency:
            return []

        paths = []
        # Only traverse to nodes that have a DIRECTED edge from current node
        for next_node in adjacency[start]:
            # Avoid cycles (don't revisit nodes already in path)
            if next_node not in path:
                # Verify edge exists (should always be true, but safe check)
                if (start, next_node) in edge_data_map:
                    newpaths = find_all_paths(next_node, end, path)
                    paths.extend(newpaths)

        return paths

    def is_valid_path(path):
        """
        Validate that a path only uses edges that exist in the topology.

        Args:
            path: List of node IDs

        Returns:
            Boolean indicating if path is valid
        """
        for i in range(len(path) - 1):
            source = path[i]
            target = path[i + 1]
            # Check that edge exists
            if (source, target) not in edge_data_map:
                return False
        return True

    # Find leaf nodes (databases, caches, queues, external)
    # Exclude infrastructure nodes (pods, compute nodes, controllers) from service path analysis
    leaf_roles = {'database', 'cache', 'queue', 'external'}
    infrastructure_roles = {'pod', 'node', 'controller'}
    leaf_nodes = []
    for node_id, attrs in nodes.items():
        role = attrs.get('role')
        # Only include service-level leaf nodes, not infrastructure
        if role in leaf_roles:
            if node_id != gateway:  # Don't include gateway as leaf
                leaf_nodes.append(node_id)
        # Also include nodes with no outgoing edges (dead-ends), unless they're infrastructure
        elif node_id not in adjacency and role not in infrastructure_roles:
            if node_id != gateway:
                leaf_nodes.append(node_id)

    # Calculate latency and capacity for each path
    path_analysis = []
    bottleneck_nodes = {}
    invalid_paths_count = 0

    for leaf in leaf_nodes:
        paths = find_all_paths(gateway, leaf)
        for path in paths:
            # Validate path uses only valid directed edges
            if not is_valid_path(path):
                invalid_paths_count += 1
                continue  # Skip invalid path
            # Build component list for this path
            components_in_path = []
            total_latency_p50 = 0.0
            total_latency_p99 = 0.0

            for i, node_id in enumerate(path):
                node_attrs = nodes[node_id]
                role = node_attrs.get('role', 'service')

                # Get component profile
                latency_profile, resource_profile = get_component_profile(role)

                # Add processing latency
                total_latency_p50 += latency_profile.p50
                total_latency_p99 += latency_profile.p99

                # Add network latency to next hop
                if i < len(path) - 1:
                    next_node = path[i + 1]
                    # Get edge data - should always exist since we validated the path
                    edge_attrs = edge_data_map.get((node_id, next_node))
                    if edge_attrs is None:
                        # This should never happen due to is_valid_path check, but safety check
                        print(f"WARNING: Edge {node_id} -> {next_node} not found in topology!")
                        continue

                    edge_type = edge_attrs.get('type', 'sync_http')
                    network = get_network_latency(edge_type)
                    total_latency_p50 += network.p50
                    total_latency_p99 += network.p99

                # Calculate node capacity WITH resource pool constraints
                num_replicas = node_attrs.get('desired_replicas', 1)

                # Get processing pipeline for services
                service_pipeline = None
                if role == 'service' and 'processing_pipeline' in node_attrs:
                    service_pipeline = node_attrs.get('processing_pipeline')

                capacity = estimate_component_capacity(
                    role,
                    num_replicas,
                    thread_pool_size=thread_pool_size if role in ['service', 'gateway'] else None,
                    db_connection_pool_size=db_connection_pool_size if role == 'service' else None,
                    service_pipeline=service_pipeline
                )

                # Track bottleneck
                node_key = f"{node_id}_{role}"
                if node_key not in bottleneck_nodes or capacity['target_rps'] < bottleneck_nodes[node_key]['target_rps']:
                    bottleneck_nodes[node_key] = {
                        'node_id': node_id,
                        'role': role,
                        'target_rps': capacity['target_rps'],
                        'max_rps': capacity['max_rps'],
                        'replicas': num_replicas,
                        'limiting_factor': capacity.get('limiting_factor', 'unknown'),
                        'thread_pool_limited_rps': capacity.get('thread_pool_limited_rps'),
                        'db_pool_limited_rps': capacity.get('db_pool_limited_rps'),
                        'processing_limited_rps': capacity.get('processing_limited_rps'),
                    }

                components_in_path.append((role, edge_attrs.get('type') if i < len(path) - 1 else None))

            path_analysis.append({
                'path': ' -> '.join(path),
                'latency_p50_ms': total_latency_p50,
                'latency_p99_ms': total_latency_p99,
                'components': components_in_path
            })

    # Find critical path (highest latency)
    critical_path_info = max(path_analysis, key=lambda x: x['latency_p99_ms']) if path_analysis else None

    # Find bottleneck node (lowest capacity)
    if bottleneck_nodes:
        bottleneck = min(bottleneck_nodes.values(), key=lambda x: x['target_rps'])
    else:
        bottleneck = {'target_rps': 100, 'node_id': 'unknown', 'role': 'unknown'}

    # Safe RPS is limited by bottleneck node
    safe_baseline_rps = int(bottleneck['target_rps'])
    safe_peak_rps = int(safe_baseline_rps * 1.5)  # 50% burst capacity

    # Calculate required connection pool using Little's Law
    # N = λ × W, where W is critical path p99 latency
    if critical_path_info:
        critical_latency_seconds = critical_path_info['latency_p99_ms'] / 1000.0
    else:
        critical_latency_seconds = 0.1  # Default 100ms

    required_connections = safe_peak_rps * critical_latency_seconds
    required_connections_with_margin = int(required_connections * 2)  # 2x safety margin

    # Validate workload generator sizing (workload generator should support topology, not constrain it)
    workload_validation = validate_workload_generator_sizing(
        safe_peak_rps,
        critical_latency_seconds,
        workload_connection_pool_size
    )

    # Analyze request routing distribution for more accurate capacity estimation
    routing_analysis = analyze_request_routing_distribution(topology, workload_config_path)

    result = {
        'safe_baseline_rps': safe_baseline_rps,
        'safe_peak_rps': safe_peak_rps,
        'required_connection_pool': max(100, required_connections_with_margin),
        'required_thread_pool': thread_pool_size,
        'required_db_connection_pool': db_connection_pool_size,
        'critical_path': critical_path_info['path'] if critical_path_info else 'N/A',
        'critical_path_latency_p50_ms': critical_path_info['latency_p50_ms'] if critical_path_info else 0,
        'critical_path_latency_p99_ms': critical_path_info['latency_p99_ms'] if critical_path_info else 0,
        'bottleneck_node': bottleneck['node_id'],
        'bottleneck_role': bottleneck['role'],
        'bottleneck_capacity_rps': bottleneck['target_rps'],
        'bottleneck_limiting_factor': bottleneck.get('limiting_factor', 'unknown'),
        'bottleneck_details': {
            'thread_pool_limited_rps': bottleneck.get('thread_pool_limited_rps'),
            'db_pool_limited_rps': bottleneck.get('db_pool_limited_rps'),
            'processing_limited_rps': bottleneck.get('processing_limited_rps'),
        },
        'workload_generator_validation': workload_validation,
        'routing_distribution': routing_analysis,
        'target_utilization': target_utilization,
        'num_paths_analyzed': len(path_analysis),
        'num_leaf_nodes': len(leaf_nodes),
        'capacity_note': (
            'Capacity is currently based on worst-case path (slowest). '
            'See routing_distribution for actual request flow patterns. '
            'This is a conservative estimate; actual capacity may be higher '
            'if most requests follow faster paths.'
        )
    }

    # Add validation info if there were issues
    if invalid_paths_count > 0:
        result['warning'] = f'{invalid_paths_count} invalid paths were skipped'

    return result


def extract_node_metrics(metrics_file: Path, node_id: str, start_time: float, end_time: float) -> HealthMetrics:
    """
    Extract health metrics for a specific node during a time window.
    NOW INCLUDES pod-level metrics (CPU, memory, thread pools, connection pools).
    """
    metrics = HealthMetrics()

    with open(metrics_file, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            sim_time = data.get('labels', {}).get('sim.time')
            component_id = data.get('labels', {}).get('component.id', '')
            service_name = data.get('labels', {}).get('service.name', '')

            # Skip if not in time window
            if sim_time is None or sim_time < start_time or sim_time >= end_time:
                continue

            # Match by component_id OR service_name (for aggregated service metrics)
            # Also allow workload metrics
            is_match = (component_id == node_id or
                       service_name == node_id or
                       data.get('name', '').startswith('workload.'))

            if not is_match:
                continue

            # Extract metrics based on metric name
            metric_name = data.get('name', '')
            value = data.get('value', 0)

            # Workload-level metrics (for gateway/workload generator)
            if metric_name == 'workload.requests' and data.get('labels', {}).get('type') == 'attempted':
                # Calculate RPS from count in interval
                metrics.incoming_rps.append(value / 10.0)  # Assuming 10s intervals

            if metric_name == 'workload.requests' and data.get('labels', {}).get('type') == 'success':
                metrics.success_count.append(value)

            if metric_name == 'workload.requests.rejected':
                metrics.failure_count.append(value)

            # Component-level request metrics
            if 'latency' in metric_name and 'p50' in metric_name:
                metrics.latency_p50.append(value)

            if 'latency' in metric_name and 'p99' in metric_name:
                metrics.latency_p99.append(value)

            # === POD-LEVEL METRICS (NEW) ===

            # CPU utilization (from pods)
            if metric_name == 'container.cpu.utilization':
                metrics.cpu_util.append(value)

            # Memory usage (from pods)
            if metric_name == 'container.memory.usage_mb':
                metrics.mem_usage_mb.append(value)

            # Thread pool metrics (from pods)
            if metric_name == 'thread_pool.threads.active':
                metrics.thread_pool_active.append(value)

            if metric_name == 'thread_pool.queue.depth':
                metrics.thread_pool_queue_depth.append(value)

            # Connection pool metrics (from pods)
            if metric_name == 'connection_pool.connections.active':
                metrics.connection_pool_active.append(value)

            if metric_name == 'connection_pool.queue_depth':
                metrics.connection_pool_queue_depth.append(value)

    return metrics


def validate_node_health(node_id: str, metrics: HealthMetrics, thresholds: Dict, thread_pool_size: int = 50, db_connection_pool_size: int = 20) -> Tuple[bool, str, float]:
    """
    Validate a single node's health using mathematical criteria.
    NOW INCLUDES pod-level resource checks (CPU, memory, thread pools, connection pools).

    Returns:
        (is_healthy, failure_reason, health_score)
    """
    # Skip if no data collected for this node
    if (metrics.total_requests == 0 and len(metrics.incoming_rps) == 0 and
        len(metrics.cpu_util) == 0 and len(metrics.thread_pool_active) == 0):
        return True, "No metrics collected (node not exercised)", 1.0

    health_scores = []

    # === REQUEST-LEVEL CHECKS ===

    # 1. Error Rate Check
    if metrics.total_requests > 0:
        error_rate = metrics.error_rate
        max_error_rate = thresholds.get('max_error_rate', 0.01)

        if error_rate > max_error_rate:
            return False, f"Error rate {error_rate:.2%} exceeds {max_error_rate:.2%}", 0.0

        h_errors = 1.0 - (error_rate / max_error_rate) if max_error_rate > 0 else 1.0
        health_scores.append(h_errors)

    # 2. Latency Distribution Check (p99/p50 ratio)
    if metrics.avg_latency_p50 > 0 and metrics.avg_latency_p99 > 0:
        latency_ratio = metrics.avg_latency_p99 / metrics.avg_latency_p50
        max_ratio = thresholds.get('max_p99_ratio', 10.0)

        if latency_ratio > max_ratio:
            return False, f"Latency p99/p50 ratio {latency_ratio:.1f} exceeds {max_ratio}", 0.0

        h_latency = 1.0 - (latency_ratio / max_ratio) if max_ratio > 0 else 1.0
        health_scores.append(h_latency)

    # 3. Circuit Breaker Check
    if metrics.circuit_breaker_opens > 0:
        return False, f"Circuit breaker opened {metrics.circuit_breaker_opens} times during baseline", 0.0

    # 4. Success Rate Check
    if metrics.total_requests > 0:
        success_rate = metrics.success_rate
        min_success_rate = thresholds.get('min_success_rate', 0.95)

        if success_rate < min_success_rate:
            return False, f"Success rate {success_rate:.2%} below {min_success_rate:.2%}", 0.0

        h_success = success_rate / min_success_rate if min_success_rate > 0 else 1.0
        health_scores.append(h_success)

    # === POD-LEVEL RESOURCE CHECKS (NEW) ===

    # 5. CPU Utilization Check
    if len(metrics.cpu_util) > 0:
        max_cpu = metrics.max_cpu_util
        avg_cpu = metrics.avg_cpu_util
        max_cpu_threshold = thresholds.get('max_cpu_utilization', 85.0)

        if max_cpu > max_cpu_threshold:
            return False, f"CPU utilization peaked at {max_cpu:.1f}% (max: {max_cpu_threshold}%)", 0.0

        # Score based on average CPU relative to threshold (only penalize if approaching limit)
        # Linear penalty starting at 50% utilization
        if avg_cpu < 50.0:
            h_cpu = 1.0  # Healthy if below 50%
        else:
            # Linear scale from 1.0 at 50% to 0.0 at 85%
            h_cpu = 1.0 - ((avg_cpu - 50.0) / (max_cpu_threshold - 50.0))
        health_scores.append(h_cpu)

    # 6. Memory Usage Check
    if len(metrics.mem_usage_mb) > 0:
        max_mem_mb = metrics.max_mem_usage_mb
        max_mem_threshold_mb = thresholds.get('max_memory_mb', 450)  # Default: 450MB out of 512MB

        if max_mem_mb > max_mem_threshold_mb:
            return False, f"Memory usage peaked at {max_mem_mb:.0f}MB (max: {max_mem_threshold_mb}MB)", 0.0

        # Score based on average memory (only penalize if approaching limit)
        # Linear penalty starting at 300MB (60% of 512MB capacity)
        avg_mem_mb = metrics.avg_mem_usage_mb
        if avg_mem_mb < 300.0:
            h_mem = 1.0  # Healthy if below 300MB
        else:
            # Linear scale from 1.0 at 300MB to 0.0 at 450MB
            h_mem = 1.0 - ((avg_mem_mb - 300.0) / (max_mem_threshold_mb - 300.0))
        health_scores.append(h_mem)

    # 7. Thread Pool Saturation Check
    if len(metrics.thread_pool_active) > 0:
        max_threads_active = metrics.max_thread_pool_active
        avg_threads_active = metrics.avg_thread_pool_active
        # Consider saturated if using >90% of thread pool
        saturation_threshold = thread_pool_size * 0.9

        if max_threads_active > saturation_threshold:
            return False, f"Thread pool saturated: {max_threads_active:.0f}/{thread_pool_size} threads (>90%)", 0.0

        # Score based on utilization (only penalize if approaching saturation)
        # Linear penalty starting at 70% utilization
        thread_utilization = avg_threads_active / thread_pool_size if thread_pool_size > 0 else 0.0
        if thread_utilization < 0.70:
            h_threads = 1.0  # Healthy if below 70%
        else:
            # Linear scale from 1.0 at 70% to 0.0 at 90%
            h_threads = 1.0 - ((thread_utilization - 0.70) / (0.90 - 0.70))
        health_scores.append(h_threads)

    # 8. Thread Pool Queue Depth Check
    if len(metrics.thread_pool_queue_depth) > 0:
        max_queue_depth = metrics.max_thread_pool_queue_depth
        avg_queue_depth = metrics.avg_thread_pool_queue_depth
        # Any significant queueing indicates saturation
        max_queue_threshold = thresholds.get('max_thread_queue_depth', 10)

        if max_queue_depth > max_queue_threshold:
            return False, f"Thread pool queue depth peaked at {max_queue_depth:.0f} (max: {max_queue_threshold})", 0.0

        # Score based on average queue depth
        h_thread_queue = 1.0 - (avg_queue_depth / max_queue_threshold) if max_queue_threshold > 0 else 1.0
        health_scores.append(h_thread_queue)

    # 9. Connection Pool Saturation Check
    if len(metrics.connection_pool_active) > 0:
        max_connections_active = metrics.max_connection_pool_active
        avg_connections_active = metrics.avg_connection_pool_active
        saturation_threshold = db_connection_pool_size * 0.9

        if max_connections_active > saturation_threshold:
            return False, f"Connection pool saturated: {max_connections_active:.0f}/{db_connection_pool_size} (>90%)", 0.0

        # Score based on utilization (only penalize if approaching saturation)
        # Linear penalty starting at 70% utilization
        conn_utilization = avg_connections_active / db_connection_pool_size if db_connection_pool_size > 0 else 0.0
        if conn_utilization < 0.70:
            h_connections = 1.0  # Healthy if below 70%
        else:
            # Linear scale from 1.0 at 70% to 0.0 at 90%
            h_connections = 1.0 - ((conn_utilization - 0.70) / (0.90 - 0.70))
        health_scores.append(h_connections)

    # 10. Connection Pool Queue Depth Check
    if len(metrics.connection_pool_queue_depth) > 0:
        max_conn_queue_depth = metrics.max_connection_pool_queue_depth
        avg_conn_queue_depth = metrics.avg_connection_pool_queue_depth
        max_conn_queue_threshold = thresholds.get('max_connection_queue_depth', 5)

        if max_conn_queue_depth > max_conn_queue_threshold:
            return False, f"Connection pool queue depth peaked at {max_conn_queue_depth:.0f} (max: {max_conn_queue_threshold})", 0.0

        h_conn_queue = 1.0 - (avg_conn_queue_depth / max_conn_queue_threshold) if max_conn_queue_threshold > 0 else 1.0
        health_scores.append(h_conn_queue)

    # Calculate overall node health score (minimum of all components - weakest link principle)
    node_health = min(health_scores) if health_scores else 1.0

    return True, "Node is healthy", node_health


def validate_system_health(
    metrics_file: Path,
    topology_file: Path,
    fault_start_time: float,
    thresholds: Optional[Dict] = None
) -> Tuple[bool, str, Dict]:
    """
    Validate entire system health using mathematical criteria.

    Args:
        metrics_file: Path to metrics.jsonl
        topology_file: Path to topology.json
        fault_start_time: When fault injection started
        thresholds: Health thresholds (optional)

    Returns:
        (is_healthy, failure_reason, detailed_metrics)
    """
    if thresholds is None:
        thresholds = {
            'max_utilization': 0.80,
            'max_error_rate': 0.01,
            'max_p99_ratio': 10.0,
            'min_success_rate': 0.95,
            'min_health_score': 0.80,
            'max_cpu_utilization': 85.0,
            'max_memory_mb': 450,
            'max_thread_queue_depth': 10,
            'max_connection_queue_depth': 5,
        }

    # Read simulation config for pool sizes
    from src.core.simulation_config import get_simulation_config
    try:
        sim_config = get_simulation_config()
        thread_pool_size = getattr(sim_config.compute, 'thread_pool_size', 50)
        db_connection_pool_size = getattr(sim_config.compute, 'db_connection_pool_capacity', 20)
    except Exception:
        thread_pool_size = 50
        db_connection_pool_size = 20

    # Load topology
    with open(topology_file, 'r') as f:
        topo_data = json.load(f)

    # Identify key nodes to validate
    nodes_to_check = []
    for node in topo_data['nodes']:
        role = node.get('role')
        # Check gateway, services, and infrastructure
        if role in ['gateway', 'service', 'database', 'cache', 'queue', 'external']:
            nodes_to_check.append(node['id'])

    # Also check workload generator metrics
    nodes_to_check.append('workload')

    # Extract and validate each node
    node_health_scores = {}
    validation_details = {}

    for node_id in nodes_to_check:
        try:
            node_metrics = extract_node_metrics(
                metrics_file,
                node_id,
                start_time=0,
                end_time=fault_start_time
            )

            is_healthy, reason, score = validate_node_health(
                node_id,
                node_metrics,
                thresholds,
                thread_pool_size=thread_pool_size,
                db_connection_pool_size=db_connection_pool_size
            )

            node_health_scores[node_id] = score
            validation_details[node_id] = {
                'is_healthy': is_healthy,
                'reason': reason,
                'health_score': score,
                # Request-level metrics
                'avg_rps': node_metrics.avg_rps,
                'error_rate': node_metrics.error_rate,
                'success_rate': node_metrics.success_rate,
                'avg_latency_p50': node_metrics.avg_latency_p50,
                'avg_latency_p99': node_metrics.avg_latency_p99,
                # Pod-level metrics (NEW)
                'avg_cpu_util': node_metrics.avg_cpu_util,
                'max_cpu_util': node_metrics.max_cpu_util,
                'avg_mem_usage_mb': node_metrics.avg_mem_usage_mb,
                'max_mem_usage_mb': node_metrics.max_mem_usage_mb,
                'avg_thread_pool_active': node_metrics.avg_thread_pool_active,
                'max_thread_pool_active': node_metrics.max_thread_pool_active,
                'avg_thread_pool_queue_depth': node_metrics.avg_thread_pool_queue_depth,
                'max_thread_pool_queue_depth': node_metrics.max_thread_pool_queue_depth,
                'avg_connection_pool_active': node_metrics.avg_connection_pool_active,
                'max_connection_pool_active': node_metrics.max_connection_pool_active,
                'avg_connection_pool_queue_depth': node_metrics.avg_connection_pool_queue_depth,
                'max_connection_pool_queue_depth': node_metrics.max_connection_pool_queue_depth,
            }

            if not is_healthy:
                return False, f"Node '{node_id}': {reason}", validation_details

        except Exception as e:
            # If we can't extract metrics, skip this node
            continue

    # Calculate system-wide health score (minimum of all nodes - weakest link)
    if node_health_scores:
        system_health = min(node_health_scores.values())
        min_health_score = thresholds['min_health_score']

        if system_health < min_health_score:
            weakest_node = min(node_health_scores, key=node_health_scores.get)
            return False, f"System health score {system_health:.2f} < {min_health_score:.2f} (weakest: {weakest_node})", validation_details

        return True, f"System is healthy (health score: {system_health:.2f})", validation_details
    else:
        return False, "No metrics could be extracted for validation", validation_details
