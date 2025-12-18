"""
whitebox_rca.py

The SOTA Root Cause Analysis Engine (v4.1).
Integrates:
1. Self-Health (Saturation + Deadlock detection)
2. Edge Disambiguation (Traffic vs. Retry patterns)
3. Hub Bias Correction (Guilt Ratio)
4. Probabilistic Blame Discounting (Solves Proxy/Middleman problem)
5. Causal Narratives
6. Temporal Causality Analysis (Changepoint detection)
7. Trace-Based Latency Analysis (Self-time vs total-time)
"""

import numpy as np
import networkx as nx
import math
import pandas as pd
from typing import Dict, List, Any, Optional
from collections import defaultdict
from pathlib import Path

# Core Components
from self_health_analyzer import SelfHealthAnalyzer
from disambiguator import CallerCalleeDisambiguator
from config_extractor import ConfigExtractor
from causal_chain_analyzer import CausalChainAnalyzer
from causal_graph_reasoner import CausalGraphReasoner

# NEW: Temporal and Trace Analysis
from temporal_analyzer import TemporalAnalyzer
from trace_analyzer import TraceAnalyzer
from log_analyzer import LogAnalyzer

class WhiteboxRCAEngine:
    def __init__(self, topology: nx.DiGraph, config: Dict = None, threshold_config: Dict = None):
        self.topology = topology
        self.config_extractor = ConfigExtractor(config)

        # NEW: Threshold configuration (reduces brittleness)
        from rca_config import get_thresholds
        self.thresholds = get_thresholds(threshold_config)

        # Pass threshold config to all analyzers
        self.self_analyzer = SelfHealthAnalyzer(self.config_extractor, threshold_config)
        self.reasoner = CausalGraphReasoner(topology)  # Physics Engine
        self.disambiguator = CallerCalleeDisambiguator(self.reasoner)  # Hybrid Disambiguator
        self.storyteller = CausalChainAnalyzer(topology)

        # NEW: Advanced analyzers
        self.temporal_analyzer = TemporalAnalyzer(topology)
        self.trace_analyzer = TraceAnalyzer(topology)  # Pass topology for service-level aggregation
        self.log_analyzer = LogAnalyzer()

    def validate_ground_truth(self, ground_truth_node: str, candidates: List[Dict]) -> Dict:
        """
        Validate that the ground truth label actually shows evidence of being faulty.

        This helps identify:
        1. Invalid ground truth labels (fault injection didn't work)
        2. Data quality issues
        3. Cases where RCA should not be evaluated

        Returns:
            Dict with validation results including is_valid, confidence, reasons, and evidence_score
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
                'reasons': [f"Ground truth node '{ground_truth_node}' not found in topology"],
                'verdict': "❌ Ground truth node not found in analysis"
            }

        # Score evidence using adaptive thresholds
        evidence_score = 0
        reasons = []

        # 1. Check for symptoms (0-3 points)
        symptom_count = len(gt_candidate.get('symptoms', []))
        if symptom_count > 0:
            evidence_score += min(3, symptom_count)
            reasons.append(f"✓ Has {symptom_count} symptoms detected")
        else:
            reasons.append("⚠️ No symptoms detected")

        # 2. Check trace evidence (0-5 points)
        trace_info = gt_candidate.get('trace_info', {})
        if trace_info:
            is_authoritative = trace_info.get('is_authoritative', False)
            self_time_deg = trace_info.get('self_time_degradation', 1.0)

            if is_authoritative:
                if self_time_deg > self.thresholds.min_effect_size_large:
                    evidence_score += 5
                    reasons.append(f"✓ Strong authoritative trace evidence: {self_time_deg:.1f}x degradation")
                elif self_time_deg > self.thresholds.min_effect_size_medium:
                    evidence_score += 3
                    reasons.append(f"✓ Moderate authoritative trace evidence: {self_time_deg:.1f}x degradation")
                else:
                    evidence_score += 1
                    reasons.append(f"⚠️ Weak authoritative trace evidence: {self_time_deg:.1f}x degradation")
            else:
                reasons.append("⚠️ Non-authoritative trace evidence (might be victim)")
        else:
            reasons.append("⚠️ No trace evidence")

        # 3. Check health status (0-2 points)
        is_healthy = gt_candidate.get('is_healthy', True)
        if not is_healthy:
            evidence_score += 2
            reasons.append("✓ Marked as unhealthy by health filter")
        else:
            reasons.append("⚠️ Marked as healthy by health filter")

        # 4. Check integrated score (0-2 points)
        integrated_score = gt_candidate.get('integrated_score', 0)
        if integrated_score > self.thresholds.min_absolute_severity:
            evidence_score += 2
            reasons.append(f"✓ High integrated_score: {integrated_score:.1f}")
        elif integrated_score > 0:
            evidence_score += 1
            reasons.append(f"⚠️ Low integrated_score: {integrated_score:.1f}")
        else:
            reasons.append("⚠️ Zero integrated_score")

        # Determine validity using statistical thresholds
        # Max score: 12 points
        # High confidence: 8+, Medium: 5-7, Low: 2-4, Very low: 0-1
        if evidence_score >= 8:
            is_valid = True
            confidence = 'high'
            verdict = "✅ Strong evidence that ground truth is actually faulty"
        elif evidence_score >= 5:
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
            'max_evidence_score': 12,
            'reasons': reasons,
            'verdict': verdict,
            'ground_truth_node': ground_truth_node,
            'ground_truth_rank': None,  # Will be filled in by caller
            'ground_truth_score': gt_candidate.get('score', 0),
        }

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
                         baseline_data: Dict[str, Dict[str, np.ndarray]],
                         current_data: Dict[str, Dict[str, np.ndarray]],
                         metrics_df: Optional[pd.DataFrame] = None,
                         fault_start_time: Optional[float] = None,
                         traces_file: Optional[Path] = None,
                         logs_file: Optional[Path] = None,
                         baseline_pods: Optional[Dict[str, Dict[str, np.ndarray]]] = None,
                         current_pods: Optional[Dict[str, Dict[str, np.ndarray]]] = None) -> List[Dict]:

        # --- PHASE 1: Self-Health (Internal Evidence) ---
        self_scores = {}
        self_analyses = {}  # Store full analysis objects for physics engine
        symptoms_map = {}

        for node in self.topology.nodes:
            # Skip pod-level nodes - they are analyzed separately in pod forensics
            node_attrs = self.topology.nodes[node]
            if node_attrs.get('parent_service') is not None:
                # This is a pod - skip it
                continue

            # Get node type from topology metadata if available
            node_type = node_attrs.get('type', 'Service')

            # Skip infrastructure/control plane nodes
            if node_type == 'DeploymentController':
                continue

            b_metrics = baseline_data.get(node, {})
            c_metrics = current_data.get(node, {})

            analysis = self.self_analyzer.analyze(node, node_type, b_metrics, c_metrics)
            self_scores[node] = analysis.self_degradation_score
            self_analyses[node] = analysis  # Store full analysis for physics
            symptoms_map[node] = analysis.symptoms

        # --- PHASE 1.5: Temporal Causality Analysis (NEW) ---
        temporal_scores = {}
        if metrics_df is not None and fault_start_time is not None:
            try:
                temporal_scores = self.temporal_analyzer.analyze(
                    metrics_df, fault_start_time, self_scores
                )
            except Exception as e:
                print(f"  [!] Warning: Temporal analysis failed: {e}")

        # --- PHASE 1.6: Trace Analysis (NEW) ---
        trace_scores = {}
        if traces_file is not None and fault_start_time is not None:
            try:
                trace_scores = self.trace_analyzer.analyze(
                    traces_file, fault_start_time
                )
            except Exception as e:
                print(f"  [!] Warning: Trace analysis failed: {e}")

        # --- PHASE 1.7: Log Analysis (NEW) ---
        log_scores = {}
        if logs_file and logs_file.exists():
            try:
                log_scores = self.log_analyzer.analyze(logs_file, fault_start_time)
            except Exception as e:
                print(f"  [!] Warning: Log analysis failed: {e}")

        # --- PHASE 2: Network Partition Detection (NEW) ---
        # Detect network partitions: completely blocked communication between nodes
        # Strategy 1: Check metrics for data gaps on edges (provides context)
        # Strategy 2: Check logs for connection timeout patterns (PRIMARY signal)
        # Double confirmation aligns with human diagnosis approach
        network_partitions = []
        metric_gaps = {}  # Track edges with metric gaps for confirmation

        # STRATEGY 1: Detect metric gaps (secondary confirmation)
        # Check if per-dependency metrics show gaps during fault period
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

                                # Detect gap: frequency dropped by >50% (network partition may not drop to zero due to retries/fallbacks)
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

        # STRATEGY 2: Scan logs for connection timeout patterns (most reliable signal)
        if logs_file and logs_file.exists():
            import json
            connection_errors = {}  # {(source, target): count}

            # Calculate fault window (fault_start_time to end of episode)
            # Only count errors during the fault period, not baseline
            fault_window_start = fault_start_time if fault_start_time else 0

            try:
                with open(logs_file, 'r') as f:
                    for line in f:
                        try:
                            log_entry = json.loads(line)

                            # CRITICAL: Only count errors during fault period
                            # Logs use nanosecond timestamps, need to convert to seconds
                            log_timestamp_ns = log_entry.get('timestamp', 0)
                            log_timestamp_s = log_timestamp_ns / 1e9 if log_timestamp_ns > 1e12 else log_timestamp_ns

                            # Skip if before fault injection (baseline period)
                            if log_timestamp_s < fault_window_start:
                                continue

                            message = log_entry.get('message', '')

                            # Detect "Connection timeout to X" or "Connection timed out: network partition between X and Y"
                            if 'connection timeout' in message.lower() or 'connection timed out' in message.lower():
                                # Extract target from message
                                # Pattern: "... to <target>" or "... between <source> and <target>"
                                if ' to ' in message:
                                    parts = message.split(' to ')
                                    if len(parts) >= 2:
                                        target = parts[-1].split(':')[0].split(',')[0].strip()

                                        # Get component ID from attributes
                                        attributes = log_entry.get('attributes', {})
                                        component_id = attributes.get('component.id') or log_entry.get('component_id')

                                        # Map pod to service
                                        if component_id and component_id.startswith('pod_'):
                                            # Extract service name from pod_<service>_<num>
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
                        # Check if this edge exists in topology
                        if self.topology.has_edge(source, target):
                            edge_data = self.topology.edges[source, target]

                            # Build reason with double confirmation if metric gap also detected
                            gap_info = metric_gaps.get((source, target))
                            if gap_info:
                                reason = (f'Network partition detected: {source} -> {target} '
                                         f'(Logs: {count} connection timeouts, '
                                         f'Metrics: {gap_info["gap_ratio"]*100:.0f}% frequency drop '
                                         f'{gap_info["baseline_freq"]:.2f} → {gap_info["current_freq"]:.2f}/s)')
                                confidence = 0.98  # Higher confidence with double confirmation
                            else:
                                reason = f'Network partition detected: {source} -> {target} ({count} connection timeout errors in logs)'
                                confidence = 0.95

                            network_partitions.append({
                                'source': source,
                                'target': target,
                                'edge_type': edge_data.get('type', 'unknown'),
                                'reason': reason,
                                'confidence': confidence,
                                'double_confirmed': gap_info is not None
                            })
            except Exception as e:
                print(f"  [!] Warning: Log-based partition detection failed: {e}")

        for u, v in self.topology.edges:
            edge_data = self.topology.edges[u, v]
            edge_type = edge_data.get('type', 'sync_http')

            # Skip non-dependency edges
            if edge_type in ['pod_pool', 'pod_placement', 'node_placement']:
                continue

            # Check for blocked throughput indicating network partition
            # For async_consume edges: check for queue backlog explosion
            if edge_type == 'async_consume':
                # Strategy: Network partition causes queue to build up massively
                # because consumer cannot pull messages from queue
                queue_metrics_base = baseline_data.get(u, {})
                queue_metrics_curr = current_data.get(u, {})
                consumer_metrics_base = baseline_data.get(v, {})

                # Check queue depth growth using STATISTICAL methods
                baseline_depth = queue_metrics_base.get('queue_depth', np.array([]))
                current_depth = queue_metrics_curr.get('queue_depth', np.array([]))

                if len(baseline_depth) > 0 and len(current_depth) > 0:
                    # Check if consumer was active using percentile-based threshold
                    baseline_consumer_rps = consumer_metrics_base.get('inbound_rps', np.array([]))
                    activity_threshold = self.thresholds.get_dynamic_threshold(
                        baseline_consumer_rps, 'consumer_rps',
                        self.thresholds.consumer_activity_percentile
                    )
                    was_active = len(baseline_consumer_rps) > 0 and np.mean(baseline_consumer_rps) > activity_threshold

                    # Detect partition using EFFECT SIZE instead of absolute thresholds
                    has_large_growth = self.thresholds.has_large_effect(baseline_depth, current_depth, 'queue')

                    # Additional check: current depth should be significantly high
                    # Use 90th percentile of baseline as minimum threshold
                    baseline_p90 = np.percentile(baseline_depth, 90)
                    current_avg = np.mean(current_depth)
                    is_significantly_high = current_avg > max(baseline_p90 * 2, 10)  # At least 2x p90 or 10 msgs

                    if was_active and has_large_growth and is_significantly_high:
                        baseline_avg_depth = np.mean(baseline_depth)
                        current_avg_depth = np.mean(current_depth)

                        network_partitions.append({
                            'source': u,
                            'target': v,
                            'edge_type': edge_type,
                            'reason': f'Blocked async consumption: {u} -> {v} (queue backlog exploded from {baseline_avg_depth:.0f} to {current_avg_depth:.0f} messages, consumer unreachable)',
                            'confidence': 0.95
                        })

            # For sync edges: check for complete failure (100% errors + zero throughput)
            elif edge_type in ['sync_http', 'sync_db', 'sync_cache', 'sync_external']:
                caller_metrics = current_data.get(u, {})
                dep_error_rate = caller_metrics.get('dependency_error_rate', np.array([]))
                dep_rps = caller_metrics.get('outbound_rps', np.array([]))

                if len(dep_error_rate) > 0 and len(dep_rps) > 0:
                    avg_error = np.mean(dep_error_rate)
                    avg_rps = np.mean(dep_rps)

                    # High error rate but RPS exists (trying but failing)
                    if avg_error > 0.95 and avg_rps > 0.1:
                        # Check baseline to confirm degradation
                        baseline_error = baseline_data.get(u, {}).get('dependency_error_rate', np.array([]))
                        baseline_avg_error = np.mean(baseline_error) if len(baseline_error) > 0 else 0

                        if baseline_avg_error < 0.1:  # Was healthy before
                            network_partitions.append({
                                'source': u,
                                'target': v,
                                'edge_type': edge_type,
                                'reason': f'Complete connection failure: {u} -> {v} ({avg_error*100:.0f}% errors)',
                                'confidence': 0.95
                            })

                # PATTERN 2: Network partition blocks calls entirely (zero outbound calls)
                # Service has inbound traffic + internal errors, but ZERO outbound calls
                # Check if:
                # 1. Caller had outbound traffic in baseline (edge was active)
                # 2. Caller has zero outbound traffic now (edge is silent)
                # 3. Caller has high internal error rate (service is failing)
                # 4. Caller has inbound traffic (service is being used)
                baseline_caller = baseline_data.get(u, {})
                current_caller = current_data.get(u, {})

                baseline_out_rps = baseline_caller.get('outbound_rps', np.array([]))
                current_out_rps = current_caller.get('outbound_rps', np.array([]))
                current_in_rps = current_caller.get('inbound_rps', np.array([]))
                current_error_rate = current_caller.get('internal_error_rate', np.array([]))

                if (len(baseline_out_rps) > 0 and len(current_out_rps) > 0 and
                    len(current_in_rps) > 0 and len(current_error_rate) > 0):

                    baseline_avg_out = np.mean(baseline_out_rps)
                    current_avg_out = np.mean(current_out_rps)
                    current_avg_in = np.mean(current_in_rps)
                    current_avg_error = np.mean(current_error_rate)

                    # Detect partition: was calling target, now silent + high errors + has inbound traffic
                    was_active = baseline_avg_out > 1.0  # Was making calls
                    now_silent = current_avg_out < 0.1  # No calls now
                    has_inbound = current_avg_in > 0.5  # Service is being used
                    has_errors = current_avg_error > 0.5  # Service is erroring

                    if was_active and now_silent and has_inbound and has_errors:
                        network_partitions.append({
                            'source': u,
                            'target': v,
                            'edge_type': edge_type,
                            'reason': f'Network partition: {u} -> {v} (edge silent: {baseline_avg_out:.1f} -> {current_avg_out:.1f} RPS, service error rate: {current_avg_error*100:.0f}%)',
                            'confidence': 0.90
                        })

        # If network partitions detected, return early with global_network as root cause
        if network_partitions:
            print(f"  [!] Network partition detected: {len(network_partitions)} blocked edge(s)")
            for partition in network_partitions:
                print(f"      - {partition['reason']}")

            # Return global_network as the root cause
            # Score breakdown: 100 points from network partition detection (log + metric evidence)
            # Calculate average confidence across all detected partitions
            avg_confidence = sum(p['confidence'] for p in network_partitions) / len(network_partitions)
            double_confirmed_count = sum(1 for p in network_partitions if p.get('double_confirmed', False))

            return [{
                'node': 'global_network',
                'score': 100.0,
                'integrated_score': 0.0,
                'guilt_raw': 0.0,
                'guilt_adjusted': 0.0,
                'discount_factor': 1.0,
                'max_outgoing_conf': 0.0,
                'self_score': 0.0,
                'temporal_score': 0.0,
                'trace_score': 0.0,
                'log_score': 100.0,  # All 100 points from log-based network partition detection
                'symptoms': ['Network partition detected between components'],
                'blamed_by': [],
                'temporal_info': {},
                'trace_info': {},
                'health_metadata': {
                    'network_partition_count': len(network_partitions),
                    'avg_confidence': avg_confidence,
                    'double_confirmed_count': double_confirmed_count,
                    'detection_method': 'log_analysis + metric_gaps' if double_confirmed_count > 0 else 'log_analysis'
                },
                'score_breakdown': {
                    # All components zero except log_bonus
                    'base_health_score': 0.0,
                    'trace_symptom_bonus': 0.0,
                    'symptom_strength_bonus': 0.0,
                    'trace_boost': 0.0,
                    'base_before_penalties': 0.0,
                    'base_after_penalties': 0.0,
                    'physics_coverage': 0.0,
                    'coverage_score': 0.0,
                    'guilt_component': 0.0,
                    'temporal_component': 0.0,
                    'impact_bonus': 0.0,
                    'capacity_bonus': 0.0,
                    'confirmation_score': 0.0,
                    'log_bonus': 100.0,  # All 100 points from network partition detection
                    'victim_penalty_applied': False,
                    'healthy_penalty_applied': False
                },
                'is_trace_authoritative': True,
                'story': [
                    '🔴 ROOT CAUSE: global_network (Network Partition)',
                    '   Network partitions detected:',
                    *[f'   - {p["reason"]}' for p in network_partitions],
                    f'',
                    f'   Detection confidence: {avg_confidence*100:.0f}%',
                    f'   Double-confirmed edges: {double_confirmed_count}/{len(network_partitions)}'
                ],
                'network_partitions': network_partitions
            }]

        # --- PHASE 2.3: Physics Coverage (The "Precision Scope") ---
        candidates = [n for n, analysis in self_analyses.items() if analysis.is_root_cause_candidate]

        physics_hypotheses = self.reasoner.calculate_global_coverage(
            candidates, self_analyses, baseline_data, current_data
        )

        # --- PHASE 2.5: Graph Propagation (External Evidence) ---
        # "Who blames who?" - Track both incoming votes and outgoing blame
        incoming_votes = defaultdict(list) # target -> [votes]
        outgoing_blame = defaultdict(list) # source -> [confidence_scores]

        for u, v in self.topology.edges:
            edge_data = self.topology.edges[u, v]
            edge_type = edge_data.get('type', 'sync_http')

            # Skip non-dependency edges (pod_pool, pod_placement, etc.)
            if edge_type in ['pod_pool', 'pod_placement', 'node_placement']:
                continue

            # Handle async consume edges differently
            # For async_consume: queue -> consumer
            # If consumer is degraded, it's likely the consumer's fault (slow processing)
            # not the queue's fault
            if edge_type == 'async_consume':
                # Check if consumer (v) is degraded
                consumer_score = self_scores.get(v, 0.0)
                if consumer_score > 2.0:
                    # Consumer is degraded - likely consumer's fault
                    # Don't blame the queue (u)
                    pass
                continue

            # For sync edges (HTTP, cache, DB, external service calls)
            # u calls v. Analyze the edge.
            # Pass full context for physics validation
            verdict = self.disambiguator.analyze_edge(
                u, v,
                caller_metrics_base=baseline_data.get(u, {}),
                caller_metrics_curr=current_data.get(u, {}),
                callee_metrics_base=baseline_data.get(v, {}),
                callee_metrics_curr=current_data.get(v, {}),
                baseline_data=baseline_data,
                current_data=current_data,
                health_scores=self_analyses
            )

            if verdict.blames_callee:
                # u blames v (standard)
                # Use confidence from disambiguator as the vote weight
                weight = verdict.confidence
                incoming_votes[v].append({'source': u, 'weight': weight, 'reason': verdict.reason})
                outgoing_blame[u].append(weight)

            elif verdict.blames_caller:
                # v implies u is attacking (DDoS)
                # Use confidence from disambiguator
                weight = verdict.confidence
                incoming_votes[u].append({'source': v, 'weight': weight, 'reason': verdict.reason})
                outgoing_blame[v].append(weight)

        # --- PHASE 3: Global Ranking with Hub Bias Correction ---
        rankings = []

        for node in self.topology.nodes:
            # Skip pod-level nodes - they are analyzed separately in pod forensics
            node_attrs = self.topology.nodes[node]
            if node_attrs.get('parent_service') is not None:
                continue

            # Skip infrastructure/control plane nodes
            if node_attrs.get('type') == 'DeploymentController':
                continue

            # 1. Calculate Integrated Health Score (Service + Pod, Coverage-Weighted)
            service_self_score = self_scores.get(node, 0.0)
            integrated_score, health_metadata = self.calculate_integrated_health_score(
                node, service_self_score, baseline_pods, current_pods
            )

            # 1.5. Capacity Degradation Detection (Zombie Pod Detection)
            # Check if some pods are zombies (not serving traffic) causing capacity loss
            capacity_degradation_bonus = 0.0
            if health_metadata.get('source') == 'pod-level':
                degraded_count = health_metadata.get('degraded_count', 0)
                total_count = health_metadata.get('total_count', 0)

                if total_count > 0 and degraded_count > 0:
                    # Check if any degraded pods have zombie symptoms
                    zombie_count = 0
                    for pod_id in [n for n in self.topology.nodes
                                   if self.topology.nodes[n].get('parent_service') == node]:
                        pod_curr = current_pods.get(pod_id, {})
                        pod_base = baseline_pods.get(pod_id, {})

                        if not pod_curr:
                            continue

                        # Check for zombie pattern: was active, now has zero throughput
                        base_rps = np.mean(pod_base.get('inbound_rps', np.array([0])))
                        curr_rps = np.mean(pod_curr.get('inbound_rps', np.array([0])))

                        if base_rps > self.thresholds.was_active_absolute and curr_rps < self.thresholds.throughput_near_zero_absolute:
                            zombie_count += 1

                    # If we have zombie pods, this indicates capacity degradation
                    if zombie_count > 0:
                        capacity_loss_pct = (zombie_count / total_count) * 100
                        capacity_degradation_bonus = min(20.0, zombie_count * 5.0)  # Up to 20 bonus points
                        health_metadata['zombie_pods'] = zombie_count
                        health_metadata['capacity_loss_pct'] = capacity_loss_pct

            # 2. Trace Analysis (for victim detection and authoritative evidence)
            trace_info = trace_scores.get(node, {})
            trace_score = trace_info.get('trace_score', 0.0)
            is_trace_authoritative = trace_info.get('is_authoritative', False)

            # Victim detection: high total-time but low self-time = waiting on dependencies
            total_time_degradation = trace_info.get('total_time_degradation', 1.0)
            self_time_degradation = trace_info.get('self_time_degradation', 1.0)
            is_victim = (total_time_degradation > 3.0 and self_time_degradation < 1.5)

            # 3. Guilt Ratio (External Evidence) - Hub Bias Correction
            # P_in: Probability node is faulty based on callers
            callers = list(self.topology.predecessors(node))
            votes = incoming_votes[node]
            vote_sum = sum(v['weight'] for v in votes)

            if len(callers) > 0:
                guilt_ratio = vote_sum / len(callers)
                # Dampen for small N to avoid noise (Law of Large Numbers)
                if len(callers) < 5:
                    guilt_ratio *= 0.8
            else:
                guilt_ratio = 0.0

            # 4. Probabilistic Blame Discounting (Solving Proxy/Middleman Problem)
            # P_out: Probability node is blaming downstream dependencies
            # If I am blaming downstream dependencies with high confidence,
            # I am likely a conduit, not the root cause.
            # Discount Factor = 1.0 - (Max_Outgoing_Confidence * 0.8)
            # We use 0.8 as max discount because shared faults can exist
            my_outgoing = outgoing_blame.get(node, [])
            max_outgoing_conf = max(my_outgoing) if my_outgoing else 0.0
            discount_factor = 1.0 - (max_outgoing_conf * 0.8)

            # Net Fault Probability: P_root ≈ P_in × (1 - P_out)
            adjusted_guilt = guilt_ratio * discount_factor

            # 5. Impact Bonus (Log Traffic)
            b_metrics = baseline_data.get(node, {})
            traffic_metric = b_metrics.get('inbound_rps')
            if traffic_metric is None or (hasattr(traffic_metric, '__len__') and len(traffic_metric) == 0):
                traffic_metric = b_metrics.get('request_rate')

            if traffic_metric is not None and hasattr(traffic_metric, '__len__') and len(traffic_metric) > 0:
                traffic_vol = np.mean(traffic_metric)
            else:
                traffic_vol = 1.0

            impact_bonus = math.log10(max(1.0, traffic_vol))

            # 6. Temporal Score
            temporal_info = temporal_scores.get(node, {})
            temporal_score = temporal_info.get('temporal_score', 0.0)

            # 7. Healthy Node Filtering (NEW) - Eliminate false positives
            # Filter out nodes that are clearly healthy to avoid noise
            is_healthy = False
            health_filter_reason = None

            # Check pod-level only detections with low coverage
            if health_metadata.get('source') == 'pod-level':
                coverage = health_metadata.get('coverage', 0.0)
                degraded_count = health_metadata.get('degraded_count', 0)
                max_severity = health_metadata.get('max_severity', 0.0)

                # Low coverage outliers: use configurable threshold
                if coverage < self.thresholds.pod_coverage_threshold and service_self_score < self.thresholds.min_absolute_severity:
                    # Also check: no external blame (not being blamed by others)
                    if guilt_ratio < self.thresholds.guilt_ratio_threshold:
                        # Apply multiple safeguards to avoid filtering true root causes
                        # Use RELATIVE thresholds based on distribution, not absolute values

                        # SAFEGUARD 1: Severe pod degradation (top 10% of all scores)
                        # Use pure percentile-based comparison (no magic numbers)
                        # If a node is in the top 10% of severity, it's significant regardless of absolute value
                        all_scores = [self_scores.get(n, 0.0) for n in self.topology.nodes]

                        # For small samples, still use percentile but with more conservative threshold
                        # Small N: use median (50th percentile) to be less aggressive
                        # Large N: use 90th percentile for top 10% detection
                        percentile = 50 if len(all_scores) <= 5 else 90
                        severity_threshold = np.percentile(all_scores, percentile)

                        if max_severity > severity_threshold:
                            # Don't filter - in top 10% of severity distribution
                            # This correctly handles cases where most nodes are healthy (threshold≈0)
                            # and identifies the most degraded node as significant
                            pass
                        # SAFEGUARD 2: Temporal correlation (statistically significant)
                        # Use relative ranking: top 20% of temporal scores
                        elif temporal_score > 0 and integrated_score > 0:
                            temporal_ratio = temporal_score / max(1.0, integrated_score)
                            if temporal_ratio > 2.0:  # Temporal evidence is 2x stronger than symptoms
                                # Don't filter - strong timing correlation
                                pass
                        # SAFEGUARD 3: Trace analysis (authoritative or strong signal)
                        elif is_trace_authoritative or (trace_score > 0 and trace_score / max(1.0, integrated_score) > 3.0):
                            # Don't filter - traces confirm service involvement
                            pass
                        # SAFEGUARD 4: Capacity loss (zombie pods detected)
                        elif health_metadata.get('zombie_pods', 0) > 0:
                            # Don't filter - capacity degradation detected
                            pass
                        else:
                            # All safeguards passed - safe to filter as healthy noise
                            is_healthy = True
                            health_filter_reason = f"Outlier pod detection ({degraded_count} pod(s), {coverage*100:.0f}% coverage) with no service-level symptoms"

            # Check nodes with zero symptoms but appearing in rankings due to noise
            # IMPORTANT: Don't filter nodes with pod-level symptoms (e.g., hot_shard)
            # Pod-level symptoms ARE real symptoms, even if service-level is 0
            has_pod_symptoms = health_metadata.get('source') == 'pod-level' and integrated_score > 0

            if service_self_score == 0.0 and integrated_score < 1.0:
                # If no symptoms, no guilt, and no temporal signal, likely healthy
                # EXCEPTION: Don't filter if has pod-level symptoms
                if guilt_ratio == 0.0 and temporal_score == 0.0 and not has_pod_symptoms:
                    is_healthy = True
                    health_filter_reason = "No symptoms detected"

            # 8. Calculate Final Score (First Principles Formula)
            # Initialize all score components for explainability
            base_health_score = integrated_score * 10.0
            trace_symptom_bonus = 0.0
            symptom_strength_bonus = 0.0
            trace_boost = 0.0
            victim_penalty_applied = False
            healthy_penalty_applied = False

            base_score = base_health_score

            # FIX 1: Enhanced symptom detection using trace data
            # For infrastructure components (cache, queue, external) with no symptoms
            # but strong trace evidence, treat trace as symptom
            node_type = self.topology.nodes[node].get('type', 'Service')
            is_infrastructure = node_type in ['ExternalCache', 'MessageQueue', 'ExternalService', 'SqlDatabase']

            if is_infrastructure and service_self_score == 0 and is_trace_authoritative:
                # Use trace degradation as symptom for infrastructure
                if self_time_degradation > self.thresholds.min_effect_size_medium:
                    # Add symptom-equivalent score based on trace evidence
                    trace_symptom_bonus = min(10.0, self_time_degradation * 2.0)
                    base_score += trace_symptom_bonus

            # FIX 1B: Boost strong symptom evidence when NO trace data available
            # Services with multiple symptoms but no traces get unfairly penalized
            symptom_count = len(symptoms_map.get(node, []))
            has_no_trace = trace_score == 0

            # Don't boost if this is likely a victim (NOT the root cause)
            # Victim indicators: high blame on dependencies, low self-time if traces exist
            is_likely_victim = is_victim or (max_outgoing_conf > 0.7)

            if has_no_trace and symptom_count >= 2 and service_self_score > 2.0 and not is_healthy and not is_likely_victim:
                # Multiple symptoms with no trace = strong local evidence
                # Boost to compete with trace-based scores
                # Use adaptive boost based on symptom strength
                symptom_strength_bonus = min(100.0, symptom_count * 20.0 + integrated_score * 10.0)
                base_score += symptom_strength_bonus

            # FIX 2: Authoritative trace evidence boost (adaptive multiplier)
            # Instead of flat +50, use multiplier based on degradation severity
            # Authoritative trace = definitive evidence, should dominate symptom-only scores
            if is_trace_authoritative:
                if self_time_degradation > self.thresholds.min_effect_size_very_large:
                    # Critical degradation (>3x): large boost
                    trace_boost = trace_score * 6.0 + 80.0
                elif self_time_degradation > self.thresholds.min_effect_size_large:
                    # Severe degradation (>2x): moderate boost
                    trace_boost = trace_score * 5.0 + 60.0
                else:
                    # Moderate degradation: standard boost
                    trace_boost = trace_score * 4.0 + 40.0
                base_score += trace_boost

            # Store base score before penalties for explainability
            base_score_before_penalties = base_score

            # Victim penalty: If confirmed victim, heavily penalize
            # (Keep in rankings but score very low)
            if is_victim and integrated_score < 2.0:
                base_score = base_score * 0.1  # 90% penalty
                victim_penalty_applied = True

            # Healthy node penalty: Strongly penalize clearly healthy nodes
            # EXCEPTION: Don't penalize if has authoritative trace evidence
            if is_healthy and not is_trace_authoritative:
                base_score = base_score * 0.05  # 95% penalty (stronger than victim penalty)
                healthy_penalty_applied = True

            # B. Physics Coverage Bonus
            # If this node explains 80% of symptoms, it gets massive points.
            coverage_val = physics_hypotheses.get(node).coverage_score if node in physics_hypotheses else 0.0

            # C. Supplemental Evidence
            # Log bonus
            log_bonus = log_scores.get(node, {}).get('log_score', 0.0)

            # Confirmation signals: External evidence is SECONDARY
            # Use ADJUSTED guilt (with probabilistic discounting) instead of raw guilt
            guilt_component = adjusted_guilt * 20.0
            temporal_component = temporal_score * 2.0

            confirmation_score = (
                guilt_component +              # Adjusted Guilt: 0-20 (with proxy discounting!)
                temporal_component +           # Temporal: 0-40
                impact_bonus +                 # Impact: 0-3 (log scale)
                capacity_degradation_bonus     # Capacity Loss: 0-20 (zombie pods)
            )

            # --- THE HYBRID FORMULA ---
            # Self(base_score) + Coverage(40) + Confirmation
            physics_coverage_bonus = coverage_val * 40.0

            final_score = base_score + physics_coverage_bonus + confirmation_score + log_bonus

            # Store results with complete score breakdown for explainability
            rankings.append({
                'node': node,
                'score': round(final_score, 2),
                'integrated_score': round(integrated_score, 2),
                'guilt_raw': round(guilt_ratio, 2),
                'guilt_adjusted': round(adjusted_guilt, 2),
                'discount_factor': round(discount_factor, 2),
                'max_outgoing_conf': round(max_outgoing_conf, 2),
                'self_score': round(service_self_score, 2),
                'temporal_score': round(temporal_score, 2),
                'trace_score': round(trace_score, 2),
                'symptoms': symptoms_map.get(node, []),
                'blamed_by': [v['source'] for v in votes],
                'temporal_info': temporal_info,
                'trace_info': trace_info,
                'health_metadata': health_metadata,
                'is_trace_authoritative': is_trace_authoritative,
                'is_healthy': is_healthy,
                'health_filter_reason': health_filter_reason,
                'story': [],  # Populated later
                # NEW: Complete score breakdown for UI explainability
                'score_breakdown': {
                    'base_health_score': round(base_health_score, 2),
                    'trace_symptom_bonus': round(trace_symptom_bonus, 2),
                    'symptom_strength_bonus': round(symptom_strength_bonus, 2),
                    'trace_boost': round(trace_boost, 2),
                    'base_before_penalties': round(base_score_before_penalties, 2),
                    'victim_penalty_applied': victim_penalty_applied,
                    'healthy_penalty_applied': healthy_penalty_applied,
                    'base_after_penalties': round(base_score, 2),
                    'physics_coverage': round(physics_coverage_bonus, 2),
                    'coverage_score': round(coverage_val, 3),
                    'guilt_component': round(guilt_component, 2),
                    'temporal_component': round(temporal_component, 2),
                    'impact_bonus': round(impact_bonus, 2),
                    'capacity_bonus': round(capacity_degradation_bonus, 2),
                    'log_bonus': round(log_bonus, 2),
                    'confirmation_score': round(confirmation_score, 2),
                }
            })

        # Sort descending
        sorted_rankings = sorted(rankings, key=lambda x: x['score'], reverse=True)
        
        # --- PHASE 4: Story Generation ---
        if sorted_rankings:
            top_candidate = sorted_rankings[0]
            top_node = top_candidate['node']

            # Get narrative from Physics engine if available, else standard
            if top_node in physics_hypotheses:
                story = physics_hypotheses[top_node].narrative
            else:
                story = []

            if not story:
                story = self.storyteller.generate_story(
                    top_node,
                    top_candidate['symptoms'],
                    incoming_votes
                )

            top_candidate['story'] = story

        return sorted_rankings