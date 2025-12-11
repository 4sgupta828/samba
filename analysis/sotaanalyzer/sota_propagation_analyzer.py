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
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict

from .pod_analysis import PodAnalyzer, ServicePodAnalysis
from .health_classifier import HealthClassifier, HealthClassification
from .root_cause_detector import RootCauseDetector, RootCauseCandidate, NetworkPartition
from .self_health_analyzer import SelfHealthAnalyzer, SelfHealthAnalysis
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

        # Build pod-to-service mapping
        self.pod_to_service = {}
        self.service_to_pods = {}
        for node in topology_data['nodes']:
            if node['type'] == 'Pod':
                pod_id = node['id']
                # Try both 'parent_service' and 'service_name' for compatibility
                service_name = node.get('parent_service') or node.get('service_name')
                if service_name:
                    self.pod_to_service[pod_id] = service_name
                    if service_name not in self.service_to_pods:
                        self.service_to_pods[service_name] = []
                    self.service_to_pods[service_name].append(pod_id)

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

        self.self_health_analyzer = SelfHealthAnalyzer()

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

    def _aggregate_pods_to_services(
        self,
        node_reports: List[NodeImpactReport],
        health_classifications: List[HealthClassification]
    ) -> Tuple[Dict, Dict, Dict]:
        """
        Aggregate pod-level data to service level.

        Returns:
            (service_severity_scores, service_health_map, service_to_pod_details)
        """
        service_severity_scores = {}
        service_health_levels = {}
        service_to_pod_details = {}

        # Health level ordering
        health_order = {'HEALTHY': 0, 'DEGRADED': 1, 'IMPACTED': 2, 'CRITICAL': 3}

        # Build health map
        health_map = {hc.node_id: hc.health_status for hc in health_classifications}

        # Aggregate pods to services
        for service_name, pod_ids in self.service_to_pods.items():
            pod_severities = []
            pod_healths = []
            pod_details = []

            for pod_id in pod_ids:
                # Find pod report
                pod_report = next((r for r in node_reports if r.node_id == pod_id), None)
                if pod_report:
                    pod_severities.append(pod_report.overall_severity_score)
                    pod_healths.append(health_map.get(pod_id, 'HEALTHY'))
                    pod_details.append({
                        'pod_id': pod_id,
                        'severity': pod_report.overall_severity_score,
                        'health': health_map.get(pod_id, 'HEALTHY'),
                        'first_impact_time': pod_report.first_impact_time
                    })

            if pod_severities:
                # Aggregate severity: use max (worst pod)
                service_severity_scores[service_name] = max(pod_severities)

                # Aggregate health: use worst health level
                worst_health = max(pod_healths, key=lambda h: health_order.get(h, 0))
                service_health_levels[service_name] = worst_health

                service_to_pod_details[service_name] = {
                    'pods': pod_details,
                    'pod_count': len(pod_ids),
                    'avg_severity': np.mean(pod_severities),
                    'max_severity': max(pod_severities),
                    'consensus': sum(1 for h in pod_healths if h != 'HEALTHY') / len(pod_healths)
                }

        return service_severity_scores, service_health_levels, service_to_pod_details

    def _map_nodes_to_services(
        self,
        node_list: List[str]
    ) -> List[str]:
        """
        Map a list of nodes to service-level identifiers.

        - Pods get mapped to their service name
        - Non-pods keep their original ID

        Returns unique service-level nodes.
        """
        service_level_nodes = set()

        for node_id in node_list:
            if node_id in self.pod_to_service:
                # This is a pod, map to service
                service_level_nodes.add(self.pod_to_service[node_id])
            else:
                # Keep original (database, cache, external service, etc.)
                service_level_nodes.add(node_id)

        return list(service_level_nodes)

    def _detect_root_causes(
        self,
        node_reports: List[NodeImpactReport],
        impacted_nodes: List[str],
        healthy_nodes: List[str],
        health_classifications: List[HealthClassification]
    ) -> List[RootCauseCandidate]:
        """
        Detect and rank root cause candidates at SERVICE level.

        UPDATED: Now includes self-health analysis to better identify service nodes
        with internal faults vs those with only downstream issues.

        For pods, aggregates to service level first to avoid dilution.
        Then drills down to identify outlier pods within root cause services.
        """
        # Build health map
        health_map = {
            hc.node_id: hc.health_status
            for hc in health_classifications
        }

        # Aggregate pods to services
        service_severity_scores, service_health_map, service_pod_details = \
            self._aggregate_pods_to_services(node_reports, health_classifications)

        # Map impacted/healthy nodes to service level
        service_level_impacted = self._map_nodes_to_services(impacted_nodes)
        service_level_healthy = self._map_nodes_to_services(healthy_nodes)

        # Merge service-level health with node-level health
        combined_health_map = {**health_map, **service_health_map}

        # Get severity scores and impact times (service-level) - MOVED UP before candidate identification
        node_severity_scores = {r.node_id: r.overall_severity_score for r in node_reports}
        # Merge with service-level severity
        combined_severity_scores = {**node_severity_scores, **service_severity_scores}

        node_first_impact_times = {r.node_id: r.first_impact_time for r in node_reports}
        # For services, use earliest pod impact time
        for service_name, details in service_pod_details.items():
            pod_times = [p['first_impact_time'] for p in details['pods'] if p['first_impact_time']]
            if pod_times:
                node_first_impact_times[service_name] = min(pod_times)

        node_ranked_metrics = {r.node_id: r.ranked_metrics for r in node_reports}
        # For services, use worst pod's metrics
        for service_name, details in service_pod_details.items():
            worst_pod = max(details['pods'], key=lambda p: p['severity'])
            worst_pod_metrics = node_ranked_metrics.get(worst_pod['pod_id'], [])
            node_ranked_metrics[service_name] = worst_pod_metrics

        # Identify candidates at service level (NOW with metrics for self-health analysis)
        candidates = self.root_cause_detector.identify_root_cause_candidates(
            service_level_impacted,
            service_level_healthy,
            combined_health_map,
            node_ranked_metrics=node_ranked_metrics  # NEW: pass metrics for self-health check
        )

        if not candidates:
            return []

        # Compute shortest paths (using service-level nodes for pods)
        candidate_paths = self.root_cause_detector.compute_shortest_paths(
            service_level_impacted, candidates
        )

        # NEW: Perform self-health analysis on all candidates
        print("    Performing self-health analysis on candidates...")
        self_health_analyses = {}
        for candidate in candidates:
            ranked_metrics = node_ranked_metrics.get(candidate, [])
            # Get node type
            node_type = self.graph.nodes.get(candidate, {}).get('type', 'Service')

            sha = self.self_health_analyzer.analyze_node_self_health(
                node_id=candidate,
                ranked_metrics=ranked_metrics,
                node_type=node_type
            )
            self_health_analyses[candidate] = sha

            # Log self-health findings
            if sha.is_likely_root_cause:
                print(f"      {candidate}: Root cause likely (self-degradation: {sha.self_degradation_score:.2f})")
            elif sha.is_likely_victim:
                print(f"      {candidate}: Victim likely (only dependency issues)")

        # Compute centrality
        centrality_scores = self.root_cause_detector.compute_centrality_scores()

        # Rank candidates (now with self-health analysis)
        ranked_candidates = self.root_cause_detector.rank_root_cause_candidates(
            candidates=candidates,
            candidate_paths=candidate_paths,
            node_severity_scores=combined_severity_scores,
            node_first_impact_times=node_first_impact_times,
            node_ranked_metrics=node_ranked_metrics,
            centrality_scores=centrality_scores,
            impacted_node_count=len(service_level_impacted),
            expected_fault_type=self.fault_type,
            self_health_analyses=self_health_analyses  # NEW
        )

        # Enhance candidates with pod-level details and self-health analysis
        for candidate in ranked_candidates:
            if candidate.node_id in service_pod_details:
                candidate.service_pod_details = service_pod_details[candidate.node_id]
            else:
                candidate.service_pod_details = None

            # Add self-health analysis to candidate
            if candidate.node_id in self_health_analyses:
                candidate.self_health_analysis = self_health_analyses[candidate.node_id].to_dict()

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


def validate_rca_discovery(
    result: SOTAAnalysisResult,
    ground_truth_root_cause: str,
    pod_to_service_map: Optional[Dict[str, str]] = None,
    top_k: int = 5
) -> Dict:
    """
    Validate if ground truth root cause is in top-K candidates from discovery mode.

    Handles service-level RCA: if ground truth is a pod, checks if its service is in top-K.

    Args:
        result: SOTAAnalysisResult from discovery mode
        ground_truth_root_cause: The actual root cause node (might be a pod)
        pod_to_service_map: Optional mapping of pod IDs to service names
        top_k: Number of top candidates to check (default: 5)

    Returns:
        Dictionary with validation results
    """
    top_k_candidates = [c.node_id for c in result.root_cause_candidates[:top_k]]

    # Check if ground truth is a pod that should be mapped to service
    ground_truth_service = None
    if pod_to_service_map and ground_truth_root_cause in pod_to_service_map:
        ground_truth_service = pod_to_service_map[ground_truth_root_cause]

    # Check if ground truth (or its service) is in top-K
    found_in_top_k = (
        ground_truth_root_cause in top_k_candidates or
        (ground_truth_service and ground_truth_service in top_k_candidates)
    )

    # Find rank if present (check both pod ID and service name)
    rank = None
    confidence = None
    matched_as = None  # 'direct' or 'service'

    for i, candidate in enumerate(result.root_cause_candidates, 1):
        if candidate.node_id == ground_truth_root_cause:
            rank = i
            confidence = candidate.probability
            matched_as = 'direct'
            break
        elif ground_truth_service and candidate.node_id == ground_truth_service:
            rank = i
            confidence = candidate.probability
            matched_as = 'service'
            break

    # If matched as service, include pod details
    pod_details = None
    if matched_as == 'service' and rank and rank <= top_k:
        matched_candidate = result.root_cause_candidates[rank - 1]
        if hasattr(matched_candidate, 'service_pod_details') and matched_candidate.service_pod_details:
            pod_details = matched_candidate.service_pod_details

    validation_result = {
        'success': found_in_top_k,
        'ground_truth': ground_truth_root_cause,
        'ground_truth_service': ground_truth_service,
        'top_k': top_k,
        'top_k_candidates': top_k_candidates,
        'rank': rank,
        'confidence': confidence,
        'matched_as': matched_as,
        'pod_details': pod_details,
        'total_candidates': len(result.root_cause_candidates)
    }

    return validation_result


def mark_episode_as_rca_investigated(
    episode_dir: str,
    validation_result: Dict
) -> None:
    """
    Create a marker file to indicate RCA has been investigated.

    Args:
        episode_dir: Path to episode directory
        validation_result: Validation results from validate_rca_discovery
    """
    episode_path = Path(episode_dir)
    marker_file = episode_path / 'RCAInvestigated.marker'

    # Write validation results to marker file
    with open(marker_file, 'w') as f:
        json.dump(validation_result, f, indent=2)

    print(f"✅ Created RCA investigation marker: {marker_file}")


def mark_episode_as_rca_failed(
    episode_dir: str,
    error_info: Dict
) -> None:
    """
    Create a marker file to indicate RCA failed for this episode.

    Args:
        episode_dir: Path to episode directory
        error_info: Error information (error message, traceback, etc.)
    """
    episode_path = Path(episode_dir)
    marker_file = episode_path / 'RCAFailed.marker'

    # Write error info to marker file
    from datetime import datetime
    error_data = {
        'failed_at': datetime.now().isoformat(),
        'error': error_info.get('error', 'Unknown error'),
        'error_type': error_info.get('error_type', 'Unknown'),
        'traceback': error_info.get('traceback', None)
    }

    with open(marker_file, 'w') as f:
        json.dump(error_data, f, indent=2)

    print(f"⚠️  Created RCA failure marker: {marker_file}")


def discover_and_validate_rca(
    episode_dir: str,
    sample_interval: int = 5,
    output_file: Optional[str] = None,
    create_marker: bool = True,
    top_k: int = 5
) -> Dict:
    """
    Run discovery mode RCA analysis and validate against ground truth.

    This function:
    1. Runs discovery mode analysis WITHOUT using ground truth for detection
    2. Checks if ground truth root cause is in top-K candidates
    3. Optionally creates a marker file if successful
    4. Returns comprehensive validation results

    Args:
        episode_dir: Path to episode directory
        sample_interval: Time between samples (seconds)
        output_file: Optional output JSON file for full analysis
        create_marker: Whether to create marker file on success
        top_k: Number of top candidates to check (default: 5)

    Returns:
        Dictionary with validation results and metadata
    """
    episode_path = Path(episode_dir)

    # Check if already investigated
    marker_file = episode_path / 'RCAInvestigated.marker'
    if marker_file.exists():
        print(f"⏭️  Episode already investigated: {episode_dir}")
        with open(marker_file, 'r') as f:
            existing_result = json.load(f)
        return {
            'already_investigated': True,
            'validation_result': existing_result
        }

    # Load ground truth
    with open(episode_path / 'label.json') as f:
        label_data = json.load(f)

    ground_truth_root_cause = label_data.get('root_cause_node')

    if not ground_truth_root_cause:
        raise ValueError(f"No root_cause_node found in label.json for {episode_dir}")

    # Load topology to build pod-to-service mapping
    with open(episode_path / 'topology.json') as f:
        topology_data = json.load(f)

    pod_to_service_map = {}
    for node in topology_data['nodes']:
        if node['type'] == 'Pod':
            # Try both 'parent_service' and 'service_name' for compatibility
            service_name = node.get('parent_service') or node.get('service_name')
            if service_name:
                pod_to_service_map[node['id']] = service_name

    # Check if ground truth is a pod
    ground_truth_service = pod_to_service_map.get(ground_truth_root_cause)

    print(f"🔍 Running discovery mode RCA analysis on: {episode_dir}")
    print(f"   Ground truth (hidden from analyzer): {ground_truth_root_cause}")
    if ground_truth_service:
        print(f"   Ground truth service: {ground_truth_service}")

    # Run discovery mode analysis
    result = analyze_episode_sota(
        episode_dir=episode_dir,
        mode='discovery',  # Discovery mode doesn't use ground truth for detection
        sample_interval=sample_interval,
        output_file=output_file
    )

    print(f"\n📊 Top {top_k} RCA candidates identified (service-level):")
    for i, candidate in enumerate(result.root_cause_candidates[:top_k], 1):
        print(f"   {i}. {candidate.node_id} (confidence: {candidate.probability:.3f})")
        # Show pod details if available
        if hasattr(candidate, 'service_pod_details') and candidate.service_pod_details:
            pod_info = candidate.service_pod_details
            print(f"      └─ {pod_info['pod_count']} pods, consensus: {pod_info['consensus']:.1%}")

    # Validate against ground truth
    validation_result = validate_rca_discovery(result, ground_truth_root_cause, pod_to_service_map, top_k)

    # Print results
    print(f"\n{'='*60}")
    if validation_result['success']:
        matched_as = validation_result.get('matched_as', 'unknown')
        if matched_as == 'service' and ground_truth_service:
            print(f"✅ SUCCESS: Ground truth service '{ground_truth_service}' found at rank {validation_result['rank']}")
            print(f"   Ground truth pod: {ground_truth_root_cause}")
        else:
            print(f"✅ SUCCESS: Ground truth '{ground_truth_root_cause}' found at rank {validation_result['rank']}")
        print(f"   Confidence: {validation_result['confidence']:.3f}")

        # Show pod details if matched as service
        if matched_as == 'service' and validation_result.get('pod_details'):
            pod_details = validation_result['pod_details']
            print(f"\n   Pod Analysis for {ground_truth_service}:")
            print(f"   - Total pods: {pod_details['pod_count']}")
            print(f"   - Avg severity: {pod_details['avg_severity']:.3f}")
            print(f"   - Max severity: {pod_details['max_severity']:.3f}")
            print(f"   - Impact consensus: {pod_details['consensus']:.1%}")
    else:
        if ground_truth_service:
            print(f"❌ NOT IN TOP-{top_k}: Ground truth service '{ground_truth_service}' (pod: {ground_truth_root_cause})")
        else:
            print(f"❌ NOT IN TOP-{top_k}: Ground truth '{ground_truth_root_cause}'")
        print(f"   Top {top_k} were: {validation_result['top_k_candidates']}")
        if validation_result['rank']:
            print(f"   Ground truth was at rank: {validation_result['rank']}")
        else:
            print(f"   Ground truth was not detected at all")
    print(f"{'='*60}\n")

    # Always create marker file to track processed episodes
    if create_marker:
        mark_episode_as_rca_investigated(episode_dir, validation_result)

    return {
        'already_investigated': False,
        'validation_result': validation_result,
        'episode_dir': episode_dir,
        'analysis_mode': result.analysis_mode,
        'total_candidates': len(result.root_cause_candidates)
    }
