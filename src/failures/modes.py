"""
Defines the implementation of specific failure modes that can be applied to components.
Each function takes a component and parameters, and modifies the component's state.

Note: For gradual failures, use the TrainingFailureInjector's apply_infrastructure_change
mechanism. These functions are for instant state changes.
"""
from typing import Dict, Any

from src.components.base_component import SimulatedComponent
from src.components.compute import ComputeAgent
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
    """Injects additional latency into a component's operations."""
    latency_ms = params.get("latency_ms", 1000)
    component.injected_latency_ms = latency_ms
    component._emit_log("WARN", f"Injecting {latency_ms}ms of additional latency.")

def revert_latency(component: SimulatedComponent, params: Dict[str, Any]):
    """Removes injected latency."""
    component.injected_latency_ms = 0
    component._emit_log("INFO", "Reverting injected latency.")
    
def start_memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """Starts or accelerates a memory leak in a ComputeAgent."""
    leak_rate = params.get("leak_mb_per_request", 0.5)
    component.leak_mb_per_request = leak_rate
    component._emit_log("WARN", f"Starting memory leak at {leak_rate} MB/request.")

def stop_memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """Stops an injected memory leak."""
    component.leak_mb_per_request = 0.0 # Or revert to a smaller baseline leak
    component._emit_log("INFO", "Stopping memory leak.")

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
    This increases query latency gradually as if the DB has been running under load.
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "inject_db_wear can only be applied to SqlDatabase components.")
        return

    wear_amount = params.get("wear_factor", 0.1)
    component.wear_factor += wear_amount
    added_latency_ms = wear_amount * 100  # Each 1.0 wear = 100ms
    component._emit_log("WARN", f"Injected DB wear (+{wear_amount:.3f}), adds ~{added_latency_ms:.1f}ms latency per query.")

def reset_db_wear(component: SqlDatabase, params: Dict[str, Any]):
    """Reset database wear to pristine state (simulates DB optimization/rebuild)."""
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "reset_db_wear can only be applied to SqlDatabase components.")
        return

    old_wear = component.wear_factor
    component.wear_factor = 0.0
    component._emit_log("INFO", f"Reset DB wear (was {old_wear:.3f}) - DB optimized/rebuilt.")


def cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """
    Simulates CPU saturation by increasing latency and CPU multiplier.
    This makes requests slower and increases CPU metrics.
    """
    if not isinstance(component, ComputeAgent):
        component._emit_log("WARN", "cpu_saturation can only be applied to ComputeAgent components.")
        return

    cpu_multiplier = params.get("cpu_multiplier", 3.0)
    latency_multiplier = params.get("latency_multiplier", 2.0)

    component.cpu_multiplier = cpu_multiplier
    component.latency_multiplier = latency_multiplier
    component._emit_log("WARN", f"CPU saturation injected: CPU {cpu_multiplier}x, latency {latency_multiplier}x")

def revert_cpu_saturation(component: ComputeAgent, params: Dict[str, Any]):
    """Revert CPU saturation."""
    if not isinstance(component, ComputeAgent):
        return

    component.cpu_multiplier = 1.0
    component.latency_multiplier = 1.0
    component._emit_log("INFO", "CPU saturation reverted")

def memory_leak(component: ComputeAgent, params: Dict[str, Any]):
    """
    Alias for start_memory_leak for consistency with scenario naming.
    """
    start_memory_leak(component, params)

def memory_pressure(component: ComputeAgent, params: Dict[str, Any]):
    """
    Simulates memory pressure without a leak - just high baseline memory usage.
    """
    if not isinstance(component, ComputeAgent):
        component._emit_log("WARN", "memory_pressure can only be applied to ComputeAgent components.")
        return

    memory_increase_mb = params.get("memory_increase_mb", 300)
    component.memory_bloat_mb += memory_increase_mb
    component._emit_log("WARN", f"Memory pressure injected: +{memory_increase_mb}MB")

def revert_memory_pressure(component: ComputeAgent, params: Dict[str, Any]):
    """Revert memory pressure."""
    if not isinstance(component, ComputeAgent):
        return

    memory_increase_mb = params.get("memory_increase_mb", 300)
    component.memory_bloat_mb = max(0, component.memory_bloat_mb - memory_increase_mb)
    component._emit_log("INFO", "Memory pressure reverted")

def inject_errors(component: SimulatedComponent, params: Dict[str, Any]):
    """
    Inject increased error rate.
    """
    error_rate = params.get("error_rate", 0.1)
    component.forced_error_rate = error_rate
    component._emit_log("WARN", f"Error rate injected: {error_rate*100:.1f}%")

def revert_errors(component: SimulatedComponent, params: Dict[str, Any]):
    """Revert error rate injection."""
    component.forced_error_rate = 0.0
    component._emit_log("INFO", "Error rate injection reverted")

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
    Simulates message queue consumer slowdown by injecting latency.
    This will cause message backlog to build up.
    """
    if not isinstance(component, MessageQueue):
        component._emit_log("WARN", "queue_consumer_slowdown can only be applied to MessageQueue components.")
        return

    latency_ms = params.get("latency_ms", 1000)
    component.injected_latency_ms = latency_ms
    component._emit_log("WARN", f"Queue consumer slowdown injected: +{latency_ms}ms per message")

def revert_queue_consumer_slowdown(component: MessageQueue, params: Dict[str, Any]):
    """Revert queue consumer slowdown."""
    if not isinstance(component, MessageQueue):
        return

    component.injected_latency_ms = 0
    component._emit_log("INFO", "Queue consumer slowdown reverted")

def slow_queries(component: SqlDatabase, params: Dict[str, Any]):
    """
    Simulates slow database queries by injecting DB wear.
    Alias for inject_db_wear with query-specific semantics.
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "slow_queries can only be applied to SqlDatabase components.")
        return

    wear_factor = params.get("wear_factor", 0.3)
    params_with_wear = {"wear_factor": wear_factor}
    inject_db_wear(component, params_with_wear)
    component._emit_log("WARN", f"Slow queries injected: wear factor +{wear_factor}")

def revert_slow_queries(component: SqlDatabase, params: Dict[str, Any]):
    """Revert slow queries."""
    reset_db_wear(component, params)

def connection_exhaustion(component: SqlDatabase, params: Dict[str, Any]):
    """
    Simulates database connection pool exhaustion by increasing connection latency.
    """
    if not isinstance(component, SqlDatabase):
        component._emit_log("WARN", "connection_exhaustion can only be applied to SqlDatabase components.")
        return

    latency_ms = params.get("latency_ms", 500)
    component.injected_latency_ms = latency_ms
    component._emit_log("WARN", f"Connection exhaustion simulated: +{latency_ms}ms connection delay")

def revert_connection_exhaustion(component: SqlDatabase, params: Dict[str, Any]):
    """Revert connection exhaustion."""
    if not isinstance(component, SqlDatabase):
        return

    component.injected_latency_ms = 0
    component._emit_log("INFO", "Connection exhaustion reverted")

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