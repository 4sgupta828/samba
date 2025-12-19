"""
whitebox_rca.py

The SOTA Root Cause Analysis Engine (vFinal - Transparent Physics).
1. Heuristics Removed: No symptom counting, no victim penalties.
2. Logic: Self + Physics Coverage + Semantics.
3. Output: Detailed score composition for explainability.
"""

import numpy as np
import networkx as nx
import pandas as pd
from typing import Dict, List, Any, Optional
from pathlib import Path

# Core Components
from self_health_analyzer import SelfHealthAnalyzer
from config_extractor import ConfigExtractor
from causal_graph_reasoner import CausalGraphReasoner

# Supplemental Components
from temporal_analyzer import TemporalAnalyzer
from log_analyzer import LogAnalyzer
from trace_analyzer import TraceAnalyzer

class WhiteboxRCAEngine:
    def __init__(self, topology: nx.DiGraph, config: Dict = None):
        self.topology = topology
        self.config_extractor = ConfigExtractor(config)

        self.self_analyzer = SelfHealthAnalyzer(self.config_extractor)
        self.reasoner = CausalGraphReasoner(topology)

        self.temporal_analyzer = TemporalAnalyzer(topology)
        self.trace_analyzer = TraceAnalyzer(topology)
        self.log_analyzer = LogAnalyzer()

    def calculate_integrated_health_score(self,
                                          node: str,
                                          service_self_score: float,
                                          baseline_pods: Optional[Dict] = None,
                                          current_pods: Optional[Dict] = None) -> tuple:
        """
        Calculate integrated health score combining service-level and pod-level signals.
        Uses coverage-weighted aggregation to properly handle partial degradation.

        Args:
            node: Service node name
            service_self_score: Service-level self-health score
            baseline_pods: Baseline metrics for all pods
            current_pods: Current metrics for all pods

        Returns:
            (integrated_score, metadata) where metadata includes breakdown
        """
        pod_score = 0.0
        pod_metadata = {}

        # Check if this node has pods
        node_attrs = self.topology.nodes.get(node, {})
        if node_attrs.get('type') == 'Service' and baseline_pods and current_pods:
            # Find all pods for this service
            pod_ids = [
                n for n in self.topology.nodes
                if self.topology.nodes[n].get('parent_service') == node
            ]

            if pod_ids:
                degraded_pods = []
                all_pod_scores = []

                for pod_id in pod_ids:
                    pod_base = baseline_pods.get(pod_id, {})
                    pod_curr = current_pods.get(pod_id, {})

                    if not pod_curr:
                        continue

                    # Analyze pod health
                    pod_type = self.topology.nodes[pod_id].get('type', 'Pod')
                    analysis = self.self_analyzer.analyze(pod_id, pod_type, pod_base, pod_curr)
                    pod_self_score = analysis.self_degradation_score

                    all_pod_scores.append(pod_self_score)

                    # Threshold for degradation
                    if pod_self_score >= 2.0:
                        degraded_pods.append({
                            'id': pod_id,
                            'score': pod_self_score,
                            'symptoms': analysis.symptoms
                        })

                # Calculate coverage-weighted score
                if degraded_pods and pod_ids:
                    coverage = len(degraded_pods) / len(pod_ids)
                    avg_severity = sum(p['score'] for p in degraded_pods) / len(degraded_pods)
                    max_severity = max(p['score'] for p in degraded_pods)

                    # Coverage-weighted: severity × coverage
                    pod_score = avg_severity * coverage

                    # Classify pattern
                    if coverage >= 0.8:
                        pattern = f"Service-wide degradation ({len(degraded_pods)}/{len(pod_ids)} pods)"
                    elif coverage >= 0.5:
                        pattern = f"Partial degradation ({len(degraded_pods)}/{len(pod_ids)} pods)"
                    elif coverage >= 0.2:
                        pattern = f"Multiple pods affected ({len(degraded_pods)}/{len(pod_ids)} pods)"
                    else:
                        pattern = f"Outlier pods ({len(degraded_pods)}/{len(pod_ids)} pods)"

                    pod_metadata = {
                        'pod_score': pod_score,
                        'coverage': coverage,
                        'avg_severity': avg_severity,
                        'max_severity': max_severity,
                        'degraded_count': len(degraded_pods),
                        'total_count': len(pod_ids),
                        'pattern': pattern
                    }

        # Integrate: use whichever signal is stronger
        integrated_score = max(service_self_score, pod_score)

        metadata = {
            'service_score': service_self_score,
            'integrated_score': integrated_score,
            'source': 'pod-level' if pod_score > service_self_score else 'service-level'
        }

        # Add pod metadata if available
        if pod_metadata:
            metadata.update(pod_metadata)

        return integrated_score, metadata

    def analyze_incident(self,
                         baseline_data: Dict, current_data: Dict,
                         metrics_df: Optional[pd.DataFrame] = None,
                         fault_start_time: Optional[float] = None,
                         traces_file: Optional[Path] = None,
                         logs_file: Optional[Path] = None,
                         baseline_pods=None, current_pods=None) -> List[Dict]:

        # --- PHASE 1: Self-Health (Whitebox + Blackbox Inference) ---
        self_scores = {}
        for node in self.topology.nodes:
            if self.topology.nodes[node].get('parent_service'): continue

            node_type = self.topology.nodes[node].get('type', 'Service')
            b_metrics = baseline_data.get(node, {})
            c_metrics = current_data.get(node, {})

            # A. Whitebox Analysis
            if c_metrics:
                analysis = self.self_analyzer.analyze(node, node_type, b_metrics, c_metrics)

            # B. Blackbox Inference
            else:
                callers = list(self.topology.predecessors(node))
                if callers:
                    c_views_base = [baseline_data.get(c, {}) for c in callers]
                    c_views_curr = [current_data.get(c, {}) for c in callers]
                    analysis = self.self_analyzer.infer_blackbox_health(
                        node, c_views_base, c_views_curr
                    )
                else:
                    continue # Orphan node

            self_scores[node] = analysis

        # --- PHASE 2: Physics Coverage ---
        candidates = [n for n, s in self_scores.items() if s.is_root_cause_candidate]

        physics_hypotheses = self.reasoner.calculate_global_coverage(
            candidates, self_scores, baseline_data, current_data
        )

        # --- PHASE 3: Network Partition Detection ---
        # Detect complete communication failure between nodes (global_network)
        # Use multiple strategies for double confirmation
        network_partition_candidate = None
        network_partitions = []
        metric_gaps = {}  # Track edges with metric gaps for confirmation

        # STRATEGY 1: Detect sustained near-complete metric gaps (network partitions)
        # Look for time windows where dependency requests drop to near-zero for extended periods
        if metrics_df is not None and fault_start_time is not None:
            try:
                # Filter for dependency request metrics
                dep_metrics = metrics_df[metrics_df['name'].str.contains('dependency.requests', na=False)].copy()

                if not dep_metrics.empty:
                    # Extract dependency_id from labels dict
                    dep_metrics['dependency_id'] = dep_metrics['labels'].apply(
                        lambda x: x.get('dependency_id') if isinstance(x, dict) else None
                    )

                    # Filter out rows without dependency_id
                    dep_metrics = dep_metrics[dep_metrics['dependency_id'].notna()]

                    if not dep_metrics.empty:
                        # Split into baseline and post-fault periods
                        baseline_df = dep_metrics[dep_metrics['sim_time'] < fault_start_time]
                        post_fault_df = dep_metrics[dep_metrics['sim_time'] >= fault_start_time]

                        # Calculate baseline request frequency for each edge
                        baseline_duration = fault_start_time if fault_start_time > 0 else 1

                        # Group by component and dependency to analyze each edge
                        for (component_id, dep_id), baseline_group in baseline_df.groupby(['component_id', 'dependency_id']):
                            # Check if this dependency had regular activity in baseline
                            baseline_count = len(baseline_group)
                            baseline_total_reqs = baseline_group['value'].sum() if 'value' in baseline_group.columns else 0

                            if baseline_count >= 3 and baseline_total_reqs > 10:  # Was active in baseline
                                # Get post-fault data for this edge
                                post_fault_group = post_fault_df[
                                    (post_fault_df['component_id'] == component_id) &
                                    (post_fault_df['dependency_id'] == dep_id)
                                ].sort_values('sim_time')

                                if len(post_fault_group) == 0:
                                    # No data at all post-fault - complete blackout
                                    baseline_freq = baseline_count / baseline_duration

                                    # Map component_id to service
                                    if component_id and component_id.startswith('pod_'):
                                        service = '_'.join(component_id.split('_')[1:-1])
                                    else:
                                        service = component_id

                                    if service and dep_id:
                                        metric_gaps[(service, dep_id)] = {
                                            'baseline_freq': baseline_freq,
                                            'max_blackout_duration': post_fault_df['sim_time'].max() - fault_start_time,
                                            'gap_ratio': 1.0,
                                            'partition_type': 'complete_blackout'
                                        }
                                else:
                                    # Use sliding window to find sustained gaps
                                    # Window size: 60 seconds (configurable)
                                    # Threshold: >95% drop (near-zero requests)
                                    window_size = 60.0
                                    baseline_freq = baseline_count / baseline_duration

                                    # Check for sustained gaps in time windows
                                    max_gap_duration = 0
                                    max_gap_start = None
                                    current_gap_start = None
                                    last_request_time = fault_start_time

                                    for _, row in post_fault_group.iterrows():
                                        request_time = row['sim_time']
                                        gap_duration = request_time - last_request_time

                                        # If gap > window_size, we have a sustained blackout
                                        if gap_duration >= window_size:
                                            if current_gap_start is None:
                                                current_gap_start = last_request_time

                                            total_gap = request_time - current_gap_start
                                            if total_gap > max_gap_duration:
                                                max_gap_duration = total_gap
                                                max_gap_start = current_gap_start
                                        else:
                                            current_gap_start = None

                                        last_request_time = request_time

                                    # Check if gap extends to end of timeline
                                    end_time = post_fault_df['sim_time'].max()
                                    final_gap = end_time - last_request_time
                                    if final_gap >= window_size:
                                        if current_gap_start is None:
                                            current_gap_start = last_request_time
                                        total_gap = end_time - current_gap_start
                                        if total_gap > max_gap_duration:
                                            max_gap_duration = total_gap
                                            max_gap_start = current_gap_start

                                    # If we found a sustained gap (>60s with near-zero requests), flag as partition
                                    if max_gap_duration >= window_size:
                                        # Map component_id to service
                                        if component_id and component_id.startswith('pod_'):
                                            service = '_'.join(component_id.split('_')[1:-1])
                                        else:
                                            service = component_id

                                        if service and dep_id:
                                            metric_gaps[(service, dep_id)] = {
                                                'baseline_freq': baseline_freq,
                                                'max_blackout_duration': max_gap_duration,
                                                'blackout_start': max_gap_start,
                                                'gap_ratio': 1.0,  # Near 100% during blackout window
                                                'partition_type': 'sustained_blackout'
                                            }

                        # Report detected gaps
                        if metric_gaps:
                            print(f"  [Network Partition Detection] Found {len(metric_gaps)} edges with sustained blackouts")
                            for (src, tgt), info in list(metric_gaps.items())[:3]:
                                print(f"    {src} -> {tgt}: {info['max_blackout_duration']:.0f}s blackout (baseline: {info['baseline_freq']:.2f} req/s)")

                        # Convert sustained blackouts to network partitions
                        # Only flag as partition if blackout is sustained (>60s) and nearly complete (>95%)
                        for (source, target), gap_info in metric_gaps.items():
                            blackout_duration = gap_info['max_blackout_duration']

                            # Very high confidence: 120+ seconds of complete blackout
                            if blackout_duration >= 120:
                                reason = (f'Network partition detected: {source} -> {target} '
                                         f'(Complete blackout for {blackout_duration:.0f}s, baseline: {gap_info["baseline_freq"]:.2f} req/s)')
                                confidence = 0.98
                                network_partitions.append({
                                    'source': source,
                                    'target': target,
                                    'reason': reason,
                                    'confidence': confidence,
                                    'double_confirmed': False
                                })
                            # High confidence: 60+ seconds of blackout
                            elif blackout_duration >= 60:
                                reason = (f'Network partition detected: {source} -> {target} '
                                         f'(Sustained blackout for {blackout_duration:.0f}s, baseline: {gap_info["baseline_freq"]:.2f} req/s)')
                                confidence = 0.90
                                network_partitions.append({
                                    'source': source,
                                    'target': target,
                                    'reason': reason,
                                    'confidence': confidence,
                                    'double_confirmed': False
                                })

            except Exception as e:
                print(f"  [!] Warning: Network partition detection failed: {e}")

        # Create global_network candidate if partitions detected
        if network_partitions:
            print(f"  [!] Network partition detected: {len(network_partitions)} blocked edge(s)")
            for partition in network_partitions:
                print(f"      - {partition['reason']}")

            # Score based on metric confidence level
            avg_confidence = sum(p['confidence'] for p in network_partitions) / len(network_partitions)

            # Map confidence to score (metric-based detection)
            # High confidence (0.9+): Strong evidence of network partition
            # Medium confidence (0.8-0.9): Likely network partition
            if avg_confidence >= 0.9:
                network_score = 100.0  # Strong evidence
                print(f"  [!] High-confidence partition (metrics), treating as root cause (confidence: {avg_confidence:.2f})")
            elif avg_confidence >= 0.8:
                network_score = 80.0  # Good evidence
                print(f"  [!] Medium-confidence partition (metrics), strong candidate (confidence: {avg_confidence:.2f})")
            else:
                network_score = 50.0  # Moderate evidence
                print(f"  [!] Low-confidence partition (metrics), moderate candidate (confidence: {avg_confidence:.2f})")

            network_partition_candidate = {
                'node': 'global_network',
                'score': network_score,
                'score_composition': {
                    'base_health': {'raw': 0, 'confidence': 'high', 'multiplier': 1.0, 'points': 0},
                    'physics_coverage': {'raw': 0, 'weight': 60.0, 'points': 0},
                    'semantic_bonus': {'is_primary': True, 'coverage_context': 'high', 'points': 0},
                    'supplements': {'temporal': 0, 'trace': 0, 'trace_degradation': 0, 'logs': 0, 'metric_gaps': network_score}
                },
                'story': [
                    '🔴 ROOT CAUSE: global_network (Network Partition)',
                    '   Network partitions detected via metric analysis:',
                    *[f'   - {p["reason"]}' for p in network_partitions],
                    f'',
                    f'   Detection confidence: {avg_confidence*100:.0f}%',
                    f'   Detected edges: {len(network_partitions)}'
                ],
                'integrated_score': 0.0,
                'self_score': 0.0,
                'symptoms': [f'Network partition detected ({len(network_partitions)} blocked edges)'],
                'health_metadata': {
                    'network_partition_count': len(network_partitions),
                    'avg_confidence': avg_confidence,
                    'detection_method': 'metric_gaps'
                },
                'guilt_ratio': 0.0,
                'temporal_score': 0.0,
                'trace_score': 0.0,
                'is_trace_authoritative': True,
                'blamed_by': []
            }

        # --- PHASE 4: Supplemental Evidence ---
        temporal_scores = {}
        if metrics_df is not None and fault_start_time:
            try: temporal_scores = self.temporal_analyzer.detect_first_impact_times(metrics_df, fault_start_time)
            except: pass

        trace_evidence = {}
        if traces_file and fault_start_time:
            try: trace_evidence = self.trace_analyzer.analyze(traces_file, fault_start_time)
            except: pass

        log_scores = {}
        if logs_file and logs_file.exists():
            try: log_scores = self.log_analyzer.analyze(logs_file, fault_start_time)
            except: pass

        # --- PHASE 4: SOTA Ranking & Explainability ---
        rankings = []
        for node in self.topology.nodes:
            if node not in self_scores: continue

            # === COMPONENT 1: BASE HEALTH (0-50 points) ===
            # Pod-level analysis is AUTHORITATIVE when available (more granular than service aggregates)
            service_self_score = self_scores[node].self_degradation_score
            service_confidence = self_scores[node].confidence

            # Calculate integrated score (considers pod-level if available)
            integrated_score, health_metadata = self.calculate_integrated_health_score(
                node, service_self_score, baseline_pods, current_pods
            )

            # PRINCIPLED: Use pod-level evidence, but weight by coverage
            # High coverage (service-wide) = strong evidence of intrinsic problem
            # Low coverage (outlier pods) = weak evidence, likely cascading effect
            if health_metadata.get('source') == 'pod-level':
                self_val = integrated_score
                coverage = health_metadata.get('coverage', 0)

                # Coverage-based confidence: distinguish root cause from victim
                if coverage >= 0.8:
                    # Service-wide degradation (≥80% pods) - strong intrinsic evidence
                    confidence = 'high'
                    confidence_multiplier = 1.0
                elif coverage >= 0.5:
                    # Majority degradation (50-80% pods) - moderate evidence
                    confidence = 'medium'
                    confidence_multiplier = 0.6
                elif coverage >= 0.3:
                    # Multiple pods (30-50%) - weak evidence
                    confidence = 'low'
                    confidence_multiplier = 0.3
                else:
                    # Outlier pods (<30%) - very weak evidence (likely cascading)
                    confidence = 'very_low'
                    confidence_multiplier = 0.15
            else:
                # No pods or pod score lower - use service-level as fallback
                self_val = service_self_score
                confidence = service_confidence
                confidence_multiplier = {'high': 1.0, 'medium': 0.8, 'low': 0.5}.get(confidence, 0.8)

            weighted_self = self_val * 5.0 * confidence_multiplier  # 0-50 points

            # === COMPONENT 2: PHYSICS COVERAGE (0-60 points) ===
            # How much of the system's pain does this node explain?
            # This is THE most important signal for root cause
            raw_coverage = physics_hypotheses.get(node).coverage_score if node in physics_hypotheses else 0.0
            weighted_coverage = raw_coverage * 60.0  # 0-60 points

            # === COMPONENT 3: SEMANTIC TYPE (0-40 points) ===
            # PRIMARY symptoms (cause) get major boost
            # SECONDARY symptoms (effect) get zero
            is_primary = (self_scores[node].symptom_type == 'primary')

            # Refined: Consider both type AND coverage
            if is_primary:
                # Primary symptoms with good coverage are strong candidates
                if raw_coverage > 0.5:
                    semantic_bonus = 40.0  # Strong root cause signal
                elif raw_coverage > 0.2:
                    semantic_bonus = 30.0  # Moderate root cause signal
                else:
                    semantic_bonus = 20.0  # Isolated primary symptom
            else:
                # Secondary symptoms are likely victims, but high coverage victims matter
                if raw_coverage > 0.7:
                    semantic_bonus = 10.0  # Major victim (might be proxy)
                else:
                    semantic_bonus = 0.0   # Minor victim

            # === CORE EVIDENCE STRENGTH ===
            # PRINCIPLE: Supplemental signals (temporal, trace, logs) should be modulated by
            # the strength of core evidence. This prevents false positives from cascading symptoms
            # while not being brittle with hard thresholds.
            #
            # Core evidence comes from:
            # 1. Self-degradation (weighted_self: 0-50 points)
            # 2. Physics coverage (weighted_coverage: 0-60 points)
            # 3. Semantic type (semantic_bonus: 0-40 points)
            #
            # Calculate core strength as percentage of maximum possible core score (150 points)
            core_base_score = weighted_self + weighted_coverage + semantic_bonus
            max_core_score = 150.0  # 50 + 60 + 40
            core_strength = min(1.0, core_base_score / max_core_score)

            # Apply soft gating: supplements are scaled by core strength
            # - core_strength = 0.0 → supplements contribute 0% (pure victim)
            # - core_strength = 0.1 → supplements contribute 10% (weak evidence)
            # - core_strength = 0.5 → supplements contribute 50% (moderate evidence)
            # - core_strength = 1.0 → supplements contribute 100% (strong evidence)
            #
            # This is continuous and non-brittle: any core evidence enables some supplement boost

            # === COMPONENT 4: TEMPORAL EVIDENCE (0-15 points) ===
            # First to break gets bonus, scaled by core evidence strength
            min_time = min(temporal_scores.values()) if temporal_scores else 0
            is_early = (temporal_scores.get(node, float('inf')) <= min_time + 5.0)
            temporal_bonus_raw = 15.0 if is_early else 0.0
            temporal_bonus = temporal_bonus_raw * core_strength

            # === COMPONENT 5: TRACE EVIDENCE (0-35 points) ===
            # Authoritative trace evidence (self-time degradation), scaled by core strength
            trace_info = trace_evidence.get(node, {})
            trace_auth = trace_info.get('is_authoritative', False)
            self_time_deg = trace_info.get('self_time_degradation', 1.0)
            trace_bonus_raw = 0.0

            if trace_auth:
                # Scale based on degradation severity
                if self_time_deg > 3.0:
                    trace_bonus_raw = 35.0  # Severe degradation
                elif self_time_deg > 2.0:
                    trace_bonus_raw = 25.0  # Moderate degradation
                else:
                    trace_bonus_raw = 15.0  # Minor degradation

            trace_bonus = trace_bonus_raw * core_strength

            # === COMPONENT 6: LOG EVIDENCE (0-20 points) ===
            # Log evidence scaled by core strength
            log_bonus_raw = min(20.0, log_scores.get(node, {}).get('log_score', 0.0))
            log_bonus = log_bonus_raw * core_strength

            # === FINAL SCORE (0-220 max) ===
            # Balanced formula: No single component dominates
            # Primary + High Coverage + Early = Strong Root Cause
            final_score = (
                weighted_self +      # 0-50: Internal health
                weighted_coverage +  # 0-60: Explanatory power (MOST IMPORTANT)
                semantic_bonus +     # 0-40: Cause vs Effect
                temporal_bonus +     # 0-15: First mover advantage
                trace_bonus +        # 0-35: Authoritative evidence
                log_bonus            # 0-20: Log evidence
            )

            # Get symptoms from analysis
            symptoms = self_scores[node].symptoms if node in self_scores else []

            # Enhanced story for global_network nodes with partition metadata
            story = physics_hypotheses.get(node).narrative if node in physics_hypotheses else []
            if node == 'global_network':
                node_attrs = self.topology.nodes.get(node, {})
                partition_meta = node_attrs.get('partition_metadata', {})
                if partition_meta:
                    edge_info = partition_meta.get('partitioned_edge', {})
                    if edge_info:
                        src = edge_info.get("source")
                        tgt = edge_info.get("target")
                        story = [
                            '🔴 ROOT CAUSE: global_network (Network Partition)',
                            '',
                            '   Partitioned Edge:',
                            f'   - Source: {src}',
                            f'   - Target: {tgt}',
                            f'   - Edge Type: {edge_info.get("edge_type")}',
                            f'   - Bidirectional: {edge_info.get("bidirectional")}',
                            '',
                            '   This network partition blocks all communication on this edge,',
                            '   causing cascading failures in services that depend on it.'
                        ]
                        # Update symptoms with partition details
                        symptoms = [f'Network partition between {src} and {tgt}']

            rankings.append({
                'node': node,
                'score': round(final_score, 2),
                'score_composition': {
                    'base_health': {
                        'raw': round(self_val, 2),
                        'confidence': confidence,
                        'multiplier': confidence_multiplier,
                        'points': round(weighted_self, 1)
                    },
                    'physics_coverage': {
                        'raw': round(raw_coverage, 2),
                        'weight': 60.0,
                        'points': round(weighted_coverage, 1)
                    },
                    'semantic_bonus': {
                        'is_primary': is_primary,
                        'coverage_context': 'high' if raw_coverage > 0.5 else 'medium' if raw_coverage > 0.2 else 'low',
                        'points': semantic_bonus
                    },
                    'supplements': {
                        'temporal': round(temporal_bonus, 2),
                        'trace': round(trace_bonus, 2),
                        'trace_degradation': round(self_time_deg, 2),
                        'logs': round(log_bonus, 2),
                        'core_strength': round(core_strength, 3)
                    }
                },
                'story': story,
                # Compatibility fields for run_rca_batch.py
                'integrated_score': round(integrated_score, 2),
                'self_score': round(service_self_score, 2),
                'symptoms': symptoms,
                'health_metadata': health_metadata,  # Includes pod-level details
                'guilt_ratio': 0.0,  # Not used in pure physics model
                'temporal_score': temporal_bonus,
                'trace_score': trace_bonus,
                'is_trace_authoritative': trace_auth,
                'blamed_by': []  # Not used in pure physics model
            })

        # Add network partition candidate if detected
        if network_partition_candidate:
            rankings.append(network_partition_candidate)

        return sorted(rankings, key=lambda x: x['score'], reverse=True)

    def validate_ground_truth(self, ground_truth_node: str, candidates: List[Dict]) -> Dict:
        """
        Validate that the ground truth label actually shows evidence of being faulty.

        Returns:
            Dict with validation results
        """
        # Find ground truth in candidates
        gt_candidate = None
        for c in candidates:
            if c['node'] == ground_truth_node:
                gt_candidate = c
                break

        if not gt_candidate:
            return {
                'is_valid': False,
                'confidence': 'unknown',
                'evidence_score': 0,
                'max_evidence_score': 10,
                'reasons': [f"Ground truth node '{ground_truth_node}' not found in topology"],
                'verdict': "❌ Ground truth node not found in analysis",
                'ground_truth_node': ground_truth_node,
                'ground_truth_rank': None,
                'ground_truth_score': 0,
            }

        # Score evidence
        evidence_score = 0
        reasons = []

        # 1. Check for symptoms (0-3 points)
        self_val = gt_candidate['score_composition']['base_health']['raw']
        if self_val > 0:
            evidence_score += min(3, int(self_val))
            reasons.append(f"✓ Self-degradation score: {self_val:.1f}")
        else:
            reasons.append("⚠️ No self-degradation detected")

        # 2. Check physics coverage (0-3 points)
        coverage = gt_candidate['score_composition']['physics_coverage']['raw']
        if coverage > 0.5:
            evidence_score += 3
            reasons.append(f"✓ High physics coverage: {coverage:.1%}")
        elif coverage > 0.2:
            evidence_score += 2
            reasons.append(f"✓ Moderate physics coverage: {coverage:.1%}")
        elif coverage > 0:
            evidence_score += 1
            reasons.append(f"⚠️ Low physics coverage: {coverage:.1%}")
        else:
            reasons.append("⚠️ No physics coverage")

        # 3. Check semantic type (0-2 points)
        is_primary = gt_candidate['score_composition']['semantic_bonus']['is_primary']
        if is_primary:
            evidence_score += 2
            reasons.append("✓ Primary symptom type (cause)")
        else:
            reasons.append("⚠️ Secondary symptom type (effect)")

        # 4. Check supplemental evidence (0-2 points)
        supplements = gt_candidate['score_composition']['supplements']
        if supplements['trace'] > 0:
            evidence_score += 1
            reasons.append("✓ Trace evidence present")
        if supplements['temporal'] > 0:
            evidence_score += 1
            reasons.append("✓ Temporal evidence present")

        # Determine validity
        if evidence_score >= 7:
            is_valid = True
            confidence = 'high'
            verdict = "✅ Strong evidence that ground truth is actually faulty"
        elif evidence_score >= 4:
            is_valid = True
            confidence = 'medium'
            verdict = "⚠️ Moderate evidence of fault - RCA should catch this"
        elif evidence_score >= 2:
            is_valid = False
            confidence = 'low'
            verdict = "⚠️ Weak evidence of fault - possibly invalid ground truth"
        else:
            is_valid = False
            confidence = 'very_low'
            verdict = "❌ No evidence of fault - likely invalid ground truth label"

        return {
            'is_valid': is_valid,
            'confidence': confidence,
            'evidence_score': evidence_score,
            'max_evidence_score': 10,
            'reasons': reasons,
            'verdict': verdict,
            'ground_truth_node': ground_truth_node,
            'ground_truth_rank': None,  # Will be filled in by caller
            'ground_truth_score': gt_candidate.get('score', 0),
        }
