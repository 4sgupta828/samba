"""
LLM-based Fault Propagation Predictor.

Predicts how a fault will propagate through a distributed system given:
- A topology (graph structure)
- A fault injection point (specific node)
- A fault type (e.g., cpu_saturation, slow_queries)

Returns expected propagation patterns including:
- Direct impact (0-hop: the faulty node itself)
- 1-hop impact (immediate dependencies)
- 2-hop+ impact (cascading effects)
- Hidden impacts (shared compute nodes, async paths, etc.)
- Propagation mechanisms (latency buildup, backpressure, resource starvation)
- Expected symptoms per component
"""
import json
import os
import networkx as nx
from typing import Dict, Any, List
from anthropic import Anthropic


class LLMFaultPropagationPredictor:
    """
    Predicts fault propagation patterns using LLM reasoning.
    """

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize the LLM Fault Propagation Predictor.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use (default: claude-sonnet-4-20250514)
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def predict_propagation(
        self,
        topology: nx.DiGraph,
        fault_node_id: str,
        fault_type: str,
        fault_params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Predict how a fault will propagate through the system.

        Args:
            topology: NetworkX graph representing the system topology
            fault_node_id: The node where the fault is injected
            fault_type: The type of fault (e.g., 'cpu_saturation', 'slow_queries')
            fault_params: Fault-specific parameters (e.g., {'cpu_percent': 95})

        Returns:
            Dictionary with:
            - fault_summary: High-level description of the fault
            - impact_timeline: Expected chronological sequence of impacts
            - impact_by_hop: Impacts grouped by distance from fault node
              - 0-hop (fault node itself): symptoms, degradation level
              - 1-hop (direct dependencies): symptoms, propagation mechanism
              - 2-hop (indirect dependencies): symptoms, propagation mechanism
            - hidden_impacts: Non-obvious impacts (shared compute, async paths)
            - propagation_mechanisms: How the fault spreads (e.g., latency buildup, backpressure)
            - critical_paths: Which request flows are most affected
            - expected_recovery: How the system should recover when fault is reverted
        """
        # Build topology context
        topology_context = self._build_propagation_context(topology, fault_node_id)

        # Call LLM
        prompt = self._build_propagation_prompt(
            topology_context,
            fault_node_id,
            fault_type,
            fault_params or {}
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,  # Need more tokens for detailed propagation analysis
            system=self._get_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse response
        response_text = response.content[0].text
        prediction = self._parse_propagation_response(response_text)

        return prediction

    def _build_propagation_context(
        self,
        topology: nx.DiGraph,
        fault_node_id: str
    ) -> Dict[str, Any]:
        """
        Build context for propagation analysis.

        Includes:
        - Fault node details
        - N-hop neighbors (upstream and downstream)
        - Shared resources (compute nodes)
        - Request flows that traverse the fault node
        """
        if fault_node_id not in topology:
            raise ValueError(f"Fault node {fault_node_id} not found in topology")

        fault_node_data = topology.nodes[fault_node_id]

        # Get N-hop neighborhoods
        # Downstream (fault propagates forward)
        downstream_1hop = list(topology.successors(fault_node_id))
        downstream_2hop = set()
        for node in downstream_1hop:
            downstream_2hop.update(topology.successors(node))
        downstream_2hop = list(downstream_2hop - set(downstream_1hop) - {fault_node_id})

        # Upstream (backpressure propagates backward)
        upstream_1hop = list(topology.predecessors(fault_node_id))
        upstream_2hop = set()
        for node in upstream_1hop:
            upstream_2hop.update(topology.predecessors(node))
        upstream_2hop = list(upstream_2hop - set(upstream_1hop) - {fault_node_id})

        # Build neighborhood details
        def get_node_details(node_id):
            if node_id not in topology:
                return None
            data = topology.nodes[node_id]
            return {
                'id': node_id,
                'type': data.get('type', 'Unknown'),
                'role': data.get('role', 'Unknown'),
                'profile': data.get('resource_profile'),
                'compute_node': data.get('compute_node'),
                'parent_service': data.get('parent_service')
            }

        neighborhood = {
            'fault_node': get_node_details(fault_node_id),
            'downstream_1hop': [get_node_details(n) for n in downstream_1hop if get_node_details(n)],
            'downstream_2hop': [get_node_details(n) for n in downstream_2hop if get_node_details(n)],
            'upstream_1hop': [get_node_details(n) for n in upstream_1hop if get_node_details(n)],
            'upstream_2hop': [get_node_details(n) for n in upstream_2hop if get_node_details(n)]
        }

        # Get edges involving fault node
        edges_from_fault = [
            {
                'source': fault_node_id,
                'target': target,
                'type': topology.edges[fault_node_id, target].get('type', 'unknown')
            }
            for target in topology.successors(fault_node_id)
        ]

        edges_to_fault = [
            {
                'source': source,
                'target': fault_node_id,
                'type': topology.edges[source, fault_node_id].get('type', 'unknown')
            }
            for source in topology.predecessors(fault_node_id)
        ]

        # Identify shared compute nodes (for noisy neighbor effects)
        fault_compute_node = fault_node_data.get('compute_node')
        colocated_pods = []
        if fault_compute_node:
            for node_id, data in topology.nodes(data=True):
                if (data.get('role') == 'pod' and
                    data.get('compute_node') == fault_compute_node and
                    node_id != fault_node_id):
                    colocated_pods.append(get_node_details(node_id))

        # Extract request flows that traverse the fault node
        request_flows = topology.graph.get('request_flows', {})
        affected_flows = {}
        for flow_type, flow_map in request_flows.items():
            if fault_node_id in flow_map:
                affected_flows[flow_type] = flow_map[fault_node_id]

        return {
            'neighborhood': neighborhood,
            'edges_from_fault': edges_from_fault,
            'edges_to_fault': edges_to_fault,
            'colocated_pods': colocated_pods,
            'affected_flows': affected_flows
        }

    def _build_propagation_prompt(
        self,
        context: Dict[str, Any],
        fault_node_id: str,
        fault_type: str,
        fault_params: Dict[str, Any]
    ) -> str:
        """Build the LLM prompt for propagation prediction."""

        # Fault type descriptions with propagation characteristics
        fault_descriptions = {
            'cpu_saturation': {
                'desc': 'CPU pinned to high % with scheduler contention lag',
                'primary_symptom': 'High latency, thread queueing',
                'propagates_via': 'Latency buildup in upstream callers'
            },
            'memory_leak': {
                'desc': 'Progressive memory increase per request',
                'primary_symptom': 'Growing memory usage, eventual OOM',
                'propagates_via': 'Service restarts, traffic redistribution'
            },
            'memory_pressure': {
                'desc': 'High baseline memory usage',
                'primary_symptom': 'Slow GC, reduced capacity',
                'propagates_via': 'Reduced throughput, latency spikes'
            },
            'inject_latency': {
                'desc': 'Additive latency on all operations',
                'primary_symptom': 'Slow responses',
                'propagates_via': 'Timeout cascades, backpressure to callers'
            },
            'inject_errors': {
                'desc': 'Baseline error rate increase',
                'primary_symptom': 'Failed requests, retries',
                'propagates_via': 'Error propagation, retry storms'
            },
            'slow_queries': {
                'desc': 'Database query latency floor',
                'primary_symptom': 'Slow DB queries',
                'propagates_via': 'Thread pool exhaustion in DB clients, latency buildup'
            },
            'connection_exhaustion': {
                'desc': 'Database connection pool starvation',
                'primary_symptom': 'Connection waits, queueing',
                'propagates_via': 'Request queueing in clients, eventual timeouts'
            },
            'enable_background_job': {
                'desc': 'Database VACUUM/cleanup CPU contention',
                'primary_symptom': 'Increased DB CPU, query latency',
                'propagates_via': 'Similar to slow_queries - affects all DB clients'
            },
            'inject_db_wear': {
                'desc': 'Database index bloat/fragmentation',
                'primary_symptom': 'Progressive query slowdown',
                'propagates_via': 'Gradual latency increase in all DB clients'
            },
            'cache_failure': {
                'desc': 'Cache hit rate degradation + latency',
                'primary_symptom': 'Cache misses, increased DB load',
                'propagates_via': 'Thundering herd to database, DB overload'
            },
            'queue_consumer_slowdown': {
                'desc': 'Message processing latency',
                'primary_symptom': 'Growing queue depth, message lag',
                'propagates_via': 'Async tasks delayed, eventual backlog'
            },
            'noisy_neighbor': {
                'desc': 'CPU pinning on aggressor pod (shared compute)',
                'primary_symptom': 'CPU contention, steal time',
                'propagates_via': 'Other pods on same node experience CPU starvation'
            },
            'hot_shard': {
                'desc': 'Traffic skew to specific pod (80% to target)',
                'primary_symptom': 'Overloaded pod, high latency',
                'propagates_via': 'Pod overload while others idle'
            },
            'network_partition': {
                'desc': 'Bidirectional link blocking',
                'primary_symptom': 'Connection failures, timeouts',
                'propagates_via': 'Immediate failure for partitioned path'
            },
            'force_deadlock': {
                'desc': 'Thread locking without CPU consumption',
                'primary_symptom': 'Thread exhaustion, request queueing',
                'propagates_via': 'Requests hang, eventual timeout cascades'
            }
        }

        fault_info = fault_descriptions.get(fault_type, {
            'desc': fault_type,
            'primary_symptom': 'Unknown',
            'propagates_via': 'Unknown'
        })

        return f"""You are a distributed systems reliability engineer specializing in fault analysis.

**Task:** Predict how a fault will propagate through a distributed system topology.

**Fault Details:**
- **Node:** `{fault_node_id}` (Type: {context['neighborhood']['fault_node']['type']}, Role: {context['neighborhood']['fault_node']['role']})
- **Fault Type:** `{fault_type}` - {fault_info['desc']}
- **Primary Symptom:** {fault_info['primary_symptom']}
- **Typical Propagation:** {fault_info['propagates_via']}
- **Fault Parameters:** {json.dumps(fault_params, indent=2)}

**Topology Context:**

**Fault Node:**
{json.dumps(context['neighborhood']['fault_node'], indent=2)}

**Downstream Dependencies (1-hop):**
{json.dumps(context['neighborhood']['downstream_1hop'], indent=2)}

**Downstream Dependencies (2-hop):**
{json.dumps(context['neighborhood']['downstream_2hop'], indent=2)}

**Upstream Callers (1-hop):**
{json.dumps(context['neighborhood']['upstream_1hop'], indent=2)}

**Upstream Callers (2-hop):**
{json.dumps(context['neighborhood']['upstream_2hop'], indent=2)}

**Edges From Fault Node:**
{json.dumps(context['edges_from_fault'], indent=2)}

**Edges To Fault Node:**
{json.dumps(context['edges_to_fault'], indent=2)}

**Colocated Pods (Same Compute Node):**
{json.dumps(context['colocated_pods'], indent=2)}

**Affected Request Flows:**
{json.dumps(context['affected_flows'], indent=2)}

**Your Task:**
Predict the complete fault propagation pattern. Consider:

1. **Direct Impact (0-hop):** What happens to the fault node itself?
2. **Downstream Impact (1-hop, 2-hop):** How does the fault propagate to dependencies?
3. **Upstream Impact (backpressure):** How do callers react to the failing component?
4. **Hidden Impacts:** Non-obvious effects:
   - Shared compute nodes (noisy neighbor effects)
   - Async consumers lagging behind
   - Cache layers becoming ineffective
   - Retry storms amplifying load
5. **Propagation Mechanisms:** HOW does the fault spread?
   - Latency buildup and timeout cascades
   - Resource exhaustion (threads, connections, memory)
   - Backpressure and queueing
   - Error propagation and retry storms
6. **Timeline:** Expected sequence of events (e.g., "0-30s: latency increases, 30-60s: timeouts begin, 60s+: upstream services degrade")
7. **Critical Paths:** Which request flows are most impacted?

**Output Format:**
Return a JSON object:

```json
{{
  "fault_summary": "High-level description of what this fault does and expected severity",
  "impact_timeline": [
    {{"time_range": "0-30s", "event": "Fault node latency increases to 500ms"}},
    {{"time_range": "30-60s", "event": "Upstream services begin experiencing timeouts"}},
    {{"time_range": "60s+", "event": "Gateway error rate increases, cascading failures"}}
  ],
  "impact_by_hop": {{
    "0-hop": {{
      "nodes": ["{fault_node_id}"],
      "symptoms": ["High CPU", "Latency 500ms", "Thread queueing"],
      "severity": "CRITICAL"
    }},
    "1-hop": {{
      "nodes": ["node1", "node2"],
      "symptoms": ["Slow responses from dependency", "Timeout increase"],
      "propagation_mechanism": "Latency buildup - clients wait for slow responses",
      "severity": "MAJOR"
    }},
    "2-hop": {{
      "nodes": ["node3", "node4"],
      "symptoms": ["Cascading timeouts", "Reduced throughput"],
      "propagation_mechanism": "Backpressure from 1-hop nodes",
      "severity": "MINOR"
    }}
  }},
  "hidden_impacts": [
    {{
      "affected_nodes": ["pod_X", "pod_Y"],
      "mechanism": "Shared compute node - CPU contention affects colocated pods",
      "expected_symptoms": ["Intermittent latency spikes", "CPU steal time"]
    }}
  ],
  "propagation_mechanisms": [
    "Latency buildup: Slow responses cascade to callers",
    "Thread exhaustion: Clients run out of threads waiting for responses",
    "Backpressure: Upstream services slow down to avoid overwhelming fault node"
  ],
  "critical_paths": [
    {{"flow": "GET /api/resource", "impact": "HIGH", "reason": "All GET requests traverse fault node"}},
    {{"flow": "POST /api/resource", "impact": "NONE", "reason": "POST requests use different path"}}
  ],
  "expected_recovery": {{
    "recovery_order": ["{fault_node_id}", "1-hop nodes", "2-hop nodes"],
    "recovery_time_estimate": "30-60s after fault revert",
    "recovery_mechanism": "Latency returns to normal, queued requests complete, backpressure releases"
  }}
}}
```

Be specific and technical. Focus on MECHANISMS of propagation, not just symptoms.
Output ONLY JSON."""

    def _get_system_prompt(self) -> str:
        """System prompt for the LLM."""
        return """You are an expert in distributed systems fault analysis and failure propagation.

Your role is to predict how faults propagate through complex distributed systems.

You must consider:
- Direct dependencies (synchronous calls, database queries)
- Indirect dependencies (async messaging, shared resources)
- Backpressure effects (upstream callers react to slow/failing components)
- Hidden resource sharing (compute nodes, network paths)
- Cascading failures (timeouts, retry storms, thundering herds)
- Recovery patterns (how the system heals after fault revert)

Be precise about MECHANISMS of propagation (e.g., "latency buildup causes thread pool exhaustion" not just "services get slow").

Output STRICT JSON matching the requested schema."""

    def _parse_propagation_response(self, response_text: str) -> Dict[str, Any]:
        """Parse LLM response into structured prediction."""
        # Extract JSON from markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        try:
            prediction = json.loads(response_text.strip())

            # Validate structure
            required_keys = {
                'fault_summary',
                'impact_timeline',
                'impact_by_hop',
                'propagation_mechanisms',
                'expected_recovery'
            }

            if not required_keys.issubset(prediction.keys()):
                raise ValueError(f"Prediction missing required keys: {required_keys - prediction.keys()}")

            return prediction

        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response: {e}")
            print(f"Response: {response_text[:500]}")
            # Return empty prediction
            return {
                'fault_summary': 'Failed to parse LLM prediction',
                'impact_timeline': [],
                'impact_by_hop': {},
                'hidden_impacts': [],
                'propagation_mechanisms': [],
                'critical_paths': [],
                'expected_recovery': {}
            }
