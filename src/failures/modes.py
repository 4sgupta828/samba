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
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache
from src.components.messaging import MessageQueue

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

    cpu_target = params.get("cpu_percent", 80)

    # Set FLOOR: CPU never goes below target (CRITICAL FIX)
    component.dynamics.fault_cpu_floor_percent = cpu_target
    component._emit_log("WARN", f"CPU saturation: {cpu_target}% floor")

def revert_cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """Revert CPU saturation by removing CPU floor."""
    if not isinstance(component, (ComputeAgent, Pod)):
        return

    if hasattr(component, 'dynamics') and component.dynamics is not None:
        component.dynamics.fault_cpu_floor_percent = None
        component._emit_log("INFO", "CPU saturation reverted (floor removed)")
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

def cache_failure(component: InMemoryCache, params: Dict[str, Any]):
    """
    Simulates cache failure by clearing the cache and setting state to degraded.
    This causes cache misses which will increase database load.
    """
    if not isinstance(component, InMemoryCache):
        component._emit_log("WARN", "cache_failure can only be applied to InMemoryCache components.")
        return

    # Clear all cached items
    component.cache.clear()
    component.state.operational = "DEGRADED"
    component._emit_log("WARN", "Cache failure injected - all items evicted, cache degraded")

def revert_cache_failure(component: InMemoryCache, params: Dict[str, Any]):
    """Revert cache failure."""
    if not isinstance(component, InMemoryCache):
        return

    component.state.operational = "RUNNING"
    component._emit_log("INFO", "Cache failure reverted - cache operational")

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
}