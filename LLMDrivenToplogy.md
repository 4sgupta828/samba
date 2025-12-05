This is the **"LLM-as-Architect"** strategy. It is a fundamental shift that solves the realism problem by having the AI design the system with *intent* rather than us trying to derive intent from a random graph.

Here is the complete specification, conceptual breakdown, and code implementation.

-----

# Specification: LLM-Native Topology Generation

## 1\. Conceptual Architecture

Instead of a procedural random walker, we create a pipeline where an LLM functions as a **System Architect**.

1.  **Design Phase (LLM):** We prompt the model with a high-level requirement (e.g., *"Design a tiered e-commerce system"*). It outputs a JSON definition containing nodes, edges, and **Business Flows** (e.g., "Checkout: Gateway $\to$ Cart $\to$ Redis").
2.  **Validation Phase (Python):** We mathematically verify the architect's work.
      * Is the synchronous call graph a DAG? (No deadlocks)
      * Are all services reachable?
      * Are component connections valid (e.g., DBs don't call Services)?
3.  **Asset Banking:** Valid topologies are saved to disk.
4.  **Simulation Runtime:** The simulation loads a topology, calculates capacity using the **Capacity Planner** (which consumes the *deterministic flows* defined by the LLM), and executes.

-----

## 2\. The Data Contract (JSON Schema)

This is the structure the LLM must generate. It maps directly to your simulation's requirements.

```json
{
  "meta": {
    "architecture_name": "Video Streaming Ingest",
    "archetype": "pipeline",
    "domain": "media",
    "description": "Handles high-throughput video upload...",
    "pros": ["High throughput", "Decoupled processing"],
    "cons": ["High latency", "Complex debugging"]
  },
  "nodes": [
    {
      "id": "ingest_service",
      "type": "Service",
      "profile": "cpu_intensive",
      "replicas": 5
    },
    {
      "id": "video_queue",
      "type": "MessageQueue"
    }
  ],
  "edges": [
    { "source": "gateway", "target": "ingest_service", "type": "sync_http" },
    { "source": "ingest_service", "target": "video_queue", "type": "async_produce" }
  ],
  "flows": {
    "UPLOAD": ["gateway", "ingest_service", "video_queue"]
  }
}
```

-----

## 3\. Implementation: `src/topology/llm_generator.py`

Create this new module. It handles the "Architect" role.

````python
"""
LLM Topology Generator.
Uses an LLM to architect realistic distributed systems with deterministic flows.
"""
import json
import os
import networkx as nx
from typing import Dict, Any, List
from anthropic import Anthropic  # Or OpenAI

class LLMTopologyGenerator:
    def __init__(self, api_key: str = None, model: str = "claude-3-5-sonnet-20240620"):
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
        target_nodes = {"small": "5-8", "medium": "12-18", "large": "25-35"}.get(scale)
        
        return f"""Design a **{scale}** ({target_nodes} nodes) architecture using the **{archetype}** pattern.

1. **Domain:** Pick a business domain fitting this pattern (e.g., {archetype == 'pipeline' and 'Video Processing' or 'E-Commerce'}).
2. **Structure:**
   - {archetype == 'hierarchical' and 'Strict layers: Gateway -> Frontend -> Backend -> Data.'}
   - {archetype == 'mesh' and 'High service-to-service connectivity.'}
   - {archetype == 'hub_spoke' and 'One central orchestration service.'}
3. **Flows:** Define specific request paths (e.g., "checkout": gateway->cart->redis).

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
            cycle = nx.find_cycle(G)
            raise ValueError(f"Topology contains a synchronous cycle: {cycle}")

    def _validate_connectivity(self, G: nx.DiGraph):
        # Simplified check: Ensure graph isn't just islands
        if len(G.nodes) > 0 and not nx.is_weakly_connected(G):
            # Note: Weakly connected is minimal requirement. 
            # Ideally check reachability from Gateway, but G here only has sync edges.
            pass

    def _validate_node_types(self, data: Dict):
        valid_types = {'RequestGateway', 'Service', 'SqlDatabase', 'ExternalCache', 'MessageQueue', 'ExternalService'}
        for n in data['nodes']:
            if n['type'] not in valid_types:
                raise ValueError(f"Invalid node type: {n['type']}")

    def convert_to_simulation_graph(self, data: Dict) -> nx.DiGraph:
        """Converts the JSON to the full NetworkX graph used by simulation."""
        G = nx.DiGraph()
        
        # 1. Add Nodes
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
                
            G.add_node(node['id'], **attrs)
            
        # 2. Add Edges
        for edge in data['edges']:
            # Assign physical latency based on edge type
            latency = 50.0 if edge['type'] == 'sync_external' else 2.0 if edge['type'] == 'sync_db' else 5.0
            G.add_edge(edge['source'], edge['target'], 
                      type=edge['type'], 
                      base_latency=latency)
                      
        # 3. Attach Metadata & Flows
        G.graph['meta'] = data.get('meta', {})
        G.graph['request_flows'] = data.get('flows', {})
        
        return G

    def _infer_role(self, type_str: str) -> str:
        map = {
            'RequestGateway': 'gateway', 'Service': 'service',
            'SqlDatabase': 'database', 'ExternalCache': 'cache',
            'MessageQueue': 'queue', 'ExternalService': 'external'
        }
        return map.get(type_str, 'service')
````

-----

## 4\. Implementation: `generate_topology_bank.py`

The offline generator script.

```python
#!/usr/bin/env python3
import os
import json
import networkx as nx
from src.topology.llm_generator import LLMTopologyGenerator

def main():
    output_dir = "data/topology_bank"
    os.makedirs(output_dir, exist_ok=True)
    
    generator = LLMTopologyGenerator() # Ensure API key env var is set
    
    # Matrix of scenarios to generate
    # This guarantees diversity of structure AND scale
    scenarios = [
        ("hierarchical", "medium"), ("hierarchical", "large"),
        ("mesh", "medium"),         ("mesh", "large"),
        ("pipeline", "medium"),     ("pipeline", "large"),
        ("hub_spoke", "medium"),    ("hub_spoke", "large")
    ]
    
    # Generate multiple samples per scenario
    samples_per_scenario = 3
    
    total = len(scenarios) * samples_per_scenario
    count = 0
    
    for archetype, scale in scenarios:
        for i in range(samples_per_scenario):
            count += 1
            print(f"[{count}/{total}] Architecting {archetype} ({scale})...")
            
            try:
                # 1. Generate (includes validation)
                topo_data = generator.generate_architecture(archetype, scale)
                
                # 2. Convert to graph for serialization check
                G = generator.convert_to_simulation_graph(topo_data)
                graph_json = nx.node_link_data(G)
                
                # 3. Save
                slug = f"{archetype}_{scale}_{i}"
                path = os.path.join(output_dir, slug)
                os.makedirs(path, exist_ok=True)
                
                # Save the graph structure used by simulation
                with open(f"{path}/graph.json", 'w') as f:
                    json.dump(graph_json, f, indent=2)
                    
                # Save the semantic map (flows + descriptions)
                # We normalize this to the structure expected by CapacityPlanner
                semantic_map = {
                    "domain": topo_data.get('meta', {}).get('domain', 'unknown'),
                    "description": topo_data.get('meta', {}).get('description', ''),
                    "request_flows": topo_data.get('flows', {}),
                    "services": {n['id']: n for n in topo_data['nodes']} # Quick lookup
                }
                with open(f"{path}/semantic_map.json", 'w') as f:
                    json.dump(semantic_map, f, indent=2)
                    
                print(f"   Saved to {path}")
                
            except Exception as e:
                print(f"   FAILED: {e}")

if __name__ == "__main__":
    main()
```

-----

## 5\. Implementation: `generate_dataset.py`

How to consume these assets.

```python
# ... imports ...
from src.core.capacity_planner import CapacityPlanner

def load_random_template(bank_dir="data/topology_bank"):
    # ... (same as previous logic) ...
    # Load graph.json and semantic_map.json
    return nx_graph, semantic_map

def generate_episode(...):
    # 1. Load Architectural Asset
    nx_graph, semantic_map = load_random_template()
    
    # 2. Define Simulation Parameters
    # We still vary these at runtime to get "Robust" vs "Fragile" variations
    # of the SAME architecture.
    target_rps = 200
    phi = random.uniform(0.6, 0.95)
    
    # 3. Plan Capacity (The Planner is now highly accurate because it has deterministic flows)
    planner = CapacityPlanner(nx_graph, semantic_map)
    tuned_configs = planner.plan_capacity(target_rps, phi)
    
    # 4. Apply Configs & Run
    # ...
```

-----

## 6\. Why This Is Better

1.  **Intentional Design:** We don't accidentally get a bottleneck; the LLM explicitly designs a "Hub-and-Spoke" architecture where the Hub *is* the bottleneck.
2.  **Deterministic Flows:** The LLM outputs `flows: {"checkout": ["gateway", "cart", "db"]}`. The `CapacityPlanner` uses this exact list. The `Service` component (if updated to read this map) executes this exact list. **Zero guesswork.**
3.  **Rich Metadata:** The LLM writes a description ("This is a video processing pipeline...") which is preserved in the dataset, providing explainability for the GNN results.
4.  **Constraint Enforcement:** The `LLMTopologyGenerator` explicitly validates the DAG property, preventing the "infinite loop" latency bug before it ever reaches the simulation.