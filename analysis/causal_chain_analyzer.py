"""
Causal Chain Analyzer

Builds mechanistic explanations of HOW and WHY faults propagated through
the system by analyzing:
- Latency increases and their downstream effects
- Resource saturation and resulting backpressure
- Retry amplification from timeout failures
- Configuration settings that shaped behavior
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import networkx as nx


@dataclass
class CausalStep:
    """A single step in the causal chain."""
    step_number: int
    observation: str
    cause: str
    consequence: str
    metrics: Dict

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class CausalAnalysis:
    """Complete causal analysis for a node's impact."""
    node_id: str
    node_type: str
    distance_from_root: int
    primary_mechanism: str
    why_impacted: str
    causal_chain: List[CausalStep]
    configuration_factors: List[str]
    summary: str

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'node_id': self.node_id,
            'node_type': self.node_type,
            'distance_from_root': self.distance_from_root,
            'primary_mechanism': self.primary_mechanism,
            'why_impacted': self.why_impacted,
            'causal_chain': [step.to_dict() for step in self.causal_chain],
            'configuration_factors': self.configuration_factors,
            'summary': self.summary
        }


class CausalChainAnalyzer:
    """Analyzes causal mechanisms of fault propagation."""

    # Common propagation mechanisms
    MECHANISMS = {
        'direct_latency': 'Direct dependency latency increase',
        'connection_pool_saturation': 'Connection pool saturation',
        'retry_amplification': 'Retry storm amplification',
        'timeout_cascade': 'Cascading timeout failures',
        'queue_buildup': 'Queue backpressure',
        'resource_exhaustion': 'Resource exhaustion (CPU/memory)',
        'error_propagation': 'Error propagation',
        'circuit_breaker': 'Circuit breaker activation'
    }

    def __init__(self, topology_graph: nx.DiGraph, root_cause_node: str):
        """
        Initialize analyzer.

        Args:
            topology_graph: NetworkX graph of system topology
            root_cause_node: ID of root cause node
        """
        self.graph = topology_graph
        self.root_cause = root_cause_node

    def identify_mechanism(
        self,
        node_id: str,
        node_report: Dict,
        latency_analysis: Optional[Dict],
        saturation_report: Optional[Dict],
        config: Optional[Dict]
    ) -> str:
        """
        Identify primary propagation mechanism for a node.

        Args:
            node_id: Node identifier
            node_report: Node impact report from propagation analyzer
            latency_analysis: Latency analysis from traces
            saturation_report: Resource saturation report
            config: Configuration context

        Returns:
            Mechanism identifier
        """
        # Check for saturation
        if saturation_report:
            peak_util = saturation_report.get('peak_utilization', {})
            if 'connection_pool' in peak_util and peak_util['connection_pool'] > 90:
                return 'connection_pool_saturation'
            if 'cpu' in peak_util and peak_util['cpu'] > 90:
                return 'resource_exhaustion'
            if 'message_queue' in peak_util:
                return 'queue_buildup'

        # Check for latency increase
        if latency_analysis:
            degradation = latency_analysis.get('degradation_factor', 1.0)
            if degradation >= 2.0:
                return 'direct_latency'

        # Check for error rate increase
        metrics = node_report.get('ranked_metrics', [])
        for metric in metrics:
            metric_name = metric.get('metric_name', '')
            if 'error' in metric_name.lower():
                severity = metric.get('severity_class', '')
                if severity in ['HIGH', 'CRITICAL']:
                    return 'error_propagation'

        # Check for throughput collapse (circuit breaker likely)
        for metric in metrics:
            if 'request' in metric.get('metric_name', '').lower():
                mean_change = metric.get('mean_change_pct', 0)
                if mean_change < -70:  # 70%+ drop
                    return 'circuit_breaker'

        return 'direct_latency'  # Default

    def build_causal_chain(
        self,
        node_id: str,
        node_type: str,
        mechanism: str,
        node_report: Dict,
        latency_analysis: Optional[Dict],
        saturation_report: Optional[Dict],
        config: Optional[Dict],
        dependencies: List[str]
    ) -> List[CausalStep]:
        """
        Build step-by-step causal chain for this node's impact.

        Args:
            node_id: Node identifier
            node_type: Type of node
            mechanism: Primary propagation mechanism
            node_report: Impact report
            latency_analysis: Latency data
            saturation_report: Saturation data
            config: Configuration
            dependencies: List of direct dependencies

        Returns:
            List of causal steps
        """
        steps = []
        step_num = 1

        # Step 1: What happened in dependencies (if not root cause)
        if dependencies and latency_analysis and node_id != self.root_cause:
            dep_latency_info = ""
            if latency_analysis:
                baseline = latency_analysis.get('baseline', {})
                fault = latency_analysis.get('fault', {})
                deg_factor = latency_analysis.get('degradation_factor', 1.0)

                dep_latency_info = (
                    f"Latency increased {deg_factor:.1f}x "
                    f"({baseline.get('mean_ms', 0):.1f}ms → {fault.get('mean_ms', 0):.1f}ms)"
                )

            steps.append(CausalStep(
                step_number=step_num,
                observation=f"Dependency degradation: {dep_latency_info or 'Performance degraded'}",
                cause=f"Fault in upstream dependency ({', '.join(dependencies[:2])})",
                consequence=f"{node_id} experiences slower response from dependencies",
                metrics={'latency_analysis': latency_analysis} if latency_analysis else {}
            ))
            step_num += 1

        # Step 2: Connection pool saturation (if applicable)
        if mechanism in ['connection_pool_saturation'] and saturation_report:
            peak_util = saturation_report.get('peak_utilization', {}).get('connection_pool', 0)
            pool_capacity = None
            if config and 'connection_pool' in config.get('configuration', {}):
                pool_capacity = config['configuration']['connection_pool'].get('capacity')

            observation = f"Connection pool saturation: {peak_util:.0f}% utilization"
            if pool_capacity:
                observation += f" ({int(peak_util * pool_capacity / 100)}/{pool_capacity} connections)"

            steps.append(CausalStep(
                step_number=step_num,
                observation=observation,
                cause="Requests holding connections longer due to slow dependencies",
                consequence="New requests must queue, adding latency proportional to queue depth",
                metrics={'peak_utilization': peak_util, 'capacity': pool_capacity}
            ))
            step_num += 1

        # Step 3: Retry amplification (if timeouts likely)
        if config and 'retry_policy' in config.get('configuration', {}):
            retry_config = config['configuration']['retry_policy']
            max_attempts = retry_config.get('max_attempts', 3)

            # Check if there were likely timeouts
            has_timeout_indicators = False
            if saturation_report and saturation_report.get('sustained_saturation'):
                has_timeout_indicators = True
            if latency_analysis and latency_analysis.get('degradation_factor', 1.0) >= 3.0:
                has_timeout_indicators = True

            if has_timeout_indicators:
                steps.append(CausalStep(
                    step_number=step_num,
                    observation=f"Retry storms: {max_attempts} attempts per failed request",
                    cause="Timeouts trigger automatic retry policy with exponential backoff",
                    consequence=f"Load amplification: ~{max_attempts}x more requests to dependencies",
                    metrics={'retry_config': retry_config}
                ))
                step_num += 1

        # Step 4: Throughput collapse / circuit breaker
        metrics = node_report.get('ranked_metrics', [])
        request_metric = None
        for metric in metrics:
            if 'request' in metric.get('metric_name', '').lower():
                request_metric = metric
                break

        if request_metric:
            mean_change = request_metric.get('mean_change_pct', 0)
            baseline_mean = request_metric.get('baseline_mean', 0)
            fault_mean = request_metric.get('fault_mean', 0)

            if mean_change < -50:  # Significant drop
                mechanism_name = "Circuit breaker activation" if mean_change < -70 else "Backpressure"

                steps.append(CausalStep(
                    step_number=step_num,
                    observation=f"Request rate dropped {abs(mean_change):.0f}% ({baseline_mean:.1f} → {fault_mean:.1f} req/s)",
                    cause=mechanism_name + ": Upstream services detect failures/timeouts",
                    consequence="Reduced load on this component, but degraded service for users",
                    metrics={'mean_change_pct': mean_change, 'baseline_mean': baseline_mean, 'fault_mean': fault_mean}
                ))
                step_num += 1

        return steps

    def explain_why_impacted(
        self,
        node_id: str,
        distance: int,
        dependencies: List[str],
        mechanism: str
    ) -> str:
        """
        Generate explanation of why this node was impacted.

        Args:
            node_id: Node identifier
            distance: Distance from root cause
            dependencies: Direct dependencies
            mechanism: Propagation mechanism

        Returns:
            Explanation string
        """
        if distance == 0:
            return f"{node_id} is the root cause of the fault"

        if distance == 1 and dependencies:
            return (
                f"Direct dependency on faulty component ({', '.join(dependencies[:2])}). "
                f"Impact propagated via {self.MECHANISMS.get(mechanism, mechanism)}"
            )

        dep_str = f" via {', '.join(dependencies[:2])}" if dependencies else ""
        return (
            f"Indirect impact at distance {distance} from root cause{dep_str}. "
            f"Propagation mechanism: {self.MECHANISMS.get(mechanism, mechanism)}"
        )

    def analyze_node(
        self,
        node_id: str,
        node_report: Dict,
        latency_analyses: Dict[str, Dict],
        saturation_reports: Dict[str, Dict],
        configs: Dict[str, Dict]
    ) -> CausalAnalysis:
        """
        Perform complete causal analysis for a node.

        Args:
            node_id: Node to analyze
            node_report: Impact report from propagation analyzer
            latency_analyses: All latency analyses
            saturation_reports: All saturation reports
            configs: All configuration contexts

        Returns:
            CausalAnalysis
        """
        node_type = node_report.get('node_type', 'Unknown')
        distance = node_report.get('distance_from_root', 0)

        # Get data for this node
        latency_analysis = latency_analyses.get(node_id)
        saturation_report = saturation_reports.get(node_id)
        config = configs.get(node_id)

        # Find direct dependencies
        dependencies = []
        if self.graph.has_node(node_id):
            dependencies = [n for n in self.graph.successors(node_id) if n != node_id]

        # Identify mechanism
        mechanism = self.identify_mechanism(
            node_id, node_report, latency_analysis, saturation_report, config
        )

        # Build causal chain
        causal_chain = self.build_causal_chain(
            node_id, node_type, mechanism, node_report,
            latency_analysis, saturation_report, config, dependencies
        )

        # Explain why impacted
        why_impacted = self.explain_why_impacted(node_id, distance, dependencies, mechanism)

        # Identify configuration factors
        config_factors = []
        if config and 'configuration' in config:
            cfg = config['configuration']
            if 'connection_pool' in cfg:
                capacity = cfg['connection_pool'].get('capacity', 0)
                config_factors.append(f"Connection pool capacity: {capacity}")
            if 'retry_policy' in cfg:
                attempts = cfg['retry_policy'].get('max_attempts', 0)
                config_factors.append(f"Retry policy: {attempts} attempts max")
            if 'timeouts' in cfg:
                db_timeout = cfg['timeouts'].get('database_call_ms', 0)
                if db_timeout:
                    config_factors.append(f"Database timeout: {db_timeout}ms")

        # Generate summary
        summary = f"{node_id} impacted via {self.MECHANISMS.get(mechanism, mechanism)}. "
        summary += f"{len(causal_chain)} causal steps identified."

        return CausalAnalysis(
            node_id=node_id,
            node_type=node_type,
            distance_from_root=distance,
            primary_mechanism=mechanism,
            why_impacted=why_impacted,
            causal_chain=causal_chain,
            configuration_factors=config_factors,
            summary=summary
        )

    def analyze_all(
        self,
        node_reports: List[Dict],
        latency_analyses: Dict[str, Dict],
        saturation_reports: Dict[str, Dict],
        configs: Dict[str, Dict]
    ) -> Dict[str, CausalAnalysis]:
        """
        Analyze causal chains for all impacted nodes.

        Args:
            node_reports: List of node impact reports
            latency_analyses: Latency analyses by component
            saturation_reports: Saturation reports by component
            configs: Configuration contexts by component

        Returns:
            Dictionary mapping node_id -> CausalAnalysis
        """
        results = {}

        for report in node_reports:
            node_id = report.get('node_id')
            if not node_id:
                continue

            analysis = self.analyze_node(
                node_id, report, latency_analyses, saturation_reports, configs
            )
            results[node_id] = analysis

        return results

    def generate_report(self, analyses: Dict[str, CausalAnalysis]) -> str:
        """Generate human-readable causal analysis report."""
        if not analyses:
            return "No causal analysis available.\n"

        lines = ["=" * 80, "CAUSAL CHAIN ANALYSIS", "=" * 80, ""]

        # Sort by distance from root
        sorted_analyses = sorted(
            analyses.items(),
            key=lambda x: (x[1].distance_from_root, x[0])
        )

        for node_id, analysis in sorted_analyses:
            lines.append(f"\n{node_id} ({analysis.node_type}) - Distance {analysis.distance_from_root}")
            lines.append("-" * 60)
            lines.append(f"  Mechanism: {self.MECHANISMS.get(analysis.primary_mechanism, analysis.primary_mechanism)}")
            lines.append(f"  Why: {analysis.why_impacted}")

            if analysis.causal_chain:
                lines.append(f"\n  Causal Chain:")
                for step in analysis.causal_chain:
                    lines.append(f"    {step.step_number}. {step.observation}")
                    lines.append(f"       → Cause: {step.cause}")
                    lines.append(f"       → Consequence: {step.consequence}")

            if analysis.configuration_factors:
                lines.append(f"\n  Configuration Factors:")
                for factor in analysis.configuration_factors:
                    lines.append(f"    - {factor}")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)
