"""
Deployment Controller - Centralized pod lifecycle orchestrator.

The DeploymentController:
- Monitors all services and maintains desired replica counts
- Detects terminated/crashed pods and creates replacements
- Performs global resource-aware scheduling across compute nodes
- Rate-limits pod creation to prevent thundering herd
- Prevents cascading failures through smart placement

NEW: Uses ComponentLifecycleManager pattern for proper state isolation on pod restarts.
"""
from .base_component import EnrichedComponent
from .pod import Pod
from .pod_restartable import RestartablePod
from .lifecycle import ComponentLifecycleManager
from src.core.simulation_config import get_simulation_config
import simpy
import random


class DeploymentController(EnrichedComponent):
    """
    Centralized pod lifecycle manager (like kube-controller-manager).

    Maintains desired replica counts for all services with global
    knowledge of cluster resources to prevent cascading failures.
    """

    def __init__(self, env: simpy.Environment, component_id="deployment_controller",
                 topology_exporter=None):
        super().__init__(env, component_id, "DeploymentController")

        self.services = []  # All services to monitor
        self.compute_nodes = []  # All available compute nodes

        # Rate limiting to prevent thundering herd
        self.max_pods_per_cycle = 3  # Max pods to create per reconciliation
        self.pending_creations = []  # Queue of pending pod creations

        # Topology state tracking (optional)
        self.topology_exporter = topology_exporter
        if self.topology_exporter:
            from src.telemetry.topology_state_exporter import TopologyEventTracker
            self.event_tracker = TopologyEventTracker(topology_exporter)

        # Metrics
        self.reconciliation_counter = self.meter.create_counter(
            "deployment_controller.reconciliations",
            description="Number of reconciliation loops completed",
            unit="1"
        )
        self.pod_creation_counter = self.meter.create_counter(
            "deployment_controller.pods.created",
            description="Number of pods created",
            unit="1"
        )
        self.pod_termination_counter = self.meter.create_counter(
            "deployment_controller.pods.terminated",
            description="Number of pods terminated",
            unit="1"
        )
        self.scheduling_failure_counter = self.meter.create_counter(
            "deployment_controller.scheduling.failures",
            description="Number of pod scheduling failures",
            unit="1"
        )

    def register_service(self, service):
        """Register a service for monitoring."""
        self.services.append(service)
        self._emit_log("INFO", f"Registered service {service.service_name} for monitoring")

    def register_node(self, node):
        """Register a compute node for scheduling."""
        self.compute_nodes.append(node)
        self._emit_log("INFO", f"Registered compute node {node.id}")

    def run(self):
        """Main reconciliation loop."""
        self._emit_log("INFO", "DeploymentController started")

        while True:
            yield self.env.timeout(5.0)  # Reconcile every 5 simulation seconds

            # Reconcile each service
            for service in self.services:
                self._reconcile_service(service)

            # Process pending pod creations (rate-limited)
            yield from self._process_pending_creations()

            # Record reconciliation
            self.reconciliation_counter.add(1, {
                "component.id": self.id,
                "sim.time": self.env.now
            })

    def _reconcile_service(self, service):
        """Ensure service has desired replica count."""
        # Count active pod managers (which track healthy pods)
        # A pod_manager is considered active if it hasn't exceeded max_restarts
        active_managers = len(service.pod_managers)

        # Also count healthy pods for logging
        healthy_pods = [p for p in service.pods
                       if p.state.operational in ["RUNNING", "STARTING"]]

        current_count = active_managers
        desired_count = service.desired_replicas

        if current_count < desired_count:
            # Need to create replacement pods
            missing = desired_count - current_count
            self._emit_log("INFO",
                f"Service {service.service_name}: {current_count}/{desired_count} managers "
                f"({len(healthy_pods)} healthy pods), creating {missing} replacements")

            # Add to pending queue (don't create immediately)
            for _ in range(missing):
                self.pending_creations.append(service)

        elif current_count > desired_count:
            # Need to scale down (user changed desired_replicas)
            excess = current_count - desired_count
            self._emit_log("INFO",
                f"Service {service.service_name}: Scaling down by {excess} pod managers")
            self._scale_down_service(service, excess)

    def _process_pending_creations(self):
        """Create pod lifecycle managers from pending queue with rate limiting."""
        if not self.pending_creations:
            return

        # Process up to max_pods_per_cycle
        to_create = self.pending_creations[:self.max_pods_per_cycle]
        self.pending_creations = self.pending_creations[self.max_pods_per_cycle:]

        for service in to_create:
            # Create pod lifecycle manager with smart node placement
            pod_manager = self._create_pod_manager_for_service(service)
            if pod_manager:
                service.pod_managers.append(pod_manager)
                self.env.process(pod_manager.run())

                self.pod_creation_counter.add(1, {
                    "component.id": self.id,
                    "service.name": service.service_name,
                    "sim.time": self.env.now
                })

                # Track pod creation event (for first instance)
                # Note: subsequent restarts will also trigger this via callback
                if self.topology_exporter and hasattr(self, 'event_tracker'):
                    # Wait for first instance to be created
                    # The callback will handle tracking
                    pass

                # Small delay between pod creations
                yield self.env.timeout(0.1)

    def _create_pod_manager_for_service(self, service):
        """Create a new pod lifecycle manager with smart node placement."""
        # Pick best node using global knowledge
        target_node = self._schedule_pod()

        if not target_node:
            self._emit_log("ERROR",
                f"No available nodes for service {service.service_name}! "
                f"Cluster may be overloaded.")

            self.scheduling_failure_counter.add(1, {
                "component.id": self.id,
                "service.name": service.service_name,
                "reason": "no_available_nodes",
                "sim.time": self.env.now
            })
            return None

        # Generate unique pod ID (persistent across restarts)
        pod_id = f"pod_{service.service_name}_{self.env.now:.0f}_{id(service) % 1000}"

        # Get restart policy from config
        config = get_simulation_config().compute
        restart_policy = {
            'max_restarts': None,  # Unlimited restarts
            'backoff_base_seconds': config.startup_backoff_delay_base_seconds,
            'backoff_max_seconds': config.startup_max_backoff_seconds,
            'backoff_jitter_range': config.startup_backoff_jitter_range_seconds,
        }

        # Create lifecycle manager
        pod_manager = ComponentLifecycleManager(
            env=self.env,
            component_id=pod_id,
            component_type="Pod",
            component_class=RestartablePod,
            persistent_config={
                'parent_service': service,
                'compute_node': target_node,
            },
            restart_policy=restart_policy
        )

        # Set up callbacks to update service.pods list
        def on_pod_created(pod_instance):
            """Called when new pod instance is created (initial or restart)."""
            service.pods.append(pod_instance)
            # Initialize request metrics
            if hasattr(pod_instance, '_initialize_request_metrics'):
                pod_instance._initialize_request_metrics()
            self._emit_log("INFO",
                f"Pod instance {pod_instance.instance_id} created for {service.service_name} "
                f"on node {target_node.id}")

            # Track topology event
            if self.topology_exporter and hasattr(self, 'event_tracker'):
                self.event_tracker.track_pod_created(
                    pod_instance,
                    service,
                    target_node
                )

        def on_pod_terminated(pod_instance):
            """Called when pod instance is terminated (crash or permanent shutdown)."""
            if pod_instance in service.pods:
                service.pods.remove(pod_instance)
            self._emit_log("INFO",
                f"Pod instance {pod_instance.instance_id} terminated")

            # Track topology event
            if self.topology_exporter and hasattr(self, 'event_tracker'):
                self.event_tracker.track_pod_terminated(pod_instance, "LIFECYCLE_END")

        def on_restart(total_restarts, cause):
            """Called when pod restarts (after crash, before creating new instance)."""
            self._emit_log("INFO",
                f"Pod {pod_id} restarting (restart #{total_restarts}, cause: {cause})")

        pod_manager.on_instance_created = on_pod_created
        pod_manager.on_instance_terminated = on_pod_terminated
        pod_manager.on_restart = on_restart

        self._emit_log("INFO",
            f"Created pod lifecycle manager {pod_id} for service {service.service_name} "
            f"on node {target_node.id}")

        return pod_manager

    def _schedule_pod(self):
        """
        Smart pod scheduling with global resource awareness.

        Returns the best node to place a new pod, or None if cluster is full.

        Scheduling strategy:
        1. Filter out nodes that are overloaded or failing
        2. Score nodes by utilization (prefer least loaded)
        3. Return node with lowest utilization
        """
        # 1. Filter out nodes that are overloaded or failing
        available_nodes = [n for n in self.compute_nodes
                          if n.state.operational == "RUNNING"
                          and n.can_accept_work()]

        if not available_nodes:
            self._emit_log("WARN", "No available nodes! Cluster at capacity.")
            return None

        # 2. Score nodes by utilization (lower is better)
        node_scores = []
        for node in available_nodes:
            cpu_util = node.get_total_pod_cpu() / (node.cpu_cores * 100)
            memory_util = node.get_total_pod_memory() / (node.memory_gb * 1024)

            # Combined score (0.0 = empty, 1.0 = full)
            score = (cpu_util + memory_util) / 2.0
            node_scores.append((node, score))

        # 3. Sort by score (pick least loaded)
        node_scores.sort(key=lambda x: x[1])

        best_node = node_scores[0][0]
        best_score = node_scores[0][1]

        self._emit_log("DEBUG",
            f"Selected node {best_node.id} with utilization {best_score*100:.1f}%")

        return best_node

    def _scale_down_service(self, service, count):
        """Scale down service by terminating excess pod managers."""
        # Pick pod managers to terminate (prefer least recently started)
        # This will permanently stop the lifecycle managers
        managers_to_terminate = service.pod_managers[:count]

        for manager in managers_to_terminate:
            self._emit_log("INFO", f"Terminating pod manager {manager.component_id} (scale down)")

            # Remove from service's manager list
            service.pod_managers.remove(manager)

            # Terminate the lifecycle manager (will interrupt current pod and stop creating new ones)
            manager.terminate()

            # The on_pod_terminated callback will handle removing the pod instance from service.pods
            # and tracking the termination event

            self.pod_termination_counter.add(1, {
                "component.id": self.id,
                "service.name": service.service_name,
                "reason": "scale_down",
                "sim.time": self.env.now
            })
