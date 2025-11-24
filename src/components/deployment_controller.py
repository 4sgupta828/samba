"""
Deployment Controller - Centralized pod lifecycle orchestrator.

The DeploymentController:
- Monitors all services and maintains desired replica counts
- Detects terminated/crashed pods and creates replacements
- Performs global resource-aware scheduling across compute nodes
- Rate-limits pod creation to prevent thundering herd
- Prevents cascading failures through smart placement
"""
from .base_component import EnrichedComponent
from .pod import Pod
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
        # Count healthy pods (RUNNING or STARTING)
        healthy_pods = [p for p in service.pods
                       if p.state.operational in ["RUNNING", "STARTING"]]

        current_count = len(healthy_pods)
        desired_count = service.desired_replicas

        if current_count < desired_count:
            # Need to create replacement pods
            missing = desired_count - current_count
            self._emit_log("INFO",
                f"Service {service.service_name}: {current_count}/{desired_count} pods, "
                f"creating {missing} replacements")

            # Add to pending queue (don't create immediately)
            for _ in range(missing):
                self.pending_creations.append(service)

        elif current_count > desired_count:
            # Need to scale down (user changed desired_replicas)
            excess = current_count - desired_count
            self._emit_log("INFO",
                f"Service {service.service_name}: Scaling down by {excess} pods")
            self._scale_down_service(service, excess)

    def _process_pending_creations(self):
        """Create pods from pending queue with rate limiting."""
        if not self.pending_creations:
            return

        # Process up to max_pods_per_cycle
        to_create = self.pending_creations[:self.max_pods_per_cycle]
        self.pending_creations = self.pending_creations[self.max_pods_per_cycle:]

        for service in to_create:
            # Create pod with smart node placement
            new_pod = self._create_pod_for_service(service)
            if new_pod:
                service.pods.append(new_pod)
                self.env.process(new_pod.run())

                self.pod_creation_counter.add(1, {
                    "component.id": self.id,
                    "service.name": service.service_name,
                    "sim.time": self.env.now
                })

                # Track pod creation event
                if self.topology_exporter and hasattr(self, 'event_tracker'):
                    self.event_tracker.track_pod_created(
                        new_pod,
                        service,
                        new_pod.compute_node
                    )

                # Small delay between pod creations
                yield self.env.timeout(0.1)

    def _create_pod_for_service(self, service):
        """Create a new pod with smart node placement."""
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

        # Generate unique pod ID
        pod_id = f"pod_{service.service_name}_{self.env.now:.0f}_{id(service) % 1000}"

        new_pod = Pod(
            env=self.env,
            component_id=pod_id,
            parent_service=service,
            compute_node=target_node
        )

        self._emit_log("INFO",
            f"Created pod {pod_id} for service {service.service_name} "
            f"on node {target_node.id}")

        return new_pod

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
        """Scale down service by terminating excess pods."""
        # Pick pods to terminate (prefer least recently started)
        pods_to_terminate = sorted(service.pods,
                                   key=lambda p: getattr(p, 'start_time', 0))[:count]

        for pod in pods_to_terminate:
            self._emit_log("INFO", f"Terminating pod {pod.id} (scale down)")
            pod.state.operational = "TERMINATED"

            if hasattr(pod, 'running_process') and pod.running_process:
                pod.running_process.interrupt("TERMINATED_BY_SCALE_DOWN")

            # Track termination event
            if self.topology_exporter and hasattr(self, 'event_tracker'):
                self.event_tracker.track_pod_terminated(pod, "SCALE_DOWN")

            # Remove from node
            if pod.compute_node and pod in pod.compute_node.pods:
                pod.compute_node.pods.remove(pod)

            # Remove from service
            service.pods.remove(pod)

            self.pod_termination_counter.add(1, {
                "component.id": self.id,
                "service.name": service.service_name,
                "reason": "scale_down",
                "sim.time": self.env.now
            })
