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

        # Find downstream nodes that have dependency edges (not infrastructure edges)
        downstream = []
        for successor in self.topology.successors(root_cause_node):
            # Filter out non-dependency edges (pod_pool, pod_placement, node_placement)
            edge_data = self.topology.edges[root_cause_node, successor]
            edge_type = edge_data.get('type', 'sync_http')

            # Only include dependency edges (calls/requests)
            if edge_type not in ['pod_pool', 'pod_placement', 'node_placement']:
                downstream.append(successor)

        if downstream:
            story.append(f"⬇️ Propagation:")

            for victim in downstream:
                # Check edge type for better description
                edge_data = self.topology.edges[root_cause_node, victim]
                edge_type = edge_data.get('type', 'sync_http')

                # Generate appropriate message based on edge type
                if edge_type in ['sync_http', 'sync_grpc']:
                    story.append(f"   - {victim} calls {root_cause_node} (Potential cascading latency)")
                elif edge_type == 'sync_db':
                    story.append(f"   - {victim} queries {root_cause_node} (Potential query slowdown)")
                elif edge_type == 'sync_cache':
                    story.append(f"   - {victim} accesses {root_cause_node} (Potential cache delays)")
                elif edge_type == 'sync_external':
                    story.append(f"   - {victim} calls {root_cause_node} (External service dependency)")
                elif edge_type == 'async_produce':
                    story.append(f"   - {victim} publishes to {root_cause_node} (Queue backpressure)")
                elif edge_type == 'async_consume':
                    story.append(f"   - {victim} consumes from {root_cause_node} (Processing delays)")
                else:
                    story.append(f"   - {victim} depends on {root_cause_node} (Potential impact)")

        return story