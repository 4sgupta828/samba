"""
Custom MetricReader for simulation-time-based metric collection.

This reader collects and exports metrics based on simulation time rather than
wall-clock time, ensuring proper histogram aggregation while maintaining fast
simulation execution.

Key insight: The OpenTelemetry SDK's MeterProvider already aggregates histogram
data internally. We just need to control WHEN we collect() from the SDK and export.

Standard flow:
1. App calls histogram.record(value) → SDK aggregates into internal buckets
2. MetricReader calls collect() on SDK → SDK returns aggregated data
3. MetricReader exports aggregated data

Our approach:
- Don't call collect() on every force_flush()
- Only call collect() when aggregation window has passed (simulation time)
- This gives us proper aggregation: 1000s of .record() calls → 1 export per window
"""
from opentelemetry.sdk.metrics.export import MetricReader, MetricExporter, AggregationTemporality, MetricExportResult


class SimulationTimeMetricReader(MetricReader):
    """
    Custom MetricReader that collects metrics based on simulation time intervals.

    This reader provides proper histogram aggregation by controlling the frequency
    of SDK metric collection based on simulation time rather than wall-clock time.
    """

    def __init__(
        self,
        exporter: MetricExporter,
        export_interval_sim_seconds: float = 10.0,
        use_delta_temporality: bool = True,
        warmup_period_seconds: float = 0.0
    ):
        """
        Initialize the simulation-time-based metric reader.

        Args:
            exporter: MetricExporter to send metrics to
            export_interval_sim_seconds: Interval between exports (simulation seconds)
            use_delta_temporality: If True, use DELTA temporality (recommended for RCA).
                                   If False, use CUMULATIVE temporality.
            warmup_period_seconds: Duration of warmup period to skip (default: 0.0)
        """
        # Configure preferred temporality
        # For DELTA temporality, we want counters and histograms to reset after each collection
        # For CUMULATIVE, they accumulate from the start
        # Note: Gauges (ObservableGauge) are always CUMULATIVE by nature
        from opentelemetry.sdk.metrics._internal.instrument import Counter, Histogram, ObservableGauge, UpDownCounter

        if use_delta_temporality:
            # DELTA: Reset after each collection (recommended for RCA)
            preferred_temporality = {
                Counter: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.CUMULATIVE,  # UpDownCounter should be cumulative
                Histogram: AggregationTemporality.DELTA,
                ObservableGauge: AggregationTemporality.CUMULATIVE,  # Gauges are always cumulative
            }
        else:
            # CUMULATIVE: Accumulate from start
            preferred_temporality = {
                Counter: AggregationTemporality.CUMULATIVE,
                UpDownCounter: AggregationTemporality.CUMULATIVE,
                Histogram: AggregationTemporality.CUMULATIVE,
                ObservableGauge: AggregationTemporality.CUMULATIVE,
            }

        super().__init__(
            preferred_temporality=preferred_temporality
        )

        self._exporter = exporter
        self._export_interval = export_interval_sim_seconds
        self._use_delta_temporality = use_delta_temporality
        self._warmup_period = warmup_period_seconds

        # Track last export time
        self._last_export_sim_time = 0.0
        self._current_sim_time = 0.0

        # Flag to control whether we should actually collect/export
        self._should_collect = False

        # Flag to track if we've cleared warmup metrics
        self._warmup_cleared = False

    def notify_sim_time(self, sim_time: float) -> bool:
        """
        Notify the reader of current simulation time.

        This should be called from the simulation's periodic flush process.
        Returns True if metrics should be collected/exported.

        Args:
            sim_time: Current simulation time in seconds

        Returns:
            bool: True if collection should happen, False otherwise
        """
        self._current_sim_time = sim_time

        # Skip metrics during warmup period
        if sim_time < self._warmup_period:
            self._should_collect = False
            return False

        # If we just finished warmup, clear accumulated warmup metrics without exporting
        if not self._warmup_cleared:
            self._warmup_cleared = True
            self._should_collect = True  # Trigger collection to clear warmup data
            self._last_export_sim_time = sim_time  # Set baseline for future exports
            # Note: _receive_metrics will detect this is the warmup clear and skip export
            return True

        # Check if we've passed the export interval
        if sim_time - self._last_export_sim_time >= self._export_interval:
            self._should_collect = True
            self._last_export_sim_time = sim_time
            return True

        self._should_collect = False
        return False

    def _receive_metrics(
        self,
        metrics_data,
        timeout_millis: float = 10_000,
        **kwargs,
    ) -> None:
        """
        Called by the SDK when collect() is invoked.

        We only export if the aggregation window has passed.
        After the SDK aggregates, we inject sim.time into each data point
        for timestamp calculation and visualization.
        """
        # Only export if we're past the aggregation window
        if not self._should_collect:
            # Skip export - we're still within the aggregation window
            return

        # Calculate adjusted sim time
        adjusted_sim_time = self._current_sim_time - self._warmup_period

        # If this is the first collection right after warmup (adjusted_sim_time == 0),
        # skip exporting to discard accumulated warmup metrics
        # Note: For DELTA temporality, this collection clears the SDK's internal state
        if adjusted_sim_time == 0.0:
            # Discard warmup metrics - they've been collected but won't be exported
            # This clears the SDK's internal counters/histograms (for DELTA mode)
            return

        # Inject current simulation time into all data points AFTER SDK aggregation
        # This ensures:
        # 1. SDK aggregates properly (sim.time not in labels)
        # 2. Exporter gets sim.time for timestamp conversion
        # 3. Dash UI gets sim.time for visualization
        for resource_metric in metrics_data.resource_metrics:
            for scope_metric in resource_metric.scope_metrics:
                for metric in scope_metric.metrics:
                    if hasattr(metric.data, 'data_points'):
                        for point in metric.data.data_points:
                            # Inject sim.time as an attribute
                            if hasattr(point, 'attributes'):
                                # Point attributes might be immutable, so create a new dict
                                if point.attributes is None:
                                    point.attributes = {}
                                # Add adjusted sim.time to the attributes (restarts from 0 after warmup)
                                point.attributes['sim.time'] = adjusted_sim_time

        # Export the aggregated metrics with sim.time attached
        result = self._exporter.export(metrics_data, timeout_millis=timeout_millis)
        if result != MetricExportResult.SUCCESS:
            print(f"Warning: Metric export failed with result: {result}")

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        """
        Force collection and export of metrics.

        This is called from the SDK's MeterProvider.force_flush() method.
        We check if we should collect based on _should_collect flag.
        """
        if not self._should_collect:
            # Not time to collect yet, skip
            return True

        # Trigger collection from the SDK
        # This calls collect() on all registered instruments, which aggregates data
        # and then calls our _receive_metrics() method
        try:
            # Call our base class collect method
            self.collect(timeout_millis=timeout_millis)
            # Flush the exporter
            self._exporter.force_flush(timeout_millis=timeout_millis)
            # Reset the flag after successful collection
            self._should_collect = False
            return True
        except Exception as e:
            print(f"Error during force_flush: {e}")
            import traceback
            traceback.print_exc()
            return False

    def shutdown(self, timeout_millis: float = 30_000) -> bool:
        """Shutdown the reader and exporter."""
        # Force final collection
        self._should_collect = True
        self.collect(timeout_millis=timeout_millis)
        return self._exporter.shutdown(timeout_millis=timeout_millis)

    def set_export_interval(self, interval_seconds: float) -> None:
        """
        Dynamically adjust the export interval.

        This provides the "knob" for controlling metric granularity.

        Args:
            interval_seconds: New export interval in simulation seconds
        """
        self._export_interval = interval_seconds
        print(f"Metric export interval set to {interval_seconds} simulation seconds")

    def get_export_interval(self) -> float:
        """Get current export interval."""
        return self._export_interval
