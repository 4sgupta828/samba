"""
causal_chain_analyzer.py

Builds a narrative explanation of the fault propagation.
Connects the Root Cause (detected by engine) to the Symptoms (user pain).
"""

import networkx as nx
from typing import List, Dict

class CausalChainAnalyzer:
    def __init__(self, topology: nx.DiGraph):
        self.topology = topology

    def generate_story(self, root_cause_node: str, symptoms: List[str], graph_votes: Dict) -> List[str]:
        """
        Traces the impact from root cause downwards to explain the incident.
        """
        story = []
        story.append(f"🔴 ROOT CAUSE: {root_cause_node}")
        story.append(f"   Internal Symptoms: {', '.join(symptoms)}")
        
        # BFS to find impacted downstream nodes
        try:
            layers = list(nx.bfs_layers(self.topology, root_cause_node))
        except nx.NetworkXError:
            return story # Node not in graph or isolated

        if len(layers) > 1:
            # Check immediate downstream
            downstream = layers[1]
            story.append(f"⬇️ Propagation:")
            
            for victim in downstream:
                # Did this victim actually blame the root cause?
                votes = graph_votes.get(victim, [])
                blamed_root = any(v['source'] == victim for v in votes) # Actually reverse logic in graph votes
                
                # Check for impact on victim
                # In a real system, we'd check the victim's metrics here. 
                # For this narrative generator, we assume impact if they voted.
                
                story.append(f"   - {victim} calls {root_cause_node} (Potential cascading latency)")
                
        return story