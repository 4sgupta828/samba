from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import random

class RequestGateway(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "RequestGateway")

        # Load balancers are lightweight routing components with minimal resource usage
        # Set baseline resource state
        self.state.cpu_utilization = 2.0  # ~2% baseline for routing operations
        self.state.memory_usage_mb = 50.0  # ~50MB for routing tables, health checks, TLS state

        # Initialize dynamics engine if enabled
        self.use_dynamics = False
        self.dynamics = None
        global_config = get_simulation_config()
        if hasattr(global_config, 'dynamics') and global_config.dynamics.get('enabled', False):
            lb_dynamics_config = global_config.dynamics.get('components', {}).get('load_balancer', {})
            if lb_dynamics_config.get('enabled', False):
                self.use_dynamics = True
                # Load balancer-specific dynamics configuration
                dynamics_params = lb_dynamics_config.get('config', {})
                dynamics_cfg = DynamicsConfig(
                    latency_base=dynamics_params.get('latency_base', 5.0),
                    cpu_from_throughput_coef=dynamics_params.get('cpu_from_throughput_coef', 0.01),
                    cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 0.5),
                    latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 50.0),
                    latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 30.0),
                    error_base=dynamics_params.get('error_base', 0.0001),
                    error_latency_threshold=dynamics_params.get('error_latency_threshold', 200.0),
                    error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 80.0),
                    noise_enabled=dynamics_params.get('noise_enabled', True),
                )
                self.dynamics = MetricsDynamicsEngine(config=dynamics_cfg)

        self.http_requests_counter = self.meter.create_counter(
            "http.server.requests",
            description="Number of incoming HTTP requests",
            unit="1",
        )
        # Request latency histogram (uses default OTel buckets; size reduction via SummarizedJsonMetricExporter)
        self.request_latency = self.meter.create_histogram(
            "http.server.request.duration",
            description="End-to-end HTTP request duration",
            unit="ms"
        )

        # NEW: Request type to service mapping for e-commerce architecture
        # This will be populated by connections to services
        self.request_to_service_map = {}

        # Track request count for dynamic CPU usage
        self.request_count = 0
        self.last_request_count = 0

    def run(self):
        """Start background processes including dynamics update loop."""
        # Call parent run() to set up the component
        yield self.env.process(super().run())

        # Start dynamics update loop if enabled
        if self.use_dynamics:
            self.env.process(self._update_dynamics_loop())

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second."""
        while True:
            yield self.env.timeout(1.0)  # Update every simulation second

            # Calculate throughput (requests per second)
            requests_delta = self.request_count - self.last_request_count
            self.last_request_count = self.request_count

            # Update dynamics engine
            # Load balancers don't have connections or queue depth in the traditional sense
            self.dynamics.update(
                dt=1.0,
                external_throughput=requests_delta,
                active_connections=0,
                queue_depth=0
            )

    def register_service(self, service, request_types):
        """
        Register a service to handle specific request types.

        Args:
            service: ApiService instance
            request_types: List of request types this service handles
        """
        for request_type in request_types:
            self.request_to_service_map[request_type] = service
        self._emit_log("INFO", f"Registered service {service.service_name} for requests: {request_types}")

    def get_service_for_request(self, request_type: str):
        """
        Get the appropriate service for a given request type.

        Args:
            request_type: Type of request

        Returns:
            ApiService instance or None if not found
        """
        return self.request_to_service_map.get(request_type)

    def get_backend_target(self):
        """
        Legacy method: Simple load balancing to pick a random compute agent.
        Used for backward compatibility when no services are configured.
        """
        # First check for standalone compute instances (aws_instance resources)
        standalone_instances = self.connections.get('compute_instances', [])
        if standalone_instances:
            # Filter to only healthy instances
            healthy_instances = [inst for inst in standalone_instances
                               if inst.state.operational == 'RUNNING']
            if healthy_instances:
                return random.choice(healthy_instances)

        # Fall back to ASG-managed instances
        asg = self.connections.get('app_tier')
        if not asg:
            return None

        # Get the active compute instances from the ASG
        active_instances = asg.get_active_instances()
        if not active_instances:
            return None
        return random.choice(active_instances)

    def handle_request(self, request_type: str):
        """Simulates handling an incoming request.

        OpenTelemetry's sampler (configured in setup.py) will automatically
        decide whether to sample this trace based on the configured rate.
        """
        # Always create a span - OpenTelemetry's sampler will decide whether to export it
        with self._start_span(f"HTTP GET /api/{request_type}", parent_span_context=None) as span:
            span.set_attribute("http.method", "GET")

            # Only propagate tracing to children if this span is being recorded
            # (i.e., the sampler decided to sample this trace)
            if span.is_recording():
                # Pass span context to children
                from opentelemetry import trace
                span_ctx = trace.set_span_in_context(span)
                yield from self._process_request(request_type, span, span_ctx)
            else:
                # Span is not being recorded (sampler dropped it), don't create child spans
                yield from self._process_request(request_type, span, None)

    def _process_request(self, request_type: str, span, span_ctx):
        """Internal method to process request with service routing."""
        # Track start time for latency measurement
        start_time = self.env.now

        # Track request count and update CPU usage
        # Load balancers have very low CPU overhead per request (~0.1% per concurrent request)
        self.request_count += 1

        # Update CPU utilization based on dynamics or simple model
        if self.use_dynamics and self.dynamics:
            self.state.cpu_utilization = self.dynamics.get_cpu_percent()

            # Circuit breaker: if error rate is too high, return 503
            if self.dynamics.get_error_rate() > 0.1:  # 10% error threshold
                self._emit_log("ERROR", "Circuit breaker triggered due to high error rate")
                self._record_error("circuit_breaker_open", {"http.status_code": 503})
                self.http_requests_counter.add(1, {
                    "http.status_code": 503,
                    "component.id": self.id
                })
                latency_ms = (self.env.now - start_time) * 1000
                self.request_latency.record(latency_ms, {
                    "http.status_code": 503,
                    "request_type": request_type,
                    "component.id": self.id
                })
                span.set_attribute("http.status_code", 503)
                span.set_attribute("error", True)
                span.set_attribute("error.type", "circuit_breaker_open")
                return

            # Add load balancer latency from dynamics
            lb_latency = self.dynamics.get_latency() / 1000.0  # Convert ms to seconds
            yield self.env.timeout(lb_latency)
        else:
            # Original behavior
            # Estimate concurrent requests from recent activity
            concurrent_requests = min(self.request_count % 100, 50)  # Simple model
            self.state.cpu_utilization = 2.0 + (concurrent_requests * 0.1)  # 2% baseline + 0.1% per request
            self.state.cpu_utilization = min(self.state.cpu_utilization, 15.0)  # Cap at 15% for load balancers

        self._emit_log("DEBUG", f"Received request for {request_type}")  # Reduced from INFO to DEBUG

        # Route based on actual topology connections (sync_http edges to services)
        # Get all services connected to this gateway
        connected_services = [
            conn for conn in self.connections.values()
            if hasattr(conn, 'service_name')  # Check if it's a service
        ]

        if connected_services:
            # Route to one of the connected services (round-robin/random)
            import random
            target = random.choice(connected_services)
            self._emit_log("DEBUG", f"Routing {request_type} to service: {target.service_name} (topology-based)")
            span.set_attribute("routing.target", "service")
            span.set_attribute("service.name", target.service_name)
            span.set_attribute("routing.method", "topology")
        else:
            # Fall back to direct compute routing (legacy/backward compatibility)
            self._emit_log("DEBUG", f"No services connected, routing to compute agents directly")
            span.set_attribute("routing.target", "compute")
            target = self.get_backend_target()

        if not target:
            self._emit_log("ERROR", "No healthy backend target found")
            # Explicitly record HTTP error metric
            self._record_error("http_503_no_backend", {"http.status_code": 503})

            self.http_requests_counter.add(1, {
                "http.status_code": 503,
                "component.id": self.id
            })
            # Record latency even for failed requests
            latency_ms = (self.env.now - start_time) * 1000
            self.request_latency.record(latency_ms, {
                "http.status_code": 503,
                "request_type": request_type,
                "component.id": self.id
            })
            # Update span with error info
            span.set_attribute("http.status_code", 503)
            span.set_attribute("error", True)
            span.set_attribute("error.type", "no_backend_available")
            return

        try:
            # Forward the request to the service or compute agent with span context as parameter
            # This prevents concurrent requests from overwriting each other's tracing context
            should_trace = span_ctx is not None
            yield self.env.process(target.handle_request(request_type, should_trace=should_trace, parent_span_context=span_ctx))

            self.http_requests_counter.add(1, {
                "http.status_code": 200,
                "component.id": self.id
            })
            # Record successful request latency
            latency_ms = (self.env.now - start_time) * 1000
            self.request_latency.record(latency_ms, {
                "http.status_code": 200,
                "request_type": request_type,
                "component.id": self.id
            })
            span.set_attribute("http.status_code", 200)

        except Exception as e:
            self._emit_log("ERROR", f"Request failed: {e}")
            # Explicitly record HTTP error metric
            self._record_error("http_500_internal", {"http.status_code": 500, "exception.type": type(e).__name__})

            self.http_requests_counter.add(1, {
                "http.status_code": 500,
                "component.id": self.id
            })
            # Record error request latency
            latency_ms = (self.env.now - start_time) * 1000
            self.request_latency.record(latency_ms, {
                "http.status_code": 500,
                "request_type": request_type,
                "component.id": self.id
            })
            # Update span with error info
            span.set_attribute("http.status_code", 500)
            span.set_attribute("error", True)
            span.add_event("exception", {
                "exception.type": type(e).__name__,
                "exception.message": str(e)
            })