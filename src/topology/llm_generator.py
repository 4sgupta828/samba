"""
LLM Topology Generator.
Uses an LLM to architect realistic distributed systems with deterministic flows.
"""
import json
import os
import networkx as nx
from typing import Dict, Any, List
from anthropic import Anthropic


class LLMTopologyGenerator:
    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize the LLM Topology Generator.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use (default: claude-sonnet-4-20250514)
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def generate_architecture(self, archetype: str, scale: str = "medium") -> Dict[str, Any]:
        """
        Orchestrates generation and validation. Retries if LLM generates invalid graph.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 1. Generate JSON from LLM
                raw_json = self._call_llm(archetype, scale)
                topology_data = self._parse_json(raw_json)

                # 2. Convert to Graph for Validation
                G_all = self._json_to_networkx_skeleton(topology_data)  # All edges for connectivity
                G_sync = self._build_sync_only_graph(topology_data)     # Sync edges only for DAG

                # 3. Rigorous Validation
                self._validate_dag(G_sync)           # Check cycles on sync edges only
                self._validate_connectivity(G_all)   # Check connectivity with all edges
                self._validate_node_types(topology_data)
                self._validate_async_edges(topology_data)
                self._validate_minimum_requirements(topology_data, archetype, scale)

                print(f"  ✓ Generated valid {archetype} topology on attempt {attempt+1}")
                return topology_data

            except ValueError as e:
                print(f"  ⚠ Attempt {attempt+1} failed validation: {e}")
                continue

        raise RuntimeError(f"Failed to generate valid {archetype} topology after {max_retries} attempts")

    def _call_llm(self, archetype: str, scale: str) -> str:
        prompt = self._build_prompt(archetype, scale)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._get_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def _get_system_prompt(self) -> str:
        return """You are a Principal Software Architect with expertise in distributed systems.
Your goal is to design realistic, fault-tolerant distributed system topologies for simulation.
You must output STRICT JSON matching the schema provided.

**STEP-BY-STEP DESIGN PROCESS:**

STEP 1: Design the infrastructure layer (databases, caches, queues, external services)
- Start with 1-3 databases for different concerns (user data, transactions, analytics)
- Add 1-2 caches (Redis/Memcached) for performance
- Add message queues for async processing (1+ for non-pipeline, 3-6 for pipeline)
- Add 1-2 external services (payment gateway, CDN, notification service)

STEP 2: Design the service layer in LAYERS (to avoid cycles)
- Layer 1 (Frontend): Services that talk to Gateway (2-3 services)
- Layer 2 (Backend): Services called by frontend (2-3 services)
- Layer 3 (Data/Async): Services that process async jobs (1-2 services)
- RULE: Services can only call services in their own layer OR lower layers
- RULE: Services CANNOT call services in higher layers (this creates cycles!)

STEP 3: Connect services to infrastructure
- Each service connects to at least ONE: database, cache, queue, or external service
- Use sync_db for database calls
- Use sync_cache for cache calls
- Use async_produce to publish to queues
- Use async_consume to consume from queues (Queue → Service, NOT Service → Queue)
- Use sync_external for external API calls

STEP 4: Define request flows
- Trace the path of GET/POST/PUT/DELETE requests
- Start from gateway, follow edges to services, then to infrastructure
- Make sure every node in flows appears in nodes[]
- Make sure every flow path corresponds to edges[]

**CRITICAL CONSTRAINTS - SELF-CHECK BEFORE RETURNING:**

1. **No Cycles (MOST IMPORTANT):**
   - Draw the service call graph on paper first
   - Organize services in layers: Frontend → Backend → Data
   - Services can ONLY call services in same/lower layers, NEVER higher layers
   - Example of CYCLE (WRONG): service_a → service_b → service_c → service_a ❌
   - Example of CORRECT: gateway → frontend_svc → backend_svc → database ✅
   - If you detect a cycle, REMOVE the edge that goes backwards to a higher layer

2. **Connectivity (SECOND MOST IMPORTANT):**
   - EVERY node must have a path from gateway (via sync OR async edges)
   - Frontend services: gateway → service (sync_http)
   - Async workers: gateway → service → queue → worker (async path is OK!)
   - Databases: at least one service → database (sync_db)
   - Caches: at least one service → cache (sync_cache)
   - Queues: at least one producer (async_produce) AND one consumer (async_consume)
   - External services: at least one service → external (sync_external)
   - EXCEPTION: Analytics/notification workers can be reached via queues only

3. **Async Edge Rules:**
   - async_produce: Service → Queue (NOT Service → Service) ✅
   - async_consume: Queue → Service (NOT Service → Queue) ✅
   - Every queue needs: at least 1 producer (async_produce) AND 1 consumer (async_consume)
   - If you write "service_a → service_b, type: async_produce", you're WRONG! Must be queue between them.

4. **Pipeline Pattern (if archetype=pipeline):**
   - Pipeline stages MUST be separated by queues
   - WRONG: upload_service → process_service (sync_http) ❌
   - CORRECT: upload_service → upload_queue (async_produce), upload_queue → process_service (async_consume) ✅
   - Each stage: Service → Queue → Service → Queue → Service...
   - NO direct Service → Service sync_http edges in pipelines!

5. **Realism:**
   - Gateway connects to frontend services (2-4 services) with sync_http
   - Frontend services connect to backend services with sync_http
   - Backend services connect to databases with sync_db
   - Services use caches with sync_cache (check cache first, then DB on miss)
   - Async pattern: Producer Service → Queue (async_produce), Queue → Worker Service (async_consume)
   - Async workers (analytics, notifications): Reachable via queue is VALID (no direct sync call needed)

**Node Types:**
- "RequestGateway": Entry point (single instance)
- "Service": Business logic (specify profile and replicas)
- "SqlDatabase": Persistence (specify replicas: 3)
- "ExternalCache": Redis/Memcached (specify replicas: 3)
- "MessageQueue": Kafka/SQS/RabbitMQ (specify replicas: 3)
- "ExternalService": Third-party APIs (Stripe/Twilio/CDN)

**Service Profiles (affects capacity planning):**
- "standard": Web apps, CRUD APIs (100-200 RPS per replica)
- "cpu_intensive": Transcoding, ML inference, compression (20-50 RPS per replica)
- "io_intensive": High DB usage, file processing (50-100 RPS per replica)
- "latency_sensitive": Real-time bidding, gaming, trading (50-100 RPS per replica)

**Replica Guidelines:**
- Standard services: 2-3 replicas
- Critical path services: 3-4 replicas
- CPU-intensive services: 4-6 replicas (need more parallelism)
- IO-intensive services: 2-3 replicas (bottleneck is DB, not service)

**Async Consumer Capacity (IMPORTANT):**
- When a service consumes from a queue, specify `async_consumer_capacity`
- This is the RPS this service can process from the queue
- cpu_intensive consumers: 20-50 RPS per replica
- io_intensive consumers: 50-100 RPS per replica
- standard consumers: 100-200 RPS per replica
- Example: transcoding_service with 4 replicas, cpu_intensive → async_consumer_capacity: 120 RPS

**BEFORE RETURNING JSON - MANDATORY CHECKLIST:**

[ ] 1. CYCLE CHECK: Draw service dependencies. Do any services form a loop? If YES, remove backwards edge.
[ ] 2. CONNECTIVITY CHECK: Can I reach every node from gateway (sync OR async path)? Async workers via queue OK!
[ ] 3. ASYNC CHECK: Does every async_produce target a Queue? Does every async_consume come from Queue?
[ ] 4. ORPHAN CHECK: Does every infrastructure node have incoming edges from services?
[ ] 5. FLOW CHECK: Do all nodes in flows exist in nodes[]?
[ ] 6. MINIMUM CHECK: Do I have enough nodes? (5+ services, 1+ DB, 1+ cache, 1+ queue, 1+ external)

**COMMON MISTAKES TO AVOID:**
❌ "service_a calls service_b, service_b calls service_a" = CYCLE (will fail validation)
❌ "cache_0 exists but no service connects to it" = DISCONNECTED (will fail validation)
❌ "async_produce: service_a → service_b" = WRONG TARGET (must be Queue)
❌ "Only 3 services total" = TOO SMALL (need 5+ minimum)
❌ "Pipeline with Service → Service edges" = WRONG PATTERN (must use Queues)

**VALID PATTERNS:**
✅ Analytics service only reachable via queue: gateway → svc → queue → analytics_service (VALID!)
✅ Notification worker only reachable via queue: gateway → svc → notif_queue → notif_worker (VALID!)
✅ Mixed sync/async: gateway → svc1 (sync) → queue (async) → svc2 (VALID!)

**HOW TO AVOID CYCLES:**
1. Number your services: service_1, service_2, service_3, ...
2. Lower-numbered services can call higher-numbered services
3. Higher-numbered services CANNOT call lower-numbered services
4. Example: gateway(0) → service_1 → service_2 → service_3 → database ✅
5. Example: service_1 → service_2 → service_1 = CYCLE ❌

If you follow these rules exactly, your topology will pass validation on the first try.
"""

    def _build_prompt(self, archetype: str, scale: str) -> str:
        # Define STRICT minimums for each scale
        scale_requirements = {
            "small": {
                "target_nodes": "8-12 application/infrastructure nodes",
                "min_services": 5,
                "min_databases": 1,
                "min_caches": 1,
                "min_queues": 3 if archetype == 'pipeline' else 1,
                "min_external": 1,
                "description": "A realistic production system, scaled down but complete"
            },
            "medium": {
                "target_nodes": "12-18 application/infrastructure nodes",
                "min_services": 8,
                "min_databases": 2,
                "min_caches": 2,
                "min_queues": 5 if archetype == 'pipeline' else 2,
                "min_external": 1,
                "description": "A full-featured production system"
            },
            "large": {
                "target_nodes": "25-35 application/infrastructure nodes",
                "min_services": 15,
                "min_databases": 3,
                "min_caches": 3,
                "min_queues": 6 if archetype == 'pipeline' else 3,
                "min_external": 2,
                "description": "An enterprise-scale production system"
            }
        }

        reqs = scale_requirements.get(scale, scale_requirements["medium"])
        target_nodes = reqs["target_nodes"]

        # Archetype-specific guidance with ANTI-CYCLE instructions
        archetype_guidance = {
            'hierarchical': '''Strict layers: Gateway -> Frontend -> Backend -> Data.
   Layer 1 (Frontend): gateway → [frontend_services] (sync_http)
   Layer 2 (Backend): [frontend_services] → [backend_services] (sync_http)
   Layer 3 (Data): [backend_services] → [databases/caches] (sync_db/sync_cache)
   RULE: Higher layers call lower layers only. No backwards calls!''',

            'mesh': '''High service-to-service connectivity BUT NO CYCLES.
   Strategy: Organize services in layers even if mesh-like.
   Layer 1: gateway → [core_services] (2-3 services)
   Layer 2: [core_services] → [specialized_services] (2-3 services)
   Layer 3: [specialized_services] → [data_services] (1-2 services)
   Services in same layer can call each other (peer-to-peer).
   Services CANNOT call services in higher layers (prevents cycles).
   All services connect to shared infrastructure (DB, cache, queue).''',

            'hub_spoke': '''One central orchestration service as hub.
   Layer 1: gateway → hub_service (the central orchestrator)
   Layer 2: hub_service → [spoke_services] (all spokes called by hub)
   Layer 3: [spoke_services] → [databases/caches] (data layer)
   RULE: Spokes do NOT call hub back (that creates cycle). Hub calls spokes.
   RULE: Spokes do NOT call other spokes directly (go through hub).''',

            'pipeline': '''Sequential processing stages with queues between them.
   Pattern: Service → Queue → Service → Queue → Service...
   Example: upload_svc → upload_q → validate_svc → validate_q → process_svc → process_q → publish_svc
   RULE: NO sync_http edges between services in pipeline! Must use queues.
   RULE: Need 3-6 queues minimum for proper stage separation.
   RULE: Each queue needs: 1 producer (async_produce) + 1 consumer (async_consume).'''
        }.get(archetype, 'Balanced architecture with mixed patterns.')

        # Diverse domain suggestions by archetype - avoiding repetition
        domain_suggestions = {
            'pipeline': 'Video Transcoding, Log Processing, Data ETL, IoT Telemetry',
            'hierarchical': 'Banking System, Healthcare Records, Content Management, SaaS Platform',
            'mesh': 'Social Network, Gaming Platform, Real-time Analytics, Collaborative Tools',
            'hub_spoke': 'Ride-sharing Dispatch, Smart Home Hub, API Gateway Platform, Workflow Engine'
        }.get(archetype, 'Any business domain')

        return f"""Design a **{scale}** ({target_nodes}) architecture using the **{archetype}** pattern.

1. **Domain:** Pick a business domain fitting this pattern (e.g., {domain_suggestions}). DO NOT use e-commerce if other examples are provided.
2. **Structure:**
   - {archetype_guidance}
3. **Flows:** Define specific request paths (e.g., "checkout": ["gateway", "cart_service", "payment_service", "db_0"]).

**IMPORTANT: Async Workers (Analytics, Notifications, etc.):**
If you include analytics_service or notification_service that only processes async jobs:
- Connect them via queues: main_service → events_queue → analytics_service
- They do NOT need direct sync_http from gateway (queue path is sufficient)
- Example: gateway → order_service → order_events_queue → analytics_service ✅
- This is VALID and will pass connectivity validation!

**MINIMUM QUALITY REQUIREMENTS FOR "{scale.upper()}":**
- At least {reqs['min_services']} Services
- At least {reqs['min_databases']} Database(s)
- At least {reqs['min_caches']} Cache(s)
- At least {reqs['min_queues']} Queue(s)
- At least {reqs['min_external']} External Service(s)
- Total: {reqs['target_nodes']}

{reqs['description']}

**CRITICAL:** These are MINIMUMS. A production system needs proper infrastructure.
Do NOT create toy examples with only 1-2 services.

**CRITICAL CONNECTIVITY RULES:**
- ALL nodes must be reachable from the gateway (directly or indirectly)
- Every Service must connect to at least one Database, Cache, Queue, or ExternalService
- Infrastructure nodes (DB, Cache, Queue, External) should have incoming edges from Services
- For large topologies, ensure fan-out: gateway connects to multiple frontends, frontends to multiple backends

**Required JSON Schema:**
```json
{{
  "meta": {{
    "architecture_name": "string",
    "archetype": "{archetype}",
    "domain": "string",
    "description": "string",
    "pros": ["string"],
    "cons": ["string"]
  }},
  "nodes": [
    {{
      "id": "gateway",
      "type": "RequestGateway"
    }},
    {{
      "id": "service_name",
      "type": "Service",
      "profile": "standard|cpu_intensive|io_intensive|latency_sensitive",
      "replicas": 3,
      "async_consumer_capacity": 100
    }}
  ],
  "edges": [
    {{ "source": "gateway", "target": "service_1", "type": "sync_http" }},
    {{ "source": "service_1", "target": "db_0", "type": "sync_db" }},
    {{ "source": "service_1", "target": "cache_0", "type": "sync_cache" }},
    {{ "source": "service_2", "target": "queue_0", "type": "async_produce" }},
    {{ "source": "queue_0", "target": "service_3", "type": "async_consume" }},
    {{ "source": "service_4", "target": "ext_0", "type": "sync_external" }}
  ],
  "flows": {{
    "GET": {{
      "gateway": ["service_1", "service_2"],
      "service_1": ["db_0"],
      "service_2": ["cache_0"]
    }},
    "POST": {{
      "gateway": ["service_3"],
      "service_3": ["db_0", "queue_0"]
    }}
  }}
}}
```

**Important:**
- Include flows for GET, POST, PUT, DELETE request types
- Each flow maps a node to its downstream dependencies
- Ensure all nodes are referenced in the edges
- Use descriptive node IDs (not just "service_1", but "cart_service", "payment_service", etc.)
- async_consumer_capacity is OPTIONAL but STRONGLY RECOMMENDED for services that consume from queues
  - Calculate: replicas × per-replica-capacity (e.g., 4 replicas × 30 RPS = 120)

Output ONLY JSON."""

    def _parse_json(self, text: str) -> Dict:
        # Helper to extract JSON from markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    def _json_to_networkx_skeleton(self, data: Dict) -> nx.DiGraph:
        """Builds a graph with ALL edges for connectivity checking."""
        G = nx.DiGraph()
        for edge in data['edges']:
            G.add_edge(edge['source'], edge['target'])
        return G

    def _build_sync_only_graph(self, data: Dict) -> nx.DiGraph:
        """Builds a graph with only synchronous edges for DAG checking."""
        G = nx.DiGraph()
        for edge in data['edges']:
            # Only track synchronous edges for cycle detection
            if 'async' not in edge['type']:
                G.add_edge(edge['source'], edge['target'])
        return G

    def _validate_dag(self, G: nx.DiGraph):
        """Validate no cycles in synchronous call graph."""
        if not nx.is_directed_acyclic_graph(G):
            try:
                cycle = nx.find_cycle(G)
                cycle_str = " → ".join(f"{u}" for u, v in cycle) + f" → {cycle[0][0]}"
                raise ValueError(
                    f"CYCLE DETECTED: {cycle_str}\n"
                    f"Fix: Remove one edge from this cycle. Usually the backwards edge.\n"
                    f"Tip: Organize services in layers. Higher layers can't call lower layers."
                )
            except nx.NetworkXNoCycle:
                raise ValueError("Topology contains a synchronous cycle (details unavailable)")

    def _validate_connectivity(self, G: nx.DiGraph):
        """Validate all nodes are reachable from gateway (if present)."""
        if len(G.nodes) == 0:
            return

        # Check if gateway exists
        if 'gateway' in G.nodes:
            # All nodes should be reachable from gateway
            reachable = nx.descendants(G, 'gateway')
            reachable.add('gateway')
            unreachable = set(G.nodes) - reachable

            if unreachable:
                unreachable_list = ", ".join(sorted(unreachable)[:5])
                if len(unreachable) > 5:
                    unreachable_list += f" (and {len(unreachable) - 5} more)"
                raise ValueError(
                    f"DISCONNECTED NODES: {unreachable_list} not reachable from gateway.\n"
                    f"Fix: Add edges from gateway (or services) to these nodes.\n"
                    f"Tip: Every service should be called by gateway or another service."
                )
        else:
            # No gateway - just check for weak connectivity
            G_undirected = G.to_undirected()
            if not nx.is_connected(G_undirected):
                components = list(nx.connected_components(G_undirected))
                sizes = [len(c) for c in components]
                raise ValueError(
                    f"DISCONNECTED GRAPH: {len(components)} separate components with sizes {sizes}.\n"
                    f"Fix: Add edges to connect all components together."
                )

    def _validate_node_types(self, data: Dict):
        valid_types = {'RequestGateway', 'Service', 'SqlDatabase', 'ExternalCache', 'MessageQueue', 'ExternalService'}
        for n in data['nodes']:
            if n['type'] not in valid_types:
                raise ValueError(f"Invalid node type: {n['type']}")

    def _validate_async_edges(self, data: Dict):
        """Validate async edges only connect to/from MessageQueues."""
        # Build node type map
        node_types = {n['id']: n['type'] for n in data['nodes']}

        errors = []
        for edge in data['edges']:
            source_type = node_types.get(edge['source'], 'unknown')
            target_type = node_types.get(edge['target'], 'unknown')
            edge_type = edge['type']

            # async_produce: source=any, target=MUST be MessageQueue
            if edge_type == 'async_produce':
                if target_type != 'MessageQueue':
                    errors.append(
                        f"async_produce edge {edge['source']} → {edge['target']}: "
                        f"target must be MessageQueue, got {target_type}"
                    )

            # async_consume: source=MUST be MessageQueue, target=any (usually Service)
            if edge_type == 'async_consume':
                if source_type != 'MessageQueue':
                    errors.append(
                        f"async_consume edge {edge['source']} → {edge['target']}: "
                        f"source must be MessageQueue, got {source_type}"
                    )

        if errors:
            raise ValueError(f"Invalid async edges:\n  " + "\n  ".join(errors))

    def _validate_minimum_requirements(self, data: Dict, archetype: str, scale: str):
        """Validate topology meets minimum quality requirements."""
        # Count node types
        type_counts = {}
        for node in data['nodes']:
            node_type = node['type']
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        # Define minimums (same as in _build_prompt)
        minimums = {
            "small": {
                "Service": 5,
                "SqlDatabase": 1,
                "ExternalCache": 1,
                "MessageQueue": 3 if archetype == 'pipeline' else 1,
                "ExternalService": 1
            },
            "medium": {
                "Service": 8,
                "SqlDatabase": 2,
                "ExternalCache": 2,
                "MessageQueue": 5 if archetype == 'pipeline' else 2,
                "ExternalService": 1
            },
            "large": {
                "Service": 15,
                "SqlDatabase": 3,
                "ExternalCache": 3,
                "MessageQueue": 6 if archetype == 'pipeline' else 3,
                "ExternalService": 2
            }
        }

        reqs = minimums.get(scale, minimums["medium"])

        errors = []
        for node_type, min_count in reqs.items():
            actual_count = type_counts.get(node_type, 0)
            if actual_count < min_count:
                errors.append(
                    f"{node_type}: need at least {min_count}, got {actual_count}"
                )

        if errors:
            raise ValueError(
                f"Topology does not meet minimum requirements for {scale} {archetype}:\n  "
                + "\n  ".join(errors)
            )

    def convert_to_simulation_graph(self, data: Dict) -> nx.DiGraph:
        """Converts the JSON to the full NetworkX graph used by simulation."""
        G = nx.DiGraph()

        # 1. Add Nodes
        services = []  # Track services for Pod generation
        for node in data['nodes']:
            attrs = {
                'type': node['type'],
                'role': self._infer_role(node['type']),
                'service_name': node['id'], # Semantic name
                'semantic_name': node['id'],
                # Default resources if not specified
                'resource_profile': node.get('profile', 'standard'),
                'desired_replicas': node.get('replicas', 3)
            }

            if attrs['role'] == 'gateway':
                attrs['is_frontend'] = True

            # Services support all HTTP methods
            if attrs['role'] == 'service':
                attrs['supported_request_types'] = ['GET', 'POST', 'PUT', 'DELETE']
                attrs['processing_pipeline'] = None  # Will be set during wiring
                services.append(node['id'])

            G.add_node(node['id'], **attrs)

        # 2. Add Edges
        for edge in data['edges']:
            # Assign physical latency based on edge type
            latency = 50.0 if edge['type'] == 'sync_external' else 2.0 if edge['type'] == 'sync_db' else 5.0
            G.add_edge(edge['source'], edge['target'],
                      type=edge['type'],
                      base_latency=latency)

        # 3. Add Service/Pod/Node Architecture (matching procedural generator)
        # Calculate pods and nodes needed
        total_pods = len(services) * 3  # 3 pods per service (default, will be overridden by capacity planner)
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
        # FIXED: Respect desired_replicas instead of hardcoding to 3
        node_idx = 0
        for svc in services:
            svc_data = G.nodes[svc]
            num_replicas = svc_data.get('desired_replicas', 3)

            for pod_num in range(num_replicas):
                pod_id = f'pod_{svc}_{pod_num}'
                target_node = nodes[node_idx % num_nodes]

                G.add_node(pod_id,
                          type='Pod',
                          role='pod',
                          parent_service=svc,
                          compute_node=target_node)

                # Add edges: Service → Pod (pod_pool), Pod → Node (pod_placement)
                G.add_edge(svc, pod_id, type='pod_pool', base_latency=0.0)
                G.add_edge(pod_id, target_node, type='pod_placement', base_latency=0.0)

                node_idx += 1

        # Create DeploymentController
        G.add_node('deployment_controller',
                  type='DeploymentController',
                  role='controller')

        # 4. Attach Metadata & Flows
        G.graph['meta'] = data.get('meta', {})
        G.graph['request_flows'] = data.get('flows', {})

        return G

    def _infer_role(self, type_str: str) -> str:
        type_map = {
            'RequestGateway': 'gateway',
            'Service': 'service',
            'SqlDatabase': 'database',
            'ExternalCache': 'cache',
            'MessageQueue': 'queue',
            'ExternalService': 'external'
        }
        return type_map.get(type_str, 'service')
