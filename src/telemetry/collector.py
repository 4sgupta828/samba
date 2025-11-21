"""
Telemetry collector that tracks counts and metadata for simulation output.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict


class TelemetryCollector:
    """Collects metadata about telemetry data generated during simulation."""

    def __init__(self, simulation_id: str, simulation_start_timestamp_ns: int = None):
        """
        Initialize the telemetry collector.

        Args:
            simulation_id: Unique identifier for this simulation run
            simulation_start_timestamp_ns: Base timestamp (in nanoseconds) for simulation start
        """
        self.simulation_id = simulation_id
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.start_timestamp = None  # Will be set based on actual telemetry data
        self.end_timestamp = None    # Will be set based on actual telemetry data
        self.sim_start_time = None
        self.sim_end_time = None

        # Track actual min/max timestamps from telemetry data
        self.min_telemetry_ts_ns = None
        self.max_telemetry_ts_ns = None

        # Telemetry counts
        self.log_count = 0
        self.log_levels = defaultdict(int)

        self.metric_count = 0
        self.metric_types = defaultdict(int)

        self.unique_trace_ids = set()  # Track actual unique trace IDs
        self.span_count = 0

        # Incident tracking
        self.incidents = []

        # Failure injection timeline (deprecated - kept for backward compatibility)
        self.failure_injections = []

    def record_log(self, log_entry: dict):
        """Record a log entry."""
        self.log_count += 1
        level = log_entry.get("level", "INFO")
        self.log_levels[level] += 1

    def record_metric(self, metric_entry: dict):
        """Record a metric entry."""
        self.metric_count += 1

        # Handle both old OTel format and new summarized format
        if "summary" in metric_entry:
            # New summarized format
            self.metric_types["histogram"] += 1
        elif "value" in metric_entry:
            # New summarized format - gauge or counter
            self.metric_types["gauge"] += 1
        else:
            # Old OTel format - determine metric type from data structure
            data = metric_entry.get("data", {})
            data_points = data.get("data_points", [])

            if data_points:
                first_point = data_points[0]
                if "bucket_counts" in first_point:
                    self.metric_types["histogram"] += 1
                elif "count" in first_point and "sum" in first_point:
                    self.metric_types["sum"] += 1
                elif "value" in first_point:
                    # Could be gauge or counter - check if there's a start_time
                    if "start_time_unix_nano" in first_point:
                        self.metric_types["counter"] += 1
                    else:
                        self.metric_types["gauge"] += 1

    def record_trace(self, span_entry: dict):
        """Record a trace span."""
        self.span_count += 1
        # Track unique trace IDs
        trace_id = span_entry.get("context", {}).get("trace_id")
        if trace_id:
            self.unique_trace_ids.add(trace_id)

    def update_timestamp_range(self, timestamp_ns: int):
        """
        Update the min/max timestamp range based on telemetry data.

        Args:
            timestamp_ns: Timestamp in nanoseconds from telemetry entry
        """
        if self.min_telemetry_ts_ns is None or timestamp_ns < self.min_telemetry_ts_ns:
            self.min_telemetry_ts_ns = timestamp_ns
        if self.max_telemetry_ts_ns is None or timestamp_ns > self.max_telemetry_ts_ns:
            self.max_telemetry_ts_ns = timestamp_ns

    def add_incident(self, incident_report):
        """
        Add an incident report to the metadata.

        Args:
            incident_report: The incident report object with details
        """
        incident_data = json.loads(incident_report.to_json())

        # Calculate anomaly window based on incident times
        start_time = incident_data.get("start_time", 0)
        end_time = incident_data.get("end_time", 0)
        duration = end_time - start_time

        # Extract root cause info
        root_cause = incident_data.get("root_cause", {})
        incident_type = root_cause.get("failure_mode", "unknown")
        root_component = root_cause.get("component_id", "unknown")

        incident_metadata = {
            "incident_id": incident_data.get("incident_id"),
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration,
            "anomaly_window": {
                "start_timestamp": self._sim_time_to_timestamp(start_time),
                "end_timestamp": self._sim_time_to_timestamp(end_time)
            },
            "type": incident_type,
            "root_cause_component": root_component,
            "symptom_count": len(incident_data.get("symptoms", [])),
            "propagation_chain_length": len(incident_data.get("propagation_chain", []))
        }

        self.incidents.append(incident_metadata)

    def add_failure_timeline(self, failure_timeline: list):
        """
        Add failure injection timeline to metadata for visualization markers.

        Args:
            failure_timeline: List of failure injection events with timing and details
        """
        # Convert sim times to timestamps for each event
        enriched_timeline = []
        for event in failure_timeline:
            enriched_event = {
                "id": event["id"],
                "sim_time": event["sim_time"],
                "timestamp": self._sim_time_to_timestamp(event["sim_time"]),
                "mode": event["mode"],
                "targets": event["targets"],
                "params": event.get("params", {}),
                "is_revert": event.get("is_revert", False)
            }
            enriched_timeline.append(enriched_event)

        self.failure_injections = enriched_timeline

    def set_simulation_times(self, start_time: float, end_time: float):
        """
        Set the simulation time boundaries and calculate telemetry timestamp range.

        Args:
            start_time: Simulation start time (usually 0)
            end_time: Simulation end time
        """
        self.sim_start_time = start_time
        self.sim_end_time = end_time

        # Calculate telemetry timestamp range from simulation times
        if self.simulation_start_timestamp_ns is not None:
            # Convert simulation times to actual telemetry timestamps
            start_timestamp_ns = self.simulation_start_timestamp_ns + int(start_time * 1_000_000_000)
            end_timestamp_ns = self.simulation_start_timestamp_ns + int(end_time * 1_000_000_000)

            # Convert to datetime and store as ISO format
            self.start_timestamp = datetime.utcfromtimestamp(start_timestamp_ns / 1_000_000_000).isoformat()
            self.end_timestamp = datetime.utcfromtimestamp(end_timestamp_ns / 1_000_000_000).isoformat()

    def _sim_time_to_timestamp(self, sim_time: float) -> str:
        """
        Convert simulation time to a real timestamp.

        This uses the same calculation as telemetry events to ensure markers
        align correctly with telemetry data in the UI.
        """
        if self.simulation_start_timestamp_ns is None:
            return datetime.utcnow().isoformat()

        # Use the same calculation as telemetry exporters
        # timestamp = simulation_start_timestamp_ns + sim_time_seconds * 1e9
        timestamp_ns = self.simulation_start_timestamp_ns + int(sim_time * 1_000_000_000)

        # Convert to datetime
        timestamp_dt = datetime.utcfromtimestamp(timestamp_ns / 1_000_000_000)

        return timestamp_dt.isoformat()

    def finalize(self):
        """
        Mark the collection as complete and calculate actual timestamp range
        from telemetry data if min/max were tracked.
        """
        # If we tracked actual telemetry timestamps, use those for metadata
        if self.min_telemetry_ts_ns is not None and self.max_telemetry_ts_ns is not None:
            self.start_timestamp = datetime.utcfromtimestamp(self.min_telemetry_ts_ns / 1_000_000_000).isoformat()
            self.end_timestamp = datetime.utcfromtimestamp(self.max_telemetry_ts_ns / 1_000_000_000).isoformat()

            # Also update sim times based on actual data
            if self.simulation_start_timestamp_ns:
                self.sim_start_time = (self.min_telemetry_ts_ns - self.simulation_start_timestamp_ns) / 1_000_000_000
                self.sim_end_time = (self.max_telemetry_ts_ns - self.simulation_start_timestamp_ns) / 1_000_000_000

    def to_metadata(self) -> dict:
        """
        Generate the metadata dictionary.

        Returns:
            Dictionary containing all collected metadata
        """
        # Calculate the true simulation start timestamp (not adjusted for warmup)
        simulation_start_timestamp_iso = None
        if self.simulation_start_timestamp_ns:
            simulation_start_timestamp_iso = datetime.utcfromtimestamp(
                self.simulation_start_timestamp_ns / 1_000_000_000
            ).isoformat()

        metadata = {
            "simulation_id": self.simulation_id,
            "simulation_start_timestamp": simulation_start_timestamp_iso,  # True baseline for marker calculations
            "start_timestamp": self.start_timestamp,  # First telemetry event (after warmup)
            "end_timestamp": self.end_timestamp,
            "duration_seconds": self.sim_end_time - self.sim_start_time if self.sim_end_time and self.sim_start_time is not None else 0,
            "telemetry": {
                "logs": {
                    "total_count": self.log_count,
                    "by_level": dict(self.log_levels)
                },
                "metrics": {
                    "total_count": self.metric_count,
                    "by_type": dict(self.metric_types)
                },
                "traces": {
                    "total_traces": len(self.unique_trace_ids),
                    "total_spans": self.span_count
                }
            },
            "incidents": self.incidents,
            "failure_injections": self.failure_injections
        }

        return metadata

    def save_metadata(self, file_path: str):
        """
        Save metadata to a JSON file.

        Args:
            file_path: Path to save the metadata file
        """
        with open(file_path, 'w') as f:
            json.dump(self.to_metadata(), f, indent=2)
