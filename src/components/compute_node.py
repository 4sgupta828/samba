"""
Compute Node Component - Physical/VM layer that hosts multiple pods.

A Compute Node:
- Represents physical or virtual machine resources
- Hosts multiple pods with finite resources (CPU, memory, network)
- Enables realistic noisy neighbor scenarios and resource contention
- Tracks node-level metrics aggregated from pods
"""
from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
import simpy


class ComputeNode(EnrichedComponent):
    """
    ComputeNode represents a physical or virtual machine that hosts multiple pods.

    Provides:
    - Finite resources (CPU cores, memory GB, network bandwidth)
    - Resource contention between co-located pods
    - Node-level failures affecting all pods
    - Node-level metrics aggregation
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 cpu_cores=8, memory_gb=32, network_bandwidth_gbps=10):
        super().__init__(env, component_id, "ComputeNode")

        # Node capacity
        self.cpu_cores = cpu_cores
        self.memory_gb = memory_gb
        self.network_bandwidth_gbps = network_bandwidth_gbps

        # Pods running on this node
        self.pods = []  # List of Pod objects

        # Load contention configuration from centralized config
        config = get_simulation_config().compute.contention
        self.contention_config = {
            'cpu_threshold': config.cpu_threshold,
            'base_penalty_ms': config.base_penalty_ms,
            'sensitivity': config.sensitivity,
        }

        # Node-level metrics
        self.node_cpu_metric = self.meter.create_observable_gauge(
            "node.cpu.utilization",
            callbacks=[self._report_node_cpu],
            unit="%",
            description="Total CPU utilization across all pods on this node"
        )
        self.node_memory_metric = self.meter.create_observable_gauge(
            "node.memory.usage_gb",
            callbacks=[self._report_node_memory],
            unit="GB",
            description="Total memory usage across all pods on this node"
        )
        self.node_pod_count_metric = self.meter.create_observable_gauge(
            "node.pods.count",
            callbacks=[self._report_pod_count],
            description="Number of running pods on this node"
        )

    def register_pod(self, pod):
        """Register a pod to this node."""
        if pod not in self.pods:
            self.pods.append(pod)
            self._emit_log("INFO", f"Registered pod {pod.id}")

    def unregister_pod(self, pod):
        """Unregister a pod from this node."""
        if pod in self.pods:
            self.pods.remove(pod)
            self._emit_log("INFO", f"Unregistered pod {pod.id}")

    def can_accept_work(self):
        """
        Check if node has capacity for more work.

        Returns:
            bool: True if node can accept work, False if overloaded
        """
        total_cpu = self.get_total_pod_cpu()
        total_memory = self.get_total_pod_memory()

        # If total usage exceeds capacity, node is overloaded
        if total_cpu > (self.cpu_cores * 100):  # 100% per core
            return False
        if total_memory > (self.memory_gb * 1024):  # Convert to MB
            return False
        return True

    def get_total_pod_cpu(self):
        """
        Sum CPU usage across all running pods.

        Returns:
            float: Total CPU percentage across all pods
        """
        total = 0
        for pod in self.pods:
            if pod.state.operational == "RUNNING":
                total += pod.dynamics.get_cpu_percent()
        return total

    def get_total_pod_memory(self):
        """
        Sum memory usage across all running pods.

        Returns:
            float: Total memory in MB across all pods
        """
        total = 0
        for pod in self.pods:
            if pod.state.operational == "RUNNING":
                total += pod.dynamics.get_memory()
        return total

    def get_running_pods(self):
        """
        Get list of running pods.

        Returns:
            list: List of pods with operational state "RUNNING"
        """
        return [p for p in self.pods if p.state.operational == "RUNNING"]

    def get_utilization(self):
        """
        Calculate node utilization (0.0 to 1.0).

        Returns:
            tuple: (cpu_utilization, memory_utilization) where 0.0 = empty, 1.0 = full
        """
        cpu_util = self.get_total_pod_cpu() / (self.cpu_cores * 100)
        memory_util = self.get_total_pod_memory() / (self.memory_gb * 1024)
        return cpu_util, memory_util

    def get_contention_penalty(self):
        """
        Calculate CPU steal time penalty based on node-level resource contention.

        When total CPU utilization exceeds threshold (default 90%), pods experience
        CPU steal time where the OS scheduler cannot give them CPU slices.

        Returns:
            float: Penalty in milliseconds (0 if below threshold)

        Formula:
            penalty_ms = base_penalty * exp((util - threshold) * sensitivity)

        Examples:
            At 95% util: ~50ms penalty
            At 99% util: ~500ms penalty
        """
        import math

        cpu_util, _ = self.get_utilization()

        # Below threshold - no contention
        if cpu_util < self.contention_config['cpu_threshold']:
            return 0.0

        # Calculate exponential steal time penalty
        excess = cpu_util - self.contention_config['cpu_threshold']
        base = self.contention_config['base_penalty_ms']
        sensitivity = self.contention_config['sensitivity']

        penalty_ms = base * math.exp(excess * sensitivity)

        return penalty_ms

    def _report_node_cpu(self, options):
        """Report total CPU utilization across all pods."""
        from opentelemetry.metrics import Observation

        total_cpu = self.get_total_pod_cpu()
        # Normalize to percentage (0-100%)
        cpu_percent = min(total_cpu, 100.0)

        yield Observation(cpu_percent, {
            "node.id": self.id,
            "node.cpu_cores": self.cpu_cores,
            "sim.time": self.env.now
        })

    def _report_node_memory(self, options):
        """Report total memory usage across all pods."""
        from opentelemetry.metrics import Observation

        total_memory_mb = self.get_total_pod_memory()
        memory_gb = total_memory_mb / 1024.0

        yield Observation(memory_gb, {
            "node.id": self.id,
            "node.memory_gb": self.memory_gb,
            "sim.time": self.env.now
        })

    def _report_pod_count(self, options):
        """Report number of running pods."""
        from opentelemetry.metrics import Observation

        running_count = len(self.get_running_pods())

        yield Observation(running_count, {
            "node.id": self.id,
            "sim.time": self.env.now
        })

    def run(self):
        """Node monitoring and health check background process."""
        # Set node to RUNNING state immediately
        self.state.operational = "RUNNING"
        self._emit_log("INFO", f"ComputeNode started with {self.cpu_cores} cores, {self.memory_gb}GB memory")

        while True:
            yield self.env.timeout(5.0)  # Check every 5 simulation seconds

            # Check for node overload
            total_cpu = self.get_total_pod_cpu()
            total_memory = self.get_total_pod_memory()

            if total_cpu > (self.cpu_cores * 100):
                self._emit_log("WARN", f"Node CPU overload: {total_cpu:.1f}% (capacity: {self.cpu_cores * 100}%)")

            if total_memory > (self.memory_gb * 1024):
                self._emit_log("WARN", f"Node memory overload: {total_memory:.1f}MB (capacity: {self.memory_gb * 1024}MB)")
                # Trigger OOMKiller when node memory is exceeded
                self._trigger_oom_killer()

    def _trigger_oom_killer(self):
        """
        Kill the pod using most memory (Linux OOMKiller simulation).

        This simulates the kernel's Out-Of-Memory killer which terminates
        processes when the system runs out of memory.
        """
        if not self.pods:
            return

        # Find pod with highest memory usage
        victim = max(self.pods,
                    key=lambda p: p.dynamics.get_memory() if p.state.operational == "RUNNING" else 0,
                    default=None)

        if victim and victim.state.operational == "RUNNING":
            self._emit_log("ERROR",
                f"OOMKiller: Terminating {victim.id} "
                f"(memory: {victim.dynamics.get_memory():.1f}MB)")

            victim.state.operational = "TERMINATED"

            # Interrupt the pod process - the pod will remove itself from the node's pod list
            if hasattr(victim, 'running_process') and victim.running_process:
                victim.running_process.interrupt("TERMINATED_BY_OOMKILLER")

            # DeploymentController will detect missing pod and reschedule
