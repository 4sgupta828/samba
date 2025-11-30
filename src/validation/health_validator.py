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
    """Container for node-level health metrics."""

    def __init__(self):
        self.incoming_rps: List[float] = []
        self.latency_p50: List[float] = []
        self.latency_p90: List[float] = []
        self.latency_p99: List[float] = []
        self.success_count: List[float] = []
        self.failure_count: List[float] = []
        self.circuit_breaker_opens: int = 0
        self.cpu_util: List[float] = []
        self.mem_util: List[float] = []

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


def calculate_safe_workload(topology, target_utilization: float = 0.70) -> Dict:
    """
    Calculate the maximum safe workload for a given topology using queueing theory
    and realistic component profiles.

    Algorithm:
    1. Find all paths from gateway to leaf nodes
    2. For each path, calculate end-to-end latency using component profiles
    3. For each node in path, estimate capacity based on component type
    4. Find bottleneck node (lowest capacity)
    5. Calculate safe RPS = min(bottleneck_capacity) × target_utilization

    Args:
        topology: NetworkX directed graph or dict with nodes/edges
        target_utilization: Target utilization threshold (0.0-1.0)

    Returns:
        Dictionary with safe workload parameters
    """
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

                # Calculate node capacity
                num_replicas = node_attrs.get('desired_replicas', 1)
                capacity = estimate_component_capacity(role, num_replicas)

                # Track bottleneck
                node_key = f"{node_id}_{role}"
                if node_key not in bottleneck_nodes or capacity['target_rps'] < bottleneck_nodes[node_key]['target_rps']:
                    bottleneck_nodes[node_key] = {
                        'node_id': node_id,
                        'role': role,
                        'target_rps': capacity['target_rps'],
                        'max_rps': capacity['max_rps'],
                        'replicas': num_replicas
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

    result = {
        'safe_baseline_rps': safe_baseline_rps,
        'safe_peak_rps': safe_peak_rps,
        'required_connection_pool': max(100, required_connections_with_margin),
        'critical_path': critical_path_info['path'] if critical_path_info else 'N/A',
        'critical_path_latency_p50_ms': critical_path_info['latency_p50_ms'] if critical_path_info else 0,
        'critical_path_latency_p99_ms': critical_path_info['latency_p99_ms'] if critical_path_info else 0,
        'bottleneck_node': bottleneck['node_id'],
        'bottleneck_role': bottleneck['role'],
        'bottleneck_capacity_rps': bottleneck['target_rps'],
        'target_utilization': target_utilization,
        'num_paths_analyzed': len(path_analysis),
        'num_leaf_nodes': len(leaf_nodes),
    }

    # Add validation info if there were issues
    if invalid_paths_count > 0:
        result['warning'] = f'{invalid_paths_count} invalid paths were skipped'

    return result


def extract_node_metrics(metrics_file: Path, node_id: str, start_time: float, end_time: float) -> HealthMetrics:
    """
    Extract health metrics for a specific node during a time window.
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

            # Skip if not in time window or not this component
            if sim_time is None or sim_time < start_time or sim_time >= end_time:
                continue

            if component_id != node_id and not data.get('name', '').startswith('workload.'):
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

            # Component-level metrics
            if 'latency' in metric_name and 'p50' in metric_name:
                metrics.latency_p50.append(value)

            if 'latency' in metric_name and 'p99' in metric_name:
                metrics.latency_p99.append(value)

            if 'cpu' in metric_name:
                metrics.cpu_util.append(value)

            if 'memory' in metric_name and 'utilization' in metric_name:
                metrics.mem_util.append(value)

    return metrics


def validate_node_health(node_id: str, metrics: HealthMetrics, thresholds: Dict) -> Tuple[bool, str, float]:
    """
    Validate a single node's health using mathematical criteria.

    Returns:
        (is_healthy, failure_reason, health_score)
    """
    # Skip if no data collected for this node
    if metrics.total_requests == 0 and len(metrics.incoming_rps) == 0:
        return True, "No metrics collected (node not exercised)", 1.0

    health_scores = []

    # 1. Utilization Check (implicit from connection pool)
    # For now, we use error rate and latency as proxies
    # TODO: Calculate actual ρ = λ / μ when we have service rate data

    # 2. Error Rate Check
    error_rate = metrics.error_rate
    max_error_rate = thresholds.get('max_error_rate', 0.01)

    if error_rate > max_error_rate:
        return False, f"Error rate {error_rate:.2%} exceeds {max_error_rate:.2%}", 0.0

    h_errors = 1.0 - (error_rate / max_error_rate) if max_error_rate > 0 else 1.0
    health_scores.append(h_errors)

    # 3. Latency Distribution Check (p99/p50 ratio)
    if metrics.avg_latency_p50 > 0 and metrics.avg_latency_p99 > 0:
        latency_ratio = metrics.avg_latency_p99 / metrics.avg_latency_p50
        max_ratio = thresholds.get('max_p99_ratio', 10.0)

        if latency_ratio > max_ratio:
            return False, f"Latency p99/p50 ratio {latency_ratio:.1f} exceeds {max_ratio}", 0.0

        h_latency = 1.0 - (latency_ratio / max_ratio) if max_ratio > 0 else 1.0
        health_scores.append(h_latency)

    # 4. Circuit Breaker Check
    if metrics.circuit_breaker_opens > 0:
        return False, f"Circuit breaker opened {metrics.circuit_breaker_opens} times during baseline", 0.0

    # 5. Success Rate Check
    success_rate = metrics.success_rate
    min_success_rate = thresholds.get('min_success_rate', 0.95)

    if success_rate < min_success_rate:
        return False, f"Success rate {success_rate:.2%} below {min_success_rate:.2%}", 0.0

    h_success = success_rate / min_success_rate if min_success_rate > 0 else 1.0
    health_scores.append(h_success)

    # Calculate overall node health score (minimum of all components)
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
        }

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

            is_healthy, reason, score = validate_node_health(node_id, node_metrics, thresholds)

            node_health_scores[node_id] = score
            validation_details[node_id] = {
                'is_healthy': is_healthy,
                'reason': reason,
                'health_score': score,
                'avg_rps': node_metrics.avg_rps,
                'error_rate': node_metrics.error_rate,
                'success_rate': node_metrics.success_rate,
                'avg_latency_p50': node_metrics.avg_latency_p50,
                'avg_latency_p99': node_metrics.avg_latency_p99,
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
