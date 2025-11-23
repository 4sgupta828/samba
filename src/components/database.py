from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy, random

class SqlDatabase(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "SqlDatabase")

        # Load centralized configuration
        config = get_simulation_config().database
        global_config = get_simulation_config()

        # Initialize dynamics engine (always enabled - single source of truth)
        # Load dynamics configuration from global config with sensible defaults
        dynamics_params = {}
        if hasattr(global_config, 'dynamics'):
            db_dynamics_config = global_config.dynamics.get('components', {}).get('database', {})
            dynamics_params = db_dynamics_config.get('config', {})

        # Create dynamics configuration with defaults
        dynamics_cfg = DynamicsConfig(
            latency_base=dynamics_params.get('latency_base', 20.0),
            cpu_from_throughput_coef=dynamics_params.get('cpu_from_throughput_coef', 0.03),
            cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 1.0),
            latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 60.0),
            latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 30.0),
            error_base=dynamics_params.get('error_base', 0.001),
            error_latency_threshold=dynamics_params.get('error_latency_threshold', 200.0),
            error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 80.0),
            noise_enabled=dynamics_params.get('noise_enabled', True),
            latency_wear_coef=dynamics_params.get('latency_wear_coef', 0.01),
        )
        self.dynamics = MetricsDynamicsEngine(config=dynamics_cfg)

        self.instance_class = ""
        self.connection_pool = simpy.Resource(env, capacity=config.connection_pool_capacity)

        # Model CPU as a finite resource
        # Use PriorityResource for priority-based requests
        self.cpu_resource = simpy.PriorityResource(env, capacity=config.cpu_cores)

        # Track queries processed for dynamics updates
        self.queries_processed = 0

        # Control flag for background job (set by failure injection)
        self.background_job_enabled = config.background_jobs_enabled

        # Track CPU usage for realistic utilization calculation
        self.cpu_usage_accumulator = 0.0  # Accumulated CPU-seconds
        self.last_cpu_reset_time = 0.0
        self.cpu_capacity_cores = config.cpu_capacity_cores

        # Track samples for time-averaged gauges (like production systems)
        self.cpu_samples = []
        self.connection_samples = []
        self.sample_window = get_simulation_config().defaults.sample_window_seconds

        # Track connection rejections (when max_connections is exceeded)
        self.connection_rejections = 0

        # OTel Metrics
        self.active_connections = self.meter.create_observable_gauge(
            "db.connections.active",
            callbacks=[self._report_active_connections],
            description="Active database connections (time-averaged)"
        )
        # Counter for connection rejections (like MySQL Connection_errors_max_connections or MongoDB connections.rejected)
        self.connection_rejections_counter = self.meter.create_counter(
            "db.connections.rejected",
            description="Total number of connection attempts rejected due to max_connections limit"
        )
        # Query latency histogram (uses default OTel buckets; size reduction via SummarizedJsonMetricExporter)
        self.query_latency = self.meter.create_histogram("db.query.latency", unit="ms")
        # Use observable gauge like production systems (CloudWatch RDS.CPUUtilization, etc.)
        self.cpu_util_gauge = self.meter.create_observable_gauge(
            "db.cpu.utilization",
            callbacks=[self._report_cpu_utilization],
            unit="%",
            description="Database CPU utilization percentage (time-averaged)"
        )

    def _report_active_connections(self, options):
        """Callback for active connections gauge - reports time-averaged value like production systems."""
        from opentelemetry.metrics import Observation

        # Calculate average active connections over the sample window
        if self.connection_samples:
            avg_connections = sum(v for _, v in self.connection_samples) / len(self.connection_samples)
        else:
            # Fallback to current pool count if no samples yet
            avg_connections = self.connection_pool.count

        yield Observation(avg_connections, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_cpu_utilization(self, options):
        """Callback for CPU utilization gauge - reports dynamics engine value."""
        from opentelemetry.metrics import Observation

        # Always use dynamics engine value (single source of truth)
        avg_cpu = self.dynamics.get_cpu_percent()

        yield Observation(avg_cpu, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def run(self):
        """Overridden run method to start background jobs."""
        # Run the base startup logic from the parent class
        # We need to manually call this since we are overriding it
        self.state.operational = "RUNNING"
        print(f"[{self.env.now:.2f}s] {self.id}: State -> RUNNING")

        # Start background processes
        # NOTE: _run_background_job() has been moved to failure injection scenarios
        # to avoid confounding baseline metrics with background job effects
        self.env.process(self._sample_cpu_periodically())

        # Start dynamics update loop (always enabled)
        self.env.process(self._update_dynamics_loop())

        # The component itself can now just idle, its jobs are running
        while True:
            try:
                yield self.env.timeout(3600)
            except simpy.Interrupt as i:
                 self._emit_log("INFO", f"Interrupted by {i.cause}")

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second."""
        last_queries_count = 0

        while True:
            yield self.env.timeout(1.0)  # Update every simulation second

            # Calculate throughput (queries per second)
            # NOTE: This naturally includes retries since each retry calls handle_query() and increments queries_processed.
            # This provides realistic retry amplification - if a client retries 3x, the DB sees 3x load.
            # The retry_load_multiplier config (default 1.0) can be used to model different retry costs in future.
            queries_delta = self.queries_processed - last_queries_count
            last_queries_count = self.queries_processed

            # Get current observations from SimPy resources
            active_connections = self.connection_pool.count
            queue_depth = len(self.connection_pool.queue)

            # Pass thread pool size from actual SimPy resource
            # DB uses CPU cores as "thread pool" - each core can handle queries
            self.dynamics.thread_pool_size = self.cpu_resource.capacity

            # Update dynamics engine
            self.dynamics.update(
                dt=1.0,
                external_throughput=queries_delta,
                active_connections=active_connections,
                queue_depth=queue_depth
            )

    def _sample_cpu_periodically(self):
        """Background process that samples CPU and connection metrics at regular intervals."""
        self.last_cpu_reset_time = self.env.now
        config = get_simulation_config().defaults

        while True:
            yield self.env.timeout(config.cpu_sampling_interval_seconds)

            current_time = self.env.now
            time_delta = current_time - self.last_cpu_reset_time

            # Calculate CPU utilization from accumulated usage
            if time_delta > 0:
                current_cpu_util = (self.cpu_usage_accumulator / time_delta / self.cpu_capacity_cores) * 100
                current_cpu_util = min(current_cpu_util, 100)  # Cap at 100%

                # Reset accumulator for next period
                self.cpu_usage_accumulator = 0
                self.last_cpu_reset_time = current_time
            else:
                current_cpu_util = 0

            self.cpu_samples.append((current_time, current_cpu_util))

            # Sample active connections - use connection pool's real-time count
            # This is the number of connections currently in use (not our manual counter)
            active_conns = self.connection_pool.count
            self.connection_samples.append((current_time, active_conns))

            # Remove samples older than the window
            cutoff_time = current_time - self.sample_window
            self.cpu_samples = [(t, v) for t, v in self.cpu_samples if t > cutoff_time]
            self.connection_samples = [(t, v) for t, v in self.connection_samples if t > cutoff_time]


    def _run_background_job(self):
        """Simulates an internal job like vacuuming or cleanup.

        This background job competes for CPU resources and can increase query latency.
        It is now controlled via failure injection to avoid confounding baseline metrics.
        """
        config = get_simulation_config().database

        while True:
            # Check if background job is still enabled
            if not self.background_job_enabled:
                self._emit_log("DEBUG", "Background job disabled, exiting.")
                return  # Exit the background job process

            # Wait for a long, random interval
            interval_range = config.background_jobs_interval_range_seconds
            yield self.env.timeout(random.uniform(interval_range[0], interval_range[1]))

            # Check again after sleep in case it was disabled
            if not self.background_job_enabled:
                return

            self._emit_log("DEBUG", "Starting internal background job (e.g., VACUUM).")  # Reduced from INFO to DEBUG
            # This job requests CPU cores with a low priority
            with self.cpu_resource.request(priority=-1) as req:
                yield req # Wait for CPU

                # Check one more time before running
                if not self.background_job_enabled:
                    return

                # Removed DEBUG log for CPU acquisition
                duration_range = config.background_jobs_duration_range_seconds
                job_duration = random.uniform(duration_range[0], duration_range[1])

                # Background job uses configured CPU cores
                cpu_cores_used = config.background_jobs_cpu_cores_used
                self.cpu_usage_accumulator += job_duration * cpu_cores_used

                yield self.env.timeout(job_duration) # Job runs for a while

            self._emit_log("DEBUG", "Internal background job finished.")  # Reduced from INFO to DEBUG


    def handle_query(self, should_trace: bool = False, parent_span_context = None):
        """UPDATED: Simulates a DB query with CPU contention and degradation.

        Args:
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        start_time = self.env.now

        # Create child span if tracing is enabled and parent context exists
        if should_trace and parent_span_context:
            with self._start_span("SQL SELECT", parent_span_context=parent_span_context):
                yield from self._handle_query_internal()
        else:
            yield from self._handle_query_internal()

        end_time = self.env.now
        self.query_latency.record((end_time - start_time) * 1000, {
            "component.id": self.id
        })

    def _handle_query_internal(self):
        """Internal query handling logic with connection rejection."""

        # Network layer handles connection establishment (connection_failure, timeout, etc.)
        yield from self._network_call(target_component_id=self.id, data_size_bytes=512, target_component_type=self.type)

        # Check if connection pool is at capacity
        # In real DBs, if max_connections is reached, new connections are rejected immediately
        if self.connection_pool.count >= self.connection_pool.capacity:
            # Connection rejected - track the rejection
            self.connection_rejections += 1
            self.connection_rejections_counter.add(1, {
                "component.id": self.id,
                "reason": "max_connections_exceeded"
            })
            self._emit_log("ERROR", f"Connection rejected: max_connections ({self.connection_pool.capacity}) exceeded")
            raise Exception(f"FATAL: sorry, too many clients already (max_connections={self.connection_pool.capacity})")

        with self.connection_pool.request() as conn_req:
            try:
                yield conn_req
            except Exception as e:
                self._emit_log("WARN", f"Failed to get connection: {e}")
                raise

            # Request 1 CPU core to execute the query
            with self.cpu_resource.request(priority=1) as cpu_req: # High priority
                yield cpu_req

                # Transient errors during query execution
                if self._should_transient_error_occur('lock_timeout'):
                    self._raise_transient_error('lock_timeout')

                if self._should_transient_error_occur('deadlock'):
                    self._raise_transient_error('deadlock')

                if self._should_transient_error_occur('statement_timeout'):
                    self._raise_transient_error('statement_timeout')

                # --- Query Time: Always use dynamics engine (single source of truth) ---
                config = get_simulation_config().database

                # Dynamics engine provides latency in milliseconds, convert to seconds
                base_query_time = self.dynamics.get_latency() / 1000.0

                # Check if query should fail based on dynamics error rate
                if random.random() < self.dynamics.get_error_rate():
                    self._emit_log("ERROR", "Query failed due to dynamics-driven error")
                    raise Exception("Database query failed: Resource temporarily unavailable")

                # Note: Fault injections now work through dynamics multipliers/wear_factor
                # No need for separate injected_latency_ms - dynamics handles everything
                total_query_time = base_query_time

                # Track CPU usage
                cpu_cores_used = config.query_cpu_usage_cores
                self.cpu_usage_accumulator += total_query_time * cpu_cores_used

                yield self.env.timeout(total_query_time)

                self.queries_processed += 1
                # Note: Wear is now managed by dynamics engine based on CPU load
                # No manual wear accumulation needed here

class NoSqlDatabase(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "NoSqlDatabase")