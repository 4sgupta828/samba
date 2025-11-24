"""
Service Layer Components.

Implements two service architectures:

1. Service (New): Lightweight coordinator for Service/Pod/Node architecture
   - Just routes requests to healthy pods
   - Holds connections and processing pipeline definition
   - No computation logic

2. ApiService (Legacy): Original service with computation logic
   - For backward compatibility with existing topologies
   - Will be deprecated once all topologies migrate to Service/Pod architecture
"""
from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy
import random


class Service(EnrichedComponent):
    """
    Lightweight service coordinator (new architecture).

    A Service is a logical grouping that:
    - Routes requests to healthy pod instances (load balancing)
    - Holds connections (dep_*, ext_*, database, cache, queue_in, queue_out)
    - Defines processing pipeline for pods to execute
    - Does NOT perform any computation itself

    All computation happens in Pod instances.
    """

    def __init__(self, env: simpy.Environment, component_id: str, service_name: str,
                 supported_request_types=None, processing_pipeline=None, desired_replicas=3):
        super().__init__(env, component_id, f"Service:{service_name}")
        self.service_name = service_name
        self.supported_request_types = supported_request_types or ["GET", "POST"]
        self.processing_pipeline = processing_pipeline or self._default_pipeline()
        self.desired_replicas = desired_replicas  # Target replica count for controller

        # Pods managed by DeploymentController
        self.pods = []  # List of Pod instances

        # Metrics (service-level aggregation)
        self.service_requests_counter = self.meter.create_counter(
            f"service.{service_name}.requests",
            description=f"Number of requests routed by {service_name}",
            unit="1",
        )
        self.service_errors_counter = self.meter.create_counter(
            f"service.{service_name}.errors",
            description=f"Number of errors in {service_name}",
            unit="1",
        )

    def _default_pipeline(self):
        """
        Default processing pipeline if none specified.

        Pipeline execution is constrained by topology:
        - Each step only executes if the required connection exists
        - Missing connections cause steps to be skipped automatically
        """
        return [
            {"type": "cache_check"},
            {"type": "service_calls", "probability": 0.7},
            {"type": "db_query"},
            {"type": "external_calls", "probability": 0.3},
            {"type": "queue_publish", "probability": 0.5}
        ]

    def handle_request(self, request_type: str, should_trace: bool = False, parent_span_context=None):
        """
        Handle incoming service request by routing to a healthy pod.

        Args:
            request_type: Type of request (must be in supported_request_types)
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Verify this service supports this request type
        if request_type not in self.supported_request_types:
            self._emit_log("ERROR", f"Unsupported request type '{request_type}' for {self.service_name}")
            self.service_errors_counter.add(1, {
                "error_type": "unsupported_request",
                "request_type": request_type,
                "component.id": self.id
            })
            raise Exception(f"Service {self.service_name} does not support request type: {request_type}")

        # Get a healthy pod to handle the request
        pod = self.get_pod_target()
        if not pod:
            self._emit_log("ERROR", f"No healthy pods available for {self.service_name}")
            self.service_errors_counter.add(1, {
                "error_type": "no_pods_available",
                "request_type": request_type,
                "component.id": self.id
            })
            raise Exception(f"No healthy pods available for service {self.service_name}")

        # Record request
        self.service_requests_counter.add(1, {
            "request_type": request_type,
            "component.id": self.id
        })

        # Forward to pod (pod executes the processing pipeline)
        try:
            yield from pod.handle_request(request_type, should_trace, parent_span_context)
        except Exception as e:
            # Record error
            self.service_errors_counter.add(1, {
                "error_type": type(e).__name__,
                "request_type": request_type,
                "component.id": self.id
            })
            raise

    def get_pod_target(self):
        """
        Load balance to a healthy pod instance.

        Returns:
            Pod: A healthy pod from the pool, or None if no pods available
        """
        healthy_pods = [p for p in self.pods if p.state.operational == "RUNNING"]
        if healthy_pods:
            return random.choice(healthy_pods)
        return None

    # No run() method - Service doesn't have background processes
    # DeploymentController handles pod lifecycle management


class ApiService(EnrichedComponent):
    """
    Base class for API services in the e-commerce platform.

    Each service:
    - Handles specific request types
    - Routes to its own pool of compute agents
    - Has dedicated database and dependencies
    - Can make service-to-service calls
    - Implements internal load balancing
    """

    def __init__(self, env: simpy.Environment, component_id: str, service_name: str):
        super().__init__(env, component_id, f"ApiService:{service_name}")
        self.service_name = service_name
        self.supported_request_types = []  # Override in subclasses

        # Initialize dynamics engine if enabled
        self.use_dynamics = False
        self.dynamics = None
        self.request_count = 0
        self.last_request_count = 0
        global_config = get_simulation_config()
        if hasattr(global_config, 'dynamics') and global_config.dynamics.get('enabled', False):
            service_dynamics_config = global_config.dynamics.get('components', {}).get('api_service', {})
            if service_dynamics_config.get('enabled', False):
                self.use_dynamics = True
                # API Service-specific dynamics configuration
                dynamics_params = service_dynamics_config.get('config', {})
                dynamics_cfg = DynamicsConfig(
                    latency_base=dynamics_params.get('latency_base', 50.0),
                    cpu_from_throughput_coef=dynamics_params.get('cpu_from_throughput_coef', 0.02),
                    cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 0.5),
                    latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 50.0),
                    latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 30.0),
                    error_base=dynamics_params.get('error_base', 0.005),
                    error_latency_threshold=dynamics_params.get('error_latency_threshold', 200.0),
                    error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 80.0),
                    noise_enabled=dynamics_params.get('noise_enabled', True),
                )
                self.dynamics = MetricsDynamicsEngine(config=dynamics_cfg)

        # Metrics
        self.service_requests_counter = self.meter.create_counter(
            f"service.{service_name}.requests",
            description=f"Number of requests handled by {service_name}",
            unit="1",
        )
        self.service_latency = self.meter.create_histogram(
            f"service.{service_name}.duration",
            description=f"Request duration for {service_name}",
            unit="ms"
        )
        self.service_errors_counter = self.meter.create_counter(
            f"service.{service_name}.errors",
            description=f"Number of errors in {service_name}",
            unit="1",
        )

        # Client-side metrics for external dependencies (from caller's POV)
        self.dependency_requests_counter = self.meter.create_counter(
            f"service.{service_name}.dependency.requests",
            description=f"Number of outbound requests to dependencies from {service_name}",
            unit="1",
        )
        self.dependency_latency = self.meter.create_histogram(
            f"service.{service_name}.dependency.duration",
            description=f"Request duration to dependencies from {service_name}",
            unit="ms"
        )
        self.dependency_errors_counter = self.meter.create_counter(
            f"service.{service_name}.dependency.errors",
            description=f"Number of errors calling dependencies from {service_name}",
            unit="1",
        )

    def run(self):
        """Start background processes including dynamics update loop and queue consumer."""
        # Start background processes BEFORE calling parent run()
        # (parent run() has an infinite loop and never completes)

        # Start dynamics update loop if enabled
        if self.use_dynamics:
            self.env.process(self._update_dynamics_loop())

        # Start queue consumer if this service consumes from a queue
        if 'queue_in' in self.connections:
            self.env.process(self._consume_from_queue())

        # Now call parent run() which will run forever
        yield self.env.process(super().run())

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second."""
        while True:
            yield self.env.timeout(1.0)  # Update every simulation second

            # Calculate throughput (requests per second)
            requests_delta = self.request_count - self.last_request_count
            self.last_request_count = self.request_count

            # Update dynamics engine
            self.dynamics.update(
                dt=1.0,
                external_throughput=requests_delta,
                active_connections=0,
                queue_depth=0
            )

    def get_compute_target(self):
        """
        Internal load balancing to select a compute agent from this service's pool.
        Supports both standalone instances and ASG-managed instances.
        """
        # Check for standalone compute instances in this service's pool
        standalone_instances = self.connections.get('compute_pool', [])
        if standalone_instances:
            # Filter to only healthy instances
            healthy_instances = [inst for inst in standalone_instances
                               if inst.state.operational == 'RUNNING']
            if healthy_instances:
                return random.choice(healthy_instances)

        # Fall back to ASG-managed instances
        asg = self.connections.get('compute_asg')
        if not asg:
            return None

        # Get the active compute instances from the ASG
        active_instances = asg.get_active_instances()
        if not active_instances:
            return None
        return random.choice(active_instances)

    def handle_request(self, request_type: str, should_trace: bool = False, parent_span_context=None):
        """
        Handle incoming service request.

        Args:
            request_type: Type of request (must be in supported_request_types)
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Verify this service supports this request type
        if request_type not in self.supported_request_types:
            self._emit_log("ERROR", f"Unsupported request type '{request_type}' for {self.service_name}")
            self.service_errors_counter.add(1, {
                "error_type": "unsupported_request",
                "request_type": request_type,
                "component.id": self.id
            })
            raise Exception(f"Service {self.service_name} does not support request type: {request_type}")

        # Create service-level span if tracing is enabled
        if should_trace and parent_span_context:
            with self._start_span(f"{self.service_name}:{request_type}", parent_span_context=parent_span_context) as span:
                span.set_attribute("service.name", self.service_name)
                span.set_attribute("request.type", request_type)
                yield from self._handle_request_internal(request_type, span)
        else:
            yield from self._handle_request_internal(request_type, None)

    def _execute_request_logic(self, request_type: str, span):
        """
        Execute the core request logic without recording metrics.

        This method can be overridden by subclasses to add service-to-service calls
        or other custom logic. The parent class will handle metrics recording.

        For generic services: forwards to compute agent + auto-discovers downstream calls
        For specialized services: override this method completely for custom behavior

        Args:
            request_type: Type of request to process
            span: OpenTelemetry span for tracing (can be None)
        """
        self._emit_log("DEBUG", f"[{self.service_name}] Processing {request_type}")

        # Apply dynamics-based behavior if enabled
        if self.use_dynamics and self.dynamics:
            # Check error rate first (circuit breaker style)
            if self.dynamics.get_error_rate() > 0.1:  # 10% error threshold
                self._emit_log("ERROR", f"[{self.service_name}] Circuit breaker open due to high error rate")
                self._record_error("circuit_breaker_open", {"request_type": request_type})
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", "circuit_breaker_open")
                raise Exception(f"Circuit breaker open for {self.service_name}")

            # Add service-level processing latency from dynamics
            service_latency = self.dynamics.get_latency() / 1000.0  # Convert ms to seconds
            yield self.env.timeout(service_latency)

            # Check if service-level error should occur
            if random.random() < self.dynamics.get_error_rate():
                self._emit_log("ERROR", f"[{self.service_name}] Service error due to dynamics")
                self._record_error("service_error", {"request_type": request_type})
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", "service_error")
                raise Exception(f"Service error in {self.service_name}")

        # Forward to compute agent (handles DB and cache calls internally)
        yield from self._process_with_compute_agent(request_type, span)

        # After compute agent processing, make downstream service calls based on topology
        # This enables generic services to follow topology edges automatically
        # Specialized services override _execute_request_logic() entirely, so this won't run for them
        yield from self._call_downstream_dependencies(request_type, span)

        if span:
            span.set_attribute("status", "success")

    def _process_with_compute_agent(self, request_type: str, span):
        """
        Forward request to compute agent for processing.

        This is separated from _execute_request_logic() so specialized services can
        call this directly when they want just the compute agent processing without
        automatic downstream dependency discovery.

        Args:
            request_type: Type of request to process
            span: OpenTelemetry span for tracing (can be None)
        """
        # Get a compute agent from this service's pool
        target = self.get_compute_target()

        if not target:
            self._emit_log("ERROR", f"[{self.service_name}] No healthy compute agents in pool")
            self._record_error("no_compute_available", {"request_type": request_type})
            if span:
                span.set_attribute("error", True)
                span.set_attribute("error.type", "no_compute_available")
            raise Exception(f"No healthy compute agents available for {self.service_name}")

        # Forward to compute agent with span context
        # This handles database and cache calls internally
        should_trace_compute = span is not None
        compute_span_ctx = None
        if should_trace_compute:
            from opentelemetry import trace
            compute_span_ctx = trace.set_span_in_context(span)

        yield self.env.process(target.handle_request(request_type, should_trace=should_trace_compute, parent_span_context=compute_span_ctx))

    def _call_downstream_dependencies(self, request_type: str, span):
        """
        Automatically discover and call downstream dependencies based on topology.

        This method examines self.connections to find downstream services and makes
        probabilistic calls to them, following the pattern used by specialized services.

        Specialized services can override _execute_request_logic() for custom behavior,
        while generic services use this automatic discovery.

        Args:
            request_type: Type of request being processed
            span: OpenTelemetry span for tracing (can be None)
        """
        # Iterate through connections to find service-to-service dependencies
        for conn_name, conn_target in self.connections.items():
            # Service-to-service RPC calls (dep_*)
            if conn_name.startswith('dep_'):
                target_service = conn_target
                # Probabilistic call - not every request needs to call every dependency
                # 70% chance to call each downstream service (realistic fan-out)
                if random.random() < 0.7:
                    try:
                        self._emit_log("DEBUG", f"[{self.service_name}] Calling downstream service {conn_name}")

                        # Propagate tracing to service-to-service call
                        should_trace_dep = span is not None
                        dep_span_ctx = None
                        if should_trace_dep:
                            from opentelemetry import trace
                            dep_span_ctx = trace.set_span_in_context(span)

                        # Call downstream service with one of its supported request types
                        if hasattr(target_service, 'supported_request_types') and target_service.supported_request_types:
                            dep_request_type = random.choice(target_service.supported_request_types)
                        else:
                            dep_request_type = request_type  # Use same request type as fallback

                        dep_start = self.env.now
                        yield self.env.process(target_service.handle_request(
                            dep_request_type,
                            should_trace=should_trace_dep,
                            parent_span_context=dep_span_ctx
                        ))
                        dep_latency = (self.env.now - dep_start) * 1000  # Convert to ms

                        # NOTE: No dependency metrics for internal service calls
                        # Internal services emit their own server-side metrics (service.{name}.requests, etc.)
                        # Dependency metrics are only for external black-box services

                        if span:
                            span.add_event(f"downstream_call", {
                                "service": conn_name,
                                "latency_ms": dep_latency
                            })

                    except Exception as e:
                        # NOTE: No dependency error metrics for internal service calls
                        # Internal services emit their own server-side error metrics

                        # Non-fatal - log and continue (some downstream calls are optional)
                        self._emit_log("WARN", f"[{self.service_name}] Downstream call to {conn_name} failed: {e}")
                        if span:
                            span.add_event(f"downstream_call_failed", {
                                "service": conn_name,
                                "error": str(e)
                            })

            # External service calls (ext_*)
            elif conn_name.startswith('ext_'):
                external_service = conn_target
                # Lower probability for external calls (more expensive, often optional)
                if random.random() < 0.3:
                    try:
                        self._emit_log("DEBUG", f"[{self.service_name}] Calling external service {conn_name}")

                        # Propagate tracing
                        should_trace_ext = span is not None
                        ext_span_ctx = None
                        if should_trace_ext:
                            from opentelemetry import trace
                            ext_span_ctx = trace.set_span_in_context(span)

                        # External services typically use GET or POST
                        ext_request_type = random.choice(['GET', 'POST'])

                        ext_start = self.env.now
                        yield self.env.process(external_service.handle_request(
                            ext_request_type,
                            should_trace=should_trace_ext,
                            parent_span_context=ext_span_ctx
                        ))
                        ext_latency = (self.env.now - ext_start) * 1000

                        # Record client-side metrics for successful external dependency call
                        self.dependency_requests_counter.add(1, {
                            "status": "success",
                            "dependency_type": "external",
                            "dependency_id": external_service.id,
                            "dependency_name": conn_name,
                            "component.id": self.id
                        })
                        self.dependency_latency.record(ext_latency, {
                            "dependency_type": "external",
                            "dependency_id": external_service.id,
                            "dependency_name": conn_name,
                            "component.id": self.id
                        })

                        if span:
                            span.add_event("external_call", {
                                "service": conn_name,
                                "latency_ms": ext_latency
                            })

                    except Exception as e:
                        # Record error metrics for failed external dependency call
                        self.dependency_requests_counter.add(1, {
                            "status": "error",
                            "dependency_type": "external",
                            "dependency_id": getattr(external_service, 'id', 'unknown'),
                            "dependency_name": conn_name,
                            "component.id": self.id
                        })
                        self.dependency_errors_counter.add(1, {
                            "error_type": type(e).__name__,
                            "dependency_type": "external",
                            "dependency_id": getattr(external_service, 'id', 'unknown'),
                            "dependency_name": conn_name,
                            "component.id": self.id
                        })

                        # External calls can fail - handle gracefully
                        self._emit_log("WARN", f"[{self.service_name}] External call to {conn_name} failed: {e}")
                        if span:
                            span.add_event("external_call_failed", {
                                "service": conn_name,
                                "error": str(e)
                            })

            # Queue publishing (queue_out for async_produce)
            elif conn_name == 'queue_out':
                queue = conn_target
                # Probabilistic queue publishing (not every request generates a message)
                if random.random() < 0.5:
                    try:
                        self._emit_log("DEBUG", f"[{self.service_name}] Publishing message to queue")
                        # send_message() is a generator, so use yield from
                        yield from queue.send_message(f"{request_type}_data_{self.env.now}")

                        if span:
                            span.add_event("message_published", {"queue": conn_name})

                    except Exception as e:
                        self._emit_log("WARN", f"[{self.service_name}] Queue publish failed: {e}")
                        if span:
                            span.add_event("queue_publish_failed", {"error": str(e)})

    def _consume_from_queue(self):
        """
        Background process that continuously consumes messages from queue_in.

        This implements the async consumer pattern where a service pulls messages
        from a queue and processes them independently of incoming HTTP requests.

        Common pattern for:
        - Order fulfillment services
        - Email notification services
        - Background job processors
        """
        queue = self.connections.get('queue_in')
        if not queue:
            self._emit_log("ERROR", f"[{self.service_name}] queue_in connection not found")
            return

        self._emit_log("INFO", f"[{self.service_name}] Starting queue consumer for {queue.id}")

        while True:
            try:
                # Wait for a message from the queue
                # receive_message() is a generator, so use yield from
                msg = yield from queue.receive_message()

                self._emit_log("DEBUG", f"[{self.service_name}] Received message {msg.id} from queue")

                # Process the message by calling handle_request
                # Use a random request type from supported types
                if self.supported_request_types:
                    request_type = random.choice(self.supported_request_types)
                else:
                    request_type = "PROCESS"

                try:
                    # Process the message (this will call compute agents, DB, etc.)
                    # Note: Queue consumers typically don't use tracing (batch processing)
                    yield self.env.process(self.handle_request(request_type, should_trace=False))

                    # Successfully processed - delete the message
                    queue.delete_message(msg)
                    self._emit_log("DEBUG", f"[{self.service_name}] Successfully processed message {msg.id}")

                except Exception as e:
                    # Processing failed - message will become visible again after timeout
                    self._emit_log("ERROR", f"[{self.service_name}] Failed to process message {msg.id}: {e}")
                    # Don't delete - let visibility timeout return it to queue for retry

            except Exception as e:
                # Queue receive failed - log and retry after delay
                self._emit_log("WARN", f"[{self.service_name}] Queue receive failed: {e}")
                yield self.env.timeout(1.0)  # Wait 1s before retrying

    def _handle_request_internal(self, request_type: str, span):
        """
        Internal request handling with metrics recording.

        This method handles timing, metrics recording, and delegates actual work
        to _execute_request_logic() which can be overridden by subclasses.
        """
        start_time = self.env.now

        # Track request count
        self.request_count += 1

        try:
            # Execute the request logic (can be overridden by subclasses)
            yield from self._execute_request_logic(request_type, span)

            # Record success metrics
            latency_ms = (self.env.now - start_time) * 1000
            self.service_requests_counter.add(1, {
                "status": "success",
                "request_type": request_type,
                "component.id": self.id
            })
            self.service_latency.record(latency_ms, {
                "request_type": request_type,
                "component.id": self.id
            })

        except Exception as e:
            self._emit_log("ERROR", f"[{self.service_name}] Request failed: {e}")
            self._record_error("request_failed", {
                "request_type": request_type,
                "exception_type": type(e).__name__
            })

            # Record error metrics
            self.service_errors_counter.add(1, {
                "error_type": type(e).__name__,
                "request_type": request_type,
                "component.id": self.id
            })
            latency_ms = (self.env.now - start_time) * 1000
            self.service_latency.record(latency_ms, {
                "status": "error",
                "request_type": request_type,
                "component.id": self.id
            })
            if span:
                span.set_attribute("error", True)
                span.add_event("exception", {
                    "exception.type": type(e).__name__,
                    "exception.message": str(e)
                })
            raise
