"""
Health tracking and propagation analysis for forensic investigations.

Tracks system health over time and analyzes error/latency propagation.
"""

import numpy as np
import pandas as pd
import networkx as nx
from typing import List, Tuple
from .models import (
    SystemHealthSnapshot, HealthState, CrashEvent, BottleneckAnalysis,
    QueueAnalysis, CircuitBreakerEvent
)


class HealthTracker:
    """Tracks system health and propagation over time."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        simulation_duration: float,
        crashes: List[CrashEvent],
        bottlenecks: List[BottleneckAnalysis],
        queue_analyses: List[QueueAnalysis]
    ):
        self.metrics_df = metrics_df
        self.topology_graph = topology_graph
        self.simulation_duration = simulation_duration
        self.crashes = crashes
        self.bottlenecks = bottlenecks
        self.queue_analyses = queue_analyses
        self.health_timeline: List[SystemHealthSnapshot] = []
        self.circuit_breaker_events: List[CircuitBreakerEvent] = []

    def track_health_timeline(self) -> List[SystemHealthSnapshot]:
        """Track system health over time."""
        sample_interval = 30

        for t in range(0, int(self.simulation_duration) + 1, sample_interval):
            snapshot = self._create_health_snapshot(t)
            self.health_timeline.append(snapshot)

        return self.health_timeline

    def analyze_error_propagation(self) -> List[Tuple[float, str, float]]:
        """Analyze how errors propagated through the system."""
        timeline = []

        error_metrics = self.metrics_df[
            (self.metrics_df['name'].astype(str).str.contains('error', na=False)) &
            (self.metrics_df['name'].astype(str).str.contains('service.', na=False))
        ].copy()

        if error_metrics.empty:
            return timeline

        for (component, time), group in error_metrics.groupby(['component.id', 'sim.time']):
            total_errors = group['value'].sum()
            if total_errors > 0:
                timeline.append((float(time), component, float(total_errors)))

        timeline.sort(key=lambda x: x[0])
        return timeline

    def analyze_latency_propagation(self) -> List[Tuple[float, str, float]]:
        """Analyze how latency propagated through the system."""
        timeline = []

        duration_metrics = self.metrics_df[
            (self.metrics_df['name'].astype(str).str.contains('duration', na=False))
        ].copy()

        if duration_metrics.empty:
            return timeline

        for (component, time), group in duration_metrics.groupby(['component.id', 'sim.time']):
            for _, row in group.iterrows():
                if 'summary' in row and isinstance(row['summary'], dict):
                    p99 = row['summary'].get('p99', 0)
                    if p99 > 0:
                        timeline.append((float(time), component, float(p99)))
                        break

        timeline.sort(key=lambda x: x[0])
        return timeline

    def track_circuit_breaker_events(self) -> List[CircuitBreakerEvent]:
        """Track all circuit breaker state changes."""
        cb_metrics = self.metrics_df[
            self.metrics_df['name'].astype(str).str.contains('circuit_breaker_state', na=False)
        ].copy()

        if cb_metrics.empty:
            return self.circuit_breaker_events

        cb_metrics = cb_metrics.sort_values('sim.time')

        for (source, target), group in cb_metrics.groupby(['component.id', 'dependency_name']):
            prev_state = None

            for _, row in group.iterrows():
                state = row['value']

                if prev_state is not None and state != prev_state:
                    reason = self._determine_cb_reason(source, target, row['sim.time'], state)

                    self.circuit_breaker_events.append(CircuitBreakerEvent(
                        source_component=source,
                        target_component=target,
                        timestamp=row['sim.time'],
                        new_state=state,
                        reason=reason
                    ))

                prev_state = state

        return self.circuit_breaker_events

    def assess_recovery(self) -> bool:
        """Assess if system recovered by end of simulation."""
        if not self.health_timeline:
            return False

        final_health = self.health_timeline[-1]

        recovered = (
            final_health.failed_services == 0 and
            final_health.active_bottlenecks <= 1 and
            final_health.overall_health in [HealthState.HEALTHY, HealthState.DEGRADED]
        )

        return recovered

    def _create_health_snapshot(self, time: float) -> SystemHealthSnapshot:
        """Create health snapshot at specific time."""
        time_metrics = self.metrics_df[
            (self.metrics_df['sim.time'] >= time - 5) &
            (self.metrics_df['sim.time'] <= time + 5)
        ]

        services = [n for n, d in self.topology_graph.nodes(data=True)
                   if d.get('role') == 'service']

        healthy = 0
        degraded = 0
        failed = 0

        for svc in services:
            state = self._assess_component_health(svc, time, time_metrics)
            if state == HealthState.HEALTHY:
                healthy += 1
            elif state == HealthState.DEGRADED or state == HealthState.CRITICAL:
                degraded += 1
            else:
                failed += 1

        active_bottlenecks = sum(
            1 for b in self.bottlenecks
            if b.start_time <= time and (b.end_time is None or b.end_time >= time)
        )

        open_cbs = 0
        for (source, target), group in time_metrics[
            time_metrics['name'].astype(str).str.contains('circuit_breaker_state', na=False)
        ].groupby(['component.id', 'dependency_name']):
            if group['value'].iloc[-1] >= 1.0:
                open_cbs += 1

        queue_backlogs = sum(
            1 for q in self.queue_analyses
            if q.backlog_started and q.backlog_started <= time and
               (q.backlog_cleared is None or q.backlog_cleared >= time)
        )

        error_data = time_metrics[time_metrics['name'].astype(str).str.contains('error', na=False)]
        error_rate = error_data['value'].sum() if not error_data.empty else 0.0

        duration_data = time_metrics[time_metrics['name'].astype(str).str.contains('duration', na=False)]
        avg_latency = 0.0
        if not duration_data.empty:
            latencies = []
            for _, row in duration_data.iterrows():
                if 'summary' in row and isinstance(row['summary'], dict):
                    latencies.append(row['summary'].get('p50', 0))
            if latencies:
                avg_latency = np.mean(latencies)

        # Determine overall health
        if failed > 0 or active_bottlenecks >= 3:
            overall_health = HealthState.FAILED
        elif degraded > len(services) * 0.3 or active_bottlenecks >= 2:
            overall_health = HealthState.CRITICAL
        elif degraded > 0 or active_bottlenecks > 0:
            overall_health = HealthState.DEGRADED
        else:
            overall_health = HealthState.HEALTHY

        return SystemHealthSnapshot(
            timestamp=time,
            overall_health=overall_health,
            healthy_services=healthy,
            degraded_services=degraded,
            failed_services=failed,
            active_bottlenecks=active_bottlenecks,
            open_circuit_breakers=open_cbs,
            queue_backlogs=queue_backlogs,
            error_rate=error_rate,
            avg_latency=avg_latency
        )

    def _assess_component_health(
        self,
        component_id: str,
        time: float,
        time_metrics: pd.DataFrame
    ) -> HealthState:
        """Assess health of a component at specific time."""
        for crash in self.crashes:
            if crash.component_id == component_id and crash.crash_time <= time:
                if not crash.recovered or (crash.recovery_time and crash.recovery_time > time):
                    return HealthState.FAILED

        for bottleneck in self.bottlenecks:
            if (bottleneck.component_id == component_id and
                bottleneck.start_time <= time and
                (bottleneck.end_time is None or bottleneck.end_time >= time)):

                if bottleneck.severity in ['critical', 'severe']:
                    return HealthState.CRITICAL
                else:
                    return HealthState.DEGRADED

        return HealthState.HEALTHY

    def _determine_cb_reason(self, source: str, target: str, time: float, new_state: float) -> str:
        """Determine why circuit breaker changed state."""
        if new_state == 1.0:
            for crash in self.crashes:
                if crash.component_id == target and abs(crash.crash_time - time) < 30:
                    return f"Target {target} crashed"

            for bottleneck in self.bottlenecks:
                if bottleneck.component_id == target and abs(bottleneck.start_time - time) < 30:
                    return f"Target {target} became bottleneck ({bottleneck.bottleneck_type.value})"

            return "High error rate or latency from target"
        elif new_state == 0.0:
            return "Target recovered, circuit breaker closed"
        else:
            return "Testing recovery (half-open state)"

    @staticmethod
    def create_default_health() -> SystemHealthSnapshot:
        """Create a default health snapshot."""
        return SystemHealthSnapshot(
            timestamp=0,
            overall_health=HealthState.HEALTHY,
            healthy_services=0,
            degraded_services=0,
            failed_services=0,
            active_bottlenecks=0,
            open_circuit_breakers=0,
            queue_backlogs=0,
            error_rate=0.0,
            avg_latency=0.0
        )
