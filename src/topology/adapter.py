"""
Topology Adapter - Converts NetworkX graphs to SimPy components.

This module bridges the gap between abstract topology generation (NetworkX graphs)
and concrete simulation components (SimPy processes).
"""
import networkx as nx
from typing import Dict, Any

# Import all component types
from src.components.networking import RequestGateway
from src.components.service import ApiService
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache
from src.components.messaging import MessageQueue
from src.components.external import ExternalService
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

    def __init__(self, env):
        """
        Initialize the adapter.

        Args:
            env: SimPy environment
        """
        self.env = env

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

        # Phase 1.5: Create compute instances for each service
        # (Services need compute resources to process requests and generate logs/traces)
        for node_id, data in G.nodes(data=True):
            if data.get('role') == 'service':
                # Create 2 compute instances per service for redundancy
                for i in range(2):
                    compute_id = f'{node_id}_compute_{i}'
                    compute = ComputeAgent(self.env, compute_id)
                    registry[compute_id] = compute

                    # Attach compute to service
                    service = registry[node_id]
                    if 'compute_pool' not in service.connections:
                        service.connections['compute_pool'] = []
                    service.connections['compute_pool'].append(compute)

        # Phase 2: Wire up connections
        for u, v, data in G.edges(data=True):
            if u not in registry or v not in registry:
                continue

            src = registry[u]
            tgt = registry[v]
            edge_type = data.get('type', 'sync')

            self._wire_connection(src, tgt, edge_type, v)

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

        if component_type == 'RequestGateway':
            return RequestGateway(self.env, node_id)

        elif component_type == 'SqlDatabase':
            return SqlDatabase(self.env, node_id)

        elif component_type == 'InMemoryCache':
            return InMemoryCache(self.env, node_id)

        elif component_type == 'MessageQueue':
            return MessageQueue(self.env, node_id)

        elif component_type == 'ExternalService':
            return ExternalService(self.env, node_id)

        elif component_type == 'ApiService':
            # Generic service with generic request types
            component = ApiService(self.env, node_id, service_name=node_id)
            component.supported_request_types = ['GET', 'POST', 'PROCESS']
            return component

        else:
            print(f"Warning: Unknown component type '{component_type}' for node '{node_id}'")
            return None

    def _wire_connection(self, src, tgt, edge_type: str, tgt_id: str):
        """
        Wire up a connection between two components.

        Args:
            src: Source component
            tgt: Target component
            edge_type: Type of connection (sync_http, sync_db, etc.)
            tgt_id: Target component ID (for connection key)
        """
        # Gateway routing
        if isinstance(src, RequestGateway):
            # Gateway needs to route requests to services
            if hasattr(tgt, 'supported_request_types'):
                # Register this service with the gateway
                src.register_service(tgt, tgt.supported_request_types)
            # Also add to connections dict for direct access
            src.connections[f'svc_{tgt_id}'] = tgt

        # Service connections
        elif isinstance(src, ApiService):
            if isinstance(tgt, SqlDatabase):
                # Service → Database
                src.connections['database'] = tgt

            elif isinstance(tgt, InMemoryCache):
                # Service → Cache
                src.connections['cache'] = tgt

            elif isinstance(tgt, MessageQueue):
                # Service → Queue
                if edge_type == 'async_produce':
                    src.connections['queue_out'] = tgt
                else:
                    src.connections['queue'] = tgt

            elif isinstance(tgt, ExternalService):
                # Service → External API
                src.connections[f'ext_{tgt_id}'] = tgt

            elif isinstance(tgt, ApiService):
                # Service → Service (RPC)
                src.connections[f'dep_{tgt_id}'] = tgt

        # Queue → Consumer
        elif isinstance(src, MessageQueue) and isinstance(tgt, ApiService):
            # Implicit connection: consumer pulls from queue
            # The service needs to know about the queue
            if 'queue_in' not in tgt.connections:
                tgt.connections['queue_in'] = src


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
    for node_id, data in G.nodes(data=True):
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
