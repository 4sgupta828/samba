#!/usr/bin/env python3
"""
Fault Propagation Analyzer

Analyzes how a fault in a root cause node propagates through the system
and affects metrics of all dependent nodes.

Usage:
    python analyze_fault_propagation.py <episode_dir> [--json]

Arguments:
    episode_dir    Path to episode directory containing label.json, topology.json, and metrics.jsonl
    --json         Output results as JSON instead of human-readable format

Examples:
    python analyze_fault_propagation.py data/data_20251125_092902/ep_1
    python analyze_fault_propagation.py data/data_20251125_092902/ep_1 --json > analysis.json

What it does:
    1. Identifies the root cause node from label.json
    2. Builds the dependency graph from topology.json
    3. Finds all nodes that depend on the root cause (directly or indirectly)
    4. Analyzes metrics at key time points:
       - Baseline (before fault)
       - Fault start
       - Early fault
       - Mid-ramp
       - Full effect
       - Sustained failure
    5. Reports how each layer of dependencies was impacted
    6. Shows the propagation chain with quantified impact (latency multipliers, etc.)
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Any
import statistics


class FaultPropagationAnalyzer:
    def __init__(self, episode_dir: str, silent: bool = False):
        self.episode_dir = Path(episode_dir)
        self.label = None
        self.topology = None
        self.metrics = defaultdict(list)
        self.dependency_graph = defaultdict(list)
        self.reverse_dependency_graph = defaultdict(list)
        self.silent = silent  # Suppress stdout when generating JSON

    def load_data(self):
        """Load episode data from files"""
        if not self.silent:
            print(f"Loading data from {self.episode_dir}...")

        # Load label.json
        with open(self.episode_dir / "label.json") as f:
            self.label = json.load(f)

        # Load topology.json
        with open(self.episode_dir / "topology.json") as f:
            self.topology = json.load(f)

        # Build dependency graphs
        self._build_dependency_graph()

        # Load metrics.jsonl (sample key metrics only to avoid memory issues)
        self._load_metrics()

        if not self.silent:
            print(f"✓ Loaded label, topology, and metrics")

    def _build_dependency_graph(self):
        """Build forward and reverse dependency graphs from topology edges"""
        for edge in self.topology["edges"]:
            source = edge["source"]
            target = edge["target"]
            edge_type = edge["type"]

            # Skip pod_pool and pod_placement edges (infrastructure)
            if edge_type in ["pod_pool", "pod_placement"]:
                continue

            self.dependency_graph[source].append({
                "target": target,
                "type": edge_type
            })
            self.reverse_dependency_graph[target].append({
                "source": source,
                "type": edge_type
            })

    def _load_metrics(self):
        """Load relevant metrics from metrics.jsonl"""
        if not self.silent:
            print("Loading metrics (this may take a moment)...")

        metrics_file = self.episode_dir / "metrics.jsonl"
        with open(metrics_file) as f:
            for line in f:
                metric = json.loads(line)
                metric_name = metric["name"]
                sim_time = int(metric["labels"].get("sim.time", 0))
                component_id = metric["labels"].get("component.id", "")

                # Store metrics by component and time
                key = (component_id, metric_name, sim_time)
                self.metrics[key].append(metric)

        if not self.silent:
            print(f"✓ Loaded metrics for {len(set(k[0] for k in self.metrics.keys()))} components")

    def find_dependent_nodes(self, root_node: str, max_depth: int = 5) -> Dict[str, int]:
        """
        Find all nodes that depend on the root_node (directly or indirectly)
        Returns: dict of {node_id: distance_from_root}
        """
        visited = {root_node: 0}
        queue = deque([(root_node, 0)])

        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Find all nodes that depend on this node (reverse dependencies)
            for dep in self.reverse_dependency_graph[node]:
                dependent_node = dep["source"]
                if dependent_node not in visited:
                    visited[dependent_node] = depth + 1
                    queue.append((dependent_node, depth + 1))

        return visited

    def get_metric_summary(self, component_id: str, metric_name: str, time: int) -> Dict:
        """Get metric summary for a component at a specific time"""
        # Check component directly
        key = (component_id, metric_name, time)
        metrics = self.metrics.get(key, [])

        # If service, aggregate from pods
        if not metrics and self._get_node_type(component_id) == "Service":
            pods = [node["id"] for node in self.topology["nodes"]
                   if node.get("type") == "Pod" and node.get("parent_service") == component_id]

            # Aggregate metrics from all pods
            pod_metrics = []
            for pod_id in pods:
                pod_key = (pod_id, metric_name, time)
                pod_metrics.extend(self.metrics.get(pod_key, []))

            if pod_metrics:
                # Average the metrics from all pods
                return self._aggregate_metrics(pod_metrics)

        if not metrics:
            return None

        metric = metrics[0]
        if "summary" in metric:
            return metric["summary"]
        elif "value" in metric:
            return {"value": metric["value"]}
        return None

    def _aggregate_metrics(self, metrics: List[Dict]) -> Dict:
        """Aggregate metrics from multiple sources (e.g., pods)"""
        if not metrics:
            return None

        # If metrics have summaries, average the percentiles
        if "summary" in metrics[0]:
            summaries = [m["summary"] for m in metrics]
            aggregated = {}

            for key in ["p50", "p90", "p99", "count", "sum", "max"]:
                values = [s[key] for s in summaries if key in s]
                if values:
                    if key == "count":
                        aggregated[key] = sum(values)
                    elif key == "sum":
                        aggregated[key] = sum(values)
                    elif key == "max":
                        aggregated[key] = max(values)
                    else:
                        aggregated[key] = statistics.mean(values)

            return aggregated

        # If metrics have simple values, average them
        elif "value" in metrics[0]:
            values = [m["value"] for m in metrics]
            return {"value": statistics.mean(values)}

        return None

    def analyze_metric_impact(self, component_id: str, metric_name: str,
                            baseline_time: int, fault_time: int) -> Dict:
        """Analyze how a metric changed from baseline to fault time"""
        baseline = self.get_metric_summary(component_id, metric_name, baseline_time)
        fault = self.get_metric_summary(component_id, metric_name, fault_time)

        # For error metrics, treat missing baseline as 0
        metric_type = self._classify_metric(metric_name)
        if metric_type == "error" and not baseline and fault:
            baseline = {"value": 0}
        elif not baseline or not fault:
            return None

        result = {"baseline": baseline, "fault": fault, "changes": {}, "metric_type": self._classify_metric(metric_name)}

        # Compare p50, p90, p99 if available
        for percentile in ["p50", "p90", "p99"]:
            if percentile in baseline and percentile in fault:
                baseline_val = baseline[percentile]
                fault_val = fault[percentile]
                if baseline_val > 0:
                    change_pct = ((fault_val - baseline_val) / baseline_val) * 100
                    change_mult = fault_val / baseline_val
                    result["changes"][percentile] = {
                        "from": baseline_val,
                        "to": fault_val,
                        "change_pct": change_pct,
                        "multiplier": change_mult,
                        "significance": self._assess_significance(change_mult, metric_name)
                    }

        # Compare simple values
        if "value" in baseline and "value" in fault:
            baseline_val = baseline["value"]
            fault_val = fault["value"]

            # Handle error metrics specially
            if "error" in metric_name.lower() or "reject" in metric_name.lower():
                # For error metrics, any increase is significant
                change_pct = ((fault_val - baseline_val) / (baseline_val + 1)) * 100  # +1 to avoid div by 0
                multiplier = fault_val / (baseline_val + 1) if baseline_val == 0 else fault_val / baseline_val
            elif baseline_val > 0:
                change_pct = ((fault_val - baseline_val) / baseline_val) * 100
                multiplier = fault_val / baseline_val
            else:
                change_pct = 0 if fault_val == 0 else float('inf')
                multiplier = float('inf') if fault_val > 0 else 1.0

            result["changes"]["value"] = {
                "from": baseline_val,
                "to": fault_val,
                "change_pct": change_pct,
                "multiplier": multiplier if "multiplier" in locals() else (1.0 if change_pct == 0 else float('inf')),
                "significance": self._assess_significance(multiplier if "multiplier" in locals() else 1.0, metric_name)
            }

        # Compare count metrics for error rates
        if "count" in baseline and "count" in fault:
            result["changes"]["count"] = {
                "from": baseline["count"],
                "to": fault["count"],
                "change_pct": ((fault["count"] - baseline["count"]) / (baseline["count"] + 1)) * 100
            }

        return result

    def _classify_metric(self, metric_name: str) -> str:
        """Classify metric type for better interpretation"""
        metric_lower = metric_name.lower()
        if any(x in metric_lower for x in ["error", "fail", "reject", "timeout", "exception"]):
            return "error"
        elif any(x in metric_lower for x in ["latency", "duration", "time"]):
            return "latency"
        elif any(x in metric_lower for x in ["cpu", "memory", "utilization"]):
            return "resource"
        elif any(x in metric_lower for x in ["queue", "pool", "active", "connection"]):
            return "saturation"
        elif any(x in metric_lower for x in ["request", "throughput", "rate"]):
            return "throughput"
        return "other"

    def _assess_significance(self, multiplier: float, metric_name: str) -> str:
        """Assess the significance of a metric change"""
        metric_type = self._classify_metric(metric_name)

        # For error metrics, any increase is critical
        if metric_type == "error":
            if multiplier > 10:
                return "CRITICAL"
            elif multiplier > 2:
                return "HIGH"
            elif multiplier > 1.1:
                return "MEDIUM"
            return "LOW"

        # For latency metrics
        elif metric_type == "latency":
            if multiplier > 10:
                return "CRITICAL"
            elif multiplier > 5:
                return "HIGH"
            elif multiplier > 2:
                return "MEDIUM"
            elif multiplier > 1.5:
                return "LOW"
            return "NEGLIGIBLE"

        # For resource/saturation
        elif metric_type in ["resource", "saturation"]:
            if multiplier > 5:
                return "CRITICAL"
            elif multiplier > 3:
                return "HIGH"
            elif multiplier > 1.5:
                return "MEDIUM"
            return "LOW"

        # Default
        if abs(multiplier - 1.0) > 2:
            return "HIGH"
        elif abs(multiplier - 1.0) > 0.5:
            return "MEDIUM"
        return "LOW"

    def analyze_node_metrics(self, node_id: str, baseline_time: int,
                           fault_times: List[int]) -> Dict:
        """Analyze all relevant metrics for a node"""
        node_type = self._get_node_type(node_id)

        # Define metrics to analyze based on node type
        metrics_to_check = {
            "Service": [
                # Latency metrics
                "service.{}.duration",
                "service.{}.dependency.duration",
                # Error metrics
                "service.{}.errors",
                "service.{}.dependency.errors",
                "component.errors.total",
                # Request metrics
                "service.{}.requests",
                "service.{}.dependency.requests",
                # Resource metrics
                "container.cpu.utilization",
                "container.memory.usage_mb",
                # Saturation metrics
                "thread_pool.threads.active",
                "thread_pool.queue.depth",
                "connection_pool.connections.active",
                "connection_pool.queue_depth"
            ],
            "SqlDatabase": [
                "db.query.latency",
                "db.connections.active",
                "db.connections.rejected",
                "db.cpu.utilization"
            ],
            "InMemoryCache": [
                "cache.hit_rate",
                "cache.misses.total"
            ],
            "RequestGateway": [
                "http.server.request.duration",
                "gateway.dependency.duration",
                "gateway.dependency.errors",
                "http.server.requests"
            ],
            "ExternalService": [
                "external.response.duration",
                "external.errors.total",
                "external.requests.total"
            ]
        }

        metrics_list = metrics_to_check.get(node_type, [])

        results = {}
        for metric_template in metrics_list:
            # Handle wildcard metrics
            if "{}" in metric_template:
                # Find actual metric names that match this pattern
                matching_metrics = self._find_matching_metrics(node_id, metric_template)
            else:
                matching_metrics = [metric_template]

            for metric_name in matching_metrics:
                # Analyze at each fault time
                for fault_time in fault_times:
                    impact = self.analyze_metric_impact(node_id, metric_name,
                                                       baseline_time, fault_time)
                    if impact and impact.get("changes"):
                        if metric_name not in results:
                            results[metric_name] = []
                        results[metric_name].append({
                            "time": fault_time,
                            "impact": impact
                        })

        return results

    def _get_node_type(self, node_id: str) -> str:
        """Get the type of a node from topology"""
        for node in self.topology["nodes"]:
            if node["id"] == node_id:
                return node["type"]
        return "Unknown"

    def _find_matching_metrics(self, component_id: str, metric_template: str) -> List[str]:
        """Find actual metric names matching a template"""
        matching = set()

        # For services, also check pod-level metrics
        pods = []
        if self._get_node_type(component_id) == "Service":
            pods = [node["id"] for node in self.topology["nodes"]
                   if node.get("type") == "Pod" and node.get("parent_service") == component_id]

        components_to_check = [component_id] + pods

        for (comp_id, metric_name, _) in self.metrics.keys():
            if comp_id in components_to_check:
                # Simple pattern matching
                if "{}" in metric_template:
                    pattern_base = metric_template.split("{}")[0]
                    if metric_name.startswith(pattern_base):
                        matching.add(metric_name)
                elif metric_name == metric_template:
                    matching.add(metric_name)
        return list(matching)

    def analyze_propagation_chain(self) -> Dict:
        """Analyze the complete fault propagation chain"""
        root_node = self.label["root_cause_node"]
        fault_start_time = self.label["fault_start_time"]
        fault_full_effect_time = self.label["fault_full_effect_time"]

        if not self.silent:
            print(f"\n{'='*80}")
            print(f"FAULT PROPAGATION ANALYSIS")
            print(f"{'='*80}")
            print(f"Episode: {self.label['episode']}")
            print(f"Scenario: {self.label['scenario']}")
            print(f"Root Cause: {root_node} ({self.label['root_cause_role']})")
            print(f"Fault Type: {self.label['fault_type']}")
            print(f"Timeline: Fault starts at {fault_start_time}s, full effect at {fault_full_effect_time}s")
            print(f"{'='*80}\n")

        # Find all dependent nodes
        dependent_nodes = self.find_dependent_nodes(root_node)

        if not self.silent:
            print(f"Found {len(dependent_nodes)} nodes in dependency chain\n")

        # Analyze at key time points
        baseline_time = 5
        fault_times = [
            fault_start_time,
            fault_start_time + 20,  # Early fault
            (fault_start_time + fault_full_effect_time) // 2,  # Mid ramp
            fault_full_effect_time,  # Full effect
            fault_full_effect_time + 100  # Sustained failure
        ]

        # Group nodes by distance from root
        nodes_by_distance = defaultdict(list)
        for node, distance in dependent_nodes.items():
            nodes_by_distance[distance].append(node)

        # Analyze each layer
        results = {}
        for distance in sorted(nodes_by_distance.keys()):
            if not self.silent:
                print(f"\n{'─'*80}")
                print(f"LAYER {distance}: {'ROOT CAUSE' if distance == 0 else f'{distance} hop(s) from root cause'}")
                print(f"{'─'*80}")

            nodes = nodes_by_distance[distance]

            if not self.silent:
                print(f"Nodes: {', '.join(nodes)}\n")

            for node in nodes:
                node_type = self._get_node_type(node)

                if not self.silent:
                    print(f"\n📊 {node} ({node_type})")
                    print(f"   {'─'*70}")

                # Analyze metrics for this node
                metrics_impact = self.analyze_node_metrics(node, baseline_time, fault_times)

                if metrics_impact:
                    # Group and sort metrics by significance
                    critical_metrics = []
                    high_metrics = []
                    medium_metrics = []

                    for metric_name, impacts in metrics_impact.items():
                        # Show most significant impact
                        max_impact = None
                        max_multiplier = 1.0
                        max_significance = "LOW"

                        for impact_data in impacts:
                            for change_key, change_val in impact_data["impact"]["changes"].items():
                                if "multiplier" in change_val:
                                    if abs(change_val["multiplier"] - 1.0) > abs(max_multiplier - 1.0):
                                        max_multiplier = change_val["multiplier"]
                                        max_impact = (impact_data["time"], change_key, change_val, metric_name)
                                        max_significance = change_val.get("significance", "LOW")

                        if max_impact:
                            metric_type = impact_data["impact"].get("metric_type", "other")
                            if max_significance == "CRITICAL":
                                critical_metrics.append((max_impact, metric_type))
                            elif max_significance == "HIGH":
                                high_metrics.append((max_impact, metric_type))
                            elif max_significance == "MEDIUM":
                                medium_metrics.append((max_impact, metric_type))

                    # Display metrics by priority
                    if not self.silent:
                        all_metrics = critical_metrics + high_metrics + medium_metrics

                        for (time, percentile, change, metric_name), metric_type in all_metrics:
                            # Always show error metrics, or significant changes in other metrics
                            should_display = (metric_type == "error" and change.get("from", 0) < change.get("to", 0)) or \
                                           change["multiplier"] > 1.5 or change["multiplier"] < 0.5
                            if should_display:
                                # Choose symbol based on metric type and significance
                                significance = change.get("significance", "LOW")
                                if metric_type == "error":
                                    if significance == "CRITICAL":
                                        symbol = "🔴"
                                    elif significance == "HIGH":
                                        symbol = "🟠"
                                    else:
                                        symbol = "🟡"
                                elif change["multiplier"] > 1:
                                    symbol = "📈" if significance in ["LOW", "MEDIUM"] else "⚠️"
                                else:
                                    symbol = "📉"

                                print(f"\n   {symbol} {metric_name} [{significance}]")
                                print(f"      At t={time}s: {percentile}")
                                print(f"      Baseline: {change['from']:.2f}")
                                print(f"      Fault:    {change['to']:.2f}")
                                print(f"      Change:   {change['multiplier']:.1f}x ({change['change_pct']:+.1f}%)")

                elif not self.silent:
                    print("   ℹ️  No significant metric changes detected")

                results[node] = {
                    "distance": distance,
                    "type": node_type,
                    "metrics": metrics_impact
                }

        # Summary statistics
        if not self.silent:
            print(f"\n\n{'='*80}")
            print(f"IMPACT SUMMARY")
            print(f"{'='*80}")

            # Count impacted nodes by layer
            impacted_by_layer = defaultdict(int)
            for node, data in results.items():
                if data["metrics"]:
                    impacted_by_layer[data["distance"]] += 1

            print("\nImpacted nodes by distance from root cause:")
            for distance in sorted(impacted_by_layer.keys()):
                print(f"  Layer {distance}: {impacted_by_layer[distance]} nodes impacted")

            # Analyze request success rates
            self._analyze_success_rates(fault_times)

        return results

    def _analyze_success_rates(self, fault_times: List[int]):
        """Analyze request success rates over time"""
        print("\n\nRequest Success Rate Analysis:")
        print(f"{'─'*80}")

        baseline_time = 5

        for time_point in [baseline_time] + fault_times:
            attempted = self.get_metric_summary("global", "workload.requests", time_point)
            success = self.get_metric_summary("global", "workload.requests", time_point)

            # Try different component IDs for workload metrics
            if not attempted:
                for key in self.metrics.keys():
                    if key[1] == "workload.requests" and key[2] == time_point:
                        metric = self.metrics[key][0]
                        if metric["labels"].get("type") == "attempted":
                            attempted = {"value": metric["value"]}
                        elif metric["labels"].get("type") == "success":
                            success = {"value": metric["value"]}

            if attempted and success and "value" in attempted and "value" in success:
                attempted_val = attempted["value"]
                success_val = success["value"]
                success_rate = (success_val / attempted_val * 100) if attempted_val > 0 else 0

                status_icon = "✅" if success_rate > 80 else "⚠️" if success_rate > 50 else "🔴"
                print(f"{status_icon} t={time_point:3d}s: {success_val:3.0f}/{attempted_val:3.0f} successful "
                      f"({success_rate:5.1f}%)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    episode_dir = sys.argv[1]
    json_output = "--json" in sys.argv

    if not Path(episode_dir).exists():
        print(f"Error: Episode directory '{episode_dir}' not found")
        sys.exit(1)

    analyzer = FaultPropagationAnalyzer(episode_dir, silent=json_output)
    analyzer.load_data()
    results = analyzer.analyze_propagation_chain()

    if json_output:
        # Output as JSON
        output = {
            "episode": analyzer.label,
            "propagation": results,
            "topology": {
                "nodes": analyzer.topology["num_nodes"],
                "edges": analyzer.topology["num_edges"]
            }
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n\n✓ Analysis complete!")


if __name__ == "__main__":
    main()
