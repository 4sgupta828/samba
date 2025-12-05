"""
LLM-based Fault Target Selector.

Uses an LLM to intelligently identify viable fault injection targets given:
- A topology (graph structure with node types, roles, connections)
- A fault type (e.g., cpu_saturation, memory_leak, slow_queries)

Returns ranked candidates with reasoning about:
- Why each node is a good candidate
- Expected impact radius (1-hop, 2-hop, 3-hop neighbors)
- Hidden dependencies (shared compute nodes, etc.)
"""
import json
import os
import networkx as nx
from typing import Dict, Any, List, Tuple
from anthropic import Anthropic


class LLMFaultTargetSelector:
    """
    Intelligently selects fault injection targets using LLM reasoning.
    """

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize the LLM Fault Target Selector.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use (default: claude-sonnet-4-20250514)
        """
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def select_candidates(
        self,
        topology: nx.DiGraph,
        fault_type: str,
        fault_target_role: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Select top-k fault injection candidates using LLM reasoning.

        Args:
            topology: NetworkX graph representing the system topology
            fault_type: The type of fault to inject (e.g., 'cpu_saturation', 'slow_queries')
            fault_target_role: The role of components to target (e.g., 'service', 'database')
            top_k: Number of top candidates to return

        Returns:
            List of candidate dictionaries with keys:
            - node_id: The component ID
            - score: Suitability score (0.0-1.0)
            - reasoning: Why this is a good candidate
            - impact_radius: Expected impact (direct, 1-hop, 2-hop, etc.)
            - hidden_dependencies: Non-obvious dependencies (shared compute, etc.)
        """
        # 1. Filter nodes by role
        candidates = [
            node_id for node_id, data in topology.nodes(data=True)
            if data.get('role') == fault_target_role
        ]

        if not candidates:
            return []

        # 2. Build topology summary for LLM
        topology_summary = self._build_topology_summary(topology, candidates)

        # 3. Call LLM
        prompt = self._build_selection_prompt(
            topology_summary,
            fault_type,
            fault_target_role,
            candidates,
            top_k
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._get_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )

        # 4. Parse LLM response
        response_text = response.content[0].text
        results = self._parse_selection_response(response_text)

        return results[:top_k]

    def _build_topology_summary(
        self,
        topology: nx.DiGraph,
        candidates: List[str]
    ) -> Dict[str, Any]:
        """
        Build a concise topology summary for the LLM.

        Includes:
        - All nodes with their types and roles
        - All edges with their types
        - For each candidate: upstream/downstream dependencies
        - Compute node mappings (to identify shared resources)
        """
        # Extract node information
        nodes = []
        for node_id, data in topology.nodes(data=True):
            node_info = {
                'id': node_id,
                'type': data.get('type', 'Unknown'),
                'role': data.get('role', 'Unknown')
            }

            # Add extra metadata if available
            if 'resource_profile' in data:
                node_info['profile'] = data['resource_profile']
            if 'desired_replicas' in data:
                node_info['replicas'] = data['desired_replicas']
            if 'compute_node' in data:
                node_info['compute_node'] = data['compute_node']
            if 'parent_service' in data:
                node_info['parent_service'] = data['parent_service']

            nodes.append(node_info)

        # Extract edge information
        edges = []
        for source, target, data in topology.edges(data=True):
            edges.append({
                'source': source,
                'target': target,
                'type': data.get('type', 'unknown')
            })

        # Build dependency maps for candidates
        candidate_dependencies = {}
        for candidate in candidates:
            if candidate not in topology:
                continue

            # Get direct dependencies
            predecessors = list(topology.predecessors(candidate))
            successors = list(topology.successors(candidate))

            # Get 2-hop dependencies
            two_hop_downstream = set()
            for succ in successors:
                two_hop_downstream.update(topology.successors(succ))

            candidate_dependencies[candidate] = {
                'upstream': predecessors,
                'downstream': successors,
                'two_hop_downstream': list(two_hop_downstream)
            }

        # Identify shared compute nodes (for noisy neighbor detection)
        compute_node_mapping = {}
        for node_id, data in topology.nodes(data=True):
            if data.get('role') == 'pod':
                compute_node = data.get('compute_node')
                if compute_node:
                    if compute_node not in compute_node_mapping:
                        compute_node_mapping[compute_node] = []
                    compute_node_mapping[compute_node].append(node_id)

        return {
            'nodes': nodes,
            'edges': edges,
            'candidate_dependencies': candidate_dependencies,
            'compute_node_mapping': compute_node_mapping
        }

    def _build_selection_prompt(
        self,
        topology_summary: Dict[str, Any],
        fault_type: str,
        fault_target_role: str,
        candidates: List[str],
        top_k: int
    ) -> str:
        """Build the LLM prompt for target selection."""

        # Get fault type description
        fault_descriptions = {
            'cpu_saturation': 'CPU pinned to high % with scheduler contention',
            'memory_leak': 'Progressive memory increase per request',
            'memory_pressure': 'High baseline memory usage',
            'inject_latency': 'Additive latency on all operations',
            'inject_errors': 'Baseline error rate increase',
            'slow_queries': 'Database query latency floor',
            'connection_exhaustion': 'Database connection pool starvation',
            'enable_background_job': 'Database VACUUM/cleanup CPU contention',
            'inject_db_wear': 'Database index bloat/fragmentation',
            'cache_failure': 'Cache hit rate degradation + latency',
            'queue_consumer_slowdown': 'Message processing latency',
            'noisy_neighbor': 'CPU pinning on aggressor pod (shared compute)',
            'hot_shard': 'Traffic skew to specific pod (80% to target)',
            'network_partition': 'Bidirectional link blocking',
            'force_deadlock': 'Thread locking without CPU consumption'
        }

        fault_desc = fault_descriptions.get(fault_type, fault_type)

        return f"""You are a distributed systems reliability engineer. Your task is to identify the BEST targets for fault injection testing.

**Topology Overview:**
- Total Nodes: {len(topology_summary['nodes'])}
- Total Edges: {len(topology_summary['edges'])}

**Nodes:**
{json.dumps(topology_summary['nodes'], indent=2)}

**Edges:**
{json.dumps(topology_summary['edges'], indent=2)}

**Candidate Dependencies:**
{json.dumps(topology_summary['candidate_dependencies'], indent=2)}

**Shared Compute Nodes:**
{json.dumps(topology_summary['compute_node_mapping'], indent=2)}

**Fault Type:** `{fault_type}` ({fault_desc})
**Target Role:** `{fault_target_role}`

**Available Candidates:** {candidates}

**Your Task:**
Analyze the topology and select the top {top_k} candidates for injecting `{fault_type}` on `{fault_target_role}` components.

**Selection Criteria:**
1. **Impact Radius:** How many downstream services will be affected? Prefer candidates with high fan-out.
2. **Criticality:** Is this component on critical paths? Prefer components that impact core flows.
3. **Hidden Dependencies:** Are there non-obvious impacts?
   - Shared compute nodes (noisy neighbor effects)
   - Async consumers that depend on this component
   - Caching layers that depend on this database
4. **Fault Compatibility:** Is this node type a good match for the fault?
   - CPU/memory faults work best on heavily loaded services
   - DB faults work best on databases with many clients
   - Shared compute faults need pods on same node
5. **Diversity:** Prefer candidates that test different propagation patterns

**Output Format:**
Return a JSON array with exactly {top_k} candidates (or fewer if less available), ordered by suitability (best first):

```json
[
  {{
    "node_id": "service_name",
    "score": 0.95,
    "reasoning": "Why this is the best candidate (2-3 sentences)",
    "impact_radius": {{
      "direct": ["node1", "node2"],
      "one_hop": ["node3", "node4"],
      "two_hop": ["node5"]
    }},
    "hidden_dependencies": [
      "Shares compute node with service X",
      "Gateway depends on this for all requests"
    ]
  }}
]
```

Output ONLY JSON. Be specific and technical in your reasoning."""

    def _get_system_prompt(self) -> str:
        """System prompt for the LLM."""
        return """You are an expert in distributed systems chaos engineering and fault injection.
Your role is to identify the most impactful and realistic targets for fault injection testing.

You must consider:
- Propagation patterns (how faults cascade through dependencies)
- Hidden resource sharing (compute nodes, network paths)
- Criticality (components on hot paths vs peripheral services)
- Realism (faults that actually happen in production)

Output STRICT JSON matching the requested schema."""

    def _parse_selection_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse LLM response into structured candidate list."""
        # Extract JSON from markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        try:
            candidates = json.loads(response_text.strip())

            # Validate structure
            if not isinstance(candidates, list):
                raise ValueError("Response must be a JSON array")

            for candidate in candidates:
                required_keys = {'node_id', 'score', 'reasoning', 'impact_radius'}
                if not required_keys.issubset(candidate.keys()):
                    raise ValueError(f"Candidate missing required keys: {required_keys - candidate.keys()}")

            return candidates

        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response: {e}")
            print(f"Response: {response_text[:500]}")
            return []

    def generate_topology_fault_index(
        self,
        topology_bank_dir: str,
        output_path: str = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate an index mapping fault types to compatible topologies.

        This is useful for:
        1. Quickly finding topologies that support a specific fault type
        2. Understanding which fault types are well-represented in the topology bank
        3. Balancing dataset generation across fault types

        Args:
            topology_bank_dir: Directory containing topology JSON files
            output_path: Where to save the index JSON (optional)

        Returns:
            Dictionary mapping fault_type -> list of {topology_id, candidates, reasoning}
        """
        import glob
        from src.scenarios.library import ScenarioLibrary

        # Get all fault types from scenario library
        scenario_lib = ScenarioLibrary()
        all_scenarios = []
        for level in [1, 2, 3, 4]:
            all_scenarios.extend(scenario_lib.levels[level])

        # Extract unique (fault_type, fault_target_role) pairs
        fault_type_role_pairs = set()
        for scenario in all_scenarios:
            fault_type_role_pairs.add((scenario.fault_type, scenario.fault_target_role))

        # Initialize index
        fault_index = {}

        # Load all topologies from bank
        topology_files = glob.glob(f"{topology_bank_dir}/*.json")

        print(f"Indexing {len(topology_files)} topologies for {len(fault_type_role_pairs)} fault types...")

        for fault_type, fault_target_role in fault_type_role_pairs:
            compatible_topologies = []

            for topo_file in topology_files:
                # Load topology
                with open(topo_file, 'r') as f:
                    topo_data = json.load(f)

                # Convert to NetworkX
                from src.topology.llm_generator import LLMTopologyGenerator
                generator = LLMTopologyGenerator()
                topology = generator.convert_to_simulation_graph(topo_data)

                # Check if topology has nodes with the required role
                available_roles = set(data.get('role') for _, data in topology.nodes(data=True))

                if fault_target_role not in available_roles and fault_type != 'network_partition':
                    continue

                # Get candidates
                candidates = self.select_candidates(
                    topology,
                    fault_type,
                    fault_target_role,
                    top_k=3
                )

                if candidates:
                    topology_id = os.path.basename(topo_file).replace('.json', '')
                    compatible_topologies.append({
                        'topology_id': topology_id,
                        'topology_file': topo_file,
                        'candidates': candidates,
                        'domain': topo_data.get('meta', {}).get('domain', 'Unknown')
                    })

            fault_key = f"{fault_type}:{fault_target_role}"
            fault_index[fault_key] = compatible_topologies
            print(f"  {fault_key}: {len(compatible_topologies)} compatible topologies")

        # Save index if output path provided
        if output_path:
            with open(output_path, 'w') as f:
                json.dump(fault_index, f, indent=2)
            print(f"\nFault index saved to: {output_path}")

        return fault_index
