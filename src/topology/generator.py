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

        # For very small topologies (2-4 nodes), use minimal allocation
        if num_nodes <= 4:
            # Minimal topology: gateway + service + (optional db/cache)
            n_service = 1
            n_db = 1 if num_nodes >= 3 else 0
            n_cache = 1 if num_nodes >= 4 else 0
            n_queue = 0
            n_external = 0
        # For small topologies (5-9 nodes), use simpler allocation
        elif num_nodes < 10:
            # Simplified allocation: prioritize services
            n_service = max(2, num_nodes - 3)  # At least 2 services
            n_db = 1
            n_cache = 1 if num_nodes > 4 else 0
            n_queue = 1 if num_nodes > 6 else 0
            n_external = 1 if num_nodes > 8 else 0
        else:
            # Standard allocation for larger topologies
            n_db = max(1, int(n_total_others * 0.2))        # 20% Databases
            n_cache = max(1, int(n_total_others * 0.15))    # 15% Caches
            n_queue = max(1, int(n_total_others * 0.1))     # 10% Queues
            n_external = max(1, int(n_total_others * 0.05)) # 5% External APIs
            n_service = n_total_others - n_db - n_cache - n_queue - n_external
            n_service = max(2, n_service)  # Ensure at least 2 services

        # Create node lists
        services = [f'svc_{i}' for i in range(n_service)]
        dbs = [f'db_{i}' for i in range(n_db)]
        caches = [f'cache_{i}' for i in range(n_cache)]
        queues = [f'queue_{i}' for i in range(n_queue)]
        externals = [f'ext_{i}' for i in range(n_external)]

        # Add nodes with metadata
        for n in services:
            # New architecture: Service with desired_replicas
            # Services support GET and POST (PUT/DELETE disabled for now)
            G.add_node(n,
                      type='Service',
                      role='service',
                      service_name=n,
                      desired_replicas=3,  # 3 pods per service
                      supported_request_types=['GET', 'POST'],  # PUT/DELETE disabled temporarily
                      processing_pipeline=None)  # Will be set during wiring
        for n in dbs:
            G.add_node(n, type='SqlDatabase', role='database')
        for n in caches:
            G.add_node(n, type='ExternalCache', role='cache')
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
        # Each database is owned by one or more services (microservices can share DBs)
        # Note: Not all services need databases - some may only call external APIs or other services
        db_to_services = {}  # Track which services use each database
        for db in dbs:
            # Assign 1-3 services to each database
            num_owners = self.rng.randint(1, min(3, len(services)))
            owners = self.rng.sample(services, num_owners)
            db_to_services[db] = owners
            for owner in owners:
                self._add_edge(G, owner, db, 'sync_db')

        # C. Service → Cache (Sidecar Pattern)
        # IMPORTANT: Caches are only created for services that have databases
        # A cache without a database doesn't make architectural sense
        # Cache is a performance optimization layer on top of persistent storage
        if caches and dbs and services:
            # Get all services that have at least one database connection
            services_with_db = set()
            for db, owners in db_to_services.items():
                services_with_db.update(owners)

            # If no services have databases yet, we can't assign caches
            if not services_with_db:
                # This shouldn't happen in normal topologies, but handle edge case
                # by assigning a database to a service first
                db = dbs[0]
                service = services[0]
                self._add_edge(G, service, db, 'sync_db')
                db_to_services[db] = db_to_services.get(db, []) + [service]
                services_with_db.add(service)

            # Assign each cache to services that have databases
            # Multiple services can share a cache (common in microservices)
            services_with_db_list = list(services_with_db)
            for cache in caches:
                # Randomly select 1-2 services with databases to share this cache
                num_cache_users = self.rng.randint(1, min(2, len(services_with_db_list)))
                cache_users = self.rng.sample(services_with_db_list, num_cache_users)

                for cache_user in cache_users:
                    # Double-check the service has a database connection (defensive programming)
                    has_db = any(data.get('type') == 'sync_db'
                                for _, _, data in G.edges(cache_user, data=True))
                    if not has_db:
                        # This should never happen, but if it does, add a database connection
                        # Use the first available database
                        db = dbs[0]
                        self._add_edge(G, cache_user, db, 'sync_db')

                    self._add_edge(G, cache_user, cache, 'sync_cache')

        # D. Async Message Queues
        # Pattern: Producer → Queue → Consumer
        # FIXED: Prevent circular dependencies (producer == consumer)
        if queues and services and len(services) >= 2:
            for queue in queues:
                # Track all producers for this queue
                producers = []

                # Allow multiple producers (1-2 per queue)
                num_producers = self.rng.randint(1, min(2, len(services)))
                for _ in range(num_producers):
                    available_producers = [s for s in services if s not in producers]
                    if available_producers:
                        producer = self.rng.choice(available_producers)
                        producers.append(producer)
                        # Producer publishes to queue
                        self._add_edge(G, producer, queue, 'async_produce')

                # Consumer must be different from ALL producers to avoid circular dependency
                potential_consumers = [s for s in services if s not in producers]
                if potential_consumers:
                    consumer = self.rng.choice(potential_consumers)
                    # Consumer reads from queue
                    self._add_edge(G, queue, consumer, 'async_consume')

        # E. Service → External API
        # Some services depend on 3rd party APIs
        if externals and services:
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

        # H. Ensure Gateway Reachability (CRITICAL FIX)
        # All nodes must be reachable from the gateway for a valid microservice architecture
        # This ensures traffic can flow from gateway to all parts of the system
        if 'gateway' in G:
            reachable = set(nx.descendants(G, 'gateway')) | {'gateway'}
            unreachable = set(G.nodes()) - reachable

            if unreachable:
                # Connect unreachable nodes to the gateway path
                # Strategy: Connect unreachable frontends to gateway, others to reachable services
                for node in unreachable:
                    node_role = G.nodes[node].get('role')

                    if node_role == 'service':
                        # Connect service to a reachable frontend service or directly to gateway
                        reachable_frontends = [n for n in reachable
                                             if G.nodes[n].get('role') == 'service' and
                                             G.nodes[n].get('is_frontend')]
                        if reachable_frontends:
                            # Connect to a frontend via RPC
                            target = self.rng.choice(reachable_frontends)
                            self._add_edge(G, target, node, 'sync_rpc')
                        else:
                            # Make this service a frontend
                            G.nodes[node]['is_frontend'] = True
                            self._add_edge(G, 'gateway', node, 'sync_http')
                    elif node_role in ['database', 'cache', 'queue', 'external']:
                        # Infrastructure nodes should be reached from services
                        # Connect from any reachable service
                        reachable_services = [n for n in reachable
                                            if G.nodes[n].get('role') == 'service']
                        if reachable_services:
                            # Special handling for cache nodes: only connect to services with databases
                            if node_role == 'cache':
                                # Filter to only services that have database connections
                                reachable_services_with_db = [
                                    s for s in reachable_services
                                    if any(data.get('type') == 'sync_db'
                                          for _, _, data in G.edges(s, data=True))
                                ]
                                if reachable_services_with_db:
                                    source = self.rng.choice(reachable_services_with_db)
                                else:
                                    # No service with DB available, add DB connection to a service first
                                    source = self.rng.choice(reachable_services)
                                    # Add database connection if not already present
                                    if dbs:
                                        self._add_edge(G, source, dbs[0], 'sync_db')
                                edge_type = 'sync_cache'
                            else:
                                source = self.rng.choice(reachable_services)
                                # Choose appropriate edge type based on node role
                                if node_role == 'database':
                                    edge_type = 'sync_db'
                                elif node_role == 'queue':
                                    edge_type = 'async_produce'
                                elif node_role == 'external':
                                    edge_type = 'sync_external'
                                else:
                                    edge_type = 'sync_rpc'

                            self._add_edge(G, source, node, edge_type)

                    # Update reachable set
                    reachable = set(nx.descendants(G, 'gateway')) | {'gateway'}
                    unreachable = set(G.nodes()) - reachable

        # I. Add New Architecture Components (Service/Pod/Node Model)
        # Calculate pods and nodes needed
        total_pods = len(services) * 3  # 3 pods per service
        pods_per_node = 5  # Target 5 pods per node
        num_nodes = max(1, (total_pods + pods_per_node - 1) // pods_per_node)  # Ceiling division

        # Create Compute Nodes
        nodes = [f'node_{i}' for i in range(num_nodes)]
        for node_id in nodes:
            G.add_node(node_id,
                      type='ComputeNode',
                      role='node',
                      cpu_cores=8,
                      memory_gb=32,
                      network_bandwidth_gbps=10)

        # Create Pods for each Service (round-robin placement across nodes)
        node_idx = 0
        for svc in services:
            for pod_num in range(3):  # 3 pods per service
                pod_id = f'pod_{svc}_{pod_num}'
                target_node = nodes[node_idx % num_nodes]

                G.add_node(pod_id,
                          type='Pod',
                          role='pod',
                          parent_service=svc,
                          compute_node=target_node)

                # Add edges: Service → Pod (pod_pool), Pod → Node (pod_placement)
                self._add_edge(G, svc, pod_id, 'pod_pool')
                self._add_edge(G, pod_id, target_node, 'pod_placement')

                node_idx += 1

        # Create DeploymentController
        G.add_node('deployment_controller',
                  type='DeploymentController',
                  role='controller')

        # Set processing pipelines for services based on their connections
        self._set_processing_pipelines(G)

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
            # FIXED: Reduced from 200ms to 50ms to prevent connection pool saturation
            # 200ms was causing baseline failures due to pool exhaustion
            latency = 50.0   # External APIs are moderately slow (50ms)
        elif edge_type == 'sync_db':
            latency = 2.0    # Databases are fast (2ms, local)
        elif edge_type == 'sync_cache':
            latency = 1.0    # Caches are very fast (1ms)

        G.add_edge(u, v, type=edge_type, base_latency=latency)

    def _set_processing_pipelines(self, G: nx.DiGraph):
        """
        Infer and set processing_pipeline for each service based on its connections.

        This analyzes the outgoing edges from each service to determine what
        resources it uses (cache, DB, other services, external APIs, queues).
        """
        for node_id, attrs in G.nodes(data=True):
            if attrs.get('role') != 'service':
                continue

            # Get outgoing edges to determine what this service connects to
            successors = list(G.successors(node_id))

            # Analyze successor types
            has_cache = False
            has_db = False
            has_service_deps = False
            has_external_deps = False
            has_queue_out = False

            for succ in successors:
                succ_role = G.nodes[succ].get('role')

                if succ_role == 'cache':
                    has_cache = True
                elif succ_role == 'database':
                    has_db = True
                elif succ_role == 'service':
                    has_service_deps = True
                elif succ_role == 'external':
                    has_external_deps = True
                elif succ_role == 'queue':
                    has_queue_out = True

            # Build pipeline based on what the service connects to
            pipeline = []

            # Always check cache first if available (cache-aside pattern)
            if has_cache:
                pipeline.append({"type": "cache_check"})

            # Query database if available (and if cache misses)
            if has_db:
                pipeline.append({"type": "db_query"})

            # Call downstream services (with probability based on architecture)
            if has_service_deps:
                # 70% of requests make service calls (some may be conditional)
                pipeline.append({"type": "service_calls", "probability": 0.7})

            # Call external APIs if available
            if has_external_deps:
                # 30% of requests need external data (often optional/enrichment)
                pipeline.append({"type": "external_calls", "probability": 0.3})

            # Publish to queue if available
            if has_queue_out:
                # 50% of requests publish events (async operations)
                pipeline.append({"type": "queue_publish", "probability": 0.5})

            # Set the pipeline (or None if no connections)
            G.nodes[node_id]['processing_pipeline'] = pipeline if pipeline else None


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
