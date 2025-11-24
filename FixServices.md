# Service/Pod Architecture Refactoring

## Current State

The codebase currently has:
- **ApiService** (in `service.py`): Service layer that handles routing and service-to-service calls
- **ComputeAgent** (in `compute.py`): Compute layer that handles request processing and resources

## Problem Statement

Current architecture has two layers (`ApiService` and `ComputeAgent`) with overlapping responsibilities, duplication of dynamics engines, and unclear separation of concerns. This doesn't match real-world architecture where services are just collections of container instances.

## Proposed Changes

1. **Rename ComputeAgent → Pod**: Use Kubernetes-native terminology
2. **Simplify Service**: Remove all computation logic, make it a lightweight coordinator
3. **Move logic to Pod**: All ApiService processing logic moves to Pod
4. **Topology-driven**: Services and connections defined by topology, not hardcoded
5. **Generic**: Remove all domain-specific logic
6. **Configurable pipelines**: Each service defines its processing order

## Design Goals

1. **Lightweight Service concept**: Logical grouping only, no computation
2. **Pod does all work**: All processing happens in pod instances (renamed from ComputeAgent)
3. **Topology-driven**: Services and their connections defined by topology, not hardcoded
4. **Generic**: No domain-specific logic (no e-commerce, no specific request types)
5. **Configurable pipelines**: Each service defines its processing order

## Architecture

### Service (Lightweight Coordinator)

**Responsibilities**:
- Logical container for a group of pods
- Load balancing to healthy pod instances
- Holds connections (downstream services, external deps, queues, DB, cache)
- Defines service metadata (name, supported request types, processing pipeline)

**NOT responsible for**:
- Any computation or request processing
- Metrics collection (beyond routing)
- Dynamics simulation
- Resource management

**Implementation**:
```python
class Service(EnrichedComponent):
    def __init__(self, env, component_id, service_name,
                 supported_request_types=None,
                 processing_pipeline=None):
        self.service_name = service_name
        self.supported_request_types = supported_request_types or []
        self.processing_pipeline = processing_pipeline or self._default_pipeline()
        # Connections: dep_*, ext_*, queue_in, queue_out, database, cache

    def handle_request(self, request_type, should_trace, parent_span_context):
        """Just route to a healthy pod"""
        pod = self.get_pod_target()
        yield from pod.handle_request(request_type, should_trace, parent_span_context)

    def get_pod_target(self):
        """Load balance to healthy instance in pod_pool or pod_asg"""
        # Returns a healthy Pod from the pool
```

### Pod (Renamed from ComputeAgent)

**Current name in code**: `ComputeAgent` (in `src/components/compute.py`)
**New name**: `Pod` (will be in `src/components/pod.py`)

**Responsibilities**:
- Belongs to a parent Service
- Executes the parent service's processing pipeline
- All actual computation and I/O:
  - Cache operations (if cache connection exists)
  - Database operations (if database connection exists)
  - Service-to-service calls (via parent service's dep_* connections)
  - External service calls (via parent service's ext_* connections)
  - Queue publishing (via parent service's queue_out connection)
- Background processes:
  - Queue consumption (if parent service has queue_in connection)
- Resource management (CPU, memory, thread pool, connection pool)
- Dynamics simulation (latency, errors, resource pressure)
- Metrics emission (tagged with parent service name)
- Crash/restart/OOM handling

**Key Changes**:
- Add `parent_service` reference to access service connections
- Move `_call_downstream_dependencies()` from ApiService → Pod
- Move `_consume_from_queue()` from ApiService → Pod
- Execute parent service's processing pipeline instead of hardcoded logic
- Access connections via `self.parent_service.connections`

**Implementation**:
```python
class Pod(EnrichedComponent):
    def __init__(self, env, component_id, parent_service=None):
        self.parent_service = parent_service
        # All existing logic (dynamics, thread pool, connection pool, etc.)

    def run(self):
        """Start background processes (including queue consumer if needed)"""
        # Start queue consumer if parent service has queue_in
        if self.parent_service.connections.get('queue_in'):
            self.env.process(self._consume_from_queue())

        # Continue with normal run() logic
        yield from super().run()

    def _consume_from_queue(self):
        """Background process that continuously consumes from queue_in"""
        queue = self.parent_service.connections.get('queue_in')
        while True:
            msg = yield from queue.receive_message()
            try:
                # Process message using normal request pipeline
                request_type = random.choice(self.parent_service.supported_request_types)
                yield from self.handle_request(request_type, should_trace=False)
                queue.delete_message(msg)
            except Exception as e:
                # Don't delete - let message return for retry
                self._emit_log("ERROR", f"Failed to process message: {e}")

    def _handle_request_internal(self, request_type, span):
        # Execute parent service's processing pipeline
        pipeline = self.parent_service.processing_pipeline

        for step in pipeline:
            # Only execute if required connections exist
            if step["type"] == "cache_check":
                if self.parent_service.connections.get("cache"):
                    yield from self._execute_cache_logic(step, span)

            elif step["type"] == "db_query":
                if self.parent_service.connections.get("database"):
                    yield from self._execute_db_logic(step, span)

            elif step["type"] == "service_calls":
                # Call dep_* connections
                yield from self._execute_service_calls(step, span)

            elif step["type"] == "external_calls":
                # Call ext_* connections
                yield from self._execute_external_calls(step, span)

            elif step["type"] == "queue_publish":
                if self.parent_service.connections.get("queue_out"):
                    yield from self._execute_queue_publish(step, span)
```

## Processing Pipeline vs Background Processes

**Important distinction:**

### Pipeline Operations (Part of Request Processing)
- Executed sequentially for each request
- Examples: `cache_check`, `db_query`, `service_calls`, `external_calls`, `queue_publish`
- Triggered by: Incoming HTTP requests or queue messages

### Background Processes (Continuous)
- Run independently in the background
- Example: `queue_consume` (only if service has `queue_in` connection)
- Triggered by: Service startup, runs continuously
- When message arrives → triggers request processing → executes pipeline

**Queue operations:**
- `queue_publish`: Pipeline step, happens during request processing
- `queue_consume`: Background process, pulls messages and triggers pipeline execution

## Processing Pipeline

### Pipeline Definition

Each service defines an ordered list of processing steps. All compute agents of that service execute the same pipeline.

**Example Pipelines**:
```python
# Cache-first service
pipeline_a = [
    {"type": "cache_check"},
    {"type": "service_calls", "probability": 0.7},
    {"type": "db_query"},
    {"type": "queue_publish", "probability": 0.5}
]

# External API-first service
pipeline_b = [
    {"type": "external_calls", "probability": 0.8},
    {"type": "db_query"},
    {"type": "service_calls", "probability": 0.5}
]

# Simple service with just DB
pipeline_c = [
    {"type": "db_query"}
]
```

### Topology Constraints

**Critical**: Pipeline steps are constrained by topology connections:
- `cache_check`: Only executes if service has `cache` connection
- `db_query`: Only executes if service has `database` connection
- `service_calls`: Only executes if service has `dep_*` connections
- `external_calls`: Only executes if service has `ext_*` connections
- `queue_publish`: Only executes if service has `queue_out` connection

**No connection = step is skipped automatically**

### Default Pipeline

If no pipeline is specified, use default:
```python
[
    {"type": "cache_check"},
    {"type": "service_calls"},
    {"type": "db_query"},
    {"type": "external_calls"},
    {"type": "queue_publish"}
]
```

## Topology Structure

```json
{
  "nodes": [
    {
      "id": "svc_a",
      "type": "Service",
      "service_name": "service_a",
      "supported_request_types": ["GET", "POST"],
      "processing_pipeline": [
        {"type": "cache_check"},
        {"type": "db_query"},
        {"type": "service_calls", "probability": 0.7}
      ]
    },
    {
      "id": "db_0",
      "type": "Database"
    },
    {
      "id": "cache_0",
      "type": "Cache"
    },
    {
      "id": "pod_a_0",
      "type": "Pod",
      "parent_service": "svc_a"
    }
  ],
  "edges": [
    {"source": "svc_a", "target": "svc_b", "type": "sync_rpc", "connection_name": "dep_svc_b"},
    {"source": "svc_a", "target": "ext_api_0", "type": "sync_external", "connection_name": "ext_api"},
    {"source": "svc_a", "target": "db_0", "type": "sync_db", "connection_name": "database"},
    {"source": "svc_a", "target": "cache_0", "type": "sync_cache", "connection_name": "cache"},
    {"source": "svc_a", "target": "queue_0", "type": "async_produce", "connection_name": "queue_out"},
    {"source": "queue_0", "target": "svc_b", "type": "async_consume", "connection_name": "queue_in"},
    {"source": "svc_a", "target": "pod_a_0", "type": "pod_pool", "connection_name": "pod_pool"}
  ]
}
```

## Edge Types and Connection Mapping

| Edge Type | Connection Name | Operation Type | Triggered By |
|-----------|----------------|----------------|--------------|
| `sync_rpc` | `dep_*` | Service-to-service call | Pipeline step: `service_calls` |
| `sync_external` | `ext_*` | External API call | Pipeline step: `external_calls` |
| `sync_db` | `database` | Database query | Pipeline step: `db_query` |
| `sync_cache` | `cache` | Cache get/set | Pipeline step: `cache_check` |
| `async_produce` | `queue_out` | Publish message | Pipeline step: `queue_publish` |
| `async_consume` | `queue_in` | Consume message | Background process |
| `pod_pool` | `pod_pool` | Internal routing | Service load balancing |

**Key insight:** `async_consume` creates a background process, while `async_produce` is a pipeline step.

## Request Flow

### HTTP Request Flow
```
1. LoadGenerator sends request → Service
2. Service.handle_request()
   - Validates request_type in supported_request_types
   - Calls get_pod_target() to pick healthy Pod
   - Forwards to Pod.handle_request()

3. Pod.handle_request()
   - Gets parent_service.processing_pipeline
   - For each step in pipeline:
     a. Check if required connection exists in parent_service.connections
     b. If yes, execute step
     c. If no, skip step

4. Step Execution Examples:
   - cache_check: Access parent_service.connections['cache']
   - db_query: Access parent_service.connections['database']
   - service_calls: Find all parent_service.connections['dep_*']
     → For each dep, call dep_service.handle_request() (goes back to step 1)
   - external_calls: Find all parent_service.connections['ext_*']
   - queue_publish: Access parent_service.connections['queue_out']
```

### Queue Consumption Flow (Background Process)
```
1. Service starts with queue_in connection
   → Each Pod starts _consume_from_queue() background process

2. Background loop (continuous):
   a. Wait for message from parent_service.connections['queue_in']
   b. Message arrives
   c. Pick request_type from parent_service.supported_request_types
   d. Call self.handle_request(request_type) → executes normal pipeline
   e. On success: delete message
   f. On failure: leave message for retry (visibility timeout)
   g. Go back to step 2a

3. Pipeline execution same as HTTP flow (step 3 above)
```

**Key difference:** Queue consumption is event-driven (triggered by queue messages), while HTTP requests are load generator-driven.

## Metrics

### Service-Level Metrics (Optional)
- Request count by service (aggregated from pods)
- Can be computed by tagging Pod metrics with `service.name`

### Pod Metrics (Primary)
All existing metrics, tagged with:
- `component.id`: pod ID
- `service.name`: parent service name

Examples:
- `container.cpu.utilization` with tag `service.name=svc_a`
- `connection_pool.connections.active` with tag `service.name=svc_a`

## Implementation Steps

### Phase 1: Rename and Restructure

1. **Rename ComputeAgent → Pod**
   - Rename file: `src/components/compute.py` → `src/components/pod.py`
   - Rename class: `ComputeAgent` → `Pod`
   - Update all imports and references throughout codebase

2. **Create new lightweight Service class**
   - Replaces current `ApiService` in `src/components/service.py`
   - No computation logic, just routing and metadata
   - Holds processing pipeline definition

### Phase 2: Move Logic from ApiService to Pod

3. **Add `parent_service` reference to Pod**
   - Pod needs to access service connections
   - Pass in constructor: `Pod(env, id, parent_service=service)`

4. **Move service logic to Pod**
   - Move `_call_downstream_dependencies()` from ApiService → Pod
   - Move `_consume_from_queue()` from ApiService → Pod
   - Move service-to-service call logic from ApiService → Pod
   - Move external service call logic from ApiService → Pod

5. **Implement processing pipeline executor in Pod**
   - Pod reads `self.parent_service.processing_pipeline`
   - Executes steps in order, checking for required connections
   - Access connections via `self.parent_service.connections`

### Phase 3: Update Topology and Remove Old Code

6. **Update topology builder**
   - Create Service + Pod architecture
   - Assign pods to services
   - Use `pod_pool` connection type (not `compute_pool`)

7. **Remove old ApiService class**
   - Delete all ApiService subclasses (ProductCatalogService, etc.)
   - Remove domain-specific logic
   - Remove hardcoded request types (browse_products, place_order, etc.)
   - Remove CACHE_ENABLED_REQUESTS dictionary

8. **Update metrics**
   - Pod metrics should include `service.name` tag
   - Update metric names if needed

9. **Update visualization**
   - Show Service → Service edges
   - Show Pod nodes behind services
   - Update topology rendering

10. **Test with generic topology**
    - Create test topology with generic services
    - Verify pipeline execution
    - Test queue consumption, service calls, etc.

## Benefits

1. **Simplified**: Single processing model, no duplication
2. **Realistic**: Matches real microservices (pod instances do everything)
3. **Flexible**: Pipeline order configurable per service
4. **Generic**: No hardcoded domain logic
5. **Topology-driven**: All behavior defined by connections
6. **Clear separation**: Service = logical grouping, Pod = container execution

## Migration Notes

### Files to Change

**Rename**:
- `src/components/compute.py` → `src/components/pod.py`
- Class `ComputeAgent` → `Pod`

**Rewrite**:
- `src/components/service.py` - Replace ApiService with lightweight Service

**Remove**:
- All ApiService subclasses (ProductCatalogService, OrderService, etc.)
- Domain-specific logic in service.py
- Hardcoded request types (browse_products, place_order, etc.)
- CACHE_ENABLED_REQUESTS dictionary

**Update**:
- All topology generators (use Pod, pod_pool)
- Visualization code (show Service + Pod layers)
- All imports of ComputeAgent
- Metrics tags (add service.name)

### Breaking Changes

- Topology JSON format changes: `compute_pool` → `pod_pool`
- Component type changes: `ComputeAgent` → `Pod`
- ApiService no longer exists, use Service + Pod
- Processing logic now in Pod, not Service

## Relationship to FixServices2.md

This document describes the **base 2-layer Service/Pod architecture**.

**FixServices2.md** extends this design by adding a third layer and orchestration:

1. **Compute Node layer**: Physical/VM resources that host multiple pods
   - Finite resources (CPU, memory, network)
   - Multiple pods share same node (noisy neighbor scenarios)
   - Node-level failures affect all co-located pods

2. **DeploymentController**: Centralized orchestrator with global scheduling
   - Maintains desired replica counts for services
   - Smart pod placement across nodes (prevents cascading failures)
   - Rate limiting and coordinated scheduling

3. **Enhanced metrics**: Pod metrics tagged with `node.id` for correlation

**When to use each**:
- **This design (2-layer)**: Simple deployments, focus on service interactions
- **FixServices2.md (3-layer)**: Need noisy neighbor scenarios, node-level failures, realistic resource contention

**Implementation order**: Implement this design first, then add Node/Controller layer from FixServices2.md if needed.
