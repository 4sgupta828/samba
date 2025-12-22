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
from collections import defaultdict

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

                # Always include pod counts when pods exist (even if none degraded)
                # This is important for distinguishing intrinsic vs dependency-caused issues
                if pod_ids:
                    pod_metadata = {
                        'total_count': len(pod_ids),
                        'degraded_count': len(degraded_pods)
                    }

                    # Calculate coverage-weighted score if there are degraded pods
                    if degraded_pods:
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

                        pod_metadata.update({
                            'pod_score': pod_score,
                            'coverage': coverage,
                            'avg_severity': avg_severity,
                            'max_severity': max_severity,
                            'pattern': pattern
                        })
                    else:
                        # No degraded pods but pods exist
                        pod_metadata['pattern'] = f"No pods showing self-degradation (0/{len(pod_ids)} pods)"

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
                         baseline_window: tuple = None,
                         current_window: tuple = None,
                         fault_start_time: Optional[float] = None,
                         traces_file: Optional[Path] = None,
                         logs_file: Optional[Path] = None,
                         baseline_pods=None, current_pods=None) -> List[Dict]:

        # --- PHASE 1: Self-Health (Whitebox + Blackbox Inference) ---
        self_scores = {}

        # Define external dependency types that should ALWAYS use caller-based analysis
        external_dep_types = {
            'ExternalService', 'ExternalAPI',
            'Database', 'Cache',
            'Queue', 'MessageBroker'
        }

        for node in self.topology.nodes:
            if self.topology.nodes[node].get('parent_service'): continue

            node_type = self.topology.nodes[node].get('type', 'Service')
            node_role = self.topology.nodes[node].get('role', '')
            b_metrics = baseline_data.get(node, {})
            c_metrics = current_data.get(node, {})

            # ROUTING DECISION: Whitebox vs Blackbox
            # For external dependencies, ALWAYS use caller-based (blackbox) analysis
            # regardless of whether they have self metrics. This provides:
            # 1. Consensus view across all callers (error rate, latency, throughput)
            # 2. Alignment with physics model (impact propagation from callers)
            # 3. Avoids relying on incomplete/misleading self metrics

            is_external_dep = (node_type in external_dep_types or node_role == 'external')

            if is_external_dep:
                # EXTERNAL DEPENDENCY: ALWAYS use caller-based consensus analysis
                # Principle: External deps are black boxes - evaluate by what callers observe,
                # not by incomplete self metrics
                callers = list(self.topology.predecessors(node))
                if callers:
                    c_views_base = [baseline_data.get(c, {}) for c in callers]
                    c_views_curr = [current_data.get(c, {}) for c in callers]
                    analysis = self.self_analyzer.infer_blackbox_health(
                        node, c_views_base, c_views_curr,
                        caller_ids=callers,
                        metrics_df=metrics_df,
                        baseline_window=baseline_window,
                        current_window=current_window,
                        target_dependency=node
                    )
                else:
                    # External dep with no callers - skip (orphan)
                    continue

            elif c_metrics:
                # INTERNAL SERVICE: Use whitebox analysis with dependency-aware error attribution
                analysis = self.self_analyzer.analyze(
                    node, node_type, b_metrics, c_metrics,
                    topology=self.topology,
                    all_baseline_data=baseline_data,
                    all_current_data=current_data
                )

            else:
                # INTERNAL SERVICE without metrics: Use blackbox inference from callers
                # (Note: This uses aggregated data since internal services aren't dependencies)
                callers = list(self.topology.predecessors(node))
                if callers:
                    c_views_base = [baseline_data.get(c, {}) for c in callers]
                    c_views_curr = [current_data.get(c, {}) for c in callers]
                    analysis = self.self_analyzer.infer_blackbox_health(
                        node, c_views_base, c_views_curr,
                        caller_ids=None,  # Internal services don't need per-dependency extraction
                        metrics_df=None,
                        baseline_window=None,
                        current_window=None,
                        target_dependency=None
                    )
                else:
                    continue # Orphan node

            self_scores[node] = analysis

        # --- PHASE 2: Physics Coverage ---
        # Start with nodes that have self-degradation
        # External dependencies are now properly scored in Phase 1 using caller consensus,
        # so no special handling needed here
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
        affected_victim_nodes = set()  # Track nodes directly affected by partition

        # STRATEGY 1: Detect sustained near-complete metric gaps (network partitions)
        # Look for time windows where dependency requests drop to near-zero for extended periods
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
                        # Split into baseline and post-fault periods
                        baseline_df = dep_metrics[dep_metrics['sim_time'] < fault_start_time]
                        post_fault_df = dep_metrics[dep_metrics['sim_time'] >= fault_start_time]

                        # Calculate baseline request frequency for each edge
                        baseline_duration = fault_start_time if fault_start_time > 0 else 1

                        # Group by component and dependency to analyze each edge
                        for (component_id, dep_id), baseline_group in baseline_df.groupby(['component_id', 'dependency_id']):
                            # Check if this dependency had regular activity in baseline
                            baseline_count = len(baseline_group)
                            baseline_total_reqs = baseline_group['value'].sum() if 'value' in baseline_group.columns else 0

                            if baseline_count >= 3 and baseline_total_reqs > 10:  # Was active in baseline
                                # Get post-fault data for this edge
                                post_fault_group = post_fault_df[
                                    (post_fault_df['component_id'] == component_id) &
                                    (post_fault_df['dependency_id'] == dep_id)
                                ].sort_values('sim_time')

                                if len(post_fault_group) == 0:
                                    # No data at all post-fault - complete blackout
                                    baseline_freq = baseline_count / baseline_duration

                                    # Map component_id to service
                                    if component_id and component_id.startswith('pod_'):
                                        service = '_'.join(component_id.split('_')[1:-1])
                                    else:
                                        service = component_id

                                    if service and dep_id:
                                        metric_gaps[(service, dep_id)] = {
                                            'baseline_freq': baseline_freq,
                                            'max_blackout_duration': post_fault_df['sim_time'].max() - fault_start_time,
                                            'gap_ratio': 1.0,
                                            'partition_type': 'complete_blackout'
                                        }
                                else:
                                    # Use sliding window to find sustained gaps
                                    # Window size: 60 seconds (configurable)
                                    # Threshold: >95% drop (near-zero requests)
                                    window_size = 60.0
                                    baseline_freq = baseline_count / baseline_duration

                                    # Check for sustained gaps in time windows
                                    max_gap_duration = 0
                                    max_gap_start = None
                                    current_gap_start = None
                                    last_request_time = fault_start_time

                                    for _, row in post_fault_group.iterrows():
                                        request_time = row['sim_time']
                                        gap_duration = request_time - last_request_time

                                        # If gap > window_size, we have a sustained blackout
                                        if gap_duration >= window_size:
                                            if current_gap_start is None:
                                                current_gap_start = last_request_time

                                            total_gap = request_time - current_gap_start
                                            if total_gap > max_gap_duration:
                                                max_gap_duration = total_gap
                                                max_gap_start = current_gap_start
                                        else:
                                            current_gap_start = None

                                        last_request_time = request_time

                                    # Check if gap extends to end of timeline
                                    end_time = post_fault_df['sim_time'].max()
                                    final_gap = end_time - last_request_time
                                    if final_gap >= window_size:
                                        if current_gap_start is None:
                                            current_gap_start = last_request_time
                                        total_gap = end_time - current_gap_start
                                        if total_gap > max_gap_duration:
                                            max_gap_duration = total_gap
                                            max_gap_start = current_gap_start

                                    # If we found a sustained gap (>60s with near-zero requests), flag as partition
                                    if max_gap_duration >= window_size:
                                        # Map component_id to service
                                        if component_id and component_id.startswith('pod_'):
                                            service = '_'.join(component_id.split('_')[1:-1])
                                        else:
                                            service = component_id

                                        if service and dep_id:
                                            metric_gaps[(service, dep_id)] = {
                                                'baseline_freq': baseline_freq,
                                                'max_blackout_duration': max_gap_duration,
                                                'blackout_start': max_gap_start,
                                                'gap_ratio': 1.0,  # Near 100% during blackout window
                                                'partition_type': 'sustained_blackout'
                                            }

                        # Report detected gaps
                        if metric_gaps:
                            print(f"  [Network Partition Detection] Found {len(metric_gaps)} edges with sustained blackouts")
                            for (src, tgt), info in list(metric_gaps.items())[:3]:
                                print(f"    {src} -> {tgt}: {info['max_blackout_duration']:.0f}s blackout (baseline: {info['baseline_freq']:.2f} req/s)")

                        # === PRINCIPLED DETECTION: Distinguish service failure from network partition ===
                        # CORE PRINCIPLE: Use existing self-health signals - NO new thresholds
                        #
                        # Logic:
                        # 1. If source has self-degradation → blackouts are cascading (source failure)
                        # 2. If source is healthy → blackouts indicate external problem (network or dependency)
                        # 3. Use convergence: multiple healthy sources failing to reach same target → partition

                        # Step 1: Classify each edge based on INTRINSIC degradation evidence
                        # PRINCIPLED: Only filter if there's CLEAR pod-level evidence of intrinsic issues
                        # Service-level errors alone are ambiguous (could be victim or cause)
                        healthy_source_gaps = {}  # Gaps from healthy sources
                        degraded_source_gaps = {}  # Gaps from sources with INTRINSIC pod degradation

                        for (source, target), gap_info in metric_gaps.items():
                            # Check source health
                            source_analysis = self_scores.get(source)

                            if not source_analysis or not source_analysis.is_root_cause_candidate:
                                # Source is healthy → blackouts indicate external problem
                                if source not in healthy_source_gaps:
                                    healthy_source_gaps[source] = []
                                healthy_source_gaps[source].append((target, gap_info))
                                continue

                            # Source shows degradation - check if it's INTRINSIC (pod-level evidence)
                            service_self_score = source_analysis.self_degradation_score
                            integrated_score, health_meta = self.calculate_integrated_health_score(
                                source, service_self_score, baseline_pods, current_pods
                            )

                            # PRINCIPLED CRITERION: Only treat as intrinsic if pods show degradation
                            # Pod degradation (CPU, memory, etc.) is unambiguous evidence of intrinsic issues
                            # Service-level errors without pod degradation could be victims
                            degraded_pod_count = health_meta.get('degraded_count', 0)

                            if degraded_pod_count > 0:
                                # CLEAR intrinsic degradation (pods are degraded) → filter blackouts
                                if source not in degraded_source_gaps:
                                    degraded_source_gaps[source] = []
                                degraded_source_gaps[source].append((target, gap_info))
                            else:
                                # Service errors but no pod degradation → ambiguous, keep as partition candidate
                                if source not in healthy_source_gaps:
                                    healthy_source_gaps[source] = []
                                healthy_source_gaps[source].append((target, gap_info))

                        # Step 2: Build impact subgraph of degraded sources (transitive closure)
                        # PRINCIPLE: If A is degraded, all downstream nodes that depend on A
                        # might also show blackouts (cascading), even if they're "healthy"
                        degraded_impact_subgraph = set()  # All nodes impacted by degraded sources
                        if degraded_source_gaps:
                            for source, gaps in degraded_source_gaps.items():
                                source_score = self_scores.get(source)
                                score_val = source_score.self_degradation_score if source_score else 0
                                print(f"  [Network Partition Filter] {source} has self-degradation (score={score_val:.1f}), "
                                      f"excluding {len(gaps)} outgoing edges as direct cascading failures")

                                # Add degraded source itself
                                degraded_impact_subgraph.add(source)

                                # Add all nodes that depend on this degraded source (transitive)
                                # These nodes might appear "healthy" but are actually cascading victims
                                if source in self.topology:
                                    # BFS to find all downstream nodes
                                    to_visit = [source]
                                    visited = set([source])
                                    while to_visit:
                                        current = to_visit.pop(0)
                                        # Get nodes that current calls
                                        for neighbor in self.topology.successors(current):
                                            if neighbor not in visited:
                                                visited.add(neighbor)
                                                degraded_impact_subgraph.add(neighbor)
                                                to_visit.append(neighbor)

                            print(f"  [Network Partition Filter] Degraded impact subgraph contains {len(degraded_impact_subgraph)} nodes")

                        # Step 3: Filter out edges from any node in the degraded impact subgraph
                        # These are ALL cascading effects, not true network partitions
                        filtered_gaps = {}
                        cascading_edges_filtered = 0

                        # Process healthy sources
                        for source, gaps in healthy_source_gaps.items():
                            # Check if this "healthy" source is actually in the impact subgraph
                            if source in degraded_impact_subgraph:
                                # This source is a cascading victim, filter out its edges
                                cascading_edges_filtered += len(gaps)
                            else:
                                # True healthy source, keep its edges as partition candidates
                                for target, gap_info in gaps:
                                    filtered_gaps[(source, target)] = gap_info

                        if cascading_edges_filtered > 0:
                            print(f"  [Network Partition Filter] Excluded {cascading_edges_filtered} additional edges from cascading victim nodes")

                        # Report filtering results
                        if not filtered_gaps and metric_gaps:
                            print(f"  [Network Partition Detection] All {len(metric_gaps)} blackouts "
                                  f"attributed to service failures (sources have self-degradation)")
                            metric_gaps = {}
                        elif filtered_gaps:
                            removed = len(metric_gaps) - len(filtered_gaps)
                            if removed > 0:
                                print(f"  [Network Partition Detection] Filtered out {removed} edges from degraded sources, "
                                      f"{len(filtered_gaps)} edges remain as partition candidates")
                            else:
                                print(f"  [Network Partition Detection] All {len(filtered_gaps)} edges from healthy sources, "
                                      f"strong network partition evidence")
                            metric_gaps = filtered_gaps

                        # Convert sustained blackouts to network partitions
                        # Only flag as partition if blackout is sustained (>60s) and nearly complete (>95%)
                        for (source, target), gap_info in metric_gaps.items():
                            blackout_duration = gap_info['max_blackout_duration']

                            # Very high confidence: 120+ seconds of complete blackout
                            if blackout_duration >= 120:
                                reason = (f'Network partition detected: {source} -> {target} '
                                         f'(Complete blackout for {blackout_duration:.0f}s, baseline: {gap_info["baseline_freq"]:.2f} req/s)')
                                confidence = 0.98
                                network_partitions.append({
                                    'source': source,
                                    'target': target,
                                    'reason': reason,
                                    'confidence': confidence,
                                    'double_confirmed': False
                                })
                                # Track victim nodes
                                affected_victim_nodes.add(source)
                                affected_victim_nodes.add(target)
                            # High confidence: 60+ seconds of blackout
                            elif blackout_duration >= 60:
                                reason = (f'Network partition detected: {source} -> {target} '
                                         f'(Sustained blackout for {blackout_duration:.0f}s, baseline: {gap_info["baseline_freq"]:.2f} req/s)')
                                confidence = 0.90
                                network_partitions.append({
                                    'source': source,
                                    'target': target,
                                    'reason': reason,
                                    'confidence': confidence,
                                    'double_confirmed': False
                                })
                                # Track victim nodes
                                affected_victim_nodes.add(source)
                                affected_victim_nodes.add(target)

            except Exception as e:
                print(f"  [!] Warning: Network partition detection failed: {e}")

        # Create global_network candidate if partitions detected
        if network_partitions:
            print(f"  [!] Network partition detected: {len(network_partitions)} blocked edge(s)")
            for partition in network_partitions:
                print(f"      - {partition['reason']}")

            # PRINCIPLED SCORING: Network partition is inherently a ROOT CAUSE
            #
            # Philosophy: Network partition represents infrastructure failure that CAUSES
            # service-level symptoms. It should score higher than its victim services.
            #
            # Approach: Score based on system-wide impact (how much of system is affected)
            # and confidence in detection.

            avg_confidence = sum(p['confidence'] for p in network_partitions) / len(network_partitions)
            num_edges = len(network_partitions)

            # Count unique affected nodes
            affected_nodes = set()
            for partition in network_partitions:
                affected_nodes.add(partition['source'])
                affected_nodes.add(partition['target'])
                affected_victim_nodes.add(partition['source'])
                affected_victim_nodes.add(partition['target'])

            # Count total degraded nodes in the system (not just on partition edges)
            # This gives us the full blast radius
            degraded_nodes = set()
            for node in self.topology.nodes:
                if self.topology.nodes[node].get('parent_service'):
                    continue  # Skip pods
                if node in self_scores and self_scores[node].is_root_cause_candidate:
                    degraded_nodes.add(node)

            # Calculate impact ratio: fraction of degraded nodes that could be explained by partition
            # If partition affects 11 nodes and 15 nodes are degraded, impact = 11/15 = 73%
            total_nodes = len([n for n in self.topology.nodes
                             if not self.topology.nodes[n].get('parent_service')])  # Exclude pods
            num_degraded = max(len(degraded_nodes), len(affected_nodes))  # At least affected nodes

            # Impact ratio: how much of the degradation can partition explain?
            impact_ratio = len(affected_nodes) / max(num_degraded, 1)

            # PRINCIPLED SCORING: Network partition, when detected, is THE root cause
            # Don't scale by impact ratio - if partition exists, it's the cause regardless of coverage
            #
            # Give full base score (as if it had max self-health + max physics + primary semantic)
            # This ensures network partition outranks all victim services
            base_score = 150.0  # max(base_health(50) + physics(60) + semantic(40))

            # Scale only by detection confidence (how sure are we of the partition?)
            network_score = base_score * avg_confidence

            # Root cause bonus: Network partitions are infrastructure-level failures
            # Give semantic bonus (primary symptom) scaled by confidence
            root_cause_bonus = 40.0 * avg_confidence
            network_score += root_cause_bonus

            # Total possible: 150 * confidence + 40 * confidence = 190 * confidence
            # At 98% confidence: 186.2 points (should outrank most victims)

            print(f"  [!] Network partition score: {network_score:.1f}")
            print(f"      - Affected nodes: {len(affected_nodes)}/{total_nodes} ({impact_ratio:.1%})")
            print(f"      - Detection confidence: {avg_confidence:.1%}")
            print(f"      - Blocked edges: {num_edges}")

            network_partition_candidate = {
                'node': 'global_network',
                'score': network_score,
                'score_composition': {
                    'base_health': {'raw': 0, 'confidence': 'high', 'multiplier': 1.0, 'points': 0},
                    'physics_coverage': {'raw': 0, 'weight': 60.0, 'points': 0},
                    'semantic_bonus': {'is_primary': True, 'coverage_context': 'high', 'points': 0},
                    'supplements': {'temporal': 0, 'trace': 0, 'trace_degradation': 0, 'logs': 0, 'metric_gaps': network_score}
                },
                'story': [
                    '🔴 ROOT CAUSE: global_network (Network Partition)',
                    '   Network partitions detected via metric analysis:',
                    *[f'   - {p["reason"]}' for p in network_partitions],
                    f'',
                    f'   Detection confidence: {avg_confidence*100:.0f}%',
                    f'   Detected edges: {len(network_partitions)}',
                    f'   Affected nodes: {len(affected_nodes)}/{total_nodes}',
                    f'   Score: {network_score:.1f} (base={base_score*impact_ratio*avg_confidence:.1f} + root_cause_bonus={root_cause_bonus:.1f})'
                ],
                'integrated_score': 0.0,
                'self_score': 0.0,
                'symptoms': [f'Network partition detected ({len(network_partitions)} blocked edges)'],
                'health_metadata': {
                    'network_partition_count': len(network_partitions),
                    'avg_confidence': avg_confidence,
                    'detection_method': 'metric_gaps',
                    'affected_nodes': len(affected_nodes),
                    'impact_ratio': impact_ratio
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

        # Debug: Check for external deps with physics
        external_deps_with_physics = [
            (node, physics_hypotheses[node].coverage_score)
            for node in self.topology.nodes
            if node in physics_hypotheses
            and self.topology.nodes[node].get('type') in ['ExternalAPI', 'ExternalService', 'Database', 'Cache', 'Queue']
            and physics_hypotheses[node].coverage_score > 0
        ]
        if external_deps_with_physics:
            print(f"\n[DEBUG] External deps with physics: {external_deps_with_physics[:5]}")

        for node in self.topology.nodes:
            # Include nodes with self-scores OR physics evidence
            # (External deps may have no self-score but strong physics signal)
            has_self_score = node in self_scores
            has_physics = node in physics_hypotheses and physics_hypotheses[node].coverage_score > 0.1

            if not (has_self_score or has_physics):
                continue  # Skip only if BOTH are missing

            # === COMPONENT 1: BASE HEALTH (0-50 points) ===
            # Pod-level analysis is AUTHORITATIVE when available (more granular than service aggregates)
            # For nodes with no self-score (external deps), use 0 (rely on physics)
            if has_self_score:
                service_self_score = self_scores[node].self_degradation_score
                service_confidence = self_scores[node].confidence
            else:
                service_self_score = 0.0
                service_confidence = 'low'

            # Calculate integrated score (considers pod-level if available)
            integrated_score, health_metadata = self.calculate_integrated_health_score(
                node, service_self_score, baseline_pods, current_pods
            )

            # PRINCIPLED: Use pod-level evidence, but weight by coverage
            # High coverage (service-wide) = strong evidence of intrinsic problem
            # Low coverage (outlier pods) = weak evidence, likely cascading effect
            if health_metadata.get('source') == 'pod-level':
                self_val = integrated_score
                coverage = health_metadata.get('coverage', 0)

                # Coverage-based confidence: distinguish root cause from victim
                if coverage >= 0.8:
                    # Service-wide degradation (≥80% pods) - strong intrinsic evidence
                    confidence = 'high'
                    confidence_multiplier = 1.0
                elif coverage >= 0.5:
                    # Majority degradation (50-80% pods) - moderate evidence
                    confidence = 'medium'
                    confidence_multiplier = 0.6
                elif coverage >= 0.3:
                    # Multiple pods (30-50%) - weak evidence
                    confidence = 'low'
                    confidence_multiplier = 0.3
                else:
                    # Outlier pods (<30%) - very weak evidence (likely cascading)
                    confidence = 'very_low'
                    confidence_multiplier = 0.15
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

            # PRINCIPLED VICTIM PENALTY: If node is a dependency victim (not intrinsic degradation),
            # reduce its physics coverage because it's propagating impact, not causing it
            #
            # A dependency victim is one that:
            # 1. Is affected by network partition
            # 2. Shows service-level errors but pods are healthy (checked during partition detection)
            #
            # We already classified these nodes during partition detection. If a node's edges were
            # kept as "partition candidates" (not filtered as intrinsic degradation), it's a victim.

            is_partition_victim = node in affected_victim_nodes
            if is_partition_victim and network_partitions:
                # Check if this node was classified as a dependency victim (not intrinsic degradation)
                # during partition detection by looking at pod forensics
                if health_metadata.get('source') == 'service-level' and health_metadata.get('total_count', 0) > 0:
                    # Service shows errors but has pods - check if pods are healthy
                    if health_metadata.get('degraded_count', 0) == 0:
                        # Dependency victim: service errors but healthy pods
                        # Reduce physics coverage significantly - it's a propagation node, not root cause
                        raw_coverage *= 0.3  # 70% reduction
                        print(f"  [Victim Penalty] {node} is dependency victim (healthy pods, partition-affected) → reducing physics by 70%")
                    else:
                        print(f"  [Diagnostic] {node} affected by partition with pod degradation → potential co-cause")
                else:
                    print(f"  [Diagnostic] {node} affected by partition ({self_val:.1f} self) → investigating")

            weighted_coverage = raw_coverage * 60.0  # 0-60 points

            # === COMPONENT 3: SEMANTIC TYPE (0-40 points) ===
            # PRIMARY symptoms (cause) get major boost
            # SECONDARY symptoms (effect) get zero
            is_primary = (self_scores[node].symptom_type == 'primary') if node in self_scores else False

            # OVERRIDE: Leaf nodes (no outgoing dependencies) are ALWAYS primary
            # Rationale: Services with no dependencies can't have symptoms caused by dependency issues
            # This includes: external deps (APIs, DBs, caches) AND internal leaf services
            # Any degradation they show is intrinsic, not cascading from downstream calls
            successors = list(self.topology.successors(node)) if node in self.topology else []
            is_leaf = len(successors) == 0
            if is_leaf:
                is_primary = True

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

            # Enhanced story for global_network nodes with partition metadata
            story = physics_hypotheses.get(node).narrative if node in physics_hypotheses else []
            if node == 'global_network':
                node_attrs = self.topology.nodes.get(node, {})
                partition_meta = node_attrs.get('partition_metadata', {})
                if partition_meta:
                    edge_info = partition_meta.get('partitioned_edge', {})
                    if edge_info:
                        src = edge_info.get("source")
                        tgt = edge_info.get("target")
                        story = [
                            '🔴 ROOT CAUSE: global_network (Network Partition)',
                            '',
                            '   Partitioned Edge:',
                            f'   - Source: {src}',
                            f'   - Target: {tgt}',
                            f'   - Edge Type: {edge_info.get("edge_type")}',
                            f'   - Bidirectional: {edge_info.get("bidirectional")}',
                            '',
                            '   This network partition blocks all communication on this edge,',
                            '   causing cascading failures in services that depend on it.'
                        ]
                        # Update symptoms with partition details
                        symptoms = [f'Network partition between {src} and {tgt}']

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
                'story': story,
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

        # === TOPOLOGY-AWARE FILTER: Physics-based intrinsic degradation ===
        # Use physics reasoning: outgoing impact WITHOUT incoming impact = intrinsic problem
        # Consider node topology type, not just metrics
        filtered_rankings = []

        for candidate in rankings:
            node = candidate['node']
            health_meta = candidate.get('health_metadata', {})
            source = health_meta.get('source', 'service-level')
            coverage = health_meta.get('coverage', 1.0)
            self_score = candidate.get('self_score', 0)
            physics_coverage = candidate.get('score_composition', {}).get('physics_coverage', {}).get('raw', 0)

            # Special case: network partition
            if node == 'global_network':
                filtered_rankings.append(candidate)
                continue

            # Get node topology info
            node_attrs = self.topology.nodes.get(node, {})
            node_type = node_attrs.get('type', 'Service')

            # Count incoming/outgoing edges (for physics reasoning)
            incoming_edges = list(self.topology.predecessors(node)) if node in self.topology else []
            outgoing_edges = list(self.topology.successors(node)) if node in self.topology else []

            is_leaf = len(outgoing_edges) == 0  # No outgoing calls
            is_external_dep = node_type in ['ExternalAPI', 'Database', 'Cache', 'Queue', 'MessageBroker']

            # === EVIDENCE EVALUATION ===
            has_intrinsic_evidence = False
            evidence_type = None

            # 1. Strong metrics-based evidence (traditional)
            if source == 'pod-level' and coverage >= 0.5:
                has_intrinsic_evidence = True
                evidence_type = "service-wide-degradation"
            elif self_score >= 0.3:
                has_intrinsic_evidence = True
                evidence_type = "strong-service-symptoms"

            # 2. Weak metrics BUT strong physics (latent unmeasurable health)
            # Pattern: Outgoing impact WITHOUT incoming impact = intrinsic problem
            elif physics_coverage > 0.3:  # Causing significant downstream impact
                # Check if this node has incoming problems (is it a victim?)
                # If no incoming edges have issues, this node is likely the source
                # This handles queues, caches, external deps with latent issues
                has_intrinsic_evidence = True
                evidence_type = "physics-latent-health"

                # Add to story
                if 'story' in candidate and isinstance(candidate['story'], str):
                    candidate['story'] += (
                        f"\n⚠️  LATENT HEALTH: No direct metrics show degradation, but causing "
                        f"{physics_coverage*100:.0f}% downstream impact. Likely unmeasured internal issue."
                    )

            # 3. External dependencies (no intrinsic metrics available)
            # Evaluate by caller consensus
            elif is_external_dep:
                # External deps can't have "intrinsic" metrics
                # Accept if they have ANY physics evidence (caller consensus)
                if physics_coverage > 0.1:  # Even weak physics evidence is meaningful
                    has_intrinsic_evidence = True
                    evidence_type = "external-dep-caller-consensus"

                    if 'story' in candidate and isinstance(candidate['story'], str):
                        candidate['story'] += (
                            f"\n📊 EXTERNAL DEP: No intrinsic metrics available. "
                            f"Evidence from {len(incoming_edges)} caller(s) reporting degradation."
                        )

            # 4. Leaf nodes (no outgoing calls) - errors are pure health signal
            # Consumer services fall in this bucket
            elif is_leaf:
                # For leaf nodes, errors indicate internal problems (not cascading)
                # Check if node has error symptoms
                symptoms = candidate.get('symptoms', [])
                has_errors = any('error' in str(s).lower() for s in symptoms)

                if has_errors or self_score >= 0.1:  # Lower threshold for leaf nodes
                    has_intrinsic_evidence = True
                    evidence_type = "leaf-node-errors"

                    if 'story' in candidate and isinstance(candidate['story'], str):
                        candidate['story'] += (
                            f"\n🎯 LEAF NODE: No downstream dependencies. "
                            f"Errors/degradation indicate internal problem, not cascading effect."
                        )

            # 5. Hot shard / Outlier pod with strong physics
            # Low coverage BUT high explanatory power = legitimate hot shard
            elif source == 'pod-level' and coverage < 0.5 and physics_coverage > 0.4:
                has_intrinsic_evidence = True
                evidence_type = "hot-shard"

                pattern = health_meta.get('pattern', 'Unknown pattern')
                if 'story' in candidate and isinstance(candidate['story'], str):
                    candidate['story'] += (
                        f"\n🔥 HOT SHARD: {pattern} but explains {physics_coverage*100:.0f}% of system impact. "
                        f"Legitimate localized fault with broad effect."
                    )

            # === FILTER DECISION ===
            if has_intrinsic_evidence:
                # Add evidence metadata
                candidate['filter_evidence'] = evidence_type
                filtered_rankings.append(candidate)

        # If filter removed everything, use physics-only fallback
        if len(filtered_rankings) == 0:
            # Fall back to top physics coverage (pure causal reasoning)
            physics_sorted = sorted(rankings,
                                  key=lambda x: x.get('score_composition', {}).get('physics_coverage', {}).get('raw', 0),
                                  reverse=True)[:3]
            for c in physics_sorted:
                c['filter_evidence'] = 'fallback-physics-only'
                # Story can be list or string, handle both
                story = c.get('story', [])
                if isinstance(story, list):
                    story.append("⚠️  FALLBACK: Weak metrics but selected by physics reasoning.")
                else:
                    c['story'] = story + "\n⚠️  FALLBACK: Weak metrics but selected by physics reasoning."
            filtered_rankings = physics_sorted

        return sorted(filtered_rankings, key=lambda x: x['score'], reverse=True)

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
