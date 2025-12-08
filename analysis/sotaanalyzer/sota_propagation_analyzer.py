"""
SOTA Fault Propagation Analyzer

Integrates all analysis components to provide:
1. Discovery Mode: Blind root cause detection (without ground truth)
2. Validation Mode: Ground truth validation with distance-based analysis

Systematic approach:
- Pod-level forensics (outliers, hot pods, noisy neighbors)
- Health classification (nuanced thresholds)
- Root cause detection (leaf nodes, convergence, temporal)
- Network partition detection
- Causal chain analysis
"""

import json
import numpy as np
import pandas as pd
import networkx as nx
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict

from .pod_analysis import PodAnalyzer, ServicePodAnalysis
from .health_classifier import HealthClassifier, HealthClassification
from .root_cause_detector import RootCauseDetector, RootCauseCandidate, NetworkPartition
from ..propagation_analyzer import FaultPropagationAnalyzer, NodeImpactReport


@dataclass
class SOTAAnalysisResult:
    """Complete SOTA analysis result."""
    analysis_mode: str  # 'discovery' or 'validation'
    episode_id: str

    # Discovery mode outputs
    root_cause_candidates: List[RootCauseCandidate]
    network_partition: Optional[NetworkPartition]

    # Service-level summaries (pods aggregated)
    service_impact_summary: List[Dict]

    # Health classifications
    healthy_nodes: List[str]
    degraded_nodes: List[str]
    impacted_nodes: List[str]
    critical_nodes: List[str]

    # Node-level reports (includes pod analysis)
    node_reports: List[Dict]

    # Validation mode outputs (if ground truth provided)
    ground_truth_root_cause: Optional[str]
    validation_results: Optional[Dict]
    propagation_by_distance: Optional[Dict]

    # Metadata
    total_nodes_analyzed: int
    analysis_timestamp: str

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['root_cause_candidates'] = [rc.to_dict() for rc in self.root_cause_candidates]
        result['network_partition'] = self.network_partition.to_dict() if self.network_partition else None
        return result

    def to_json(self, filepath: Optional[str] = None, indent: int = 2) -> str:
        """Convert to JSON string or save to file."""
        json_str = json.dumps(self.to_dict(), indent=indent, default=str)

        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)

        return json_str


class SOTAPropagationAnalyzer:
    """
    State-of-the-art fault propagation analyzer.

    Implements systematic multi-layered analysis.
    """

    def __init__(
        self,
        metrics_df: pd.DataFrame,
        topology_graph: nx.DiGraph,
        topology_data: Dict,
        label_data: Dict,
        sample_interval: int = 5
    ):
        """
        Initialize SOTA analyzer.

        Args:
            metrics_df: Time-series metrics DataFrame
            topology_graph: NetworkX directed graph
            topology_data: Raw topology data (for pod analysis)
            label_data: Fault injection metadata
            sample_interval: Sampling interval in seconds
        """
        self.metrics_df = metrics_df
        self.graph = topology_graph
        self.topology_data = topology_data
        self.label_data = label_data
        self.sample_interval = sample_interval

        # Extract fault info
        self.fault_start_time = label_data.get('fault_start_time', 0)
        self.ground_truth_root_cause = label_data.get('root_cause_node')
        self.fault_type = label_data.get('fault_type', 'unknown')

        # Initialize sub-analyzers
        self.base_analyzer = FaultPropagationAnalyzer(
            metrics_df, topology_graph, label_data, sample_interval
        )

        self.pod_analyzer = PodAnalyzer(
            metrics_df, topology_data, outlier_threshold=1.5
        )

        self.health_classifier = HealthClassifier()

        self.root_cause_detector = RootCauseDetector(
            topology_graph, self.fault_start_time
        )

    def analyze(
        self,
        mode: str = 'discovery'
    ) -> SOTAAnalysisResult:
        """
        Perform complete SOTA analysis.

        Args:
            mode: 'discovery' (blind root cause detection) or 'validation' (ground truth)

        Returns:
            SOTAAnalysisResult with comprehensive outputs
        """
        print(f"🔍 Starting SOTA analysis (mode: {mode})...")

        # Phase 1: Base propagation analysis (all nodes)
        print("  Phase 1: Analyzing impact on all nodes...")
        base_summary = self.base_analyzer.analyze_propagation()
        node_reports = base_summary.node_reports

        # Phase 2: Pod-level analysis
        print("  Phase 2: Pod-level forensics...")
        pod_analyses = self._analyze_all_services(node_reports)

        # Phase 3: Health classification
        print("  Phase 3: Health classification...")
        health_classifications = self._classify_health(node_reports)

        healthy_nodes = self.health_classifier.get_healthy_nodes(health_classifications)
        degraded_nodes = self.health_classifier.get_impacted_nodes(health_classifications, 'DEGRADED')
        impacted_nodes = self.health_classifier.get_impacted_nodes(health_classifications, 'IMPACTED')
        critical_nodes = self.health_classifier.get_impacted_nodes(health_classifications, 'CRITICAL')

        print(f"    ✓ {len(healthy_nodes)} healthy, {len(critical_nodes)} critical")

        # Phase 4: Root cause detection
        print("  Phase 4: Root cause detection...")
        truly_impacted = [
            n for n in (degraded_nodes + impacted_nodes + critical_nodes)
            if n not in healthy_nodes
        ]

        root_cause_candidates = self._detect_root_causes(
            node_reports,
            truly_impacted,
            healthy_nodes,
            health_classifications
        )

        print(f"    ✓ Found {len(root_cause_candidates)} candidates")

        # Phase 5: Network partition detection
        print("  Phase 5: Network partition detection...")
        network_partition = self.root_cause_detector.detect_network_partition(
            [r.to_dict() for r in node_reports],
            truly_impacted
        )

        if network_partition:
            print(f"    ⚠️  Network partition detected!")

        # Phase 6: Service-level summary
        service_impact_summary = self._create_service_summary(node_reports, pod_analyses)

        # Phase 7: Validation (if mode == 'validation')
        validation_results = None
        propagation_by_distance = None

        if mode == 'validation' and self.ground_truth_root_cause:
            print("  Phase 6: Ground truth validation...")
            validation_results = self._validate_against_ground_truth(root_cause_candidates)
            propagation_by_distance = self._analyze_by_distance(node_reports, pod_analyses)

        # Build enhanced node reports with pod analysis
        enhanced_node_reports = self._enhance_node_reports(node_reports, pod_analyses, health_classifications)

        # Create result
        from datetime import datetime

        result = SOTAAnalysisResult(
            analysis_mode=mode,
            episode_id=str(self.label_data.get('episode', 'unknown')),
            root_cause_candidates=root_cause_candidates[:3],  # Top 3
            network_partition=network_partition,
            service_impact_summary=service_impact_summary,
            healthy_nodes=healthy_nodes,
            degraded_nodes=degraded_nodes,
            impacted_nodes=impacted_nodes,
            critical_nodes=critical_nodes,
            node_reports=enhanced_node_reports,
            ground_truth_root_cause=self.ground_truth_root_cause if mode == 'validation' else None,
            validation_results=validation_results,
            propagation_by_distance=propagation_by_distance,
            total_nodes_analyzed=len(node_reports),
            analysis_timestamp=datetime.now().isoformat()
        )

        print("✅ SOTA analysis complete!")
        return result

    def _analyze_all_services(
        self,
        node_reports: List[NodeImpactReport]
    ) -> Dict[str, ServicePodAnalysis]:
        """Perform pod analysis for all services."""
        # Build pod severity scores
        pod_severity_scores = {
            report.node_id: report.overall_severity_score
            for report in node_reports
        }

        # Get all services
        services = set(self.pod_analyzer.service_to_pods.keys())

        pod_analyses = {}

        for service_id in services:
            analysis = self.pod_analyzer.analyze_service(
                service_id,
                pod_severity_scores,
                self.fault_start_time
            )
            pod_analyses[service_id] = analysis

        return pod_analyses

    def _classify_health(
        self,
        node_reports: List[NodeImpactReport]
    ) -> List[HealthClassification]:
        """Classify health for all nodes."""
        classifications = []

        for report in node_reports:
            # Count metrics by severity
            metrics_by_severity = {
                'CRITICAL': report.metrics_with_critical_impact,
                'HIGH': report.metrics_with_high_impact,
                'MEDIUM': report.metrics_with_medium_impact,
                'LOW': report.metrics_with_low_impact,
                'NEGLIGIBLE': report.metrics_unchanged
            }

            classification = self.health_classifier.classify_node_health(
                node_id=report.node_id,
                overall_severity_score=report.overall_severity_score,
                metrics_by_severity=metrics_by_severity,
                ranked_metrics=report.ranked_metrics,
                total_metrics=report.total_metrics_analyzed
            )

            classifications.append(classification)

        return classifications

    def _detect_root_causes(
        self,
        node_reports: List[NodeImpactReport],
        impacted_nodes: List[str],
        healthy_nodes: List[str],
        health_classifications: List[HealthClassification]
    ) -> List[RootCauseCandidate]:
        """Detect and rank root cause candidates."""
        # Build health map
        health_map = {
            hc.node_id: hc.health_status
            for hc in health_classifications
        }

        # Identify candidates
        candidates = self.root_cause_detector.identify_root_cause_candidates(
            impacted_nodes, healthy_nodes, health_map
        )

        if not candidates:
            return []

        # Compute shortest paths
        candidate_paths = self.root_cause_detector.compute_shortest_paths(
            impacted_nodes, candidates
        )

        # Get severity scores and impact times
        node_severity_scores = {r.node_id: r.overall_severity_score for r in node_reports}
        node_first_impact_times = {r.node_id: r.first_impact_time for r in node_reports}
        node_ranked_metrics = {r.node_id: r.ranked_metrics for r in node_reports}

        # Compute centrality
        centrality_scores = self.root_cause_detector.compute_centrality_scores()

        # Rank candidates
        ranked_candidates = self.root_cause_detector.rank_root_cause_candidates(
            candidates=candidates,
            candidate_paths=candidate_paths,
            node_severity_scores=node_severity_scores,
            node_first_impact_times=node_first_impact_times,
            node_ranked_metrics=node_ranked_metrics,
            centrality_scores=centrality_scores,
            impacted_node_count=len(impacted_nodes),
            expected_fault_type=self.fault_type
        )

        return ranked_candidates

    def _create_service_summary(
        self,
        node_reports: List[NodeImpactReport],
        pod_analyses: Dict[str, ServicePodAnalysis]
    ) -> List[Dict]:
        """Create service-level impact summary (pods aggregated)."""
        summary = []

        # Get services
        for service_id, pod_analysis in pod_analyses.items():
            if pod_analysis.total_pods == 0:
                continue

            summary.append({
                'service_id': service_id,
                'total_pods': pod_analysis.total_pods,
                'aggregated_severity_score': pod_analysis.aggregated_severity_score,
                'pod_consensus': pod_analysis.pod_consensus,
                'consistent_impact': pod_analysis.consistent_impact,
                'outlier_pods_count': len(pod_analysis.outlier_pods),
                'hot_pods': pod_analysis.hot_pod_analysis.hot_pods if pod_analysis.hot_pod_analysis else [],
                'noisy_neighbor_count': len([n for n in pod_analysis.noisy_neighbor_analysis if n.is_noisy_neighbor])
            })

        # Sort by severity
        summary.sort(key=lambda s: s['aggregated_severity_score'], reverse=True)

        return summary

    def _validate_against_ground_truth(
        self,
        root_cause_candidates: List[RootCauseCandidate]
    ) -> Dict:
        """Validate detection against ground truth."""
        # Check if ground truth is in top-K
        detected_rank = None
        detected_probability = None

        for candidate in root_cause_candidates:
            if candidate.node_id == self.ground_truth_root_cause:
                detected_rank = candidate.rank
                detected_probability = candidate.probability
                break

        correct_detection = detected_rank is not None and detected_rank <= 3

        return {
            'root_cause_in_top_3': correct_detection,
            'detected_rank': detected_rank,
            'detection_probability': detected_probability,
            'correct_detection': detected_rank == 1 if detected_rank else False,
            'top_3_candidates': [c.node_id for c in root_cause_candidates[:3]]
        }

    def _analyze_by_distance(
        self,
        node_reports: List[NodeImpactReport],
        pod_analyses: Dict[str, ServicePodAnalysis]
    ) -> Dict:
        """Analyze propagation by distance from ground truth root cause."""
        if not self.ground_truth_root_cause:
            return {}

        # Group by distance
        by_distance = {}

        for report in node_reports:
            dist = report.distance_from_root
            if dist not in by_distance:
                by_distance[dist] = []

            # Add pod analysis if available
            pod_analysis = pod_analyses.get(report.node_id)

            by_distance[dist].append({
                'node_id': report.node_id,
                'node_type': report.node_type,
                'severity_score': report.overall_severity_score,
                'severity_class': report.overall_severity,
                'first_impact_time': report.first_impact_time,
                'pod_analysis': pod_analysis.to_dict() if pod_analysis and pod_analysis.total_pods > 0 else None
            })

        # Sort nodes within each distance by severity
        for dist in by_distance:
            by_distance[dist].sort(key=lambda n: n['severity_score'], reverse=True)

        return by_distance

    def _enhance_node_reports(
        self,
        node_reports: List[NodeImpactReport],
        pod_analyses: Dict[str, ServicePodAnalysis],
        health_classifications: List[HealthClassification]
    ) -> List[Dict]:
        """Enhance node reports with pod analysis and health classification."""
        # Build lookup maps
        health_map = {hc.node_id: hc for hc in health_classifications}

        enhanced = []

        for report in node_reports:
            report_dict = report.to_dict()

            # Add health classification
            health = health_map.get(report.node_id)
            if health:
                report_dict['health_classification'] = health.to_dict()

            # Add pod analysis (if multi-pod service)
            pod_analysis = pod_analyses.get(report.node_id)
            if pod_analysis and pod_analysis.total_pods > 0:
                report_dict['pod_analysis'] = pod_analysis.to_dict()

            enhanced.append(report_dict)

        return enhanced


def analyze_episode_sota(
    episode_dir: str,
    mode: str = 'discovery',
    sample_interval: int = 5,
    output_file: Optional[str] = None
) -> SOTAAnalysisResult:
    """
    Analyze episode using SOTA methods.

    Args:
        episode_dir: Path to episode directory
        mode: 'discovery' or 'validation'
        sample_interval: Time between samples (seconds)
        output_file: Optional output JSON file

    Returns:
        SOTAAnalysisResult
    """
    episode_path = Path(episode_dir)

    # Load data
    with open(episode_path / 'label.json') as f:
        label_data = json.load(f)

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
    analyzer = SOTAPropagationAnalyzer(
        metrics_df=metrics_df,
        topology_graph=graph,
        topology_data=topology_data,
        label_data=label_data,
        sample_interval=sample_interval
    )

    # Run analysis
    result = analyzer.analyze(mode=mode)

    # Save if requested
    if output_file:
        result.to_json(output_file)

    return result
