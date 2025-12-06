"""
Pod Component - Container instances that execute service logic.

A Pod is a container instance that:
- Belongs to a parent Service
- Optionally runs on a Compute Node (for resource contention scenarios)
- Executes the parent service's processing pipeline
- Handles all computation, I/O, and resource management
"""
from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.core.constants import get_profile_multiplier
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
from src.resilience.service_propagation_mixin import ServicePropagationMixin, DependencyFailureException
import simpy
import random


class Pod(EnrichedComponent, ServicePropagationMixin):
    """
    Pod represents a container instance that executes service logic.

    Renamed from ComputeAgent to match Kubernetes terminology.
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 parent_service=None, compute_node=None, semantic_profile=None):
        super().__init__(env, component_id, "Pod")

        # Initialize ServicePropagationMixin for fault propagation
        ServicePropagationMixin.__init__(self, env)

        # NEW: References to parent service and compute node
        self.parent_service = parent_service
        self.compute_node = compute_node

        # NEW: Semantic profile for resource behavior
        self.semantic_profile = semantic_profile or {}
        self.resource_profile = self.semantic_profile.get("profile", "standard")

        # Register this pod with the node if provided
        if self.compute_node:
            self.compute_node.register_pod(self)

        # Load centralized configuration
        config = get_simulation_config().compute

        # Initialize iac_config for capacity planner overrides
        self.iac_config = {}

        # Internal state for cumulative effects
        self.memory_capacity_mb = config.memory_capacity_mb
        self.restarts = 0
        # Deployment-triggered behavior support (non-dynamics attributes)
        self.critical_error_boost: float = 0.0  # Adds to probability of 5xx errors (0.0 = normal, 0.15 = +15%)

        # Client-side connection pool (like HikariCP, pgBouncer, etc.)
        # Each pod manages its own pool of DB connections
        if config.db_connection_pool_capacity > 0:
            self.db_connection_pool = simpy.Resource(env, capacity=config.db_connection_pool_capacity)
        else:
            self.db_connection_pool = None

        # Thread pool for request processing
        self.thread_pool_size = getattr(config, 'thread_pool_size', 50)
        self.thread_pool = simpy.Resource(env, capacity=self.thread_pool_size)

        # Track active request processes for crash interruption
        self.active_request_processes = set()

        # Track samples for time-averaged gauges (like production systems)
        self.cpu_samples = []
        self.memory_samples = []
        self.connection_pool_samples = []
        self.connection_queue_samples = []
        self.sample_window = get_simulation_config().defaults.sample_window_seconds

        # Initialize dynamics engine (always enabled - single source of truth)
        self.request_count = 0
        self.last_request_count = 0
        global_config = get_simulation_config()

        # Load dynamics configuration with sensible defaults
        dynamics_params = {}
        if hasattr(global_config, 'dynamics'):
            compute_dynamics_config = global_config.dynamics.get('components', {}).get('compute_agent', {})
            dynamics_params = compute_dynamics_config.get('config', {})

        # NEW: Adjust dynamics parameters based on resource profile
        # This configures the dynamics engine to model different resource characteristics
        cpu_min = dynamics_params.get('cpu_min', 10.0)
        memory_base = dynamics_params.get('memory_base', config.memory_base_mb)
        cpu_from_throughput_coef = dynamics_params.get('cpu_from_throughput_coef', 0.25)

        if self.resource_profile == "cpu_intensive":
            # CPU-intensive services have higher baseline CPU and more CPU per request
            cpu_min = max(cpu_min, 30.0)  # Higher baseline
            cpu_from_throughput_coef *= 1.5  # More CPU growth per request
        elif self.resource_profile == "io_intensive":
            # I/O-intensive services have higher memory baseline
            memory_base *= 1.3  # 30% higher memory baseline
        elif self.resource_profile == "latency_sensitive":
            # Latency-sensitive services keep CPU low for fast response
            cpu_min = min(cpu_min, 15.0)  # Lower baseline for fast response

        # Create dynamics configuration with profile-adjusted defaults
        dynamics_cfg = DynamicsConfig(
            latency_base=dynamics_params.get('latency_base', 50.0),
            cpu_min=cpu_min,
            cpu_from_throughput_coef=cpu_from_throughput_coef,
            cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 2.0),
            latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 70.0),
            latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 20.0),
            error_base=dynamics_params.get('error_base', 0.002),
            error_latency_threshold=dynamics_params.get('error_latency_threshold', 500.0),
            error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 85.0),
            noise_enabled=dynamics_params.get('noise_enabled', True),
            memory_base=memory_base,
            memory_per_request_mb=dynamics_params.get('memory_per_request_mb', 5.0),
        )
        self.dynamics = MetricsDynamicsEngine(config=dynamics_cfg)

        # OTel Metrics - using gauges like production systems (CloudWatch, Prometheus, Datadog)
        self.cpu_usage_metric = self.meter.create_observable_gauge(
            "container.cpu.utilization",
            callbacks=[self._report_cpu_utilization],
            unit="%",
            description="CPU utilization percentage (time-averaged)"
        )
        self.memory_usage_metric = self.meter.create_observable_gauge(
            "container.memory.usage_mb",
            callbacks=[self._report_memory_usage],
            unit="MB",
            description="Memory usage in megabytes (time-averaged)"
        )
        self.connection_pool_active = self.meter.create_observable_gauge(
            "connection_pool.connections.active",
            callbacks=[self._report_connection_pool_active],
            description="Active connections in client-side connection pool (time-averaged)"
        )
        self.connection_pool_queue_depth = self.meter.create_observable_gauge(
            "connection_pool.queue_depth",
            callbacks=[self._report_connection_pool_queue_depth],
            description="Number of requests waiting for a connection from pool (time-averaged)"
        )

        # Thread pool metrics
        self.thread_pool_active_metric = self.meter.create_observable_gauge(
            "thread_pool.threads.active",
            callbacks=[self._report_thread_pool_active],
            description="Active threads processing requests"
        )
        self.thread_pool_queue_metric = self.meter.create_observable_gauge(
            "thread_pool.queue.depth",
            callbacks=[self._report_thread_pool_queue],
            description="Number of requests queued waiting for thread"
        )

        # Request-level metrics will be initialized after parent_service is set
        # (See _initialize_request_metrics() method)
        self.request_counter = None
        self.request_duration = None
        self.request_errors = None
        self.dependency_requests = None
        self.dependency_duration = None
        self.dependency_errors = None

    def _initialize_request_metrics(self):
        """
        Initialize request-level metrics after parent_service is set.
        Must be called after parent_service is wired during topology setup.
        """
        if self.parent_service is None:
            # Cannot initialize without parent service
            return

        service_name = self.parent_service.service_name
        service_id = self.parent_service.id

        # Request-level metrics (use service.id namespace for stable identifiers)
        # IMPORTANT: Use service_id (component ID) in metric names, not service_name (semantic name)
        # This ensures UI can find metrics even when semantic overlay changes service names
        # These will be tagged with both service.name (human-readable) and service.id (stable ID)
        self.request_counter = self.meter.create_counter(
            f"service.{service_id}.requests",
            unit="1",
            description=f"Number of requests handled by pods of {service_name}"
        )
        self.request_duration = self.meter.create_histogram(
            f"service.{service_id}.duration",
            unit="ms",
            description=f"Request processing duration for {service_name}"
        )
        self.request_errors = self.meter.create_counter(
            f"service.{service_id}.errors",
            unit="1",
            description=f"Number of request errors in {service_name}"
        )

        # External dependency call metrics (from this pod's perspective as client)
        self.dependency_requests = self.meter.create_counter(
            f"service.{service_id}.dependency.requests",
            unit="1",
            description=f"Requests to external dependencies from {service_name}"
        )
        self.dependency_duration = self.meter.create_histogram(
            f"service.{service_id}.dependency.duration",
            unit="ms",
            description=f"External dependency call duration from {service_name}"
        )
        self.dependency_errors = self.meter.create_counter(
            f"service.{service_id}.dependency.errors",
            unit="1",
            description=f"External dependency call errors from {service_name}"
        )

        # Initialize propagation metrics (circuit breakers, retries, timeouts)
        # These use service_id as well for consistency
        self._initialize_propagation_metrics(service_id)

    def _reset_state_on_restart(self):
        """
        Reset ALL mutable state to simulate a fresh process start.

        This method is called at the start of each restart iteration to ensure
        no state leaks from the previous pod lifetime. Implements recommendations
        from STATE_PERSISTENCE_AUDIT.md

        Categories of state being reset:
        1. Resource pool state (HIGH PRIORITY)
        2. Dynamics engine state (MEDIUM PRIORITY)
        3. Counter state (MEDIUM PRIORITY)
        4. Circuit breaker state (HIGH PRIORITY)
        5. Metrics samples (MEDIUM PRIORITY)
        """
        # === Category 1: Resource Pool State (CRITICAL) ===
        # SimPy Resource has TWO lists that must both be cleared:
        # - queue: requests waiting for resource
        # - users: requests currently using resource
        # When a process crashes, ALL held resources are released by the OS

        # Clear thread pool
        self.thread_pool.queue.clear()
        self.thread_pool.users.clear()

        # Clear DB connection pool (if it exists)
        if self.db_connection_pool:
            self.db_connection_pool.queue.clear()
            self.db_connection_pool.users.clear()

        # === Category 2: Dynamics Engine State ===
        # Reset dynamics to baseline (simulates fresh process)
        self.dynamics.memory_percent = self.dynamics.config.memory_base
        self.dynamics.cpu_percent = self.dynamics.config.cpu_min
        self.dynamics.concurrent_requests = 0
        # Reset other dynamics state if needed
        if hasattr(self.dynamics, 'latency_ms'):
            self.dynamics.latency_ms = self.dynamics.config.latency_base
        if hasattr(self.dynamics, 'error_rate'):
            self.dynamics.error_rate = self.dynamics.config.error_base

        # === Category 3: Counter State ===
        # Process counters reset to 0 on restart (real-world behavior)
        self.request_count = 0
        self.last_request_count = 0

        # === Category 4: Circuit Breaker & Retry State (CRITICAL) ===
        # Circuit breakers are in-memory state, cleared on process restart
        # This matches Kubernetes behavior (Hystrix, Resilience4j reset on restart)
        if hasattr(self, '_circuit_breakers'):
            self._circuit_breakers.clear()
        if hasattr(self, '_retry_policies'):
            self._retry_policies.clear()

        # === Category 5: Metrics Samples ===
        # Monitoring agents lose samples when process dies
        # (Debatable, but included for correctness)
        self.cpu_samples.clear()
        self.memory_samples.clear()
        self.connection_pool_samples.clear()
        self.connection_queue_samples.clear()

        # === Category 6: Active Request Interruption ===
        # Interrupt in-flight requests (simulates SIGKILL behavior)
        for proc in list(self.active_request_processes):
            try:
                proc.interrupt("PodCrashed")
            except RuntimeError:
                pass
        self.active_request_processes.clear()

        # === State that correctly persists ===
        # - self.restarts (cumulative across lifetimes)
        # - self.version (deployment property)
        # - self.parent_service, self.compute_node (references)
        # - self.critical_error_boost (deployment-level property)

        self._emit_log("DEBUG", "State reset complete for fresh pod lifetime")

    def run(self):
        """Pod lifecycle with crash/restart loop and permanent termination support."""
        self.start_time = self.env.now  # Track when pod started

        # Start background processes ONCE (they run for entire pod lifecycle)
        self.env.process(self._sample_cpu_periodically())
        self.env.process(self._monitor_oom())
        self.env.process(self._update_dynamics_loop())

        # Start queue consumer if parent service has queue_in connection
        if self.parent_service and 'queue_in' in getattr(self.parent_service, 'connections', {}):
            self.env.process(self._consume_from_queue())

        while True:
            self.state.operational = "STARTING"
            self.restarts += 1

            # Comprehensive state reset (simulates process restart)
            self._reset_state_on_restart()

            self._emit_log("INFO", f"Starting (Restart #{self.restarts})...")

            config = get_simulation_config().compute
            startup_range = config.startup_time_range_seconds
            yield self.env.timeout(random.uniform(startup_range[0], startup_range[1]))  # Simulate startup time

            self.state.operational = "RUNNING"
            self._emit_log("INFO", f"Pod started successfully (Version: {self.version}).")

            # Store reference to current running process for interrupt
            self.running_process = self.env.active_process

            try:
                # Pod is now running until it's interrupted (e.g., by a crash)
                yield self.env.timeout(3600)  # Wait for a long time or interrupt
            except simpy.Interrupt as interrupt:
                if interrupt.cause == "OOMKilled":
                    self._emit_log("FATAL", "OOMKilled: Memory limit exceeded. Restarting...")
                    self.state.operational = "CRASHED"
                    # State will be reset by _reset_state_on_restart() at top of next loop iteration

                    # Longer CrashLoopBackOff delay for OOM (includes cleanup, restart policy backoff)
                    # Kubernetes-style exponential backoff
                    backoff_delay = min(config.startup_backoff_delay_base_seconds * (2 ** (self.restarts - 1)), config.startup_max_backoff_seconds)
                    jitter_range = config.startup_backoff_jitter_range_seconds
                    actual_delay = backoff_delay + random.uniform(jitter_range[0], jitter_range[1])  # Add jitter
                    self._emit_log("WARN", f"CrashLoopBackOff: waiting {actual_delay:.1f}s before restart #{self.restarts + 1}")
                    try:
                        yield self.env.timeout(actual_delay)
                    except simpy.Interrupt as backoff_interrupt:
                        # Handle interruption during backoff (e.g., deployment termination)
                        if backoff_interrupt.cause in ["TERMINATED_FOR_DEPLOYMENT", "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                            self.state.operational = "TERMINATED"
                            self._emit_log("INFO", f"Pod terminated: {backoff_interrupt.cause}")
                            return  # Exit the process permanently
                        else:
                            # Re-raise other interrupts
                            raise

                # Handle termination from the deployment controller or node OOMKiller
                elif interrupt.cause in ["TERMINATED_FOR_DEPLOYMENT", "TERMINATED_BY_OOMKILLER", "TERMINATED_BY_SCALE_DOWN"]:
                    self.state.operational = "TERMINATED"
                    self._emit_log("INFO", f"Pod terminated: {interrupt.cause}")

                    # Remove from node if attached
                    if self.compute_node and self in self.compute_node.pods:
                        self.compute_node.pods.remove(self)

                    return  # Exit the process permanently

                else:
                    self._emit_log("ERROR", f"Unhandled interrupt: {interrupt.cause}. Shutting down.")
                    self.state.operational = "DOWN"
                    return  # Exit the run loop
            finally:
                self.running_process = None

    def _consume_from_queue(self):
        """
        Background process that continuously consumes messages from parent service's queue_in.

        This is called automatically if the parent service has a queue_in connection.
        Messages are processed concurrently to simulate realistic queue consumer behavior.
        """
        if not self.parent_service:
            return

        queue = self.parent_service.connections.get('queue_in')
        if not queue:
            return

        self._emit_log("INFO", f"Starting queue consumer for {queue.id}")

        # Continuously pull messages and spawn concurrent processing tasks
        while self.state.operational != "TERMINATED":
            try:
                # Wait for a message from the queue
                msg = yield from queue.receive_message()

                self._emit_log("DEBUG", f"Received message {msg.id} from queue")

                # Spawn concurrent message processing (don't wait for completion)
                self.env.process(self._process_queue_message(msg, queue))

            except Exception as e:
                # Queue receive failed - log and retry after delay
                self._emit_log("WARN", f"Queue receive failed: {e}")
                yield self.env.timeout(1.0)  # Wait 1s before retrying

    def _process_queue_message(self, msg, queue):
        """
        Process a single queue message concurrently.
        This allows multiple messages to be in-flight simultaneously.
        """
        # Process the message by calling handle_request
        # Use a random request type from parent service's supported types
        if hasattr(self.parent_service, 'supported_request_types') and self.parent_service.supported_request_types:
            request_type = random.choice(self.parent_service.supported_request_types)
        else:
            request_type = "PROCESS"

        # Track total message processing time (including consumer slowdown)
        start_time = self.env.now

        try:
            # Apply consumer processing slowdown if injected on the queue
            if hasattr(queue, 'consumer_processing_latency_ms') and queue.consumer_processing_latency_ms > 0:
                slowdown_ms = queue.consumer_processing_latency_ms
                self._emit_log("DEBUG", f"Applying consumer slowdown: +{slowdown_ms}ms for message {msg.id}")
                yield self.env.timeout(slowdown_ms / 1000.0)

            # Process the message (executes pipeline)
            yield self.env.process(self.handle_request(request_type, should_trace=False))

            # Successfully processed - delete the message
            queue.delete_message(msg)
            self._emit_log("DEBUG", f"Successfully processed message {msg.id}")

            # Record total message processing duration (including consumer slowdown)
            latency_ms = (self.env.now - start_time) * 1000
            if self.request_counter and self.request_duration and self.parent_service:
                self.request_counter.add(1, {
                    "status": "success",
                    "request_type": request_type,
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name,
                    "service.id": self.parent_service.id
                })
                self.request_duration.record(latency_ms, {
                    "status": "success",
                    "request_type": request_type,
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name,
                    "service.id": self.parent_service.id
                })

        except Exception as e:
            # Processing failed - message will become visible again after timeout
            self._emit_log("ERROR", f"Failed to process message {msg.id}: {e}")

            # Record error metrics with total processing time
            latency_ms = (self.env.now - start_time) * 1000
            if self.request_counter and self.request_duration and self.request_errors and self.parent_service:
                self.request_counter.add(1, {
                    "status": "error",
                    "request_type": request_type,
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name,
                    "service.id": self.parent_service.id
                })
                self.request_duration.record(latency_ms, {
                    "status": "error",
                    "request_type": request_type,
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name,
                    "service.id": self.parent_service.id
                })
                self.request_errors.add(1, {
                    "error_type": str(type(e).__name__),
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name,
                    "service.id": self.parent_service.id
                })

            # Don't delete - let visibility timeout return it to queue for retry

    def _monitor_oom(self):
        """Background process that monitors for OOMKilled condition using dynamics engine."""
        config = get_simulation_config().compute
        while self.state.operational != "TERMINATED":
            yield self.env.timeout(config.oom_check_interval_seconds)

            # Check again after timeout in case we were terminated during the wait
            if self.state.operational == "TERMINATED":
                break

            # Check if we're currently running and memory exceeds capacity
            # Check node-level capacity first if attached to a node
            if self.state.operational == "RUNNING":
                current_memory = self.dynamics.get_memory()

                # Check pod-level memory
                if current_memory > self.memory_capacity_mb:
                    self._emit_log("WARN", f"OOMKilled condition detected: {current_memory:.1f}MB > {self.memory_capacity_mb}MB")
                    # Interrupt the running process
                    if hasattr(self, 'running_process') and self.running_process is not None:
                        self.running_process.interrupt("OOMKilled")

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second."""
        while self.state.operational != "TERMINATED":
            yield self.env.timeout(1.0)  # Update every simulation second

            # Check again after timeout in case we were terminated during the wait
            if self.state.operational == "TERMINATED":
                break

            # Check memory pressure for GC (always use dynamics - single source of truth)
            memory_mb = self.dynamics.get_memory()
            memory_capacity = self.iac_config.get('memory_capacity_mb', 512)
            memory_pct = memory_mb / memory_capacity

            # Trigger GC if memory >85%
            if memory_pct > 0.85:
                gc_pause_ms = random.uniform(100, 500)  # 100-500ms pause

                self._emit_log("WARN", f"GC triggered: memory={memory_mb:.0f}MB ({memory_pct*100:.1f}%)")

                # During GC: spike CPU, pause request processing
                old_cpu = self.dynamics.cpu_percent
                self.dynamics.cpu_percent = random.uniform(85, 100)

                yield self.env.timeout(gc_pause_ms / 1000.0)

                # After GC: reclaim memory (30% reclaim)
                self.dynamics.memory_percent *= 0.7
                self.dynamics.cpu_percent = old_cpu

            # Calculate throughput (requests per second)
            requests_delta = self.request_count - self.last_request_count
            self.last_request_count = self.request_count

            # Get current observations from SimPy resources
            active_connections = self.db_connection_pool.count if self.db_connection_pool else 0
            queue_depth = len(self.db_connection_pool.queue) if self.db_connection_pool else 0

            # Read actual thread pool usage from SimPy
            actual_threads_active = self.thread_pool.count  # Actual blocked threads
            actual_queue_depth = len(self.thread_pool.queue) if hasattr(self.thread_pool, 'queue') else 0

            # Pass thread pool size from actual SimPy resource
            self.dynamics.thread_pool_size = self.thread_pool.capacity

            # Override dynamics' calculated concurrent_requests with ACTUAL thread count
            self.dynamics.concurrent_requests = actual_threads_active

            # Update dynamics engine
            self.dynamics.update(
                dt=1.0,
                external_throughput=requests_delta,
                active_connections=active_connections,
                queue_depth=actual_queue_depth  # Use actual thread queue, not DB queue
            )

    def _sample_cpu_periodically(self):
        """Background process that samples CPU, memory, and connection pool metrics at regular intervals."""
        config = get_simulation_config().defaults
        while self.state.operational != "TERMINATED":
            yield self.env.timeout(config.cpu_sampling_interval_seconds)

            # Check again after timeout in case we were terminated during the wait
            if self.state.operational == "TERMINATED":
                break

            current_time = self.env.now

            # Sample CPU utilization from dynamics engine
            self.cpu_samples.append((current_time, self.dynamics.get_cpu_percent()))

            # Sample memory usage from dynamics engine
            current_memory = self.dynamics.get_memory()
            self.memory_samples.append((current_time, current_memory))

            # Sample connection pool metrics (if pool exists)
            if self.db_connection_pool:
                active_connections = self.db_connection_pool.count
                queue_depth = len(self.db_connection_pool.queue)
                self.connection_pool_samples.append((current_time, active_connections))
                self.connection_queue_samples.append((current_time, queue_depth))

            # Remove samples older than the window
            cutoff_time = current_time - self.sample_window
            self.cpu_samples = [(t, v) for t, v in self.cpu_samples if t > cutoff_time]
            self.memory_samples = [(t, v) for t, v in self.memory_samples if t > cutoff_time]
            self.connection_pool_samples = [(t, v) for t, v in self.connection_pool_samples if t > cutoff_time]
            self.connection_queue_samples = [(t, v) for t, v in self.connection_queue_samples if t > cutoff_time]

    def handle_request(self, request_type: str, should_trace: bool = False, parent_span_context=None):
        """
        Handle incoming request by executing parent service's processing pipeline.

        Args:
            request_type: Type of request to handle
            should_trace: Whether to create tracing spans for this request
            parent_span_context: Parent span context for distributed tracing
        """
        # Check if tracing is enabled for this request
        if should_trace and parent_span_context:
            # Create child span with parent context for distributed tracing
            with self._start_span(f"pod:process:{request_type}", parent_span_context=parent_span_context) as span:
                span.set_attribute("pod.id", self.id)
                if self.parent_service:
                    span.set_attribute("service.name", self.parent_service.service_name)
                if self.compute_node:
                    span.set_attribute("node.id", self.compute_node.id)
                yield from self._handle_request_internal(request_type, span)
        else:
            yield from self._handle_request_internal(request_type, None)

    def _handle_request_internal(self, request_type: str, span):
        """
        Internal request handling - executes parent service's processing pipeline.

        This is the core of the new architecture where all computation happens in the Pod.
        """
        # Track start time for latency measurement
        start_time = self.env.now

        # Track request count for dynamics
        self.request_count += 1

        # Check node-level resource availability if attached to a node
        if self.compute_node and not self.compute_node.can_accept_work():
            self._emit_log("WARN", "Node overloaded, request throttled")
            yield self.env.timeout(0.1)  # Throttling delay

        # Request thread from pool
        queue_start = self.env.now

        # Track this process for interruption (before acquiring thread)
        current_proc = self.env.active_process

        # FIX: Wrap the entire with block in try/finally to ensure cleanup happens
        # AFTER the with block's __exit__, preventing SimPy resource conflicts
        try:
            # Add to tracking set BEFORE acquiring thread so it gets interrupted even while queued
            self.active_request_processes.add(current_proc)

            with self.thread_pool.request() as req:
                yield req  # Wait for available thread

                queue_wait_time = (self.env.now - queue_start) * 1000  # Convert to ms

                # Add queue wait time to span if we waited
                if span and queue_wait_time > 0:
                    span.set_attribute("thread_pool.queue_wait_ms", queue_wait_time)

                # Apply CPU steal time penalty if on a contended node
                if self.compute_node:
                    contention_penalty_ms = self.compute_node.get_contention_penalty()
                    if contention_penalty_ms > 0:
                        self._emit_log("DEBUG", f"CPU Steal Time: {contention_penalty_ms:.2f}ms")
                        if span:
                            span.set_attribute("cpu_steal_time_ms", contention_penalty_ms)
                        yield self.env.timeout(contention_penalty_ms / 1000.0)

                self._emit_log("DEBUG", f"Processing request type: {request_type}")

                # Wrap processing in try/except to record metrics
                try:
                    # Check dynamics-based error before processing
                    if random.random() < self.dynamics.get_error_rate():
                        self._emit_log("ERROR", "Request failed due to dynamics-driven error")
                        if span:
                            span.set_attribute("error", True)
                            span.set_attribute("error.type", "dynamics_error")
                        raise Exception("Request processing failed: Service temporarily unavailable")

                    # Apply dynamics-based latency
                    base_latency = self.dynamics.get_latency() / 1000.0  # Convert ms to seconds

                    # NEW: Apply resource profile multipliers
                    # Note: We apply multipliers to latency and add temporary resource spikes
                    # but we do NOT permanently modify dynamics state (that would accumulate)
                    latency_multiplier = get_profile_multiplier(self.resource_profile)
                    service_latency = base_latency * latency_multiplier

                    if span:
                        span.set_attribute("resource.profile", self.resource_profile)
                        span.set_attribute("profile.latency_multiplier", latency_multiplier)

                    yield self.env.timeout(service_latency)

                    # Execute parent service's processing pipeline
                    if self.parent_service and hasattr(self.parent_service, 'processing_pipeline'):
                        yield from self._execute_processing_pipeline(request_type, span)
                    else:
                        # Fallback to legacy behavior if no pipeline defined
                        yield from self._execute_legacy_request_logic(request_type, span)

                    # Record success metrics (only if metrics are initialized)
                    latency_ms = (self.env.now - start_time) * 1000
                    if self.request_counter and self.request_duration and self.parent_service:
                        self.request_counter.add(1, {
                            "status": "success",
                            "request_type": request_type,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name,
                            "service.id": self.parent_service.id  # NEW: Add service ID for UI filtering
                        })
                        self.request_duration.record(latency_ms, {
                            "status": "success",
                            "request_type": request_type,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name,
                            "service.id": self.parent_service.id  # NEW: Add service ID for UI filtering
                        })

                except Exception as e:
                    # Record error metrics (only if metrics are initialized)
                    latency_ms = (self.env.now - start_time) * 1000
                    if self.request_counter and self.request_duration and self.request_errors and self.parent_service:
                        self.request_counter.add(1, {
                            "status": "error",
                            "request_type": request_type,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name,
                            "service.id": self.parent_service.id  # NEW: Add service ID for UI filtering
                        })
                        self.request_duration.record(latency_ms, {
                            "status": "error",
                            "request_type": request_type,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name,
                            "service.id": self.parent_service.id  # NEW: Add service ID for UI filtering
                        })
                        self.request_errors.add(1, {
                            "request_type": request_type,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name,
                            "service.id": self.parent_service.id  # NEW: Add service ID for UI filtering
                        })
                    raise  # Re-raise the exception
        finally:
            # Remove from tracking AFTER the with block's __exit__ completes
            # This prevents conflicts with SimPy's resource cleanup
            self.active_request_processes.discard(current_proc)

    def _execute_processing_pipeline(self, request_type: str, span):
        """
        Execute the parent service's processing pipeline.

        Pipeline steps are executed in order, but only if the required connections exist.

        Cache-aside pattern: cache_check sets a flag, db_query conditionally executes,
        and if cache missed, we populate cache after db_query.
        """
        pipeline = self.parent_service.processing_pipeline

        # Track cache state across pipeline steps
        cache_hit = False
        cache_key = None
        cache_connection = None

        for step in pipeline:
            step_type = step.get("type")
            probability = step.get("probability", 1.0)  # Default: always execute

            # Probabilistic execution
            if random.random() > probability:
                continue

            # Execute step based on type
            if step_type == "cache_check":
                if 'cache' in self.parent_service.connections:
                    # Returns (hit, key, cache_obj)
                    cache_hit, cache_key, cache_connection = yield from self._execute_cache_logic(step, span)

            elif step_type == "db_query":
                # Only query DB if cache missed or no cache available
                if 'database' in self.parent_service.connections:
                    # If we had a cache check and it was a hit, skip DB query
                    if cache_hit:
                        self._emit_log("DEBUG", "Skipping DB query due to cache hit")
                        continue

                    # Execute DB query
                    yield from self._execute_db_logic(step, span)

                    # If we had a cache miss, populate cache after successful DB query
                    if cache_key and cache_connection:
                        yield from self._populate_cache_after_db(cache_key, cache_connection, span)

            elif step_type == "service_calls":
                # Call dep_* connections (NEW: pass request_type for deterministic routing)
                yield from self._execute_service_calls(step, span, request_type=request_type)

            elif step_type == "external_calls":
                # Call ext_* connections
                yield from self._execute_external_calls(step, span)

            elif step_type == "queue_publish":
                if 'queue_out' in self.parent_service.connections:
                    yield from self._execute_queue_publish(step, span)

    def _execute_cache_logic(self, step, span):
        """
        Check cache and return status.

        Returns:
            tuple: (cache_hit: bool, cache_key: str|None, cache_obj: Cache|None)
        """
        cache = self.parent_service.connections.get('cache')
        if not cache:
            return (False, None, None)

        # Generate cache key from a larger key space to simulate realistic cache behavior
        # Using 10,000 possible keys ensures cache (max 1000 items) experiences evictions
        cache_key = f"{self.parent_service.service_name}:data:{random.randint(1, 10000)}"

        cache_start = self.env.now

        # Try cache lookup
        try:
            should_trace_cache = span is not None
            cache_span_ctx = None
            if should_trace_cache:
                from opentelemetry import trace
                cache_span_ctx = trace.set_span_in_context(span)

            # Try cache get
            cache_process = self.env.process(cache.get(cache_key, should_trace=should_trace_cache, parent_span_context=cache_span_ctx))
            cached_data = yield cache_process

            if cached_data:
                # Cache HIT - record success
                if span:
                    span.set_attribute("cache.hit", True)
                self._emit_log("DEBUG", f"Cache hit for key {cache_key}")

                # Record cache success metrics
                cache_latency_ms = (self.env.now - cache_start) * 1000
                if self.dependency_requests and self.dependency_duration and self.parent_service:
                    self.dependency_requests.add(1, {
                        "dependency_id": cache.id,
                        "dependency_name": "cache",
                        "status": "success",
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name,
                        "service.id": self.parent_service.id
                    })
                    self.dependency_duration.record(cache_latency_ms, {
                        "dependency_id": cache.id,
                        "dependency_name": "cache",
                        "status": "success",
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name,
                        "service.id": self.parent_service.id
                    })

                return (True, None, None)  # Cache hit - no need to track key

            else:
                # Cache MISS
                if span:
                    span.set_attribute("cache.hit", False)
                self._emit_log("DEBUG", f"Cache miss for key {cache_key}")

                # Record cache miss as success (operation succeeded, just no data)
                cache_latency_ms = (self.env.now - cache_start) * 1000
                if self.dependency_requests and self.dependency_duration and self.parent_service:
                    self.dependency_requests.add(1, {
                        "dependency_id": cache.id,
                        "dependency_name": "cache",
                        "status": "success",
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name,
                        "service.id": self.parent_service.id
                    })
                    self.dependency_duration.record(cache_latency_ms, {
                        "dependency_id": cache.id,
                        "dependency_name": "cache",
                        "status": "success",
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name,
                        "service.id": self.parent_service.id
                    })

                return (False, cache_key, cache)  # Cache miss - return key for later population

        except Exception as e:
            # Cache operation failed - treat as miss but log error
            self._emit_log("WARN", f"Cache operation failed: {e}, will use database")

            # Record cache error metrics
            cache_latency_ms = (self.env.now - cache_start) * 1000
            if self.dependency_requests and self.dependency_duration and self.dependency_errors and self.parent_service:
                self.dependency_requests.add(1, {
                    "dependency_id": cache.id,
                    "dependency_name": "cache",
                    "status": "error",
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name
                })
                self.dependency_duration.record(cache_latency_ms, {
                    "dependency_id": cache.id,
                    "dependency_name": "cache",
                    "status": "error",
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name
                })
                self.dependency_errors.add(1, {
                    "dependency_id": cache.id,
                    "dependency_name": "cache",
                    "component.id": self.id,
                    "service.name": self.parent_service.service_name
                })

            # Treat cache error as miss, but don't propagate error - DB will be tried
            if span:
                span.set_attribute("cache.hit", False)
                span.set_attribute("cache.error", True)

            # Return None for cache object so we don't try to populate it later
            return (False, None, None)

    def _populate_cache_after_db(self, cache_key, cache, span):
        """
        Populate cache after successful database query (best effort).

        Args:
            cache_key: The key to store in cache
            cache: The cache connection object
            span: OpenTelemetry span for tracing
        """
        try:
            should_trace_cache_set = span is not None
            cache_set_span_ctx = None
            if should_trace_cache_set:
                from opentelemetry import trace
                cache_set_span_ctx = trace.set_span_in_context(span)

            # Mock data - in real system this would be the DB result
            cache_value = f"data_for_{cache_key}"

            set_process = self.env.process(cache.set(cache_key, cache_value, should_trace=should_trace_cache_set, parent_span_context=cache_set_span_ctx))
            yield set_process
            self._emit_log("DEBUG", f"Populated cache key {cache_key} after DB query")
        except Exception as e:
            # Cache write failure is non-fatal - we already have data from DB
            self._emit_log("WARN", f"Cache population failed after DB query: {e} (non-fatal)")

    def _execute_db_logic(self, step, span):
        """Execute database query logic."""
        db = self.parent_service.connections.get('database')
        if not db:
            return

        # Check if this pod has a database connection pool configured
        if not self.db_connection_pool:
            return

        config = get_simulation_config().compute
        max_retries = config.db_max_retries

        dep_start = self.env.now
        # Acquire connection from client-side pool
        with self.db_connection_pool.request() as conn_req:
            yield conn_req  # Wait for an available connection

            # Check connection pool pressure
            pool_utilization = self.db_connection_pool.count / self.db_connection_pool.capacity
            if pool_utilization > 0.8:
                wait_time_ms = (pool_utilization - 0.8) * 5 * 100
                yield self.env.timeout(wait_time_ms / 1000.0)

                if span:
                    span.set_attribute("connection_pool.wait_time_ms", wait_time_ms)

            # Make the DB call with retries
            for attempt in range(max_retries):
                try:
                    should_trace_db = span is not None
                    db_span_ctx = None
                    if should_trace_db:
                        from opentelemetry import trace
                        db_span_ctx = trace.set_span_in_context(span)

                    yield self.env.process(db.handle_query(should_trace=should_trace_db, parent_span_context=db_span_ctx))

                    # Record success metrics
                    dep_latency_ms = (self.env.now - dep_start) * 1000
                    if self.dependency_requests and self.dependency_duration and self.parent_service:
                        self.dependency_requests.add(1, {
                            "dependency_id": db.id,
                            "dependency_name": "database",
                            "status": "success",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })
                        self.dependency_duration.record(dep_latency_ms, {
                            "dependency_id": db.id,
                            "dependency_name": "database",
                            "status": "success",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })

                    break  # Success
                except Exception as e:
                    self._emit_log("WARN", f"DB call failed (attempt {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        backoff_time = (2 ** attempt) * config.db_retry_backoff_base_seconds
                        yield self.env.timeout(backoff_time)
                    else:
                        # Record error metrics on final failure
                        dep_latency_ms = (self.env.now - dep_start) * 1000
                        if self.dependency_requests and self.dependency_duration and self.dependency_errors and self.parent_service:
                            self.dependency_requests.add(1, {
                                "dependency_id": db.id,
                                "dependency_name": "database",
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_duration.record(dep_latency_ms, {
                                "dependency_id": db.id,
                                "dependency_name": "database",
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_errors.add(1, {
                                "dependency_id": db.id,
                                "dependency_name": "database",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                        raise

    def _execute_service_calls(self, step, span, request_type=None):
        """Execute service-to-service calls with fault propagation (deterministic routing)."""
        # NEW: Get deterministic flow from semantic config if available
        semantic_config = getattr(self.parent_service, 'semantic_config', {})
        request_flows = semantic_config.get('request_flows', {})

        # If we have deterministic flows for this request type, use them
        if request_type and request_flows and request_type in request_flows:
            flow_map = request_flows[request_type]
            required_calls = flow_map.get(self.parent_service.id, [])

            # Deterministic: only call services that are in the flow
            for conn_name, conn_target in self.parent_service.connections.items():
                if conn_name.startswith('dep_') and conn_target.id in required_calls:
                    dep_start = self.env.now

                    # Prepare call function for propagation
                    def make_service_call():
                        should_trace_dep = span is not None
                        dep_span_ctx = None
                        if should_trace_dep:
                            from opentelemetry import trace
                            dep_span_ctx = trace.set_span_in_context(span)

                        # Use the same request type to maintain flow consistency
                        dep_request_type = request_type if request_type in getattr(conn_target, 'supported_request_types', []) else random.choice(getattr(conn_target, 'supported_request_types', ['GET']))

                        yield self.env.process(conn_target.handle_request(
                            dep_request_type,
                            should_trace=should_trace_dep,
                            parent_span_context=dep_span_ctx
                        ))

                    try:
                        # Use propagation logic (circuit breaker, retry, timeout, probabilistic propagation)
                        yield from self.call_dependency_with_propagation(
                            dep_name=conn_name,
                            dep_type='service',
                            call_func=make_service_call,
                            span=span
                        )

                        # Record success metrics
                        dep_latency_ms = (self.env.now - dep_start) * 1000
                        if self.dependency_requests and self.dependency_duration and self.parent_service:
                            self.dependency_requests.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "success",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_duration.record(dep_latency_ms, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "success",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })

                    except DependencyFailureException as e:
                        # Error propagated from dependency - fail this request too
                        dep_latency_ms = (self.env.now - dep_start) * 1000
                        if self.dependency_requests and self.dependency_duration and self.dependency_errors and self.parent_service:
                            self.dependency_requests.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_duration.record(dep_latency_ms, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_errors.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                        # Re-raise to propagate to caller
                        raise

        else:
            # Fallback to old probabilistic behavior if no semantic flows
            # Find all dep_* connections
            for conn_name, conn_target in self.parent_service.connections.items():
                if conn_name.startswith('dep_'):
                    dep_start = self.env.now

                    # Prepare call function for propagation
                    def make_service_call():
                        should_trace_dep = span is not None
                        dep_span_ctx = None
                        if should_trace_dep:
                            from opentelemetry import trace
                            dep_span_ctx = trace.set_span_in_context(span)

                        # Call downstream service
                        if hasattr(conn_target, 'supported_request_types') and conn_target.supported_request_types:
                            dep_request_type = random.choice(conn_target.supported_request_types)
                        else:
                            dep_request_type = "GET"

                        yield self.env.process(conn_target.handle_request(
                            dep_request_type,
                            should_trace=should_trace_dep,
                            parent_span_context=dep_span_ctx
                        ))

                    try:
                        # Use propagation logic (circuit breaker, retry, timeout, probabilistic propagation)
                        yield from self.call_dependency_with_propagation(
                            dep_name=conn_name,
                            dep_type='service',
                            call_func=make_service_call,
                            span=span
                        )

                        # Record success metrics
                        dep_latency_ms = (self.env.now - dep_start) * 1000
                        if self.dependency_requests and self.dependency_duration and self.parent_service:
                            self.dependency_requests.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "success",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_duration.record(dep_latency_ms, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "success",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })

                    except DependencyFailureException as e:
                        # Error propagated from dependency - fail this request too
                        dep_latency_ms = (self.env.now - dep_start) * 1000
                        if self.dependency_requests and self.dependency_duration and self.dependency_errors and self.parent_service:
                            self.dependency_requests.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_duration.record(dep_latency_ms, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "status": "error",
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                            self.dependency_errors.add(1, {
                                "dependency_id": conn_target.id,
                                "dependency_name": conn_name,
                                "component.id": self.id,
                                "service.name": self.parent_service.service_name
                            })
                        # Re-raise to propagate to caller
                        raise

    def _execute_external_calls(self, step, span):
        """Execute external service calls with fault propagation."""
        # Find all ext_* connections
        for conn_name, conn_target in self.parent_service.connections.items():
            if conn_name.startswith('ext_'):
                dep_start = self.env.now

                # Prepare call function for propagation
                def make_external_call():
                    should_trace_ext = span is not None
                    ext_span_ctx = None
                    if should_trace_ext:
                        from opentelemetry import trace
                        ext_span_ctx = trace.set_span_in_context(span)

                    # Call external service
                    ext_request_type = random.choice(['GET', 'POST'])
                    yield self.env.process(conn_target.handle_request(
                        ext_request_type,
                        should_trace=should_trace_ext,
                        parent_span_context=ext_span_ctx
                    ))

                try:
                    # Use propagation logic (circuit breaker, retry, timeout, probabilistic propagation)
                    yield from self.call_dependency_with_propagation(
                        dep_name=conn_name,
                        dep_type='external',
                        call_func=make_external_call,
                        span=span
                    )

                    # Record success metrics (only if metrics are initialized)
                    dep_latency_ms = (self.env.now - dep_start) * 1000
                    if self.dependency_requests and self.dependency_duration and self.parent_service:
                        self.dependency_requests.add(1, {
                            "dependency_id": conn_target.id,
                            "dependency_name": conn_name,
                            "status": "success",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })
                        self.dependency_duration.record(dep_latency_ms, {
                            "dependency_id": conn_target.id,
                            "dependency_name": conn_name,
                            "status": "success",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })

                except DependencyFailureException as e:
                    # Error propagated from dependency - fail this request too
                    dep_latency_ms = (self.env.now - dep_start) * 1000
                    if self.dependency_requests and self.dependency_duration and self.dependency_errors and self.parent_service:
                        self.dependency_requests.add(1, {
                            "dependency_id": conn_target.id,
                            "dependency_name": conn_name,
                            "status": "error",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })
                        self.dependency_duration.record(dep_latency_ms, {
                            "dependency_id": conn_target.id,
                            "dependency_name": conn_name,
                            "status": "error",
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })
                        self.dependency_errors.add(1, {
                            "dependency_id": conn_target.id,
                            "dependency_name": conn_name,
                            "component.id": self.id,
                            "service.name": self.parent_service.service_name
                        })
                    # Re-raise to propagate to caller
                    raise

    def _execute_queue_publish(self, step, span):
        """Execute queue message publishing to all connected queues."""
        queue_out = self.parent_service.connections.get('queue_out')
        if not queue_out:
            return

        # Support both single queue (backward compat) and multiple queues
        queues = queue_out if isinstance(queue_out, list) else [queue_out]

        # Publish to all connected queues
        for queue in queues:
            try:
                message_data = f"message_from_{self.parent_service.service_name}_{self.env.now}"
                yield queue.send_message(message_data)  # send_message returns an event, not a generator

                if span:
                    span.add_event("message_published", {"queue": queue.id})
            except Exception as e:
                self._emit_log("WARN", f"Queue publish failed to {queue.id}: {e}")

    def _execute_legacy_request_logic(self, request_type: str, span):
        """
        Legacy request handling for backward compatibility.

        This is used when no processing pipeline is defined.
        """
        # Calculate memory pressure effects
        current_memory = self.dynamics.get_memory()
        memory_pressure_delay = self._calculate_memory_pressure_delay(current_memory)

        if memory_pressure_delay > 0:
            if memory_pressure_delay > 0.1:
                self._emit_log("INFO", f"Memory pressure delay: {memory_pressure_delay*1000:.1f}ms")
            yield self.env.timeout(memory_pressure_delay)

        # Default processing work
        config = get_simulation_config().compute
        work_time = random.gauss(config.request_default_time_mean_seconds, config.request_default_time_stdev_seconds)
        yield self.env.timeout(work_time)

    def _calculate_memory_pressure_delay(self, current_memory_mb: float) -> float:
        """Calculate additional delay due to memory pressure (GC pauses, thrashing)."""
        config = get_simulation_config().compute
        thresholds = config.memory_pressure_thresholds_mb

        if current_memory_mb < thresholds[0]:
            return 0.0
        elif current_memory_mb < thresholds[1]:
            # Minor GC pressure
            pressure_factor = (current_memory_mb - thresholds[0]) / (thresholds[1] - thresholds[0])
            delay_range = config.memory_pressure_delays_minor_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor
        elif current_memory_mb < thresholds[2]:
            # Moderate GC pressure
            pressure_factor = (current_memory_mb - thresholds[1]) / (thresholds[2] - thresholds[1])
            delay_range = config.memory_pressure_delays_moderate_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor
        else:
            # Severe GC pressure
            pressure_factor = min((current_memory_mb - thresholds[2]) / 100, 1.0)
            delay_range = config.memory_pressure_delays_severe_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor

    def _report_cpu_utilization(self, options):
        """Callback for CPU utilization gauge - includes node.id tag if attached to a node."""
        from opentelemetry.metrics import Observation

        # Don't emit metrics if pod is terminated
        if self.state.operational == "TERMINATED":
            return

        avg_cpu = self.dynamics.get_cpu_percent()

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }

        # Add service and node tags
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name
        if self.compute_node:
            attributes["node.id"] = self.compute_node.id

        yield Observation(avg_cpu, attributes)

    def _report_memory_usage(self, options):
        """Callback for memory usage gauge - includes node.id tag if attached to a node."""
        from opentelemetry.metrics import Observation

        # Don't emit metrics if pod is terminated
        if self.state.operational == "TERMINATED":
            return

        avg_memory = self.dynamics.get_memory()
        self.state.memory_usage_mb = avg_memory

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }

        # Add service and node tags
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name
        if self.compute_node:
            attributes["node.id"] = self.compute_node.id

        yield Observation(avg_memory, attributes)

    def _report_connection_pool_active(self, options):
        """Callback for connection pool active connections gauge."""
        from opentelemetry.metrics import Observation

        if self.connection_pool_samples:
            avg_active = sum(v for _, v in self.connection_pool_samples) / len(self.connection_pool_samples)
        else:
            avg_active = self.db_connection_pool.count if self.db_connection_pool else 0

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name

        yield Observation(avg_active, attributes)

    def _report_connection_pool_queue_depth(self, options):
        """Callback for connection pool queue depth gauge."""
        from opentelemetry.metrics import Observation

        if self.connection_queue_samples:
            avg_queue = sum(v for _, v in self.connection_queue_samples) / len(self.connection_queue_samples)
        else:
            avg_queue = len(self.db_connection_pool.queue) if self.db_connection_pool else 0

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name

        yield Observation(avg_queue, attributes)

    def _report_thread_pool_active(self, options):
        """Callback for thread pool active threads gauge."""
        from opentelemetry.metrics import Observation

        active_threads = self.thread_pool.count

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name

        yield Observation(active_threads, attributes)

    def _report_thread_pool_queue(self, options):
        """Callback for thread pool queue depth gauge."""
        from opentelemetry.metrics import Observation

        queue_depth = len(self.thread_pool.queue)

        attributes = {
            "component.id": self.id,
            "sim.time": self.env.now
        }
        if self.parent_service:
            attributes["service.name"] = self.parent_service.service_name

        yield Observation(queue_depth, attributes)
