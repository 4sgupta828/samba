"""
Defines the implementation of specific failure modes that can be applied to components.
Each function takes a component and parameters, and modifies the component's state.

Note: For gradual failures, use the TrainingFailureInjector's apply_infrastructure_change
mechanism. These functions are for instant state changes.
"""
from typing import Dict, Any

from src.components.base_component import SimulatedComponent
from src.components.compute import ComputeAgent
from src.components.pod import Pod
from src.components.service import Service
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache
from src.components.messaging import MessageQueue
from src.components.network import NetworkLink

def set_component_state(component: SimulatedComponent, params: Dict[str, Any]):
    """Forces a component into a specific operational state."""
    target_state = params.get("state", "DOWN")
    if hasattr(component.state, 'operational'):
        component.state.operational = target_state
        component._emit_log("FATAL", f"Forced state transition to {target_state} by failure injector.")
        # If the component is running a process that waits on an event, interrupt it.
        # Note: SimPy's succeed() doesn't accept 'cause' parameter, so we just trigger it
        if not component.interrupt_event.triggered:
            component.interrupt_event.succeed()
    else:
        component._emit_log("WARN", f"Cannot force state on component without 'operational' state attribute.")

def inject_latency(component: SimulatedComponent, params: Dict[str, Any]):
    """
    ADDITIVE FAULT: Adds fixed latency on top of natural latency.
    Models network delays, external API slowness.
    """
    latency_ms = params.get("latency_ms", 500)

    # For components with dynamics engine, set dynamics fault
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_latency_additive_ms = latency_ms
        component._emit_log("WARN", f"Latency injection (dynamics): +{latency_ms}ms")

    # ALSO set direct attribute for components that use it directly (like ExternalService)
    if hasattr(component, 'injected_latency_ms'):
        component.injected_latency_ms = latency_ms
        component._emit_log("WARN", f"Latency injection (direct): +{latency_ms}ms")

    if not (hasattr(component, 'dynamics') and component.dynamics is not None) and not hasattr(component, 'injected_latency_ms'):
        component._emit_log("ERROR", "Component does not support latency injection (no dynamics or injected_latency_ms attribute)")

def revert_latency(component: SimulatedComponent, params: Dict[str, Any]):
    """Removes injected latency."""
    reverted = False

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_latency_additive_ms = 0.0
        component._emit_log("INFO", "Latency injection reverted (dynamics)")
        reverted = True

    if hasattr(component, 'injected_latency_ms'):
        component.injected_latency_ms = 0.0
        component._emit_log("INFO", "Latency injection reverted (direct)")
        reverted = True

    if not reverted:
        component._emit_log("WARN", "Component does not support latency injection")
    
def start_memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """Starts or accelerates a memory leak in a ComputeAgent/Pod via dynamics engine."""
    if not isinstance(component, (ComputeAgent, Pod)):
        component._emit_log("WARN", "start_memory_leak can only be applied to ComputeAgent/Pod components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject memory leak")
        return

    leak_rate = params.get("leak_mb_per_request", 0.5)
    # Increase memory per request in dynamics engine
    component.dynamics.config.memory_per_request_mb += leak_rate
    component._emit_log("WARN", f"Starting memory leak: +{leak_rate} MB/request (dynamics: memory_per_request_mb={component.dynamics.config.memory_per_request_mb:.2f})")

def stop_memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """Stops an injected memory leak via dynamics engine."""
    if not isinstance(component, (ComputeAgent, Pod)):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        leak_rate = params.get("leak_mb_per_request", 0.5)
        # Reduce memory per request back to normal (careful not to go negative)
        component.dynamics.config.memory_per_request_mb = max(0.1, component.dynamics.config.memory_per_request_mb - leak_rate)
        component._emit_log("INFO", f"Stopping memory leak (dynamics: memory_per_request_mb={component.dynamics.config.memory_per_request_mb:.2f})")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

# Deprecated database-specific faults removed (2025-12-10)
# - start_db_background_job → Use cpu_saturation instead
# - stop_db_background_job → Removed (use revert_cpu_saturation)
# - inject_db_wear → Use disk_io_saturation instead
# - reset_db_wear → Removed (use revert_disk_io_saturation)


def cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """
    CPU SATURATION FAULT: Increases CPU cost per request via cpu_multiplier.

    Uses first-principles approach: increases computational work needed per request.
    The dynamics engine naturally translates this to higher CPU utilization and latency.

    Severity parameter (0.0-1.0):
    - 0.0-0.3: Subtle (1.5-2.5x CPU)
    - 0.3-0.7: Moderate (2.5-4.0x CPU) [default: 0.5]
    - 0.7-1.0: Severe (4.0-5.0x CPU)

    The fault tuner calculates cpu_multiplier based on:
    - Current baseline utilization
    - Available headroom
    - Severity (non-linear scaling)
    - Capacity (threads, replicas)

    Capacity-relative: No hardcoded targets, scales based on actual system capacity.
    """
    if not isinstance(component, (ComputeAgent, Pod)):
        component._emit_log("WARN", "cpu_saturation can only be applied to ComputeAgent/Pod components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject CPU saturation")
        return

    # Get cpu_multiplier from fault tuner (capacity-relative, severity-scaled)
    # Fallback to legacy cpu_percent if cpu_multiplier not provided
    if 'cpu_multiplier' in params:
        cpu_multiplier = params['cpu_multiplier']

        # Apply CPU multiplier (first principles: more work per request)
        if not hasattr(component, 'baseline_cpu_multiplier'):
            component.baseline_cpu_multiplier = 1.0

        # Increase CPU cost per request in dynamics engine
        # This is handled by infrastructure change mechanism for gradual faults
        # For instant faults, we need to set the multiplier directly
        component.cpu_cost_multiplier = cpu_multiplier

        # Calculate target CPU for floor (visible indicator)
        # Use current CPU + (available headroom * severity scale)
        current_cpu = component.dynamics.cpu_percent
        available_headroom = 95.0 - current_cpu
        severity = params.get('severity', 0.5)

        # Non-linear severity scaling (matches fault tuner)
        if severity < 0.3:
            scale = (severity / 0.3) * 0.6
        elif severity < 0.7:
            scale = 0.6 + ((severity - 0.3) / 0.4) * 0.4
        else:
            scale = 1.0 + (((severity - 0.7) / 0.3) ** 1.5) * 0.3

        target_cpu = min(95.0, current_cpu + (available_headroom * scale * 0.75))
        component.dynamics.fault_cpu_floor_percent = target_cpu

        # Add scheduler contention latency (scales with severity)
        base_contention_ms = 50.0  # Base: 50ms
        contention_ms = base_contention_ms * (1.0 + severity * 3.0)  # Up to 200ms at severity=1.0
        component.dynamics.fault_latency_additive_ms = contention_ms

        component._emit_log("WARN",
            f"CPU saturation: {cpu_multiplier:.2f}x CPU cost, "
            f"target={target_cpu:.1f}%, contention={contention_ms:.0f}ms (severity={severity:.2f})")

    else:
        # Legacy mode: use cpu_percent directly (for backward compatibility)
        cpu_target = params.get("cpu_percent", 95)
        component.dynamics.fault_cpu_floor_percent = cpu_target
        component.dynamics.fault_latency_additive_ms = 200.0
        component._emit_log("WARN", f"CPU saturation (legacy): {cpu_target}% floor + 200ms contention lag")

def revert_cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """Revert CPU saturation by removing CPU floor and resetting multiplier."""
    if not isinstance(component, (ComputeAgent, Pod)):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        # Remove CPU floor
        component.dynamics.fault_cpu_floor_percent = None
        # Remove contention latency
        component.dynamics.fault_latency_additive_ms = 0.0
        # Reset CPU cost multiplier to baseline
        if hasattr(component, 'cpu_cost_multiplier'):
            component.cpu_cost_multiplier = getattr(component, 'baseline_cpu_multiplier', 1.0)
        component._emit_log("INFO", "CPU saturation reverted")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

def memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """
    Alias for start_memory_leak for consistency with scenario naming.
    """
    start_memory_leak(component, params)

def memory_pressure(component: ComputeAgent, params: Dict[str, Any]):
    """
    MEMORY PRESSURE FAULT: Increases baseline memory usage.

    Models sustained high memory usage (not a leak, just elevated baseline).
    Creates generic memory pressure effects that apply to ALL languages:
    - Allocation overhead increases (malloc/new slows down)
    - Page faults increase (OS swapping at high utilization)
    - CPU overhead increases (memory management)
    - OOM risk increases

    Severity parameter (0.0-1.0):
    - 0.0-0.3: Subtle (memory to 70-80%)
    - 0.3-0.7: Moderate (memory to 80-90%) [default: 0.5]
    - 0.7-1.0: Severe (memory to 90-95%, risk of OOM)

    Capacity-relative: Calculates increase based on available memory headroom.
    No GC assumptions: Works for Python, Go, Rust, Java, C++ alike.
    """
    if not isinstance(component, ComputeAgent):
        component._emit_log("WARN", "memory_pressure can only be applied to ComputeAgent components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject memory pressure")
        return

    # Capacity-relative calculation
    severity = params.get('severity', 0.5)

    # Get current memory state
    current_memory_mb = component.dynamics.memory_percent  # Actually in MB despite name
    memory_capacity_mb = component.dynamics.config.memory_max  # Max capacity

    # Calculate available headroom
    available_headroom_mb = memory_capacity_mb - current_memory_mb

    # Non-linear severity scaling (matches fault tuner)
    if severity < 0.3:
        scale = (severity / 0.3) * 0.6  # 0-60% of headroom
    elif severity < 0.7:
        scale = 0.6 + ((severity - 0.3) / 0.4) * 0.4  # 60-100% of headroom
    else:
        scale = 1.0 + (((severity - 0.7) / 0.3) ** 1.5) * 0.3  # 100-130% of headroom

    # Calculate memory increase (use 70% of available headroom by default, scaled by severity)
    base_consumption = 0.70  # Consume 70% of available headroom
    memory_increase_mb = available_headroom_mb * base_consumption * scale

    # Fallback to provided parameter if severity not calculated properly
    if 'memory_increase_mb' in params:
        memory_increase_mb = params['memory_increase_mb']

    # Bounds check
    memory_increase_mb = max(50.0, min(available_headroom_mb * 0.9, memory_increase_mb))

    # Store original for revert
    if not hasattr(component, '_memory_pressure_original_base'):
        component._memory_pressure_original_base = component.dynamics.config.memory_base

    # Increase baseline memory in dynamics engine
    component.dynamics.config.memory_base += memory_increase_mb

    # Calculate resulting memory utilization percentage
    new_memory_mb = component.dynamics.memory_percent + memory_increase_mb
    memory_util_pct = (new_memory_mb / memory_capacity_mb) * 100.0

    component._emit_log("WARN",
        f"Memory pressure injected: +{memory_increase_mb:.0f}MB "
        f"(utilization: {memory_util_pct:.1f}%, severity={severity:.2f})")

def revert_memory_pressure(component: ComputeAgent, params: Dict[str, Any]):
    """Revert memory pressure by restoring original baseline."""
    if not isinstance(component, ComputeAgent):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        # Restore original baseline if stored
        if hasattr(component, '_memory_pressure_original_base'):
            original_base = component._memory_pressure_original_base
            component.dynamics.config.memory_base = original_base
            delattr(component, '_memory_pressure_original_base')
            component._emit_log("INFO", f"Memory pressure reverted (restored baseline: {original_base:.1f}MB)")
        else:
            # Fallback to parameter-based revert
            memory_increase_mb = params.get("memory_increase_mb", 300)
            component.dynamics.config.memory_base = max(10.0, component.dynamics.config.memory_base - memory_increase_mb)
            component._emit_log("INFO", f"Memory pressure reverted (dynamics: memory_base={component.dynamics.config.memory_base:.1f}MB)")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

def memory_thrashing(component: ComputeAgent, params: Dict[str, Any]):
    """
    MEMORY THRASHING FAULT: Periodic allocation bursts causing intermittent spikes.

    Different from memory_pressure:
    - memory_pressure: Sustained high memory usage (steady state)
    - memory_thrashing: Periodic spikes with rapid allocation/deallocation (dynamic)

    Unique observable signature:
    - Bimodal latency distribution (fast requests → pause → fast again)
    - Intermittent CPU spikes (from allocation overhead)
    - Memory usage oscillates rather than staying constant
    - Unpredictable performance (not consistent slowdown)

    Severity parameter (0.0-1.0):
    - 0.0-0.3: Subtle (small burst size, infrequent)
    - 0.3-0.7: Moderate (medium bursts, periodic) [default: 0.5]
    - 0.7-1.0: Severe (large bursts, frequent, high risk of OOM)

    Implementation: Spawns a background process that periodically allocates/deallocates
    memory, simulating GC pressure, memory fragmentation, or object churn.

    Capacity-relative: Burst size scales with available memory.
    Generic: Works for any language (models OS-level memory management overhead).
    """
    if not isinstance(component, (ComputeAgent, Pod)):
        component._emit_log("WARN", "memory_thrashing can only be applied to ComputeAgent/Pod components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject memory thrashing")
        return

    severity = params.get('severity', 0.5)

    # Calculate thrashing parameters based on severity
    # Burst size: How much memory to allocate per burst
    memory_capacity_mb = component.dynamics.config.memory_max
    base_burst_mb = memory_capacity_mb * 0.1  # 10% of capacity

    # Scale by severity (non-linear)
    if severity < 0.3:
        scale = (severity / 0.3) * 0.6
    elif severity < 0.7:
        scale = 0.6 + ((severity - 0.3) / 0.4) * 0.4
    else:
        scale = 1.0 + (((severity - 0.7) / 0.3) ** 1.5) * 0.3

    burst_size_mb = base_burst_mb * scale

    # Burst frequency: How often to thrash (seconds between bursts)
    # Higher severity = more frequent thrashing
    base_period_sec = 10.0  # Base: every 10 seconds
    burst_period_sec = base_period_sec * (1.5 - severity)  # At severity=1.0: every 5 seconds

    # Burst duration: How long each allocation burst lasts
    base_duration_sec = 2.0  # Base: 2 second burst
    burst_duration_sec = base_duration_sec * (0.5 + severity)  # At severity=1.0: 3 seconds

    # Store parameters for background process
    component._memory_thrashing_enabled = True
    component._memory_thrashing_burst_mb = burst_size_mb
    component._memory_thrashing_period_sec = burst_period_sec
    component._memory_thrashing_duration_sec = burst_duration_sec

    # Spawn background thrashing process
    def memory_thrashing_process():
        """Background process that periodically allocates/deallocates memory."""
        while component._memory_thrashing_enabled:
            # Allocation burst
            old_base = component.dynamics.config.memory_base
            component.dynamics.config.memory_base += burst_size_mb
            component._emit_log("DEBUG",
                f"Memory thrashing: BURST +{burst_size_mb:.0f}MB (total={component.dynamics.config.memory_base:.0f}MB)")

            # Hold for burst duration (causes latency spike during this window)
            yield component.env.timeout(burst_duration_sec)

            # Deallocation (memory freed)
            component.dynamics.config.memory_base = old_base
            component._emit_log("DEBUG",
                f"Memory thrashing: RELEASE -{burst_size_mb:.0f}MB (total={component.dynamics.config.memory_base:.0f}MB)")

            # Wait until next burst
            yield component.env.timeout(burst_period_sec - burst_duration_sec)

    component._memory_thrashing_process = component.env.process(memory_thrashing_process())

    component._emit_log("WARN",
        f"Memory thrashing: {burst_size_mb:.0f}MB bursts every {burst_period_sec:.1f}s "
        f"(duration={burst_duration_sec:.1f}s, severity={severity:.2f})")

def revert_memory_thrashing(component: ComputeAgent, params: Dict[str, Any]):
    """Revert memory thrashing by stopping the background process."""
    if not isinstance(component, (ComputeAgent, Pod)):
        return

    if hasattr(component, '_memory_thrashing_enabled'):
        component._memory_thrashing_enabled = False

        # Interrupt the background process if still running
        if hasattr(component, '_memory_thrashing_process'):
            if component._memory_thrashing_process.is_alive:
                try:
                    component._memory_thrashing_process.interrupt("Memory thrashing reverted")
                except RuntimeError:
                    pass
            delattr(component, '_memory_thrashing_process')

        # Clean up attributes
        for attr in ['_memory_thrashing_burst_mb', '_memory_thrashing_period_sec', '_memory_thrashing_duration_sec']:
            if hasattr(component, attr):
                delattr(component, attr)

        component._emit_log("INFO", "Memory thrashing reverted")
    else:
        component._emit_log("WARN", "No memory thrashing active to revert")

def disk_io_saturation(component: SimulatedComponent, params: Dict[str, Any]):
    """
    DISK I/O SATURATION FAULT: High latency with LOW CPU (unique signature).

    Models I/O bottlenecks: disk saturation, network storage delays, database query slowness.

    Unique observable signature:
    - HIGH latency (requests waiting on I/O)
    - LOW CPU (threads blocked, not computing)
    - Throughput decreases (I/O bandwidth limit)
    - Queue depth increases (requests waiting for I/O)

    Different from cpu_saturation:
    - cpu_saturation: High CPU, all requests slow
    - disk_io_saturation: Low CPU, high wait time

    Severity parameter (0.0-1.0):
    - 0.0-0.3: Subtle (50-200ms I/O wait)
    - 0.3-0.7: Moderate (200-500ms I/O wait) [default: 0.5]
    - 0.7-1.0: Severe (500-2000ms I/O wait)

    Capacity-relative: I/O wait time scales with severity.
    Generic: Models any I/O bottleneck (disk, network, database).
    """
    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject disk I/O saturation")
        return

    severity = params.get('severity', 0.5)

    # Calculate I/O wait latency based on severity
    # Base latency: 100ms
    # Scale by severity with non-linear curve
    base_io_wait_ms = 100.0

    if severity < 0.3:
        scale = (severity / 0.3) * 0.6  # 0-60% of base
        io_wait_ms = base_io_wait_ms * scale * 2.0  # Up to 120ms
    elif severity < 0.7:
        scale = 0.6 + ((severity - 0.3) / 0.4) * 0.4  # 60-100% of base
        io_wait_ms = base_io_wait_ms * (1.0 + scale * 4.0)  # 120-500ms
    else:
        scale = 1.0 + (((severity - 0.7) / 0.3) ** 1.5) * 0.3  # 100-130% of base
        io_wait_ms = base_io_wait_ms * (5.0 + scale * 15.0)  # 500-2000ms

    # Fallback to provided parameter if available
    if 'io_wait_ms' in params:
        io_wait_ms = params['io_wait_ms']

    # Set FLOOR on latency (I/O wait is minimum latency)
    component.dynamics.fault_latency_floor_ms = io_wait_ms

    # Key characteristic: LOW CPU during I/O wait
    # Threads are blocked on I/O, not consuming CPU
    # Model this by NOT adding CPU load (unlike cpu_saturation)

    component._emit_log("WARN",
        f"Disk I/O saturation: {io_wait_ms:.0f}ms I/O wait (LOW CPU, severity={severity:.2f})")

def revert_disk_io_saturation(component: SimulatedComponent, params: Dict[str, Any]):
    """Revert disk I/O saturation by removing latency floor."""
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_latency_floor_ms = None
        component._emit_log("INFO", "Disk I/O saturation reverted")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

def thread_exhaustion(component, params: Dict[str, Any]):
    """
    THREAD EXHAUSTION FAULT: Thread pool saturation causing queue buildup.

    Models thread pool exhaustion from any cause:
    - Deadlocks (threads waiting on locks)
    - Blocking I/O (threads waiting on slow operations)
    - Slow downstream services (threads held during calls)
    - Resource contention (threads waiting for resources)

    Unique observable signature:
    - Queue depth grows rapidly
    - Latency increases over time (FIFO degradation)
    - Eventually: connection rejections when queue fills
    - CPU may stay LOW if threads are blocked (not cpu_saturation)

    Severity parameter (0.0-1.0):
    - 0.0-0.3: Subtle (40-60% threads blocked)
    - 0.3-0.7: Moderate (60-80% threads blocked) [default: 0.5 → 70%]
    - 0.7-1.0: Severe (80-90% threads blocked)

    Capacity-relative: Thread count scales with pool size.
    Generic: Models any thread blocking scenario.

    Note: This is the preferred name. 'force_deadlock' is an alias for backward compatibility.
    """
    # Forward to force_deadlock implementation (they're the same)
    return force_deadlock(component, params)

def revert_thread_exhaustion(component, params: Dict[str, Any]):
    """Revert thread exhaustion by releasing blocked threads."""
    return revert_force_deadlock(component, params)

def inject_errors(component: SimulatedComponent, params: Dict[str, Any]):
    """
    ADDITIVE FAULT: Adds base error rate on top of natural errors.
    Models external failures, flaky networks.
    """
    error_rate = params.get("error_rate", 0.1)  # 10%

    # For components with dynamics engine, set dynamics fault
    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_error_additive = error_rate
        component._emit_log("WARN", f"Error injection (dynamics): +{error_rate*100:.1f}% base error rate")

    # ALSO set direct attribute for components that use it directly (like ExternalService)
    if hasattr(component, 'forced_error_rate'):
        component.forced_error_rate = error_rate
        component._emit_log("WARN", f"Error injection (direct): +{error_rate*100:.1f}% base error rate")

    if not (hasattr(component, 'dynamics') and component.dynamics is not None) and not hasattr(component, 'forced_error_rate'):
        component._emit_log("ERROR", "Component does not support error injection (no dynamics or forced_error_rate attribute)")

def revert_errors(component: SimulatedComponent, params: Dict[str, Any]):
    """Revert error rate injection."""
    reverted = False

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_error_additive = 0.0
        component._emit_log("INFO", "Error injection reverted (dynamics)")
        reverted = True

    if hasattr(component, 'forced_error_rate'):
        component.forced_error_rate = 0.0
        component._emit_log("INFO", "Error injection reverted (direct)")
        reverted = True

    if not reverted:
        component._emit_log("WARN", "Component does not support error injection")

def cache_failure(component, params: Dict[str, Any]):
    """
    Simulates cache failure by gradually increasing error rate and latency.
    This causes cache misses which will increase database load (thundering herd).

    NOTE: This fault is designed for ExternalCache (Redis, Memcached).
    For InMemoryCache within pods, this just clears the cache.

    Configuration is loaded from config/simulation_config.yaml under fault_injection.cache_failure.
    Gradual mode: Ramps from baseline to max error rate and latency
    Hit rate degrades from baseline to minimum (simulates gradual cache poisoning/eviction)
    """
    from src.components.storage import InMemoryCache, ExternalCache
    from src.core.simulation_config import get_simulation_config

    if isinstance(component, ExternalCache):
        # Get progress for gradual ramp-up (0.0 to 1.0)
        progress = params.get("progress", 1.0)  # Default to full fault if not gradual

        # Load configuration from simulation_config.yaml
        config = get_simulation_config()
        fault_config = config.fault_injection.cache_failure
        base_config = config.storage.external_cache

        # Get fault-specific parameters from fault config
        max_error_rate = params.get("max_error_rate", fault_config.max_error_rate)
        max_latency_ms = params.get("max_latency_ms", fault_config.max_latency_ms)
        min_hit_rate = params.get("min_hit_rate", fault_config.min_hit_rate)

        # Get baseline parameters from base component config (avoid duplication)
        baseline_latency_ms = params.get("baseline_latency_ms", base_config.base_latency_mean_ms)
        baseline_hit_rate = params.get("baseline_hit_rate", base_config.baseline_hit_rate)

        # Linear ramp with progress
        current_error_rate = max_error_rate * progress
        current_latency_ms = baseline_latency_ms + (max_latency_ms - baseline_latency_ms) * progress
        current_hit_rate = baseline_hit_rate - (baseline_hit_rate - min_hit_rate) * progress

        component.injected_latency_ms = current_latency_ms
        component.forced_error_rate = current_error_rate
        component.simulated_hit_rate = current_hit_rate

        # State transitions based on progress
        if progress < 0.3:
            component.state.operational = "RUNNING"
        elif progress < 0.7:
            component.state.operational = "DEGRADED"
        else:
            component.state.operational = "CRITICAL"

        component._emit_log("WARN",
            f"Cache degradation: {current_error_rate*100:.1f}% errors, "
            f"{current_latency_ms:.1f}ms latency, {current_hit_rate*100:.1f}% hit rate "
            f"(progress: {progress*100:.0f}%)")

    elif isinstance(component, InMemoryCache):
        # In-memory cache - just clear it
        component.cache.clear()
        component.state.operational = "DEGRADED"
        component._emit_log("WARN", "InMemoryCache cleared - all items evicted")

    else:
        component._emit_log("WARN", "cache_failure can only be applied to cache components")

def revert_cache_failure(component, params: Dict[str, Any]):
    """Revert cache failure."""
    from src.components.storage import InMemoryCache, ExternalCache
    from src.core.simulation_config import get_simulation_config

    if isinstance(component, ExternalCache):
        component.injected_latency_ms = 0
        component.forced_error_rate = 0.0
        component.state.operational = "RUNNING"

        # Restore baseline hit rate from config
        config = get_simulation_config().storage.external_cache
        component.simulated_hit_rate = config.baseline_hit_rate

        component._emit_log("INFO", "External cache failure reverted")

    elif isinstance(component, InMemoryCache):
        component.state.operational = "RUNNING"
        component._emit_log("INFO", "InMemoryCache reverted to operational")

    else:
        pass  # Not a cache component

def queue_consumer_slowdown(component: MessageQueue, params: Dict[str, Any]):
    """
    Simulates message queue consumer slowdown by adding processing latency to consumers.
    This causes messages to accumulate in-flight and visible queues.

    Note: The fault is applied to the queue, but it affects the CONSUMERS by adding
    a marker that consumers will check and apply latency during message processing.
    """
    if not isinstance(component, MessageQueue):
        component._emit_log("WARN", "queue_consumer_slowdown can only be applied to MessageQueue components.")
        return

    latency_ms = params.get("latency_ms", 1000)
    # Mark the queue so consumers know to slow down their processing
    component.consumer_processing_latency_ms = latency_ms
    component._emit_log("WARN", f"Queue consumer slowdown injected: +{latency_ms}ms processing latency per message")

def revert_queue_consumer_slowdown(component: MessageQueue, params: Dict[str, Any]):
    """Revert queue consumer slowdown."""
    if not isinstance(component, MessageQueue):
        return

    component.consumer_processing_latency_ms = 0
    component._emit_log("INFO", "Queue consumer slowdown reverted")

# Deprecated redundant faults removed (2025-12-10)
# These faults had identical observable effects to existing faults:
# - slow_queries → Use disk_io_saturation instead (same: HIGH latency from I/O wait)
# - revert_slow_queries → Use revert_disk_io_saturation
# - connection_exhaustion → Use thread_exhaustion instead (same: pool saturation, queue buildup)
# - revert_connection_exhaustion → Use revert_thread_exhaustion
# - enable_background_job → Use cpu_saturation instead (same: CPU contention)
# - disable_background_job → Use revert_cpu_saturation

def noisy_neighbor(component, params: Dict[str, Any]):
    """
    Simulates noisy neighbor by pinning CPU to high percentage on the aggressor pod.
    This causes resource contention on the shared node, affecting other pods
    on the same node through CPU steal time.

    The fault has TWO effects:
    1. Aggressor pod: CPU pinned to target percentage (e.g., 90-100%)
    2. Co-located pods: Experience CPU steal time due to node contention

    Args:
        component: The aggressor Pod or Service (if Service, picks a random pod)
        params: cpu_percent (default: randomized 90-100%), steal_time_multiplier (default: 1.5)
    """
    # If component is a Service, pick a random pod
    if isinstance(component, Service):
        if not component.pods:
            component._emit_log("WARN", "noisy_neighbor: Service has no pods")
            return
        # Pick a random pod as aggressor for diversity
        import random
        target_pod = random.choice(component.pods)
        # Store the affected pod ID on the Service for robust revert
        component._noisy_neighbor_pod_id = target_pod.id
        component._emit_log("INFO", f"noisy_neighbor: Applying to randomly selected pod {target_pod.id} (out of {len(component.pods)} pods)")
    elif isinstance(component, Pod):
        target_pod = component
        # Store pod ID on itself for consistency
        component._noisy_neighbor_pod_id = target_pod.id
    else:
        component._emit_log("WARN", f"noisy_neighbor can only be applied to Pod or Service components (got {type(component).__name__})")
        return

    if not hasattr(target_pod, 'dynamics') or target_pod.dynamics is None:
        target_pod._emit_log("ERROR", "Pod does not have dynamics engine - cannot inject noisy neighbor")
        return

    cpu_target = params.get("cpu_percent", 100.0)
    steal_time_multiplier = params.get("steal_time_multiplier", 1.5)

    # EFFECT 1: Set CPU floor to pin the aggressor pod's CPU
    target_pod.dynamics.fault_cpu_floor_percent = cpu_target
    target_pod._emit_log("WARN", f"Noisy neighbor: CPU pinned to {cpu_target}% (aggressor pod)")

    # EFFECT 2: Apply steal time to co-located pods (if on a compute node)
    if target_pod.compute_node is not None:
        node = target_pod.compute_node
        co_located_pods = [p for p in node.pods if p.id != target_pod.id]

        if co_located_pods:
            component._emit_log("INFO", f"noisy_neighbor: Applying steal time to {len(co_located_pods)} co-located pods on node {node.id}")

            # Store original latency adders for revert
            if not hasattr(component, '_noisy_neighbor_victims'):
                component._noisy_neighbor_victims = {}

            for victim_pod in co_located_pods:
                if hasattr(victim_pod, 'dynamics') and victim_pod.dynamics is not None:
                    # Store original value
                    original_latency = victim_pod.dynamics.fault_latency_additive_ms or 0.0

                    # Calculate steal time based on node contention
                    # Use a modest steal time penalty that won't cause cascading failures
                    # The impact should be noticeable but not catastrophic
                    # Typical services have 100-500ms latency, so 20-30ms penalty is ~5-10% increase
                    base_steal_time_ms = 20.0  # Modest base steal time penalty
                    steal_time_ms = base_steal_time_ms * steal_time_multiplier

                    # Add steal time to victim pods
                    victim_pod.dynamics.fault_latency_additive_ms = original_latency + steal_time_ms

                    component._noisy_neighbor_victims[victim_pod.id] = {
                        'original_latency': original_latency,
                        'added_steal_time': steal_time_ms
                    }

                    victim_pod._emit_log("WARN", f"noisy_neighbor: Experiencing CPU steal time (+{steal_time_ms:.1f}ms latency penalty)")
        else:
            component._emit_log("INFO", f"noisy_neighbor: No co-located pods on node {node.id if node else 'unknown'}")

def revert_noisy_neighbor(component, params: Dict[str, Any]):
    """Revert noisy neighbor by removing CPU floor from aggressor and steal time from victims."""
    # Get the originally affected pod ID
    if not hasattr(component, '_noisy_neighbor_pod_id'):
        component._emit_log("WARN", "No noisy_neighbor pod ID tracked - cannot revert")
        return

    affected_pod_id = component._noisy_neighbor_pod_id

    # Find the aggressor pod by ID
    if isinstance(component, Service):
        # Look up pod in service's current pod list
        target_pod = None
        for pod in component.pods:
            if pod.id == affected_pod_id:
                target_pod = pod
                break

        if target_pod is None:
            component._emit_log("WARN", f"noisy_neighbor: Original pod {affected_pod_id} no longer exists (may have been replaced)")
            # Clean up tracking
            del component._noisy_neighbor_pod_id
            if hasattr(component, '_noisy_neighbor_victims'):
                del component._noisy_neighbor_victims
            return

        component._emit_log("INFO", f"noisy_neighbor: Reverting on aggressor pod {target_pod.id}")
    elif isinstance(component, Pod):
        target_pod = component
    else:
        return

    # REVERT EFFECT 1: Remove CPU floor from aggressor pod
    if hasattr(target_pod, 'dynamics') and target_pod.dynamics is not None:
        target_pod.dynamics.fault_cpu_floor_percent = None
        target_pod._emit_log("INFO", "Noisy neighbor: CPU floor removed (aggressor)")
    else:
        target_pod._emit_log("WARN", "Component does not have dynamics engine")

    # REVERT EFFECT 2: Remove steal time from victim pods
    if hasattr(component, '_noisy_neighbor_victims'):
        victims_info = component._noisy_neighbor_victims

        # Get the compute node to find victim pods
        # First try to get it from the aggressor pod
        compute_node = None
        if hasattr(target_pod, 'compute_node'):
            compute_node = target_pod.compute_node

        if compute_node is not None:
            # Look up victim pods via compute node
            for victim_pod in compute_node.pods:
                if victim_pod.id in victims_info:
                    info = victims_info[victim_pod.id]
                    if hasattr(victim_pod, 'dynamics') and victim_pod.dynamics is not None:
                        # Restore original latency (remove the steal time we added)
                        victim_pod.dynamics.fault_latency_additive_ms = info['original_latency']
                        victim_pod._emit_log("INFO", f"Noisy neighbor: CPU steal time removed (-{info['added_steal_time']:.1f}ms)")
        else:
            component._emit_log("WARN", f"noisy_neighbor: Cannot access compute node to revert victim pods")

        # Clean up victims tracking
        del component._noisy_neighbor_victims

    # Clean up aggressor tracking
    del component._noisy_neighbor_pod_id

def hot_shard(component: Service, params: Dict[str, Any]):
    """
    Simulates hot shard by skewing traffic to a specific pod.

    Args:
        component: The Service to apply traffic skew to
        params:
            - target_pod_index (int or 'random'): Which pod to make hot
            - skew_factor (float, e.g., 0.8 for 80%): How much traffic to send to hot pod
    """
    if not isinstance(component, Service):
        component._emit_log("WARN", "hot_shard can only be applied to Service components.")
        return

    if not component.pods:
        component._emit_log("WARN", "hot_shard: Service has no pods")
        return

    target_pod_index = params.get("target_pod_index", 0)
    skew_factor = params.get("skew_factor", 0.8)

    # Support random pod selection
    if target_pod_index == 'random':
        import random
        target_pod_index = random.randint(0, len(component.pods) - 1)
        component._emit_log("INFO", f"hot_shard: Randomly selected pod index {target_pod_index} (out of {len(component.pods)} pods)")

    if target_pod_index >= len(component.pods):
        component._emit_log("ERROR", f"Invalid target_pod_index {target_pod_index} (only {len(component.pods)} pods)")
        return

    # Identify the hot shard pod
    hot_pod = component.pods[target_pod_index]

    # Build traffic weights
    num_pods = len(component.pods)
    remaining_weight = 1.0 - skew_factor
    other_weight = remaining_weight / (num_pods - 1) if num_pods > 1 else 0.0

    component.traffic_weights = {}
    for pod in component.pods:
        if pod.id == hot_pod.id:
            component.traffic_weights[pod.id] = skew_factor
        else:
            component.traffic_weights[pod.id] = other_weight

    component._emit_log("WARN", f"Hot shard: {skew_factor*100:.0f}% traffic to pod {hot_pod.id}")

def revert_hot_shard(component: Service, params: Dict[str, Any]):
    """Revert hot shard by resetting traffic weights to uniform."""
    if not isinstance(component, Service):
        return

    component.traffic_weights = {}
    component._emit_log("INFO", "Hot shard reverted - uniform traffic distribution")

def network_partition(component: NetworkLink, params: Dict[str, Any]):
    """
    Simulates network partition by blocking traffic between source and target.

    Args:
        component: The NetworkLink to apply partition to
        params: source_component_id (str), target_component_id (str), bidirectional (bool, default: True)
    """
    if not isinstance(component, NetworkLink):
        component._emit_log("WARN", "network_partition can only be applied to NetworkLink components.")
        return

    source_id = params.get("source_component_id")
    target_id = params.get("target_component_id")
    bidirectional = params.get("bidirectional", True)

    if not source_id or not target_id:
        component._emit_log("ERROR", "network_partition requires source_component_id and target_component_id")
        return

    # Add partition rule(s)
    component.partition_rules.add((source_id, target_id))
    if bidirectional:
        component.partition_rules.add((target_id, source_id))

    direction = "bidirectional" if bidirectional else "unidirectional"
    component._emit_log("WARN", f"Network partition: {source_id} <-> {target_id} ({direction})")

def revert_network_partition(component: NetworkLink, params: Dict[str, Any]):
    """Revert network partition by removing partition rules."""
    if not isinstance(component, NetworkLink):
        return

    source_id = params.get("source_component_id")
    target_id = params.get("target_component_id")
    bidirectional = params.get("bidirectional", True)

    if not source_id or not target_id:
        component._emit_log("ERROR", "revert_network_partition requires source_component_id and target_component_id")
        return

    # Remove partition rule(s)
    component.partition_rules.discard((source_id, target_id))
    if bidirectional:
        component.partition_rules.discard((target_id, source_id))

    component._emit_log("INFO", f"Network partition reverted: {source_id} <-> {target_id}")

def force_deadlock(component, params: Dict[str, Any]):
    """
    Simulates logical deadlock by consuming threads/connections without consuming CPU.
    This models lock waits or circular dependencies.

    Args:
        component: The Pod, Service, or Database to deadlock
        params:
            - locked_threads (int, optional): Absolute number of threads/connections to lock
            - thread_percentage (float, optional): Percentage of threads/connections to lock (0.0-1.0)
            - duration (float, seconds): How long to hold threads/connections

    If both locked_threads and thread_percentage are provided, locked_threads takes precedence.
    If neither is provided, defaults to 70% of thread/connection pool (enough to cause degradation).
    """
    from src.components.database import SqlDatabase

    # Determine target component and resource pool
    target = None
    resource_pool = None
    resource_type = "threads"

    if isinstance(component, Service):
        if not component.pods:
            component._emit_log("WARN", "force_deadlock: Service has no pods")
            return
        import random
        target = random.choice(component.pods)
        resource_pool = target.thread_pool
        resource_type = "threads"
        # Store the affected pod ID on the Service for robust revert
        component._force_deadlock_pod_id = target.id
        component._emit_log("INFO", f"force_deadlock: Applying to randomly selected pod {target.id} (out of {len(component.pods)} pods)")
    elif isinstance(component, Pod):
        target = component
        resource_pool = target.thread_pool
        resource_type = "threads"
        # Store pod ID on itself for consistency
        component._force_deadlock_pod_id = target.id
    elif isinstance(component, SqlDatabase):
        target = component
        resource_pool = target.connection_pool
        resource_type = "connections"
        # Store component ID for revert
        component._force_deadlock_component_id = target.id
    else:
        component._emit_log("WARN", f"force_deadlock can only be applied to Pod, Service, or Database components (got {type(component).__name__})")
        return

    # Determine how many threads/connections to lock
    if "locked_threads" in params:
        # Explicit count provided
        locked_resources = params["locked_threads"]
    elif "thread_percentage" in params:
        # Percentage-based approach
        thread_percentage = params["thread_percentage"]
        pool_size = resource_pool.capacity
        locked_resources = max(1, int(pool_size * thread_percentage))
        target._emit_log("INFO", f"force_deadlock: Locking {thread_percentage*100:.0f}% of {pool_size} {resource_type} = {locked_resources} {resource_type}")
    else:
        # Default: Lock 70% (enough to cause issues but not total failure)
        pool_size = resource_pool.capacity
        locked_resources = max(1, int(pool_size * 0.7))
        target._emit_log("INFO", f"force_deadlock: Using default 70% of {pool_size} {resource_type} = {locked_resources} {resource_type}")

    duration = params.get("duration", 300.0)  # 5 minutes default

    # Validate: Can't lock more than pool capacity
    pool_capacity = resource_pool.capacity
    if locked_resources > pool_capacity:
        target._emit_log("WARN", f"force_deadlock: Requested {locked_resources} {resource_type} but pool only has {pool_capacity}. Capping to {pool_capacity}.")
        locked_resources = pool_capacity

    # Validate: Need at least 1 resource to lock
    if locked_resources < 1:
        target._emit_log("WARN", f"force_deadlock: Cannot lock {locked_resources} {resource_type}. Must lock at least 1.")
        return

    # Initialize zombie process tracking if not exists
    if not hasattr(target, '_zombie_processes'):
        target._zombie_processes = []

    # Spawn zombie processes that acquire resources but don't do work
    def _zombie_task():
        try:
            with resource_pool.request() as req:
                yield req  # Acquire resource
                target._emit_log("DEBUG", f"Deadlock: {resource_type[:-1]} locked (zombie task)")
                # Just sleep - no CPU consumption, no dynamics update
                yield target.env.timeout(duration)
                target._emit_log("DEBUG", f"Deadlock: {resource_type[:-1]} released (duration expired)")
        except Exception as e:
            # Handle interruption (from revert_force_deadlock)
            target._emit_log("DEBUG", f"Deadlock: {resource_type[:-1]} released (interrupted: {e})")

    # Spawn the zombie tasks and track them
    for _ in range(locked_resources):
        zombie_proc = target.env.process(_zombie_task())
        target._zombie_processes.append(zombie_proc)

    target._emit_log("WARN", f"Force deadlock: {locked_resources} {resource_type} locked for {duration}s")

def revert_force_deadlock(component, params: Dict[str, Any]):
    """
    Revert force deadlock by interrupting all zombie processes on the originally affected component.

    This allows threads/connections to be released early before the deadlock duration expires.
    """
    from src.components.database import SqlDatabase

    # Determine target component
    target = None
    tracking_attr = None

    if hasattr(component, '_force_deadlock_pod_id'):
        # Pod or Service
        affected_pod_id = component._force_deadlock_pod_id
        tracking_attr = '_force_deadlock_pod_id'

        if isinstance(component, Service):
            # Look up pod in service's current pod list
            for pod in component.pods:
                if pod.id == affected_pod_id:
                    target = pod
                    break

            if target is None:
                component._emit_log("WARN", f"force_deadlock: Original pod {affected_pod_id} no longer exists (may have been replaced)")
                del component._force_deadlock_pod_id
                return

            component._emit_log("INFO", f"force_deadlock: Reverting on pod {target.id}")
        elif isinstance(component, Pod):
            target = component
        else:
            return

    elif hasattr(component, '_force_deadlock_component_id'):
        # Database
        target = component
        tracking_attr = '_force_deadlock_component_id'
    else:
        component._emit_log("WARN", "No force_deadlock tracking found - cannot revert")
        return

    if not hasattr(target, '_zombie_processes') or not target._zombie_processes:
        target._emit_log("INFO", "No zombie processes to revert")
        # Clean up tracking
        if tracking_attr:
            delattr(component, tracking_attr)
        return

    # Interrupt all zombie processes
    interrupted_count = 0
    for zombie_proc in target._zombie_processes:
        if zombie_proc.is_alive:
            try:
                zombie_proc.interrupt("Deadlock reverted")
                interrupted_count += 1
            except RuntimeError:
                # Process already finished
                pass

    # Clear the zombie process list
    target._zombie_processes = []

    target._emit_log("INFO", f"Force deadlock reverted: {interrupted_count} resources released early")

    # Clean up tracking
    if tracking_attr:
        delattr(component, tracking_attr)


def no_fault(component: SimulatedComponent, params: Dict[str, Any]):
    """
    No-op fault mode for running simulations without any fault injection.
    This allows users to collect baseline performance data.

    Args:
        component: Target component (unused)
        params: Fault parameters (unused)
    """
    pass


# A registry mapping the 'mode' string to the actual function
FAILURE_MODES = {
    # No fault mode (baseline)
    "no_fault": no_fault,

    # State manipulation
    "set_state": set_component_state,

    # Generic latency and errors
    "inject_latency": inject_latency,
    "revert_latency": revert_latency,
    "inject_errors": inject_errors,
    "revert_errors": revert_errors,

    # Compute/Service failures (Tier 1: Core Resource Saturation)
    "cpu_saturation": cpu_saturation,
    "revert_cpu_saturation": revert_cpu_saturation,
    "memory_leak": memory_leak,  # Alias for start_memory_leak
    "start_memory_leak": start_memory_leak,
    "stop_memory_leak": stop_memory_leak,
    "memory_pressure": memory_pressure,
    "revert_memory_pressure": revert_memory_pressure,
    "memory_thrashing": memory_thrashing,  # NEW: Tier 1 fault
    "revert_memory_thrashing": revert_memory_thrashing,
    "thread_exhaustion": thread_exhaustion,  # NEW: Tier 1 fault (preferred name)
    "revert_thread_exhaustion": revert_thread_exhaustion,
    "disk_io_saturation": disk_io_saturation,  # NEW: Tier 1 fault
    "revert_disk_io_saturation": revert_disk_io_saturation,

    # Database-specific faults removed (2025-12-10)
    # Deprecated redundant faults that duplicated existing functionality:
    # - slow_queries/revert_slow_queries → Use disk_io_saturation (HIGH latency, LOW CPU)
    # - connection_exhaustion/revert_connection_exhaustion → Use thread_exhaustion (pool saturation)
    # - enable_background_job/disable_background_job → Use cpu_saturation (CPU contention)
    # - start_db_background_job/stop_db_background_job → Use cpu_saturation (CPU contention)
    # - inject_db_wear/reset_db_wear → Use disk_io_saturation (I/O slowdown)

    # Cache failures
    "cache_failure": cache_failure,
    "revert_cache_failure": revert_cache_failure,

    # Queue/messaging failures
    "queue_consumer_slowdown": queue_consumer_slowdown,
    "revert_queue_consumer_slowdown": revert_queue_consumer_slowdown,

    # Structural failure modes
    "noisy_neighbor": noisy_neighbor,
    "revert_noisy_neighbor": revert_noisy_neighbor,
    "hot_shard": hot_shard,
    "revert_hot_shard": revert_hot_shard,
    "network_partition": network_partition,
    "revert_network_partition": revert_network_partition,
    "force_deadlock": force_deadlock,
    "revert_force_deadlock": revert_force_deadlock,
}

# Registry mapping fault injection modes to their revert functions
# Used by the training injector for automatic fault recovery
REVERT_MODES = {
    # No fault mode (no revert needed)
    "no_fault": None,

    # Generic faults
    "inject_latency": revert_latency,
    "inject_errors": revert_errors,

    # Compute/Service faults (Tier 1: Core Resource Saturation)
    "cpu_saturation": revert_cpu_saturation,
    "memory_leak": stop_memory_leak,
    "start_memory_leak": stop_memory_leak,
    "memory_pressure": revert_memory_pressure,
    "memory_thrashing": revert_memory_thrashing,  # NEW: Tier 1 fault
    "thread_exhaustion": revert_thread_exhaustion,  # NEW: Tier 1 fault
    "disk_io_saturation": revert_disk_io_saturation,  # NEW: Tier 1 fault

    # Database-specific faults removed (2025-12-10)
    # See FAILURE_MODES registry for migration guide

    # Cache faults
    "cache_failure": revert_cache_failure,

    # Queue faults
    "queue_consumer_slowdown": revert_queue_consumer_slowdown,

    # Structural faults
    "noisy_neighbor": revert_noisy_neighbor,
    "hot_shard": revert_hot_shard,
    "network_partition": revert_network_partition,
    "force_deadlock": revert_force_deadlock,

    # State changes (no revert needed - handled by deployment controller)
    "set_state": None,
}