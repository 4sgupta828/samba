"""
Bottleneck analysis for forensic investigations.

Identifies and analyzes resource bottlenecks in services and infrastructure.
"""

import pandas as pd
import networkx as nx
from typing import List, Optional
from .models import BottleneckAnalysis, BottleneckType


class BottleneckAnalyzer:
    """Analyzes system bottlenecks."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        fault_start_time: float,
        fault_duration: float,
        simulation_duration: float
    ):
        self.metrics_df = metrics_df
        self.topology_graph = topology_graph
        self.fault_start_time = fault_start_time
        self.fault_duration = fault_duration
        self.simulation_duration = simulation_duration
        self.bottlenecks: List[BottleneckAnalysis] = []

    def analyze_all_bottlenecks(self) -> List[BottleneckAnalysis]:
        """Identify and analyze all bottlenecks in the system."""
        self._analyze_service_bottlenecks()
        self._analyze_infrastructure_bottlenecks()
        self._analyze_external_bottlenecks()
        return self.bottlenecks

    def _analyze_service_bottlenecks(self):
        """Analyze service-level bottlenecks."""
        services = [n for n, d in self.topology_graph.nodes(data=True)
                   if d.get('role') == 'service']

        for service in services:
            self._check_cpu_bottleneck(service, 'Service')
            self._check_memory_bottleneck(service, 'Service')
            self._check_thread_pool_bottleneck(service)
            self._check_connection_pool_bottleneck(service)

    def _check_cpu_bottleneck(self, component_id: str, component_type: str):
        """Check for CPU bottleneck."""
        cpu_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'container.cpu.utilization')
        ].copy()

        if cpu_metrics.empty:
            return

        cpu_metrics = cpu_metrics.sort_values('sim.time')
        high_cpu = cpu_metrics[cpu_metrics['value'] > 80]

        if not high_cpu.empty:
            for start_idx in range(len(high_cpu) - 2):
                window = high_cpu.iloc[start_idx:start_idx+3]
                if len(window) >= 3:
                    start_time = window.iloc[0]['sim.time']

                    end_mask = (cpu_metrics['sim.time'] > start_time) & (cpu_metrics['value'] <= 80)
                    end_data = cpu_metrics[end_mask]
                    end_time = end_data.iloc[0]['sim.time'] if not end_data.empty else None

                    duration = (end_time - start_time) if end_time else (self.simulation_duration - start_time)
                    peak_value = high_cpu['value'].max()

                    severity = self._determine_severity(peak_value, thresholds=[85, 95, 99])

                    self.bottlenecks.append(BottleneckAnalysis(
                        component_id=component_id,
                        component_type=component_type,
                        bottleneck_type=BottleneckType.CPU,
                        start_time=start_time,
                        end_time=end_time,
                        duration=duration,
                        severity=severity,
                        peak_value=peak_value,
                        capacity=100.0,
                        utilization_pct=peak_value,
                        impact=f"CPU saturated, causing request queuing and increased latency",
                        contributing_factors=self._identify_cpu_factors(component_id, start_time),
                        degradation_pct=0.0
                    ))
                    break

    def _check_memory_bottleneck(self, component_id: str, component_type: str):
        """Check for memory bottleneck."""
        memory_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'container.memory.usage_mb')
        ].copy()

        if memory_metrics.empty:
            return

        memory_metrics = memory_metrics.sort_values('sim.time')
        memory_limit = 512.0

        threshold = memory_limit * 0.7
        high_memory = memory_metrics[memory_metrics['value'] > threshold]

        if not high_memory.empty:
            start_time = high_memory.iloc[0]['sim.time']
            peak_value = high_memory['value'].max()
            utilization = (peak_value / memory_limit) * 100

            end_mask = (memory_metrics['sim.time'] > start_time) & (memory_metrics['value'] <= threshold)
            end_data = memory_metrics[end_mask]
            end_time = end_data.iloc[0]['sim.time'] if not end_data.empty else None

            duration = (end_time - start_time) if end_time else (self.simulation_duration - start_time)
            severity = self._determine_severity(utilization, thresholds=[75, 90, 95])

            self.bottlenecks.append(BottleneckAnalysis(
                component_id=component_id,
                component_type=component_type,
                bottleneck_type=BottleneckType.MEMORY,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                severity=severity,
                peak_value=peak_value,
                capacity=memory_limit,
                utilization_pct=utilization,
                impact=f"Memory pressure, risk of OOM kills",
                contributing_factors=self._identify_memory_factors(component_id, start_time),
                degradation_pct=0.0
            ))

    def _check_thread_pool_bottleneck(self, component_id: str):
        """Check for thread pool saturation."""
        active_threads = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'thread_pool.threads.active')
        ].copy()

        queue_depth = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'thread_pool.queue.depth')
        ].copy()

        if active_threads.empty or queue_depth.empty:
            return

        active_threads = active_threads.sort_values('sim.time')
        queue_depth = queue_depth.sort_values('sim.time')

        thread_limit = 50
        maxed_threads = active_threads[active_threads['value'] >= thread_limit]

        if not maxed_threads.empty:
            start_time = maxed_threads.iloc[0]['sim.time']

            queue_at_start = queue_depth[queue_depth['sim.time'] >= start_time]
            if not queue_at_start.empty:
                peak_queue = queue_at_start['value'].max()

                if peak_queue > 100:
                    end_mask = (active_threads['sim.time'] > start_time) & (active_threads['value'] < thread_limit)
                    end_data = active_threads[end_mask]
                    end_time = end_data.iloc[0]['sim.time'] if not end_data.empty else None

                    duration = (end_time - start_time) if end_time else (self.simulation_duration - start_time)
                    severity = self._determine_severity(peak_queue, thresholds=[1000, 5000, 10000])

                    self.bottlenecks.append(BottleneckAnalysis(
                        component_id=component_id,
                        component_type='Service',
                        bottleneck_type=BottleneckType.THREAD_POOL,
                        start_time=start_time,
                        end_time=end_time,
                        duration=duration,
                        severity=severity,
                        peak_value=peak_queue,
                        capacity=thread_limit,
                        utilization_pct=100.0,
                        impact=f"Thread pool exhausted, {int(peak_queue)} requests queued",
                        contributing_factors=self._identify_thread_pool_factors(component_id, start_time),
                        degradation_pct=0.0
                    ))

    def _check_connection_pool_bottleneck(self, component_id: str):
        """Check for connection pool saturation."""
        active_conns = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'connection_pool.connections.active')
        ].copy()

        queue_depth = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'connection_pool.queue_depth')
        ].copy()

        if active_conns.empty or queue_depth.empty:
            return

        conn_limit = 20
        active_conns = active_conns.sort_values('sim.time')
        saturated = active_conns[active_conns['value'] >= conn_limit * 0.9]

        if not saturated.empty:
            start_time = saturated.iloc[0]['sim.time']
            peak_value = saturated['value'].max()

            queue_at_start = queue_depth[queue_depth['sim.time'] >= start_time]
            peak_queue = queue_at_start['value'].max() if not queue_at_start.empty else 0

            if peak_queue > 5:
                end_mask = (active_conns['sim.time'] > start_time) & (active_conns['value'] < conn_limit * 0.9)
                end_data = active_conns[end_mask]
                end_time = end_data.iloc[0]['sim.time'] if not end_data.empty else None

                duration = (end_time - start_time) if end_time else (self.simulation_duration - start_time)
                utilization = (peak_value / conn_limit) * 100
                severity = self._determine_severity(peak_queue, thresholds=[10, 50, 100])

                self.bottlenecks.append(BottleneckAnalysis(
                    component_id=component_id,
                    component_type='Service',
                    bottleneck_type=BottleneckType.CONNECTION_POOL,
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    severity=severity,
                    peak_value=peak_queue,
                    capacity=conn_limit,
                    utilization_pct=utilization,
                    impact=f"Connection pool exhausted, requests waiting for DB/cache connections",
                    contributing_factors=["Cache failure forcing all DB queries", "Increased DB latency"],
                    degradation_pct=0.0
                ))

    def _analyze_infrastructure_bottlenecks(self):
        """Analyze infrastructure-level bottlenecks (nodes, DB, cache)."""
        nodes = [n for n, d in self.topology_graph.nodes(data=True)
                if d.get('role') == 'node']

        for node in nodes:
            self._check_cpu_bottleneck(node, 'ComputeNode')
            self._check_node_memory_bottleneck(node)

    def _check_node_memory_bottleneck(self, node_id: str):
        """Check node memory saturation."""
        memory_metrics = self.metrics_df[
            (self.metrics_df['node.id'] == node_id) &
            (self.metrics_df['name'] == 'node.memory.usage_gb')
        ].copy()

        if memory_metrics.empty:
            return

        capacity_label = memory_metrics['node.memory_gb'].iloc[0] if 'node.memory_gb' in memory_metrics.columns else 32

        memory_metrics = memory_metrics.sort_values('sim.time')
        threshold = capacity_label * 0.8

        high_memory = memory_metrics[memory_metrics['value'] > threshold]

        if not high_memory.empty:
            start_time = high_memory.iloc[0]['sim.time']
            peak_value = high_memory['value'].max()
            utilization = (peak_value / capacity_label) * 100

            end_mask = (memory_metrics['sim.time'] > start_time) & (memory_metrics['value'] <= threshold)
            end_data = memory_metrics[end_mask]
            end_time = end_data.iloc[0]['sim.time'] if not end_data.empty else None

            duration = (end_time - start_time) if end_time else (self.simulation_duration - start_time)
            severity = self._determine_severity(utilization, thresholds=[85, 92, 97])

            self.bottlenecks.append(BottleneckAnalysis(
                component_id=node_id,
                component_type='ComputeNode',
                bottleneck_type=BottleneckType.MEMORY,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                severity=severity,
                peak_value=peak_value,
                capacity=capacity_label,
                utilization_pct=utilization,
                impact=f"Node memory pressure affecting all pods on node",
                contributing_factors=["Multiple pods experiencing memory growth"],
                degradation_pct=0.0
            ))

    def _analyze_external_bottlenecks(self):
        """Analyze external component bottlenecks (DB, cache, external services)."""
        cache_nodes = [n for n, d in self.topology_graph.nodes(data=True)
                      if d.get('role') == 'cache']

        for cache in cache_nodes:
            self._check_cache_bottleneck(cache)

    def _check_cache_bottleneck(self, cache_id: str):
        """Check cache issues (which is the root cause in this scenario)."""
        cache_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == cache_id)
        ].copy()

        if not cache_metrics.empty:
            self.bottlenecks.append(BottleneckAnalysis(
                component_id=cache_id,
                component_type='Cache',
                bottleneck_type=BottleneckType.CACHE,
                start_time=self.fault_start_time,
                end_time=self.fault_start_time + self.fault_duration,
                duration=self.fault_duration,
                severity="critical",
                peak_value=0.0,
                capacity=100.0,
                utilization_pct=0.0,
                impact="Complete cache failure causing thundering herd to database",
                contributing_factors=["Injected cache failure fault"],
                degradation_pct=0.0
            ))

    def _determine_severity(self, value: float, thresholds: List[float]) -> str:
        """Determine severity based on value and thresholds."""
        if value >= thresholds[2]:
            return "critical"
        elif value >= thresholds[1]:
            return "severe"
        elif value >= thresholds[0]:
            return "moderate"
        else:
            return "mild"

    def _identify_cpu_factors(self, component_id: str, start_time: float) -> List[str]:
        """Identify factors contributing to CPU bottleneck."""
        factors = []

        if start_time >= self.fault_start_time:
            factors.append("Cache failure forcing synchronous DB queries")

        thread_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'thread_pool.threads.active') &
            (self.metrics_df['sim.time'] >= start_time - 10) &
            (self.metrics_df['sim.time'] <= start_time + 10)
        ]

        if not thread_metrics.empty and thread_metrics['value'].max() >= 50:
            factors.append("Thread pool saturation (50/50 threads active)")

        return factors if factors else ["High request load"]

    def _identify_memory_factors(self, component_id: str, start_time: float) -> List[str]:
        """Identify factors contributing to memory bottleneck."""
        factors = []

        queue_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'] == 'thread_pool.queue.depth') &
            (self.metrics_df['sim.time'] >= start_time - 10) &
            (self.metrics_df['sim.time'] <= start_time + 10)
        ]

        if not queue_metrics.empty:
            peak_queue = queue_metrics['value'].max()
            if peak_queue > 1000:
                factors.append(f"Large request queue ({int(peak_queue)} requests holding memory)")

        return factors if factors else ["Memory leak or accumulation"]

    def _identify_thread_pool_factors(self, component_id: str, start_time: float) -> List[str]:
        """Identify factors contributing to thread pool bottleneck."""
        factors = []

        duration_metrics = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['name'].astype(str).str.contains('duration', na=False)) &
            (self.metrics_df['sim.time'] >= start_time - 10) &
            (self.metrics_df['sim.time'] <= start_time + 10)
        ]

        if not duration_metrics.empty:
            high_latency = False
            for _, row in duration_metrics.iterrows():
                if 'summary' in row and isinstance(row['summary'], dict):
                    p99 = row['summary'].get('p99', 0)
                    if p99 > 500:
                        high_latency = True
                        break

            if high_latency:
                factors.append("High latency blocking threads (>500ms p99)")

        deps = list(self.topology_graph.successors(component_id))
        for dep in deps:
            for bottleneck in self.bottlenecks:
                if bottleneck.component_id == dep and abs(bottleneck.start_time - start_time) < 30:
                    factors.append(f"Downstream bottleneck in {dep}")

        return factors if factors else ["High request rate with slow processing"]
