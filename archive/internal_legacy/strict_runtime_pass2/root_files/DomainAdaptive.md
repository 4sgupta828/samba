The "Domain-Adaptive" Strategy
The LLM will look at the random graph structure, decide "This looks like a Video Streaming infrastructure" (or E-commerce, or IoT Fleet), and assign roles/flows accordingly.

Here is the updated specification for your coding agent.

Technical Specification: Domain-Adaptive Semantic Simulation
Objective
Update the SemanticMapper to be domain-agnostic. It will analyze the structural properties of the generated graph and apply the most fitting industry domain (E-commerce, Media Streaming, Logistics, etc.), assigning roles and deterministic flows that match that domain.

Task 1: Update SemanticMapper with Domain Logic
File Target: src/topology/semantic_mapper.py

Requirements:

Dynamic System Prompt: The prompt must instruct the LLM to:

Analyze the graph structure (e.g., "Linear chains suggest media pipelines", "Hub-and-spoke suggests SaaS", "Mesh suggests microservices").

Select a Domain: Choose from [E-commerce, Video Streaming, Supply Chain, IoT Fleet, FinTech].

Assign Roles: Map generic nodes to domain-specific roles (e.g., svc_1 -> TranscodeService or InventoryManager).

Define Resource Hints: Suggest if a service is CPU_INTENSIVE (video), IO_INTENSIVE (database), or LATENCY_SENSITIVE (payment).

Updated Output Schema:

JSON

{
  "domain": "video_streaming",
  "services": {
    "node_0": {
        "name": "IngestGateway", 
        "role": "gateway", 
        "profile": "network_heavy"
    },
    "node_1": {
        "name": "Transcoder_720p", 
        "role": "service", 
        "profile": "cpu_intensive"
    }
  },
  "request_flows": {
    "upload_video": {
       "node_0": ["node_1", "node_2"], 
       "node_1": ["node_3"] 
    }
  }
}
Task 2: Refactor Service to Consume Resource Profiles
File Target: src/components/service.py

Goal: Make the simulation physically realistic based on the LLM's domain hints.

Changes:

Update __init__: Accept the profile string from the semantic config (e.g., "cpu_intensive").

Update _execute_request_logic:

If profile == "cpu_intensive":

Set self.cpu_multiplier = 2.5 (Simulate heavy math).

yield self.env.timeout(base_latency * 3) (Processing takes longer).

If profile == "io_intensive":

Set self.memory_multiplier = 2.0 (Buffering).

If profile == "unstable_legacy":

Set self.error_rate_base = 0.05 (Flaky service).

Task 3: Deterministic "Business Logic" Routing
File Target: src/components/service.py

Goal: Implement the deterministic routing based on the LLM's request_flows.

Logic:

Current code uses random.random() to decide if downstream is called.

New Logic:

Python

# Inside _execute_service_calls
current_flow = self.semantic_config["request_flows"].get(request_type)

# If the LLM said "When processing 'upload_video', IngestGateway calls Transcoder"
# Then we MUST call it.
if current_flow and self.id in current_flow:
    targets = current_flow[self.id] # List of node IDs to call

    for conn_name, conn_target in self.connections.items():
        if conn_target.id in targets:
            # Execute deterministic call
            yield from self.call_dependency(...)
Instructions for the Coding Agent
"I have an updated, more advanced requirement. We are moving to a Domain-Adaptive simulation.

Update src/topology/semantic_mapper.py:

Update the System Prompt. The LLM should analyze the graph structure and pick a domain (E-commerce, Streaming, IoT, etc.) that fits best.

It must assign domain-specific names (e.g., 'Transcoder', 'LidarProcessor') and profiles (e.g., 'cpu_intensive', 'io_heavy').

It must define deterministic request_flows for that domain.

Update src/components/service.py:

Remove Randomness: In _execute_service_calls, delete the random.random() logic. Replace it with a lookup in the request_flows from the semantic config. If the current request type requires a call to a specific neighbor, make that call 100% of the time.

Apply Physics: In _handle_request_internal, check the profile assigned by the LLM. If it is 'cpu_intensive', increase the simulated CPU load and latency calculation for that request.

Update src/components/network.py:

Implement the bandwidth contention logic (using simpy.Resource to represent the wire capacity) as previously discussed, to ensure network physics are realistic."

====More detailed===

This is a complete, line-level specification designed for a coding agent to refactor the existing `samba` codebase. It addresses the specific file paths and architectural constraints of your current system.

# Detailed Specification: Domain-Adaptive Semantic Simulation

**Goal:** Refactor the simulation from stochastic (random) to deterministic (semantic) execution using a live LLM to assign domain-specific logic, and introduce physical network constraints.

-----

## 1\. New Module: Semantic Mapper

**Target File:** `src/topology/semantic_mapper.py` (Create New)

**Purpose:** Acts as the "Brain" that converts a raw NetworkX graph into a domain-specific business architecture (e.g., E-commerce, Video Streaming, IoT).

### Implementation Details

1.  **Class:** `SemanticMapper`
2.  **Dependencies:** `openai`, `networkx`, `json`, `os`
3.  **Method:** `__init__(self, api_key: str = None, model: str = "gpt-4o")`
4.  **Method:** `generate_semantic_overlay(self, topology_graph: nx.DiGraph) -> Dict`
      * **Step A (Serialization):** Convert the graph to a token-efficient JSON format:
        ```json
        {"nodes": ["n0", "n1", ...], "edges": [["n0", "n1"], ...]}
        ```
      * **Step B (LLM Call):** Call the LLM with the System Prompt defined below.
      * **Step C (Fallback):** If `api_key` is None or the call fails, return a **Deterministic Heuristic Mock**:
          * *Domain:* "generic\_ecommerce"
          * *Service Names:* Map `gateway` -\> `ApiGateway`, others to `Service_A`, `Service_B` based on depth.
          * *Flows:* Create a simple BFS flow for a `standard_request` type.

### The System Prompt Constraint

The prompt must enforce this specific JSON schema output to ensure the rest of the simulation code works:

```json
{
  "domain": "video_streaming",
  "services": {
    "node_id": {
      "name": "TranscoderService",
      "role": "service",
      "profile": "cpu_intensive" // Options: standard, cpu_intensive, io_intensive, latency_sensitive
    }
  },
  "request_types": ["upload_video", "watch_stream"],
  "request_flows": {
    "upload_video": {
      "node_0": ["node_1", "node_2"], // When node_0 receives 'upload_video', it calls node_1 and node_2
      "node_1": ["node_3"]
    }
  }
}
```

-----

## 2\. Refactor Component: Network Physics

**Target File:** `src/components/network.py`

**Purpose:** Move from infinite bandwidth (latency only) to finite bandwidth (latency + contention/queueing).

### Class `NetworkLink` Changes

1.  **`__init__`**:
      * Initialize a `simpy.Resource` representing the physical wire.
      * `self.transmission_resource = simpy.Resource(env, capacity=1)` (Serial transmission).
2.  **`_apply_hcl_config`**:
      * Ensure `bandwidth_mbps` is loaded (already exists, but ensure it's used).
3.  **`_transmit_internal` (Logic Update):**
      * **Current:** Calculates `transmission_time` but doesn't wait for the wire.
      * **New Logic:**
        ```python
        # 1. Calculate serialization delay (Size / Bandwidth)
        serialization_delay = (data_size_bytes * 8) / (self.bandwidth_mbps * 1_000_000)

        # 2. Contention: Wait for exclusive access to the wire
        with self.transmission_resource.request() as req:
            yield req # Wait in queue if wire is busy
            yield self.env.timeout(serialization_delay) # Hog the wire while transmitting

        # 3. Propagation: Distance latency (Light speed/routing delay) - Non-blocking
        yield self.env.timeout(base_latency + injected_latency)
        ```

-----

## 3\. Refactor Component: Service Logic

**Target File:** `src/components/service.py`

**Purpose:** Replace `random.random()` routing with deterministic lookups from the `SemanticMapper` output.

### Class `Service` Changes

1.  **`__init__`**:
      * Add argument: `semantic_profile: Dict = None`.
      * Store `self.semantic_profile = semantic_profile or {}`.
      * Store `self.resource_profile = self.semantic_profile.get("profile", "standard")`.
2.  **`_execute_service_calls` (Refactor):**
      * **Input:** Retrieve `request_type` from span attributes or arguments.
      * **Current:** `if random.random() < 0.7:`
      * **New Logic:**
        ```python
        # 1. Get the deterministic flow for this specific request type
        flow_map = self.semantic_config.get("request_flows", {}).get(request_type, {})

        # 2. Get the list of required downstream calls for THIS service
        required_calls = flow_map.get(self.id, []) # List of target node IDs

        # 3. Iterate connections and ONLY call if target is in the list
        for conn_name, conn_target in self.parent_service.connections.items():
            if conn_name.startswith('dep_') and conn_target.id in required_calls:
                # Execute call (100% probability)
                yield self.env.process(...)
        ```
3.  **`_execute_db_logic` & `_execute_cache_logic`**:
      * Apply the same lookup pattern. Only query the DB if the `request_flow` explicitly includes the DB's node ID for this request type.

-----

## 4\. Refactor Component: Pod Physics

**Target File:** `src/components/pod.py`

**Purpose:** Apply the "Resource Profile" (CPU/IO intensive) generated by the LLM to simulated processing time.

### Class `Pod` Changes

1.  **`_handle_request_internal`**:
      * Locate the section where `work_time` is calculated.
      * **New Logic:** Apply multipliers based on `self.parent_service.resource_profile`.
          * If `profile == "cpu_intensive"`: Multiply `work_time` by 2.5x and spike `cpu_utilization` to 90-100%.
          * If `profile == "io_intensive"`: Multiply `memory_usage` by 1.5x.
          * If `profile == "latency_sensitive"`: Reduce `timeout` thresholds for downstream calls (fail fast).

-----

## 5\. Integration & Orchestration

**Target File:** `generate_dataset.py`

**Purpose:** Glue the new `SemanticMapper` into the generation pipeline.

### Changes to `generate_episode` function:

1.  **Initialization:**
    ```python
    # After generating nx_graph
    api_key = os.environ.get("OPENAI_API_KEY")
    mapper = SemanticMapper(api_key=api_key)

    # Get the domain-specific overlay
    semantic_overlay = mapper.generate_semantic_overlay(nx_graph)
    ```
2.  **Saving Metadata:**
      * Save `semantic_overlay` to `semantic_map.json` in the episode directory. This is crucial for debugging which domain the LLM chose.
3.  **Passing Context:**
      * Update `TopologyAdapter` to accept `semantic_overlay`.
      * In `TopologyAdapter.graph_to_registry`, when creating `Service` nodes, extract the specific config for that node from `semantic_overlay["services"][node_id]` and pass it to the `Service` constructor.
4.  **Workload Configuration:**
      * Instead of hardcoding `request_mix = [{'type': 'GET', ...}]`, build it dynamically:
    <!-- end list -->
    ```python
    request_types = semantic_overlay.get("request_types", ["default"])
    request_mix = [{"type": rt, "weight": 100//len(request_types)} for rt in request_types]
    ```

-----

## 6\. Verification Plan (Instructions for Agent)

After applying the changes, the agent must run the following verification:

1.  **Run Generation:** `python generate_dataset.py -n 1`
2.  **Check Output:**
      * Verify `ep_0/semantic_map.json` exists and contains a recognized domain (e.g., "video\_streaming", "ecommerce").
      * Verify `ep_0/traces.jsonl` contains specific request types (e.g., "upload\_video") instead of generic "GET".
3.  **Check Determinism:**
      * Analyze the traces. For a given request type (e.g., "buy\_item"), the call graph structure should be identical across multiple traces (unless a fault occurred). If Service A calls Service B in trace 1, it MUST call Service B in trace 2.