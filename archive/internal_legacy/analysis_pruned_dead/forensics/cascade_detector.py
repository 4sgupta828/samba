"""
Cascade detection for forensic investigations.

Detects and analyzes failure cascades through the system.
"""

import networkx as nx
from typing import List, Tuple
from .models import CascadeChain, CrashEvent, BottleneckAnalysis, ComponentDegradation


class CascadeDetector:
    """Detects cascade chains of failures."""

    def __init__(
        self,
        topology_graph: nx.DiGraph,
        crashes: List[CrashEvent],
        bottlenecks: List[BottleneckAnalysis],
        component_degradations: List[ComponentDegradation]
    ):
        self.topology_graph = topology_graph
        self.crashes = crashes
        self.bottlenecks = bottlenecks
        self.component_degradations = component_degradations
        self.cascades: List[CascadeChain] = []

    def detect_cascades(self) -> List[CascadeChain]:
        """Detect cascade chains of failures."""
        # Build timeline of all significant events
        events = []

        for crash in self.crashes:
            events.append({
                'time': crash.crash_time,
                'component': crash.component_id,
                'type': 'crash',
                'severity': 10
            })

        for bottleneck in self.bottlenecks:
            events.append({
                'time': bottleneck.start_time,
                'component': bottleneck.component_id,
                'type': 'bottleneck',
                'severity': 5 if bottleneck.severity == 'critical' else 3
            })

        events.sort(key=lambda x: x['time'])

        # Detect cascades
        cascade_id = 0
        visited = set()

        for i, event in enumerate(events):
            if event['component'] in visited:
                continue

            chain = [(event['component'], event['time'], event['type'])]
            visited.add(event['component'])

            # Find downstream events
            for j in range(i + 1, len(events)):
                next_event = events[j]

                if next_event['time'] - event['time'] > 30:
                    break

                if self._has_dependency(event['component'], next_event['component']):
                    chain.append((next_event['component'], next_event['time'], next_event['type']))
                    visited.add(next_event['component'])

            if len(chain) > 1:
                cascade_id += 1
                cascade_duration = chain[-1][1] - chain[0][1]
                cascade_type = self._determine_cascade_type(chain)

                cascade = CascadeChain(
                    cascade_id=cascade_id,
                    root_component=chain[0][0],
                    chain=chain,
                    total_components_affected=len(chain),
                    cascade_duration=cascade_duration,
                    cascade_type=cascade_type,
                    layers=[],
                    impact_summary=""
                )

                self.cascades.append(cascade)

        # Enhance cascades with layers and degradation
        self._enhance_cascades()

        return self.cascades

    def _has_dependency(self, source: str, target: str) -> bool:
        """Check if target depends on source in topology."""
        try:
            return nx.has_path(self.topology_graph, source, target)
        except:
            return False

    def _determine_cascade_type(self, chain: List[Tuple]) -> str:
        """Determine the type of cascade."""
        types = [event[2] for event in chain]

        if 'crash' in types:
            return 'resource_exhaustion'
        elif 'bottleneck' in types:
            return 'latency'
        else:
            return 'error'

    def _enhance_cascades(self):
        """Enhance cascades with degradation % and layer visualization."""
        for cascade in self.cascades:
            # Build layers using BFS from root
            layers = []
            visited = {cascade.root_component}
            current_layer = [cascade.root_component]

            while current_layer:
                layers.append(current_layer[:])
                next_layer = []

                for node in current_layer:
                    for successor in self.topology_graph.successors(node):
                        if successor not in visited:
                            if any(comp[0] == successor for comp in cascade.chain):
                                visited.add(successor)
                                next_layer.append(successor)

                current_layer = next_layer

            cascade.layers = layers

            # Add degradation % to chain entries
            enhanced_chain = []
            for comp_id, time, mechanism, *rest in cascade.chain:
                deg_pct = 0
                for deg in self.component_degradations:
                    if deg.component_id == comp_id:
                        deg_pct = deg.degradation_pct
                        break

                enhanced_chain.append((comp_id, time, mechanism, deg_pct))

            cascade.chain = enhanced_chain

            # Generate impact summary
            if len(layers) > 1:
                cascade.impact_summary = f"Cascade: {layers[0][0]} → {len(layers[1]) if len(layers) > 1 else 0} direct → {len(layers[2]) if len(layers) > 2 else 0} indirect"
            else:
                cascade.impact_summary = "Single component failure"
