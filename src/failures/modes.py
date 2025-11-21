"""
Defines the implementation of specific failure modes that can be applied to components.
Each function takes a component and parameters, and modifies the component's state.
"""
from typing import Dict, Any

from src.components.base_component import SimulatedComponent
from src.components.compute import ComputeAgent
from src.components.database import SqlDatabase

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


# A registry mapping the 'mode' string from the YAML to the actual function
FAILURE_MODES = {
    "set_state": set_component_state,
    "inject_latency": inject_latency,
    "revert_latency": revert_latency,
    "start_memory_leak": start_memory_leak,
    "stop_memory_leak": stop_memory_leak,
    "start_db_background_job": start_db_background_job,
    "stop_db_background_job": stop_db_background_job,
    "inject_db_wear": inject_db_wear,
    "reset_db_wear": reset_db_wear,
}