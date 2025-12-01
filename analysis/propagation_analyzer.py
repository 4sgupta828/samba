"""
Graph-Aware Fault Propagation Analyzer

Analyzes how faults propagate through a distributed system topology,
starting from the root cause node and moving outward.

Provides comprehensive, quantitative analysis of impact on all nodes
in the dependency graph.
"""

import numpy as np
import pandas as pd
import networkx as nx
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
import json

from .metric_impact_analyzer import (
    analyze_all_node_metrics,
    rank_metrics_by_impact,
    MetricImpactResult
)


@dataclass
class NodeImpactReport:
    """Impact report for a single node."""
    node_id: str
    node_type: str
    distance_from_root: int
    first_impact_time: Optional[float]
    impact_delay_seconds: Optional[float]
    overall_severity: str
    overall_severity_score: float

    total_metrics_analyzed: int
    metrics_with_critical_impact: int
    metrics_with_high_impact: int
    metrics_with_medium_impact: int
    metrics_with_low_impact: int
    metrics_unchanged: int

    ranked_metrics: List[Dict]  # Top impacted metrics
    primary_impact_type: Optional[str]
    secondary_impact_type: Optional[str]

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class PropagationSummary:
    """Summary of fault propagation across entire topology."""
    episode_id: str
    root_cause: Dict
    propagation_statistics: Dict
    node_reports: List[NodeImpactReport]
    validation: Dict

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = asdict(self)
        result['node_reports'] = [nr.to_dict() for nr in self.node_reports]
        return result

    def to_json(self, filepath: Optional[str] = None, indent: int = 2) -> str:
        """
        Convert to JSON string or save to file.

        Args:
            filepath: If provided, save to this file
            indent: JSON indentation

        Returns:
            JSON string
        """
        json_str = json.dumps(self.to_dict(), indent=indent, default=str)

        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)

        return json_str


class FaultPropagationAnalyzer:
    """Main analyzer for fault propagation detection."""

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        label_data: Dict,
        sample_interval: int = 5
    ):
        """
        Initialize analyzer.

        Args:
            metrics_df: DataFrame with time-series metrics
            topology_graph: NetworkX directed graph with system topology
            label_data: Dictionary with fault information
            sample_interval: Time interval between samples (seconds)
        """
        self.metrics_df = metrics_df
        self.graph = topology_graph
        self.label_data = label_data
        self.sample_interval = sample_interval

        # Extract fault information
        self.root_cause_node = label_data.get('root_cause_node')
        self.fault_start_time = label_data.get('fault_start_time', 0)
        self.fault_type = label_data.get('fault_type', 'unknown')

    def compute_node_distances(self) -> Dict[str, int]:
        """
        Compute graph distance from root cause to all other nodes.

        Uses BFS to find shortest path distances (following dependency edges).
        Automatically expands Service nodes to include their Pods for detailed analysis.

        Returns:
            Dictionary mapping node_id -> distance
        """
        if self.root_cause_node not in self.graph:
            return {}

        # BFS from root cause (reverse graph to follow dependents)
        reverse_graph = self.graph.reverse()

        distances = {self.root_cause_node: 0}
        queue = deque([(self.root_cause_node, 0)])
        visited = {self.root_cause_node}

        while queue:
            node, dist = queue.popleft()

            for neighbor in reverse_graph.neighbors(node):
                if neighbor not in visited:
                    visited.add(neighbor)
                    distances[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        # EXPANSION: For each Service node discovered, automatically expand to its Pods
        # This allows pod-level metrics analysis without cluttering the topology
        expanded_distances = distances.copy()

        for node_id, dist in distances.items():
            node_data = self.graph.nodes.get(node_id, {})
            node_type = node_data.get('type', '')

            # If this is a Service node, find its pods
            if node_type == 'Service':
                for pod_node_id in self.graph.nodes():
                    pod_data = self.graph.nodes.get(pod_node_id, {})
                    # Check if this pod belongs to this service
                    if pod_data.get('type') == 'Pod' and pod_data.get('parent_service') == node_id:
                        # Pods inherit the same distance as their parent service
                        # (they're logically part of the same component)
                        expanded_distances[pod_node_id] = dist

        return expanded_distances

    def analyze_node(self, node_id: str, distance_from_root: int) -> NodeImpactReport:
        """
        Analyze impact on a single node.

        Args:
            node_id: Node to analyze
            distance_from_root: Graph distance from root cause

        Returns:
            NodeImpactReport with complete analysis
        """
        # Get node type from graph
        node_data = self.graph.nodes.get(node_id, {})
        node_type = node_data.get('type', 'Unknown')

        # Analyze all metrics for this node
        metric_results = analyze_all_node_metrics(
            self.metrics_df,
            node_id,
            self.fault_start_time
        )

        if len(metric_results) == 0:
            return NodeImpactReport(
                node_id=node_id,
                node_type=node_type,
                distance_from_root=distance_from_root,
                first_impact_time=None,
                impact_delay_seconds=None,
                overall_severity='UNKNOWN',
                overall_severity_score=0.0,
                total_metrics_analyzed=0,
                metrics_with_critical_impact=0,
                metrics_with_high_impact=0,
                metrics_with_medium_impact=0,
                metrics_with_low_impact=0,
                metrics_unchanged=0,
                ranked_metrics=[],
                primary_impact_type=None,
                secondary_impact_type=None
            )

        # Rank metrics by impact
        ranked = rank_metrics_by_impact(metric_results)

        # Count by severity
        severity_counts = defaultdict(int)
        for _, result in ranked:
            severity_counts[result.severity_class] += 1

        # Overall severity (highest severity among metrics)
        if len(ranked) > 0:
            overall_severity = ranked[0][1].severity_class
            overall_severity_score = ranked[0][1].severity_score
        else:
            overall_severity = 'NEGLIGIBLE'
            overall_severity_score = 0.0

        # First impact time (earliest changepoint detected)
        first_impact_time = None
        for _, result in ranked:
            cp = result.changepoint
            if cp.get('detected') and cp.get('time') is not None:
                impact_time = cp['time']
                if first_impact_time is None or impact_time < first_impact_time:
                    first_impact_time = impact_time

        impact_delay = None
        if first_impact_time is not None:
            impact_delay = first_impact_time - self.fault_start_time

        # Prepare ranked metrics (top 10) with detailed information
        ranked_metrics_list = []
        for rank, (metric_name, result) in enumerate(ranked[:10], start=1):
            # Extract key quantitative details
            effect_sizes = result.effect_sizes
            baseline_char = result.baseline_characterization
            fault_char = result.fault_characterization

            # Build detailed metric info
            metric_detail = {
                'rank': rank,
                'metric_name': metric_name,
                'severity_score': result.severity_score,
                'severity_class': result.severity_class,
                'interpretation': result.interpretation,

                # Direction and magnitude
                'mean_change_pct': effect_sizes.get('mean_pct_change', None),
                'median_change_pct': effect_sizes.get('median_pct_change', None),
                'cohens_d': effect_sizes.get('cohens_d', None),
                'cohens_d_category': effect_sizes.get('cohens_d_category', None),

                # Baseline vs Fault
                'baseline_mean': baseline_char.get('location', {}).get('mean', None),
                'baseline_median': baseline_char.get('location', {}).get('median', None),
                'baseline_std': baseline_char.get('spread', {}).get('std', None),
                'fault_mean': fault_char.get('location', {}).get('mean', None),
                'fault_median': fault_char.get('location', {}).get('median', None),
                'fault_std': fault_char.get('spread', {}).get('std', None),

                # Variance change
                'variance_ratio': effect_sizes.get('variance_ratio', None),

                # Pattern changes
                'volatility_ratio': result.pattern_changes.get('volatility', {}).get('volatility_ratio', None),
                'burstiness_change': result.pattern_changes.get('burstiness', {}).get('burstiness_change', None),
            }

            ranked_metrics_list.append(metric_detail)

        # Identify primary/secondary impact types
        impact_types = []
        for metric_name, _ in ranked[:5]:
            if 'error' in metric_name.lower():
                impact_types.append('error_rate_increase')
            elif 'latency' in metric_name.lower() or 'duration' in metric_name.lower():
                impact_types.append('latency_degradation')
            elif 'queue' in metric_name.lower() or 'pool' in metric_name.lower():
                impact_types.append('saturation')

        primary_impact = impact_types[0] if len(impact_types) > 0 else None
        secondary_impact = impact_types[1] if len(impact_types) > 1 and impact_types[1] != primary_impact else None

        return NodeImpactReport(
            node_id=node_id,
            node_type=node_type,
            distance_from_root=distance_from_root,
            first_impact_time=first_impact_time,
            impact_delay_seconds=impact_delay,
            overall_severity=overall_severity,
            overall_severity_score=overall_severity_score,
            total_metrics_analyzed=len(metric_results),
            metrics_with_critical_impact=severity_counts['CRITICAL'],
            metrics_with_high_impact=severity_counts['HIGH'],
            metrics_with_medium_impact=severity_counts['MEDIUM'],
            metrics_with_low_impact=severity_counts['LOW'],
            metrics_unchanged=severity_counts['NEGLIGIBLE'],
            ranked_metrics=ranked_metrics_list,
            primary_impact_type=primary_impact,
            secondary_impact_type=secondary_impact
        )

    def analyze_propagation(self) -> PropagationSummary:
        """
        Perform complete fault propagation analysis.

        Analyzes all nodes in the topology, starting from root cause
        and moving outward by graph distance.

        Returns:
            PropagationSummary with complete results
        """
        # Compute distances from root cause
        distances = self.compute_node_distances()

        # Group nodes by distance
        nodes_by_distance = defaultdict(list)
        for node_id, dist in distances.items():
            nodes_by_distance[dist].append(node_id)

        # Analyze each node
        node_reports = []

        for distance in sorted(nodes_by_distance.keys()):
            nodes = nodes_by_distance[distance]

            for node_id in nodes:
                report = self.analyze_node(node_id, distance)
                node_reports.append(report)

        # Compute propagation statistics
        total_nodes = len(node_reports)

        severity_counts = {
            'CRITICAL': 0,
            'HIGH': 0,
            'MEDIUM': 0,
            'LOW': 0,
            'NEGLIGIBLE': 0,
            'UNKNOWN': 0
        }

        for report in node_reports:
            severity_counts[report.overall_severity] += 1

        impact_by_distance = defaultdict(lambda: {
            'critical': 0,
            'high': 0,
            'medium': 0,
            'low': 0,
            'negligible': 0,
            'unknown': 0
        })

        for report in node_reports:
            dist = report.distance_from_root
            severity_key = report.overall_severity.lower()
            impact_by_distance[dist][severity_key] += 1

        # Propagation timing
        impact_times = [
            report.first_impact_time
            for report in node_reports
            if report.first_impact_time is not None
        ]

        first_impact_time = min(impact_times) if impact_times else None
        first_impact_node = None
        if first_impact_time:
            for report in node_reports:
                if report.first_impact_time == first_impact_time:
                    first_impact_node = report.node_id
                    break

        impact_delays = [
            report.impact_delay_seconds
            for report in node_reports
            if report.impact_delay_seconds is not None
        ]

        median_delay = float(np.median(impact_delays)) if impact_delays else None
        max_delay = float(np.max(impact_delays)) if impact_delays else None

        propagation_stats = {
            'total_nodes_analyzed': total_nodes,
            'nodes_critically_impacted': severity_counts['CRITICAL'],
            'nodes_highly_impacted': severity_counts['HIGH'],
            'nodes_moderately_impacted': severity_counts['MEDIUM'],
            'nodes_unimpacted': severity_counts['NEGLIGIBLE'],
            'impact_by_distance': dict(impact_by_distance),
            'propagation_timing': {
                'first_impact_time': first_impact_time,
                'first_impact_node': first_impact_node,
                'median_propagation_delay': median_delay,
                'max_propagation_delay': max_delay
            }
        }

        # Validation
        root_cause_report = next((r for r in node_reports if r.node_id == self.root_cause_node), None)

        root_cause_impacted = False
        if root_cause_report:
            root_cause_impacted = root_cause_report.overall_severity in ['CRITICAL', 'HIGH']

        propagation_detected = (
            severity_counts['CRITICAL'] + severity_counts['HIGH'] + severity_counts['MEDIUM']
        ) > 1  # More than just root cause

        blast_radius = sum(1 for r in node_reports if r.overall_severity in ['CRITICAL', 'HIGH', 'MEDIUM'])

        # Quality score (heuristic)
        quality_factors = []

        if root_cause_impacted:
            quality_factors.append(0.4)  # Root cause clearly impacted

        if propagation_detected:
            quality_factors.append(0.3)  # Propagation detected

        if first_impact_time and first_impact_time < self.fault_start_time + 30:
            quality_factors.append(0.2)  # Quick impact detection

        if blast_radius >= 3:
            quality_factors.append(0.1)  # Reasonable blast radius

        quality_score = sum(quality_factors)

        validation = {
            'fault_injection_working': root_cause_impacted and propagation_detected,
            'root_cause_clearly_impacted': root_cause_impacted,
            'propagation_detected': propagation_detected,
            'blast_radius': blast_radius,
            'quality_score': quality_score,
            'issues': []
        }

        if not root_cause_impacted:
            validation['issues'].append('Root cause node does not show significant impact')

        if not propagation_detected:
            validation['issues'].append('No propagation detected beyond root cause')

        if blast_radius == 0:
            validation['issues'].append('No nodes impacted (fault may not be working)')

        # Create summary
        summary = PropagationSummary(
            episode_id=self.label_data.get('episode', 'unknown'),
            root_cause={
                'node_id': self.root_cause_node,
                'node_type': self.label_data.get('root_cause_role', 'unknown'),
                'fault_type': self.fault_type,
                'fault_start_time': self.fault_start_time,
                'fault_params': self.label_data.get('fault_params', {})
            },
            propagation_statistics=propagation_stats,
            node_reports=node_reports,
            validation=validation
        )

        return summary


def analyze_episode(
    episode_dir: str,
    sample_interval: int = 5,
    output_file: Optional[str] = None,
    enable_enhanced_analysis: bool = True
) -> PropagationSummary:
    """
    Analyze fault propagation for a complete episode.

    Args:
        episode_dir: Path to episode directory
        sample_interval: Time interval between samples
        output_file: Optional JSON output file
        enable_enhanced_analysis: Whether to run enhanced analysis (latency, config, causal chains)

    Returns:
        PropagationSummary with results
    """
    from pathlib import Path

    episode_path = Path(episode_dir)

    # Load label
    with open(episode_path / 'label.json') as f:
        label_data = json.load(f)

    # Load topology
    with open(episode_path / 'topology.json') as f:
        topology_data = json.load(f)

    # Build graph
    graph = nx.DiGraph()
    for node in topology_data['nodes']:
        graph.add_node(node['id'], **node)

    for edge in topology_data['edges']:
        graph.add_edge(edge['source'], edge['target'], **edge)

    # Load metrics
    metrics_df = pd.read_json(episode_path / 'metrics.jsonl', lines=True)

    # Create analyzer
    analyzer = FaultPropagationAnalyzer(
        metrics_df=metrics_df,
        topology_graph=graph,
        label_data=label_data,
        sample_interval=sample_interval
    )

    # Run analysis
    summary = analyzer.analyze_propagation()

    # Enhanced analysis (if enabled and files exist)
    if enable_enhanced_analysis:
        traces_file = episode_path / 'traces.jsonl'
        metrics_file = episode_path / 'metrics.jsonl'

        fault_start_time = label_data.get('fault_start_time', 0)
        root_cause_node = label_data.get('root_cause_node')

        enhanced_data = {}

        # 1. Trace-based latency analysis
        if traces_file.exists():
            from .trace_latency_analyzer import TraceLatencyAnalyzer
            try:
                latency_analyzer = TraceLatencyAnalyzer(traces_file, fault_start_time)
                latency_analyses = latency_analyzer.analyze_all(topology_data)
                enhanced_data['latency_analyses'] = {
                    node_id: analysis.to_dict()
                    for node_id, analysis in latency_analyses.items()
                }
            except Exception as e:
                print(f"Warning: Latency analysis failed: {e}")
                enhanced_data['latency_analyses'] = {}
        else:
            enhanced_data['latency_analyses'] = {}

        # 2. Configuration context extraction
        try:
            from .config_extractor import ConfigExtractor
            config_extractor = ConfigExtractor()  # Will use defaults if no config file
            configs = config_extractor.extract_all(topology_data)
            enhanced_data['configurations'] = configs
        except Exception as e:
            print(f"Warning: Config extraction failed: {e}")
            enhanced_data['configurations'] = {}

        # 3. Resource saturation detection
        if metrics_file.exists():
            from .resource_saturation_detector import ResourceSaturationDetector
            try:
                saturation_detector = ResourceSaturationDetector(metrics_file, fault_start_time)
                saturation_reports = saturation_detector.analyze_all(topology_data, enhanced_data['configurations'])
                enhanced_data['saturation_reports'] = {
                    node_id: report.to_dict()
                    for node_id, report in saturation_reports.items()
                }
            except Exception as e:
                print(f"Warning: Saturation detection failed: {e}")
                enhanced_data['saturation_reports'] = {}
        else:
            enhanced_data['saturation_reports'] = {}

        # 4. Causal chain analysis
        try:
            from .causal_chain_analyzer import CausalChainAnalyzer
            causal_analyzer = CausalChainAnalyzer(graph, root_cause_node)
            causal_analyses = causal_analyzer.analyze_all(
                [report.to_dict() for report in summary.node_reports],
                enhanced_data['latency_analyses'],
                enhanced_data['saturation_reports'],
                enhanced_data['configurations']
            )
            enhanced_data['causal_analyses'] = {
                node_id: analysis.to_dict()
                for node_id, analysis in causal_analyses.items()
            }
        except Exception as e:
            print(f"Warning: Causal analysis failed: {e}")
            enhanced_data['causal_analyses'] = {}

        # Add enhanced data to summary
        summary_dict = summary.to_dict()
        summary_dict['enhanced_analysis'] = enhanced_data

        # Enhance node reports with new data
        for report_dict in summary_dict['node_reports']:
            node_id = report_dict['node_id']
            if node_id in enhanced_data.get('latency_analyses', {}):
                report_dict['latency_analysis'] = enhanced_data['latency_analyses'][node_id]
            if node_id in enhanced_data.get('configurations', {}):
                report_dict['configuration_context'] = enhanced_data['configurations'][node_id]
            if node_id in enhanced_data.get('saturation_reports', {}):
                report_dict['saturation_report'] = enhanced_data['saturation_reports'][node_id]
            if node_id in enhanced_data.get('causal_analyses', {}):
                report_dict['causal_analysis'] = enhanced_data['causal_analyses'][node_id]

        # Save with enhanced data if requested
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(summary_dict, f, indent=2, default=str)
            return summary

    # Save if requested (without enhanced data)
    if output_file:
        summary.to_json(output_file)

    return summary
