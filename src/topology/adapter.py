"""
Topology Adapter - Converts NetworkX graphs to SimPy components.

This module bridges the gap between abstract topology generation (NetworkX graphs)
and concrete simulation components (SimPy processes).

Supports two architectures:
1. New: Service/Pod/Node with DeploymentController
2. Legacy: ApiService/ComputeAgent for backward compatibility
"""
import networkx as nx
import simpy
from typing import Dict, Any

# Import all component types
from src.components.networking import RequestGateway
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache, ExternalCache
from src.components.messaging import MessageQueue
from src.components.external import ExternalService

# New architecture imports
from src.components.service import Service
from src.components.pod import Pod
from src.components.compute_node import ComputeNode
from src.components.deployment_controller import DeploymentController

# Legacy architecture imports (for backward compatibility)
from src.components.service import ApiService
from src.components.compute import ComputeAgent


class TopologyAdapter:
    """
    Instantiates SimPy components based on a NetworkX topology graph.

    This adapter:
    1. Creates component instances based on node types
    2. Wires up connections based on edges
    3. Registers services with the gateway
    4. Returns a component registry for simulation
    """

    def __init__(self, env, semantic_overlay=None, topology_exporter=None):
        """
        Initialize the adapter.

        Args:
            env: SimPy environment
            semantic_overlay: Optional semantic configuration from SemanticMapper
            topology_exporter: Optional TopologyStateExporter for pod lifecycle tracking
        """
        self.env = env
        self.semantic_overlay = semantic_overlay or {}
        self.topology_exporter = topology_exporter

    def graph_to_registry(self, G: nx.DiGraph) -> Dict[str, Any]:
        """
        Convert a NetworkX graph to a component registry.

        Args:
            G: NetworkX directed graph with node/edge attributes

        Returns:
            Dictionary mapping component IDs to component instances
        """
        registry = {}

        # Phase 1: Instantiate all components
        for node_id, data in G.nodes(data=True):
            component = self._create_component(node_id, data)
            if component:
                registry[node_id] = component

        # Phase 1.5: REMOVED - Legacy ComputeAgent creation
        # New Service architecture uses Pods (created by topology generator)

        # Phase 2: Wire up connections
        for u, v, data in G.edges(data=True):
            if u not in registry or v not in registry:
                continue

            src = registry[u]
            tgt = registry[v]
            edge_type = data.get('type', 'sync')

            self._wire_connection(src, tgt, edge_type, v)

        # Phase 3: REMOVED - Legacy ComputeAgent connection propagation
        # New architecture: Pods inherit connections from parent Service dynamically

        # Phase 4: Sync component state back to graph (for topology serialization)
        # This ensures that attributes set during wiring (like compute_node) are preserved
        # in the graph when it's serialized to topology.json
        self._sync_component_state_to_graph(G, registry)

        return registry

    def _create_component(self, node_id: str, node_data: Dict[str, Any]):
        """
        Create a component instance based on node type.

        Args:
            node_id: Unique component identifier
            node_data: Node metadata (type, role, etc.)

        Returns:
            Component instance or None
        """
        component_type = node_data.get('type')

        # Infrastructure components
        if component_type == 'RequestGateway':
            return RequestGateway(self.env, node_id)

        elif component_type == 'SqlDatabase' or component_type == 'Database':
            component = SqlDatabase(self.env, node_id)

            # Apply resource overrides from CapacityPlanner
            overrides = node_data.get('iac_config_overrides', {})
            if overrides:
                self._apply_overrides(component, overrides)

            return component

        elif component_type == 'InMemoryCache' or component_type == 'Cache':
            return InMemoryCache(self.env, node_id)

        elif component_type == 'ExternalCache':
            return ExternalCache(self.env, node_id)

        elif component_type == 'MessageQueue':
            return MessageQueue(self.env, node_id)

        elif component_type == 'ExternalService':
            return ExternalService(self.env, node_id)

        # New architecture components
        elif component_type == 'Service':
            # New lightweight service coordinator
            # NEW: Get semantic configuration from overlay
            semantic_services = self.semantic_overlay.get('services', {})
            semantic_config = semantic_services.get(node_id, {})

            # IMPORTANT: Keep using HTTP methods for actual simulation
            # Semantic request types are for analysis/documentation only
            # Using domain-specific types would break compatibility with workload generator
            supported_request_types = node_data.get('supported_request_types', ['GET', 'POST'])

            processing_pipeline = node_data.get('processing_pipeline')

            # Check for overrides from CapacityPlanner
            overrides = node_data.get('iac_config_overrides', {})

            # Use overridden replicas if present, else default
            desired_replicas = overrides.get('desired_replicas',
                                           node_data.get('desired_replicas', 3))

            # Include full semantic config (with request_flows)
            full_semantic_config = {
                **semantic_config,
                'request_flows': self.semantic_overlay.get('request_flows', {})
            }

            component = Service(
                self.env,
                node_id,
                service_name=semantic_config.get('name', node_data.get('service_name', node_id)),
                supported_request_types=supported_request_types,
                processing_pipeline=processing_pipeline,
                desired_replicas=desired_replicas,
                semantic_config=full_semantic_config
            )

            # Apply resource overrides after component creation
            self._apply_overrides(component, overrides)

            return component

        elif component_type == 'Pod':
            # Pod instances (will be linked to parent service and compute node later)
            # NEW: Get semantic profile from overlay
            semantic_services = self.semantic_overlay.get('services', {})

            # First try to get pod's own profile from overlay
            semantic_profile = semantic_services.get(node_id, {})

            # If pod doesn't have its own profile, try to infer from parent service
            # Pod names follow pattern: pod_svc_X_Y where svc_X is the parent service
            if not semantic_profile and 'pod_svc_' in node_id:
                # Extract parent service ID from pod name (e.g., "pod_svc_0_1" -> "svc_0")
                import re
                match = re.search(r'pod_(svc_\d+)_\d+', node_id)
                if match:
                    parent_svc_id = match.group(1)
                    semantic_profile = semantic_services.get(parent_svc_id, {})

            # If still no profile, it will default to "standard" in Pod.__init__
            # Pass event_tracker if we have a topology_exporter
            event_tracker = None
            if self.topology_exporter:
                from src.telemetry.topology_state_exporter import TopologyEventTracker
                event_tracker = TopologyEventTracker(self.topology_exporter)
            component = Pod(self.env, node_id, parent_service=None, compute_node=None, semantic_profile=semantic_profile, event_tracker=event_tracker)

            # Apply resource overrides from CapacityPlanner
            overrides = node_data.get('iac_config_overrides', {})
            if overrides:
                self._apply_overrides(component, overrides)

            return component

        elif component_type == 'ComputeNode':
            # Physical/VM resources
            cpu_cores = node_data.get('cpu_cores', 8)
            memory_gb = node_data.get('memory_gb', 32)
            network_bandwidth_gbps = node_data.get('network_bandwidth_gbps', 10)

            return ComputeNode(
                self.env,
                node_id,
                cpu_cores=cpu_cores,
                memory_gb=memory_gb,
                network_bandwidth_gbps=network_bandwidth_gbps
            )

        elif component_type == 'DeploymentController':
            return DeploymentController(self.env, node_id, topology_exporter=self.topology_exporter)

        else:
            print(f"Warning: Unknown component type '{component_type}' for node '{node_id}'")
            return None

    def _wire_connection(self, src, tgt, edge_type: str, tgt_id: str):
        """
        Wire up a connection between two components.

        Args:
            src: Source component
            tgt: Target component
            edge_type: Type of connection (sync_http, sync_db, pod_pool, pod_placement, etc.)
            tgt_id: Target component ID (for connection key)
        """
        # Gateway routing (works with both Service and ApiService)
        if isinstance(src, RequestGateway):
            # Gateway needs to route requests to services
            if hasattr(tgt, 'supported_request_types'):
                # Register this service with the gateway
                src.register_service(tgt, tgt.supported_request_types)
            # Also add to connections dict for direct access
            src.connections[f'svc_{tgt_id}'] = tgt

        # New architecture: Service → Pod (pod_pool edge)
        elif isinstance(src, Service) and isinstance(tgt, Pod) and edge_type == 'pod_pool':
            # Add pod to service's pod list
            src.pods.append(tgt)
            # Set pod's parent service
            tgt.parent_service = src
            # NEW: Inherit semantic profile from parent service
            if hasattr(src, 'semantic_config'):
                tgt.semantic_profile = src.semantic_config
                tgt.resource_profile = src.semantic_config.get('profile', 'standard')
            # Initialize request-level metrics now that parent_service is set
            tgt._initialize_request_metrics()

        # New architecture: Pod → ComputeNode (pod_placement edge)
        elif isinstance(src, Pod) and isinstance(tgt, ComputeNode) and edge_type == 'pod_placement':
            # Set pod's compute node
            src.compute_node = tgt
            # Register pod with node
            tgt.register_pod(src)

        # New architecture: DeploymentController registration
        elif isinstance(src, DeploymentController):
            if isinstance(tgt, Service):
                # Register service with controller
                src.register_service(tgt)
            elif isinstance(tgt, ComputeNode):
                # Register node with controller
                src.register_node(tgt)

        # New architecture: Service connections (same pattern as ApiService)
        elif isinstance(src, Service):
            if isinstance(tgt, SqlDatabase):
                # Service → Database
                # Use unique key to support multiple databases per service
                src.connections[f'db_{tgt_id}'] = tgt

            elif isinstance(tgt, InMemoryCache) or isinstance(tgt, ExternalCache):
                # Service → Cache (in-memory or external/Redis-like)
                # Use unique key to support multiple caches per service
                src.connections[f'cache_{tgt_id}'] = tgt

            elif isinstance(tgt, MessageQueue):
                # Service → Queue
                if edge_type == 'async_produce':
                    # Support multiple outgoing queues
                    if 'queue_out' not in src.connections:
                        src.connections['queue_out'] = []
                    if isinstance(src.connections['queue_out'], list):
                        src.connections['queue_out'].append(tgt)
                    else:
                        # Convert single queue to list for backward compatibility
                        src.connections['queue_out'] = [src.connections['queue_out'], tgt]
                elif edge_type == 'async_consume':
                    src.connections['queue_in'] = tgt
                else:
                    src.connections['queue'] = tgt

            elif isinstance(tgt, ExternalService):
                # Service → External API
                src.connections[f'ext_{tgt_id}'] = tgt

            elif isinstance(tgt, Service) or isinstance(tgt, ApiService):
                # Service → Service (RPC)
                src.connections[f'dep_{tgt_id}'] = tgt

        # Legacy: ApiService connections
        elif isinstance(src, ApiService):
            if isinstance(tgt, SqlDatabase):
                # Service → Database
                # Use unique key to support multiple databases per service
                src.connections[f'db_{tgt_id}'] = tgt

            elif isinstance(tgt, InMemoryCache) or isinstance(tgt, ExternalCache):
                # Service → Cache (in-memory or external/Redis-like)
                # Use unique key to support multiple caches per service
                src.connections[f'cache_{tgt_id}'] = tgt

            elif isinstance(tgt, MessageQueue):
                # Service → Queue
                if edge_type == 'async_produce':
                    # Support multiple outgoing queues
                    if 'queue_out' not in src.connections:
                        src.connections['queue_out'] = []
                    if isinstance(src.connections['queue_out'], list):
                        src.connections['queue_out'].append(tgt)
                    else:
                        # Convert single queue to list for backward compatibility
                        src.connections['queue_out'] = [src.connections['queue_out'], tgt]
                else:
                    src.connections['queue'] = tgt

            elif isinstance(tgt, ExternalService):
                # Service → External API
                src.connections[f'ext_{tgt_id}'] = tgt

            elif isinstance(tgt, ApiService):
                # Service → Service (RPC)
                src.connections[f'dep_{tgt_id}'] = tgt

        # Queue → Consumer (works with both Service and ApiService)
        elif isinstance(src, MessageQueue):
            if isinstance(tgt, ApiService):
                # Legacy: ApiService consumes from queue
                if 'queue_in' not in tgt.connections:
                    tgt.connections['queue_in'] = src
            elif isinstance(tgt, Service):
                # New: Service consumes from queue (pods will handle consumption)
                if 'queue_in' not in tgt.connections:
                    tgt.connections['queue_in'] = src

    def _sync_component_state_to_graph(self, G: nx.DiGraph, registry: Dict[str, Any]):
        """
        Sync component state back to the NetworkX graph.
        
        This ensures that attributes set during wiring (like compute_node on Pods)
        are preserved in the graph when it's serialized to topology.json.
        
        Args:
            G: NetworkX graph to update
            registry: Component registry mapping node IDs to component instances
        """
        for node_id, component in registry.items():
            if node_id not in G:
                continue
            
            # Sync Pod compute_node and parent_service attributes
            if isinstance(component, Pod):
                if hasattr(component, 'compute_node') and component.compute_node:
                    G.nodes[node_id]['compute_node'] = component.compute_node.id
                if hasattr(component, 'parent_service') and component.parent_service:
                    G.nodes[node_id]['parent_service'] = component.parent_service.id

    def _apply_overrides(self, component, overrides: Dict[str, Any]):
        """
        Apply capacity planning overrides to a component.

        Args:
            component: Component instance to modify
            overrides: Dictionary of override parameters
        """
        if not overrides:
            return

        # Apply thread pool size
        if 'thread_pool_size' in overrides and hasattr(component, 'thread_pool'):
            # Re-create resource with new capacity
            component.thread_pool_size = overrides['thread_pool_size']
            component.thread_pool = simpy.Resource(component.env, capacity=component.thread_pool_size)

        # Apply DB pool size (only if capacity > 0)
        if 'db_connection_pool_capacity' in overrides and hasattr(component, 'db_connection_pool'):
            capacity = overrides['db_connection_pool_capacity']
            if capacity > 0:
                component.db_connection_pool = simpy.Resource(component.env, capacity=capacity)
            else:
                # Service doesn't need database connections, set to None
                component.db_connection_pool = None

        # Apply memory capacity (for Pods - right-sizing based on workload)
        if 'memory_capacity_mb' in overrides and hasattr(component, 'memory_capacity_mb'):
            component.memory_capacity_mb = overrides['memory_capacity_mb']

        # Apply message concurrency (for async queue consumers)
        if 'message_concurrency' in overrides and hasattr(component, 'message_concurrency_semaphore'):
            component.message_concurrency = overrides['message_concurrency']
            component.message_concurrency_semaphore = simpy.Resource(
                component.env, capacity=component.message_concurrency)

        # Apply Timeouts (update the component's config object)
        if 'timeouts' in overrides and hasattr(component, 'iac_config'):
            if not component.iac_config:
                component.iac_config = {}
            component.iac_config['timeouts'] = overrides['timeouts']

        # Apply CPU Cores (for Database)
        if 'cpu_cores' in overrides and hasattr(component, 'cpu_resource'):
            capacity = overrides['cpu_cores']
            component.cpu_resource = simpy.PriorityResource(component.env, capacity=capacity)

        # Apply connection pool capacity (for Database)
        if 'connection_pool_capacity' in overrides and hasattr(component, 'connection_pool'):
            capacity = overrides['connection_pool_capacity']
            component.connection_pool = simpy.Resource(component.env, capacity=capacity)


def print_topology_summary(G: nx.DiGraph):
    """
    Print a human-readable summary of the topology.

    Args:
        G: NetworkX graph
    """
    print("\n=== Topology Summary ===")
    print(f"Total Nodes: {G.number_of_nodes()}")
    print(f"Total Edges: {G.number_of_edges()}")

    # Count by role
    role_counts = {}
    for _, data in G.nodes(data=True):
        role = data.get('role', 'unknown')
        role_counts[role] = role_counts.get(role, 0) + 1

    print("\nNode Distribution:")
    for role, count in sorted(role_counts.items()):
        print(f"  {role}: {count}")

    # Find frontends
    frontends = [n for n, d in G.nodes(data=True) if d.get('is_frontend')]
    print(f"\nFrontend Services: {len(frontends)}")
    print(f"  {', '.join(frontends)}")

    # Check connectivity
    is_connected = nx.is_weakly_connected(G)
    print(f"\nWeakly Connected: {is_connected}")

    if not is_connected:
        components = list(nx.weakly_connected_components(G))
        print(f"  Warning: {len(components)} disconnected components!")
