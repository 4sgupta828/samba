# Mathematical Framework for Baseline Health

## Problem Statement

We need a **rigorous, mathematical definition** of what constitutes a "healthy" baseline for a distributed system topology. The current approach (success rate > 50%) is ad-hoc and doesn't account for the underlying system dynamics.

## System Model

### 1. **Node-Level Metrics Vector**

For each node `i` in the topology, we observe:

```
M_i = {
    λ_in: incoming request rate (RPS),
    λ_out: outgoing request rate (RPS),
    λ_success: successful request rate (RPS),
    λ_failure: failed request rate (RPS),

    L: latency distribution {p50, p90, p99, max},
    C: connection pool {size, utilization},

    R: resources {
        cpu_util: [0, 1],
        mem_util: [0, 1],
        disk_util: [0, 1],
        queue_depth: integer
    },

    E: error metrics {
        timeout_count,
        circuit_breaker_opens,
        retry_count
    }
}
```

### 2. **System-Level Metrics**

For the entire topology `G = (V, E)`:

```
M_system = {
    Λ_total: total system throughput,
    L_e2e: end-to-end latency distribution,
    SR: success rate = λ_success / λ_in,
    CBR: circuit breaker open ratio
}
```

## Health Criteria (Queueing Theory Approach)

### **Fundamental Theorem**: A system is healthy if it operates **below saturation** for all nodes.

From queueing theory, a service node with:
- Arrival rate: `λ` (requests/second)
- Service rate: `μ` (requests/second)
- Utilization: `ρ = λ / μ`

Is **stable** if and only if `ρ < 1`.

### **Practical Health Thresholds**

For production systems, we want **headroom**:

```
Health Condition: ρ < ρ_max

Where:
  ρ_max = 0.75 for critical components (gateway, frontend)
  ρ_max = 0.85 for backend services
  ρ_max = 0.90 for stateful stores (DB, cache)
```

**Rationale**:
- At ρ = 0.75, average queue length ≈ 1.5 requests (manageable)
- At ρ = 0.90, average queue length ≈ 4.5 requests (borderline)
- At ρ = 1.0, queue length → ∞ (unstable)

## Derivation of Health Metrics

### 1. **Connection Pool Health**

For a connection pool of size `C` with average request latency `L_avg`:

```
Utilization: U_pool = (λ_in × L_avg) / C

Health Condition: U_pool < 0.80
```

**Derivation**:
```
Number of occupied connections = λ_in × L_avg  (Little's Law)
Utilization = occupied / total = (λ_in × L_avg) / C

If U_pool ≥ 0.80: High risk of saturation
If U_pool ≥ 1.00: Guaranteed saturation (requests queue indefinitely)
```

### 2. **CPU Health**

```
Health Condition: cpu_util < 0.80

Why: At 80%+ CPU:
- Context switching overhead increases
- GC pauses become frequent
- Response time variance increases exponentially
```

### 3. **Latency Health**

For a healthy system, latency should follow a **log-normal distribution** with:

```
Health Conditions:
  p50 < T_baseline
  p99 < 10 × p50  (tail latency not excessive)

Where T_baseline depends on component type:
  - Cache: 5ms
  - Database: 10ms
  - Service: 20ms
  - External: 100ms
```

**Unhealthy Pattern**: If `p99 >> 10 × p50`, indicates:
- Queue buildup
- Resource contention
- Cascading failures

### 4. **Error Rate Health**

```
Health Conditions:
  error_rate = λ_failure / λ_in < 0.01  (1% error rate)
  timeout_rate < 0.005  (0.5% timeout rate)
  circuit_breaker_opens = 0  (no CB opens during baseline)
```

### 5. **Success Rate Health**

```
Health Condition: success_rate = λ_success / λ_in > 0.95

Derivation:
  At 95% success:
    - 1 in 20 requests fails (acceptable)
    - Circuit breaker stays closed (threshold = 90%)
    - User experience acceptable

  At <95% success:
    - Risk of circuit breaker opening
    - Cascading failures likely
```

## System-Wide Health Score

Define a **composite health score** `H` for the entire topology:

```
H = min(H_throughput, H_latency, H_resources, H_errors)

Where each component is in [0, 1]:

H_throughput = min_i(1 - ρ_i) / (1 - ρ_max)
H_latency = 1 - (p99_system / T_max)
H_resources = min_i(1 - max(cpu_i, mem_i))
H_errors = 1 - error_rate_system

Health Conditions:
  H > 0.8: Healthy
  0.5 < H ≤ 0.8: Degraded but functional
  H ≤ 0.5: Unhealthy (reject dataset)
```

## Mathematical Validation Algorithm

### **Pre-Simulation Validation** (Topology Analysis)

Before running simulation, validate topology structure:

```python
def validate_topology_structure(G, workload_rps):
    """
    Validate topology can theoretically handle workload.
    Returns: (is_valid, bottleneck_nodes)
    """

    # 1. Find all paths from gateway to leaf nodes
    gateway = find_gateway(G)
    paths = find_all_paths(gateway, G)

    # 2. Calculate theoretical maximum throughput
    for path in paths:
        path_latency = sum(edge['base_latency'] for edge in path)

        # For each node in path, calculate max throughput
        for node in path:
            service_time = node.processing_time + sum(dep_latencies)
            max_throughput = 1 / service_time  # Requests per second

            # Check if node can handle workload
            if workload_rps > max_throughput:
                return False, node  # Bottleneck found!

    # 3. Check connection pool capacity
    for component in [gateway, workload_generator]:
        required_connections = workload_rps * max_path_latency
        if required_connections > component.connection_pool_size:
            return False, component

    return True, None
```

### **Post-Simulation Validation** (Metrics Analysis)

After simulation, analyze collected metrics:

```python
def validate_baseline_health(metrics, fault_start_time):
    """
    Mathematically validate baseline health using queueing theory.
    """
    baseline_metrics = extract_baseline(metrics, 0, fault_start_time)

    # Calculate per-node health
    node_health = {}
    for node_id, node_metrics in baseline_metrics.items():
        # 1. Utilization check (ρ < ρ_max)
        λ_in = node_metrics['incoming_rps']
        L_avg = node_metrics['latency_p50'] / 1000  # Convert to seconds
        C_pool = node_metrics['connection_pool_size']

        ρ = (λ_in * L_avg) / C_pool if C_pool > 0 else float('inf')

        if ρ >= 0.80:
            return False, f"{node_id}: Utilization {ρ:.2f} exceeds 0.80"

        # 2. Latency check (p99/p50 ratio)
        p50 = node_metrics['latency_p50']
        p99 = node_metrics['latency_p99']

        if p99 > 10 * p50:
            return False, f"{node_id}: p99/p50 ratio {p99/p50:.1f} > 10"

        # 3. Error rate check
        error_rate = node_metrics['error_count'] / node_metrics['total_requests']
        if error_rate > 0.01:
            return False, f"{node_id}: Error rate {error_rate:.2%} > 1%"

        # 4. CPU check
        if node_metrics['cpu_util'] > 0.80:
            return False, f"{node_id}: CPU utilization {node_metrics['cpu_util']:.2%} > 80%"

        # 5. Circuit breaker check
        if node_metrics['circuit_breaker_opens'] > 0:
            return False, f"{node_id}: Circuit breaker opened during baseline"

        # Calculate node health score
        h_util = 1 - (ρ / 0.80)
        h_latency = 1 - (p99 / (10 * p50))
        h_errors = 1 - (error_rate / 0.01)
        h_cpu = 1 - (node_metrics['cpu_util'] / 0.80)

        node_health[node_id] = min(h_util, h_latency, h_errors, h_cpu)

    # System health = minimum node health (weakest link)
    system_health = min(node_health.values())

    if system_health < 0.8:
        return False, f"System health score {system_health:.2f} < 0.80"

    return True, f"System health score: {system_health:.2f}"
```

## Proactive Configuration Generation

Instead of **generate-and-validate**, we should **configure-for-health**:

```python
def calculate_safe_workload(topology, target_utilization=0.70):
    """
    Given a topology, calculate the maximum safe workload.

    Uses queueing theory to ensure ρ < target_utilization for all nodes.
    """

    # 1. Calculate critical path (longest latency path)
    critical_path = find_critical_path(topology)
    critical_latency = sum(edge['base_latency'] for edge in critical_path)

    # 2. Find bottleneck node (lowest service rate)
    bottleneck = None
    min_service_rate = float('inf')

    for node in topology.nodes:
        service_time = node.processing_time + sum(dep['base_latency'] for dep in node.dependencies)
        service_rate = 1 / service_time

        if service_rate < min_service_rate:
            min_service_rate = service_rate
            bottleneck = node

    # 3. Calculate safe RPS
    # We want: ρ = λ / μ < target_utilization
    # Therefore: λ < target_utilization × μ

    safe_rps = target_utilization * min_service_rate

    # 4. Calculate required connection pool size
    # N_connections = λ × L_max (Little's Law)
    required_connections = safe_rps * (critical_latency / 1000)

    return {
        'safe_baseline_rps': safe_rps,
        'safe_peak_rps': safe_rps * 1.5,  # Allow 50% burst
        'required_connection_pool': int(required_connections * 2),  # 2x buffer
        'bottleneck_node': bottleneck,
        'critical_path_latency': critical_latency
    }
```

## Implementation Strategy

### Phase 1: **Pre-Flight Validation**

Before starting simulation:

```python
# In generate_dataset.py, BEFORE simulation:

# 1. Analyze topology structure
workload_config = create_dynamic_workload(nx_graph, base_rps=80, peak_rps=200)

# 2. Calculate theoretical capacity
capacity = calculate_safe_workload(nx_graph)

# 3. Adjust workload to match capacity
if workload_config['baseline_rps'] > capacity['safe_baseline_rps']:
    print(f"WARNING: Requested RPS {workload_config['baseline_rps']} exceeds safe capacity {capacity['safe_baseline_rps']}")
    print(f"Auto-adjusting workload to safe levels...")
    workload_config['baseline_rps'] = capacity['safe_baseline_rps']
    workload_config['peak_rps'] = capacity['safe_peak_rps']

# 4. Ensure connection pool is sized correctly
required_pool_size = capacity['required_connection_pool']
if sim.workload_generator.connection_pool_size < required_pool_size:
    print(f"WARNING: Connection pool {sim.workload_generator.connection_pool_size} too small")
    print(f"Required: {required_pool_size}")
    # Either reject or resize
```

### Phase 2: **Runtime Monitoring**

During simulation, track health in real-time:

```python
# Sample health metrics every 10 seconds
# If health drops below threshold during baseline → ABORT simulation early
```

### Phase 3: **Post-Validation**

After simulation, use mathematical criteria:

```python
is_healthy, reason = validate_baseline_health(
    metrics,
    fault_start_time,
    thresholds={
        'max_utilization': 0.80,
        'max_error_rate': 0.01,
        'max_p99_ratio': 10.0,
        'min_success_rate': 0.95,
        'min_health_score': 0.80
    }
)
```

## Key Insights

1. **Health is not just "success rate > X%"**
   - It's about operating below saturation (ρ < ρ_max)
   - It's about latency distributions being predictable
   - It's about no circuit breakers firing
   - It's about resource headroom

2. **We can predict health BEFORE simulation**
   - Queueing theory gives us theoretical bounds
   - We can calculate max safe RPS for any topology
   - We should generate workloads that are PROVABLY safe

3. **Health is the minimum of all components**
   - System is only as healthy as its weakest link
   - One saturated node → entire system unhealthy
   - Must validate ALL nodes, not just aggregate metrics

4. **Dynamic workload adjustment is better than retry**
   - Instead of generating random workload and hoping it works
   - Calculate safe workload for the specific topology
   - Guarantee healthy baseline by construction

## Next Steps

1. Implement `calculate_safe_workload()` function
2. Implement `validate_baseline_health()` with mathematical criteria
3. Add pre-flight topology validation
4. Replace ad-hoc thresholds with queueing theory bounds
5. Add real-time health monitoring during simulation

This transforms baseline health from a **heuristic** to a **mathematical guarantee**.
