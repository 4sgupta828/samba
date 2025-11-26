"""
Trace-Based Latency Analyzer

Extracts actual latency measurements from trace data to provide concrete
performance metrics (mean, p50, p95, p99) for baseline vs fault periods.
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class LatencyStats:
    """Statistical summary of latencies."""
    mean_ms: float
    median_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    std_ms: float
    sample_count: int

    def to_dict(self) -> Dict:
        """Convert to dictionary, rounding to 2 decimal places."""
        return {
            k: round(v, 2) if isinstance(v, float) else v
            for k, v in asdict(self).items()
        }


@dataclass
class LatencyAnalysis:
    """Complete latency analysis for a component."""
    component_id: str
    component_type: str
    operation_type: str
    baseline: LatencyStats
    fault: LatencyStats
    degradation_factor: float
    mean_increase_ms: float
    interpretation: str

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'component_id': self.component_id,
            'component_type': self.component_type,
            'operation_type': self.operation_type,
            'baseline': self.baseline.to_dict(),
            'fault': self.fault.to_dict(),
            'degradation_factor': round(self.degradation_factor, 2),
            'mean_increase_ms': round(self.mean_increase_ms, 2),
            'interpretation': self.interpretation
        }


class TraceLatencyAnalyzer:
    """Analyzes latency from distributed trace data."""

    def __init__(self, traces_file: Path, fault_start_time: float):
        """
        Initialize analyzer.

        Args:
            traces_file: Path to traces.jsonl file
            fault_start_time: Time when fault was injected (seconds)
        """
        self.traces_file = Path(traces_file)
        self.fault_start_time = fault_start_time
        self.baseline_end_time = fault_start_time  # Everything before is baseline

    def extract_latencies(self) -> Dict[str, List[Tuple[float, float]]]:
        """
        Extract all latencies from traces, organized by component.

        Returns:
            Dictionary mapping component_id -> [(timestamp, duration_ms), ...]
        """
        latencies_by_component = defaultdict(list)

        with open(self.traces_file, 'r') as f:
            for line in f:
                try:
                    trace = json.loads(line)

                    # Extract component info
                    attributes = trace.get('attributes', {})
                    component_id = attributes.get('component.id')
                    duration_ms = attributes.get('duration.ms')
                    sim_time = attributes.get('sim.start_time')

                    if component_id and duration_ms is not None and sim_time is not None:
                        latencies_by_component[component_id].append((sim_time, duration_ms))

                except (json.JSONDecodeError, KeyError):
                    continue

        return latencies_by_component

    def compute_stats(self, latencies: List[float]) -> Optional[LatencyStats]:
        """
        Compute statistical summary of latencies.

        Args:
            latencies: List of latency values in milliseconds

        Returns:
            LatencyStats or None if insufficient data
        """
        if len(latencies) < 10:  # Need at least 10 samples for meaningful stats
            return None

        arr = np.array(latencies)

        return LatencyStats(
            mean_ms=float(np.mean(arr)),
            median_ms=float(np.median(arr)),
            p50_ms=float(np.percentile(arr, 50)),
            p95_ms=float(np.percentile(arr, 95)),
            p99_ms=float(np.percentile(arr, 99)),
            min_ms=float(np.min(arr)),
            max_ms=float(np.max(arr)),
            std_ms=float(np.std(arr)),
            sample_count=len(latencies)
        )

    def analyze_component(
        self,
        component_id: str,
        latencies: List[Tuple[float, float]],
        component_type: str = "Unknown",
        operation_type: str = "operation"
    ) -> Optional[LatencyAnalysis]:
        """
        Analyze latency for a single component.

        Args:
            component_id: Component identifier
            latencies: List of (timestamp, duration_ms) tuples
            component_type: Type of component
            operation_type: Type of operation (e.g., "SQL SELECT", "RPC call")

        Returns:
            LatencyAnalysis or None if insufficient data
        """
        # Split into baseline and fault periods
        baseline_latencies = [dur for ts, dur in latencies if ts < self.baseline_end_time]
        fault_latencies = [dur for ts, dur in latencies if ts >= self.fault_start_time]

        # Compute stats for each period
        baseline_stats = self.compute_stats(baseline_latencies)
        fault_stats = self.compute_stats(fault_latencies)

        if not baseline_stats or not fault_stats:
            return None

        # Calculate degradation
        degradation_factor = fault_stats.mean_ms / baseline_stats.mean_ms if baseline_stats.mean_ms > 0 else 0
        mean_increase_ms = fault_stats.mean_ms - baseline_stats.mean_ms

        # Generate interpretation
        if degradation_factor >= 2.0:
            severity = "severe"
            deg_desc = f"{degradation_factor:.1f}x"
        elif degradation_factor >= 1.5:
            severity = "significant"
            deg_desc = f"{degradation_factor:.1f}x"
        elif degradation_factor >= 1.2:
            severity = "moderate"
            deg_desc = f"{degradation_factor:.1f}x"
        elif degradation_factor >= 0.8:
            severity = "stable"
            deg_desc = "stable"
        else:
            severity = "improved"
            deg_desc = f"{1/degradation_factor:.1f}x faster"

        interpretation = (
            f"Latency {severity}: baseline {baseline_stats.mean_ms:.1f}ms → "
            f"fault {fault_stats.mean_ms:.1f}ms ({deg_desc} degradation). "
            f"P95: {baseline_stats.p95_ms:.1f}ms → {fault_stats.p95_ms:.1f}ms"
        )

        return LatencyAnalysis(
            component_id=component_id,
            component_type=component_type,
            operation_type=operation_type,
            baseline=baseline_stats,
            fault=fault_stats,
            degradation_factor=degradation_factor,
            mean_increase_ms=mean_increase_ms,
            interpretation=interpretation
        )

    def analyze_all(self, topology: Dict) -> Dict[str, LatencyAnalysis]:
        """
        Analyze latencies for all components with trace data.

        Args:
            topology: Topology dictionary with node information

        Returns:
            Dictionary mapping component_id -> LatencyAnalysis
        """
        # Extract all latencies
        latencies_by_component = self.extract_latencies()

        # Create node type lookup
        node_types = {
            node['id']: node.get('type', 'Unknown')
            for node in topology.get('nodes', [])
        }

        # Operation type mapping by component type
        operation_types = {
            'SqlDatabase': 'SQL query',
            'InMemoryCache': 'cache operation',
            'MessageQueue': 'queue operation',
            'Service': 'service call',
            'Pod': 'pod processing',
            'RequestGateway': 'gateway routing',
            'ExternalService': 'external API call'
        }

        # Analyze each component
        results = {}
        for component_id, latencies in latencies_by_component.items():
            node_type = node_types.get(component_id, 'Unknown')
            operation_type = operation_types.get(node_type, 'operation')

            analysis = self.analyze_component(
                component_id,
                latencies,
                component_type=node_type,
                operation_type=operation_type
            )

            if analysis:
                results[component_id] = analysis

        return results

    def generate_report(self, analyses: Dict[str, LatencyAnalysis]) -> str:
        """
        Generate human-readable report of latency analysis.

        Args:
            analyses: Dictionary of LatencyAnalysis objects

        Returns:
            Formatted report string
        """
        if not analyses:
            return "No latency data available from traces.\n"

        lines = ["=" * 80, "TRACE-BASED LATENCY ANALYSIS", "=" * 80, ""]

        # Sort by degradation factor (worst first)
        sorted_analyses = sorted(
            analyses.items(),
            key=lambda x: x[1].degradation_factor,
            reverse=True
        )

        for component_id, analysis in sorted_analyses:
            lines.append(f"\n{component_id} ({analysis.component_type})")
            lines.append("-" * 60)
            lines.append(f"  Operation: {analysis.operation_type}")
            lines.append(f"  {analysis.interpretation}")
            lines.append(f"  Baseline: {analysis.baseline.sample_count} samples")
            lines.append(f"  Fault:    {analysis.fault.sample_count} samples")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)
