Here are the exact code changes needed to fix the three specific issues you identified: (1) Thread pool sizing based on cumulative latency, (2) Strict timeout margins, and (3) Uncapped workload generator.

### 1\. File: `src/core/simulation_config.py`

**Fix:** Drastically scale up the default `WorkloadGenerator` settings so the test harness never rejects requests.

```python
@dataclass
class WorkloadGeneratorConfig:
    """Workload generator configuration (realistic client behavior)."""
    # FIX: Massive increase to support high-latency chains (e.g. 200 RPS * 15s = 3000 concurrent connections)
    connection_pool_size: int = 5000
    
    # FIX: Increase timeout to prevent client-side timeouts before server responds
    request_timeout_seconds: float = 60.0
    
    # FIX: Larger queue to absorb Poisson bursts without immediate rejection
    max_queue_size: int = 10000
    
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
```

### 2\. File: `src/core/capacity_planner.py`

**Fix:** Update `_tune_node` to calculate thread counts based on **Total Latency** (Local + Downstream) and use **Strict Margins** for timeouts.

```python
    def _tune_node(self, node_id: str, role: str, metrics: Dict, phi: float) -> Dict[str, Any]:
        """Calculates resource parameters."""
        rps = metrics['rps']
        if rps <= 0: rps = 0.1
        
        # Poisson Buffer
        headroom = 1.15 + (2.85 * (1.0 - phi))
        
        latency_prof, res_prof = get_component_profile(role)
        base_processing_ms = latency_prof.p50

        # 1. Determine Semantic Profile & Multiplier
        resource_profile = "standard"
        if self.semantic_map and 'services' in self.semantic_map:
            svc_data = self.semantic_map['services'].get(node_id, {})
            resource_profile = svc_data.get('profile', 'standard')

        latency_multiplier = 1.0
        if resource_profile == "cpu_intensive": latency_multiplier = 2.5
        elif resource_profile == "io_intensive": latency_multiplier = 1.1
        elif resource_profile == "latency_sensitive": latency_multiplier = 0.8
            
        # Effective local processing time
        effective_processing_ms = base_processing_ms * latency_multiplier

        config = {}
        
        if role == 'service' or role == 'gateway':
            # --- Horizontal Scaling ---
            cpu_per_req_ms = res_prof.cpu_ms_per_request * latency_multiplier
            max_rps_per_pod = min(1000.0 / max(0.1, cpu_per_req_ms), 500.0)
            
            tuned_replicas = math.ceil((rps / max_rps_per_pod) * headroom)
            min_replicas = 2 if rps > 50 else 1
            config['desired_replicas'] = max(min_replicas, tuned_replicas)
            
            # --- Vertical Tuning (Threads per Pod) ---
            pod_rps = rps / config['desired_replicas']
            
            # [FIX 1] Calculate Cumulative Latency (Local + Downstream Wait)
            chain_latency = self._estimate_dependency_latency(node_id, phi)
            total_thread_occupancy_ms = effective_processing_ms + chain_latency
            
            # Little's Law: Threads = RPS * Total_Time_Thread_Is_Blocked
            concurrency_per_pod = math.ceil(pod_rps * (total_thread_occupancy_ms / 1000.0))
            
            # Pool Headroom
            pool_headroom = 1.0 + (1.5 * (1.0 - phi))
            
            # Ensure minimum floor of 10 threads
            config['thread_pool_size'] = max(10, int(concurrency_per_pod * pool_headroom))
            config['db_connection_pool_capacity'] = max(5, int(config['thread_pool_size'] * 0.8))
            
            # --- [FIX 2] Strict Timeout Tuning ---
            # Calculate Total Expected Latency (P99 chain + local)
            total_expected_ms = effective_processing_ms + chain_latency
            
            # STRICT Margin: Max 1.5x (Robust) down to 1.05x (Critical)
            # We do NOT multiply by 3.0 or 4.0 anymore to avoid compounding.
            timeout_margin = 1.05 + (0.45 * (1.0 - phi))
            
            timeout_sec = (total_expected_ms * timeout_margin) / 1000.0
            
            config['timeouts'] = {
                'database_call_seconds': max(0.2, timeout_sec),
                'service_call_seconds': max(0.2, timeout_sec),
                'external_api_seconds': max(1.0, timeout_sec * 2)
            }
            
        elif role == 'database':
            # ... (Database logic remains same as previous correct version)
            system_concurrency = rps * (base_processing_ms / 1000.0)
            config['connection_pool_capacity'] = max(50, int(system_concurrency * headroom * 2))
            
            queries_per_core = 1000.0 / res_prof.cpu_ms_per_request
            needed_cores = math.ceil((rps / queries_per_core) * headroom)
            config['cpu_cores'] = max(2, int(needed_cores))

        return config
```

### 3\. File: `generate_dataset.py`

**Fix:** Explicitly inject the massive `workload_generator` config into the simulation configuration dictionary to guarantee it overrides any defaults.

```python
    # ... inside generate_episode ...

    # 6. Configure Simulation
    sim_config = {
        'simulation': {
            'duration': cfg.duration,
            'output_dir': episode_dir,
            'warmup_period': 60.0
        },
        'telemetry': {
            'metric_export_interval': cfg.export_interval,
            'exporter_type': 'file'
        },
        'workload': {
            'path': workload_path
        },
        'infrastructure': {
            'path': 'generated_internal'
        },
        # [FIX 3] Explicitly set massive workload capacity
        'workload_generator': {
            'connection_pool_size': 5000,
            'request_timeout_seconds': 60.0,
            'max_queue_size': 10000,
            'circuit_breaker': {
                'enabled': True,
                'failure_threshold': 0.9,
                'success_threshold': 0.8,
                'window_size': 100
            }
        }
    }
```