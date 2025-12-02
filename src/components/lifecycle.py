"""
Component Lifecycle Management - First-Principles Design for Restartable Components

This module implements the ComponentLifecycleManager pattern which ensures proper state
isolation across component restarts. Each restart creates a fresh component instance,
preventing state leakage that occurred with the previous while-True restart loop pattern.

Key concepts:
- ComponentLifecycleManager: Persistent manager that handles restart policy and backoff
- RestartableComponent: Base class for ephemeral component instances (one per lifetime)
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

    Key principles:
    - Each instance represents a single process lifetime
    - State is initialized fresh in _initialize_fresh_state()
    - run_single_lifetime() runs until crash or termination
    - Instance is garbage collected after termination (state cannot leak!)
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 component_type: str, lifetime_id: int):
        """
        Initialize component instance for a single lifetime.

        Args:
            env: SimPy environment
            component_id: Persistent component identifier (e.g., "pod_1")
            component_type: Type of component (Pod, Database, etc.)
            lifetime_id: Which lifetime this is (0 = first start, 1 = first restart, etc.)
        """
        self.env = env
        self.component_id = component_id  # Persistent ID across lifetimes
        self.lifetime_id = lifetime_id    # Which incarnation (0, 1, 2, ...)
        self.component_type = component_type

        # Full ID includes lifetime for debugging
        self.instance_id = f"{component_id}_L{lifetime_id}"

        # Let subclass initialize its fresh state
        self._initialize_fresh_state()

    @abstractmethod
    def _initialize_fresh_state(self):
        """
        Initialize all mutable state for this lifetime.

        This method MUST initialize ALL state variables to their starting values.
        This is called once during __init__ and never again.

        Example:
            self.thread_pool = simpy.Resource(self.env, capacity=50)
            self.request_count = 0
            self.active_processes = set()
            self.cpu_samples = []

        CRITICAL: Every mutable state variable must be initialized here.
        If you add new state later, add it here!
        """
        pass

    @abstractmethod
    def run_single_lifetime(self):
        """
        Run component for a single lifetime (until crash or termination).

        This is a SimPy generator that runs until:
        - Interrupted with crash cause (e.g., "OOMKilled", "CRASHED")
        - Interrupted with "TERMINATED" cause (permanent stop)
        - Completes naturally (rare)

        Returns control to ComponentLifecycleManager when done.

        Example:
            # Startup phase
            self.state = "STARTING"
            yield self.env.timeout(startup_delay)

            # Running phase
            self.state = "RUNNING"
            self.env.process(self._background_task())

            # Wait until interrupted
            try:
                yield self.env.timeout(float('inf'))
            except simpy.Interrupt:
                raise  # Let lifecycle manager handle it
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
                'parent_service': self.parent_service,
                'compute_node': self.compute_node,
                'thread_pool_size': self.thread_pool_size,
            }

        DO NOT include:
        - Counters (request_count, etc.)
        - Resource pools (thread_pool, connection_pool)
        - Active processes
        - Metrics samples
        """
        pass


class ComponentLifecycleManager:
    """
    Manages the lifecycle of a restartable component.

    This is the PERSISTENT manager that survives across restarts.
    It creates fresh RestartableComponent instances on each restart.

    Responsibilities:
    - Restart policy enforcement (max_restarts, backoff delays)
    - Creating fresh component instances
    - Tracking lifetime count and restart count
    - Notifying listeners of lifecycle events
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
                {
                    'max_restarts': int or None (None = unlimited),
                    'backoff_base_seconds': float,
                    'backoff_max_seconds': float,
                    'backoff_jitter_range': [min, max],
                }
        """
        self.env = env
        self.component_id = component_id
        self.component_type = component_type
        self.component_class = component_class
        self.persistent_config = persistent_config

        # Restart policy with sensible defaults
        self.restart_policy = restart_policy or {
            'max_restarts': None,  # None = unlimited
            'backoff_base_seconds': 10.0,
            'backoff_max_seconds': 300.0,
            'backoff_jitter_range': [-2, 5],
        }

        # Lifecycle tracking
        self.lifetime_count = 0  # How many lifetimes (0 = first start)
        self.total_restarts = 0  # How many restarts (lifetime_count - 1)
        self.current_instance: Optional[RestartableComponent] = None
        self.current_process: Optional[simpy.Process] = None
        self.termination_requested = False

        # Lifecycle event callbacks
        self.on_instance_created: Optional[Callable[[RestartableComponent], None]] = None
        self.on_instance_terminated: Optional[Callable[[RestartableComponent], None]] = None
        self.on_restart: Optional[Callable[[int], None]] = None

    def run(self):
        """
        Main lifecycle loop - creates and manages component instances.

        This is a SimPy generator that runs forever (or until terminated).
        Creates fresh component instances on each iteration.
        """
        while not self.termination_requested:
            # Create NEW instance for this lifetime (fresh state!)
            try:
                self.current_instance = self.component_class(
                    env=self.env,
                    component_id=self.component_id,
                    component_type=self.component_type,
                    lifetime_id=self.lifetime_count,
                    **self.persistent_config  # Pass persistent config
                )
            except Exception as e:
                print(f"ERROR: Failed to create {self.component_type} {self.component_id}: {e}")
                break

            # Notify listeners
            if self.on_instance_created:
                try:
                    self.on_instance_created(self.current_instance)
                except Exception as e:
                    print(f"WARNING: on_instance_created callback failed: {e}")

            try:
                # Run instance for single lifetime
                self.current_process = self.env.process(
                    self.current_instance.run_single_lifetime()
                )
                yield self.current_process

                # If we get here, instance completed naturally (rare)
                print(f"{self.component_type} {self.component_id} completed lifetime {self.lifetime_count}")
                break  # Exit lifecycle loop

            except simpy.Interrupt as interrupt:
                cause = interrupt.cause if hasattr(interrupt, 'cause') else "UNKNOWN"

                if cause in ["TERMINATED", "TERMINATED_FOR_DEPLOYMENT",
                             "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                    # Permanent termination requested
                    print(f"{self.component_type} {self.component_id} terminated at lifetime {self.lifetime_count}: {cause}")
                    break  # Exit lifecycle loop

                elif cause in ["CRASHED", "OOMKilled", "Error"]:
                    # Component crashed - prepare for restart
                    print(f"{self.component_type} {self.component_id} crashed at lifetime {self.lifetime_count}: {cause}")

                    self.total_restarts += 1

                    # Notify restart listeners
                    if self.on_restart:
                        try:
                            self.on_restart(self.total_restarts)
                        except Exception as e:
                            print(f"WARNING: on_restart callback failed: {e}")

                    # Check restart limit
                    max_restarts = self.restart_policy.get('max_restarts')
                    if max_restarts is not None and self.total_restarts >= max_restarts:
                        print(f"{self.component_type} {self.component_id} exceeded max restarts ({max_restarts})")
                        break  # Exit lifecycle loop

                    # Calculate backoff delay (exponential with jitter)
                    backoff_base = self.restart_policy['backoff_base_seconds']
                    backoff_max = self.restart_policy['backoff_max_seconds']
                    jitter_range = self.restart_policy['backoff_jitter_range']

                    backoff = min(backoff_base * (2 ** (self.total_restarts - 1)), backoff_max)
                    jitter = random.uniform(jitter_range[0], jitter_range[1])
                    delay = max(0, backoff + jitter)  # Ensure non-negative

                    print(f"{self.component_type} {self.component_id} waiting {delay:.1f}s before restart #{self.total_restarts + 1}")

                    # Wait for backoff
                    try:
                        yield self.env.timeout(delay)
                    except simpy.Interrupt as backoff_interrupt:
                        # Handle interrupt during backoff (e.g., termination)
                        backoff_cause = backoff_interrupt.cause if hasattr(backoff_interrupt, 'cause') else "UNKNOWN"
                        if backoff_cause in ["TERMINATED", "TERMINATED_FOR_DEPLOYMENT",
                                            "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                            print(f"{self.component_type} {self.component_id} terminated during backoff")
                            break  # Exit lifecycle loop
                        else:
                            print(f"WARNING: Unexpected interrupt during backoff: {backoff_cause}")
                            break

                    # Notify listeners that instance is being terminated
                    if self.on_instance_terminated and self.current_instance:
                        try:
                            self.on_instance_terminated(self.current_instance)
                        except Exception as e:
                            print(f"WARNING: on_instance_terminated callback failed: {e}")

                    # Instance object goes out of scope here and will be garbage collected
                    # ALL its state is destroyed! Cannot leak!
                    self.current_instance = None
                    self.current_process = None

                    # Increment lifetime counter
                    self.lifetime_count += 1

                    # Continue to next iteration (create new instance)

                else:
                    # Unknown interrupt cause
                    print(f"{self.component_type} {self.component_id} received unknown interrupt: {cause}")
                    break  # Exit lifecycle loop

            except Exception as e:
                # Unexpected exception
                print(f"ERROR: {self.component_type} {self.component_id} failed with exception: {e}")
                import traceback
                traceback.print_exc()
                break

            finally:
                # Cleanup current instance reference
                if self.on_instance_terminated and self.current_instance:
                    try:
                        self.on_instance_terminated(self.current_instance)
                    except Exception as e:
                        print(f"WARNING: on_instance_terminated callback in finally failed: {e}")

                self.current_instance = None
                self.current_process = None

        print(f"{self.component_type} {self.component_id} lifecycle ended (total restarts: {self.total_restarts})")

    def terminate(self):
        """
        Request termination of the component (graceful shutdown).

        This sets the termination flag and interrupts the current instance if running.
        """
        self.termination_requested = True
        if self.current_process and self.current_process.is_alive:
            try:
                self.current_process.interrupt("TERMINATED")
            except RuntimeError:
                pass  # Process already finished

    def trigger_crash(self, cause: str = "CRASHED"):
        """
        Trigger a crash of the current instance.

        Args:
            cause: Crash reason (e.g., "OOMKilled", "CRASHED")
        """
        if self.current_process and self.current_process.is_alive:
            try:
                self.current_process.interrupt(cause)
            except RuntimeError:
                pass  # Process already finished
