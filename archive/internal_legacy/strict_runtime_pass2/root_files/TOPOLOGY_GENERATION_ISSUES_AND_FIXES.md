# Topology Generation Issues and Fixes

## Issues Identified

### 1. **Pod Count Hardcoded to 3** (CRITICAL BUG)
**Location:** `src/topology/llm_generator.py:268`

**Current Code:**
```python
for svc in services:
    for pod_num in range(3):  # ❌ BUG: Hardcoded to 3
        pod_id = f'pod_{svc}_{pod_num}'
```

**Problem:** Ignores `node.get('replicas', 3)` and `desired_replicas` attribute set on line 227.

**Impact:**
- Services needing 4+ replicas are under-provisioned
- Services needing 2 replicas are over-provisioned
- Capacity planner's replica calculations are ignored

---

### 2. **Missing Async Edge Type Validation** (CRITICAL BUG)
**Location:** `src/topology/llm_generator.py:38-42`

**Current Validation:**
```python
def _validate_dag(self, G):
    # Only checks synchronous edges for cycles
    if 'async' not in edge['type']:
        G.add_edge(edge['source'], edge['target'])
```

**Missing Validations:**
- ❌ `async_produce` edges must target MessageQueue, NOT Service
- ❌ `async_consume` edges must originate from MessageQueue, NOT Service
- ❌ No validation that async edges have proper queue in between

**Impact:** Generated pipeline topologies can have invalid async_produce → Service edges (as seen in `pipeline_small_0`).

---

### 3. **LLM Prompt Doesn't Request Queue Consumer Capacity**
**Location:** `src/topology/llm_generator.py:122-163`

**Current Schema:**
```json
{
  "id": "service_name",
  "type": "Service",
  "profile": "standard|cpu_intensive|io_intensive|latency_sensitive",
  "replicas": 3
}
```

**Missing:**
- No field for async consumer throughput/capacity
- No field for queue processing rate
- No field for consumer thread pool size

**Impact:** Capacity planner has no information about how fast a service can consume from a queue, leading to under-provisioned consumers.

---

### 4. **"Small" Scale Definition Too Vague**
**Location:** `src/topology/llm_generator.py:90`

**Current:**
```python
target_nodes = {"small": "8-12", "medium": "12-18", "large": "25-35"}.get(scale, "12-18")
```

**Problem:** "8-12 nodes" doesn't specify WHAT nodes:
- Does this include ComputeNodes and Pods?
- Does this include infrastructure (DB, Cache, Queue)?
- What's the minimum service count?

**Result:** LLM generates 5-6 service topologies when 8-12 was requested.

---

### 5. **No Flow Validation**
**Location:** `src/topology/llm_generator.py` - missing validation

**Missing Checks:**
- Flows reference nodes that don't exist in the graph
- Flows reference edges that don't exist
- Flows are incomplete (missing critical paths)

---

### 6. **No Pipeline-Specific Validation**
**Location:** `src/topology/llm_generator.py` - missing validation

**For Pipeline Archetype:**
- Should validate ALL stages connected by queues
- Should validate no service-to-service sync edges (defeats the purpose)
- Should validate linear flow (no branching/merging in pure pipeline)

---

## Fixes Required

### Fix #1: Respect desired_replicas

**File:** `src/topology/llm_generator.py`

**Change lines 265-282:**
```python
# OLD (BROKEN):
for svc in services:
    for pod_num in range(3):  # ❌ Hardcoded
        pod_id = f'pod_{svc}_{pod_num}'
        # ...

# NEW (FIXED):
for svc in services:
    svc_data = G.nodes[svc]
    num_replicas = svc_data.get('desired_replicas', 3)

    for pod_num in range(num_replicas):  # ✅ Use actual replicas
        pod_id = f'pod_{svc}_{pod_num}'
        target_node = nodes[node_idx % num_nodes]

        G.add_node(pod_id,
                  type='Pod',
                  role='pod',
                  parent_service=svc,
                  compute_node=target_node)

        G.add_edge(svc, pod_id, type='pod_pool', base_latency=0.0)
        G.add_edge(pod_id, target_node, type='pod_placement', base_latency=0.0)

        node_idx += 1
```

---

### Fix #2: Add Async Edge Validation

**File:** `src/topology/llm_generator.py`

**Add new validation method after line 211:**
```python
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
```

**Update generate_architecture() at line 41:**
```python
# 3. Rigorous Validation
self._validate_dag(G)
self._validate_connectivity(G)
self._validate_node_types(topology_data)
self._validate_async_edges(topology_data)  # ✅ Add this
```

---

### Fix #3: Add Queue Consumer Capacity to Schema

**File:** `src/topology/llm_generator.py`

**Update prompt at line 138-142:**
```python
{
  "id": "service_name",
  "type": "Service",
  "profile": "standard|cpu_intensive|io_intensive|latency_sensitive",
  "replicas": 3,
  "async_consumer_capacity": 50  // Optional: RPS this service can consume from queues
}
```

**Update prompt at line 122 (MessageQueue section):**
```python
{
  "id": "queue_name",
  "type": "MessageQueue",
  "replicas": 3,
  "consumer_capacity_hint": 100  // Optional: Expected consumer throughput (RPS)
}
```

**Update system prompt at line 77-79 to include:**
```
**Async Consumer Capacity:**
- Services that consume from queues should specify `async_consumer_capacity` (RPS)
- This represents how fast the service can process messages from the queue
- cpu_intensive services: 20-50 RPS, io_intensive: 50-100 RPS, standard: 100-200 RPS
```

---

### Fix #4: Define Minimal Quality Standards

**File:** `src/topology/llm_generator.py`

**Update prompt at line 88-98:**
```python
def _build_prompt(self, archetype: str, scale: str) -> str:
    # Define STRICT minimums for "small" topologies
    scale_requirements = {
        "small": {
            "target_nodes": "8-12 application/infrastructure nodes",
            "min_services": 5,
            "min_databases": 1,
            "min_caches": 1,
            "min_queues": 1,  # For pipeline: 3 minimum
            "min_external": 1,
            "description": "A realistic production system, scaled down but complete"
        },
        "medium": {
            "target_nodes": "12-18 application/infrastructure nodes",
            "min_services": 8,
            "min_databases": 2,
            "min_caches": 2,
            "min_queues": 2,
            "min_external": 1,
            "description": "A full-featured production system"
        },
        "large": {
            "target_nodes": "25-35 application/infrastructure nodes",
            "min_services": 15,
            "min_databases": 3,
            "min_caches": 3,
            "min_queues": 3,
            "min_external": 2,
            "description": "An enterprise-scale production system"
        }
    }

    reqs = scale_requirements.get(scale, scale_requirements["medium"])
```

**Update prompt to include:**
```
**MINIMUM QUALITY REQUIREMENTS FOR "{scale.upper()}":**
- At least {reqs['min_services']} Services
- At least {reqs['min_databases']} Database(s)
- At least {reqs['min_caches']} Cache(s)
- At least {reqs['min_queues']} Queue(s) {' (3+ for pipeline)' if archetype=='pipeline' else ''}
- At least {reqs['min_external']} External Service(s)
- Total: {reqs['target_nodes']}

{reqs['description']}

**CRITICAL:** These are MINIMUMS. A production system needs proper infrastructure.
Do NOT create toy examples with only 1-2 services.
```

---

### Fix #5: Add Flow Validation

**File:** `src/topology/llm_generator.py`

**Add validation method:**
```python
def _validate_flows(self, data: Dict):
    """Validate that flows reference existing nodes and edges."""
    # Build node set and edge set
    node_ids = {n['id'] for n in data['nodes']}
    edge_set = {(e['source'], e['target']) for e in data['edges']}

    errors = []
    flows = data.get('flows', {})

    for method, flow_map in flows.items():
        for source, targets in flow_map.items():
            # Check source exists
            if source not in node_ids:
                errors.append(f"Flow {method}: source '{source}' not in topology")
                continue

            # Check each target exists and has edge from source
            for target in targets:
                if target not in node_ids:
                    errors.append(f"Flow {method}: target '{target}' not in topology")
                # Note: We don't strictly require edge existence because flows may be abstract
                # But we can warn if missing

    if errors:
        raise ValueError(f"Invalid flows:\n  " + "\n  ".join(errors))
```

---

### Fix #6: Add Pipeline-Specific Validation

**File:** `src/topology/llm_generator.py`

**Add validation method:**
```python
def _validate_pipeline_archetype(self, data: Dict):
    """Extra validation for pipeline topologies."""
    # For pipeline archetype, enforce:
    # 1. Services should be connected via queues, not direct sync_http
    # 2. At least 3 stages (upload/process/output pattern)

    if data.get('meta', {}).get('archetype') != 'pipeline':
        return  # Only validate pipelines

    # Check for service-to-service sync edges (anti-pattern in pipeline)
    node_types = {n['id']: n['type'] for n in data['nodes']}

    service_to_service_edges = []
    for edge in data['edges']:
        if edge['type'] in ['sync_http', 'sync_rpc']:
            source_type = node_types.get(edge['source'])
            target_type = node_types.get(edge['target'])

            if source_type == 'Service' and target_type == 'Service':
                service_to_service_edges.append(f"{edge['source']} → {edge['target']}")

    if service_to_service_edges:
        raise ValueError(
            f"Pipeline archetype should use queues between services, not direct sync calls:\n  "
            + "\n  ".join(service_to_service_edges)
        )

    # Check for minimum queue count (pipeline needs multiple stages)
    queues = [n for n in data['nodes'] if n['type'] == 'MessageQueue']
    if len(queues) < 3:
        raise ValueError(
            f"Pipeline archetype needs at least 3 queues for multi-stage processing, got {len(queues)}"
        )
```

---

### Fix #7: Enhanced LLM System Prompt with Self-Checking

**File:** `src/topology/llm_generator.py`

**Update _get_system_prompt() at line 62:**
```python
def _get_system_prompt(self) -> str:
    return """You are a Principal Software Architect with expertise in distributed systems.
Your goal is to design realistic, fault-tolerant distributed system topologies for simulation.
You must output STRICT JSON matching the schema provided.

**CRITICAL CONSTRAINTS - SELF-CHECK BEFORE RETURNING:**

1. **No Cycles:** Synchronous calls (sync_http/sync_db/sync_cache) MUST NOT form loops.
   - Check: Can you traverse from any service back to itself via sync edges? If yes, FIX IT.

2. **Connectivity:** All nodes must be reachable from the Gateway.
   - Check: Is every node reachable from 'gateway'? If no, ADD EDGES.

3. **Async Edge Rules:**
   - async_produce edges MUST target MessageQueue (NOT Service)
   - async_consume edges MUST originate from MessageQueue
   - Check: Do all async_produce edges have MessageQueue as target? If no, FIX IT.
   - Check: Do all async_consume edges have MessageQueue as source? If no, FIX IT.

4. **Pipeline Pattern:**
   - Services connected via queues: Service → Queue → Service → Queue → ...
   - NO direct Service → Service sync_http edges in pipelines
   - Check: Are pipeline stages properly separated by queues? If no, ADD QUEUES.

5. **Realism:**
   - Use Cache-Aside pattern: Service → Cache (check) → Database (on miss)
   - Use Queues for async decoupling: Producer → Queue → Consumer
   - Services need databases OR caches OR queues (not orphaned)
   - Check: Does every service connect to infrastructure? If no, ADD CONNECTIONS.

6. **Flows Match Topology:**
   - Every node in flows must exist in nodes[]
   - Every edge in flows should correspond to an edge in edges[]
   - Check: Do all flow references exist? If no, FIX FLOWS.

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
- Example: transcoding_service with 4 replicas, cpu_intensive → 4 * 30 RPS = 120 RPS capacity

**BEFORE RETURNING JSON:**
1. Verify no sync cycles exist
2. Verify all nodes reachable from gateway
3. Verify async edges only connect to/from MessageQueues
4. Verify all services connect to infrastructure
5. Verify flows reference existing nodes
6. Verify minimum node counts met for scale
"""
```

---

## Updated Minimal Quality Standards

### Small Topologies (Fast simulation, realistic structure)

**Minimum Requirements:**
- **Services:** 5-8 (not 3-4)
- **Databases:** 1-2 (must have at least 1)
- **Caches:** 1-2 (must have at least 1)
- **Queues:**
  - Non-pipeline: 1-2
  - Pipeline: 3-5 (one per stage transition)
- **External Services:** 1-2
- **Total Nodes:** 8-12 (application/infrastructure, excludes compute nodes)

**Rationale:**
- Must have enough components to show realistic failure propagation
- Must have cache+DB for cache-aside pattern
- Must have queues for async patterns
- Must have external dependencies for external failure testing

### Example Minimal Pipeline:
```
Gateway → Upload Service → Upload Queue →
          Processor Service → Process Queue →
          Packager Service → Package Queue →
          Publisher Service → CDN (external)

Infrastructure:
- 1 Database (metadata)
- 1 Cache (results cache)
```

**Services:** 4 (upload, processor, packager, publisher)
**Queues:** 3 (upload, process, package)
**DB:** 1
**Cache:** 1
**External:** 1
**Total:** 10 nodes ✅

---

## Implementation Plan

1. **High Priority (Do First):**
   - Fix #1: Respect desired_replicas in pod creation
   - Fix #2: Add async edge validation
   - Fix #4: Define minimal quality standards

2. **Medium Priority (Do Next):**
   - Fix #3: Add consumer capacity to schema
   - Fix #7: Enhanced self-checking prompt

3. **Nice to Have (Can Wait):**
   - Fix #5: Flow validation
   - Fix #6: Pipeline-specific validation

---

## Testing Plan

After implementing fixes:

1. **Regenerate topology bank**
   ```bash
   python generate_topology_bank.py --samples 1 --output data/topology_bank_test
   ```

2. **Validate each topology:**
   - Check pod count matches desired_replicas
   - Check no async_produce → Service edges
   - Check pipeline has 3+ queues
   - Check minimal node counts met

3. **Run simulation test:**
   ```bash
   python generate_dataset.py --topology data/topology_bank_test/pipeline_small_0 --episodes 1
   ```

4. **Check capacity planning:**
   - Verify queue consumers have sufficient capacity
   - Verify no underflows in async consumption
   - Check metrics show healthy baseline (no faults)
