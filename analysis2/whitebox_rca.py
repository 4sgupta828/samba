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

# NEW: Temporal and Trace Analysis
from temporal_analyzer import TemporalAnalyzer
from trace_analyzer import TraceAnalyzer

class WhiteboxRCAEngine:
    def __init__(self, topology: nx.DiGraph, config: Dict = None, threshold_config: Dict = None):
        self.topology = topology
        self.config_extractor = ConfigExtractor(config)

        # NEW: Threshold configuration (reduces brittleness)
        from rca_config import get_thresholds
        self.thresholds = get_thresholds(threshold_config)

        # Pass threshold config to all analyzers
        self.self_analyzer = SelfHealthAnalyzer(self.config_extractor, threshold_config)
        self.disambiguator = CallerCalleeDisambiguator()
        self.storyteller = CausalChainAnalyzer(topology)

        # NEW: Advanced analyzers
        self.temporal_analyzer = TemporalAnalyzer(topology)
        self.trace_analyzer = TraceAnalyzer(topology)  # Pass topology for service-level aggregation

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
                         baseline_pods: Optional[Dict[str, Dict[str, np.ndarray]]] = None,
                         current_pods: Optional[Dict[str, Dict[str, np.ndarray]]] = None) -> List[Dict]:

        # --- PHASE 1: Self-Health (Internal Evidence) ---
        self_scores = {}
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

        # --- PHASE 2: Network Partition Detection (NEW) ---
        # Detect network partitions: completely blocked communication between nodes
        # Strategy: If two nodes have zero throughput on their connection edge,
        # this indicates a network partition
        network_partitions = []

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

        # If network partitions detected, return early with global_network as root cause
        if network_partitions:
            print(f"  [!] Network partition detected: {len(network_partitions)} blocked edge(s)")
            for partition in network_partitions:
                print(f"      - {partition['reason']}")

            # Return global_network as the root cause
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
                'symptoms': ['Network partition detected between components'],
                'blamed_by': [],
                'temporal_info': {},
                'trace_info': {},
                'health_metadata': {},
                'is_trace_authoritative': True,
                'story': [
                    '🔴 ROOT CAUSE: global_network (Network Partition)',
                    '   Network partitions detected:',
                    *[f'   - {p["reason"]}' for p in network_partitions]
                ],
                'network_partitions': network_partitions
            }]

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
            verdict = self.disambiguator.analyze_edge(
                caller_metrics_base=baseline_data.get(u, {}),
                caller_metrics_curr=current_data.get(u, {}),
                callee_metrics_base=baseline_data.get(v, {}),
                callee_metrics_curr=current_data.get(v, {})
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
                        # Compare against the distribution of all node scores
                        all_scores = [self_scores.get(n, 0.0) for n in self.topology.nodes]
                        severity_threshold = np.percentile(all_scores, 90) if len(all_scores) > 5 else 20.0

                        if max_severity >= severity_threshold and max_severity > 5.0:
                            # Don't filter - severe pod is significant relative to others
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
            if service_self_score == 0.0 and integrated_score < 1.0:
                # If no symptoms, no guilt, and no temporal signal, likely healthy
                if guilt_ratio == 0.0 and temporal_score == 0.0:
                    is_healthy = True
                    health_filter_reason = "No symptoms detected"

            # 8. Calculate Final Score (First Principles Formula)
            # Base score: Internal evidence is PRIMARY (0-100 points)
            base_score = integrated_score * 10.0

            # Authoritative trace evidence is strong confirmation
            if is_trace_authoritative:
                base_score += 50.0

            # Victim penalty: If confirmed victim, heavily penalize
            # (Keep in rankings but score very low)
            if is_victim and integrated_score < 2.0:
                base_score = base_score * 0.1  # 90% penalty

            # Healthy node penalty: Strongly penalize clearly healthy nodes
            if is_healthy:
                base_score = base_score * 0.05  # 95% penalty (stronger than victim penalty)

            # Confirmation signals: External evidence is SECONDARY (0-40 points total)
            # Use ADJUSTED guilt (with probabilistic discounting) instead of raw guilt
            confirmation_score = (
                (adjusted_guilt * 20.0) +     # Adjusted Guilt: 0-20 (with proxy discounting!)
                (temporal_score * 2.0) +      # Temporal: 0-40
                impact_bonus +                # Impact: 0-3 (log scale)
                capacity_degradation_bonus    # Capacity Loss: 0-20 (zombie pods)
            )

            final_score = base_score + confirmation_score

            # Store results
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
                'story': []  # Populated later
            })

        # Sort descending
        sorted_rankings = sorted(rankings, key=lambda x: x['score'], reverse=True)
        
        # --- PHASE 4: Story Generation ---
        if sorted_rankings:
            top_candidate = sorted_rankings[0]
            top_candidate['story'] = self.storyteller.generate_story(
                top_candidate['node'], 
                top_candidate['symptoms'], 
                incoming_votes
            )

        return sorted_rankings