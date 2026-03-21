"""
Post-Simulation Forensic Analyzer

Comprehensive analysis of what happened during and after fault injection,
tracking the complete lifecycle of the fault's impact on the topology.

This analyzer provides:
1. Bottleneck identification and degradation analysis
2. Crash analysis with recovery tracking
3. Queue backlog and consumer/producer health
4. Infrastructure bottleneck detection
5. Cascade development tracking
6. Error propagation analysis
7. Latency propagation analysis
8. Circuit breaker state timeline
9. End-state system health assessment
10. Recovery recommendations
"""

import numpy as np
import pandas as pd
import networkx as nx
from pathlib import Path
from typing import Dict, List, Any
import json

from .forensics import (
    ForensicReport,
    BottleneckAnalyzer,
    CrashAnalyzer,
    CascadeDetector,
    DegradationCalculator,
    HealthTracker,
    RecommendationGenerator,
    QueueAnalyzer,
)


class ForensicAnalyzer:
    """
    Comprehensive forensic analyzer for post-simulation analysis.

    Orchestrates multiple specialized analyzers to provide a complete
    picture of what happened during fault injection.
    """

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        logs_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        label_data: Dict,
        topology_state_snapshots: List[Dict],
        output_dir: str
    ):
        """
        Initialize forensic analyzer.

        Args:
            metrics_df: DataFrame with all metrics
            logs_df: DataFrame with all logs
            topology_graph: NetworkX graph of topology
            label_data: Label information including fault details
            topology_state_snapshots: List of topology state snapshots
            output_dir: Output directory for analysis
        """
        self.metrics_df = metrics_df
        self.logs_df = logs_df
        self.topology_graph = topology_graph
        self.label_data = label_data
        self.topology_snapshots = topology_state_snapshots
        self.output_dir = Path(output_dir)

        # Extract key info
        self.fault_start_time = label_data.get('fault_start_time', 0)
        self.fault_duration = label_data.get('fault_total_duration', 0)
        self.simulation_duration = metrics_df['sim.time'].max() if 'sim.time' in metrics_df.columns else 900
        self.root_cause = label_data.get('root_cause_node', 'unknown')
        self.fault_type = label_data.get('fault_type', 'unknown')

    def analyze(self) -> ForensicReport:
        """
        Run complete forensic analysis.

        Returns:
            ForensicReport with all analysis results
        """
        print("Starting forensic analysis...")

        # 0. Calculate component degradations first (needed by other analyses)
        print("  0/11 Calculating component degradation percentages...")
        degradation_calc = DegradationCalculator(
            self.metrics_df,
            self.topology_graph,
            self.fault_start_time,
            self.simulation_duration
        )
        component_degradations = degradation_calc.calculate_all_degradations()

        # 1. Analyze bottlenecks and degradation
        print("  1/11 Analyzing bottlenecks and degradation...")
        bottleneck_analyzer = BottleneckAnalyzer(
            self.metrics_df,
            self.topology_graph,
            self.fault_start_time,
            self.fault_duration,
            self.simulation_duration
        )
        bottlenecks = bottleneck_analyzer.analyze_all_bottlenecks()

        # 2. Analyze crashes and recovery
        print("  2/11 Analyzing crashes and recovery...")
        crash_analyzer = CrashAnalyzer(
            self.metrics_df,
            self.logs_df,
            self.topology_graph,
            self.topology_snapshots,
            self.fault_start_time
        )
        crashes = crash_analyzer.analyze_crashes()

        # 3. Analyze queue backlogs
        print("  3/11 Analyzing queue backlogs...")
        queue_analyzer = QueueAnalyzer(
            self.metrics_df,
            self.topology_graph,
            crashes,
            self.fault_start_time,
            self.simulation_duration
        )
        queue_analyses = queue_analyzer.analyze_queues()

        # 4. Detect cascades (improved with degradation %)
        print("  4/11 Detecting cascades...")
        cascade_detector = CascadeDetector(
            self.topology_graph,
            crashes,
            bottlenecks,
            component_degradations
        )
        cascades = cascade_detector.detect_cascades()

        # 5-8. Track health, circuit breakers, and propagation
        print("  5/11 Tracking circuit breaker events...")
        print("  6/11 Analyzing error propagation...")
        print("  7/11 Analyzing latency propagation...")
        print("  8/11 Tracking system health timeline...")

        health_tracker = HealthTracker(
            self.metrics_df,
            self.topology_graph,
            self.simulation_duration,
            crashes,
            bottlenecks,
            queue_analyses
        )

        circuit_breaker_events = health_tracker.track_circuit_breaker_events()
        error_timeline = health_tracker.analyze_error_propagation()
        latency_timeline = health_tracker.analyze_latency_propagation()
        health_timeline = health_tracker.track_health_timeline()

        # 9. Assess final system state
        print("  9/11 Assessing final system state...")
        system_recovered = health_tracker.assess_recovery()

        # 10. Generate recovery recommendations (service/node-specific)
        print("  10/11 Generating recovery recommendations...")
        rec_generator = RecommendationGenerator(
            crashes,
            bottlenecks,
            queue_analyses,
            self.simulation_duration
        )
        recommendations = rec_generator.generate_recommendations()

        # 11. Create summary statistics
        print("  11/11 Generating summary statistics...")
        summary = self._create_summary(
            bottlenecks, crashes, cascades, circuit_breaker_events,
            queue_analyses, health_timeline, system_recovered
        )

        # Build report
        report = ForensicReport(
            episode_id=str(self.label_data.get('episode', 0)),
            simulation_duration=self.simulation_duration,
            fault_injection_time=self.fault_start_time,
            fault_type=self.fault_type,
            root_cause_component=self.root_cause,
            component_degradations=component_degradations,
            bottlenecks=bottlenecks,
            crashes=crashes,
            queue_analyses=queue_analyses,
            cascades=cascades,
            circuit_breaker_events=circuit_breaker_events,
            error_propagation_timeline=error_timeline,
            latency_propagation_timeline=latency_timeline,
            health_timeline=health_timeline,
            initial_health=health_timeline[0] if health_timeline else HealthTracker.create_default_health(),
            final_health=health_timeline[-1] if health_timeline else HealthTracker.create_default_health(),
            system_recovered=system_recovered,
            recovery_recommendations=recommendations,
            summary=summary
        )

        # Save report
        report_path = self.output_dir / "forensic_analysis.json"
        report.to_json(str(report_path))
        print(f"\nForensic analysis complete. Report saved to: {report_path}")

        return report

    def _create_summary(
        self,
        bottlenecks,
        crashes,
        cascades,
        circuit_breaker_events,
        queue_analyses,
        health_timeline,
        system_recovered
    ) -> Dict[str, Any]:
        """Create summary statistics."""
        return {
            'total_bottlenecks': len(bottlenecks),
            'bottleneck_types': dict(pd.Series([b.bottleneck_type.value for b in bottlenecks]).value_counts()),
            'total_crashes': len(crashes),
            'components_crashed': list(set(c.component_id for c in crashes)),
            'crashes_recovered': sum(1 for c in crashes if c.recovered),
            'crash_loops_detected': sum(1 for c in crashes if c.crash_loop_detected),
            'total_cascades': len(cascades),
            'longest_cascade': max((c.total_components_affected for c in cascades), default=0),
            'total_circuit_breaker_events': len(circuit_breaker_events),
            'circuit_breakers_opened': sum(1 for cb in circuit_breaker_events if cb.new_state == 1.0),
            'circuit_breakers_closed': sum(1 for cb in circuit_breaker_events if cb.new_state == 0.0),
            'queue_backlogs': len([q for q in queue_analyses if q.backlog_started]),
            'health_trajectory': {
                'initial': health_timeline[0].overall_health.value if health_timeline else 'unknown',
                'worst': min((h.overall_health.value for h in health_timeline), default='unknown',
                           key=lambda x: ['healthy', 'degraded', 'critical', 'failed'].index(x)),
                'final': health_timeline[-1].overall_health.value if health_timeline else 'unknown'
            },
            'time_to_first_impact': min((b.start_time for b in bottlenecks if b.component_id != self.root_cause),
                                       default=None) if bottlenecks else None,
            'time_to_first_crash': min((c.crash_time for c in crashes), default=None) if crashes else None,
            'system_recovered': system_recovered
        }


def analyze_episode(episode_dir: str) -> ForensicReport:
    """
    Run forensic analysis on an episode.

    Args:
        episode_dir: Directory containing episode data

    Returns:
        ForensicReport with complete analysis
    """
    episode_path = Path(episode_dir)

    # Load label
    with open(episode_path / 'label.json') as f:
        label_data = json.loads(f.read())

    # Load topology
    with open(episode_path / 'topology.json') as f:
        topology_data = json.loads(f.read())

    # Build graph
    topology_graph = nx.DiGraph()
    for node in topology_data['nodes']:
        topology_graph.add_node(node['id'], **node)

    for edge in topology_data['edges']:
        topology_graph.add_edge(edge['source'], edge['target'], **edge)

    # Load metrics
    metrics_df = pd.read_json(episode_path / 'metrics.jsonl', lines=True)

    # Flatten labels column if present
    if 'labels' in metrics_df.columns:
        labels_df = pd.json_normalize(metrics_df['labels'])
        for col in labels_df.columns:
            metrics_df[col] = labels_df[col]

    # Load logs
    logs_file = episode_path / 'logs.jsonl'
    if logs_file.exists():
        logs_df = pd.read_json(logs_file, lines=True)

        if 'attributes' in logs_df.columns:
            logs_df['component_id'] = logs_df['attributes'].apply(
                lambda x: x.get('component.id') if isinstance(x, dict) else None
            )
            logs_df['component_type'] = logs_df['attributes'].apply(
                lambda x: x.get('component.type') if isinstance(x, dict) else None
            )
    else:
        logs_df = pd.DataFrame(columns=['timestamp', 'component_id', 'level', 'message'])

    # Load topology snapshots
    topology_state_file = episode_path / "topology_state.jsonl"
    topology_snapshots = []

    if topology_state_file.exists():
        with open(topology_state_file, 'r') as f:
            for line in f:
                topology_snapshots.append(json.loads(line))

    # Create analyzer
    analyzer = ForensicAnalyzer(
        metrics_df=metrics_df,
        logs_df=logs_df,
        topology_graph=topology_graph,
        label_data=label_data,
        topology_state_snapshots=topology_snapshots,
        output_dir=str(episode_dir)
    )

    # Run analysis
    report = analyzer.analyze()

    return report
