"""
whitebox_rca.py

The SOTA Root Cause Analysis Engine (v3.0).
Integrates:
1. Self-Health (Saturation + Deadlock detection)
2. Edge Disambiguation (Traffic vs. Retry patterns)
3. Hub Bias Correction (Guilt Ratio)
4. Causal Narratives
"""

import numpy as np
import networkx as nx
import math
from typing import Dict, List, Any
from collections import defaultdict

# Components
from self_health_analyzer import SelfHealthAnalyzer
from disambiguator import CallerCalleeDisambiguator
from config_extractor import ConfigExtractor
from causal_chain_analyzer import CausalChainAnalyzer

class WhiteboxRCAEngine:
    def __init__(self, topology: nx.DiGraph, config: Dict = None):
        self.topology = topology
        self.config_extractor = ConfigExtractor(config)
        self.self_analyzer = SelfHealthAnalyzer(self.config_extractor)
        self.disambiguator = CallerCalleeDisambiguator()
        self.storyteller = CausalChainAnalyzer(topology)

    def analyze_incident(self, 
                         baseline_data: Dict[str, Dict[str, np.ndarray]], 
                         current_data: Dict[str, Dict[str, np.ndarray]]) -> List[Dict]:
        
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

        # --- PHASE 2: Graph Propagation (External Evidence) ---
        # "Who blames who?"
        incoming_votes = defaultdict(list) # target -> [votes]

        for u, v in self.topology.edges:
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

            # 3. Final Score
            self_score = self_scores.get(node, 0.0)
            
            # Formula: Guilt (External) + Self (Internal) + Impact
            final_score = (guilt_ratio * 100.0) + (self_score * 5.0) + impact_bonus

            if final_score > 10.0:
                rankings.append({
                    'node': node,
                    'score': round(final_score, 2),
                    'guilt_ratio': round(guilt_ratio, 2),
                    'self_score': round(self_score, 2),
                    'symptoms': symptoms_map.get(node, []),
                    'blamed_by': [v['source'] for v in votes],
                    'story': [] # Populated later
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