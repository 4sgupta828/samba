"""
Queue analysis for forensic investigations.

Analyzes message queue behavior and backlogs.
"""

import pandas as pd
import networkx as nx
from typing import List, Tuple
from .models import QueueAnalysis, CrashEvent


class QueueAnalyzer:
    """Analyzes message queue behavior."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        crashes: List[CrashEvent],
        fault_start_time: float,
        simulation_duration: float
    ):
        self.metrics_df = metrics_df
        self.topology_graph = topology_graph
        self.crashes = crashes
        self.fault_start_time = fault_start_time
        self.simulation_duration = simulation_duration
        self.queue_analyses: List[QueueAnalysis] = []

    def analyze_queues(self) -> List[QueueAnalysis]:
        """Analyze message queue behavior and backlogs."""
        queues = [n for n, d in self.topology_graph.nodes(data=True)
                 if d.get('role') == 'queue']

        for queue_id in queues:
            self._analyze_queue(queue_id)

        return self.queue_analyses

    def _analyze_queue(self, queue_id: str):
        """Analyze a specific message queue."""
        in_flight = self.metrics_df[
            (self.metrics_df['component.id'] == queue_id) &
            (self.metrics_df['name'] == 'mq.messages.in_flight')
        ].copy()

        if in_flight.empty:
            return

        in_flight = in_flight.sort_values('sim.time')

        # Calculate normal depth (before fault)
        normal_data = in_flight[in_flight['sim.time'] < self.fault_start_time]
        normal_depth = normal_data['value'].mean() if not normal_data.empty else 0

        # Peak depth
        peak_depth = in_flight['value'].max()

        # Depth at end
        end_data = in_flight[in_flight['sim.time'] >= self.simulation_duration - 10]
        depth_at_end = end_data['value'].mean() if not end_data.empty else in_flight.iloc[-1]['value']

        # Find when backlog started (depth > 2x normal)
        backlog_threshold = max(normal_depth * 2, 100)
        backlog_data = in_flight[in_flight['value'] > backlog_threshold]
        backlog_started = backlog_data.iloc[0]['sim.time'] if not backlog_data.empty else None

        # Check if cleared
        if backlog_started:
            after_backlog = in_flight[in_flight['sim.time'] > backlog_started]
            cleared = after_backlog[after_backlog['value'] <= backlog_threshold]
            backlog_cleared = cleared.iloc[0]['sim.time'] if not cleared.empty else None
        else:
            backlog_cleared = None

        # Find producers and consumers from topology
        producers = [e[0] for e in self.topology_graph.in_edges(queue_id)]
        consumers = [e[1] for e in self.topology_graph.out_edges(queue_id)]

        # Check for producer/consumer failures
        producer_failures: List[Tuple[str, float]] = []
        consumer_failures: List[Tuple[str, float]] = []

        for crash in self.crashes:
            if crash.component_id in consumers:
                consumer_failures.append((crash.component_id, crash.crash_time))

        # Determine cause
        if consumer_failures:
            backlog_cause = f"Consumer failures: {len(consumer_failures)} consumers crashed/degraded"
        elif peak_depth > normal_depth * 10:
            backlog_cause = "Massive increase in message production due to cascading failures"
        else:
            backlog_cause = "Unknown"

        # Can it recover?
        recovery_possible = len(consumer_failures) < len(consumers) or any(
            c.recovered for c in self.crashes if c.component_id in consumers
        )

        self.queue_analyses.append(QueueAnalysis(
            queue_id=queue_id,
            normal_depth=normal_depth,
            peak_depth=peak_depth,
            depth_at_end=depth_at_end,
            backlog_started=backlog_started,
            backlog_cleared=backlog_cleared,
            producers=producers,
            consumers=consumers,
            producer_failures=producer_failures,
            consumer_failures=consumer_failures,
            backlog_cause=backlog_cause,
            recovery_possible=recovery_possible
        ))
