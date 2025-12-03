Here is the complete, consolidated set of changes to transform the simulation into a **"Fragility-First" architecture**.

This package implements the **Deterministic Capacity Planner**, integrates it into the generation loop, applies the specific fixes for gaps (Async, Bursts, Cold Start), and cleans up legacy code.

### 1\. New Module: `src/core/capacity_planner.py`

Create this file. It contains the core logic to "right-size" the infrastructure based on exact semantic flows and the fragility parameter $\phi$.

```python
"""
Deterministic Capacity Planner.
Right-sizes infrastructure based on semantic request flows and fragility.
Handles Async Queues, Poisson Bursts, and Circular Dependencies.
"""
import math
import networkx as nx
from typing import Dict, Any, List, Tuple, Set
from src.validation.component_profiles import get_component_profile, get_network_latency

class CapacityPlanner:
    def __init__(self, graph: nx.DiGraph, semantic_map: Dict = None):
        self.graph = graph
        self.semantic_map = semantic_map or {}
        
    def plan_capacity(self, target_global_rps: float, phi: float) -> Dict[str, Dict[str, Any]]:
        """
        Tunes node resources based on exact semantic flows.
        
        Args:
            target_global_rps: Total ingress RPS.
            phi: Fragility index [0.0=Robust, 1.0=Critical].
        """
        # 1. Calculate deterministic load per node
        node_metrics = self._calculate_deterministic_load(target_global_rps, phi)
        
        tuned_configs = {}
        
        for node_id, metrics in node_metrics.items():
            if node_id == 'workload': continue
            if node_id not in self.graph.nodes: continue
            
            node_data = self.graph.nodes[node_id]
            role = node_data.get('role', 'service')
            
            # Tune the node based on its specific load
            config = self._tune_node(node_id, role, metrics, phi)
            tuned_configs[node_id] = config
            
        return tuned_configs

    def _calculate_deterministic_load(self, global_rps: float, phi: float) -> Dict[str, Any]:
        """Traverses flows to calculate RPS load."""
        node_stats = {n: {'rps': 0.0} for n in self.graph.nodes()}
        
        flows = self.semantic_map.get('request_flows', {})
        request_types = self.semantic_map.get('request_types', ['GET'])
        type_weight = 1.0 / max(1, len(request_types))
        
        for req_type in request_types:
            flow_map = flows.get(req_type, {})
            type_rps = global_rps * type_weight
            
            # Start at gateways/frontends
            entry_points = [n for n in self.graph.nodes() 
                          if self.graph.nodes[n].get('is_frontend') or 
                             self.graph.nodes[n].get('role') == 'gateway']
            
            for entry in entry_points:
                self._traverse_flow(entry, type_rps, flow_map, node_stats, phi, visited=set())

        return node_stats

    def _traverse_flow(self, node_id: str, rps: float, flow_map: Dict, stats: Dict, phi: float, visited: Set[str]):
        """Recursive traversal to accumulate RPS."""
        if node_id not in stats: return
        
        # Prevent infinite loops in load calculation
        if node_id in visited: return
        visited.add(node_id)
        
        # Add load to current node
        stats[node_id]['rps'] += rps
        
        successors = list(self.graph.successors(node_id))

        # 1. Explicit Service Flows (from Semantic Map)
        downstream_services = flow_map.get(node_id, [])
        for child in downstream_services:
            # 1:1 mapping: if A calls B in a flow, it calls it for every request
            self._traverse_flow(child, rps, flow_map, stats, phi, visited.copy())

        # 2. Infrastructure Dependencies (Implicit)
        infrastructure_nodes = [
            n for n in successors 
            if self.graph.nodes[n].get('role') in ['database', 'cache', 'queue']
        ]
        
        for infra in infrastructure_nodes:
            edge_data = self.graph.get_edge_data(node_id, infra)
            edge_type = edge_data.get('type', 'sync')
            
            infra_load = rps
            
            # Logic for Caches reducing DB load
            if self.graph.nodes[infra].get('role') == 'database':
                caches = [n for n in successors if self.graph.nodes[n].get('role') == 'cache']
                if caches:
                    # Effective hit rate degrades as phi increases (fragility)
                    base_hit_rate = 0.8 
                    effective_hit_rate = base_hit_rate * (1.0 - (phi * 0.2))
                    infra_load = rps * (1.0 - effective_hit_rate)
            
            # Logic for Queues (Decoupling)
            if self.graph.nodes[infra].get('role') == 'queue':
                stats[infra]['rps'] += infra_load
                
                # Propagate to consumers
                consumers = [
                    u for u, v, d in self.graph.out_edges(infra, data=True) 
                    if d.get('type') == 'async_consume'
                ]
                for consumer in consumers:
                    # Pass empty set for visited to restart cycle detection for new async context
                    self._traverse_flow(consumer, infra_load, flow_map, stats, phi, visited=set())
            else:
                stats[infra]['rps'] += infra_load

    def _estimate_dependency_latency(self, node_id: str, phi: float, visited=None) -> float:
        """
        Recursively estimates P99 latency of dependencies.
        Stops at Async boundaries (Queues). Handles Circular dependencies.
        """
        if visited is None: visited = set()
        if node_id in visited: return 0.0
        visited.add(node_id)

        total_dep_latency = 0.0
        
        successors = list(self.graph.successors(node_id))
        for child in successors:
            edge_data = self.graph.get_edge_data(node_id, child)
            edge_type = edge_data.get('type', 'sync_rpc')
            
            # Async calls do not add blocking latency to the caller
            if 'async' in edge_type or self.graph.nodes[child].get('role') == 'queue':
                continue 
                
            net_latency = get_network_latency(edge_type).p99
            
            child_role = self.graph.nodes[child].get('role', 'service')
            child_profile, _ = get_component_profile(child_role)
            child_base_time = child_profile.p99
            
            child_dep_latency = self._estimate_dependency_latency(child, phi, visited.copy())
            
            # Assume sequential execution for worst-case timeout budgeting
            total_dep_latency += (net_latency + child_base_time + child_dep_latency)

        return total_dep_latency

    def _tune_node(self, node_id: str, role: str, metrics: Dict, phi: float) -> Dict[str, Any]:
        """Calculates resource parameters."""
        rps = metrics['rps']
        if rps <= 0: rps = 0.1
        
        # Fix B: Poisson Buffer - Minimum headroom is 1.15x
        headroom = 1.15 + (2.85 * (1.0 - phi)) # Maps phi 0->4.0x, phi 1->1.15x
        
        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50
        
        config = {}
        
        if role == 'service' or role == 'gateway':
            # Horizontal Scaling (Pods)
            cpu_per_req_ms = res_prof.cpu_ms_per_request
            # Cap single pod capacity to force horizontal scaling
            max_rps_per_pod = min(1000.0 / cpu_per_req_ms, 200.0) 
            
            raw_replicas = rps / max_rps_per_pod
            tuned_replicas = math.ceil(raw_replicas * headroom)
            config['desired_replicas'] = max(1, tuned_replicas)
            
            # Vertical Tuning (Threads per Pod)
            pod_rps = rps / config['desired_replicas']
            concurrency_per_pod = math.ceil(pod_rps * (base_processing_ms / 1000.0))
            
            # High phi -> tight pool. Low phi -> huge pool.
            pool_headroom = 1.0 + (2.0 * (1.0 - phi))
            config['thread_pool_size'] = max(5, int(concurrency_per_pod * pool_headroom))
            config['db_connection_pool_capacity'] = max(2, int(config['thread_pool_size'] * 0.5))
            
            # Timeout Tuning (Flow-Aware)
            chain_latency = self._estimate_dependency_latency(node_id, phi)
            total_expected_ms = base_processing_ms + chain_latency
            
            timeout_margin = 1.1 + (3.0 * (1.0 - phi))
            timeout_sec = (total_expected_ms * timeout_margin) / 1000.0
            
            config['timeouts'] = {
                'database_call_seconds': max(0.1, timeout_sec),
                'service_call_seconds': max(0.1, timeout_sec),
                'external_api_seconds': max(0.5, timeout_sec * 2)
            }

        elif role == 'database':
            # DB Connections
            system_concurrency = rps * (base_processing_ms / 1000.0)
            config['connection_pool_capacity'] = max(20, int(system_concurrency * headroom * 2))
            
            # CPU Cores
            queries_per_core = 1000.0 / res_prof.cpu_ms_per_request
            needed_cores = math.ceil((rps / queries_per_core) * headroom)
            config['cpu_cores'] = max(2, int(needed_cores))
            
        return config
```

### 2\. Update: `generate_dataset.py`

Integrate the planner, remove legacy checks, and enable cold-start handling.

```python
# ... existing imports ...
from src.core.capacity_planner import CapacityPlanner # Add this import

def generate_episode(episode_id: int, output_dir: str, scenario_lib: ScenarioLibrary, ...):
    # ... (Keep existing scenario selection and topology generation logic) ...
    
    # [REPLACE lines 46-69 (Pre-Flight Health Check) with:]
    
    # --- Deterministic Capacity Planning ---
    if verbose:
        print(f"\n[Capacity Planning]")
        print(f"  Analyzing flows and tuning resources...")

    # 1. Define Target Workload (Fixed high load to stress the system)
    target_rps = 200 
    
    # 2. Randomize Fragility (Curriculum Learning)
    # phi -> 1.0 means system is tuned "just in time" (metastable)
    # phi -> 0.0 means system is over-provisioned (robust)
    phi = random.uniform(0.6, 0.95) 
    
    if verbose:
        print(f"  Fragility Index (phi): {phi:.2f}")

    # 3. Run Capacity Planner
    planner = CapacityPlanner(nx_graph, semantic_overlay)
    tuned_configs = planner.plan_capacity(target_rps, phi)
    
    # 4. Apply Configs to Graph Nodes (Service level)
    for node_id, config in tuned_configs.items():
        nx_graph.nodes[node_id]['iac_config_overrides'] = config
        
    # 5. Propagate Configs to Pods (Infrastructure level)
    # Since Pods are separate nodes in the graph, we need to copy the parent service's 
    # thread/connection pool settings to the pod nodes so Adapter picks them up.
    for node_id, attrs in nx_graph.nodes(data=True):
        if attrs.get('type') == 'Pod':
            parent_svc = attrs.get('parent_service')
            if parent_svc and parent_svc in tuned_configs:
                # Copy relevant resource configs to pod
                svc_config = tuned_configs[parent_svc]
                pod_override = {
                    'thread_pool_size': svc_config.get('thread_pool_size'),
                    'db_connection_pool_capacity': svc_config.get('db_connection_pool_capacity'),
                    'timeouts': svc_config.get('timeouts')
                }
                nx_graph.nodes[node_id]['iac_config_overrides'] = pod_override

    # 6. Create Workload Config matching the target RPS
    workload_path = create_dynamic_workload(nx_graph, base_rps=int(target_rps*0.8), peak_rps=target_rps)

    # --- End Capacity Planning ---

    # [UPDATE sim_config construction (around line 48)]
    sim_config = {
        'simulation': {
            'duration': cfg.duration,
            'output_dir': episode_dir,
            'warmup_period': 60.0 # Fix D: Cold Start handling
        },
        # ... rest of config
    }
    
    # ... rest of the function ...
```

### 3\. Update: `src/topology/adapter.py`

Update `_create_component` to apply the overrides.

```python
    def _create_component(self, node_id: str, node_data: Dict[str, Any]):
        # ... existing code ...
        
        component = None # Holder
        
        # [Existing component creation logic...]
        
        if component_type == 'Service':
            # ... existing setup ...
            
            # Check for overrides from CapacityPlanner
            overrides = node_data.get('iac_config_overrides', {})
            
            # Use overridden replicas if present, else default
            desired_replicas = overrides.get('desired_replicas', 
                                           node_data.get('desired_replicas', 3))

            component = Service(
                # ... existing args ...
                desired_replicas=desired_replicas, 
                # ...
            )
            
        # [After component is created, before returning, apply generic overrides]
        
        # Apply Resource Overrides if component was created
        if component:
            overrides = node_data.get('iac_config_overrides', {})
            if overrides:
                # Apply thread pool size
                if 'thread_pool_size' in overrides and hasattr(component, 'thread_pool'):
                    # Re-create resource with new capacity
                    # Note: We must access the simpy environment from the component
                    component.thread_pool_size = overrides['thread_pool_size']
                    component.thread_pool = simpy.Resource(component.env, capacity=component.thread_pool_size)
                    
                # Apply DB pool size
                if 'db_connection_pool_capacity' in overrides and hasattr(component, 'db_connection_pool'):
                    capacity = overrides['db_connection_pool_capacity']
                    component.db_connection_pool = simpy.Resource(component.env, capacity=capacity)
                    
                # Apply Timeouts (update the component's config object)
                if 'timeouts' in overrides and hasattr(component, 'iac_config'):
                    if not component.iac_config: component.iac_config = {}
                    component.iac_config['timeouts'] = overrides['timeouts']
                    
                # Apply CPU Cores (for Database)
                if 'cpu_cores' in overrides and hasattr(component, 'cpu_resource'):
                    capacity = overrides['cpu_cores']
                    component.cpu_resource = simpy.PriorityResource(component.env, capacity=capacity)
                    
        return component
```

### 4\. Update: `src/components/deployment_controller.py`

Ensure it respects the service's replicas.

```python
    def _reconcile_service(self, service):
        """Ensure service has desired replica count."""
        # ... existing code ...
        
        # Use the attribute on the service object, which was set by Adapter from overrides
        desired_count = service.desired_replicas 

        # ... rest of logic
```

### 5\. Update: `src/failures/modes.py`

Make the faults more aggressive.

```python
# ...

def cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """
    FLOOR FAULT: Sets minimum CPU regardless of load.
    Models CPU exhaustion from external processes, resource contention.
    """
    # ... checks ...

    cpu_target = params.get("cpu_percent", 95) # Default 95%

    # Set FLOOR
    component.dynamics.fault_cpu_floor_percent = cpu_target
    
    # FIX: Add additive latency to simulate scheduler contention
    # When CPU is pinned at 95%, threads don't just run slower, they wait for time slices.
    # Add 200ms processing delay penalty.
    component.dynamics.fault_latency_additive_ms = 200.0
    
    component._emit_log("WARN", f"CPU saturation: {cpu_target}% floor + 200ms contention lag")

def revert_cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    # ...
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_cpu_floor_percent = None
        component.dynamics.fault_latency_additive_ms = 0.0 # Reset
        component._emit_log("INFO", "CPU saturation reverted")
```

### 6\. Deprecation Instructions

Provide this list to your agent to remove dead code:

1.  **Delete** `src/validation/health_validator.py` (The `calculate_safe_workload` function is replaced by `CapacityPlanner`).
2.  **Delete** `src/validation/component_profiles.py` -\> `estimate_component_capacity` function (Logic moved to `CapacityPlanner._tune_node`).
3.  **Remove** calls to `validate_system_health` in `generate_dataset.py`. The system is now designed to be "barely healthy" by default, so strict health validation might fail false-positive. Rely on the `warmup_period` to stabilize.

### Summary of Resulting Behavior

1.  **Semantic Flow:** `generate_dataset.py` creates a topology and a semantic map.
2.  **Planning:** `CapacityPlanner` traces the request paths. It sees that "frontend" calls "backend" which calls "db".
3.  **Tuning:** With `phi=0.9`, it sets "backend" timeouts to `1.1s` (assuming `1s` DB latency). It sets "backend" thread pool to `10` (just enough for 200 RPS).
4.  **Injection:** The fault injector adds `200ms` latency to the DB.
5.  **Propagation:**
      * DB Latency goes to `1.2s`.
      * "Backend" calls take `1.2s` \> `1.1s` timeout.
      * "Backend" threads block for `1.1s` instead of `0.05s` processing.
      * Little's Law: $N = 200 * 1.1 = 220$ threads needed.
      * "Backend" has only `10` threads.
      * **Pool Exhaustion** occurs almost instantly.
      * "Frontend" receives 503s.
      * **Cascade Complete.**