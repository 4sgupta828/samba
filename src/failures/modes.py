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

def start_db_background_job(component: SqlDatabase, params: Dict[str, Any]):
    """Starts the database background job (VACUUM/cleanup) which competes for CPU resources."""
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "start_db_background_job can only be applied to SqlDatabase components.")
        return

    # Start the background job process
    component.env.process(component._run_background_job())
    component._emit_log("WARN", "Started background job (VACUUM/cleanup) - may increase DB CPU and query latency.")

def stop_db_background_job(component: SqlDatabase, params: Dict[str, Any]):
    """
    Stops the database background job.
    Note: Due to SimPy's process model, we can't easily stop a running background process.
    Instead, we add a flag that the background job checks.
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "stop_db_background_job can only be applied to SqlDatabase components.")
        return

    # Set a flag to stop the background job
    component.background_job_enabled = False
    component._emit_log("INFO", "Background job disabled - DB should return to baseline performance.")

def inject_db_wear(component: SqlDatabase, params: Dict[str, Any]):
    """
    Inject database degradation (simulates index bloat, fragmentation, etc.)
    This increases query latency via the dynamics engine wear_factor.
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "inject_db_wear can only be applied to SqlDatabase components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject wear")
        return

    wear_amount = params.get("wear_factor", 0.1)
    component.dynamics.wear_factor += wear_amount
    # Wear affects latency through dynamics: latency *= (1 + wear_factor * latency_wear_coef)
    wear_coef = component.dynamics.config.latency_wear_coef
    added_latency_factor = wear_amount * wear_coef
    component._emit_log("WARN", f"Injected DB wear (+{wear_amount:.3f}), latency multiplier: {1 + added_latency_factor:.3f}x")

def reset_db_wear(component: SqlDatabase, params: Dict[str, Any]):
    """Reset database wear to pristine state via dynamics engine."""
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "reset_db_wear can only be applied to SqlDatabase components.")
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        old_wear = component.dynamics.wear_factor
        component.dynamics.wear_factor = 0.0
        component._emit_log("INFO", f"Reset DB wear (was {old_wear:.3f}) - DB optimized/rebuilt (dynamics)")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")


def cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """
    FLOOR FAULT: Sets minimum CPU regardless of load.
    Models CPU exhaustion from external processes, resource contention.
    """
    if not isinstance(component, (ComputeAgent, Pod)):
        component._emit_log("WARN", "cpu_saturation can only be applied to ComputeAgent/Pod components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject CPU saturation")
        return

    cpu_target = params.get("cpu_percent", 95)  # Default 95%

    # Set FLOOR
    component.dynamics.fault_cpu_floor_percent = cpu_target

    # FIX: Add additive latency to simulate scheduler contention
    # When CPU is pinned at 95%, threads don't just run slower, they wait for time slices.
    # Add 200ms processing delay penalty.
    component.dynamics.fault_latency_additive_ms = 200.0

    component._emit_log("WARN", f"CPU saturation: {cpu_target}% floor + 200ms contention lag")

def revert_cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """Revert CPU saturation by removing CPU floor."""
    if not isinstance(component, (ComputeAgent, Pod)):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_cpu_floor_percent = None
        component.dynamics.fault_latency_additive_ms = 0.0  # Reset
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
    Simulates memory pressure without a leak - just high baseline memory usage via dynamics engine.
    """
    if not isinstance(component, ComputeAgent):
        component._emit_log("WARN", "memory_pressure can only be applied to ComputeAgent components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject memory pressure")
        return

    memory_increase_mb = params.get("memory_increase_mb", 300)
    # Increase baseline memory in dynamics engine
    component.dynamics.config.memory_base += memory_increase_mb
    component._emit_log("WARN", f"Memory pressure injected: +{memory_increase_mb}MB (dynamics: memory_base={component.dynamics.config.memory_base:.1f}MB)")

def revert_memory_pressure(component: ComputeAgent, params: Dict[str, Any]):
    """Revert memory pressure via dynamics engine."""
    if not isinstance(component, ComputeAgent):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        memory_increase_mb = params.get("memory_increase_mb", 300)
        # Reduce baseline memory back to normal (careful not to go negative)
        component.dynamics.config.memory_base = max(10.0, component.dynamics.config.memory_base - memory_increase_mb)
        component._emit_log("INFO", f"Memory pressure reverted (dynamics: memory_base={component.dynamics.config.memory_base:.1f}MB)")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

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

def slow_queries(component: SqlDatabase, params: Dict[str, Any]):
    """
    FLOOR FAULT: Sets minimum query latency regardless of load.
    Models inherently slow queries (table scans, missing indexes).
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "slow_queries can only be applied to SqlDatabase components.")
        return

    if not hasattr(component, 'dynamics') or component.dynamics is None:
        component._emit_log("ERROR", "Component does not have dynamics engine - cannot inject slow queries")
        return

    # Map wear_factor parameter to meaningful latency floor
    # wear_factor 0.3 -> 56ms floor, 0.5 -> 80ms floor, 1.0 -> 140ms floor
    wear_factor = params.get("wear_factor", 0.3)
    slowdown_factor = 1.0 + (wear_factor * 6.0)
    base_latency = component.dynamics.config.latency_base
    latency_floor = base_latency * slowdown_factor

    # Set FLOOR: queries never faster than this (CRITICAL FIX)
    component.dynamics.fault_latency_floor_ms = latency_floor
    component._emit_log("WARN", f"Slow queries: {slowdown_factor:.1f}x floor ({latency_floor:.0f}ms min, wear={wear_factor})")

def revert_slow_queries(component: SqlDatabase, params: Dict[str, Any]):
    """Revert slow queries by removing latency floor."""
    if not isinstance(component, SqlDatabase):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_latency_floor_ms = None
        component._emit_log("INFO", "Slow queries reverted (floor removed)")
    else:
        component._emit_log("WARN", "Component does not have dynamics engine")

def connection_exhaustion(component: SqlDatabase, params: Dict[str, Any]):
    """
    Simulates database connection pool exhaustion by holding connections.

    Creates dummy/leaked connections that occupy slots in the pool, causing:
    - New requests to queue waiting for available connections
    - Increased latency due to queueing
    - Potential connection rejections if pool fills completely
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "connection_exhaustion can only be applied to SqlDatabase components.")
        return

    if not hasattr(component, 'connection_pool'):
        component._emit_log("ERROR", "Component does not have connection_pool - cannot inject connection exhaustion")
        return

    exhaustion_rate = params.get("exhaustion_rate", 0.7)  # Default: exhaust 70% of pool
    pool_capacity = component.connection_pool.capacity
    num_to_hold = int(pool_capacity * exhaustion_rate)

    # Store leaked connection requests on the component for revert
    if not hasattr(component, '_leaked_connections'):
        component._leaked_connections = []

    # Acquire connections and hold them (simulating leaked/stuck connections)
    for i in range(num_to_hold):
        conn_req = component.connection_pool.request()
        component._leaked_connections.append(conn_req)
        # Trigger the request to actually acquire the connection
        conn_req.__enter__()

    available = pool_capacity - component.connection_pool.count
    component._emit_log("WARN", f"Connection exhaustion: {num_to_hold}/{pool_capacity} connections held (leaked), {available} available")

def revert_connection_exhaustion(component: SqlDatabase, params: Dict[str, Any]):
    """Revert connection exhaustion by releasing held connections."""
    if not isinstance(component, SqlDatabase):
        return

    if not hasattr(component, '_leaked_connections'):
        component._emit_log("INFO", "No leaked connections to revert")
        return

    # Release all held connections
    num_released = len(component._leaked_connections)
    for conn_req in component._leaked_connections:
        try:
            conn_req.__exit__(None, None, None)
        except Exception as e:
            component._emit_log("WARN", f"Error releasing connection: {e}")

    component._leaked_connections = []
    component._emit_log("INFO", f"Connection exhaustion reverted: {num_released} connections released")

def enable_background_job(component: SqlDatabase, params: Dict[str, Any]):
    """
    Alias for start_db_background_job for consistency with scenario naming.
    """
    start_db_background_job(component, params)

def disable_background_job(component: SqlDatabase, params: Dict[str, Any]):
    """
    Alias for stop_db_background_job for consistency.
    """
    stop_db_background_job(component, params)

def noisy_neighbor(component, params: Dict[str, Any]):
    """
    Simulates noisy neighbor by pinning CPU to 100% on the aggressor pod.
    This causes resource contention on the shared node, affecting other pods
    on the same node through CPU steal time.

    The fault has TWO effects:
    1. Aggressor pod: CPU pinned to target percentage (e.g., 100%)
    2. Co-located pods: Experience CPU steal time due to node contention

    Args:
        component: The aggressor Pod or Service (if Service, picks a random pod)
        params: cpu_percent (default: 100.0), steal_time_multiplier (default: 1.5)
    """
    # If component is a Service, pick a random pod
    if isinstance(component, Service):
        if not component.pods:
            component._emit_log("WARN", "noisy_neighbor: Service has no pods")
            return
        target_pod = component.pods[0]  # Pick first pod as aggressor
        # Store the affected pod ID on the Service for robust revert
        component._noisy_neighbor_pod_id = target_pod.id
        component._emit_log("INFO", f"noisy_neighbor: Applying to pod {target_pod.id}")
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
        params: target_pod_index (int), skew_factor (float, e.g., 0.8 for 80%)
    """
    if not isinstance(component, Service):
        component._emit_log("WARN", "hot_shard can only be applied to Service components.")
        return

    target_pod_index = params.get("target_pod_index", 0)
    skew_factor = params.get("skew_factor", 0.8)

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
    Simulates logical deadlock by consuming threads without consuming CPU.
    This models lock waits or circular dependencies.

    Args:
        component: The Pod or Service to deadlock (if Service, picks a random pod)
        params: locked_threads (int, default: 10), duration (float, seconds)
    """
    # If component is a Service, pick a random pod
    if isinstance(component, Service):
        if not component.pods:
            component._emit_log("WARN", "force_deadlock: Service has no pods")
            return
        target_pod = component.pods[0]  # Pick first pod to deadlock
        # Store the affected pod ID on the Service for robust revert
        component._force_deadlock_pod_id = target_pod.id
        component._emit_log("INFO", f"force_deadlock: Applying to pod {target_pod.id}")
    elif isinstance(component, Pod):
        target_pod = component
        # Store pod ID on itself for consistency
        component._force_deadlock_pod_id = target_pod.id
    else:
        component._emit_log("WARN", f"force_deadlock can only be applied to Pod or Service components (got {type(component).__name__})")
        return

    locked_threads = params.get("locked_threads", 10)  # Default to 10 threads
    duration = params.get("duration", 300.0)  # 5 minutes default

    # Initialize zombie process tracking if not exists
    if not hasattr(target_pod, '_zombie_processes'):
        target_pod._zombie_processes = []

    # Spawn zombie processes that acquire threads but don't do work
    def _zombie_task():
        try:
            with target_pod.thread_pool.request() as req:
                yield req  # Acquire thread
                target_pod._emit_log("DEBUG", "Deadlock: thread locked (zombie task)")
                # Just sleep - no CPU consumption, no dynamics update
                yield target_pod.env.timeout(duration)
                target_pod._emit_log("DEBUG", "Deadlock: thread released (duration expired)")
        except Exception as e:
            # Handle interruption (from revert_force_deadlock)
            target_pod._emit_log("DEBUG", f"Deadlock: thread released (interrupted: {e})")

    # Spawn the zombie tasks and track them
    for _ in range(locked_threads):
        zombie_proc = target_pod.env.process(_zombie_task())
        target_pod._zombie_processes.append(zombie_proc)

    target_pod._emit_log("WARN", f"Force deadlock: {locked_threads} threads locked for {duration}s")

def revert_force_deadlock(component, params: Dict[str, Any]):
    """
    Revert force deadlock by interrupting all zombie processes on the originally affected pod.

    This allows threads to be released early before the deadlock duration expires.
    """
    # Get the originally affected pod ID
    if not hasattr(component, '_force_deadlock_pod_id'):
        component._emit_log("WARN", "No force_deadlock pod ID tracked - cannot revert")
        return

    affected_pod_id = component._force_deadlock_pod_id

    # Find the pod by ID
    if isinstance(component, Service):
        # Look up pod in service's current pod list
        target_pod = None
        for pod in component.pods:
            if pod.id == affected_pod_id:
                target_pod = pod
                break

        if target_pod is None:
            component._emit_log("WARN", f"force_deadlock: Original pod {affected_pod_id} no longer exists (may have been replaced)")
            # Clean up tracking
            del component._force_deadlock_pod_id
            return

        component._emit_log("INFO", f"force_deadlock: Reverting on pod {target_pod.id}")
    elif isinstance(component, Pod):
        target_pod = component
    else:
        return

    if not hasattr(target_pod, '_zombie_processes') or not target_pod._zombie_processes:
        target_pod._emit_log("INFO", "No zombie processes to revert")
        # Clean up tracking
        del component._force_deadlock_pod_id
        return

    # Interrupt all zombie processes
    interrupted_count = 0
    for zombie_proc in target_pod._zombie_processes:
        if zombie_proc.is_alive:
            try:
                zombie_proc.interrupt("Deadlock reverted")
                interrupted_count += 1
            except RuntimeError:
                # Process already finished
                pass

    # Clear the zombie process list
    target_pod._zombie_processes = []

    target_pod._emit_log("INFO", f"Force deadlock reverted: {interrupted_count} threads released early")

    # Clean up tracking
    del component._force_deadlock_pod_id

# A registry mapping the 'mode' string to the actual function
FAILURE_MODES = {
    # State manipulation
    "set_state": set_component_state,

    # Generic latency and errors
    "inject_latency": inject_latency,
    "revert_latency": revert_latency,
    "inject_errors": inject_errors,
    "revert_errors": revert_errors,

    # Compute/Service failures
    "cpu_saturation": cpu_saturation,
    "revert_cpu_saturation": revert_cpu_saturation,
    "memory_leak": memory_leak,  # Alias for start_memory_leak
    "start_memory_leak": start_memory_leak,
    "stop_memory_leak": stop_memory_leak,
    "memory_pressure": memory_pressure,
    "revert_memory_pressure": revert_memory_pressure,

    # Database failures
    "slow_queries": slow_queries,
    "revert_slow_queries": revert_slow_queries,
    "connection_exhaustion": connection_exhaustion,
    "revert_connection_exhaustion": revert_connection_exhaustion,
    "enable_background_job": enable_background_job,
    "disable_background_job": disable_background_job,
    "start_db_background_job": start_db_background_job,
    "stop_db_background_job": stop_db_background_job,
    "inject_db_wear": inject_db_wear,
    "reset_db_wear": reset_db_wear,

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
    # Generic faults
    "inject_latency": revert_latency,
    "inject_errors": revert_errors,

    # Compute/Service faults
    "cpu_saturation": revert_cpu_saturation,
    "memory_leak": stop_memory_leak,
    "start_memory_leak": stop_memory_leak,
    "memory_pressure": revert_memory_pressure,

    # Database faults
    "slow_queries": revert_slow_queries,
    "connection_exhaustion": revert_connection_exhaustion,
    "enable_background_job": stop_db_background_job,
    "start_db_background_job": stop_db_background_job,
    "inject_db_wear": reset_db_wear,

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