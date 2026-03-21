"""
Crash analysis for forensic investigations.

Analyzes crash events, recovery attempts, and crash loops.
"""

import pandas as pd
import networkx as nx
from typing import List, Optional, Dict
from .models import CrashEvent


class CrashAnalyzer:
    """Analyzes crash events and recovery."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        logs_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        topology_snapshots: List[Dict],
        fault_start_time: float
    ):
        self.metrics_df = metrics_df
        self.logs_df = logs_df
        self.topology_graph = topology_graph
        self.topology_snapshots = topology_snapshots
        self.fault_start_time = fault_start_time
        self.crashes: List[CrashEvent] = []

    def analyze_crashes(self) -> List[CrashEvent]:
        """Analyze all crash events and recovery attempts."""
        if self.logs_df.empty:
            return self.crashes

        oom_logs = self.logs_df[
            self.logs_df['message'].astype(str).str.contains('OOMKilled', na=False)
        ].copy()

        crashed_components = set()
        if not oom_logs.empty:
            crashed_components.update(oom_logs['component_id'].dropna().unique())

        for component_id in crashed_components:
            self._analyze_component_crashes(component_id)

        return self.crashes

    def _analyze_component_crashes(self, component_id: str):
        """Analyze crash history for a specific component."""
        oom_events = self.logs_df[
            (self.logs_df['component_id'] == component_id) &
            (self.logs_df['message'].astype(str).str.contains('OOMKilled', na=False))
        ].copy()

        if oom_events.empty:
            return

        oom_events = oom_events.sort_values('timestamp')

        first_crash_timestamp = oom_events.iloc[0]['timestamp']
        restart_attempts = len(oom_events)

        # Try to get metrics at crash time
        memory_at_crash = None
        cpu_at_crash = None
        threads_at_crash = None
        queue_at_crash = None

        component_metrics = self.metrics_df[
            self.metrics_df['component.id'] == component_id
        ]

        if not component_metrics.empty:
            late_metrics = component_metrics[component_metrics['sim.time'] >= 600]

            if not late_metrics.empty:
                mem_data = late_metrics[late_metrics['name'] == 'container.memory.usage_mb']
                if not mem_data.empty:
                    memory_at_crash = mem_data['value'].max()

                cpu_data = late_metrics[late_metrics['name'] == 'container.cpu.utilization']
                if not cpu_data.empty:
                    cpu_at_crash = cpu_data['value'].max()

                thread_data = late_metrics[late_metrics['name'] == 'thread_pool.threads.active']
                if not thread_data.empty:
                    threads_at_crash = thread_data['value'].max()

                queue_data = late_metrics[late_metrics['name'] == 'thread_pool.queue.depth']
                if not queue_data.empty:
                    queue_at_crash = queue_data['value'].max()

        estimated_crash_time = self.fault_start_time + 400

        # Check if recovered
        final_snapshot = self.topology_snapshots[-1] if self.topology_snapshots else None
        recovered = False
        recovery_time = None

        if final_snapshot:
            pod_states = {p['id']: p for p in final_snapshot.get('pods', [])}
            if component_id in pod_states:
                recovered = pod_states[component_id]['operational_state'] == 'RUNNING'

        crash_loop = restart_attempts >= 3

        crash_reason = self._determine_crash_reason(
            memory_at_crash, cpu_at_crash, threads_at_crash, queue_at_crash
        )

        self.crashes.append(CrashEvent(
            component_id=component_id,
            component_type=self._get_component_type(component_id),
            crash_time=estimated_crash_time,
            crash_reason=crash_reason,
            memory_at_crash=memory_at_crash,
            cpu_at_crash=cpu_at_crash,
            thread_pool_at_crash=threads_at_crash,
            queue_depth_at_crash=queue_at_crash,
            restart_attempts=restart_attempts,
            recovery_time=recovery_time,
            recovered=recovered,
            crash_loop_detected=crash_loop
        ))

    def _determine_crash_reason(
        self,
        memory: Optional[float],
        cpu: Optional[float],
        threads: Optional[int],
        queue: Optional[int]
    ) -> str:
        """Determine the primary reason for crash."""
        reasons = []

        if memory and memory > 512:
            reasons.append(f"OOM: Memory exceeded limit ({memory:.0f}MB > 512MB)")

        if cpu and cpu >= 100:
            reasons.append("CPU: 100% saturation")

        if threads and threads >= 50:
            reasons.append("Thread pool: Fully saturated (50/50)")

        if queue and queue > 1000:
            reasons.append(f"Request backlog: {int(queue)} queued requests")

        if not reasons:
            return "Unknown"

        return " + ".join(reasons)

    def _get_component_type(self, component_id: str) -> str:
        """Get component type from topology."""
        if component_id in self.topology_graph:
            return self.topology_graph.nodes[component_id].get('type', 'Unknown')
        return 'Unknown'
