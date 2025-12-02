"""
Component Lifecycle Management

This module provides the infrastructure for managing restartable components in the simulation.
It implements a pattern where component instances are ephemeral and recreated on each restart,
ensuring that state never leaks between lifetimes.

Key Classes:
    RestartableComponent: Base class for components that can be restarted
    ComponentLifecycleManager: Manages the lifecycle of a restartable component

Design Philosophy:
    "Each restart should be indistinguishable from creating a new process"

Real-World Analogy:
    ComponentLifecycleManager = Kubernetes Pod Controller
    RestartableComponent = Container Process (dies and is recreated)
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict, Callable
import simpy
import random


class RestartableComponent(ABC):
    """
    Base class for components that can be restarted (Pods, Databases, etc.).

    This is the EPHEMERAL instance that lives for a single lifetime.
    It is created fresh on each restart and garbage collected when terminated.

    Each instance represents one "incarnation" of the component - like a single
    process lifetime in a real system. When the process crashes, this object is
    destroyed and a new one is created.
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 component_type: str, lifetime_id: int):
        """
        Initialize component instance for a single lifetime.

        Args:
            env: SimPy environment
            component_id: Persistent component identifier (survives restarts)
            component_type: Type of component (Pod, Database, etc.)
            lifetime_id: Which lifetime this is (0 = first start, 1 = first restart, etc.)
        """
        self.env = env
        self.component_id = component_id  # Persistent ID
        self.lifetime_id = lifetime_id    # Which incarnation
        self.component_type = component_type

        # Full ID includes lifetime for debugging
        self.instance_id = f"{component_id}_L{lifetime_id}"

        # Initialize fresh state
        self._initialize_fresh_state()

        print(f"[{self.env.now:.2f}] Created {component_type} instance: {self.instance_id}")

    @abstractmethod
    def _initialize_fresh_state(self):
        """
        Initialize all mutable state for this lifetime.

        This method MUST initialize ALL state variables to their starting values.
        This is called once during __init__ and never again.

        IMPORTANT: This should create NEW objects, not reuse old ones:
            ✅ self.thread_pool = simpy.Resource(self.env, capacity=50)
            ✅ self.request_count = 0
            ✅ self.active_processes = set()

            ❌ self.thread_pool.queue.clear()  # Don't clear, create new!
            ❌ self.request_count = self.request_count or 0  # Don't reuse!

        Example:
            def _initialize_fresh_state(self):
                self.thread_pool = simpy.Resource(self.env, capacity=50)
                self.request_count = 0
                self.active_processes = set()
                self.metrics = []
        """
        pass

    @abstractmethod
    def run_single_lifetime(self):
        """
        Run component for a single lifetime (until crash or termination).

        This is a SimPy generator that runs until:
        - Interrupted with "CRASHED" cause (restart)
        - Interrupted with "TERMINATED" cause (permanent stop)
        - Interrupted with crash-specific causes ("OOMKilled", "Error", etc.)
        - Completes naturally (rare)

        Returns control to ComponentLifecycleManager when done.

        Example:
            def run_single_lifetime(self):
                # Startup phase
                self.state = "STARTING"
                yield self.env.timeout(startup_delay)

                self.state = "RUNNING"

                # Start background processes
                self.env.process(self._monitor_health())

                # Run until interrupted
                try:
                    yield self.env.timeout(float('inf'))
                except simpy.Interrupt:
                    # Let lifecycle manager handle the interrupt
                    raise
        """
        pass

    @abstractmethod
    def get_persistent_config(self) -> Dict[str, Any]:
        """
        Return configuration that should persist across restarts.

        This is used to initialize the next instance after restart.
        Only include immutable configuration, NOT runtime state.

        Example:
            return {
                'thread_pool_size': 50,
                'memory_capacity': 1024,
                'parent_service': self.parent_service,  # Reference to parent
            }

        DO NOT include:
        - Counters (request_count, etc.)
        - Collections (active_processes, queues, etc.)
        - Metrics (cpu_samples, latency_samples, etc.)
        - Dynamic state (circuit_breakers, etc.)
        """
        pass


class ComponentLifecycleManager:
    """
    Manages the lifecycle of a restartable component.

    This is the PERSISTENT manager that survives across restarts.
    It creates fresh RestartableComponent objects on each restart.

    Responsibilities:
    - Create new instances on each restart
    - Enforce restart policies (backoff, max restarts)
    - Track lifecycle metrics (restart count, uptime)
    - Notify listeners of lifecycle events
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 component_type: str, component_class: type,
                 persistent_config: Dict[str, Any],
                 restart_policy: Optional[Dict[str, Any]] = None):
        """
        Initialize lifecycle manager.

        Args:
            env: SimPy environment
            component_id: Unique identifier for this component
            component_type: Type of component (Pod, Database, etc.)
            component_class: Class to instantiate (must inherit RestartableComponent)
            persistent_config: Configuration that persists across restarts
            restart_policy: Restart policy configuration
        """
        self.env = env
        self.component_id = component_id
        self.component_type = component_type
        self.component_class = component_class
        self.persistent_config = persistent_config

        # Restart policy
        default_policy = {
            'max_restarts': None,  # None = unlimited
            'backoff_base_seconds': 10.0,
            'backoff_max_seconds': 300.0,
            'backoff_jitter_range': [-2, 5],
        }
        self.restart_policy = {**default_policy, **(restart_policy or {})}

        # Lifecycle tracking
        self.lifetime_count = 0
        self.total_restarts = 0
        self.current_instance: Optional[RestartableComponent] = None
        self.current_process: Optional[simpy.Process] = None
        self.termination_requested = False

        # Callbacks for lifecycle events
        self.on_instance_created: Optional[Callable[[RestartableComponent], None]] = None
        self.on_instance_terminated: Optional[Callable[[RestartableComponent], None]] = None
        self.on_restart: Optional[Callable[[int, str], None]] = None

    def run(self):
        """
        Main lifecycle loop - creates and manages component instances.

        This is a SimPy generator that runs forever (or until terminated).
        """
        while not self.termination_requested:
            # Create new instance for this lifetime
            self.current_instance = self.component_class(
                env=self.env,
                component_id=self.component_id,
                component_type=self.component_type,
                lifetime_id=self.lifetime_count,
                **self.persistent_config  # Pass persistent config
            )

            # Notify listeners
            if self.on_instance_created:
                self.on_instance_created(self.current_instance)

            try:
                # Run instance for single lifetime
                self.current_process = self.env.process(
                    self.current_instance.run_single_lifetime()
                )
                yield self.current_process

                # If we get here, instance completed naturally (rare)
                print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                      f"completed lifetime {self.lifetime_count}")
                break  # Exit lifecycle loop

            except simpy.Interrupt as interrupt:
                cause = interrupt.cause

                if cause == "TERMINATED":
                    # Permanent termination requested
                    print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                          f"terminated at lifetime {self.lifetime_count}")
                    break  # Exit lifecycle loop

                elif cause in ["CRASHED", "OOMKilled", "Error", "Timeout", "HealthCheckFailed"]:
                    # Component crashed - prepare for restart
                    print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                          f"crashed at lifetime {self.lifetime_count}: {cause}")

                    self.total_restarts += 1

                    # Notify restart listener
                    if self.on_restart:
                        self.on_restart(self.total_restarts, cause)

                    # Check restart limit
                    max_restarts = self.restart_policy['max_restarts']
                    if max_restarts is not None and self.total_restarts >= max_restarts:
                        print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                              f"exceeded max restarts ({max_restarts})")
                        break  # Exit lifecycle loop

                    # Calculate backoff delay (exponential with jitter)
                    backoff_base = self.restart_policy['backoff_base_seconds']
                    backoff_max = self.restart_policy['backoff_max_seconds']
                    jitter_range = self.restart_policy['backoff_jitter_range']

                    backoff = min(backoff_base * (2 ** (self.total_restarts - 1)), backoff_max)
                    jitter = random.uniform(jitter_range[0], jitter_range[1])
                    delay = max(0, backoff + jitter)  # Don't allow negative delays

                    print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                          f"waiting {delay:.1f}s before restart #{self.total_restarts + 1}")

                    # Notify listeners
                    if self.on_instance_terminated:
                        self.on_instance_terminated(self.current_instance)

                    # Wait for backoff
                    yield self.env.timeout(delay)

                    # Instance object goes out of scope here and will be garbage collected
                    # ALL its state is destroyed!
                    self.current_instance = None
                    self.current_process = None

                    # Increment lifetime counter
                    self.lifetime_count += 1

                    # Continue to next iteration (create new instance)

                else:
                    # Unknown interrupt cause
                    print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
                          f"received unknown interrupt: {cause}")
                    break  # Exit lifecycle loop

            finally:
                # Cleanup
                if self.on_instance_terminated and self.current_instance:
                    self.on_instance_terminated(self.current_instance)
                self.current_instance = None
                self.current_process = None

        print(f"[{self.env.now:.2f}] {self.component_type} {self.component_id} "
              f"lifecycle ended (total restarts: {self.total_restarts})")

    def terminate(self):
        """
        Request termination of the component (graceful shutdown).

        This will interrupt the current instance with "TERMINATED" cause
        and prevent any further restarts.
        """
        self.termination_requested = True
        if self.current_process and self.current_process.is_alive:
            try:
                self.current_process.interrupt("TERMINATED")
            except RuntimeError:
                pass  # Process already terminated

    def trigger_crash(self, cause: str = "CRASHED"):
        """
        Trigger a crash of the current instance.

        This will interrupt the current instance with the specified cause,
        which will trigger the restart logic (if within restart limits).

        Args:
            cause: Crash cause (CRASHED, OOMKilled, Error, etc.)
        """
        if self.current_process and self.current_process.is_alive:
            try:
                self.current_process.interrupt(cause)
            except RuntimeError:
                pass  # Process already terminated
