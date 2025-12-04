"""
Topology State Exporter - Captures dynamic Service/Pod/Node mappings over time.

This exporter tracks the evolving state of the cluster:
- Service → Pod mappings (which pods belong to which service)
- Pod → Node placement (which pods run on which nodes)
- Pod lifecycle events (created, terminated, rescheduled)

Output format: JSONL with timestamped snapshots for temporal analysis.
"""
import json
from pathlib import Path
from typing import Dict, List, Any
import simpy


class TopologyStateExporter:
    """
    Exports dynamic topology state for temporal analysis.

    Captures:
    1. Service → Pod mappings
    2. Pod → Node placement
    3. Pod lifecycle events
    4. Node resource utilization
    """

    def __init__(self, env: simpy.Environment, output_dir: str):
        """
        Initialize the topology state exporter.

        Exports state snapshots only on changes (event-driven):
        - Initial state
        - Pod created/terminated/rescheduled
        - Final state

        Args:
            env: SimPy environment
            output_dir: Directory to write topology state files
        """
        self.env = env
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track components
        self.services = []
        self.pods = []
        self.nodes = []
        self.controller = None

        # Output file (single file with snapshots on changes)
        self.topology_state_file = self.output_dir / "topology_state.jsonl"

        # Initialize file
        self.topology_state_file.write_text("")  # Clear file

        # Track snapshot count
        self.snapshot_count = 0
        self.initial_exported = False

    def register_service(self, service):
        """Register a service for tracking."""
        self.services.append(service)

    def register_pod(self, pod):
        """Register a pod for tracking."""
        self.pods.append(pod)

    def register_node(self, node):
        """Register a compute node for tracking."""
        self.nodes.append(node)

    def register_controller(self, controller):
        """Register the deployment controller."""
        self.controller = controller

    def export_initial_state(self):
        """Export initial topology state (call after all components registered)."""
        if not self.initial_exported:
            self.export_snapshot(snapshot_type="initial", event="simulation_start")
            self.initial_exported = True

    def export_snapshot(self, snapshot_type: str = "change", event: str = None):
        """
        Export a complete topology state snapshot.

        Args:
            snapshot_type: Type of snapshot (initial, change, final)
            event: Event that triggered this snapshot (optional)
        """
        snapshot = {
            "timestamp": self.env.now,
            "snapshot_id": self.snapshot_count,
            "snapshot_type": snapshot_type,
            "event": event,  # What triggered this snapshot
            "services": self._get_service_states(),
            "pods": self._get_pod_states(),
            "nodes": self._get_node_states(),
            "mappings": self._get_mappings(),
            "cluster_stats": self._get_cluster_stats()
        }

        # Write to JSONL
        with open(self.topology_state_file, 'a') as f:
            f.write(json.dumps(snapshot) + '\n')

        self.snapshot_count += 1

    def _get_service_states(self) -> List[Dict[str, Any]]:
        """Get state of all services."""
        return [
            {
                "id": svc.id,
                "service_name": svc.service_name,
                "desired_replicas": svc.desired_replicas,
                "actual_replicas": len([p for p in svc.pods if p.state.operational == "RUNNING"]),
                "total_pods": len(svc.pods),
                "supported_request_types": svc.supported_request_types,
                "pipeline_steps": len(svc.processing_pipeline),
                "connections": {
                    k: v.id if hasattr(v, 'id') else str(v)
                    for k, v in svc.connections.items()
                }
            }
            for svc in self.services
        ]

    def _get_pod_states(self) -> List[Dict[str, Any]]:
        """Get state of all pods."""
        pod_states = []

        for pod in self.pods:
            state = {
                "id": pod.id,
                "operational_state": pod.state.operational,
                "restarts": pod.restarts,
                "parent_service": pod.parent_service.service_name if pod.parent_service else None,
                "parent_service_id": pod.parent_service.id if pod.parent_service else None,
                "compute_node": pod.compute_node.id if pod.compute_node else None,
                "start_time": getattr(pod, 'start_time', None),
                "age": self.env.now - getattr(pod, 'start_time', self.env.now),
            }

            # Add resource metrics if pod is running
            if pod.state.operational == "RUNNING":
                state["cpu_percent"] = pod.dynamics.get_cpu_percent()
                state["memory_mb"] = pod.dynamics.get_memory()
                state["thread_pool_active"] = pod.thread_pool.count
                state["thread_pool_queued"] = len(pod.thread_pool.queue)
                state["connection_pool_active"] = pod.db_connection_pool.count if pod.db_connection_pool else 0
                state["connection_pool_queued"] = len(pod.db_connection_pool.queue) if pod.db_connection_pool else 0

            pod_states.append(state)

        return pod_states

    def _get_node_states(self) -> List[Dict[str, Any]]:
        """Get state of all compute nodes."""
        return [
            {
                "id": node.id,
                "operational_state": node.state.operational,
                "cpu_cores": node.cpu_cores,
                "memory_gb": node.memory_gb,
                "network_bandwidth_gbps": node.network_bandwidth_gbps,
                "total_pods": len(node.pods),
                "running_pods": len(node.get_running_pods()),
                "total_cpu_percent": node.get_total_pod_cpu(),
                "total_memory_mb": node.get_total_pod_memory(),
                "cpu_utilization": node.get_total_pod_cpu() / (node.cpu_cores * 100),
                "memory_utilization": node.get_total_pod_memory() / (node.memory_gb * 1024),
                "can_accept_work": node.can_accept_work(),
                "pods": [p.id for p in node.pods]
            }
            for node in self.nodes
        ]

    def _get_mappings(self) -> Dict[str, Any]:
        """
        Get explicit Service → Pod → Node mappings.

        This is the key data structure for the GNN to understand topology.
        """
        mappings = {
            "service_to_pods": {},
            "pod_to_node": {},
            "node_to_pods": {},
            "pod_to_service": {}
        }

        # Service → Pods mapping
        for svc in self.services:
            mappings["service_to_pods"][svc.id] = [p.id for p in svc.pods]

        # Pod → Service and Pod → Node mappings
        for pod in self.pods:
            if pod.parent_service:
                mappings["pod_to_service"][pod.id] = pod.parent_service.id
            if pod.compute_node:
                mappings["pod_to_node"][pod.id] = pod.compute_node.id

        # Node → Pods mapping
        for node in self.nodes:
            mappings["node_to_pods"][node.id] = [p.id for p in node.pods]

        return mappings

    def _get_cluster_stats(self) -> Dict[str, Any]:
        """Get overall cluster statistics."""
        stats = {
            "total_services": len(self.services),
            "total_pods": len(self.pods),
            "total_nodes": len(self.nodes),
            "running_pods": sum(1 for p in self.pods if p.state.operational == "RUNNING"),
            "starting_pods": sum(1 for p in self.pods if p.state.operational == "STARTING"),
            "crashed_pods": sum(1 for p in self.pods if p.state.operational == "CRASHED"),
            "terminated_pods": sum(1 for p in self.pods if p.state.operational == "TERMINATED"),
        }

        # Node utilization stats
        if self.nodes:
            cpu_utils = [n.get_total_pod_cpu() / (n.cpu_cores * 100) for n in self.nodes]
            mem_utils = [n.get_total_pod_memory() / (n.memory_gb * 1024) for n in self.nodes]

            stats["cluster_cpu_utilization"] = {
                "mean": sum(cpu_utils) / len(cpu_utils),
                "max": max(cpu_utils),
                "min": min(cpu_utils)
            }
            stats["cluster_memory_utilization"] = {
                "mean": sum(mem_utils) / len(mem_utils),
                "max": max(mem_utils),
                "min": min(mem_utils)
            }

        # Controller stats
        if self.controller:
            stats["pending_pod_creations"] = len(self.controller.pending_creations)

        return stats

    def export_final_snapshot(self):
        """Export the final snapshot at end of simulation."""
        self.export_snapshot(snapshot_type="final", event="simulation_end")

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of exported data."""
        return {
            "total_snapshots": self.snapshot_count,
            "topology_state_file": str(self.topology_state_file)
        }


class TopologyEventTracker:
    """
    Wrapper to automatically track pod lifecycle events.

    Exports full topology snapshots on pod lifecycle changes.
    """

    def __init__(self, exporter: TopologyStateExporter):
        self.exporter = exporter

    def track_pod_created(self, pod, service, node):
        """Track pod creation event - export snapshot."""
        event_desc = f"pod_created:{pod.id}@{service.service_name}→{node.id}"
        self.exporter.export_snapshot(
            snapshot_type="change",
            event=event_desc
        )

    def track_pod_terminated(self, pod, reason):
        """Track pod termination event - export snapshot."""
        event_desc = f"pod_terminated:{pod.id}:{reason}"
        self.exporter.export_snapshot(
            snapshot_type="change",
            event=event_desc
        )

    def track_pod_rescheduled(self, pod, old_node, new_node):
        """Track pod rescheduling event - export snapshot."""
        event_desc = f"pod_rescheduled:{pod.id}:{old_node.id if old_node else 'None'}→{new_node.id}"
        self.exporter.export_snapshot(
            snapshot_type="change",
            event=event_desc
        )
