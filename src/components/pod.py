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
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy
import random


class Pod(EnrichedComponent):
    """
    Pod represents a container instance that executes service logic.

    Renamed from ComputeAgent to match Kubernetes terminology.
    """

    def __init__(self, env: simpy.Environment, component_id: str,
                 parent_service=None, compute_node=None):
        super().__init__(env, component_id, "Pod")

        # NEW: References to parent service and compute node
        self.parent_service = parent_service
        self.compute_node = compute_node

        # Register this pod with the node if provided
        if self.compute_node:
            self.compute_node.register_pod(self)

        # Load centralized configuration
        config = get_simulation_config().compute

        # Internal state for cumulative effects
        self.memory_capacity_mb = config.memory_capacity_mb
        self.restarts = 0
        # Deployment-triggered behavior support (non-dynamics attributes)
        self.critical_error_boost: float = 0.0  # Adds to probability of 5xx errors (0.0 = normal, 0.15 = +15%)

        # Client-side connection pool (like HikariCP, pgBouncer, etc.)
        # Each pod manages its own pool of DB connections
        self.db_connection_pool = simpy.Resource(env, capacity=config.db_connection_pool_capacity)

        # Thread pool for request processing
        self.thread_pool_size = getattr(config, 'thread_pool_size', 50)
        self.thread_pool = simpy.Resource(env, capacity=self.thread_pool_size)

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

        # Create dynamics configuration with defaults
        dynamics_cfg = DynamicsConfig(
            latency_base=dynamics_params.get('latency_base', 50.0),
            cpu_min=dynamics_params.get('cpu_min', 10.0),
            cpu_from_throughput_coef=dynamics_params.get('cpu_from_throughput_coef', 0.25),
            cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 2.0),
            latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 70.0),
            latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 20.0),
            error_base=dynamics_params.get('error_base', 0.002),
            error_latency_threshold=dynamics_params.get('error_latency_threshold', 500.0),
            error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 85.0),
            noise_enabled=dynamics_params.get('noise_enabled', True),
            memory_base=dynamics_params.get('memory_base', config.memory_base_mb),
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

        # Request-level metrics (use service namespace for compatibility with visualization)
        # These will be tagged with service.name for aggregation at service level
        self.request_counter = self.meter.create_counter(
            f"service.{service_name}.requests",
            unit="1",
            description="Number of requests handled by pods of this service"
        )
        self.request_duration = self.meter.create_histogram(
            f"service.{service_name}.duration",
            unit="ms",
            description="Request processing duration"
        )
        self.request_errors = self.meter.create_counter(
            f"service.{service_name}.errors",
            unit="1",
            description="Number of request errors"
        )

        # External dependency call metrics (from this pod's perspective as client)
        self.dependency_requests = self.meter.create_counter(
            f"service.{service_name}.dependency.requests",
            unit="1",
            description="Requests to external dependencies"
        )
        self.dependency_duration = self.meter.create_histogram(
            f"service.{service_name}.dependency.duration",
            unit="ms",
            description="External dependency call duration"
        )
        self.dependency_errors = self.meter.create_counter(
            f"service.{service_name}.dependency.errors",
            unit="1",
            description="External dependency call errors"
        )

    def run(self):
        """Pod lifecycle with crash/restart loop and permanent termination support."""
        self.start_time = self.env.now  # Track when pod started

        # Start background processes
        self.env.process(self._sample_cpu_periodically())
        self.env.process(self._monitor_oom())
        self.env.process(self._update_dynamics_loop())

        # Start queue consumer if parent service has queue_in connection
        if self.parent_service and 'queue_in' in getattr(self.parent_service, 'connections', {}):
            self.env.process(self._consume_from_queue())

        while True:
            self.state.operational = "STARTING"
            self.restarts += 1
            # Reset dynamics memory on restart (simulates process restart)
            self.dynamics.memory_percent = self.dynamics.config.memory_base
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

                    # Reset dynamics memory immediately (simulates process termination)
                    self.dynamics.memory_percent = self.dynamics.config.memory_base
                    self.state.cpu_utilization = 0  # Process is dead, no CPU usage

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
        """
        if not self.parent_service:
            return

        queue = self.parent_service.connections.get('queue_in')
        if not queue:
            return

        self._emit_log("INFO", f"Starting queue consumer for {queue.id}")

        while self.state.operational != "TERMINATED":
            try:
                # Wait for a message from the queue
                msg = yield from queue.receive_message()

                self._emit_log("DEBUG", f"Received message {msg.id} from queue")

                # Process the message by calling handle_request
                # Use a random request type from parent service's supported types
                if hasattr(self.parent_service, 'supported_request_types') and self.parent_service.supported_request_types:
                    request_type = random.choice(self.parent_service.supported_request_types)
                else:
                    request_type = "PROCESS"

                try:
                    # Process the message (executes pipeline)
                    yield self.env.process(self.handle_request(request_type, should_trace=False))

                    # Successfully processed - delete the message
                    queue.delete_message(msg)
                    self._emit_log("DEBUG", f"Successfully processed message {msg.id}")

                except Exception as e:
                    # Processing failed - message will become visible again after timeout
                    self._emit_log("ERROR", f"Failed to process message {msg.id}: {e}")
                    # Don't delete - let visibility timeout return it to queue for retry

            except Exception as e:
                # Queue receive failed - log and retry after delay
                self._emit_log("WARN", f"Queue receive failed: {e}")
                yield self.env.timeout(1.0)  # Wait 1s before retrying

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
            active_connections = self.db_connection_pool.count
            queue_depth = len(self.db_connection_pool.queue)

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

            # Sample connection pool metrics
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
        with self.thread_pool.request() as req:
            yield req  # Wait for available thread

            queue_wait_time = (self.env.now - queue_start) * 1000  # Convert to ms

            # Add queue wait time to span if we waited
            if span and queue_wait_time > 0:
                span.set_attribute("thread_pool.queue_wait_ms", queue_wait_time)

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
                service_latency = self.dynamics.get_latency() / 1000.0  # Convert ms to seconds
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
                        "service.name": self.parent_service.service_name
                    })
                    self.request_duration.record(latency_ms, {
                        "status": "success",
                        "request_type": request_type,
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name
                    })

            except Exception as e:
                # Record error metrics (only if metrics are initialized)
                latency_ms = (self.env.now - start_time) * 1000
                if self.request_counter and self.request_duration and self.request_errors and self.parent_service:
                    self.request_counter.add(1, {
                        "status": "error",
                        "request_type": request_type,
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name
                    })
                    self.request_duration.record(latency_ms, {
                        "status": "error",
                        "request_type": request_type,
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name
                    })
                    self.request_errors.add(1, {
                        "request_type": request_type,
                        "component.id": self.id,
                        "service.name": self.parent_service.service_name
                    })
                raise  # Re-raise the exception

    def _execute_processing_pipeline(self, request_type: str, span):
        """
        Execute the parent service's processing pipeline.

        Pipeline steps are executed in order, but only if the required connections exist.
        """
        pipeline = self.parent_service.processing_pipeline

        for step in pipeline:
            step_type = step.get("type")
            probability = step.get("probability", 1.0)  # Default: always execute

            # Probabilistic execution
            if random.random() > probability:
                continue

            # Execute step based on type
            if step_type == "cache_check":
                if 'cache' in self.parent_service.connections:
                    yield from self._execute_cache_logic(step, span)

            elif step_type == "db_query":
                if 'database' in self.parent_service.connections:
                    yield from self._execute_db_logic(step, span)

            elif step_type == "service_calls":
                # Call dep_* connections
                yield from self._execute_service_calls(step, span)

            elif step_type == "external_calls":
                # Call ext_* connections
                yield from self._execute_external_calls(step, span)

            elif step_type == "queue_publish":
                if 'queue_out' in self.parent_service.connections:
                    yield from self._execute_queue_publish(step, span)

    def _execute_cache_logic(self, step, span):
        """Execute cache check logic."""
        cache = self.parent_service.connections.get('cache')
        if not cache:
            return

        # Generate cache key
        cache_key = f"{self.parent_service.service_name}:data:{random.randint(1, 100)}"

        try:
            should_trace_cache = span is not None
            cache_span_ctx = None
            if should_trace_cache:
                from opentelemetry import trace
                cache_span_ctx = trace.set_span_in_context(span)

            # Try cache get
            cache_process = self.env.process(cache.get(cache_key, should_trace=should_trace_cache, parent_span_context=cache_span_ctx))
            cached_data = yield cache_process  # Process objects need yield, not yield from

            if cached_data:
                if span:
                    span.set_attribute("cache.hit", True)
                self._emit_log("DEBUG", f"Cache hit for key {cache_key}")
                return
            else:
                if span:
                    span.set_attribute("cache.hit", False)
                self._emit_log("DEBUG", f"Cache miss for key {cache_key}")
        except Exception as e:
            self._emit_log("WARN", f"Cache operation failed: {e}")

    def _execute_db_logic(self, step, span):
        """Execute database query logic."""
        db = self.parent_service.connections.get('database')
        if not db:
            return

        config = get_simulation_config().compute
        max_retries = config.db_max_retries

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
                    break  # Success
                except Exception as e:
                    self._emit_log("WARN", f"DB call failed (attempt {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        backoff_time = (2 ** attempt) * config.db_retry_backoff_base_seconds
                        yield self.env.timeout(backoff_time)
                    else:
                        raise

    def _execute_service_calls(self, step, span):
        """Execute service-to-service calls."""
        # Find all dep_* connections
        for conn_name, conn_target in self.parent_service.connections.items():
            if conn_name.startswith('dep_'):
                try:
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
                except Exception as e:
                    self._emit_log("WARN", f"Service call to {conn_name} failed: {e}")

    def _execute_external_calls(self, step, span):
        """Execute external service calls."""
        # Find all ext_* connections
        for conn_name, conn_target in self.parent_service.connections.items():
            if conn_name.startswith('ext_'):
                dep_start = self.env.now
                try:
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

                except Exception as e:
                    self._emit_log("WARN", f"External call to {conn_name} failed: {e}")

                    # Record error metrics (only if metrics are initialized)
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

    def _execute_queue_publish(self, step, span):
        """Execute queue message publishing."""
        queue = self.parent_service.connections.get('queue_out')
        if not queue:
            return

        try:
            message_data = f"message_from_{self.parent_service.service_name}_{self.env.now}"
            yield queue.send_message(message_data)  # send_message returns an event, not a generator

            if span:
                span.add_event("message_published", {"queue": "queue_out"})
        except Exception as e:
            self._emit_log("WARN", f"Queue publish failed: {e}")

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
            avg_active = self.db_connection_pool.count

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
            avg_queue = len(self.db_connection_pool.queue)

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
