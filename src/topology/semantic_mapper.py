"""
Semantic Mapper - Domain-Adaptive Topology Intelligence

This module analyzes raw NetworkX graphs and assigns domain-specific semantics using Claude AI.
It transforms generic topologies into realistic business architectures (E-commerce, Video Streaming, etc.)
with deterministic request flows and resource profiles.
"""
import os
import json
import networkx as nx
from typing import Dict, Optional
from anthropic import Anthropic


class SemanticMapper:
    """
    Analyzes graph structure and applies domain-specific semantics using Claude AI.

    The mapper:
    1. Converts topology to LLM-friendly format
    2. Calls Claude to analyze and assign domain
    3. Returns semantic overlay with:
       - Domain identification
       - Service names and roles
       - Resource profiles (cpu_intensive, io_intensive, etc.)
       - Deterministic request flows
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20250929"):
        """
        Initialize semantic mapper.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.client = Anthropic(api_key=self.api_key) if self.api_key else None

    def generate_semantic_overlay(self, topology_graph: nx.DiGraph) -> Dict:
        """
        Generate semantic overlay for a topology graph.

        Args:
            topology_graph: NetworkX directed graph with node/edge attributes

        Returns:
            Dictionary with domain, services, request_types, and request_flows
        """
        if not self.client:
            # Fallback to deterministic heuristic if no API key
            return self._generate_heuristic_overlay(topology_graph)

        try:
            # Convert graph to LLM-friendly format
            graph_repr = self._serialize_graph_for_llm(topology_graph)

            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self._get_system_prompt(),
                messages=[{
                    "role": "user",
                    "content": f"Analyze this topology and assign domain-specific semantics:\n\n{json.dumps(graph_repr, indent=2)}"
                }]
            )

            # Parse response
            response_text = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            try:
                if "```json" in response_text:
                    json_start = response_text.index("```json") + 7
                    json_end = response_text.index("```", json_start)
                    json_text = response_text[json_start:json_end].strip()
                elif "```" in response_text:
                    json_start = response_text.index("```") + 3
                    json_end = response_text.index("```", json_start)
                    json_text = response_text[json_start:json_end].strip()
                else:
                    json_text = response_text.strip()

                semantic_overlay = json.loads(json_text)
            except (ValueError, json.JSONDecodeError) as parse_error:
                print(f"Warning: Failed to parse Claude response as JSON: {parse_error}")
                print(f"Response text: {response_text[:200]}...")
                raise

            # Validate the overlay structure
            self._validate_overlay(semantic_overlay, topology_graph)

            return semantic_overlay

        except Exception as e:
            print(f"Warning: Claude API call failed ({e}), falling back to heuristic overlay")
            return self._generate_heuristic_overlay(topology_graph)

    def _serialize_graph_for_llm(self, graph: nx.DiGraph) -> Dict:
        """
        Convert NetworkX graph to token-efficient JSON for LLM.

        Args:
            graph: NetworkX directed graph

        Returns:
            Compact graph representation
        """
        nodes = []
        for node_id, attrs in graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "role": attrs.get("role", "unknown"),
                "is_frontend": attrs.get("is_frontend", False)
            })

        edges = []
        for source, target, attrs in graph.edges(data=True):
            edges.append({
                "source": source,
                "target": target,
                "type": attrs.get("type", "sync")
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "num_nodes": len(nodes),
            "num_edges": len(edges)
        }

    def _get_system_prompt(self) -> str:
        """
        Get the system prompt for Claude API.

        Returns:
            System prompt instructing Claude how to analyze topology
        """
        return """You are a microservices architecture expert. Analyze the provided topology graph and assign domain-specific semantics.

Your task:
1. Analyze the graph structure (topology, connectivity patterns, node roles)
2. Select the MOST FITTING domain from: [e-commerce, video_streaming, supply_chain, iot_fleet, fintech]
3. Assign domain-specific service names (e.g., "TranscodeService", "InventoryManager", "PaymentProcessor")
4. Assign resource profiles to each service:
   - "standard": Normal compute/memory requirements
   - "cpu_intensive": High CPU usage (video encoding, ML inference, crypto)
   - "io_intensive": High I/O usage (databases, caches, log aggregation)
   - "latency_sensitive": Time-critical services (payment processing, trading)
5. Define deterministic request flows showing which services call which for each request type

Guidelines for domain selection - VARY YOUR CHOICES:
- Linear chains suggest media pipelines (video_streaming)
- Hub-and-spoke patterns with high fan-out suggest e-commerce/retail
- Many external APIs suggest supply_chain (3rd party integrations)
- Message queue heavy architectures suggest iot_fleet (sensor data processing)
- Latency-sensitive services with databases suggest fintech (trading, payments)
- Services with many incoming connections are likely databases/caches (io_intensive)
- Mesh patterns with moderate connectivity can be any domain - use variety

IMPORTANT: Do NOT default to e-commerce! Actively consider all 5 domains and pick the best fit.
If the topology could fit multiple domains, rotate through options to ensure diversity.

IMPORTANT CONSTRAINTS:
- request_types MUST be HTTP methods: ["GET", "POST", "PUT", "DELETE"] - DO NOT use domain-specific names
- request_flows MUST use these HTTP methods as keys
- request_flows MUST be CONNECTED - every service must be reachable from a frontend/gateway
- DO NOT include services in flows that have no path from the entry point

Output ONLY valid JSON in this EXACT format:
{
  "domain": "video_streaming",
  "services": {
    "node_id": {
      "name": "ServiceName",
      "role": "service",
      "profile": "cpu_intensive"
    }
  },
  "request_types": ["GET", "POST"],
  "request_flows": {
    "GET": {
      "gateway": ["node_1"],
      "node_1": ["node_2", "node_3"]
    },
    "POST": {
      "gateway": ["node_1"],
      "node_1": ["node_4"]
    }
  }
}

Key rules:
- EVERY node in the topology MUST appear in the "services" dict
- Request flows MUST be deterministic (no randomness)
- request_types MUST be HTTP methods (GET, POST, PUT, DELETE) not domain-specific names
- Frontend nodes (is_frontend=true) should be entry points in request_flows
- Each request flow should form a valid path through the topology
"""

    def _generate_heuristic_overlay(self, graph: nx.DiGraph) -> Dict:
        """
        Generate deterministic heuristic overlay when API is unavailable.

        Args:
            graph: NetworkX directed graph

        Returns:
            Heuristic semantic overlay
        """
        # Analyze graph structure to pick domain
        num_nodes = len(graph.nodes())
        avg_degree = sum(dict(graph.degree()).values()) / num_nodes if num_nodes > 0 else 0

        # Count node types for domain hints
        queue_count = sum(1 for _, d in graph.nodes(data=True) if d.get('role') == 'queue')
        external_count = sum(1 for _, d in graph.nodes(data=True) if d.get('role') == 'external')

        # Heuristic domain selection with variety
        # IMPORTANT: Use HTTP methods for request types, not domain-specific names
        # Use graph hash to add deterministic pseudo-randomness for variety
        graph_hash = hash(frozenset(graph.edges())) % 5

        if avg_degree < 2:
            # Linear/chain topology
            domain = "video_streaming"  # Linear = streaming pipeline
            request_types = ["GET", "POST"]
        elif queue_count >= 2:
            # Queue-heavy suggests IoT or event-driven
            domain = "iot_fleet"
            request_types = ["GET", "POST", "PUT"]
        elif external_count >= 2:
            # Many external dependencies suggest supply chain
            domain = "supply_chain"
            request_types = ["GET", "POST", "PUT", "DELETE"]
        elif avg_degree > 4:
            # Very highly connected = e-commerce or fintech
            domain = "fintech" if graph_hash % 2 == 0 else "e-commerce"
            request_types = ["GET", "POST", "PUT", "DELETE"]
        else:
            # Moderate connectivity - rotate through domains
            domains = ["e-commerce", "video_streaming", "supply_chain", "iot_fleet", "fintech"]
            domain = domains[graph_hash]
            request_types = ["GET", "POST", "PUT", "DELETE"]

        # Assign service names and profiles
        services = {}
        for node_id, attrs in graph.nodes(data=True):
            role = attrs.get("role", "service")

            if role == "gateway":
                name = "ApiGateway"
                profile = "standard"
            elif role == "service":
                # Check connectivity to infer profile
                in_degree = graph.in_degree(node_id)
                out_degree = graph.out_degree(node_id)

                if in_degree > 2:
                    name = f"HubService_{node_id}"
                    profile = "cpu_intensive"
                elif out_degree == 0:
                    name = f"LeafService_{node_id}"
                    profile = "io_intensive"
                else:
                    name = f"Service_{node_id}"
                    profile = "standard"
            elif role == "database":
                name = f"Database_{node_id}"
                profile = "io_intensive"
            elif role == "cache":
                name = f"Cache_{node_id}"
                profile = "io_intensive"
            elif role == "queue":
                name = f"MessageQueue_{node_id}"
                profile = "io_intensive"
            elif role == "external":
                name = f"ExternalService_{node_id}"
                profile = "latency_sensitive"
            else:
                name = f"Component_{node_id}"
                profile = "standard"

            services[node_id] = {
                "name": name,
                "role": role,
                "profile": profile
            }

        # Generate simple BFS-based request flows
        request_flows = {}
        for request_type in request_types:
            flow = {}

            # Find frontend nodes as starting points
            frontends = [n for n, d in graph.nodes(data=True) if d.get("is_frontend")]
            if not frontends:
                # Fallback: nodes with no predecessors
                frontends = [n for n in graph.nodes() if graph.in_degree(n) == 0]

            # Build flows using BFS from each frontend
            visited = set()
            for frontend in frontends:
                queue = [frontend]
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    visited.add(current)

                    # Get downstream nodes
                    successors = list(graph.successors(current))
                    if successors:
                        flow[current] = successors
                        queue.extend(successors)

            request_flows[request_type] = flow

        return {
            "domain": domain,
            "services": services,
            "request_types": request_types,
            "request_flows": request_flows
        }

    def _validate_overlay(self, overlay: Dict, graph: nx.DiGraph):
        """
        Validate that the semantic overlay is well-formed.

        Args:
            overlay: Semantic overlay dictionary
            graph: Original topology graph

        Raises:
            ValueError: If overlay is invalid
        """
        required_keys = ["domain", "services", "request_types", "request_flows"]
        for key in required_keys:
            if key not in overlay:
                raise ValueError(f"Missing required key in semantic overlay: {key}")

        # Validate all nodes are covered
        node_ids = set(graph.nodes())
        service_ids = set(overlay["services"].keys())

        if node_ids != service_ids:
            missing = node_ids - service_ids
            extra = service_ids - node_ids
            raise ValueError(f"Node mismatch in semantic overlay. Missing: {missing}, Extra: {extra}")

        # Validate service profiles
        valid_profiles = {"standard", "cpu_intensive", "io_intensive", "latency_sensitive"}
        for node_id, service_data in overlay["services"].items():
            if "profile" not in service_data:
                raise ValueError(f"Service {node_id} missing 'profile'")
            if service_data["profile"] not in valid_profiles:
                raise ValueError(f"Invalid profile for {node_id}: {service_data['profile']}")

        # Validate request types are HTTP methods
        valid_http_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        for request_type in overlay.get("request_types", []):
            if request_type not in valid_http_methods:
                print(f"Warning: Non-HTTP request type '{request_type}' - should use HTTP methods")

        # Validate request flows reference valid nodes
        for request_type, flow in overlay["request_flows"].items():
            # Check for connected flows (all nodes should be reachable from frontends)
            flow_nodes = set(flow.keys())
            for source, targets in flow.items():
                if source not in node_ids:
                    raise ValueError(f"Request flow references unknown source node: {source}")
                for target in targets:
                    if target not in node_ids:
                        raise ValueError(f"Request flow references unknown target node: {target}")
                    flow_nodes.add(target)

            # Find frontend/gateway nodes
            frontends = [n for n, d in graph.nodes(data=True) if d.get('is_frontend') or d.get('role') == 'gateway']

            # Check if all nodes in flow are reachable from a frontend
            if frontends:
                reachable = set(frontends)
                changed = True
                while changed:
                    changed = False
                    for source in list(reachable):
                        if source in flow:
                            for target in flow[source]:
                                if target not in reachable:
                                    reachable.add(target)
                                    changed = True

                # Warn about unreachable nodes
                unreachable = flow_nodes - reachable
                if unreachable:
                    print(f"Warning: Request flow '{request_type}' has unreachable nodes: {unreachable}")
