"""
trace_analyzer.py

Trace-Based Latency Analysis for RCA.
Uses distributed traces to calculate self-time vs total-time,
which is AUTHORITATIVE for identifying where latency originates.

Key insight: High self-time = component's internal logic is slow (ROOT CAUSE)
             High total-time, low self-time = waiting on dependencies (VICTIM)
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class SpanData:
    """Represents a single span from a trace."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    component_id: str
    operation: str
    timestamp: float
    duration_ms: float
    status: str


@dataclass
class ComponentLatency:
    """Latency metrics for a component."""
    component_id: str
    baseline_total_p99: float
    fault_total_p99: float
    total_degradation_factor: float
    baseline_self_p99: float
    fault_self_p99: float
    self_time_degradation_factor: float
    baseline_count: int
    fault_count: int


class TraceAnalyzer:
    """
    Analyzes distributed traces to identify latency root causes.
    """

    def __init__(self, topology=None):
        """
        Args:
            topology: Optional NetworkX graph for service-level aggregation
        """
        self.topology = topology

    def load_traces(self, traces_file: Path) -> List[SpanData]:
        """
        Load traces from JSONL file.

        Args:
            traces_file: Path to traces.jsonl

        Returns:
            List of SpanData objects
        """
        if not traces_file.exists():
            return []

        spans = []
        try:
            with open(traces_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)

                        # Handle nested context structure
                        context = data.get('context', {})
                        attributes = data.get('attributes', {})

                        # Extract trace_id and span_id
                        trace_id = context.get('trace_id', data.get('trace_id', ''))
                        span_id = context.get('span_id', data.get('span_id', ''))

                        # Extract parent_span_id
                        parent_span_id = data.get('parent_id', data.get('parent_span_id'))

                        # Extract component_id
                        component_id = attributes.get('component.id', data.get('component_id', data.get('service_name', '')))

                        # Extract operation name
                        operation = data.get('name', data.get('operation', ''))

                        # Extract timestamp (prefer sim.start_time from attributes)
                        timestamp = float(attributes.get('sim.start_time', data.get('timestamp', 0)))

                        # Extract duration (prefer duration.ms from attributes)
                        duration_ms = float(attributes.get('duration.ms', data.get('duration_ms', data.get('duration', 0))))

                        # Extract status
                        status_obj = data.get('status', {})
                        if isinstance(status_obj, dict):
                            status = status_obj.get('status_code', 'OK')
                        else:
                            status = str(status_obj) if status_obj else 'OK'

                        span = SpanData(
                            trace_id=trace_id,
                            span_id=span_id,
                            parent_span_id=parent_span_id,
                            component_id=component_id,
                            operation=operation,
                            timestamp=timestamp,
                            duration_ms=duration_ms,
                            status=status
                        )
                        spans.append(span)
                    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                        continue
        except Exception:
            return []

        return spans

    def calculate_self_time(
        self,
        span: SpanData,
        trace_spans: List[SpanData]
    ) -> float:
        """
        Calculate self time: duration minus child span durations.

        Example:
        Parent span: 100ms total
        Child span 1: 40ms
        Child span 2: 30ms
        Self time: 100 - 40 - 30 = 30ms (time in parent's logic)

        Args:
            span: The span to calculate self-time for
            trace_spans: All spans in the same trace

        Returns:
            Self-time in milliseconds
        """
        total_time = span.duration_ms
        child_time = 0.0

        # Find all direct children of this span
        for other_span in trace_spans:
            if other_span.parent_span_id == span.span_id:
                child_time += other_span.duration_ms

        # Self-time cannot be negative (due to timing inaccuracies)
        return max(0.0, total_time - child_time)

    def _map_to_service(self, component_id: str) -> str:
        """
        Map pod-level component ID to service-level.
        If topology is provided, maps pods to their parent service.
        Otherwise returns component_id as-is.
        """
        if not self.topology:
            return component_id

        node_attrs = self.topology.nodes.get(component_id, {})
        parent_service = node_attrs.get('parent_service')

        # If this is a pod, return parent service
        # Otherwise return the component itself (Service, ExternalService, etc.)
        return parent_service if parent_service else component_id

    def analyze_traces(
        self,
        traces_file: Path,
        fault_start_time: float
    ) -> Dict[str, ComponentLatency]:
        """
        Extract latency metrics from distributed traces.

        Calculates both total-time and self-time for each component,
        split into baseline (pre-fault) and fault (post-fault) periods.

        NOTE: If no pre-fault traces exist, uses early fault traces as pseudo-baseline.

        Args:
            traces_file: Path to traces.jsonl
            fault_start_time: When the fault was injected

        Returns:
            {component_id: ComponentLatency}
        """
        # Load all spans
        all_spans = self.load_traces(traces_file)

        if not all_spans:
            return {}

        # Split into baseline and fault periods
        baseline_spans = [s for s in all_spans if s.timestamp < fault_start_time]
        fault_spans = [s for s in all_spans if s.timestamp >= fault_start_time]

        # FALLBACK: If no baseline traces, use early fault traces as pseudo-baseline
        if not baseline_spans and fault_spans:
            # Use first 30 seconds of fault period as baseline
            # and later period as degraded state
            early_cutoff = fault_start_time + 30
            baseline_spans = [s for s in fault_spans if s.timestamp < early_cutoff]
            fault_spans = [s for s in fault_spans if s.timestamp >= early_cutoff]

        # If still no data, return empty
        if not baseline_spans or not fault_spans:
            return {}

        # Group spans by trace_id for self-time calculation
        baseline_traces = self._group_by_trace(baseline_spans)
        fault_traces = self._group_by_trace(fault_spans)

        # Calculate latency metrics for each component
        component_metrics = {}

        # Get all unique components and map to service level
        all_components_raw = set(s.component_id for s in all_spans)
        all_components = set(self._map_to_service(c) for c in all_components_raw if c)

        for component_id in all_components:
            if not component_id:
                continue

            # Extract spans for this component (may include multiple pods mapped to same service)
            baseline_comp_spans = [s for s in baseline_spans if self._map_to_service(s.component_id) == component_id]
            fault_comp_spans = [s for s in fault_spans if self._map_to_service(s.component_id) == component_id]

            if not baseline_comp_spans or not fault_comp_spans:
                continue

            # Calculate TOTAL durations (full span)
            baseline_total_durations = [s.duration_ms for s in baseline_comp_spans]
            fault_total_durations = [s.duration_ms for s in fault_comp_spans]

            baseline_total_p99 = np.percentile(baseline_total_durations, 99) if baseline_total_durations else 0.0
            fault_total_p99 = np.percentile(fault_total_durations, 99) if fault_total_durations else 0.0

            # Calculate SELF durations (subtract child spans)
            baseline_self_durations = []
            for span in baseline_comp_spans:
                trace_spans = baseline_traces.get(span.trace_id, [])
                self_time = self.calculate_self_time(span, trace_spans)
                baseline_self_durations.append(self_time)

            fault_self_durations = []
            for span in fault_comp_spans:
                trace_spans = fault_traces.get(span.trace_id, [])
                self_time = self.calculate_self_time(span, trace_spans)
                fault_self_durations.append(self_time)

            baseline_self_p99 = np.percentile(baseline_self_durations, 99) if baseline_self_durations else 0.0
            fault_self_p99 = np.percentile(fault_self_durations, 99) if fault_self_durations else 0.0

            # Calculate degradation factors
            total_deg_factor = (fault_total_p99 / baseline_total_p99) if baseline_total_p99 > 0 else 1.0
            self_deg_factor = (fault_self_p99 / baseline_self_p99) if baseline_self_p99 > 0 else 1.0

            component_metrics[component_id] = ComponentLatency(
                component_id=component_id,
                baseline_total_p99=baseline_total_p99,
                fault_total_p99=fault_total_p99,
                total_degradation_factor=total_deg_factor,
                baseline_self_p99=baseline_self_p99,
                fault_self_p99=fault_self_p99,
                self_time_degradation_factor=self_deg_factor,
                baseline_count=len(baseline_comp_spans),
                fault_count=len(fault_comp_spans)
            )

        return component_metrics

    def _group_by_trace(self, spans: List[SpanData]) -> Dict[str, List[SpanData]]:
        """
        Group spans by trace_id.

        Returns:
            {trace_id: [spans]}
        """
        traces = defaultdict(list)
        for span in spans:
            traces[span.trace_id].append(span)
        return dict(traces)

    def calculate_trace_scores(
        self,
        component_metrics: Dict[str, ComponentLatency]
    ) -> Dict[str, Dict]:
        """
        Calculate trace-based evidence scores.

        High self-time degradation is AUTHORITATIVE evidence of root cause.

        Args:
            component_metrics: Output from analyze_traces()

        Returns:
            {component_id: {'trace_score': float, 'is_authoritative': bool, ...}}
        """
        scores = {}

        for component_id, metrics in component_metrics.items():
            trace_score = 0.0
            is_authoritative = False
            reason = ""

            # Check self-time degradation (MOST IMPORTANT)
            # STRICTER: Only mark as authoritative if self-time is SIGNIFICANTLY degraded
            # and the degradation is primarily internal (not just waiting on deps)
            if metrics.self_time_degradation_factor > 2.0:
                # This component's INTERNAL processing is slow
                if metrics.self_time_degradation_factor > 5.0:
                    trace_score = 20.0
                    reason = f"Self-time increased {metrics.self_time_degradation_factor:.1f}x (critical)"
                elif metrics.self_time_degradation_factor > 3.0:
                    trace_score = 15.0
                    reason = f"Self-time increased {metrics.self_time_degradation_factor:.1f}x (high)"
                else:
                    trace_score = 10.0
                    reason = f"Self-time increased {metrics.self_time_degradation_factor:.1f}x"

                # Only mark as AUTHORITATIVE if:
                # 1. Self-time degradation is significant (> 3.0x)
                # 2. Self-time degradation dominates total degradation (> 80% of total)
                if (metrics.self_time_degradation_factor > 3.0 and
                    metrics.self_time_degradation_factor > metrics.total_degradation_factor * 0.8):
                    is_authoritative = True

            # Check total-time degradation (LESS IMPORTANT - could be waiting on deps)
            elif metrics.total_degradation_factor > 5.0:
                trace_score = 8.0
                reason = f"Total latency increased {metrics.total_degradation_factor:.1f}x (may be waiting on deps)"
            elif metrics.total_degradation_factor > 2.0:
                trace_score = 5.0
                reason = f"Total latency increased {metrics.total_degradation_factor:.1f}x"

            if trace_score > 0:
                scores[component_id] = {
                    'trace_score': trace_score,
                    'is_authoritative': is_authoritative,
                    'self_time_degradation': metrics.self_time_degradation_factor,
                    'total_time_degradation': metrics.total_degradation_factor,
                    'baseline_self_p99': metrics.baseline_self_p99,
                    'fault_self_p99': metrics.fault_self_p99,
                    'reason': reason
                }

        return scores

    def analyze(
        self,
        traces_file: Path,
        fault_start_time: float
    ) -> Dict[str, Dict]:
        """
        Main entry point: Analyze traces and calculate scores.

        Args:
            traces_file: Path to traces.jsonl
            fault_start_time: When fault was injected

        Returns:
            {component_id: {'trace_score': float, 'is_authoritative': bool, ...}}
        """
        # Extract latency metrics from traces
        component_metrics = self.analyze_traces(traces_file, fault_start_time)

        # Calculate trace-based scores
        trace_scores = self.calculate_trace_scores(component_metrics)

        return trace_scores
