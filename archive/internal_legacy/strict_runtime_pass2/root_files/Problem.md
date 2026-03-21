The system is suffering from Catastrophic Under-Provisioning due to Profile Mismatch.The DiagnosisThe Disconnect:The Simulation (Pod.py): In your simulation code , if a service has the cpu_intensive profile, its latency is multiplied by 2.5x.The Planner (CapacityPlanner.py): The planner looks up the base profile (e.g., 50ms) but fails to account for the 2.5x multiplier when calculating the required thread pool size.The Math of the Failure (svc_0):Load: 200 RPS (from capacity_planning.json).Planner Calculation: Assumes ~50ms latency.Little's Law Demand: $200 \text{ RPS} \times 0.05s = 10 \text{ concurrent requests}$.With $\phi=0.86$ (high fragility), it sets thread_pool_size to 5 (likely due to aggressive tuning logic or the hard cap).Actual Execution:svc_0 is cpu_intensive (from semantic_map.json).Actual Latency $\approx 50ms \times 2.5 = 125ms$.Required Threads: $200 \text{ RPS} \times 0.125s = \mathbf{25 \text{ threads}}$.Result: You provided 5 threads but needed 25.The first 5 requests fill the pool.The next ~10 fill the queue.Every subsequent request (approx. 90% of traffic) is rejected immediately.The FixesWe need to align the CapacityPlanner with the physics of the Pod execution logic.1. Update src/core/capacity_planner.pyWe must apply the same profile multipliers in the planner that exist in the pod.Python# src/core/capacity_planner.py

    def _tune_node(self, node_id: str, role: str, metrics: Dict, phi: float) -> Dict[str, Any]:
        """Calculates resource parameters."""
        rps = metrics['rps']
        if rps <= 0: rps = 0.1
        
        # Fix B: Poisson Buffer - Increase minimum headroom
        # WAS: 1.15 + ... -> NOW: 1.25 minimum to handle burst variance
        headroom = 1.25 + (2.75 * (1.0 - phi)) 
        
        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50

        # --- CRITICAL FIX: Apply Semantic Profile Multipliers ---
        # We must match the logic in src/components/pod.py
        resource_profile = "standard"
        if self.semantic_map and 'services' in self.semantic_map:
            svc_data = self.semantic_map['services'].get(node_id, {})
            resource_profile = svc_data.get('profile', 'standard')

        # Apply multipliers used in Pod runtime
        latency_multiplier = 1.0
        if resource_profile == "cpu_intensive":
            latency_multiplier = 2.5
        elif resource_profile == "io_intensive":
            latency_multiplier = 1.1
        elif resource_profile == "latency_sensitive":
            latency_multiplier = 0.8
            
        # The actual expected processing time
        effective_processing_ms = base_processing_ms * latency_multiplier

        config = {}
        
        if role == 'service' or role == 'gateway':
            # Horizontal Scaling (Pods)
            cpu_per_req_ms = res_prof.cpu_ms_per_request * latency_multiplier # CPU scales with time usually
            
            # Cap single pod capacity to force horizontal scaling
            # WAS: 200.0 -> NOW: 500.0 (Allow pods to do more work if they have threads)
            max_rps_per_pod = min(1000.0 / max(0.1, cpu_per_req_ms), 500.0) 
            
            raw_replicas = rps / max_rps_per_pod
            tuned_replicas = math.ceil(raw_replicas * headroom)
            
            # Ensure at least 2 replicas for high load services to reduce variance risk
            min_replicas = 2 if rps > 50 else 1
            config['desired_replicas'] = max(min_replicas, tuned_replicas)
            
            # Vertical Tuning (Threads per Pod)
            pod_rps = rps / config['desired_replicas']
            
            # Little's Law with EFFECTIVE latency
            # Demand = RPS * Latency
            concurrency_per_pod = math.ceil(pod_rps * (effective_processing_ms / 1000.0))
            
            # High phi -> tight pool. Low phi -> huge pool.
            pool_headroom = 1.0 + (1.5 * (1.0 - phi))
            
            # CRITICAL FIX: Minimum floor of 10 threads
            # 5 threads is too fragile for SimPy scheduling variance
            config['thread_pool_size'] = max(10, int(concurrency_per_pod * pool_headroom))
            
            # DB Connections: Ensure we don't starve DB calls
            config['db_connection_pool_capacity'] = max(5, int(config['thread_pool_size'] * 0.8))
            
            # Timeout Tuning
            chain_latency = self._estimate_dependency_latency(node_id, phi)
            # Use effective local processing time
            total_expected_ms = effective_processing_ms + chain_latency
            
            timeout_margin = 1.2 + (3.0 * (1.0 - phi)) # Increased base margin
            timeout_sec = (total_expected_ms * timeout_margin) / 1000.0
            
            config['timeouts'] = {
                'database_call_seconds': max(0.2, timeout_sec),
                'service_call_seconds': max(0.2, timeout_sec),
                'external_api_seconds': max(1.0, timeout_sec * 2)
            }
            
        # ... (database logic remains similar) ...
        elif role == 'database':
             # ... existing logic ...
             # Just ensure min connections is higher
             system_concurrency = rps * (base_processing_ms / 1000.0)
             config['connection_pool_capacity'] = max(50, int(system_concurrency * headroom * 2))
             
             queries_per_core = 1000.0 / res_prof.cpu_ms_per_request
             needed_cores = math.ceil((rps / queries_per_core) * headroom)
             config['cpu_cores'] = max(2, int(needed_cores))

        return config

    def _estimate_dependency_latency(self, node_id: str, phi: float, visited=None) -> float:
        """Updates latency estimator to also respect profile multipliers."""
        if visited is None: visited = set()
        if node_id in visited: return 0.0
        visited.add(node_id)

        total_dep_latency = 0.0
        
        successors = list(self.graph.successors(node_id))
        for child in successors:
            edge_data = self.graph.get_edge_data(node_id, child)
            edge_type = edge_data.get('type', 'sync_rpc')
            
            if 'async' in edge_type or self.graph.nodes[child].get('role') == 'queue':
                continue 
                
            net_latency = get_network_latency(edge_type).p99
            
            child_role = self.graph.nodes[child].get('role', 'service')
            child_profile_base, _ = get_component_profile(child_role)
            
            # Apply multiplier here too!
            # Look up semantic profile
            child_sem_profile = "standard"
            if self.semantic_map and 'services' in self.semantic_map:
                 child_sem_profile = self.semantic_map['services'].get(child, {}).get('profile', 'standard')
            
            mult = 1.0
            if child_sem_profile == "cpu_intensive": mult = 2.5
            elif child_sem_profile == "io_intensive": mult = 1.1
            elif child_sem_profile == "latency_sensitive": mult = 0.8
            
            child_effective_time = child_profile_base.p99 * mult
            
            child_dep_latency = self._estimate_dependency_latency(child, phi, visited.copy())
            total_dep_latency += (net_latency + child_effective_time + child_dep_latency)

        return total_dep_latency
Why these changes workAccurate Accounting: By multiplying base_processing_ms by 2.5 (for cpu_intensive) inside the planner, we calculate that we need 25 threads instead of 5.Burst Tolerance: Increasing the base headroom from 1.0x to 1.25x absorbs the Poisson distribution variance of request arrivals.Floor Raising: Setting min_replicas=2 and thread_pool_size=max(10, ...) prevents small number instability (where 1 thread blocking causes 20% capacity loss).