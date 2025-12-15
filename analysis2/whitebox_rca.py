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
        self.trace_analyzer = TraceAnalyzer()

    def analyze_incident(self,
                         baseline_data: Dict[str, Dict[str, np.ndarray]],
                         current_data: Dict[str, Dict[str, np.ndarray]],
                         metrics_df: Optional[pd.DataFrame] = None,
                         fault_start_time: Optional[float] = None,
                         traces_file: Optional[Path] = None) -> List[Dict]:

        # --- PHASE 1: Self-Health (Internal Evidence) ---
        self_scores = {}
        symptoms_map = {}

        for node in self.topology.nodes:
            # Get node type from topology metadata if available
            node_type = self.topology.nodes[node].get('type', 'Service')

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
            # 1. Guilt Ratio (SOTA Logic)
            # Fixes Hub Bias: A DB called by 100 svcs needs >50 complaints to be guilty.
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

            # 2. Impact Bonus (Log Traffic)
            # Prioritize high-traffic nodes slightly
            b_metrics = baseline_data.get(node, {})
            traffic_metric = b_metrics.get('inbound_rps') if 'inbound_rps' in b_metrics else b_metrics.get('request_rate')
            traffic_vol = np.mean(traffic_metric) if traffic_metric is not None and len(traffic_metric) > 0 else 1.0
            impact_bonus = math.log10(max(1.0, traffic_vol))

            # 3. Temporal Score (NEW)
            temporal_info = temporal_scores.get(node, {})
            temporal_score = temporal_info.get('temporal_score', 0.0)

            # 4. Trace Score (NEW)
            trace_info = trace_scores.get(node, {})
            trace_score = trace_info.get('trace_score', 0.0)
            is_trace_authoritative = trace_info.get('is_authoritative', False)

            # 5. Final Score (Enhanced Formula)
            self_score = self_scores.get(node, 0.0)

            # If traces show authoritative evidence (high self-time),
            # boost self_score to ensure it's not ignored
            if is_trace_authoritative:
                self_score = max(self_score, 8.0)

            # Enhanced Formula: Guilt + Self + Impact + Temporal + Trace
            final_score = (
                (guilt_ratio * 100.0) +        # External evidence (0-100)
                (self_score * 5.0) +           # Internal evidence (0-50)
                impact_bonus +                  # Traffic volume (0-3)
                (temporal_score * 2.0) +       # Temporal causality (0-40)
                (trace_score * 2.0)            # Trace evidence (0-40)
            )

            # REMOVED: Hard threshold (score > 10.0)
            # Now we rank ALL nodes and let top-K filtering happen later
            rankings.append({
                'node': node,
                'score': round(final_score, 2),
                'guilt_ratio': round(guilt_ratio, 2),
                'self_score': round(self_score, 2),
                'temporal_score': round(temporal_score, 2),
                'trace_score': round(trace_score, 2),
                'symptoms': symptoms_map.get(node, []),
                'blamed_by': [v['source'] for v in votes],
                'temporal_info': temporal_info,
                'trace_info': trace_info,
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