"""
Resource Saturation Detector

Identifies when resources hit capacity limits and how that drives
fault propagation behavior:
- Connection pool saturation
- CPU/memory limits
- Queue buildup
- Connection rejections
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class SaturationEvent:
    """Record of a resource saturation event."""
    resource_type: str  # 'connection_pool', 'cpu', 'memory', 'queue'
    time_s: float
    value: float
    threshold: float
    utilization_pct: float
    severity: str  # 'warning', 'critical'
    impact: str
    additional_metrics: Dict

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = asdict(self)
        for key in ['value', 'threshold', 'utilization_pct']:
            if isinstance(result[key], float):
                result[key] = round(result[key], 2)
        return result


@dataclass
class ResourceSaturationReport:
    """Complete saturation analysis for a component."""
    component_id: str
    component_type: str
    saturation_events: List[SaturationEvent]
    peak_utilization: Dict[str, float]
    sustained_saturation: bool
    saturation_duration_s: Optional[float]
    summary: str

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'component_id': self.component_id,
            'component_type': self.component_type,
            'saturation_events': [e.to_dict() for e in self.saturation_events],
            'peak_utilization': {
                k: round(v, 2) for k, v in self.peak_utilization.items()
            },
            'sustained_saturation': self.sustained_saturation,
            'saturation_duration_s': round(self.saturation_duration_s, 1) if self.saturation_duration_s else None,
            'summary': self.summary
        }


class ResourceSaturationDetector:
    """Detects resource saturation events from metrics."""

    # Saturation thresholds
    THRESHOLDS = {
        'connection_pool_utilization': 0.8,  # 80% utilization
        'cpu_utilization': 80.0,              # 80% CPU
        'memory_utilization': 80.0,           # 80% memory
        'queue_depth': 10,                    # 10+ items queued
    }

    CRITICAL_THRESHOLDS = {
        'connection_pool_utilization': 0.95,  # 95% utilization
        'cpu_utilization': 95.0,
        'memory_utilization': 95.0,
        'queue_depth': 50,
    }

    def __init__(self, metrics_file: Path, fault_start_time: float):
        """
        Initialize detector.

        Args:
            metrics_file: Path to metrics.jsonl file
            fault_start_time: When fault was injected
        """
        self.metrics_file = Path(metrics_file)
        self.fault_start_time = fault_start_time
        self.metrics_by_component = defaultdict(lambda: defaultdict(list))

    def load_metrics(self):
        """Load all metrics from file."""
        with open(self.metrics_file, 'r') as f:
            for line in f:
                try:
                    metric = json.loads(line)
                    component_id = metric.get('labels', {}).get('component.id')
                    if not component_id:
                        continue

                    metric_name = metric['name']
                    sim_time = metric.get('labels', {}).get('sim.time')
                    value = metric.get('value')

                    if sim_time is not None and value is not None:
                        self.metrics_by_component[component_id][metric_name].append({
                            'time': float(sim_time),
                            'value': float(value) if not isinstance(value, str) else value
                        })
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

    def detect_connection_pool_saturation(
        self,
        component_id: str,
        pool_capacity: Optional[int] = None
    ) -> List[SaturationEvent]:
        """Detect connection pool saturation events."""
        events = []

        # Look for active connections metric
        active_connections = self.metrics_by_component[component_id].get('db.connections.active', [])
        rejections = self.metrics_by_component[component_id].get('db.connections.rejected', [])

        # Also check for pod-level connection pool metrics
        pool_active = self.metrics_by_component[component_id].get('connection_pool.connections.active', [])
        pool_queue = self.metrics_by_component[component_id].get('connection_pool.queue_depth', [])

        # Database connections
        if active_connections and pool_capacity:
            for point in active_connections:
                if point['time'] >= self.fault_start_time:
                    utilization = point['value'] / pool_capacity
                    if utilization >= self.THRESHOLDS['connection_pool_utilization']:
                        severity = 'critical' if utilization >= self.CRITICAL_THRESHOLDS['connection_pool_utilization'] else 'warning'

                        # Check for rejections at same time
                        rejection_count = 0
                        for rej_point in rejections:
                            if abs(rej_point['time'] - point['time']) < 5:  # Within 5s
                                rejection_count += rej_point['value']

                        impact = f"{int(point['value'])}/{pool_capacity} connections active ({utilization*100:.0f}% utilization)"
                        if rejection_count > 0:
                            impact += f", {int(rejection_count)} connections rejected"

                        events.append(SaturationEvent(
                            resource_type='connection_pool',
                            time_s=point['time'],
                            value=point['value'],
                            threshold=pool_capacity * self.THRESHOLDS['connection_pool_utilization'],
                            utilization_pct=utilization * 100,
                            severity=severity,
                            impact=impact,
                            additional_metrics={'rejections': rejection_count}
                        ))

        # Service-level connection pool (for pods calling DB)
        if pool_active and pool_queue:
            # Match up active + queue metrics
            for active_point in pool_active:
                if active_point['time'] >= self.fault_start_time:
                    # Find corresponding queue depth
                    queue_depth = 0
                    for queue_point in pool_queue:
                        if abs(queue_point['time'] - active_point['time']) < 1:
                            queue_depth = queue_point['value']
                            break

                    if queue_depth >= self.THRESHOLDS['queue_depth']:
                        severity = 'critical' if queue_depth >= self.CRITICAL_THRESHOLDS['queue_depth'] else 'warning'
                        impact = f"{int(queue_depth)} requests queued for connection pool"

                        events.append(SaturationEvent(
                            resource_type='connection_pool_queue',
                            time_s=active_point['time'],
                            value=queue_depth,
                            threshold=self.THRESHOLDS['queue_depth'],
                            utilization_pct=100.0,  # Queue is saturated
                            severity=severity,
                            impact=impact,
                            additional_metrics={'active_connections': active_point['value']}
                        ))

        return events

    def detect_cpu_saturation(self, component_id: str) -> List[SaturationEvent]:
        """Detect CPU saturation events."""
        events = []

        cpu_metrics = self.metrics_by_component[component_id].get('db.cpu.utilization', []) or \
                     self.metrics_by_component[component_id].get('pod.cpu.utilization', []) or \
                     self.metrics_by_component[component_id].get('compute.cpu.utilization', [])

        for point in cpu_metrics:
            if point['time'] >= self.fault_start_time:
                if point['value'] >= self.THRESHOLDS['cpu_utilization']:
                    severity = 'critical' if point['value'] >= self.CRITICAL_THRESHOLDS['cpu_utilization'] else 'warning'
                    impact = f"CPU at {point['value']:.1f}% utilization"

                    events.append(SaturationEvent(
                        resource_type='cpu',
                        time_s=point['time'],
                        value=point['value'],
                        threshold=self.THRESHOLDS['cpu_utilization'],
                        utilization_pct=point['value'],
                        severity=severity,
                        impact=impact,
                        additional_metrics={}
                    ))

        return events

    def detect_queue_saturation(self, component_id: str) -> List[SaturationEvent]:
        """Detect message queue saturation events."""
        events = []

        visible_messages = self.metrics_by_component[component_id].get('mq.messages.visible', [])

        for point in visible_messages:
            if point['time'] >= self.fault_start_time:
                # Look for rapid buildup (> 5000 messages is concerning for our system)
                if point['value'] >= 5000:
                    severity = 'critical' if point['value'] >= 8000 else 'warning'
                    impact = f"{int(point['value'])} messages queued and visible"

                    events.append(SaturationEvent(
                        resource_type='message_queue',
                        time_s=point['time'],
                        value=point['value'],
                        threshold=5000,
                        utilization_pct=min((point['value'] / 10000) * 100, 100),  # Assume 10k is max
                        severity=severity,
                        impact=impact,
                        additional_metrics={}
                    ))

        return events

    def analyze_component(
        self,
        component_id: str,
        component_type: str,
        config: Optional[Dict] = None
    ) -> Optional[ResourceSaturationReport]:
        """
        Analyze resource saturation for a component.

        Args:
            component_id: Component identifier
            component_type: Type of component
            config: Optional configuration context with capacities

        Returns:
            ResourceSaturationReport or None if no saturation detected
        """
        events = []

        # Extract capacity from config if available
        pool_capacity = None
        if config and 'connection_pool' in config.get('configuration', {}):
            pool_capacity = config['configuration']['connection_pool'].get('capacity')

        # Detect different types of saturation
        if component_type in ['SqlDatabase', 'Service', 'Pod']:
            events.extend(self.detect_connection_pool_saturation(component_id, pool_capacity))

        if component_type in ['SqlDatabase', 'Pod', 'ComputeNode']:
            events.extend(self.detect_cpu_saturation(component_id))

        if component_type == 'MessageQueue':
            events.extend(self.detect_queue_saturation(component_id))

        if not events:
            return None

        # Calculate peak utilization by resource type
        peak_utilization = {}
        for event in events:
            key = event.resource_type
            if key not in peak_utilization or event.utilization_pct > peak_utilization[key]:
                peak_utilization[key] = event.utilization_pct

        # Check for sustained saturation
        critical_events = [e for e in events if e.severity == 'critical']
        sustained = len(critical_events) >= 3  # 3+ critical events = sustained

        saturation_duration = None
        if events:
            saturation_duration = max(e.time_s for e in events) - min(e.time_s for e in events)

        # Generate summary
        resource_types = list(set(e.resource_type for e in events))
        summary = f"Saturation detected in {', '.join(resource_types)}. "
        summary += f"{len([e for e in events if e.severity == 'critical'])} critical events, "
        summary += f"{len([e for e in events if e.severity == 'warning'])} warnings."

        return ResourceSaturationReport(
            component_id=component_id,
            component_type=component_type,
            saturation_events=events[:10],  # Limit to first 10 events
            peak_utilization=peak_utilization,
            sustained_saturation=sustained,
            saturation_duration_s=saturation_duration,
            summary=summary
        )

    def analyze_all(self, topology: Dict, configs: Dict[str, Dict]) -> Dict[str, ResourceSaturationReport]:
        """
        Analyze saturation for all components.

        Args:
            topology: Topology dictionary
            configs: Configuration contexts from ConfigExtractor

        Returns:
            Dictionary mapping component_id -> ResourceSaturationReport
        """
        self.load_metrics()

        results = {}
        for node in topology.get('nodes', []):
            node_id = node['id']
            node_type = node.get('type', 'Unknown')

            config = configs.get(node_id)
            report = self.analyze_component(node_id, node_type, config)

            if report:
                results[node_id] = report

        return results

    def generate_report(self, reports: Dict[str, ResourceSaturationReport]) -> str:
        """Generate human-readable saturation report."""
        if not reports:
            return "No resource saturation detected.\n"

        lines = ["=" * 80, "RESOURCE SATURATION ANALYSIS", "=" * 80, ""]

        for component_id, report in sorted(reports.items()):
            lines.append(f"\n{component_id} ({report.component_type})")
            lines.append("-" * 60)
            lines.append(f"  {report.summary}")
            lines.append(f"  Peak Utilization:")
            for resource, util in report.peak_utilization.items():
                lines.append(f"    - {resource}: {util:.1f}%")

            if report.saturation_events:
                lines.append(f"  Key Saturation Events (showing {min(3, len(report.saturation_events))}):")
                for event in report.saturation_events[:3]:
                    lines.append(f"    - t={event.time_s:.0f}s [{event.severity.upper()}]: {event.impact}")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)
