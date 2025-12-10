"""
Defines the abstract base class for all simulated infrastructure components,
including enriched data structures for holding detailed configuration.
"""
import simpy, json, random
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from opentelemetry import trace, metrics
from opentelemetry.trace import Status, StatusCode
from src.core.simulation_config import get_simulation_config

# --- Configuration Dataclasses (from Phase 1, no changes) ---

@dataclass
class ResourceLimits:
    cpu_request: Optional[str] = None
    cpu_limit: Optional[str] = None
    memory_request: Optional[str] = None
    memory_limit: Optional[str] = None

@dataclass
class HealthCheck:
    protocol: str = 'HTTP'
    port: int = 80
    path: str = '/'
    interval: int = 30
    timeout: int = 5
    healthy_threshold: int = 2
    unhealthy_threshold: int = 2

@dataclass
class AutoScalingPolicy:
    min_size: int = 1
    max_size: int = 1
    desired_capacity: int = 1
    cooldown: int = 300
    target_metric: str = 'cpu_utilization'
    target_value: float = 70.0    

# --- NEW: Multi-Dimensional State ---
@dataclass
class MultiDimensionalState:
    """Tracks the various aspects of a component's state."""
    operational: str = "INITIALIZING"  # e.g., RUNNING, DEGRADED, DOWN
    cpu_utilization: float = 0.0       # as a percentage
    memory_usage_mb: float = 0.0
    # Other state dimensions like disk_io, network_throughput can be added here

class SimulatedComponent:
    """Base class for all infrastructure components in the simulation."""

    # Log level configuration
    LOG_LEVEL_PRIORITY = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}

    # Shared network layer (singleton)
    _network_layer = None

    def __init__(self, env: simpy.Environment, component_id: str, component_type: str):
        # Load centralized configuration
        config = get_simulation_config()

        self.env = env
        self.id = component_id
        self.type = component_type
        # UPDATED: Use the new state object
        self.state = MultiDimensionalState()
        self.iac_config: Dict[str, Any] = {}
        self.interrupt_event = self.env.event()
        self.tracer = trace.get_tracer(self.type, "0.1.0")
        # Use component ID for meter to ensure each component has unique observable gauges
        self.meter = metrics.get_meter(self.id, "0.1.0")
        self.connections: Dict[str, Any] = {}
        self._should_trace = False  # Track if current request should be traced
        self._parent_trace_context = None  # Temporary storage for parent trace context within a single request

        # Telemetry configuration from centralized config
        self.MIN_LOG_LEVEL = config.telemetry.min_log_level
        self.TRACE_SAMPLING_RATE = config.telemetry.trace_sampling_rate
        self.TRACE_SAMPLING_RATE_ERRORS = config.telemetry.trace_sampling_rate_errors
        self.log_throttle_window = config.telemetry.log_throttle_window_seconds
        self.log_throttle_cleanup_threshold = config.telemetry.log_throttle_cleanup_threshold_seconds

        # NEW: Base resource capacities (can be overridden by IaC)
        self.cpu_capacity_cores: float = 1.0
        self.memory_capacity_mb: float = 1024.0

        # --- NEW: Attributes for Failure Injection ---
        self.injected_latency_ms: float = config.fault_injection.default_injected_latency_ms
        self.cpu_cost_multiplier: float = 1.0  # Multiplier for CPU required per request (for cpu_saturation fault)
        self.forced_error_rate: float = config.fault_injection.default_forced_error_rate

        # --- NEW: Component-level error metrics ---
        self.error_counter = self.meter.create_counter(
            "component.errors.total",
            description="Total number of errors encountered by this component"
        )

        # NEW: Attribute to track the deployed version
        self.version: str = "initial_build"

        print(f"Component '{self.id}' ({self.type}) created.")

    def _start_span(self, span_name: str, parent_span_context=None):
        """
        Create a span with simulation time tracking.

        Args:
            span_name: Name of the span
            parent_span_context: Optional parent span context for creating child spans

        Returns a context manager that must be used with 'with' statement.

        SIMPLE APPROACH: Don't use OTel's automatic context propagation (it doesn't work
        with SimPy generators). Instead, explicitly pass parent context when needed.
        """
        from contextlib import contextmanager

        @contextmanager
        def span_wrapper():
            sim_start = self.env.now

            # Create span - if parent provided, create as child, otherwise create new trace
            if parent_span_context:
                span = self.tracer.start_span(span_name, context=parent_span_context)
            else:
                # Create a brand new root span (new trace)
                span = self.tracer.start_span(span_name)

            # Set simulation start time and component info
            span.set_attribute('sim.start_time', sim_start)
            span.set_attribute('component.id', self.id)
            span.set_attribute('component.type', self.type)

            try:
                yield span
                # If we reach here without exception, operation was successful
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                # Record the error status and exception details
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise  # Re-raise the exception
            finally:
                # Set simulation end time
                sim_end = self.env.now
                span.set_attribute('sim.end_time', sim_end)

                # Calculate duration
                duration_ms = (sim_end - sim_start) * 1000
                span.set_attribute('duration.ms', duration_ms)

                # End span
                span.end()

        return span_wrapper()

    def run(self):
        """
        The main process generator for the component, run by SimPy.
        This default implementation models a component starting up and then
        idling, while listening for interruptions.
        """
        self.state.operational = "RUNNING"
        print(f"[{self.env.now:.2f}s] {self.id}: State -> RUNNING (Version: {self.version})")
        # The main run loop now just ensures the component is "alive"
        # Most logic will be in specific handler methods.
        while True:
            # Check for forced failure state
            if self.state.operational != "RUNNING":
                self._emit_log("WARN", f"Component is in a non-running state: {self.state.operational}. Halting operations.")
                yield self.env.event() # Wait indefinitely for an interrupt to change state

            try:
                # Wait for a long time or until an interrupt occurs.
                yield self.env.timeout(3600)
            except simpy.Interrupt as i:
                print(f"[{self.env.now:.2f}s] {self.id}: Interrupted by '{i.cause}'")
                # NEW: If terminated for deployment, exit gracefully
                if i.cause == "TERMINATED_FOR_DEPLOYMENT":
                    self.state.operational = "TERMINATED"
                    self._emit_log("INFO", "Component terminated for deployment.")
                    return  # This stops the SimPy process for this component instance
    
    def _record_error(self, error_type: str = "generic", additional_attrs: Dict = None):
        """
        Record an error metric for this component.

        Args:
            error_type: Type of error (e.g., "timeout", "connection_failed", "query_error")
            additional_attrs: Additional attributes to include with the metric
        """
        attrs = {
            "component.id": self.id,
            "component.type": self.type,
            "error.type": error_type,
            "sim.time": self.env.now,
        }
        if additional_attrs:
            attrs.update(additional_attrs)

        self.error_counter.add(1, attrs)

    def _should_transient_error_occur(self, error_type: str) -> bool:
        """
        Determine if a transient error should occur based on error configuration.

        Args:
            error_type: Type of error (e.g., 'connection_failure', 'timeout', 'lock_timeout')

        Returns:
            True if error should occur, False otherwise
        """
        from src.core.error_config import get_error_simulator

        simulator = get_error_simulator()

        # Calculate memory utilization ratio
        memory_utilization = self.state.memory_usage_mb / self.memory_capacity_mb if self.memory_capacity_mb > 0 else 0.0

        # Get error_rate_multiplier from ComputeAgent if available (deployment-triggered errors)
        error_rate_multiplier = getattr(self, 'error_rate_multiplier', 1.0)

        return simulator.should_error_occur(
            component_type=self.type,
            error_type=error_type,
            cpu_utilization=self.state.cpu_utilization,
            memory_utilization=memory_utilization,
            injected_latency_ms=self.injected_latency_ms,
            error_rate_multiplier=error_rate_multiplier
        )

    def _raise_transient_error(self, error_type: str):
        """
        Raise a transient error with realistic error message.

        Args:
            error_type: Type of error to raise
        """
        from src.core.error_config import get_error_simulator

        simulator = get_error_simulator()
        error_message = simulator.get_error_message(self.type, error_type)

        # Log and record the error
        self._emit_log("ERROR", error_message)
        self._record_error(error_type)

        # Raise the exception
        raise Exception(error_message)

    def _network_call(self, target_component_id: str, data_size_bytes: int = 1024, target_component_type: str = None):
        """
        Simulate a network call to another component through the network layer.

        This centralizes all network error simulation in the NetworkLink component.

        Args:
            target_component_id: ID of target component
            data_size_bytes: Size of data being transmitted
            target_component_type: Type of target component (e.g., "SqlDatabase", "InMemoryCache")
                                  for component-specific network latency. If None, uses default.

        Yields:
            SimPy timeout for network transmission

        Raises:
            Exception: On network failures (connection, timeout, etc.)
        """
        # Initialize network layer if not already done
        if SimulatedComponent._network_layer is None:
            from src.components.network import NetworkLink
            SimulatedComponent._network_layer = NetworkLink(self.env, "global_network")

        # Perform network transmission through the network layer
        yield from SimulatedComponent._network_layer._transmit_internal(
            data_size_bytes,
            span=None,
            target_component_type=target_component_type
        )

    def _emit_log(self, level: str, message: str, attributes: Dict = None):
        """Formats and prints a structured log with throttling."""
        # Filter logs based on minimum log level
        if self.LOG_LEVEL_PRIORITY.get(level, 0) < self.LOG_LEVEL_PRIORITY.get(self.MIN_LOG_LEVEL, 1):
            return  # Skip logs below minimum level

        # Automatically record error metrics for ERROR and FATAL logs
        if level in ["ERROR", "FATAL"]:
            # Extract error type from message if possible
            error_type = "generic"
            message_lower = message.lower()
            if "timeout" in message_lower:
                error_type = "timeout"
            elif "connection" in message_lower:
                error_type = "connection"
            elif "query" in message_lower or "database" in message_lower:
                error_type = "database"
            elif "memory" in message_lower:
                error_type = "memory"
            elif "cpu" in message_lower:
                error_type = "cpu"

            self._record_error(error_type, attributes)

        # Log throttling: prevent spam from repeated operations
        # IMPORTANT: Never throttle ERROR or CRITICAL logs - these indicate problems
        if level not in ["ERROR", "CRITICAL"]:
            if not hasattr(self, '_log_throttle'):
                self._log_throttle = {}

            # Create a throttle key based on message content
            throttle_key = f"{level}:{message[:50]}"  # Use first 50 chars as key

            # Check if we've logged this recently
            current_time = self.env.now
            if throttle_key in self._log_throttle:
                last_log_time = self._log_throttle[throttle_key]
                if current_time - last_log_time < self.log_throttle_window:
                    return  # Skip this log

            # Update throttle time
            self._log_throttle[throttle_key] = current_time

            # Clean old throttle entries
            self._log_throttle = {k: v for k, v in self._log_throttle.items()
                                 if current_time - v < self.log_throttle_cleanup_threshold}

        log_record = {
            "timestamp": self.env.now,
            "level": level,
            "message": message,
            "component.id": self.id,
            "component.type": self.type,
            **(attributes or {})
        }

        # Use file log handler if available
        if hasattr(EnrichedComponent, '_log_handler') and EnrichedComponent._log_handler:
            EnrichedComponent._log_handler.emit(log_record)
        else:
            # Fallback to console output
            print(f"LOG: {json.dumps(log_record)}")

    @classmethod
    def from_hcl(cls, env: simpy.Environment, component_id: str, hcl_config: Dict):
        instance = cls(env, component_id)
        instance.iac_config = hcl_config
        instance._apply_hcl_config()
        return instance
        
    def _apply_hcl_config(self):
        """Placeholder method for subclasses to apply their specific HCL configs."""
        pass

    def apply_infrastructure_change(
        self,
        parameter: str,
        delta: float,
        duration: float,
        progression: str = "linear",
        start_time: float = None
    ):
        """
        Apply a gradual behavioral change to this component.

        Args:
            parameter: The parameter to change (e.g., 'latency_ms', 'error_rate', 'throughput_multiplier')
            delta: The change amount (positive for increase, negative for decrease)
            duration: Time over which to apply the change (in seconds)
            progression: How to progress the change ('linear', 'exponential', 'step')
            start_time: The simulation time when this change starts
        """
        if start_time is None:
            start_time = self.env.now

        # Start a background process to apply the change gradually
        self.env.process(self._apply_gradual_change(
            parameter=parameter,
            delta=delta,
            duration=duration,
            progression=progression,
            start_time=start_time
        ))

    def _apply_gradual_change(
        self,
        parameter: str,
        delta: float,
        duration: float,
        progression: str,
        start_time: float
    ):
        """
        Background process that applies the change gradually over time.
        """
        # Map parameter names to actual attributes
        param_mapping = {
            'latency_ms': 'injected_latency_ms',
            'error_rate': 'forced_error_rate',
            'cpu_cost_multiplier': 'cpu_cost_multiplier',
            # Add more mappings as needed
        }

        actual_param = param_mapping.get(parameter, parameter)

        if not hasattr(self, actual_param):
            print(f"[{self.id}] WARNING: Component does not have parameter '{actual_param}'")
            return

        initial_value = getattr(self, actual_param)
        target_value = initial_value + delta

        print(f"[{self.id}] Starting infrastructure change: {parameter} "
              f"from {initial_value:.2f} to {target_value:.2f} over {duration:.1f}s ({progression})")

        if duration <= 0:
            # Instant change
            setattr(self, actual_param, target_value)
            print(f"[{self.id}] Applied instant change: {parameter} = {target_value:.2f}")
            return

        # Apply change gradually
        update_interval = 1.0  # Update every simulation second
        num_updates = int(duration / update_interval)

        for i in range(num_updates + 1):
            elapsed = i * update_interval
            if elapsed > duration:
                elapsed = duration

            # Calculate progress based on progression type
            if progression == "linear":
                progress = elapsed / duration
            elif progression == "exponential":
                # Exponential curve: slower at start, faster at end (for increases)
                # or faster at start, slower at end (for decreases)
                if delta > 0:
                    progress = (2 ** (elapsed / duration) - 1)  # 0 to 1 exponentially
                else:
                    progress = 1 - (2 ** (1 - elapsed / duration) - 1)
            elif progression == "step":
                # Step function: changes at specific intervals
                step_size = duration / 4  # 4 steps
                progress = min(1.0, int(elapsed / step_size) * 0.25)
            else:
                progress = elapsed / duration  # Default to linear

            progress = min(1.0, max(0.0, progress))  # Clamp to [0, 1]
            current_value = initial_value + (delta * progress)

            setattr(self, actual_param, current_value)

            if i < num_updates:
                yield self.env.timeout(update_interval)

        # Ensure we reach the exact target value
        setattr(self, actual_param, target_value)
        print(f"[{self.id}] Completed infrastructure change: {parameter} = {target_value:.2f}")

    def __repr__(self):
        return f"{self.type}(id='{self.id}', state='{self.state.operational}')"

class EnrichedComponent(SimulatedComponent):
    """An enhanced base component with more detailed configuration attributes."""

    # Class-level log handler for file output
    _log_handler = None

    @classmethod
    def set_log_handler(cls, log_handler):
        """Set the global log handler for all components."""
        cls._log_handler = log_handler

    def __init__(self, env: simpy.Environment, component_id: str, component_type: str):
        super().__init__(env, component_id, component_type)
        self.cost_per_hour: float = 0.0
        self.region: str = "us-east-1"
        self.az: str = "us-east-1a"
        self.tags: Dict[str, str] = {}
        self.network_rules: Dict[str, Any] = {}
        self.resource_limits: Optional[ResourceLimits] = None
        self.health_check_config: Optional[HealthCheck] = None
        self.scaling_policy: Optional[AutoScalingPolicy] = None