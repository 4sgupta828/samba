#!/usr/bin/env python3
"""
Deep Failure Analysis for RCA

For each failed RCA case, analyzes:
1. What was the topology structure
2. Ground truth root cause and fault type
3. Top candidates we found instead
4. WHY we missed the ground truth:
   - Did ground truth exhibit fault signature?
   - Did fault propagate properly?
   - Connection between false positives and ground truth
"""

import json
import networkx as nx
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple


class FailureAnalyzer:
    """Analyzes why RCA failed to detect ground truth."""

    def __init__(self, episode_dir: str):
        self.episode_dir = Path(episode_dir)
        self.load_data()

    def load_data(self):
        """Load all data files for the episode."""
        # Load label (ground truth)
        with open(self.episode_dir / 'label.json') as f:
            self.label = json.load(f)

        # Load topology
        with open(self.episode_dir / 'topology.json') as f:
            self.topology = json.load(f)

        # Build graph
        self.graph = nx.DiGraph()
        for node in self.topology['nodes']:
            self.graph.add_node(node['id'], **node)
        for edge in self.topology['edges']:
            self.graph.add_edge(edge['source'], edge['target'], **edge)

        # Load RCA analysis results
        analysis_file = self.episode_dir / 'rca_analysis.json'
        if analysis_file.exists():
            with open(analysis_file) as f:
                self.analysis = json.load(f)
        else:
            self.analysis = None

        # Load marker
        marker_file = self.episode_dir / 'RCAInvestigated.marker'
        if marker_file.exists():
            with open(marker_file) as f:
                self.marker = json.load(f)
        else:
            self.marker = None

    def analyze(self) -> Dict:
        """Perform comprehensive failure analysis."""
        gt_node = self.label['root_cause_node']
        fault_type = self.label['fault_type']

        # Get top candidates
        top_candidates = self.marker.get('top_k_candidates', []) if self.marker else []

        # 1. Check if ground truth was detected at all
        gt_in_candidates = self._find_ground_truth_in_analysis()

        # 2. Analyze ground truth node's metrics
        gt_metrics = self._analyze_ground_truth_metrics()

        # 3. Analyze false positives
        false_positive_analysis = self._analyze_false_positives(top_candidates[:3])

        # 4. Topology analysis
        topology_analysis = self._analyze_topology()

        # 5. Connection analysis between GT and false positives
        connection_analysis = self._analyze_connections(gt_node, top_candidates[:3])

        return {
            'episode': str(self.episode_dir),
            'ground_truth': gt_node,
            'fault_type': fault_type,
            'top_3_candidates': top_candidates[:3],
            'ground_truth_detected': gt_in_candidates is not None,
            'ground_truth_rank': gt_in_candidates['rank'] if gt_in_candidates else None,
            'ground_truth_metrics': gt_metrics,
            'false_positives': false_positive_analysis,
            'topology': topology_analysis,
            'connections': connection_analysis,
            'root_cause_hypothesis': self._generate_hypothesis(
                gt_metrics,
                false_positive_analysis,
                connection_analysis
            )
        }

    def _find_ground_truth_in_analysis(self) -> Dict:
        """Check if ground truth was in the candidate list at all."""
        if not self.analysis:
            return None

        gt_node = self.label['root_cause_node']

        for candidate in self.analysis.get('root_cause_candidates', []):
            if candidate['node_id'] == gt_node:
                return {
                    'rank': candidate['rank'],
                    'probability': candidate['probability'],
                    'confidence': candidate['confidence'],
                    'severity_score': candidate['severity_score'],
                    'reasoning': candidate['reasoning']
                }

        return None

    def _analyze_ground_truth_metrics(self) -> Dict:
        """Analyze the ground truth node's metrics and impact."""
        if not self.analysis:
            return {'error': 'No analysis data'}

        gt_node = self.label['root_cause_node']

        # Find ground truth in node reports
        gt_report = None
        for report in self.analysis.get('node_reports', []):
            if report['node_id'] == gt_node:
                gt_report = report
                break

        if not gt_report:
            return {
                'found': False,
                'reason': 'Ground truth node not in node reports (not analyzed)'
            }

        # Extract key metrics
        return {
            'found': True,
            'overall_severity_score': gt_report.get('overall_severity_score', 0),
            'overall_severity': gt_report.get('overall_severity', 'UNKNOWN'),
            'health_status': gt_report.get('health_classification', {}).get('health_status', 'UNKNOWN'),
            'first_impact_time': gt_report.get('first_impact_time'),
            'top_impacted_metrics': [
                {
                    'name': m['metric_name'],
                    'severity': m['severity_class'],
                    'baseline': m.get('baseline_mean'),
                    'fault': m.get('fault_mean')
                }
                for m in gt_report.get('ranked_metrics', [])[:5]
            ],
            'total_metrics_analyzed': gt_report.get('total_metrics_analyzed', 0),
            'critical_metrics': gt_report.get('metrics_with_critical_impact', 0),
            'high_metrics': gt_report.get('metrics_with_high_impact', 0)
        }

    def _analyze_false_positives(self, false_positives: List[str]) -> List[Dict]:
        """Analyze why false positives ranked higher."""
        if not self.analysis:
            return []

        fp_analysis = []

        for fp_node in false_positives:
            # Find in candidates
            fp_candidate = None
            for candidate in self.analysis.get('root_cause_candidates', []):
                if candidate['node_id'] == fp_node:
                    fp_candidate = candidate
                    break

            if not fp_candidate:
                continue

            # Find in node reports
            fp_report = None
            for report in self.analysis.get('node_reports', []):
                if report['node_id'] == fp_node:
                    fp_report = report
                    break

            fp_analysis.append({
                'node_id': fp_node,
                'node_type': self.graph.nodes[fp_node].get('type', 'Unknown'),
                'rank': fp_candidate['rank'],
                'probability': fp_candidate['probability'],
                'severity_score': fp_candidate['severity_score'],
                'is_leaf_node': fp_candidate['is_leaf_node'],
                'impacted_first': fp_candidate['impacted_first'],
                'convergence_score': fp_candidate['convergence_score'],
                'health_status': fp_report.get('health_classification', {}).get('health_status', 'UNKNOWN') if fp_report else 'UNKNOWN',
                'reasoning': fp_candidate['reasoning']
            })

        return fp_analysis

    def _analyze_topology(self) -> Dict:
        """Analyze topology structure."""
        gt_node = self.label['root_cause_node']

        # Check if GT node exists in graph
        if gt_node not in self.graph:
            return {
                'error': f'Ground truth node "{gt_node}" not in topology graph',
                'ground_truth_type': 'Unknown',
                'ground_truth_role': 'Unknown',
                'is_leaf_node': False,
                'dependencies_count': 0,
                'dependents_count': 0,
                'dependencies': [],
                'dependents': [],
                'total_nodes': len(self.graph.nodes()),
                'total_edges': len(self.graph.edges())
            }

        # Get ground truth node info
        gt_node_data = self.graph.nodes.get(gt_node, {})

        # Get dependencies and dependents
        dependencies = list(self.graph.successors(gt_node))  # Nodes GT calls
        dependents = list(self.graph.predecessors(gt_node))  # Nodes that call GT

        # Check if GT is a leaf node
        is_leaf = len(dependencies) == 0

        return {
            'ground_truth_type': gt_node_data.get('type', 'Unknown'),
            'ground_truth_role': gt_node_data.get('role', 'Unknown'),
            'is_leaf_node': is_leaf,
            'dependencies_count': len(dependencies),
            'dependents_count': len(dependents),
            'dependencies': dependencies,
            'dependents': dependents,
            'total_nodes': len(self.graph.nodes()),
            'total_edges': len(self.graph.edges())
        }

    def _analyze_connections(self, gt_node: str, false_positives: List[str]) -> Dict:
        """Analyze connections between ground truth and false positives."""
        connections = {}

        for fp in false_positives:
            if fp not in self.graph:
                connections[fp] = {'error': 'Node not in graph'}
                continue

            # 1. Direct sync call chain
            direct_paths = self._find_direct_paths(gt_node, fp)

            # 2. Shared compute nodes (for pods)
            shared_compute = self._find_shared_compute_nodes(gt_node, fp)

            # 3. Async connections (via queues)
            async_connections = self._find_async_connections(gt_node, fp)

            # 4. Distance in graph
            try:
                distance = nx.shortest_path_length(self.graph.to_undirected(), gt_node, fp)
            except nx.NetworkXNoPath:
                distance = None

            connections[fp] = {
                'direct_paths': direct_paths,
                'shared_compute_nodes': shared_compute,
                'async_connections': async_connections,
                'graph_distance': distance,
                'has_any_connection': bool(direct_paths or shared_compute or async_connections)
            }

        return connections

    def _find_direct_paths(self, source: str, target: str) -> List[List[str]]:
        """Find direct sync call paths between two nodes."""
        try:
            # Find all simple paths (up to length 5)
            paths = list(nx.all_simple_paths(self.graph, source, target, cutoff=5))
            return paths[:3]  # Return up to 3 paths
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def _find_shared_compute_nodes(self, node1: str, node2: str) -> List[str]:
        """Find compute nodes shared by two nodes (for pods)."""
        node1_data = self.graph.nodes.get(node1, {})
        node2_data = self.graph.nodes.get(node2, {})

        compute1 = node1_data.get('compute_node')
        compute2 = node2_data.get('compute_node')

        if compute1 and compute2 and compute1 == compute2:
            return [compute1]

        return []

    def _find_async_connections(self, source: str, target: str) -> List[Dict]:
        """Find async connections via message queues."""
        connections = []

        # Look for queue-based connections
        # Source -> Queue -> Target
        for intermediate in self.graph.nodes():
            node_data = self.graph.nodes[intermediate]
            if node_data.get('type') == 'MessageQueue':
                # Check if source produces to queue and target consumes from queue
                source_to_queue = self.graph.has_edge(source, intermediate)
                queue_to_target = self.graph.has_edge(intermediate, target)

                if source_to_queue and queue_to_target:
                    connections.append({
                        'queue': intermediate,
                        'pattern': 'producer->queue->consumer'
                    })

        return connections

    def _generate_hypothesis(
        self,
        gt_metrics: Dict,
        false_positives: List[Dict],
        connections: Dict
    ) -> List[str]:
        """Generate hypotheses for why RCA failed."""
        hypotheses = []

        # Check if ground truth was analyzed
        if not gt_metrics.get('found'):
            hypotheses.append(
                "❌ CRITICAL: Ground truth node was not analyzed at all. "
                "Possible reasons: (1) Not in topology, (2) No metrics collected, "
                "(3) Filtered out during preprocessing"
            )
            return hypotheses

        # Check severity
        severity = gt_metrics.get('overall_severity_score', 0)
        health = gt_metrics.get('health_status', 'UNKNOWN')

        if severity < 0.1:
            hypotheses.append(
                f"❌ LOW IMPACT: Ground truth severity score is very low ({severity:.3f}). "
                f"The fault may not have significantly impacted this node's metrics. "
                f"Health status: {health}"
            )

        if health == 'HEALTHY':
            hypotheses.append(
                f"❌ CLASSIFIED HEALTHY: Ground truth was classified as HEALTHY despite being root cause. "
                f"The fault signature may be subtle or metrics may not capture the fault well."
            )

        # Check if it's a service (known issue)
        if gt_metrics.get('found'):
            # Find GT node type from topology
            gt_node = self.label['root_cause_node']
            gt_type = self.graph.nodes.get(gt_node, {}).get('type', 'Unknown')

            if gt_type in ['InternalService', 'BackgroundService']:
                hypotheses.append(
                    f"⚠️  SERVICE-LEVEL FAULT: Ground truth is a {gt_type}. "
                    f"Algorithm currently struggles with service-level faults (0% success rate). "
                    f"Services may show less severe metric changes than their dependencies."
                )

        # Compare with false positives
        if false_positives:
            fp_severities = [fp['severity_score'] for fp in false_positives]
            avg_fp_severity = sum(fp_severities) / len(fp_severities)

            if avg_fp_severity > severity:
                hypotheses.append(
                    f"⚠️  FALSE POSITIVES MORE SEVERE: Top false positives have higher severity "
                    f"({avg_fp_severity:.3f} vs {severity:.3f}). They may be heavily impacted victims "
                    f"that look more like root causes."
                )

            # Check if false positives are downstream
            fp_nodes = [fp['node_id'] for fp in false_positives]
            downstream_fps = []

            for fp in fp_nodes:
                conn = connections.get(fp, {})
                if conn.get('has_any_connection'):
                    downstream_fps.append(fp)

            if downstream_fps:
                hypotheses.append(
                    f"⚠️  CONNECTED FALSE POSITIVES: {len(downstream_fps)} of top-3 false positives "
                    f"are connected to ground truth: {', '.join(downstream_fps)}. "
                    f"These are likely heavily impacted downstream components that appear worse than the root cause."
                )

            # Check leaf node bias
            fp_leaf_count = sum(1 for fp in false_positives if fp['is_leaf_node'])
            if fp_leaf_count == len(false_positives):
                hypotheses.append(
                    f"⚠️  LEAF NODE BIAS: All top-3 candidates are leaf nodes. "
                    f"Algorithm may be over-prioritizing leaf nodes in scoring."
                )

        # Check metric signature
        critical_metrics = gt_metrics.get('critical_metrics', 0)
        high_metrics = gt_metrics.get('high_metrics', 0)

        if critical_metrics == 0 and high_metrics == 0:
            hypotheses.append(
                f"❌ WEAK FAULT SIGNATURE: Ground truth has no critical or high-severity metrics. "
                f"The fault may not be manifesting in observable metrics, or metrics may be inadequate."
            )

        # Check temporal aspects
        first_impact = gt_metrics.get('first_impact_time')
        if first_impact is None:
            hypotheses.append(
                f"⚠️  NO IMPACT TIME: Ground truth node has no recorded first impact time. "
                f"Temporal analysis may have excluded it from candidates."
            )

        if not hypotheses:
            hypotheses.append(
                "❓ UNCLEAR: Ground truth was analyzed and showed some impact, "
                "but still ranked lower than false positives. May need deeper investigation."
            )

        return hypotheses


def analyze_all_failures(base_dir: str = 'data/batch_run'):
    """Analyze all failed RCA cases."""
    base_path = Path(base_dir)

    # Find all failures
    failures = []
    for marker_file in base_path.rglob('RCAInvestigated.marker'):
        with open(marker_file) as f:
            marker = json.load(f)

        # Check if it's a failure
        if not marker.get('success'):
            failures.append(marker_file.parent)

    print(f"{'='*80}")
    print(f"DEEP FAILURE ANALYSIS")
    print(f"{'='*80}")
    print(f"Found {len(failures)} failed RCA cases to analyze\n")

    # Analyze each failure
    results = []
    for i, episode_dir in enumerate(failures, 1):
        print(f"\n{'='*80}")
        print(f"FAILURE #{i}: {episode_dir.name}")
        print(f"{'='*80}\n")

        try:
            analyzer = FailureAnalyzer(str(episode_dir))
            result = analyzer.analyze()
            results.append(result)

            # Print analysis
            print_failure_analysis(result)

        except Exception as e:
            print(f"❌ Error analyzing {episode_dir}: {e}")
            import traceback
            traceback.print_exc()

    # Summary statistics
    print(f"\n{'='*80}")
    print(f"FAILURE PATTERN SUMMARY")
    print(f"{'='*80}\n")
    print_failure_summary(results)

    return results


def print_failure_analysis(result: Dict):
    """Print detailed analysis for a single failure."""
    print(f"Ground Truth: {result['ground_truth']}")
    print(f"Fault Type: {result['fault_type']}")
    print(f"Ground Truth Detected: {'Yes' if result['ground_truth_detected'] else 'No'}")
    if result['ground_truth_rank']:
        print(f"Ground Truth Rank: {result['ground_truth_rank']} (outside top-K)")
    print()

    print("Top 3 Candidates Found:")
    for i, candidate in enumerate(result['top_3_candidates'], 1):
        print(f"  {i}. {candidate}")
    print()

    # Ground truth metrics
    print("Ground Truth Metrics:")
    gt_metrics = result['ground_truth_metrics']
    if gt_metrics.get('found'):
        print(f"  Severity Score: {gt_metrics.get('overall_severity_score', 0):.3f}")
        print(f"  Health Status: {gt_metrics.get('health_status', 'UNKNOWN')}")
        print(f"  Critical Metrics: {gt_metrics.get('critical_metrics', 0)}")
        print(f"  High Metrics: {gt_metrics.get('high_metrics', 0)}")
        print(f"  Top Impacted Metrics:")
        for metric in gt_metrics.get('top_impacted_metrics', [])[:3]:
            print(f"    - {metric['name']}: {metric['severity']}")
    else:
        print(f"  ❌ {gt_metrics.get('reason', 'Not analyzed')}")
    print()

    # Topology
    print("Topology:")
    topo = result['topology']
    print(f"  GT Type: {topo['ground_truth_type']}")
    print(f"  GT Role: {topo['ground_truth_role']}")
    print(f"  Is Leaf: {topo['is_leaf_node']}")
    print(f"  Dependencies: {topo['dependencies_count']} nodes")
    print(f"  Dependents: {topo['dependents_count']} nodes")
    print()

    # Connections
    print("Connections (GT → False Positives):")
    for fp, conn in result['connections'].items():
        if conn.get('error'):
            print(f"  {fp}: {conn['error']}")
            continue

        print(f"  {fp}:")
        print(f"    Graph Distance: {conn['graph_distance']}")
        print(f"    Direct Paths: {len(conn['direct_paths'])} found")
        if conn['direct_paths']:
            for path in conn['direct_paths'][:2]:
                print(f"      - {' → '.join(path)}")
        print(f"    Shared Compute: {conn['shared_compute_nodes']}")
        print(f"    Async Connections: {len(conn['async_connections'])} found")
        print(f"    Has Connection: {conn['has_any_connection']}")
    print()

    # Hypotheses
    print("Root Cause Hypotheses (Why we missed it):")
    for i, hypothesis in enumerate(result['root_cause_hypothesis'], 1):
        print(f"  {i}. {hypothesis}")
    print()


def print_failure_summary(results: List[Dict]):
    """Print summary statistics across all failures."""
    from collections import Counter

    total = len(results)

    # Ground truth detected but ranked low
    detected = sum(1 for r in results if r['ground_truth_detected'])
    print(f"Ground Truth Detected (but not in top-K): {detected}/{total} ({detected/total*100:.1f}%)")
    print()

    # Failure reasons
    print("Common Failure Patterns:")

    # Service-level faults
    service_faults = sum(1 for r in results
                        if 'service' in r['topology']['ground_truth_type'].lower())
    if service_faults:
        print(f"  - Service-level faults: {service_faults}/{total} ({service_faults/total*100:.1f}%)")

    # Low severity
    low_severity = sum(1 for r in results
                      if r['ground_truth_metrics'].get('found') and
                      r['ground_truth_metrics'].get('overall_severity_score', 0) < 0.1)
    if low_severity:
        print(f"  - Low severity (<0.1): {low_severity}/{total} ({low_severity/total*100:.1f}%)")

    # Classified healthy
    healthy = sum(1 for r in results
                 if r['ground_truth_metrics'].get('health_status') == 'HEALTHY')
    if healthy:
        print(f"  - Classified as HEALTHY: {healthy}/{total} ({healthy/total*100:.1f}%)")

    # Not analyzed
    not_analyzed = sum(1 for r in results if not r['ground_truth_metrics'].get('found'))
    if not_analyzed:
        print(f"  - Not analyzed at all: {not_analyzed}/{total} ({not_analyzed/total*100:.1f}%)")

    print()

    # Fault type distribution
    print("Failures by Fault Type:")
    fault_types = Counter(r['fault_type'] for r in results)
    for ft, count in fault_types.most_common():
        print(f"  - {ft}: {count}")


if __name__ == "__main__":
    import sys
    base_dir = sys.argv[1] if len(sys.argv) > 1 else 'data/batch_run'
    analyze_all_failures(base_dir)
