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
                G = self._json_to_networkx_skeleton(topology_data)

                # 3. Rigorous Validation
                self._validate_dag(G)
                self._validate_connectivity(G)
                self._validate_node_types(topology_data)

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
        return """You are a Principal Software Architect.
Your goal is to design realistic, fault-tolerant distributed system topologies for simulation.
You must output STRICT JSON matching the schema provided.

**Constraints:**
1. **No Cycles:** Synchronous calls (RPC/HTTP/DB) MUST NOT form loops.
2. **Connectivity:** All services must be reachable from the Gateway.
3. **Realism:** Use Cache-Aside for DBs. Use Queues for async decoupling.
4. **Flows:** Explicitly define the call trace for 3-5 major business operations.

**Node Types:**
- "RequestGateway" (The entry point)
- "Service" (Business logic)
- "SqlDatabase" (Persistence)
- "ExternalCache" (Redis/Memcached)
- "MessageQueue" (Kafka/SQS)
- "ExternalService" (Stripe/Twilio)

**Service Profiles:**
- "standard": Web apps.
- "cpu_intensive": Transcoding, ML.
- "io_intensive": High DB usage.
- "latency_sensitive": Real-time bidding.
"""

    def _build_prompt(self, archetype: str, scale: str) -> str:
        # Define node counts based on scale
        target_nodes = {"small": "5-8", "medium": "12-18", "large": "25-35"}.get(scale, "12-18")

        # Archetype-specific guidance
        archetype_guidance = {
            'hierarchical': 'Strict layers: Gateway -> Frontend -> Backend -> Data.',
            'mesh': 'High service-to-service connectivity.',
            'hub_spoke': 'One central orchestration service.',
            'pipeline': 'Sequential processing stages with queues between them.'
        }.get(archetype, 'Balanced architecture with mixed patterns.')

        # Diverse domain suggestions by archetype - avoiding repetition
        domain_suggestions = {
            'pipeline': 'Video Transcoding, Log Processing, Data ETL, IoT Telemetry',
            'hierarchical': 'Banking System, Healthcare Records, Content Management, SaaS Platform',
            'mesh': 'Social Network, Gaming Platform, Real-time Analytics, Collaborative Tools',
            'hub_spoke': 'Ride-sharing Dispatch, Smart Home Hub, API Gateway Platform, Workflow Engine'
        }.get(archetype, 'Any business domain')

        return f"""Design a **{scale}** ({target_nodes} nodes) architecture using the **{archetype}** pattern.

1. **Domain:** Pick a business domain fitting this pattern (e.g., {domain_suggestions}). DO NOT use e-commerce if other examples are provided.
2. **Structure:**
   - {archetype_guidance}
3. **Flows:** Define specific request paths (e.g., "checkout": ["gateway", "cart_service", "payment_service", "db_0"]).

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
      "replicas": 3
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

Output ONLY JSON."""

    def _parse_json(self, text: str) -> Dict:
        # Helper to extract JSON from markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    def _json_to_networkx_skeleton(self, data: Dict) -> nx.DiGraph:
        """Builds a lightweight graph just for validation."""
        G = nx.DiGraph()
        for edge in data['edges']:
            # Only track synchronous edges for DAG checking
            if 'async' not in edge['type']:
                G.add_edge(edge['source'], edge['target'])
        return G

    def _validate_dag(self, G: nx.DiGraph):
        if not nx.is_directed_acyclic_graph(G):
            try:
                cycle = nx.find_cycle(G)
                raise ValueError(f"Topology contains a synchronous cycle: {cycle}")
            except:
                raise ValueError("Topology contains a synchronous cycle")

    def _validate_connectivity(self, G: nx.DiGraph):
        # Simplified check: Ensure graph isn't just islands
        if len(G.nodes) > 0 and len(list(G.nodes())) > 1:
            # Build undirected version to check weak connectivity
            G_undirected = G.to_undirected()
            if not nx.is_connected(G_undirected):
                raise ValueError("Topology has disconnected components")

    def _validate_node_types(self, data: Dict):
        valid_types = {'RequestGateway', 'Service', 'SqlDatabase', 'ExternalCache', 'MessageQueue', 'ExternalService'}
        for n in data['nodes']:
            if n['type'] not in valid_types:
                raise ValueError(f"Invalid node type: {n['type']}")

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
        node_idx = 0
        for svc in services:
            for pod_num in range(3):  # 3 pods per service (will be overridden by capacity planner)
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
