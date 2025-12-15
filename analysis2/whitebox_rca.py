"""
whitebox_rca.py

The SOTA Root Cause Analysis Engine (v4.0).
Integrates:
1. Self-Health (Saturation + Deadlock detection)
2. Edge Disambiguation (Traffic vs. Retry patterns)
3. Hub Bias Correction (Guilt Ratio)
4. Causal Narratives
5. Temporal Causality Analysis (NEW - changepoint detection)
6. Trace-Based Latency Analysis (NEW - self-time vs total-time)
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
    def __init__(self, topology: nx.DiGraph, config: Dict = None):
        self.topology = topology
        self.config_extractor = ConfigExtractor(config)
        self.self_analyzer = SelfHealthAnalyzer(self.config_extractor)
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

        # --- PHASE 2: Graph Propagation (External Evidence) ---
        # "Who blames who?"
        incoming_votes = defaultdict(list) # target -> [votes]

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
                incoming_votes[v].append({'source': u, 'weight': 1.0, 'reason': verdict.reason})

            elif verdict.blames_caller:
                # v implies u is attacking (DDoS)
                incoming_votes[u].append({'source': v, 'weight': 0.5, 'reason': verdict.reason})

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

            # 2. Trace Analysis (for victim detection and authoritative evidence)
            trace_info = trace_scores.get(node, {})
            trace_score = trace_info.get('trace_score', 0.0)
            is_trace_authoritative = trace_info.get('is_authoritative', False)

            # Victim detection: high total-time but low self-time = waiting on dependencies
            total_time_degradation = trace_info.get('total_time_degradation', 1.0)
            self_time_degradation = trace_info.get('self_time_degradation', 1.0)
            is_victim = (total_time_degradation > 3.0 and self_time_degradation < 1.5)

            # 3. Guilt Ratio (Confirmatory Evidence)
            callers = list(self.topology.predecessors(node))
            votes = incoming_votes[node]
            vote_sum = sum(v['weight'] for v in votes)

            if len(callers) > 0:
                guilt_ratio = vote_sum / len(callers)
                # Dampen for small N to avoid noise
                if len(callers) < 5:
                    guilt_ratio *= 0.8
            else:
                guilt_ratio = 0.0

            # 6. Temporal Score
            temporal_info = temporal_scores.get(node, {})
            temporal_score = temporal_info.get('temporal_score', 0.0)

            # 7. Calculate Final Score (First Principles Formula)
            # Base score: Internal evidence is PRIMARY (0-100 points)
            base_score = integrated_score * 10.0

            # Authoritative trace evidence is strong confirmation
            if is_trace_authoritative:
                base_score += 50.0

            # Victim penalty: If confirmed victim, heavily penalize
            # (Keep in rankings but score very low)
            if is_victim and integrated_score < 2.0:
                base_score = base_score * 0.1  # 90% penalty

            # Confirmation signals: External evidence is SECONDARY (0-40 points total)
            confirmation_score = (
                (guilt_ratio * 20.0) +        # Guilt: 0-20 (reduced from 100!)
                (temporal_score * 2.0)        # Temporal: 0-40
            )

            final_score = base_score + confirmation_score

            # Store results
            rankings.append({
                'node': node,
                'score': round(final_score, 2),
                'integrated_score': round(integrated_score, 2),
                'guilt_ratio': round(guilt_ratio, 2),
                'self_score': round(service_self_score, 2),
                'temporal_score': round(temporal_score, 2),
                'trace_score': round(trace_score, 2),
                'symptoms': symptoms_map.get(node, []),
                'blamed_by': [v['source'] for v in votes],
                'temporal_info': temporal_info,
                'trace_info': trace_info,
                'health_metadata': health_metadata,
                'is_trace_authoritative': is_trace_authoritative,
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