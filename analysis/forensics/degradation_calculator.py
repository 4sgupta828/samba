"""
Component degradation calculation for forensic investigations.

Calculates percentage degradation for services and nodes based on metrics.
"""

import numpy as np
import pandas as pd
import networkx as nx
from typing import List, Optional
from .models import ComponentDegradation


class DegradationCalculator:
    """Calculates component degradation percentages."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        fault_start_time: float,
        simulation_duration: float
    ):
        self.metrics_df = metrics_df
        self.topology_graph = topology_graph
        self.fault_start_time = fault_start_time
        self.simulation_duration = simulation_duration
        self.component_degradations: List[ComponentDegradation] = []

    def calculate_all_degradations(self) -> List[ComponentDegradation]:
        """Calculate percentage degradation for each service and node."""
        components = []

        # Add services
        components.extend([
            (n, 'Service') for n, d in self.topology_graph.nodes(data=True)
            if d.get('role') == 'service'
        ])

        # Add nodes
        components.extend([
            (n, 'ComputeNode') for n, d in self.topology_graph.nodes(data=True)
            if d.get('role') == 'node'
        ])

        # Add database, cache
        components.extend([
            (n, 'Database') for n, d in self.topology_graph.nodes(data=True)
            if d.get('role') == 'database'
        ])

        components.extend([
            (n, 'Cache') for n, d in self.topology_graph.nodes(data=True)
            if d.get('role') == 'cache'
        ])

        for component_id, component_type in components:
            degradation = self._calculate_single_component_degradation(component_id, component_type)
            if degradation:
                self.component_degradations.append(degradation)

        return self.component_degradations

    def _calculate_single_component_degradation(
        self,
        component_id: str,
        component_type: str
    ) -> Optional[ComponentDegradation]:
        """Calculate degradation for a single component."""
        # Get baseline metrics (before fault)
        baseline_data = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['sim.time'] >= max(0, self.fault_start_time - 60)) &
            (self.metrics_df['sim.time'] < self.fault_start_time)
        ]

        # Get degraded metrics (during/after fault)
        degraded_data = self.metrics_df[
            (self.metrics_df['component.id'] == component_id) &
            (self.metrics_df['sim.time'] >= self.fault_start_time + 60) &
            (self.metrics_df['sim.time'] <= self.simulation_duration)
        ]

        if baseline_data.empty or degraded_data.empty:
            return None

        baseline_metrics = {}
        degraded_metrics = {}
        metric_degradations = {}

        # Define metrics to track based on component type
        if component_type == 'Service':
            metrics_to_track = [
                ('service.*.requests', 'success', 'request_rate'),
                ('service.*.duration', 'p99', 'latency_p99'),
                ('service.*.errors', 'total', 'error_rate'),
                ('container.cpu.utilization', 'mean', 'cpu_util'),
                ('container.memory.usage_mb', 'mean', 'memory_mb')
            ]
        elif component_type == 'ComputeNode':
            metrics_to_track = [
                ('node.cpu.utilization', 'mean', 'cpu_util'),
                ('node.memory.usage_gb', 'mean', 'memory_gb')
            ]
        else:
            return None

        for metric_pattern, agg_type, key in metrics_to_track:
            baseline_subset = baseline_data[baseline_data['name'].str.contains(metric_pattern.replace('*', ''), na=False, regex=False)]

            if not baseline_subset.empty:
                baseline_val = self._aggregate_metric(baseline_subset, agg_type)
                baseline_metrics[key] = baseline_val

                degraded_subset = degraded_data[degraded_data['name'].str.contains(metric_pattern.replace('*', ''), na=False, regex=False)]

                if not degraded_subset.empty:
                    degraded_val = self._aggregate_metric(degraded_subset, agg_type)
                    degraded_metrics[key] = degraded_val

                    # Calculate degradation %
                    deg_pct = self._calculate_metric_degradation(key, baseline_val, degraded_val)
                    metric_degradations[key] = deg_pct

        if not metric_degradations:
            return None

        # Overall degradation = weighted average
        weights = {
            'request_rate': 0.4,
            'latency_p99': 0.3,
            'error_rate': 0.2,
            'cpu_util': 0.05,
            'memory_mb': 0.05
        }

        overall_degradation = 0
        total_weight = 0

        for key, deg_pct in metric_degradations.items():
            if key in weights:
                overall_degradation += deg_pct * weights[key]
                total_weight += weights[key]

        if total_weight > 0:
            overall_degradation = overall_degradation / total_weight

        # Determine severity
        if overall_degradation >= 75:
            severity = 'critical'
        elif overall_degradation >= 50:
            severity = 'severe'
        elif overall_degradation >= 25:
            severity = 'moderate'
        else:
            severity = 'mild'

        start_time = self.fault_start_time
        end_time = self.simulation_duration

        return ComponentDegradation(
            component_id=component_id,
            component_type=component_type,
            degradation_pct=round(overall_degradation, 2),
            baseline_metrics=baseline_metrics,
            degraded_metrics=degraded_metrics,
            metric_degradations={k: round(v, 2) for k, v in metric_degradations.items()},
            start_time=start_time,
            end_time=end_time,
            severity=severity
        )

    def _aggregate_metric(self, data: pd.DataFrame, agg_type: str) -> float:
        """Aggregate metric based on type."""
        if agg_type == 'success':
            return data[data.get('status', data.get('labels', {})) == 'success']['value'].sum()
        elif agg_type == 'p99':
            p99_vals = []
            for _, row in data.iterrows():
                if 'summary' in row and isinstance(row['summary'], dict):
                    p99_vals.append(row['summary'].get('p99', 0))
            return np.mean(p99_vals) if p99_vals else 0
        elif agg_type == 'total':
            return data['value'].sum()
        else:  # mean
            return data['value'].mean()

    def _calculate_metric_degradation(self, key: str, baseline_val: float, degraded_val: float) -> float:
        """Calculate degradation percentage for a specific metric."""
        if key in ['request_rate']:
            # For throughput, degradation = % decrease
            if baseline_val > 0:
                return max(0, ((baseline_val - degraded_val) / baseline_val) * 100)
            else:
                return 0
        elif key in ['latency_p99']:
            # For latency, degradation = % increase
            if baseline_val > 0:
                return max(0, ((degraded_val - baseline_val) / baseline_val) * 100)
            else:
                return 0
        elif key in ['error_rate']:
            # For errors, degradation = absolute increase
            return max(0, degraded_val - baseline_val)
        else:  # Resource metrics
            # For CPU/memory, degradation = % increase if above baseline
            if baseline_val > 0 and degraded_val > baseline_val:
                return ((degraded_val - baseline_val) / baseline_val) * 100
            else:
                return 0
