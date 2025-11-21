"""
Custom file-based exporters for OpenTelemetry data.
These exporters write telemetry data to separate files for logs, metrics, and traces.
"""
import json
import os
from typing import Sequence
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, AggregationTemporality
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.metrics.export import MetricsData
from typing import Optional, Callable


def convert_sim_time_to_timestamp_ns(
    sim_time_seconds: float,
    simulation_start_timestamp_ns: int,
    timestamp_transform_fn: Optional[Callable[[int], int]] = None
) -> int:
    """
    Convert simulation time to Unix timestamp in nanoseconds.

    Args:
        sim_time_seconds: Simulation time in seconds (can be 0.0)
        simulation_start_timestamp_ns: Base timestamp (in nanoseconds) for simulation start
        timestamp_transform_fn: Optional function to transform the final timestamp
            (e.g., to map to a different time window)

    Returns:
        Unix timestamp in nanoseconds
    """
    # Convert simulation seconds to nanoseconds and add to base timestamp
    timestamp_ns = simulation_start_timestamp_ns + int(sim_time_seconds * 1_000_000_000)

    # Apply optional transformation
    if timestamp_transform_fn:
        timestamp_ns = timestamp_transform_fn(timestamp_ns)

    return timestamp_ns


class FileSpanExporter(SpanExporter):
    """Exports spans to a JSONL file."""

    def __init__(self, file_path: str, collector=None, simulation_start_timestamp_ns=None, warmup_period_seconds=0, timestamp_transform_fn=None):
        """
        Initialize the file span exporter.

        Args:
            file_path: Path to the output file
            collector: Optional telemetry collector for tracking counts
            simulation_start_timestamp_ns: Optional base timestamp (in nanoseconds) for simulation start
            warmup_period_seconds: Skip traces from first N seconds of simulation (default: 0)
            timestamp_transform_fn: Optional function to transform timestamps (e.g., to map to a different time window)
        """
        self.file_path = file_path
        self.collector = collector
        self.warmup_period_seconds = warmup_period_seconds
        # Store simulation start timestamp for converting simulation time to realistic timestamps
        # If not provided, use current time as base
        if simulation_start_timestamp_ns is None:
            from datetime import datetime
            simulation_start_timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.timestamp_transform_fn = timestamp_transform_fn
        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Create/clear the file
        with open(file_path, 'w') as f:
            pass

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to file with realistic timestamps based on simulation time."""
        try:
            with open(self.file_path, 'a') as f:
                for span in spans:
                    # Check if span has simulation time attributes
                    # If so, convert them to realistic timestamps
                    attrs = dict(span.attributes) if span.attributes else {}

                    # Extract simulation times if present (set by components)
                    sim_start_time = attrs.get('sim.start_time')
                    sim_end_time = attrs.get('sim.end_time')

                    # Skip spans within warmup period
                    if sim_start_time is not None and sim_start_time < self.warmup_period_seconds:
                        continue

                    # Convert simulation times to realistic nanosecond timestamps
                    if sim_start_time is not None:
                        start_time_ns = convert_sim_time_to_timestamp_ns(
                            sim_start_time,
                            self.simulation_start_timestamp_ns,
                            self.timestamp_transform_fn
                        )
                    else:
                        # Fallback to actual span time if no simulation time
                        start_time_ns = span.start_time

                    if sim_end_time is not None:
                        end_time_ns = convert_sim_time_to_timestamp_ns(
                            sim_end_time,
                            self.simulation_start_timestamp_ns,
                            self.timestamp_transform_fn
                        )
                    else:
                        end_time_ns = span.end_time

                    # Keep simulation times for debugging but calculate actual duration
                    # Don't remove sim times - they're useful for debugging
                    # attrs.pop('sim.start_time', None)
                    # attrs.pop('sim.end_time', None)

                    span_dict = {
                        "name": span.name,
                        "context": {
                            "trace_id": format(span.context.trace_id, '032x'),
                            "span_id": format(span.context.span_id, '016x'),
                            "trace_state": str(span.context.trace_state)
                        },
                        "kind": str(span.kind),
                        "parent_id": format(span.parent.span_id, '016x') if span.parent else None,
                        "start_time": start_time_ns,
                        "end_time": end_time_ns,
                        "status": {
                            "status_code": str(span.status.status_code)
                        },
                        "attributes": attrs,
                        "events": [
                            {
                                "name": event.name,
                                "timestamp": event.timestamp,
                                "attributes": dict(event.attributes) if event.attributes else {}
                            }
                            for event in span.events
                        ] if span.events else []
                    }
                    f.write(json.dumps(span_dict) + '\n')

                    # Track in collector
                    if self.collector:
                        self.collector.record_trace(span_dict)
                        # Track timestamp range for metadata (use both start and end times)
                        self.collector.update_timestamp_range(start_time_ns)
                        self.collector.update_timestamp_range(end_time_ns)

            return SpanExportResult.SUCCESS
        except Exception as e:
            print(f"Error exporting spans: {e}")
            return SpanExportResult.FAILURE

    def shutdown(self, timeout_millis: float = 30_000, timeout: float = None, **kwargs) -> bool:
        """Shutdown the exporter."""
        return True


class FileMetricExporter(MetricExporter):
    """Exports metrics to a JSONL file."""

    def __init__(self, file_path: str, collector=None, preferred_temporality=None, preferred_aggregation=None):
        """
        Initialize the file metric exporter.

        Args:
            file_path: Path to the output file
            collector: Optional telemetry collector for tracking counts
            preferred_temporality: Optional preferred temporality
            preferred_aggregation: Optional preferred aggregation
        """
        super().__init__(
            preferred_temporality=preferred_temporality,
            preferred_aggregation=preferred_aggregation
        )
        self.file_path = file_path
        self.collector = collector
        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Create/clear the file
        with open(file_path, 'w') as f:
            pass

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs) -> MetricExportResult:
        """Export metrics to file."""
        try:
            with open(self.file_path, 'a') as f:
                for resource_metric in metrics_data.resource_metrics:
                    for scope_metric in resource_metric.scope_metrics:
                        for metric in scope_metric.metrics:
                            metric_dict = {
                                "name": metric.name,
                                "description": metric.description,
                                "unit": metric.unit,
                                "data": self._serialize_metric_data(metric.data)
                            }
                            f.write(json.dumps(metric_dict) + '\n')

                            # Track in collector
                            if self.collector:
                                self.collector.record_metric(metric_dict)

            return MetricExportResult.SUCCESS
        except Exception as e:
            print(f"Error exporting metrics: {e}")
            return MetricExportResult.FAILURE

    def _serialize_metric_data(self, data):
        """Serialize metric data to JSON-compatible format."""
        data_points = []

        for point in data.data_points:
            point_dict = {
                "attributes": dict(point.attributes) if hasattr(point, 'attributes') and point.attributes else {},
                "time_unix_nano": point.time_unix_nano
            }

            # Add start_time for cumulative metrics
            if hasattr(point, 'start_time_unix_nano'):
                point_dict["start_time_unix_nano"] = point.start_time_unix_nano

            # Handle different metric types
            if hasattr(point, 'value'):
                point_dict["value"] = point.value

            if hasattr(point, 'count'):
                point_dict["count"] = point.count
                point_dict["sum"] = point.sum if hasattr(point, 'sum') else None

            if hasattr(point, 'bucket_counts'):
                point_dict["bucket_counts"] = list(point.bucket_counts)
                point_dict["explicit_bounds"] = list(point.explicit_bounds)
                if hasattr(point, 'min'):
                    point_dict["min"] = point.min
                if hasattr(point, 'max'):
                    point_dict["max"] = point.max

            data_points.append(point_dict)

        return {"data_points": data_points}

    def shutdown(self, timeout_millis: float = 30_000, timeout: float = None, **kwargs) -> bool:
        """Shutdown the exporter."""
        return True

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        """Force flush any pending metrics."""
        return True

    def shutdown(self, timeout_millis: float = 30_000, timeout: float = None, **kwargs) -> bool:
        """Shutdown the exporter."""
        return True


class FileLogHandler:
    """Custom log handler that writes logs to a JSONL file."""

    def __init__(self, file_path: str, collector=None, simulation_start_timestamp_ns=None, warmup_period_seconds=0, timestamp_transform_fn=None):
        """
        Initialize the file log handler.

        Args:
            file_path: Path to the output file
            collector: Optional telemetry collector for tracking counts
            simulation_start_timestamp_ns: Optional base timestamp (in nanoseconds) for simulation start
            warmup_period_seconds: Skip logs from first N seconds of simulation (default: 0)
            timestamp_transform_fn: Optional function to transform timestamps (e.g., to map to a different time window)
        """
        self.file_path = file_path
        self.collector = collector
        self.warmup_period_seconds = warmup_period_seconds
        # Store simulation start timestamp for converting simulation time to realistic timestamps
        # If not provided, use current time as base
        if simulation_start_timestamp_ns is None:
            from datetime import datetime
            simulation_start_timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.timestamp_transform_fn = timestamp_transform_fn
        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Create/clear the file
        with open(file_path, 'w') as f:
            pass
        self.file = open(file_path, 'a')

    def emit(self, record):
        """Emit a log record to the file."""
        try:
            # Get simulation time from record (can be 0.0)
            sim_time = record.get("timestamp")

            # Skip logs within warmup period
            if sim_time is not None and sim_time < self.warmup_period_seconds:
                return

            # Convert simulation time to Unix nanoseconds if available
            if sim_time is not None:  # Explicitly check for None to handle 0.0 correctly
                timestamp_ns = convert_sim_time_to_timestamp_ns(
                    sim_time,
                    self.simulation_start_timestamp_ns,
                    self.timestamp_transform_fn
                )
            else:
                # Fallback: use current time if no simulation time provided
                from datetime import datetime
                timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)

            log_dict = {
                "timestamp": timestamp_ns,
                "level": record.get("level", "INFO"),
                "logger": record.get("logger", ""),
                "message": record.get("message", ""),
                "attributes": {}
            }

            # Add component context if available
            if "component_id" in record:
                log_dict["attributes"]["component.id"] = record["component_id"]

            # Add any extra fields
            for key, value in record.items():
                if key not in ["timestamp", "level", "logger", "message", "component_id"]:
                    log_dict["attributes"][key] = value

            self.file.write(json.dumps(log_dict) + '\n')
            self.file.flush()

            # Track in collector
            if self.collector:
                self.collector.record_log(log_dict)
                # Track timestamp range for metadata
                self.collector.update_timestamp_range(timestamp_ns)

        except Exception as e:
            print(f"Error writing log: {e}")

    def close(self):
        """Close the file handler."""
        if self.file:
            self.file.close()


class SummarizedJsonMetricExporter(MetricExporter):
    """
    Exports metrics to a condensed JSONL format optimized for AI/ML training datasets.
    
    This exporter transforms verbose OpenTelemetry histogram data into a compact format
    that preserves essential statistical information while dramatically reducing file size.
    Each line represents a single metric point with:
    - For gauges/counters: direct value
    - For histograms: statistical summary (count, sum, percentiles)
    """

    def __init__(self, file_path: str, collector=None, preferred_temporality=None, preferred_aggregation=None, simulation_start_timestamp_ns=None, warmup_period_seconds=0, timestamp_transform_fn=None):
        """
        Initialize the summarized metric exporter.

        Args:
            file_path: Path to the output file
            collector: Optional telemetry collector for tracking counts
            preferred_temporality: Optional preferred temporality
            preferred_aggregation: Optional preferred aggregation
            simulation_start_timestamp_ns: Optional base timestamp (in nanoseconds) for simulation start
            warmup_period_seconds: Skip metrics from first N seconds of simulation (default: 0)
            timestamp_transform_fn: Optional function to transform timestamps (e.g., to map to a different time window)
        """
        super().__init__(
            preferred_temporality=preferred_temporality,
            preferred_aggregation=preferred_aggregation
        )
        self.file_path = file_path
        self.collector = collector
        self.warmup_period_seconds = warmup_period_seconds
        # Store simulation start timestamp for converting simulation time to realistic timestamps
        # If not provided, use current time as base
        if simulation_start_timestamp_ns is None:
            from datetime import datetime
            simulation_start_timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.timestamp_transform_fn = timestamp_transform_fn
        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Create/clear the file
        with open(file_path, 'w') as f:
            pass

        # Track exported points to prevent duplicates
        self.exported_points = set()
        # Track last cleanup time to prevent unbounded memory growth
        self.last_cleanup_time = 0
        self.cleanup_interval = 300  # Cleanup every 5 minutes (wall-clock time)

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs) -> MetricExportResult:
        """Export metrics to condensed JSONL format."""
        try:
            # Periodic cleanup of deduplication set to prevent unbounded memory growth
            import time
            current_time = time.time()
            if current_time - self.last_cleanup_time > self.cleanup_interval:
                # Keep only points from last 10 minutes (600 seconds)
                # Points older than this are unlikely to be re-exported
                cutoff_ts = int((current_time - 600) * 1_000_000_000)
                # Filter out old entries by parsing timestamp from dedup key
                self.exported_points = {
                    k for k in self.exported_points
                    if int(k.split('_')[0]) > cutoff_ts
                }
                self.last_cleanup_time = current_time

            with open(self.file_path, 'a') as f:
                for resource_metric in metrics_data.resource_metrics:
                    for scope_metric in resource_metric.scope_metrics:
                        for metric in scope_metric.metrics:
                            # Process each data point as a separate line
                            if hasattr(metric.data, 'data_points'):
                                for point in metric.data.data_points:
                                    summarized_point = self._create_summarized_point(metric, point)
                                    if summarized_point:
                                        # Create a unique key for deduplication
                                        dedup_key = f"{summarized_point['ts']}_{summarized_point['name']}_{str(sorted(summarized_point['labels'].items()))}"

                                        # Only export if we haven't seen this exact point before
                                        if dedup_key not in self.exported_points:
                                            self.exported_points.add(dedup_key)
                                            f.write(json.dumps(summarized_point) + '\n')

                                            # Track in collector
                                            if self.collector:
                                                self.collector.record_metric(summarized_point)
                                                # Track timestamp range for metadata
                                                self.collector.update_timestamp_range(summarized_point['ts'])

            return MetricExportResult.SUCCESS
        except Exception as e:
            print(f"Error exporting summarized metrics: {e}")
            import traceback
            traceback.print_exc()
            return MetricExportResult.FAILURE

    def _create_summarized_point(self, metric, point):
        """
        Create a summarized metric point in the optimal format.

        Returns a single JSON object representing one metric reading at one point in time.
        Returns None if the point is within the warmup period and should be skipped.
        """
        # Convert simulation time to realistic timestamp
        # Use sim.time from attributes instead of time_unix_nano
        # because time_unix_nano is the same for all metrics when force_flush() is called
        sim_time = None
        if hasattr(point, 'attributes') and point.attributes:
            sim_time = point.attributes.get('sim.time')

        # Skip metrics within warmup period
        if sim_time is not None and sim_time < self.warmup_period_seconds:
            return None

        if sim_time is not None:
            # Convert simulation time to Unix nanoseconds
            timestamp_ns = convert_sim_time_to_timestamp_ns(
                sim_time,
                self.simulation_start_timestamp_ns,
                self.timestamp_transform_fn
            )
        elif hasattr(point, 'time_unix_nano') and point.time_unix_nano:
            # Fallback to point's timestamp if sim.time not available
            timestamp_ns = point.time_unix_nano
        else:
            # Final fallback to current time
            from datetime import datetime
            timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)

        # Extract attributes as labels
        labels = {}
        if hasattr(point, 'attributes') and point.attributes:
            labels = dict(point.attributes)

        # Handle different metric types
        if hasattr(metric.data, 'data_points'):
            data_point = point
            
            # Check if this is a histogram (has bucket_counts)
            if hasattr(data_point, 'bucket_counts') and data_point.bucket_counts:
                # This is a histogram - create statistical summary
                summary = self._calculate_histogram_summary(data_point)
                return {
                    "ts": timestamp_ns,
                    "name": metric.name,
                    "labels": labels,
                    "summary": summary
                }
            else:
                # This is a gauge or counter - use direct value
                value = getattr(data_point, 'value', getattr(data_point, 'sum', 0))
                return {
                    "ts": timestamp_ns,
                    "name": metric.name,
                    "labels": labels,
                    "value": value
                }
        
        return None

    def _calculate_histogram_summary(self, data_point):
        """Calculate statistical summary from histogram data point."""
        bucket_counts = data_point.bucket_counts
        explicit_bounds = data_point.explicit_bounds
        
        # Calculate basic statistics
        count = sum(bucket_counts)
        sum_value = getattr(data_point, 'sum', 0)
        min_value = getattr(data_point, 'min', 0)
        max_value = getattr(data_point, 'max', 0)
        
        # Calculate percentiles from bucket data
        p50, p90, p99 = self._calculate_percentiles_from_buckets(bucket_counts, explicit_bounds)
        
        return {
            "count": count,
            "sum": sum_value,
            "p50": p50,
            "p90": p90,
            "p99": p99,
            "max": max_value
        }

    def _calculate_percentiles_from_buckets(self, bucket_counts, explicit_bounds):
        """
        Calculate percentiles from histogram bucket data using linear interpolation.

        This provides more accurate percentile estimates by interpolating within buckets
        rather than just returning bucket boundaries.
        """
        total_count = sum(bucket_counts)
        if total_count == 0:
            return 0, 0, 0

        # Calculate the target rank for each percentile
        p50_rank = total_count * 0.50
        p90_rank = total_count * 0.90
        p99_rank = total_count * 0.99

        # Calculate cumulative counts and interpolate percentiles
        cumulative = 0
        percentiles = {}

        for i, count in enumerate(bucket_counts):
            if count == 0:
                continue

            prev_cumulative = cumulative
            cumulative += count

            # Determine bucket boundaries
            bucket_lower = explicit_bounds[i-1] if i > 0 else 0
            bucket_upper = explicit_bounds[i] if i < len(explicit_bounds) else explicit_bounds[-1]

            # Check if each percentile falls within this bucket and interpolate
            if 'p50' not in percentiles and cumulative >= p50_rank:
                percentiles['p50'] = self._interpolate_percentile(
                    p50_rank, prev_cumulative, cumulative, bucket_lower, bucket_upper
                )

            if 'p90' not in percentiles and cumulative >= p90_rank:
                percentiles['p90'] = self._interpolate_percentile(
                    p90_rank, prev_cumulative, cumulative, bucket_lower, bucket_upper
                )

            if 'p99' not in percentiles and cumulative >= p99_rank:
                percentiles['p99'] = self._interpolate_percentile(
                    p99_rank, prev_cumulative, cumulative, bucket_lower, bucket_upper
                )

        return percentiles.get('p50', 0), percentiles.get('p90', 0), percentiles.get('p99', 0)

    def _interpolate_percentile(self, target_rank, prev_cumulative, cumulative, bucket_lower, bucket_upper):
        """
        Linearly interpolate a percentile value within a bucket.

        Args:
            target_rank: The target rank (count * percentile)
            prev_cumulative: Cumulative count before this bucket
            cumulative: Cumulative count including this bucket
            bucket_lower: Lower bound of the bucket
            bucket_upper: Upper bound of the bucket

        Returns:
            Interpolated percentile value
        """
        # How far through the bucket is the target rank?
        bucket_count = cumulative - prev_cumulative
        rank_within_bucket = target_rank - prev_cumulative
        fraction = rank_within_bucket / bucket_count if bucket_count > 0 else 0

        # Linear interpolation within the bucket
        return bucket_lower + fraction * (bucket_upper - bucket_lower)

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        """Force flush any pending metrics."""
        return True

    def shutdown(self, timeout_millis: float = 30_000, timeout: float = None, **kwargs) -> bool:
        """Shutdown the exporter."""
        return True
