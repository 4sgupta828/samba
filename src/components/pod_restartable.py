"""
Restartable Pod Component - New lifecycle management pattern.

This module implements the Pod component using the RestartableComponent pattern,
where each restart creates a fresh instance with no state leakage.

Key improvements over original Pod:
- Automatic state isolation (impossible to leak state between restarts)
- Clear separation of lifecycle management and business logic
- Matches real-world Kubernetes behavior (container death = state loss)

Design:
- RestartablePod inherits from Pod to reuse all business logic
- Only overrides __init__ and lifecycle-related methods
- ComponentLifecycleManager creates fresh RestartablePod instances on each restart
"""

from .pod import Pod
from .lifecycle import RestartableComponent
from src.core.simulation_config import get_simulation_config
import simpy
import random


class RestartablePod(Pod, RestartableComponent):
    """
    Pod implementation using RestartableComponent pattern.

    This class inherits from both Pod (for business logic) and RestartableComponent (for lifecycle).
    Each instance is a fresh process with no state from previous lifetimes.
    When the pod crashes, this object is garbage collected and a new one is created by the
    ComponentLifecycleManager.

    Key differences from original Pod:
    - No while True loop in run() - single lifetime only
    - Fresh state guaranteed by ComponentLifecycleManager
    - Cleaner separation of concerns
    """

    def __init__(self, env, component_id, component_type, lifetime_id,
                 parent_service=None, compute_node=None, **kwargs):
        """
        Initialize a fresh pod instance for a single lifetime.

        Args:
            env: SimPy environment
            component_id: Persistent component identifier
            component_type: Component type (should be "Pod")
            lifetime_id: Which lifetime this is (0 = first start, 1 = first restart, etc.)
            parent_service: Reference to parent Service object
            compute_node: Reference to ComputeNode object (optional)
        """
        # Initialize Pod parent class (but don't call its __init__ yet)
        # We need to set up some things first

        # Initialize RestartableComponent first to set up instance_id, etc.
        RestartableComponent.__init__(self, env, component_id, component_type, lifetime_id)

        # Now initialize Pod using a special internal method that doesn't duplicate work
        # Use Pod's parent component ID but our instance-specific ID
        Pod.__init__(self, env, f"{component_id}_L{lifetime_id}", parent_service, compute_node)

        # Override the restarts counter to reflect total restarts from lifecycle manager
        self.restarts = lifetime_id

        print(f"[{self.env.now:.2f}] Created RestartablePod instance: {self.instance_id} (lifetime {lifetime_id})")

    def _initialize_fresh_state(self):
        """
        Initialize ALL mutable state for this lifetime.

        This is called by RestartableComponent.__init__(), but for RestartablePod,
        the state initialization is already handled by Pod.__init__().

        We override this to be a no-op since Pod.__init__() already does everything we need.
        """
        pass  # Pod.__init__() already initialized everything

    def run(self):
        """
        Override Pod.run() to remove the while True restart loop.

        This version runs for a single lifetime only. The ComponentLifecycleManager
        handles restart logic by creating new RestartablePod instances.
        """
        # Use the single_lifetime_run method instead
        yield from self.run_single_lifetime()

    def run_single_lifetime(self):
        """
        Run pod for a single lifetime (until crash or termination).

        This is the core run logic extracted from Pod.run() but without the while True loop.
        """
        config = get_simulation_config().compute

        # Track start time
        self.start_time = self.env.now

        # Start background processes
        self.env.process(self._sample_cpu_periodically())
        self.env.process(self._monitor_oom())
        self.env.process(self._update_dynamics_loop())

        # Start queue consumer if parent service has queue_in connection
        if self.parent_service and 'queue_in' in getattr(self.parent_service, 'connections', {}):
            self.env.process(self._consume_from_queue())

        # === Startup Phase ===
        self.state.operational = "STARTING"
        self.restarts += 1  # Increment for this lifetime
        self._emit_log("INFO", f"Starting (Lifetime {self.lifetime_id}, Restart #{self.restarts})...")

        # Reset dynamics memory on restart (simulates process restart)
        self.dynamics.memory_percent = self.dynamics.config.memory_base

        # Startup delay
        startup_delay = random.uniform(*config.startup_time_range_seconds)
        yield self.env.timeout(startup_delay)

        # === Running Phase ===
        self.state.operational = "RUNNING"
        self._emit_log("INFO", f"Pod started successfully (Version: {self.version}).")

        # Store reference to current running process for interrupt
        self.running_process = self.env.active_process

        try:
            # Pod is now running until it's interrupted (e.g., by a crash)
            yield self.env.timeout(float('inf'))

        except simpy.Interrupt as interrupt:
            # Handle different interrupt types
            if interrupt.cause == "OOMKilled":
                self._emit_log("FATAL", "OOMKilled: Memory limit exceeded.")
                self.state.operational = "CRASHED"

                # Reset dynamics memory immediately (simulates process termination)
                self.dynamics.memory_percent = self.dynamics.config.memory_base
                self.state.cpu_utilization = 0  # Process is dead, no CPU usage

                # Re-raise to lifecycle manager
                raise

            elif interrupt.cause in ["TERMINATED_FOR_DEPLOYMENT", "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                self.state.operational = "TERMINATED"
                self._emit_log("INFO", f"Pod terminated: {interrupt.cause}")

                # Remove from node if attached
                if self.compute_node and self in self.compute_node.pods:
                    self.compute_node.pods.remove(self)

                # Re-raise to lifecycle manager
                raise

            else:
                self._emit_log("ERROR", f"Unhandled interrupt: {interrupt.cause}")
                self.state.operational = "DOWN"
                raise

        finally:
            self.running_process = None

    def get_persistent_config(self):
        """
        Return configuration that persists across restarts.

        Only includes immutable references, NOT runtime state.
        """
        return {
            'parent_service': self.parent_service,
            'compute_node': self.compute_node,
        }
