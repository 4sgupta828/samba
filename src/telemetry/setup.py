"""
Telemetry setup and configuration using OpenTelemetry.
"""
import os
from typing import Callable, Dict, Tuple, Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ParentBased
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter, AggregationTemporality, InMemoryMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

from src.telemetry.exporters import FileSpanExporter, FileMetricExporter, SummarizedJsonMetricExporter, FileLogHandler
from src.telemetry.collector import TelemetryCollector
from src.telemetry.simulation_metric_reader import SimulationTimeMetricReader


def reset_opentelemetry_globals():
    """
    Reset OpenTelemetry global providers to allow fresh setup for new episodes.

    This is necessary when running multiple episodes in the same Python process,
    as OpenTelemetry's design uses global singletons that normally cannot be reset.

    WARNING: This uses internal OpenTelemetry APIs and should only be used in
    controlled environments like training data generation.
    """
    # Reset trace globals
    try:
        import opentelemetry.trace as trace_module
        from opentelemetry.util._once import Once

        # Reset the provider variable
        if hasattr(trace_module, '_TRACER_PROVIDER'):
            trace_module._TRACER_PROVIDER = None

        # Reset the "set once" guard that prevents re-setting the provider
        if hasattr(trace_module, '_TRACER_PROVIDER_SET_ONCE'):
            trace_module._TRACER_PROVIDER_SET_ONCE = Once()

        # Reset the proxy provider's reference
        if hasattr(trace_module, '_PROXY_TRACER_PROVIDER'):
            if hasattr(trace_module._PROXY_TRACER_PROVIDER, '_real_provider'):
                trace_module._PROXY_TRACER_PROVIDER._real_provider = None

        print("Telemetry: Reset trace provider globals")
    except Exception as e:
        print(f"Warning: Could not fully reset trace provider: {e}")
        import traceback
        traceback.print_exc()

    # Reset metrics globals
    try:
        import opentelemetry.metrics as metrics_module
        from opentelemetry.util._once import Once

        # Reset the provider variable
        if hasattr(metrics_module, '_METER_PROVIDER'):
            metrics_module._METER_PROVIDER = None

        # Reset the "set once" guard that prevents re-setting the provider
        if hasattr(metrics_module, '_internal'):
            if hasattr(metrics_module._internal, '_METER_PROVIDER_SET_ONCE'):
                metrics_module._internal._METER_PROVIDER_SET_ONCE = Once()

        # Reset the proxy provider's reference
        if hasattr(metrics_module, '_internal'):
            if hasattr(metrics_module._internal, '_PROXY_METER_PROVIDER'):
                if hasattr(metrics_module._internal._PROXY_METER_PROVIDER, '_real_provider'):
                    metrics_module._internal._PROXY_METER_PROVIDER._real_provider = None

        print("Telemetry: Reset meter provider globals")
    except Exception as e:
        print(f"Warning: Could not fully reset meter provider: {e}")
        import traceback
        traceback.print_exc()

    # Reset component log handler
    try:
        from src.components.base_component import EnrichedComponent
        EnrichedComponent._log_handler = None
        print("Telemetry: Reset component log handler")
    except Exception as e:
        print(f"Warning: Could not reset component log handler: {e}")


def setup_telemetry(config: Dict, output_dir: str = None, simulation_id: str = None, simulation_start_timestamp_ns: int = None, timestamp_transform_fn: Optional[Callable[[int], int]] = None) -> Tuple[Callable, TelemetryCollector, FileLogHandler, 'MeterProvider', Optional['SimulationTimeMetricReader']]:
    """
    Initializes OpenTelemetry SDK providers and exporters based on configuration.
    Returns a tuple of (shutdown function, telemetry collector, log handler, meter provider, metric reader).

    Args:
        config: Telemetry configuration dictionary
        output_dir: Directory to write telemetry files (if using file exporter)
        simulation_id: Unique identifier for this simulation run
        simulation_start_timestamp_ns: Base timestamp (in nanoseconds) for simulation start
        timestamp_transform_fn: Optional function to transform timestamps (e.g., to map to a different time window)

    Returns:
        Tuple of (shutdown_function, telemetry_collector, log_handler, meter_provider, metric_reader)
        The metric_reader is the SimulationTimeMetricReader instance (or None for other exporters),
        which can be used to control metric collection timing.
    """
    exporter_type = config.get("exporter", "console")
    endpoint = config.get("endpoint", "http://localhost:4317")

    # Use a resource to identify all telemetry from this simulator
    resource = Resource(attributes={
        "service.name": "cloud-infra-simulator"
    })

    # Create telemetry collector if using file exporter
    collector = None
    log_handler = None

    # Use provided simulation start timestamp or generate one if not provided
    if simulation_start_timestamp_ns is None:
        from datetime import datetime
        simulation_start_timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)

    if exporter_type == "file" and output_dir:
        if not simulation_id:
            simulation_id = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        collector = TelemetryCollector(simulation_id, simulation_start_timestamp_ns)
        print(f"Telemetry: Using File Exporter (output_dir: {output_dir})")

    # --- TRACE PROVIDER SETUP ---
    # Configure trace sampling to reduce volume
    # Use 1% sampling rate for normal operations
    # ParentBased sampler ensures that if a parent span is sampled, all children are also sampled
    sampler = ParentBased(root=TraceIdRatioBased(0.01))
    trace_provider = TracerProvider(resource=resource, sampler=sampler)
    print(f"Telemetry: Trace sampling rate set to 1% (0.01) for volume reduction")

    if exporter_type == "otlp":
        print(f"Telemetry: Using OTLP Exporter for traces (endpoint: {endpoint})")
        otlp_trace_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        trace_processor = BatchSpanProcessor(otlp_trace_exporter)
    elif exporter_type == "file" and output_dir:
        traces_file = os.path.join(output_dir, "traces.jsonl")
        # Get warmup period for filtering
        warmup_period = config.get("warmup_period", 0)
        if warmup_period > 0:
            print(f"Telemetry: Skipping first {warmup_period}s warmup period in traces export")
        file_trace_exporter = FileSpanExporter(traces_file, collector=collector,
                                               simulation_start_timestamp_ns=simulation_start_timestamp_ns,
                                               warmup_period_seconds=warmup_period,
                                               timestamp_transform_fn=timestamp_transform_fn)
        # Use SimpleSpanProcessor instead of BatchSpanProcessor to ensure immediate export
        # and prevent context bleeding between requests
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        trace_processor = SimpleSpanProcessor(file_trace_exporter)
    else:
        print("Telemetry: Using Console Exporter for traces.")
        trace_processor = BatchSpanProcessor(ConsoleSpanExporter())

    trace_provider.add_span_processor(trace_processor)
    trace.set_tracer_provider(trace_provider)

    # --- METRICS PROVIDER SETUP ---
    # Get metric configuration parameters
    metric_export_interval = config.get("metric_export_interval", 10)  # Default: 10 simulation seconds
    use_delta_temporality = config.get("use_delta_temporality", True)  # Default: DELTA (production best practice)

    # Track the metric reader for returning (needed by simulation to control timing)
    simulation_metric_reader = None

    if exporter_type == "otlp":
        print(f"Telemetry: Using OTLP Exporter for metrics (endpoint: {endpoint})")
        otlp_metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
        metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter)
    elif exporter_type == "file" and output_dir:
        metrics_file = os.path.join(output_dir, "metrics.jsonl")

        # Configure temporality for the exporter
        # DELTA temporality means counters export the change since last collection
        # CUMULATIVE means counters export the total since start
        if use_delta_temporality:
            exporter_temporality = {
                # Use DELTA for all instrument types
                # This will be passed to the exporter's preferred_temporality
            }
        else:
            exporter_temporality = None  # Use SDK default (CUMULATIVE)

        # Check if we should use the new summarized format
        use_summarized_format = config.get("use_summarized_format", True)
        warmup_period = config.get("warmup_period", 0)

        if use_summarized_format:
            print("Telemetry: Using SummarizedJsonMetricExporter for optimal AI/ML dataset format")
            if warmup_period > 0:
                print(f"Telemetry: Skipping first {warmup_period}s warmup period in metrics export")
            file_metric_exporter = SummarizedJsonMetricExporter(
                metrics_file,
                collector=collector,
                preferred_temporality=exporter_temporality,
                simulation_start_timestamp_ns=simulation_start_timestamp_ns,
                warmup_period_seconds=warmup_period,
                timestamp_transform_fn=timestamp_transform_fn
            )
        else:
            print("Telemetry: Using FileMetricExporter for full OpenTelemetry format")
            file_metric_exporter = FileMetricExporter(
                metrics_file,
                collector=collector,
                preferred_temporality=exporter_temporality,
                simulation_start_timestamp_ns=simulation_start_timestamp_ns
            )

        # Use custom SimulationTimeMetricReader for proper aggregation based on simulation time
        print(f"Telemetry: Using SimulationTimeMetricReader with {metric_export_interval}s interval")
        print(f"Telemetry: Temporality mode: {'DELTA' if use_delta_temporality else 'CUMULATIVE'}")
        if warmup_period > 0:
            print(f"Telemetry: Skipping first {warmup_period}s warmup period in metrics collection")

        simulation_metric_reader = SimulationTimeMetricReader(
            exporter=file_metric_exporter,
            export_interval_sim_seconds=metric_export_interval,
            use_delta_temporality=use_delta_temporality,
            warmup_period_seconds=warmup_period
        )
        metric_reader = simulation_metric_reader
    else:
        print("Telemetry: Using Console Exporter for metrics.")
        console_metric_exporter = ConsoleMetricExporter()
        metric_reader = PeriodicExportingMetricReader(console_metric_exporter, export_interval_millis=5000)

    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- LOG HANDLER SETUP ---
    if exporter_type == "file" and output_dir:
        logs_file = os.path.join(output_dir, "logs.jsonl")
        # Get warmup period for filtering
        warmup_period = config.get("warmup_period", 0)
        if warmup_period > 0:
            print(f"Telemetry: Skipping first {warmup_period}s warmup period in logs export")
        log_handler = FileLogHandler(logs_file, collector=collector,
                                     simulation_start_timestamp_ns=simulation_start_timestamp_ns,
                                     warmup_period_seconds=warmup_period,
                                     timestamp_transform_fn=timestamp_transform_fn)

    print("Telemetry setup complete.")

    def shutdown_telemetry():
        """Function to gracefully flush telemetry data and close file handlers.

        This flushes all pending data and closes file handlers but does NOT shutdown
        the providers. The providers will be reset via reset_opentelemetry_globals()
        in multi-episode scenarios to allow fresh setup for the next episode.
        """
        print("Telemetry: Flushing data...")

        # Flush all pending telemetry data (this is crucial to ensure buffered data is exported)
        trace_provider.force_flush(timeout_millis=10000)
        meter_provider.force_flush(timeout_millis=10000)

        # Close file handlers to ensure logs are written
        if log_handler:
            log_handler.close()

        print("Telemetry: Flush complete.")

    return shutdown_telemetry, collector, log_handler, meter_provider, simulation_metric_reader