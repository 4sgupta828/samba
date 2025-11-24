# Service/Pod/Node Architecture Design

## Overview

This design introduces a realistic Kubernetes-like architecture with three layers:
1. **Service**: Logical grouping (lightweight coordinator)
2. **Pod**: Container instances (renamed from ComputeAgent)
3. **Compute Node**: Physical/VM layer that hosts multiple pods

## Motivation

Current architecture lacks the **compute node layer** where multiple pods share physical resources, leading to:
- **Noisy neighbor problems**: One pod's CPU/memory usage affects co-located pods
- **Node-level failures**: All pods on a node fail together
- **Resource contention**: Pods compete for finite node resources
- **Realistic scheduling**: Topology must decide pod → node placement

## Three-Layer Architecture

```
Service (logical)
  ├─ Pod 1 ──┐
  ├─ Pod 2 ──┼─→ Compute Node A (8 CPU, 32GB RAM)
  └─ Pod 3 ──┘

Service B (logical)
  ├─ Pod 4 ──┐
  └─ Pod 5 ──┼─→ Compute Node B (8 CPU, 32GB RAM)
             │
Other Service
  └─ Pod 6 ──┘
```

**Key insight**: Pods on same node contend for resources → realistic noisy neighbor scenarios

## Component Definitions

### 1. Service (Lightweight Coordinator)

**No changes from FixServices.md** - still just logical grouping and load balancing.

```python
class Service(EnrichedComponent):
    def __init__(self, env, component_id, service_name, processing_pipeline=None):
        self.service_name = service_name
        self.supported_request_types = []
        self.processing_pipeline = processing_pipeline
        # Connections: dep_*, ext_*, queue_in, queue_out, database, cache

    def handle_request(self, request_type, should_trace, parent_span_context):
        """Route to healthy pod"""
        pod = self.get_pod_target()
        yield from pod.handle_request(request_type, should_trace, parent_span_context)

    def get_pod_target(self):
        """Load balance to healthy pod in pod_pool"""
        # Returns a healthy Pod from the pool
```

### 2. Pod (Renamed from ComputeAgent)

**Responsibilities**:
- Container instance that executes service logic
- Belongs to a parent Service AND a Compute Node
- Executes parent service's processing pipeline
- Shares compute node resources with other pods (contention!)
- All processing logic from ComputeAgent (cache, DB, service calls, etc.)
- Emits metrics tagged with both service.name AND node.id

**Key Changes**:
- Rename `ComputeAgent` → `Pod`
- Add `compute_node` reference (in addition to `parent_service`)
- Resource usage now constrained by node capacity
- Metrics include `node.id` tag

**Implementation**:
```python
class Pod(EnrichedComponent):
    def __init__(self, env, component_id, parent_service=None, compute_node=None):
        super().__init__(env, component_id, "Pod")
        self.parent_service = parent_service
        self.compute_node = compute_node  # NEW: Reference to physical node

        # Register this pod with the node
        if self.compute_node:
            self.compute_node.register_pod(self)

        # All existing ComputeAgent logic (dynamics, thread pool, etc.)

    def _handle_request_internal(self, request_type, span):
        # Check node-level resource availability BEFORE processing
        if self.compute_node and not self.compute_node.can_accept_work():
            # Node is overloaded - throttle or fail
            self._emit_log("WARN", "Node overloaded, request throttled")
            yield self.env.timeout(0.1)  # Throttling delay

        # Execute parent service's processing pipeline
        pipeline = self.parent_service.processing_pipeline
        for step in pipeline:
            # ... same as FixServices.md

    def _report_cpu_utilization(self, options):
        """Emit CPU metric tagged with node.id"""
        from opentelemetry.metrics import Observation

        avg_cpu = self.dynamics.get_cpu_percent()
        yield Observation(avg_cpu, {
            "component.id": self.id,
            "service.name": self.parent_service.service_name,
            "node.id": self.compute_node.id if self.compute_node else "unknown",
            "sim.time": self.env.now
        })

    def _report_memory_usage(self, options):
        """Emit memory metric tagged with node.id"""
        from opentelemetry.metrics import Observation

        avg_memory = self.dynamics.get_memory()
        yield Observation(avg_memory, {
            "component.id": self.id,
            "service.name": self.parent_service.service_name,
            "node.id": self.compute_node.id if self.compute_node else "unknown",
            "sim.time": self.env.now
        })
```

### 3. Compute Node (NEW)

**Responsibilities**:
- Physical/VM layer that hosts multiple pods
- Finite resources (CPU cores, memory GB, network bandwidth)
- Resource contention between co-located pods
- Node-level failures (affects all pods)
- Emits node-level metrics (aggregated from pods)

**Implementation**:
```python
class ComputeNode(EnrichedComponent):
    def __init__(self, env, component_id, cpu_cores=8, memory_gb=32, network_bandwidth_gbps=10):
        super().__init__(env, component_id, "ComputeNode")

        # Node capacity
        self.cpu_cores = cpu_cores
        self.memory_gb = memory_gb
        self.network_bandwidth_gbps = network_bandwidth_gbps

        # Pods running on this node
        self.pods = []  # List of Pod objects

        # Node-level metrics
        self.node_cpu_metric = self.meter.create_observable_gauge(
            "node.cpu.utilization",
            callbacks=[self._report_node_cpu],
            unit="%",
            description="Total CPU utilization across all pods on this node"
        )
        self.node_memory_metric = self.meter.create_observable_gauge(
            "node.memory.usage_gb",
            callbacks=[self._report_node_memory],
            unit="GB",
            description="Total memory usage across all pods on this node"
        )
        self.node_pod_count_metric = self.meter.create_observable_gauge(
            "node.pods.count",
            callbacks=[self._report_pod_count],
            description="Number of running pods on this node"
        )

    def register_pod(self, pod):
        """Register a pod to this node"""
        self.pods.append(pod)

    def can_accept_work(self):
        """Check if node has capacity for more work"""
        total_cpu = self.get_total_pod_cpu()
        total_memory = self.get_total_pod_memory()

        # If total usage exceeds capacity, node is overloaded
        if total_cpu > (self.cpu_cores * 100):  # 100% per core
            return False
        if total_memory > (self.memory_gb * 1024):  # Convert to MB
            return False
        return True

    def get_total_pod_cpu(self):
        """Sum CPU usage across all running pods"""
        total = 0
        for pod in self.pods:
            if pod.state.operational == "RUNNING":
                total += pod.dynamics.get_cpu_percent()
        return total

    def get_total_pod_memory(self):
        """Sum memory usage across all running pods"""
        total = 0
        for pod in self.pods:
            if pod.state.operational == "RUNNING":
                total += pod.dynamics.get_memory()
        return total

    def get_running_pods(self):
        """Get list of running pods"""
        return [p for p in self.pods if p.state.operational == "RUNNING"]

    def _report_node_cpu(self, options):
        """Report total CPU utilization across all pods"""
        from opentelemetry.metrics import Observation

        total_cpu = self.get_total_pod_cpu()
        # Normalize to percentage (0-100%)
        cpu_percent = min(total_cpu, 100.0)

        yield Observation(cpu_percent, {
            "node.id": self.id,
            "node.cpu_cores": self.cpu_cores,
            "sim.time": self.env.now
        })

    def _report_node_memory(self, options):
        """Report total memory usage across all pods"""
        from opentelemetry.metrics import Observation

        total_memory_mb = self.get_total_pod_memory()
        memory_gb = total_memory_mb / 1024.0

        yield Observation(memory_gb, {
            "node.id": self.id,
            "node.memory_gb": self.memory_gb,
            "sim.time": self.env.now
        })

    def _report_pod_count(self, options):
        """Report number of running pods"""
        from opentelemetry.metrics import Observation

        running_count = len(self.get_running_pods())

        yield Observation(running_count, {
            "node.id": self.id,
            "sim.time": self.env.now
        })

    def run(self):
        """Node monitoring and health check"""
        while True:
            yield self.env.timeout(5.0)  # Check every 5 simulation seconds

            # Check for node overload
            total_cpu = self.get_total_pod_cpu()
            total_memory = self.get_total_pod_memory()

            if total_cpu > (self.cpu_cores * 100):
                self._emit_log("WARN", f"Node CPU overload: {total_cpu:.1f}% (capacity: {self.cpu_cores * 100}%)")

            if total_memory > (self.memory_gb * 1024):
                self._emit_log("WARN", f"Node memory overload: {total_memory:.1f}MB (capacity: {self.memory_gb * 1024}MB)")
                # Could trigger OOMKiller here - kill a pod
```

## Topology Planning

### Node Allocation Strategy

When generating topology, decide:
1. **How many compute nodes needed?**
   - Based on number of pods and desired density
   - Example: 3 pods per node (average)

2. **How to assign pods to nodes?**
   - **Random**: Simple, realistic
   - **Packed**: Fill nodes to capacity (high contention)
   - **Spread**: Distribute evenly (low contention)
   - **Mixed**: Some nodes packed, some spread

### Topology Structure

```json
{
  "nodes": [
    {
      "id": "node_0",
      "type": "ComputeNode",
      "cpu_cores": 8,
      "memory_gb": 32,
      "network_bandwidth_gbps": 10
    },
    {
      "id": "svc_a",
      "type": "Service",
      "service_name": "service_a",
      "processing_pipeline": [...]
    },
    {
      "id": "pod_a_0",
      "type": "Pod",
      "parent_service": "svc_a",
      "compute_node": "node_0"
    },
    {
      "id": "pod_a_1",
      "type": "Pod",
      "parent_service": "svc_a",
      "compute_node": "node_0"
    },
    {
      "id": "pod_b_0",
      "type": "Pod",
      "parent_service": "svc_b",
      "compute_node": "node_0"
    }
  ],
  "edges": [
    {"source": "svc_a", "target": "pod_a_0", "type": "pod_pool"},
    {"source": "svc_a", "target": "pod_a_1", "type": "pod_pool"},
    {"source": "pod_a_0", "target": "node_0", "type": "pod_placement"},
    {"source": "pod_a_1", "target": "node_0", "type": "pod_placement"},
    {"source": "pod_b_0", "target": "node_0", "type": "pod_placement"}
  ]
}
```

### Node Sizing Examples

**Small deployment (5 services)**:
- 15 pods total (3 per service)
- 3 compute nodes (5 pods per node)
- Node size: 4 cores, 16GB RAM

**Medium deployment (10 services)**:
- 30 pods total (3 per service)
- 6 compute nodes (5 pods per node)
- Node size: 8 cores, 32GB RAM

**Large deployment (20 services)**:
- 60 pods total (3 per service)
- 12 compute nodes (5 pods per node)
- Node size: 16 cores, 64GB RAM

## Resource Contention Scenarios

### 1. Noisy Neighbor - CPU Saturation

**Setup**:
- Node with 8 cores (800% total)
- Pod A (victim): Normal load (50% CPU)
- Pod B (noisy): CPU spike (600% CPU)
- Pod C (affected): Normal load (50% CPU)

**Impact**:
- Total: 700% > 800% capacity
- All pods throttled
- Pod A and C latencies increase despite normal behavior

**Detection**:
- Pod metrics show increased latency
- Node metrics show 100% CPU
- Correlate by `node.id` tag

### 2. Node Memory Exhaustion

**Setup**:
- Node with 32GB RAM
- 5 pods, each using 6GB normally
- One pod has memory leak → grows to 15GB

**Impact**:
- Total: 39GB > 32GB capacity
- Node triggers OOMKiller
- One or more pods killed (lowest priority first)

**Detection**:
- `node.memory.usage_gb` exceeds capacity
- Pod crashes with OOMKilled
- Other pods on same node show restarts

### 3. Network Saturation

**Setup**:
- Node with 10Gbps network
- Pod A: Bulk data transfer (8Gbps)
- Pod B: Latency-sensitive API calls (1Gbps)

**Impact**:
- Network congestion affects Pod B
- API latency spikes
- Packet loss, retransmissions

**Detection**:
- Pod B latency increases
- `node.network.utilization` near 100%
- Correlate by `node.id`

## Failure Scenarios

### 1. Node Failure

**Impact**:
- All pods on node fail simultaneously
- Services with multiple pods on different nodes: degraded
- Services with all pods on failed node: complete outage

**Root cause analysis**:
- Multiple pods fail at same time
- All share same `node.id`
- Node-level issue (hardware, kernel panic, network partition)

### 2. Node Maintenance/Drain

**Scenario**:
- Node scheduled for maintenance
- Pods evicted and rescheduled to other nodes
- Temporary overload on target nodes

**Detection**:
- Pod restarts with different `node.id`
- Spike in pod scheduling events
- Target nodes show increased resource usage

## Metrics Emission Strategy

### How Metrics Are Emitted

**Observable Gauges with Callbacks** (consistent with current architecture):

Both Pod and Node metrics use OpenTelemetry observable gauges:
1. **Telemetry system** periodically calls registered callbacks (every 5-10 simulation seconds)
2. **Callbacks compute current values** on-demand by aggregating pod state
3. **Metrics exported** to JSON/Prometheus format

**Not traffic-driven** - metrics are time-driven (periodic reporting), matching real monitoring systems like Prometheus node_exporter or CloudWatch agent.

### Node Metrics Implementation

```python
class ComputeNode:
    def __init__(self, env, component_id, cpu_cores=8, memory_gb=32):
        # Observable gauges (callbacks invoked by telemetry system)
        self.node_cpu_metric = self.meter.create_observable_gauge(
            "node.cpu.utilization",
            callbacks=[self._report_node_cpu],  # Called every export interval
            unit="%"
        )

    def _report_node_cpu(self, options):
        """
        Callback invoked by telemetry system (e.g., every 5s).
        Aggregates pod metrics on-demand.
        """
        from opentelemetry.metrics import Observation

        # Sum CPU across all running pods
        total_cpu = sum(pod.dynamics.get_cpu_percent()
                       for pod in self.pods
                       if pod.state.operational == "RUNNING")

        # Normalize to 0-100%
        cpu_percent = min(total_cpu / self.cpu_cores, 100.0)

        yield Observation(cpu_percent, {
            "node.id": self.id,
            "node.cpu_cores": self.cpu_cores,
            "sim.time": self.env.now
        })

    def run(self):
        """
        Background process for node management (separate from metrics).
        Monitors resource usage and takes immediate actions.
        """
        while True:
            yield self.env.timeout(1.0)  # Check every simulation second

            # Node management actions (not metrics)
            if self.get_total_pod_memory() > self.memory_gb * 1024:
                self._trigger_oom_killer()

            if self.get_total_pod_cpu() > self.cpu_cores * 100 * 0.95:
                self._emit_log("WARN", f"Node CPU critical: {self.get_total_pod_cpu():.1f}%")
```

**Separation of concerns**:
- **Metrics callbacks**: Periodic (every 5-10s), for observability
- **Node management process**: Continuous (every 1s), for immediate actions (OOMKiller, throttling)

## Metrics

### Pod-Level Metrics (Enhanced)

All existing pod metrics, now tagged with `node.id`:

```python
{
    "component.id": "pod_a_0",
    "service.name": "service_a",
    "node.id": "node_0",  # NEW: Node placement
    "sim.time": 123.45
}
```

Examples:
- `container.cpu.utilization` (pod-level, tagged with node.id)
- `container.memory.usage_mb` (pod-level, tagged with node.id)
- `connection_pool.connections.active` (pod-level, tagged with node.id)

### Node-Level Metrics (NEW)

Aggregated across all pods on the node:

- `node.cpu.utilization` (0-100%, total across all cores)
- `node.memory.usage_gb` (total GB used by all pods)
- `node.pods.count` (number of running pods)
- `node.network.utilization` (future: network throughput)

Tagged with:
```python
{
    "node.id": "node_0",
    "node.cpu_cores": 8,
    "node.memory_gb": 32,
    "sim.time": 123.45
}
```

## Topology Generator Changes

### Algorithm

```python
def generate_topology_with_nodes(num_services, pods_per_service, pods_per_node):
    """
    Generate topology with services, pods, and compute nodes.

    Args:
        num_services: Number of services
        pods_per_service: Pods per service (e.g., 3)
        pods_per_node: Target pods per node (e.g., 5)
    """
    # 1. Create services
    services = [create_service(f"svc_{i}") for i in range(num_services)]

    # 2. Calculate total pods
    total_pods = num_services * pods_per_service

    # 3. Calculate number of nodes needed
    num_nodes = math.ceil(total_pods / pods_per_node)

    # 4. Create compute nodes
    nodes = [create_compute_node(f"node_{i}") for i in range(num_nodes)]

    # 5. Create pods and assign to nodes
    pods = []
    node_idx = 0
    for service in services:
        for pod_num in range(pods_per_service):
            pod = create_pod(f"pod_{service.id}_{pod_num}",
                           parent_service=service,
                           compute_node=nodes[node_idx % num_nodes])
            pods.append(pod)
            node_idx += 1

    # 6. Create edges (service → pod, pod → node)
    # ... topology edges

    return {
        "services": services,
        "pods": pods,
        "nodes": nodes,
        "edges": edges
    }
```

### Placement Strategies

**Round-robin** (default):
```python
for i, pod in enumerate(pods):
    node_idx = i % num_nodes
    pod.compute_node = nodes[node_idx]
```

**Packed** (high contention):
```python
node_idx = 0
pods_on_current_node = 0
for pod in pods:
    pod.compute_node = nodes[node_idx]
    pods_on_current_node += 1
    if pods_on_current_node >= pods_per_node:
        node_idx += 1
        pods_on_current_node = 0
```

**Random** (realistic):
```python
for pod in pods:
    pod.compute_node = random.choice(nodes)
```

## Request Flow (Updated)

```
1. LoadGenerator → Service.handle_request()

2. Service picks healthy Pod via load balancing

3. Pod.handle_request()
   ├─ Check compute_node.can_accept_work() (node overload?)
   ├─ If overloaded: throttle or fail
   └─ Execute processing pipeline
      ├─ Each step contends for node resources
      └─ CPU/memory usage tracked at node level

4. Node monitors total resource usage
   ├─ Aggregate CPU across all pods
   ├─ Aggregate memory across all pods
   └─ Trigger node-level actions (OOMKiller, throttling)
```

## DeploymentController (Centralized Orchestrator)

### Why We Need It

**Problem with per-service scheduling**:
- Services independently reschedule pods without coordination
- Multiple services pick same "best" node simultaneously
- Node becomes overloaded → cascading OOMKills
- No global rate limiting or resource balancing

**Solution: Centralized controller with global knowledge**

### Responsibilities

1. **Monitor all services**: Track desired vs actual replica counts
2. **Detect missing pods**: Terminated, crashed, or OOMKilled
3. **Create replacement pods**: With smart node placement
4. **Global resource scheduling**: Avoid overcrowding nodes
5. **Rate limiting**: Throttle pod creation to prevent thundering herd
6. **Handle scaling**: Service replica count changes

### Implementation

```python
class DeploymentController(EnrichedComponent):
    """
    Centralized pod lifecycle manager (like kube-controller-manager).

    Maintains desired replica counts for all services with global
    knowledge of cluster resources to prevent cascading failures.
    """

    def __init__(self, env, component_id="deployment_controller"):
        super().__init__(env, component_id, "DeploymentController")

        self.services = []  # All services to monitor
        self.compute_nodes = []  # All available compute nodes

        # Rate limiting to prevent thundering herd
        self.max_pods_per_cycle = 3  # Max pods to create per reconciliation
        self.pending_creations = []  # Queue of pending pod creations

    def register_service(self, service):
        """Register a service for monitoring"""
        self.services.append(service)

    def register_node(self, node):
        """Register a compute node for scheduling"""
        self.compute_nodes.append(node)

    def run(self):
        """Main reconciliation loop"""
        while True:
            yield self.env.timeout(5.0)  # Reconcile every 5 simulation seconds

            # Reconcile each service
            for service in self.services:
                self._reconcile_service(service)

            # Process pending pod creations (rate-limited)
            yield from self._process_pending_creations()

    def _reconcile_service(self, service):
        """Ensure service has desired replica count"""
        # Count healthy pods (RUNNING or STARTING)
        healthy_pods = [p for p in service.pods
                       if p.state.operational in ["RUNNING", "STARTING"]]

        current_count = len(healthy_pods)
        desired_count = service.desired_replicas

        if current_count < desired_count:
            # Need to create replacement pods
            missing = desired_count - current_count
            self._emit_log("INFO",
                f"Service {service.service_name}: {current_count}/{desired_count} pods, "
                f"creating {missing} replacements")

            # Add to pending queue (don't create immediately)
            for _ in range(missing):
                self.pending_creations.append(service)

        elif current_count > desired_count:
            # Need to scale down (user changed desired_replicas)
            excess = current_count - desired_count
            self._emit_log("INFO",
                f"Service {service.service_name}: Scaling down by {excess} pods")
            self._scale_down_service(service, excess)

    def _process_pending_creations(self):
        """Create pods from pending queue with rate limiting"""
        if not self.pending_creations:
            return

        # Process up to max_pods_per_cycle
        to_create = self.pending_creations[:self.max_pods_per_cycle]
        self.pending_creations = self.pending_creations[self.max_pods_per_cycle:]

        for service in to_create:
            # Create pod with smart node placement
            new_pod = self._create_pod_for_service(service)
            if new_pod:
                service.pods.append(new_pod)
                self.env.process(new_pod.run())

                # Small delay between pod creations
                yield self.env.timeout(0.1)

    def _create_pod_for_service(self, service):
        """Create a new pod with smart node placement"""
        # Pick best node using global knowledge
        target_node = self._schedule_pod()

        if not target_node:
            self._emit_log("ERROR",
                f"No available nodes for service {service.service_name}! "
                f"Cluster may be overloaded.")
            return None

        # Generate unique pod ID
        pod_id = f"pod_{service.service_name}_{self.env.now:.0f}_{id(service) % 1000}"

        new_pod = Pod(
            env=self.env,
            component_id=pod_id,
            parent_service=service,
            compute_node=target_node
        )

        self._emit_log("INFO",
            f"Created pod {pod_id} for service {service.service_name} "
            f"on node {target_node.id}")

        return new_pod

    def _schedule_pod(self):
        """
        Smart pod scheduling with global resource awareness.

        Returns the best node to place a new pod, or None if cluster is full.
        """
        # 1. Filter out nodes that are overloaded or failing
        available_nodes = [n for n in self.compute_nodes
                          if n.state.operational == "RUNNING"
                          and n.can_accept_work()]

        if not available_nodes:
            self._emit_log("WARN", "No available nodes! Cluster at capacity.")
            return None

        # 2. Score nodes by utilization (lower is better)
        node_scores = []
        for node in available_nodes:
            cpu_util = node.get_total_pod_cpu() / (node.cpu_cores * 100)
            memory_util = node.get_total_pod_memory() / (node.memory_gb * 1024)

            # Combined score (0.0 = empty, 1.0 = full)
            score = (cpu_util + memory_util) / 2.0
            node_scores.append((node, score))

        # 3. Sort by score (pick least loaded)
        node_scores.sort(key=lambda x: x[1])

        best_node = node_scores[0][0]
        best_score = node_scores[0][1]

        self._emit_log("DEBUG",
            f"Selected node {best_node.id} with utilization {best_score*100:.1f}%")

        return best_node

    def _scale_down_service(self, service, count):
        """Scale down service by terminating excess pods"""
        # Pick pods to terminate (prefer least recently started)
        pods_to_terminate = sorted(service.pods,
                                   key=lambda p: p.env.now - getattr(p, 'start_time', 0))[:count]

        for pod in pods_to_terminate:
            self._emit_log("INFO", f"Terminating pod {pod.id} (scale down)")
            pod.state.operational = "TERMINATED"

            if hasattr(pod, 'running_process') and pod.running_process:
                pod.running_process.interrupt("TERMINATED_BY_SCALE_DOWN")

            # Remove from node
            if pod.compute_node:
                pod.compute_node.pods.remove(pod)

            # Remove from service
            service.pods.remove(pod)
```

### Node OOMKiller Integration

When node kills a pod, it just terminates it. DeploymentController detects and reschedules:

```python
class ComputeNode:
    def _trigger_oom_killer(self):
        """Kill the pod using most memory"""
        if not self.pods:
            return

        # Find pod with highest memory usage
        victim = max(self.pods,
                    key=lambda p: p.dynamics.get_memory() if p.state.operational == "RUNNING" else 0,
                    default=None)

        if victim and victim.state.operational == "RUNNING":
            self._emit_log("ERROR",
                f"OOMKiller: Terminating {victim.id} "
                f"(memory: {victim.dynamics.get_memory():.1f}MB)")

            victim.state.operational = "TERMINATED"

            # Interrupt the pod process
            if hasattr(victim, 'running_process') and victim.running_process:
                victim.running_process.interrupt("TERMINATED_BY_OOMKILLER")

            # Remove from node's pod list
            self.pods.remove(victim)

            # DeploymentController will detect missing pod and reschedule
```

### Pod Lifecycle with Controller

```python
class Pod:
    def run(self):
        """Pod lifecycle with permanent termination support"""
        self.start_time = self.env.now  # Track when pod started

        while True:
            self.state.operational = "STARTING"
            self.restarts += 1

            # Startup...
            yield self.env.timeout(random.uniform(5, 10))

            self.state.operational = "RUNNING"
            self._emit_log("INFO", f"Pod started successfully")

            self.running_process = self.env.active_process

            try:
                yield self.env.timeout(3600)  # Run until interrupted

            except simpy.Interrupt as interrupt:
                if interrupt.cause == "OOMKilled":
                    # Temporary failure - try restart with backoff
                    self._emit_log("ERROR", "OOMKilled, attempting restart")
                    backoff = min(10 * (2 ** self.restarts), 300)
                    yield self.env.timeout(backoff)

                elif interrupt.cause in ["TERMINATED_BY_OOMKILLER",
                                        "TERMINATED_BY_SCALE_DOWN"]:
                    # Permanent termination - exit
                    self.state.operational = "TERMINATED"
                    self._emit_log("INFO", f"Pod terminated: {interrupt.cause}")
                    return  # Exit forever

                else:
                    self._emit_log("ERROR", f"Unhandled interrupt: {interrupt.cause}")
                    return

            finally:
                self.running_process = None
```

### Service Changes

Service no longer manages pod lifecycle, just holds pod list:

```python
class Service(EnrichedComponent):
    def __init__(self, env, component_id, service_name, desired_replicas=3):
        self.service_name = service_name
        self.desired_replicas = desired_replicas  # Target replica count
        self.pods = []  # Pod list (managed by DeploymentController)

    def get_pod_target(self):
        """Load balance to healthy pod"""
        healthy_pods = [p for p in self.pods
                       if p.state.operational == "RUNNING"]
        if healthy_pods:
            return random.choice(healthy_pods)
        return None

    # No run() method - DeploymentController handles reconciliation
```

### Topology Initialization

```python
def initialize_topology(env, topology_spec):
    """Initialize topology with DeploymentController"""

    # 1. Create DeploymentController
    controller = DeploymentController(env)

    # 2. Create compute nodes
    nodes = []
    for node_spec in topology_spec['nodes']:
        if node_spec['type'] == 'ComputeNode':
            node = ComputeNode(env, node_spec['id'], ...)
            nodes.append(node)
            controller.register_node(node)

    # 3. Create services
    services = []
    for service_spec in topology_spec['services']:
        service = Service(env, service_spec['id'],
                         service_spec['name'],
                         desired_replicas=service_spec.get('replicas', 3))
        services.append(service)
        controller.register_service(service)

    # 4. Create initial pods (controller will maintain them)
    for service in services:
        for i in range(service.desired_replicas):
            # Controller handles scheduling
            pod = controller._create_pod_for_service(service)
            if pod:
                service.pods.append(pod)
                env.process(pod.run())

    # 5. Start controller
    env.process(controller.run())

    return controller, services, nodes
```

## Benefits of DeploymentController

1. **Global resource awareness**: Sees all nodes, all pods
2. **Prevents cascading failures**: Smart scheduling avoids overloaded nodes
3. **Rate limiting**: Max 3 pods/cycle prevents thundering herd
4. **Coordinated scheduling**: No race conditions between services
5. **Realistic**: Matches Kubernetes kube-controller-manager
6. **Handles scaling**: Change desired_replicas, controller reconciles
7. **Graceful degradation**: If no nodes available, logs error (doesn't crash)

## Cascading Failure Prevention Example

**Scenario**: Node becomes overloaded, kills 3 pods from different services

**Without controller** (naive per-service scheduling):
```
1. Node kills pod_A, pod_B, pod_C
2. Service A: "Best node is node_1!" → creates pod on node_1
3. Service B: "Best node is node_1!" → creates pod on node_1
4. Service C: "Best node is node_1!" → creates pod on node_1
5. Node_1 now overloaded → kills more pods → repeat
```

**With DeploymentController**:
```
1. Node kills pod_A, pod_B, pod_C
2. Controller reconciles (5s later)
3. Detects 3 missing pods from 3 services
4. Rate limit: Create max 3 pods this cycle
5. Global scheduling:
   - pod_A → node_1 (30% util)
   - pod_B → node_2 (35% util)
   - pod_C → node_3 (40% util)
6. Load balanced across nodes, no cascading failure
```

## Implementation Steps

1. Rename `ComputeAgent` → `Pod` (class, files, references)
2. Create `ComputeNode` class with resource tracking
3. Create `DeploymentController` class with global scheduling
4. Add `compute_node` reference to Pod
5. Update Pod metrics to include `node.id` tag
6. Implement node-level resource aggregation
7. Add node capacity checks and OOMKiller
8. Update Pod lifecycle to handle permanent termination
9. Update Service to remove reconciliation logic
10. Update topology generator to create controller, nodes, and initial pods
11. Add node placement strategies (round-robin, packed, random)
12. Implement noisy neighbor scenarios in failure modes
13. Update visualization to show node layer and controller

## Benefits

1. **Realistic noisy neighbor scenarios**: One pod's behavior affects co-located pods
2. **Node-level failures**: All pods on a node fail together
3. **Resource contention**: Finite node capacity creates realistic bottlenecks
4. **Better root cause analysis**: GNN can learn node-level vs pod-level issues
5. **Kubernetes-native terminology**: Pod, Node (more familiar to users)
6. **Correlation**: `node.id` tag enables grouping affected pods

## Migration Notes

- Rename all `ComputeAgent` → `Pod`
- Update `compute.py` → `pod.py`
- Add `compute_node.py` for new ComputeNode class
- Update topology generators to include node allocation
- Update metrics exporters to handle node-level metrics
- Update visualization to show 3-layer hierarchy
