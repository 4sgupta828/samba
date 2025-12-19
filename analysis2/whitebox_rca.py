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

        # STRATEGY 1: Detect metric gaps (secondary confirmation)
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
                        # Split into baseline and current periods
                        baseline_df = dep_metrics[dep_metrics['sim_time'] < fault_start_time]
                        current_df = dep_metrics[dep_metrics['sim_time'] >= fault_start_time]

                        # Calculate duration of each period
                        baseline_duration = fault_start_time if fault_start_time > 0 else 1
                        current_duration = current_df['sim_time'].max() - fault_start_time if len(current_df) > 0 else 1

                        # Group by component and dependency to find gaps
                        for (component_id, dep_id), baseline_group in baseline_df.groupby(['component_id', 'dependency_id']):
                            # Check if this dependency had regular activity in baseline
                            baseline_count = len(baseline_group)
                            baseline_total_reqs = baseline_group['value'].sum() if 'value' in baseline_group.columns else 0

                            if baseline_count >= 3 and baseline_total_reqs > 10:  # Was active in baseline
                                # Check if we have data in current period
                                current_group = current_df[
                                    (current_df['component_id'] == component_id) &
                                    (current_df['dependency_id'] == dep_id)
                                ]
                                current_count = len(current_group)

                                # Calculate FREQUENCY (samples per second) instead of absolute count
                                baseline_freq = baseline_count / baseline_duration
                                current_freq = current_count / current_duration if current_duration > 0 else 0

                                # Detect gap: frequency dropped by >50%
                                if current_freq < baseline_freq * 0.5:
                                    # Map component_id to service
                                    if component_id and component_id.startswith('pod_'):
                                        service = '_'.join(component_id.split('_')[1:-1])
                                    else:
                                        service = component_id

                                    if service and dep_id:
                                        metric_gaps[(service, dep_id)] = {
                                            'baseline_samples': baseline_count,
                                            'current_samples': current_count,
                                            'gap_ratio': 1.0 - (current_freq / baseline_freq) if baseline_freq > 0 else 1.0,
                                            'baseline_freq': baseline_freq,
                                            'current_freq': current_freq
                                        }

                        # Report detected gaps
                        if metric_gaps:
                            print(f"  [Metric Gaps] Detected {len(metric_gaps)} edges with metric frequency drops")
                            for (src, tgt), info in list(metric_gaps.items())[:3]:
                                print(f"    {src} -> {tgt}: {info['baseline_freq']:.3f} → {info['current_freq']:.3f}/s ({info['gap_ratio']*100:.0f}% drop)")

            except Exception as e:
                print(f"  [!] Warning: Metric gap detection failed: {e}")

        # STRATEGY 2: Scan logs for connection timeout patterns
        # DISABLED: Log-based detection causes false positives (timeouts are often symptoms, not cause)
        # Only use metric-based detection for now
        if False and logs_file and logs_file.exists() and fault_start_time:
            import json
            connection_errors = {}  # {(source, target): count}

            try:
                with open(logs_file, 'r') as f:
                    for line in f:
                        try:
                            log_entry = json.loads(line)

                            # Only count errors during fault period
                            log_timestamp_ns = log_entry.get('timestamp', 0)
                            log_timestamp_s = log_timestamp_ns / 1e9 if log_timestamp_ns > 1e12 else log_timestamp_ns

                            if log_timestamp_s < fault_start_time:
                                continue

                            message = log_entry.get('message', '')

                            # Detect connection timeouts
                            if 'connection timeout' in message.lower() or 'connection timed out' in message.lower():
                                if ' to ' in message:
                                    parts = message.split(' to ')
                                    if len(parts) >= 2:
                                        target = parts[-1].split(':')[0].split(',')[0].strip()

                                        attributes = log_entry.get('attributes', {})
                                        component_id = attributes.get('component.id') or log_entry.get('component_id')

                                        # Map pod to service
                                        if component_id and component_id.startswith('pod_'):
                                            service = '_'.join(component_id.split('_')[1:-1])
                                        else:
                                            service = component_id

                                        if service and target:
                                            key = (service, target)
                                            connection_errors[key] = connection_errors.get(key, 0) + 1
                        except:
                            continue

                # Check if any edge has significant connection errors
                for (source, target), count in connection_errors.items():
                    if count >= 10:  # At least 10 connection timeouts indicates partition
                        # Build reason with double confirmation if metric gap also detected
                        gap_info = metric_gaps.get((source, target))
                        if gap_info:
                            reason = (f'Network partition detected: {source} -> {target} '
                                     f'(Logs: {count} connection timeouts, '
                                     f'Metrics: {gap_info["gap_ratio"]*100:.0f}% frequency drop '
                                     f'{gap_info["baseline_freq"]:.2f} → {gap_info["current_freq"]:.2f}/s)')
                            confidence = 0.98  # Higher confidence with double confirmation
                            network_partitions.append({
                                'source': source,
                                'target': target,
                                'reason': reason,
                                'confidence': confidence,
                                'double_confirmed': True
                            })
            except Exception as e:
                print(f"  [!] Warning: Log-based partition detection failed: {e}")

        # Create global_network candidate if partitions detected
        if network_partitions:
            print(f"  [!] Network partition detected: {len(network_partitions)} blocked edge(s)")
            for partition in network_partitions:
                print(f"      - {partition['reason']}")

            # Score based on confirmation level
            avg_confidence = sum(p['confidence'] for p in network_partitions) / len(network_partitions)
            double_confirmed_count = sum(1 for p in network_partitions if p.get('double_confirmed', False))

            # Only add as strong candidate if double-confirmed (logs + metrics)
            if double_confirmed_count > 0:
                network_score = 100.0  # Strong evidence
                print(f"  [!] Double-confirmed partition (logs + metrics), treating as high-confidence root cause")
            else:
                network_score = 30.0  # Weak evidence, likely symptom of service failure
                print(f"  [!] Single-confirmation partition (logs only), scoring lower - may be symptom not cause")

            network_partition_candidate = {
                'node': 'global_network',
                'score': network_score,
                'score_composition': {
                    'base_health': {'raw': 0, 'confidence': 'high', 'multiplier': 1.0, 'points': 0},
                    'physics_coverage': {'raw': 0, 'weight': 60.0, 'points': 0},
                    'semantic_bonus': {'is_primary': True, 'coverage_context': 'high', 'points': 0},
                    'supplements': {'temporal': 0, 'trace': 0, 'trace_degradation': 0, 'logs': network_score}
                },
                'story': [
                    '🔴 ROOT CAUSE: global_network (Network Partition)',
                    '   Network partitions detected:',
                    *[f'   - {p["reason"]}' for p in network_partitions],
                    f'',
                    f'   Detection confidence: {avg_confidence*100:.0f}%',
                    f'   Double-confirmed edges: {double_confirmed_count}/{len(network_partitions)}'
                ],
                'integrated_score': 0.0,
                'self_score': 0.0,
                'symptoms': [f'Network partition detected ({len(network_partitions)} blocked edges)'],
                'health_metadata': {
                    'network_partition_count': len(network_partitions),
                    'avg_confidence': avg_confidence,
                    'double_confirmed_count': double_confirmed_count,
                    'detection_method': 'log_analysis + metric_gaps' if double_confirmed_count > 0 else 'log_analysis'
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

            # PRINCIPLED: Always use pod-integrated score when pods exist (it's the ground truth)
            # Service-level score is just a lossy aggregate - only use it as fallback
            if health_metadata.get('source') == 'pod-level':
                # Pod analysis is authoritative - use high confidence
                self_val = integrated_score
                confidence = 'high'  # Pod-level is concrete evidence
                confidence_multiplier = 1.0
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
                'story': physics_hypotheses.get(node).narrative if node in physics_hypotheses else [],
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
