This is a comprehensive refactoring plan to achieve realistic fault propagation and dataset quality. We are moving from a "loose" simulation (where faults are absorbed by excess capacity) to a "tight" simulation (where faults immediately cause contention).

Here are the **6 specific file changes** required to fix the physics, enable recovery phases, and ensure propagation.

### 1\. Fix the Math: Correct Capacity Estimation

**File:** `src/validation/component_profiles.py`

We must replace the single-threaded capacity assumption with Little's Law ($Throughput = \frac{Concurrency}{Latency}$) to accurately target the system's breaking point.

```python
# src/validation/component_profiles.py

def estimate_component_capacity(
    component_role: str,
    num_replicas: int = 1,
    thread_pool_size: int = None,  # <--- New Argument
    db_connection_pool_size: int = None,
    service_pipeline: list = None,
    cache_hit_rate: float = 0.7
) -> Dict[str, float]:
    
    # ... [Keep existing imports and setup] ...
    
    latency_profile, resource_profile = get_component_profile(component_role)
    
    # --- FIX START ---
    # OLD: processing_limited_rps = (1.0 / processing_time_sec) * num_replicas
    
    # NEW: Application of Little's Law (Throughput = Concurrency / Latency)
    processing_time_sec = latency_profile.p50 / 1000.0
    
    # 1. Thread Pool Limit (Logical Concurrency)
    # If thread_pool_size is not provided, assume infinite (or resource profile default)
    effective_threads = thread_pool_size if thread_pool_size else resource_profile.max_concurrent
    total_system_threads = effective_threads * num_replicas
    
    if processing_time_sec > 0:
        thread_limited_rps = total_system_threads / processing_time_sec
    else:
        thread_limited_rps = float('inf')

    # 2. CPU Limit (Physical Concurrency)
    # How many requests can we process given CPU time per request?
    # Max RPS = (Total Cores) / (CPU seconds per request)
    # Assume 4 cores per node (standard in your topology gen)
    cpu_cores_per_node = 4.0 
    cpu_time_per_req_sec = resource_profile.cpu_ms_per_request / 1000.0
    
    if cpu_time_per_req_sec > 0:
        cpu_limited_rps = (cpu_cores_per_node * num_replicas) / cpu_time_per_req_sec
    else:
        cpu_limited_rps = float('inf')
        
    # Processing limit is the tighter of Threads vs CPU
    processing_limited_rps = min(thread_limited_rps, cpu_limited_rps)
    # --- FIX END ---

    # ... [Rest of function remains the same regarding DB pool calculations] ...
```

### 2\. Tighten Constraints: Create Resource Scarcity

**File:** `src/core/simulation_config.py`

We need to lower the "safety margins" so that latency spikes actually fill queues.

```python
# src/core/simulation_config.py

@dataclass
class ComputeConfig:
    """Compute component configuration."""
    # ...
    
    # FIX: Reduced from 100 to 15. 
    # With 15 threads, a 200ms latency spike @ 50 RPS fills the pool instantly.
    thread_pool_size: int = 15  
    
    # FIX: Reduced from 20 to 10.
    # Forces connection queuing during DB slowdowns.
    db_connection_pool_capacity: int = 10 

    # ... [Rest of config]
```

### 3\. Fix Dynamics: Memory Pressure & CPU Coupling

**File:** `src/dynamics/metrics_dynamics_engine.py`

Add the missing link where high memory usage degrades CPU performance (thrashing/paging) *before* the OOM kill happens.

```python
# src/dynamics/metrics_dynamics_engine.py

    def _compute_cpu_derivative(self) -> float:
        # ... [Existing calculation of target_cpu_from_load] ...

        # ... [Existing queue contention logic] ...

        # --- FIX START: Add Memory Pressure Overhead ---
        # If memory > 80%, add exponential CPU penalty (Thrashing)
        memory_usage_ratio = self.memory_percent / self.config.memory_max
        memory_pressure_cpu = 0.0
        if memory_usage_ratio > 0.8:
            # at 80% -> 0% CPU penalty
            # at 95% -> ~33% CPU penalty
            # at 100% -> ~100% CPU penalty
            memory_pressure_cpu = 100.0 * ((memory_usage_ratio - 0.8) / 0.2) ** 2
        # --- FIX END ---

        # Combine all CPU sources
        target_cpu = target_cpu_from_load + queue_contention_cpu + contention_cpu + memory_pressure_cpu
        
        # ... [Rest of method] ...
```

### 4\. Aggressive Propagation: Ensure Faults Travel

**File:** `src/resilience/propagation_config.py`

We want the GNN to learn causal chains, so we need distinct signals downstream.

```python
# src/resilience/propagation_config.py

# STANDARD: Balanced propagation 
# FIX: Increased probability to 0.9 (90% of dependency failures cause caller failure)
# FIX: thread_pool_exhaustion_error_rate to 1.0 (If pool is full, we MUST reject/error)
STANDARD_PROPAGATION = PropagationConfig(
    error_propagation_probability=0.9, 
    timeout_causes_error=True,
    thread_pool_exhaustion_error_rate=1.0,
    # ...
)
```

### 5\. Implement Revert Logic

**File:** `src/failures/training_injector.py`

Add the capability to reverse gradual failures for the recovery phase.

```python
# src/failures/training_injector.py

    # Add this new method
    def revert_gradual_failure(
        self,
        target_id: str,
        failure_mode: str,
        params: Dict[str, Any],
        duration: float = 10.0
    ):
        """
        Reverts a gradual failure by applying the inverse infrastructure change.
        """
        if target_id not in self.component_registry:
            return

        target = self.component_registry[target_id]
        
        # Log the revert event
        print(f"[{self.env.now:.2f}s] <<< REVERTING GRADUAL FAILURE: '{failure_mode}' on {target_id}")
        
        # Logic inverses matching _apply_gradual_failure
        if failure_mode == 'inject_latency':
            # Apply negative delta to remove latency
            target.apply_infrastructure_change(
                parameter='latency_ms',
                delta=-params.get('latency_ms', 1000), # Negative delta
                duration=duration,
                progression='linear',
                start_time=self.env.now
            )
        elif failure_mode == 'cpu_saturation':
            # Remove the floor constraint
            if hasattr(target, 'dynamics'):
                target.dynamics.fault_cpu_floor_percent = None
        
        # ... [Add other modes logic] ...
```

The revert_gradual_failure function (Fix 5) needs complete logic for every fault type. If a revert is missing, the fault will become permanent.Missing Revert Logic (Example)Required Implementation in revert_gradual_failureinject_errorsRevert: target.apply_infrastructure_change(parameter='error_rate', delta=-params.get('error_rate', 0.5), duration=duration, progression='linear', start_time=self.env.now)memory_leakNeed to call the corresponding stop_memory_leak function in src/failures/modes.py with inverse parameters.slow_queriesNeeds to set target.dynamics.fault_latency_floor_ms = None after the delay.cache_failureNeeds custom symmetric logic to ramp forced_error_rate, injected_latency_ms, and simulated_hit_rate back to baseline over duration.The orchestrating logic in generate_dataset.py (Fix 6) will rely on these revert functions to implement the B $\rightarrow$ A phase.

### 6\. Orchestrate A-B-A Timeline

**File:** `generate_dataset.py`

Update the generation logic to include Healthy -\> Fault -\> Recovery phases.

```python
# generate_dataset.py

    # ... [Inside generate_episode function] ...

    # 1. Define Timeline
    # Example: Duration 600s
    # Warmup: 0-100s
    # Fault Ramp: 100-160s (60s ramp)
    # Fault Sustain: 160-400s (240s sustain)
    # Recovery: 400-460s (60s recovery)
    # Post-Recovery: 460-600s
    
    fault_start_time = int(cfg.duration * 0.20)
    fault_ramp_duration = int(cfg.duration * 0.10) # Fast ramp
    
    # We want the fault to be active for ~40% of the episode
    fault_sustain_duration = int(cfg.duration * 0.40) 
    
    recovery_start_time = fault_start_time + fault_ramp_duration + fault_sustain_duration
    
    # ... [Injector Setup] ...

    # 2. Schedule Fault Injection (Phase A -> B)
    injector.inject_gradual_failure(
        target_id=target_id,
        failure_mode=cfg.fault_type,
        start_time=fault_start_time,
        duration=fault_ramp_duration,
        params=params,
        progression=cfg.progression,
        episode_id=f'ep{episode_id}_fault'
    )
    
    # 3. Schedule Fault Revert (Phase B -> A)
    # Note: You need to pass the same params so it subtracts the exact amount added
    if hasattr(injector, 'revert_gradual_failure'):
        # Use a process delay to schedule the revert
        def schedule_revert():
            yield sim.env.timeout(recovery_start_time)
            injector.revert_gradual_failure(
                target_id=target_id,
                failure_mode=cfg.fault_type,
                params=params,
                duration=fault_ramp_duration # Symmetrical recovery
            )
        sim.env.process(schedule_revert())

    # 4. Update Ground Truth Label
    label = {
        # ... existing fields ...
        'timeline': {
            'healthy_start': 0,
            'fault_injection_start': fault_start_time,
            'fault_full_effect': fault_start_time + fault_ramp_duration,
            'recovery_start': recovery_start_time,
            'recovery_complete': recovery_start_time + fault_ramp_duration,
            'episode_end': cfg.duration
        }
    }
```

### Final Validation Step

Before generating the full dataset, run `test_propagation.sh`. You should see:

1.  **Latency Spikes** on the root cause node.
2.  **Queue Depth** increases on the root cause node (due to `thread_pool_size=15`).
3.  **Client Errors / Latency** on upstream services (callers) because their requests to the root cause are timing out or being rejected.

If you see the upstream nodes showing errors or high latency that correlates with the root cause, **you have achieved realistic propagation.**

