"""
Topology Generator - Procedurally generates microservice architectures.

This module creates diverse, realistic microservice topologies for training
GNN models. Each topology is unique, forcing models to learn structural patterns
rather than memorizing specific node IDs.
"""
import networkx as nx
import random
from typing import Dict, Any


class TopologyGenerator:
    """
    Generates procedural microservice topologies with realistic patterns:
    - Gateway → Frontend services (entry points)
    - Services → Databases (persistence layer)
    - Services → Caches (performance optimization)
    - Services → Queues → Services (async messaging)
    - Services → External APIs (3rd party dependencies)
    - Services → Services (RPC calls)
    - Ensures weak connectivity (no isolated components)
    """

    def __init__(self, seed: int = None):
        """
        Initialize the topology generator.

        Args:
            seed: Random seed for reproducible topology generation
        """
        self.rng = random.Random(seed)

    def generate_complex_graph(self, num_nodes: int = 20) -> nx.DiGraph:
        """
        Generate a complex microservice topology graph.

        Args:
            num_nodes: Total number of nodes (services + infrastructure)

        Returns:
            NetworkX directed graph with node attributes (type, role) and
            edge attributes (type, base_latency)
        """
        G = nx.DiGraph()

        # --- 1. Component Allocation ---
        # Heuristic ratios for realistic architecture
        n_gateway = 1
        n_total_others = num_nodes - 1

        n_db = max(1, int(n_total_others * 0.2))        # 20% Databases
        n_cache = max(1, int(n_total_others * 0.15))    # 15% Caches
        n_queue = max(1, int(n_total_others * 0.1))     # 10% Queues
        n_external = max(1, int(n_total_others * 0.05)) # 5% External APIs
        n_service = n_total_others - n_db - n_cache - n_queue - n_external

        # Create node lists
        services = [f'svc_{i}' for i in range(n_service)]
        dbs = [f'db_{i}' for i in range(n_db)]
        caches = [f'cache_{i}' for i in range(n_cache)]
        queues = [f'queue_{i}' for i in range(n_queue)]
        externals = [f'ext_{i}' for i in range(n_external)]

        # Add nodes with metadata
        for n in services:
            G.add_node(n, type='ApiService', role='service')
        for n in dbs:
            G.add_node(n, type='SqlDatabase', role='database')
        for n in caches:
            G.add_node(n, type='InMemoryCache', role='cache')
        for n in queues:
            G.add_node(n, type='MessageQueue', role='queue')
        for n in externals:
            G.add_node(n, type='ExternalService', role='external')
        G.add_node('gateway', type='RequestGateway', role='gateway')

        # --- 2. Wiring Strategy ---

        # A. Gateway → Frontends (Entry Points)
        # Pick 20% of services to be "frontends" (directly reachable from gateway)
        n_frontends = max(1, int(len(services) * 0.2))
        frontends = self.rng.sample(services, n_frontends)

        # Tag frontends for workload generator
        for svc in frontends:
            G.nodes[svc]['is_frontend'] = True
            self._add_edge(G, 'gateway', svc, 'sync_http')

        # B. Service → Database (Persistence)
        # Each database is owned by one service (microservice pattern)
        available_services = list(services)
        for db in dbs:
            if not available_services:
                available_services = list(services)  # Recycle if needed
            owner = self.rng.choice(available_services)
            self._add_edge(G, owner, db, 'sync_db')

        # C. Service → Cache (Sidecar Pattern)
        # Caches attached to read-heavy services
        for cache in caches:
            user = self.rng.choice(services)
            self._add_edge(G, user, cache, 'sync_cache')

        # D. Async Message Queues
        # Pattern: Producer → Queue → Consumer
        for queue in queues:
            producer = self.rng.choice(services)
            potential_consumers = [s for s in services if s != producer]
            if potential_consumers:
                consumer = self.rng.choice(potential_consumers)
                # Producer publishes to queue
                self._add_edge(G, producer, queue, 'async_produce')
                # Consumer reads from queue
                self._add_edge(G, queue, consumer, 'async_consume')

        # E. Service → External API
        # Some services depend on 3rd party APIs
        for ext in externals:
            caller = self.rng.choice(services)
            self._add_edge(G, caller, ext, 'sync_external')

        # F. Service → Service (RPC)
        # Add inter-service dependencies (50% additional edges)
        num_rpc_links = int(len(services) * 0.5)
        for _ in range(num_rpc_links):
            u = self.rng.choice(services)
            v = self.rng.choice(services)
            if u != v and not G.has_edge(u, v):
                self._add_edge(G, u, v, 'sync_rpc')

        # G. Ensure Connectivity
        # Repair any disconnected components by connecting them to the main component
        if not nx.is_weakly_connected(G):
            components = list(nx.weakly_connected_components(G))
            main_comp = max(components, key=len)
            for comp in components:
                if comp == main_comp:
                    continue
                # Connect island to main component
                # Find a service node in the main component
                main_services = [n for n in main_comp if G.nodes[n].get('role') == 'service']
                comp_services = [n for n in comp if G.nodes[n].get('role') == 'service']

                if main_services and comp_services:
                    u = self.rng.choice(main_services)
                    v = self.rng.choice(comp_services)
                    self._add_edge(G, u, v, 'sync_rpc')
                elif main_services:
                    # If no services in island, connect to any node
                    u = self.rng.choice(main_services)
                    v = self.rng.choice(list(comp))
                    self._add_edge(G, u, v, 'sync_rpc')
                else:
                    # Last resort: connect any two nodes
                    u = self.rng.choice(list(main_comp))
                    v = self.rng.choice(list(comp))
                    self._add_edge(G, u, v, 'sync_rpc')

        return G

    def _add_edge(self, G: nx.DiGraph, u: str, v: str, edge_type: str):
        """
        Add edge with physical properties (latency).

        Args:
            G: Graph to modify
            u: Source node
            v: Target node
            edge_type: Type of connection (determines latency)
        """
        # Assign realistic latencies based on edge type
        latency = 5.0  # Default: 5ms (local network)

        if edge_type == 'sync_external':
            latency = 200.0  # External APIs are slow (200ms)
        elif edge_type == 'sync_db':
            latency = 2.0    # Databases are fast (2ms, local)
        elif edge_type == 'sync_cache':
            latency = 1.0    # Caches are very fast (1ms)

        G.add_edge(u, v, type=edge_type, base_latency=latency)


def visualize_topology(G: nx.DiGraph, output_path: str = None):
    """
    Visualize the generated topology (optional, requires matplotlib).

    Args:
        G: NetworkX graph to visualize
        output_path: Path to save visualization (optional)
    """
    try:
        import matplotlib.pyplot as plt

        # Color nodes by role
        color_map = {
            'gateway': 'lightblue',
            'service': 'lightgreen',
            'database': 'orange',
            'cache': 'yellow',
            'queue': 'pink',
            'external': 'red'
        }

        node_colors = [color_map.get(G.nodes[n].get('role', 'service'), 'gray') for n in G.nodes()]

        plt.figure(figsize=(12, 8))
        pos = nx.spring_layout(G, k=0.5, iterations=50)
        nx.draw(G, pos, node_color=node_colors, with_labels=True,
                node_size=500, font_size=8, arrows=True, edge_color='gray', alpha=0.7)

        plt.title(f"Generated Topology ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")

        if output_path:
            plt.savefig(output_path)
        else:
            plt.show()
    except ImportError:
        print("Warning: matplotlib not installed, skipping visualization")
