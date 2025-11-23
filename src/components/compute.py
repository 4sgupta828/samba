from .base_component import EnrichedComponent, AutoScalingPolicy
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy, random

class ComputeAgent(EnrichedComponent):
    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "ComputeAgent")

        # Load centralized configuration
        config = get_simulation_config().compute

        # Internal state for cumulative effects
        self.memory_capacity_mb = config.memory_capacity_mb
        self.restarts = 0
        # Deployment-triggered behavior support (non-dynamics attributes)
        self.critical_error_boost: float = 0.0  # Adds to probability of 5xx errors (0.0 = normal, 0.15 = +15%)

        # Client-side connection pool (like HikariCP, pgBouncer, etc.)
        # Each compute agent manages its own pool of DB connections
        self.db_connection_pool = simpy.Resource(env, capacity=config.db_connection_pool_capacity)

        # Phase 3.1: Thread pool for request processing
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

        # Phase 3.1: Thread pool metrics
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

    def run(self):
        """Overridden run method to handle the crash/restart loop."""
        # Start CPU sampling background process
        self.env.process(self._sample_cpu_periodically())

        # Start OOMKilled monitoring process
        self.env.process(self._monitor_oom())

        # Start dynamics update loop (always enabled - single source of truth)
        self.env.process(self._update_dynamics_loop())

        while True:
            self.state.operational = "STARTING"
            self.restarts += 1
            # Reset dynamics memory on restart (simulates process restart)
            self.dynamics.memory_percent = self.dynamics.config.memory_base
            self._emit_log("INFO", f"Starting (Restart #{self.restarts})...")

            config = get_simulation_config().compute
            startup_range = config.startup_time_range_seconds
            yield self.env.timeout(random.uniform(startup_range[0], startup_range[1])) # Simulate startup time

            self.state.operational = "RUNNING"
            self._emit_log("INFO", f"Component has started successfully (Version: {self.version}).")

            # Store reference to current running process for interrupt
            self.running_process = self.env.active_process

            try:
                # Component is now running until it's interrupted (e.g., by a crash)
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
                        if backoff_interrupt.cause == "TERMINATED_FOR_DEPLOYMENT":
                            self.state.operational = "TERMINATED"
                            self._emit_log("INFO", "Component terminated for new deployment during CrashLoopBackOff.")
                            return  # Exit the process permanently
                        else:
                            # Re-raise other interrupts
                            raise

                # NEW: Handle termination from the deployment controller
                elif interrupt.cause == "TERMINATED_FOR_DEPLOYMENT":
                    self.state.operational = "TERMINATED"
                    self._emit_log("INFO", "Component terminated for new deployment.")
                    return  # Exit the process permanently

                else:
                    self._emit_log("ERROR", f"Unhandled interrupt: {interrupt.cause}. Shutting down.")
                    self.state.operational = "DOWN"
                    return # Exit the run loop
            finally:
                self.running_process = None

    def _monitor_oom(self):
        """Background process that monitors for OOMKilled condition using dynamics engine."""
        config = get_simulation_config().compute
        while self.state.operational != "TERMINATED":
            yield self.env.timeout(config.oom_check_interval_seconds)

            # Check again after timeout in case we were terminated during the wait
            if self.state.operational == "TERMINATED":
                break

            # Check if we're currently running and memory exceeds capacity
            # Always use dynamics engine (single source of truth)
            if self.state.operational == "RUNNING":
                current_memory = self.dynamics.get_memory()
                if current_memory > self.memory_capacity_mb:
                    self._emit_log("WARN", f"OOMKilled condition detected: {current_memory:.1f}MB > {self.memory_capacity_mb}MB (dynamics)")
                    # Interrupt the running process
                    if hasattr(self, 'running_process') and self.running_process is not None:
                        self.running_process.interrupt("OOMKilled")

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second.

        Phase 3.4: Includes GC pressure simulation.
        """
        while self.state.operational != "TERMINATED":
            yield self.env.timeout(1.0)  # Update every simulation second

            # Check again after timeout in case we were terminated during the wait
            if self.state.operational == "TERMINATED":
                break

            # Phase 3.4: Check memory pressure for GC (always use dynamics - single source of truth)
            memory_mb = self.dynamics.get_memory()
            memory_capacity = self.iac_config.get('memory_capacity_mb', 512)
            memory_pct = memory_mb / memory_capacity

            # Trigger GC if memory >85%
            if memory_pct > 0.85:
                gc_pause_ms = random.uniform(100, 500)  # 100-500ms pause

                self._emit_log("WARN", f"GC triggered: memory={memory_mb:.0f}MB ({memory_pct*100:.1f}%) (dynamics)")

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

            # CRITICAL: Read actual thread pool usage from SimPy (not calculated!)
            actual_threads_active = self.thread_pool.count  # Actual blocked threads
            actual_queue_depth = len(self.thread_pool.queue) if hasattr(self.thread_pool, 'queue') else 0

            # Pass thread pool size from actual SimPy resource
            self.dynamics.thread_pool_size = self.thread_pool.capacity

            # Override dynamics' calculated concurrent_requests with ACTUAL thread count
            # This ensures CPU contention reflects real blocking, not just mathematical estimate
            self.dynamics.concurrent_requests = actual_threads_active

            # Update dynamics engine (multipliers are managed by the dynamics engine itself)
            self.dynamics.update(
                dt=1.0,
                external_throughput=requests_delta,
                active_connections=active_connections,
                queue_depth=actual_queue_depth  # Use actual thread queue, not DB queue
            )

    def _call_with_timeout(self, process, timeout_seconds, error_message="Call timeout"):
        """
        Helper to execute a process with a timeout.

        Args:
            process: SimPy process to execute
            timeout_seconds: Maximum time to wait
            error_message: Error message to raise on timeout

        Yields:
            The process result if successful

        Raises:
            Exception: If timeout occurs
        """
        start_time = self.env.now
        timeout_event = self.env.timeout(timeout_seconds)

        # Race between the process and timeout
        result = yield process | timeout_event

        # Check if timeout occurred
        if self.env.now - start_time >= timeout_seconds:
            self._emit_log("ERROR", f"{error_message} after {timeout_seconds}s")
            raise Exception(f"{error_message}: operation exceeded {timeout_seconds}s")

    def _sample_cpu_periodically(self):
        """Background process that samples CPU, memory, and connection pool metrics at regular intervals.

        Always uses dynamics engine for CPU and memory (single source of truth).
        """
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

    def handle_request(self, request_type: str, should_trace: bool = False, parent_span_context = None):
        """UPDATED: Now includes a cache-aside pattern with trace sampling.

        Args:
            request_type: Type of request to handle
            should_trace: Whether to create tracing spans for this request
            parent_span_context: Parent span context for distributed tracing
        """
        # Check if tracing is enabled for this request (parent span is being recorded)
        if should_trace and parent_span_context:
            # Create child span with parent context for distributed tracing
            with self._start_span(f"process:{request_type}", parent_span_context=parent_span_context) as span:
                yield from self._handle_request_internal(request_type, span)
        else:
            yield from self._handle_request_internal(request_type, None)

    def _handle_request_internal(self, request_type: str, span):
        """Internal request handling with optional tracing.

        Phase 3.1: Uses thread pool to process requests, adding queue wait time.
        """
        # Track request count for dynamics
        self.request_count += 1

        # Phase 3.1: Request thread from pool
        queue_start = self.env.now
        with self.thread_pool.request() as req:
            yield req  # Wait for available thread

            queue_wait_time = (self.env.now - queue_start) * 1000  # Convert to ms

            # Add queue wait time to span if we waited
            if span and queue_wait_time > 0:
                span.set_attribute("thread_pool.queue_wait_ms", queue_wait_time)

            self._emit_log("DEBUG", f"Processing request type: {request_type}")  # Reduced from INFO to DEBUG

            # Check dynamics-based error before processing (always enabled - single source of truth)
            if random.random() < self.dynamics.get_error_rate():
                self._emit_log("ERROR", "Request failed due to dynamics-driven error")
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", "dynamics_error")
                raise Exception("Request processing failed: Service temporarily unavailable")

            # Calculate memory pressure effects using dynamics engine
            current_memory = self.dynamics.get_memory()
            memory_pressure_delay = self._calculate_memory_pressure_delay(current_memory)

            if memory_pressure_delay > 0:
                # Simulate GC pause or memory pressure impact
                # Only log significant delays (> 100ms) to avoid spam
                if memory_pressure_delay > 0.1:
                    self._emit_log("INFO", f"Memory pressure delay: {memory_pressure_delay*1000:.1f}ms (mem: {current_memory:.1f}MB)")

                # Spike CPU during GC pause - higher spike for severe memory pressure
                config = get_simulation_config().compute
                thresholds = config.memory_pressure_thresholds_mb
                old_cpu = self.state.cpu_utilization
                if current_memory > thresholds[2]:
                    # Severe thrashing - very high CPU
                    cpu_range = config.memory_pressure_cpu_severe_percent
                    self.state.cpu_utilization = random.uniform(cpu_range[0], cpu_range[1])
                elif current_memory > thresholds[1]:
                    # Moderate GC pressure
                    cpu_range = config.memory_pressure_cpu_moderate_percent
                    self.state.cpu_utilization = random.uniform(cpu_range[0], cpu_range[1])
                else:
                    # Minor GC pressure
                    cpu_range = config.memory_pressure_cpu_minor_percent
                    self.state.cpu_utilization = random.uniform(cpu_range[0], cpu_range[1])

                yield self.env.timeout(memory_pressure_delay)
                self.state.cpu_utilization = old_cpu

            db = self.connections.get("database")
            cache = self.connections.get("cache")
            # NOTE: Both database and cache are optional
            # Some services may only call external APIs, other services, or queues
            # If no database is available, we skip the cache-aside pattern

            # --- Determine if request type uses cache ---
            # Define cache-friendly request types with their cache key patterns and hit rates
            CACHE_ENABLED_REQUESTS = {
                # Legacy request type
                "read_profile": {
                    "key_pattern": "user:{id}",
                    "hit_rate": 0.90,  # 90% cache hit rate
                    "id_range": [1, 100]
                },
                # E-commerce Product Catalog requests
                "browse_products": {
                    "key_pattern": "products:category:{id}",
                    "hit_rate": 0.80,  # Popular categories cached
                    "id_range": [1, 50]  # 50 product categories
                },
                "get_product_details": {
                    "key_pattern": "product:{id}",
                    "hit_rate": 0.70,  # Individual product pages
                    "id_range": [1, 1000]  # 1000 products
                },
                "search_products": {
                    "key_pattern": "search:{id}",  # id represents query hash
                    "hit_rate": 0.50,  # Common searches cached
                    "id_range": [1, 200]  # 200 common search queries
                },
                "get_recommendations": {
                    "key_pattern": "recommendations:user:{id}",
                    "hit_rate": 0.60,  # Personalized recommendations
                    "id_range": [1, 100]  # User ID range
                },
                # E-commerce User Account requests
                "get_user_profile": {
                    "key_pattern": "user_profile:{id}",
                    "hit_rate": 0.90,  # Hot path - high cache hit rate
                    "id_range": [1, 100]
                },
                "login": {
                    "key_pattern": "session:{id}",
                    "hit_rate": 0.70,  # Session tokens cached
                    "id_range": [1, 200]  # Session tokens
                },
                # E-commerce Order requests
                "get_order_history": {
                    "key_pattern": "orders:user:{id}",
                    "hit_rate": 0.40,  # Lower hit rate due to frequent updates
                    "id_range": [1, 100]
                }
            }

            # Check if this request type uses cache
            cache_config = CACHE_ENABLED_REQUESTS.get(request_type)

            # --- Cache-Aside Logic for cache-enabled requests ---
            # Note: Cache-aside pattern requires both cache and database
            if cache_config and cache and db:
                config = get_simulation_config().compute

                # Generate cache key based on request type configuration
                id_range = cache_config["id_range"]
                resource_id = random.randint(id_range[0], id_range[1])
                cache_key = cache_config["key_pattern"].replace("{id}", str(resource_id))

                # Simulate cache hit/miss based on configured hit rate
                # We simulate this probabilistically to model a warm cache without pre-population
                cache_hit_rate = cache_config["hit_rate"]
                should_simulate_hit = random.random() < cache_hit_rate

                cached_data = None

                # Try cache lookup
                should_trace_cache = span is not None
                cache_span_ctx = None
                if should_trace_cache:
                    from opentelemetry import trace
                    cache_span_ctx = trace.set_span_in_context(span)

                # Use timeout for cache call
                try:
                    timeout_config = get_simulation_config().compute.timeouts
                    cache_process = self.env.process(cache.get(cache_key, should_trace=should_trace_cache, parent_span_context=cache_span_ctx))
                    actual_cached_data = yield from self._call_with_timeout(
                        cache_process,
                        timeout_config.cache_call_seconds,
                        f"Cache get timeout for {cache.id}"
                    )

                    # Simulate warm cache: if we should have a hit, return synthetic data
                    # This models a production cache that has been warming up
                    if should_simulate_hit or actual_cached_data:
                        cached_data = actual_cached_data if actual_cached_data else f"{request_type}_cached_data_{resource_id}"
                except Exception as e:
                    self._emit_log("WARN", f"Cache get failed: {e}")
                    cached_data = None

                if cached_data:
                    if span:
                        span.set_attribute("cache.hit", True)
                    self._emit_log("DEBUG", f"Cache hit for key {cache_key}")
                    # Simulate light CPU work for processing cached data
                    proc_time_range = config.cache_processing_time_range_seconds
                    yield self.env.timeout(random.uniform(proc_time_range[0], proc_time_range[1]))

                    # Note: Memory is now managed by dynamics engine based on concurrent requests
                    # No need for manual memory leak tracking

                    return # Request is done!

                # --- Cache Miss ---
                if span:
                    span.set_attribute("cache.hit", False)
                self._emit_log("DEBUG", f"Cache miss for key {cache_key} (request: {request_type}), fetching from DB.")

                # --- DB call with client-side connection pool and retry logic ---
                max_retries = config.db_max_retries
                db_data = None

                # Acquire connection from client-side pool (queues here if pool is full)
                # Network errors will be handled by the network layer when making the actual call
                with self.db_connection_pool.request() as conn_req:
                    yield conn_req  # Wait for an available connection

                    # Phase 3.2: Check connection pool pressure and add wait time
                    pool_utilization = self.db_connection_pool.count / self.db_connection_pool.capacity
                    if pool_utilization > 0.8:
                        # Pool is under pressure, add wait time
                        wait_time_ms = (pool_utilization - 0.8) * 5 * 100  # Up to 100ms wait
                        yield self.env.timeout(wait_time_ms / 1000.0)

                        if span:
                            span.set_attribute("connection_pool.wait_time_ms", wait_time_ms)
                            span.set_attribute("connection_pool.utilization", pool_utilization)

                    # Now we have a connection, make the DB call with retries
                    for attempt in range(max_retries):
                        try:
                            # Propagate tracing and context to DB for THIS attempt only via parameters
                            should_trace_db = span is not None
                            db_span_ctx = None
                            if should_trace_db:
                                from opentelemetry import trace
                                db_span_ctx = trace.set_span_in_context(span)

                            # Use timeout for database call (simulation realism)
                            timeout_config = get_simulation_config().compute.timeouts
                            db_process = self.env.process(db.handle_query(should_trace=should_trace_db, parent_span_context=db_span_ctx))
                            yield from self._call_with_timeout(
                                db_process,
                                timeout_config.database_call_seconds,
                                f"Database call timeout for {db.id}"
                            )

                            # Generate mock data based on request type
                            db_data = f"{request_type}_data_for_{resource_id}" # Mock data
                            break # Success
                        except Exception as e:
                            self._emit_log("WARN", f"DB call failed (attempt {attempt+1}/{max_retries}): {e}")
                            if span:
                                span.add_event("db_retry", {"attempt": attempt + 1})
                            if attempt < max_retries - 1:
                                # Exponential backoff with jitter
                                jitter_range = config.db_retry_backoff_jitter_range_seconds
                                backoff_time = (2 ** attempt) * config.db_retry_backoff_base_seconds + random.uniform(jitter_range[0], jitter_range[1])
                                yield self.env.timeout(backoff_time)
                            else:
                                self._emit_log("ERROR", "DB call failed after all retries.")
                                raise # Re-raise the exception to fail the request
                    # Connection is automatically released when exiting the 'with' block

                # After getting data from DB, write it back to the cache if available
                if db_data and cache:
                    should_trace_cache_set = span is not None
                    cache_set_span_ctx = None
                    if should_trace_cache_set:
                        from opentelemetry import trace
                        cache_set_span_ctx = trace.set_span_in_context(span)

                    # Use timeout for cache set (best effort - don't fail request if cache set fails)
                    try:
                        timeout_config = get_simulation_config().compute.timeouts
                        cache_set_process = self.env.process(cache.set(cache_key, db_data, should_trace=should_trace_cache_set, parent_span_context=cache_set_span_ctx))
                        yield from self._call_with_timeout(
                            cache_set_process,
                            timeout_config.cache_call_seconds,
                            f"Cache set timeout for {cache.id}"
                        )
                    except Exception as e:
                        self._emit_log("WARN", f"Cache set failed: {e} (non-fatal)")

                return # End of cache-enabled request (cache hit or cache miss + DB fetch)

            # --- Logic for other request types (generate_report, update_profile) ---
            # Set work time and resource usage based on request type
            config = get_simulation_config().compute
            if request_type == "generate_report":
                # This is a heavy request
                work_time = random.gauss(config.request_generate_report_time_mean_seconds, config.request_generate_report_time_stdev_seconds)
                cpu_range = config.request_generate_report_cpu_range_percent
                cpu_spike = random.uniform(cpu_range[0], cpu_range[1])
            elif request_type == "update_profile":
                # Medium weight request
                work_time = random.gauss(config.request_update_profile_time_mean_seconds, config.request_update_profile_time_stdev_seconds)
                cpu_range = config.request_update_profile_cpu_range_percent
                cpu_spike = random.uniform(cpu_range[0], cpu_range[1])
            else:
                # Default for unknown request types
                work_time = random.gauss(config.request_default_time_mean_seconds, config.request_default_time_stdev_seconds)
                cpu_range = config.request_default_cpu_spike_range_percent
                cpu_spike = random.uniform(cpu_range[0], cpu_range[1])

            # --- Apply resource usage ---
            # Note: Memory, CPU multipliers, latency multipliers, and error rates are now
            # managed by the dynamics engine automatically. Fault injections set dynamics
            # multipliers which the engine uses to compute realistic metric evolution.

            # Update state CPU for instantaneous spikes (dynamics provides time-averaged values)
            self.state.cpu_utilization = cpu_spike

            # Work time is base latency - dynamics will apply its multipliers
            yield self.env.timeout(work_time)

            self.state.cpu_utilization = config.cpu_idle_level_percent # Back to idle

            # Update memory usage for metrics from dynamics engine
            self.state.memory_usage_mb = self.dynamics.get_memory()

            # Check if deployment introduced critical errors (e.g., validation bugs causing 500s)
            # This is separate from dynamics error rate - it's a specific deployment bug scenario
            if self.critical_error_boost > 0 and random.random() < self.critical_error_boost:
                error_msg = "Validation error: Unexpected data format in request payload"
                self._emit_log("ERROR", f"Critical error triggered by deployment bug: {error_msg}")
                raise Exception(f"DeploymentBug: {error_msg}")

            # --- Stochasticity: Simulate CPU work with noise ---
            cpu_range = config.cpu_processing_range_percent
            self.state.cpu_utilization = random.uniform(cpu_range[0], cpu_range[1])
            additional_work_time = random.gauss(config.cpu_additional_work_time_mean_seconds, config.cpu_additional_work_time_stdev_seconds)
            # Note: Latency injections now work through dynamics latency_multiplier
            yield self.env.timeout(additional_work_time)
            self.state.cpu_utilization = config.cpu_idle_level_percent # Back to idle

            # --- DB call with client-side connection pool and retry logic for write operations ---
            # Only make database call if database connection is available
            if not db:
                # No database connection - service completes without database access
                # This is valid for services that only call external APIs or other services
                self._emit_log("DEBUG", f"No database connection for {request_type}, completing without DB call")
                return

            max_retries = config.db_max_retries

            # Acquire connection from client-side pool (queues here if pool is full)
            with self.db_connection_pool.request() as conn_req:
                yield conn_req  # Wait for an available connection

                # Phase 3.2: Check connection pool pressure and add wait time
                pool_utilization = self.db_connection_pool.count / self.db_connection_pool.capacity
                if pool_utilization > 0.8:
                    # Pool is under pressure, add wait time
                    wait_time_ms = (pool_utilization - 0.8) * 5 * 100  # Up to 100ms wait
                    yield self.env.timeout(wait_time_ms / 1000.0)

                    if span:
                        span.set_attribute("connection_pool.wait_time_ms", wait_time_ms)
                        span.set_attribute("connection_pool.utilization", pool_utilization)

                # Now we have a connection, make the DB call with retries
                for attempt in range(max_retries):
                    try:
                        # Propagate tracing and context to DB for THIS attempt only via parameters
                        should_trace_db_write = span is not None
                        db_write_span_ctx = None
                        if should_trace_db_write:
                            from opentelemetry import trace
                            db_write_span_ctx = trace.set_span_in_context(span)

                        yield self.env.process(db.handle_query(should_trace=should_trace_db_write, parent_span_context=db_write_span_ctx))

                        self._emit_log("INFO", f"Finished processing {request_type}")
                        return # Success
                    except Exception as e:
                        self._emit_log("WARN", f"DB call failed (attempt {attempt+1}/{max_retries}): {e}")
                        if span:
                            span.add_event("db_retry", {"attempt": attempt + 1})
                        if attempt < max_retries - 1:
                            # Exponential backoff with jitter
                            jitter_range = config.db_retry_backoff_jitter_range_seconds
                            backoff_time = (2 ** attempt) * config.db_retry_backoff_base_seconds + random.uniform(jitter_range[0], jitter_range[1])
                            yield self.env.timeout(backoff_time)
                        else:
                            self._emit_log("ERROR", "DB call failed after all retries.")
                            raise # Re-raise the exception to fail the request
                # Connection is automatically released when exiting the 'with' block

    def _calculate_memory_pressure_delay(self, current_memory_mb: float) -> float:
        """Calculate additional delay due to memory pressure (GC pauses, thrashing).

        Returns delay in simulation seconds.
        """
        config = get_simulation_config().compute
        thresholds = config.memory_pressure_thresholds_mb

        if current_memory_mb < thresholds[0]:
            return 0.0
        elif current_memory_mb < thresholds[1]:
            # Minor GC pressure
            pressure_factor = (current_memory_mb - thresholds[0]) / (thresholds[1] - thresholds[0])  # 0.0 to 1.0
            delay_range = config.memory_pressure_delays_minor_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor
        elif current_memory_mb < thresholds[2]:
            # Moderate GC pressure
            pressure_factor = (current_memory_mb - thresholds[1]) / (thresholds[2] - thresholds[1])  # 0.0 to 1.0
            delay_range = config.memory_pressure_delays_moderate_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor
        else:
            # Severe GC pressure (system is thrashing)
            pressure_factor = min((current_memory_mb - thresholds[2]) / 100, 1.0)  # 0.0 to 1.0
            delay_range = config.memory_pressure_delays_severe_seconds
            return delay_range[0] + random.uniform(0, delay_range[1] - delay_range[0]) * pressure_factor

    def _report_cpu_utilization(self, options):
        """Callback for CPU utilization gauge - always uses dynamics engine (single source of truth)."""
        from opentelemetry.metrics import Observation

        # Don't emit metrics if instance is terminated
        if self.state.operational == "TERMINATED":
            return

        # Always use dynamics engine value (single source of truth)
        # Dynamics engine already applies cpu_multiplier internally
        avg_cpu = self.dynamics.get_cpu_percent()

        yield Observation(avg_cpu, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_memory_usage(self, options):
        """Callback for memory usage gauge - always uses dynamics engine (single source of truth).

        Returns MB directly from dynamics engine.
        """
        from opentelemetry.metrics import Observation

        # Don't emit metrics if instance is terminated
        if self.state.operational == "TERMINATED":
            return

        # Always use dynamics engine value (single source of truth)
        avg_memory = self.dynamics.get_memory()  # Returns MB directly

        # Also update state for consistency
        self.state.memory_usage_mb = avg_memory
        yield Observation(avg_memory, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_connection_pool_active(self, options):
        """Callback for connection pool active connections gauge."""
        from opentelemetry.metrics import Observation

        # Calculate average active connections over the sample window
        if self.connection_pool_samples:
            avg_active = sum(v for _, v in self.connection_pool_samples) / len(self.connection_pool_samples)
        else:
            # Fallback to current pool count if no samples yet
            avg_active = self.db_connection_pool.count

        yield Observation(avg_active, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_connection_pool_queue_depth(self, options):
        """Callback for connection pool queue depth gauge."""
        from opentelemetry.metrics import Observation

        # Calculate average queue depth over the sample window
        if self.connection_queue_samples:
            avg_queue = sum(v for _, v in self.connection_queue_samples) / len(self.connection_queue_samples)
        else:
            # Fallback to current queue length if no samples yet
            avg_queue = len(self.db_connection_pool.queue)

        yield Observation(avg_queue, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_thread_pool_active(self, options):
        """Callback for thread pool active threads gauge (Phase 3.1)."""
        from opentelemetry.metrics import Observation

        # Report current active threads (threads in use)
        active_threads = self.thread_pool.count

        yield Observation(active_threads, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

    def _report_thread_pool_queue(self, options):
        """Callback for thread pool queue depth gauge (Phase 3.1)."""
        from opentelemetry.metrics import Observation

        # Report current queue depth (requests waiting for thread)
        queue_depth = len(self.thread_pool.queue)

        yield Observation(queue_depth, {
            "component.id": self.id,
            "sim.time": self.env.now
        })

class AutoScalingGroup(EnrichedComponent):
    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "AutoScalingGroup")
    def _apply_hcl_config(self):
        self.scaling_policy = AutoScalingPolicy(min_size=self.iac_config.get('min_size',1), max_size=self.iac_config.get('max_size',1), desired_capacity=self.iac_config.get('desired_capacity',1))
    def get_active_instances(self) -> list:
        """Returns a list of the running compute agent objects."""
        return [inst for inst in self.connections.get('instances', []) if inst.state.operational == "RUNNING"]