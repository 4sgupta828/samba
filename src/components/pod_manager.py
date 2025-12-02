"""
Pod Lifecycle Manager - Manages Pod instances with proper state isolation.

This module provides a lifecycle manager for Pods that creates fresh instances
on each restart, ensuring no state leakage between lifetimes.

This is a practical implementation that wraps the existing Pod class rather than
requiring a complete rewrite. It provides the benefits of the RestartableComponent
pattern while maintaining compatibility with existing code.

Usage:
    # Instead of:
    pod = Pod(env, "pod_1", parent_service=service)
    env.process(pod.run())

    # Use:
    pod_manager = PodLifecycleManager(
        env=env,
        component_id="pod_1",
        parent_service=service,
        compute_node=node
    )
    env.process(pod_manager.run())
"""

from .pod import Pod
from src.core.simulation_config import get_simulation_config
import simpy
import random


class PodLifecycleManager:
    """
    Manages the lifecycle of a Pod with proper state isolation.

    This manager creates fresh Pod instances on each restart, ensuring that
    state never leaks between lifetimes. It implements the ComponentLifecycleManager
    pattern specifically for Pods.

    Key benefits:
    - Fresh state on each restart (impossible to leak state)
    - Proper restart backoff and policy enforcement
    - Clear separation of lifecycle management and business logic
    - Maintains compatibility with existing Pod implementation
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 parent_service=None, compute_node=None,
                 restart_policy: dict = None):
        """
        Initialize Pod lifecycle manager.

        Args:
            env: SimPy environment
            component_id: Unique identifier for this pod (persists across restarts)
            parent_service: Reference to parent Service object
            compute_node: Reference to ComputeNode object (optional)
            restart_policy: Restart policy configuration (None = use defaults from config)
        """
        self.env = env
        self.component_id = component_id
        self.parent_service = parent_service
        self.compute_node = compute_node

        # Load restart policy from config if not provided
        config = get_simulation_config().compute
        if restart_policy is None:
            self.restart_policy = {
                'max_restarts': None,  # None = unlimited
                'backoff_base_seconds': config.startup_backoff_delay_base_seconds,
                'backoff_max_seconds': config.startup_max_backoff_seconds,
                'backoff_jitter_range': config.startup_backoff_jitter_range_seconds,
            }
        else:
            self.restart_policy = restart_policy

        # Lifecycle tracking
        self.lifetime_count = 0  # Number of lifetimes (including first start)
        self.total_restarts = 0  # Number of restarts (lifetime_count - 1)
        self.current_pod: Pod = None
        self.current_process: simpy.Process = None
        self.termination_requested = False

        # Callbacks for lifecycle events (for Service/DeploymentController integration)
        self.on_pod_created = None  # Called when new pod instance is created
        self.on_pod_terminated = None  # Called when pod instance is terminated
        self.on_restart = None  # Called when restart occurs (after crash, before backoff)

    def run(self):
        """
        Main lifecycle loop - creates and manages pod instances.

        This is a SimPy generator that runs until terminated.
        """
        while not self.termination_requested:
            # Create new Pod instance for this lifetime
            pod_id = f"{self.component_id}_L{self.lifetime_count}"

            self.current_pod = Pod(
                env=self.env,
                component_id=pod_id,
                parent_service=self.parent_service,
                compute_node=self.compute_node
            )

            # Initialize request metrics if parent service is set
            if self.parent_service:
                self.current_pod._initialize_request_metrics()

            # Notify listeners that new pod instance was created
            if self.on_pod_created:
                self.on_pod_created(self.current_pod)

            # Register with service's pod list
            if self.parent_service and hasattr(self.parent_service, 'pods'):
                self.parent_service.pods.append(self.current_pod)

            try:
                # Run pod for single lifetime
                self.current_process = self.env.process(self._run_pod_single_lifetime())
                yield self.current_process

                # If we get here, pod completed naturally (rare)
                print(f"[{self.env.now:.2f}] Pod {self.component_id} completed lifetime {self.lifetime_count}")
                break  # Exit lifecycle loop

            except simpy.Interrupt as interrupt:
                cause = interrupt.cause

                if cause in ["TERMINATED_FOR_DEPLOYMENT", "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                    # Permanent termination requested
                    print(f"[{self.env.now:.2f}] Pod {self.component_id} terminated: {cause}")
                    break  # Exit lifecycle loop

                elif cause == "OOMKilled":
                    # Pod crashed due to OOM - prepare for restart
                    print(f"[{self.env.now:.2f}] Pod {self.component_id} crashed (OOMKilled) at lifetime {self.lifetime_count}")

                    self.total_restarts += 1

                    # Notify restart listener
                    if self.on_restart:
                        self.on_restart(self.total_restarts, cause)

                    # Check restart limit
                    max_restarts = self.restart_policy['max_restarts']
                    if max_restarts is not None and self.total_restarts >= max_restarts:
                        print(f"[{self.env.now:.2f}] Pod {self.component_id} exceeded max restarts ({max_restarts})")
                        break  # Exit lifecycle loop

                    # Calculate backoff delay (exponential with jitter)
                    backoff_base = self.restart_policy['backoff_base_seconds']
                    backoff_max = self.restart_policy['backoff_max_seconds']
                    jitter_range = self.restart_policy['backoff_jitter_range']

                    backoff = min(backoff_base * (2 ** (self.total_restarts - 1)), backoff_max)
                    jitter = random.uniform(jitter_range[0], jitter_range[1])
                    delay = max(0, backoff + jitter)

                    print(f"[{self.env.now:.2f}] Pod {self.component_id} "
                          f"CrashLoopBackOff: waiting {delay:.1f}s before restart #{self.total_restarts + 1}")

                    # Cleanup old pod instance
                    yield from self._cleanup_pod_instance()

                    # Wait for backoff
                    try:
                        yield self.env.timeout(delay)
                    except simpy.Interrupt as backoff_interrupt:
                        # Interruption during backoff (e.g., deployment termination)
                        if backoff_interrupt.cause in ["TERMINATED_FOR_DEPLOYMENT", "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                            print(f"[{self.env.now:.2f}] Pod {self.component_id} terminated during backoff: {backoff_interrupt.cause}")
                            break  # Exit lifecycle loop
                        else:
                            raise  # Re-raise other interrupts

                    # Increment lifetime counter
                    self.lifetime_count += 1

                    # Continue to next iteration (create new pod instance)

                else:
                    # Unknown interrupt cause
                    print(f"[{self.env.now:.2f}] Pod {self.component_id} received unknown interrupt: {cause}")
                    break  # Exit lifecycle loop

            finally:
                # Final cleanup
                yield from self._cleanup_pod_instance()

        print(f"[{self.env.now:.2f}] Pod {self.component_id} lifecycle ended (total restarts: {self.total_restarts})")

    def _run_pod_single_lifetime(self):
        """
        Run pod for a single lifetime.

        This wraps the Pod's run() method but extracts just the single-lifetime logic
        by removing the while True loop that was in the original implementation.
        """
        config = get_simulation_config().compute

        # Mark as starting
        self.current_pod.state.operational = "STARTING"
        self.current_pod.restarts = self.lifetime_count + 1  # Track total restarts for metrics
        self.current_pod._emit_log("INFO", f"Starting (Lifetime #{self.lifetime_count}, Restart #{self.total_restarts})...")

        # Start background processes
        self.env.process(self.current_pod._sample_cpu_periodically())
        self.env.process(self.current_pod._monitor_oom())
        self.env.process(self.current_pod._update_dynamics_loop())

        # Start queue consumer if parent service has queue_in connection
        if self.parent_service and hasattr(self.parent_service, 'connections'):
            if 'queue_in' in self.parent_service.connections:
                self.env.process(self.current_pod._consume_from_queue())

        # Startup delay
        startup_delay = random.uniform(*config.startup_time_range_seconds)
        yield self.env.timeout(startup_delay)

        # Mark as running
        self.current_pod.state.operational = "RUNNING"
        self.current_pod._emit_log("INFO", f"Pod started successfully (Version: {self.current_pod.version}).")

        # Store reference to running process for interrupt
        self.current_pod.running_process = self.env.active_process

        try:
            # Pod is now running until it's interrupted
            yield self.env.timeout(float('inf'))
        except simpy.Interrupt as interrupt:
            # Pod interrupted - re-raise to lifecycle manager
            raise
        finally:
            self.current_pod.running_process = None

    def _cleanup_pod_instance(self):
        """
        Clean up the current pod instance.

        This ensures proper deregistration and garbage collection.
        """
        if not self.current_pod:
            return

        # Notify listeners
        if self.on_pod_terminated:
            self.on_pod_terminated(self.current_pod)

        # Remove from service's pod list
        if self.parent_service and hasattr(self.parent_service, 'pods'):
            if self.current_pod in self.parent_service.pods:
                self.parent_service.pods.remove(self.current_pod)

        # Remove from compute node if attached
        if self.compute_node and hasattr(self.compute_node, 'pods'):
            if self.current_pod in self.compute_node.pods:
                self.compute_node.pods.remove(self.current_pod)

        # Clear reference to allow garbage collection
        # The Python GC will destroy the Pod object and ALL its state
        self.current_pod = None
        self.current_process = None

        # Yield to allow any pending events to process
        yield self.env.timeout(0)

    def terminate(self):
        """
        Request permanent termination of the pod.

        This will interrupt the current pod instance and prevent any further restarts.
        """
        self.termination_requested = True
        if self.current_process and self.current_process.is_alive:
            try:
                self.current_process.interrupt("TERMINATED_FOR_DEPLOYMENT")
            except RuntimeError:
                pass  # Process already terminated

    def trigger_crash(self, cause: str = "OOMKilled"):
        """
        Trigger a crash of the current pod instance.

        This will interrupt the current pod with the specified cause,
        which will trigger the restart logic.

        Args:
            cause: Crash cause (OOMKilled, Error, etc.)
        """
        if self.current_pod and self.current_pod.running_process:
            try:
                self.current_pod.running_process.interrupt(cause)
            except RuntimeError:
                pass  # Process already terminated
