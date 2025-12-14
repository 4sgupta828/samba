"""
whitebox_rca.py

The SOTA Root Cause Analysis Engine (v2.0).
Usage: python whitebox_rca.py
"""

import numpy as np
import networkx as nx
import math
from typing import Dict, List, Any

# Import our modular components
from statistical_utils import compare_distributions
from self_health_analyzer import SelfHealthAnalyzer
from disambiguator import CallerCalleeDisambiguator

class WhiteboxRCAEngine:
    def __init__(self, topology: nx.DiGraph):
        self.topology = topology
        self.self_analyzer = SelfHealthAnalyzer()
        self.disambiguator = CallerCalleeDisambiguator()

    def analyze_incident(self, 
                         baseline_data: Dict[str, Dict[str, np.ndarray]], 
                         current_data: Dict[str, Dict[str, np.ndarray]]) -> List[Dict]:
        """
        Main entry point.
        :param baseline_data: Dict {node_id: {metric_name: np.array}}
        :param current_data: Dict {node_id: {metric_name: np.array}}
        """
        
        # --- PHASE 1: Self-Health Analysis (Internal Evidence) ---
        self_scores = {}
        symptoms_map = {}
        
        for node in self.topology.nodes:
            # Handle missing data gracefully
            b_metrics = baseline_data.get(node, {})
            c_metrics = current_data.get(node, {})
            
            analysis = self.self_analyzer.analyze(node, b_metrics, c_metrics)
            self_scores[node] = analysis.self_degradation_score
            symptoms_map[node] = analysis.symptoms

        # --- PHASE 2: Graph Propagation (External Evidence) ---
        # We collect "votes" of blame.
        # Vote Structure: (target_node, weight, reason)
        incoming_votes = {n: [] for n in self.topology.nodes}

        for u, v in self.topology.edges:
            # u calls v. Analyze the edge.
            verdict = self.disambiguator.analyze_edge(
                caller_metrics_base=baseline_data.get(u, {}),
                caller_metrics_curr=current_data.get(u, {}),
                callee_metrics_base=baseline_data.get(v, {}),
                callee_metrics_curr=current_data.get(v, {})
            )

            if verdict.blames_callee:
                # Caller (u) blames Callee (v)
                incoming_votes[v].append({'source': u, 'weight': 1.0, 'reason': verdict.reason})
            
            elif verdict.blames_caller:
                # Callee (v) implies Caller (u) is attacking
                incoming_votes[u].append({'source': v, 'weight': 0.5, 'reason': verdict.reason})

        # --- PHASE 3: Global Ranking (Fixing Hub Bias) ---
        rankings = []

        for node in self.topology.nodes:
            # 1. Calculate Guilt Ratio (Probability)
            # Fixes Hub Bias: A node called by 100 svcs needs >50 complaints to be guilty.
            # A node called by 1 svc only needs 1 complaint.
            
            callers = list(self.topology.predecessors(node))
            votes = incoming_votes[node]
            vote_sum = sum(v['weight'] for v in votes)
            
            if len(callers) > 0:
                guilt_ratio = vote_sum / len(callers)
                # Dampen ratio for small N (Law of large numbers)
                if len(callers) < 5: 
                    guilt_ratio *= 0.8
            else:
                guilt_ratio = 0.0

            # 2. Calculate Final RCA Score
            # Score = (GuiltRatio * 100) + (SelfHealthScore * 2) + ImpactBonus
            
            self_score = self_scores.get(node, 0.0)
            
            # Impact Bonus: Log(Traffic) - prioritizes high traffic nodes slightly
            # (Mocking traffic volume here, normally strictly from metrics)

            # FIX: Fetch actual traffic from baseline to determine service importance
            # We use baseline because if the service is dead (0 RPS currently), 
            # we still want to know it *should* be handling traffic.
            b_metrics = baseline_data.get(node, {})
            
            # Try to find a throughput metric (adapt key to your specific mapping)
            traffic_metric = b_metrics.get('inbound_rps') or b_metrics.get('request_rate')
            
            if traffic_metric is not None and len(traffic_metric) > 0:
                # Use average baseline traffic
                traffic_vol = np.mean(traffic_metric)
            else:
                traffic_vol = 1.0 # Fallback to avoid log(0) errors

            # Log scale: 10 RPS -> 1 pt, 100k RPS -> 5 pts
            impact_bonus = math.log10(max(1.0, traffic_vol))

            final_score = (guilt_ratio * 100.0) + (self_score * 2.0) + impact_bonus

            if final_score > 5.0: # Filter out noise
                rankings.append({
                    'node': node,
                    'score': round(final_score, 2),
                    'guilt_ratio': round(guilt_ratio, 2),
                    'self_score': round(self_score, 2),
                    'symptoms': symptoms_map.get(node, []),
                    'blamed_by': [v['source'] for v in votes]
                })

        # Sort descending
        return sorted(rankings, key=lambda x: x['score'], reverse=True)

# ==========================================
# DEMO / TEST RUNNER
# ==========================================
if __name__ == "__main__":
    print("Running Whitebox RCA 2.0 Demo...\n")

    # 1. Create Mock Topology (Frontend -> Backend -> DB)
    G = nx.DiGraph()
    G.add_edge("frontend", "backend")
    G.add_edge("backend", "database")

    # 2. Generate Mock Data (Scenario: Database CPU Saturation)
    # Database: High CPU, slow response.
    # Backend: High Latency to DB, high queue.
    # Frontend: High Latency to Backend.

    def noise(n, mean=10, std=1):
        return np.random.normal(mean, std, n)

    baseline = {
        "database": {
            "cpu_usage": noise(50, 20, 2),
            "avg_latency": noise(50, 5, 1)
        },
        "backend": {
            "dependency_latency": noise(50, 5, 1), # Calls to DB
            "outbound_rps": noise(50, 100, 5)
        },
        "frontend": {
            "dependency_latency": noise(50, 20, 2), # Calls to Backend
            "outbound_rps": noise(50, 100, 5)
        }
    }

    current = {
        "database": {
            "cpu_usage": noise(50, 95, 2), # <--- ROOT CAUSE: CPU Saturation
            "avg_latency": noise(50, 200, 20) # Slow internal processing
        },
        "backend": {
            "dependency_latency": noise(50, 200, 20), # Sees DB as slow
            "outbound_rps": noise(50, 100, 5) # Traffic normal (not DDoS)
        },
        "frontend": {
            "dependency_latency": noise(50, 220, 20), # Sees Backend as slow
            "outbound_rps": noise(50, 100, 5)
        }
    }

    # 3. Run Analysis
    engine = WhiteboxRCAEngine(G)
    results = engine.analyze_incident(baseline, current)

    # 4. Print Results
    print(f"{'RANK':<5} {'NODE':<15} {'SCORE':<10} {'REASON'}")
    print("-" * 60)
    for i, res in enumerate(results):
        print(f"#{i+1:<4} {res['node']:<15} {res['score']:<10} Self-Score: {res['self_score']}")
        for sym in res['symptoms']:
            print(f"      - {sym}")
        if res['blamed_by']:
            print(f"      - Blamed by: {res['blamed_by']}")
        print("")