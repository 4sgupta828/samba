"""
E-Commerce Service Layer Components.

Implements realistic microservices architecture with:
- ProductCatalogService: Product browsing and search
- OrderService: Order placement and management
- UserAccountService: User authentication and profiles
- InventoryService: Stock management and reservations
"""
from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy
import random


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
        should_trace_compute = span is not None
        compute_span_ctx = None
        if should_trace_compute:
            from opentelemetry import trace
            compute_span_ctx = trace.set_span_in_context(span)

        yield self.env.process(target.handle_request(request_type, should_trace=should_trace_compute, parent_span_context=compute_span_ctx))

        if span:
            span.set_attribute("status", "success")

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


class ProductCatalogService(ApiService):
    """
    Product Catalog Service - handles product browsing and search.

    Request Types:
    - browse_products: Browse product listings (calls InventoryService for stock)
    - search_products: Search for products by keyword
    - get_product_details: Get detailed product information (calls InventoryService)
    - get_recommendations: Get product recommendations

    Dependencies:
    - product_catalog_db: Product database (read-optimized)
    - cache: Hot products and search results
    - inventory_service: For real-time stock availability
    """

    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "product_catalog")
        self.supported_request_types = [
            "browse_products",
            "search_products",
            "get_product_details",
            "get_recommendations"
        ]

    def _execute_request_logic(self, request_type: str, span):
        """Override to add service-to-service calls for inventory availability."""
        # Requests that need real-time inventory data
        if request_type in ["browse_products", "get_product_details"]:
            self._emit_log("DEBUG", f"[{self.service_name}] Processing {request_type} with inventory check")

            # First, get product data from our own compute pool (cache + DB)
            # This is handled by the parent implementation
            yield from super()._execute_request_logic(request_type, span)

            # Then, call InventoryService for stock availability (if available)
            inventory_service = self.connections.get('inventory_service')
            if inventory_service:
                try:
                    # For browse_products, we might check multiple items
                    # For get_product_details, we check a single item
                    num_checks = 5 if request_type == "browse_products" else 1

                    for _ in range(num_checks):
                        # Propagate tracing to service-to-service call
                        should_trace_inventory = span is not None
                        inventory_span_ctx = None
                        if should_trace_inventory:
                            from opentelemetry import trace
                            inventory_span_ctx = trace.set_span_in_context(span)

                        self._emit_log("DEBUG", f"[{self.service_name}] Calling InventoryService.check_availability")

                        yield self.env.process(inventory_service.handle_request(
                            "check_availability",
                            should_trace=should_trace_inventory,
                            parent_span_context=inventory_span_ctx
                        ))

                    if span:
                        span.add_event("inventory_checked", {
                            "service": "inventory_service",
                            "num_checks": num_checks
                        })

                except Exception as e:
                    # Non-fatal - can still show products without stock info
                    self._emit_log("WARN", f"[{self.service_name}] Inventory check failed: {e}")
                    if span:
                        span.add_event("inventory_check_failed", {"error": str(e)})

            return

        # For all other request types (search_products, get_recommendations), use default handling
        yield from super()._execute_request_logic(request_type, span)


class OrderService(ApiService):
    """
    Order Service - handles order placement and management.

    Request Types:
    - place_order: Place a new order (calls InventoryService)
    - get_order_history: Get user's order history
    - get_order_status: Check order status
    - cancel_order: Cancel an existing order

    Dependencies:
    - orders_db: Orders database (ACID transactions)
    - message_queue: Async order processing
    - inventory_service: For stock reservation (service-to-service call)
    """

    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "order")
        self.supported_request_types = [
            "place_order",
            "get_order_history",
            "get_order_status",
            "cancel_order"
        ]

    def _execute_request_logic(self, request_type: str, span):
        """Override to add service-to-service call for place_order."""
        # Special handling for place_order - needs to call InventoryService
        if request_type == "place_order":
            self._emit_log("DEBUG", f"[{self.service_name}] Processing place_order with inventory check")

            # Step 1: Call InventoryService to reserve stock
            inventory_service = self.connections.get('inventory_service')
            if inventory_service:
                try:
                    self._emit_log("INFO", f"[{self.service_name}] Calling InventoryService.reserve_stock")

                    # Propagate tracing to service-to-service call
                    should_trace_inventory = span is not None
                    inventory_span_ctx = None
                    if should_trace_inventory:
                        from opentelemetry import trace
                        inventory_span_ctx = trace.set_span_in_context(span)

                    # Phase 3.3: Measure dependency latency to inherit upstream slowness
                    dep_start = self.env.now
                    yield self.env.process(inventory_service.handle_request(
                        "reserve_stock",
                        should_trace=should_trace_inventory,
                        parent_span_context=inventory_span_ctx
                    ))
                    dep_latency = (self.env.now - dep_start) * 1000  # Convert to ms

                    if span:
                        span.add_event("inventory_reserved", {"service": "inventory_service"})
                        span.set_attribute("dependency.inventory_service.latency_ms", dep_latency)

                except Exception as e:
                    self._emit_log("ERROR", f"[{self.service_name}] Inventory reservation failed: {e}")
                    if span:
                        span.set_attribute("error", True)
                        span.add_event("inventory_reservation_failed")
                    raise Exception("Order failed: Unable to reserve inventory")

            # Step 2: Continue with normal order processing (write to DB)
            # This is handled by calling the parent implementation
            yield from super()._execute_request_logic(request_type, span)

            # Step 3: Publish to message queue for async fulfillment
            queue = self.connections.get('message_queue')
            if queue:
                self._emit_log("DEBUG", f"[{self.service_name}] Publishing order to message queue")
                if span:
                    span.add_event("order_queued", {"queue": "order_fulfillment"})

            return

        # For all other request types, use default handling
        yield from super()._execute_request_logic(request_type, span)


class UserAccountService(ApiService):
    """
    User Account Service - handles user authentication and profiles.

    Request Types:
    - get_user_profile: Get user profile data (calls OrderService for recent orders)
    - update_user_profile: Update user profile
    - login: User authentication
    - register: New user registration

    Dependencies:
    - user_db: User database (credentials, profiles)
    - cache: Session tokens and auth data
    - order_service: For displaying recent orders on profile page
    """

    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "user_account")
        self.supported_request_types = [
            "get_user_profile",
            "update_user_profile",
            "login",
            "register"
        ]

    def _execute_request_logic(self, request_type: str, span):
        """Override to add service-to-service call for fetching recent orders."""
        # get_user_profile shows recent orders on the profile dashboard
        if request_type == "get_user_profile":
            self._emit_log("DEBUG", f"[{self.service_name}] Processing {request_type} with order history")

            # First, get user profile data from our own compute pool (cache + DB)
            yield from super()._execute_request_logic(request_type, span)

            # Then, call OrderService to get recent orders for the dashboard
            order_service = self.connections.get('order_service')
            if order_service:
                try:
                    self._emit_log("DEBUG", f"[{self.service_name}] Calling OrderService.get_order_history")

                    # Propagate tracing to service-to-service call
                    should_trace_orders = span is not None
                    order_span_ctx = None
                    if should_trace_orders:
                        from opentelemetry import trace
                        order_span_ctx = trace.set_span_in_context(span)

                    yield self.env.process(order_service.handle_request(
                        "get_order_history",
                        should_trace=should_trace_orders,
                        parent_span_context=order_span_ctx
                    ))

                    if span:
                        span.add_event("recent_orders_fetched", {"service": "order_service"})

                except Exception as e:
                    # Non-fatal - can still show profile without order history
                    self._emit_log("WARN", f"[{self.service_name}] Order history fetch failed: {e}")
                    if span:
                        span.add_event("order_history_failed", {"error": str(e)})

            return

        # For all other request types, use default handling
        yield from super()._execute_request_logic(request_type, span)


class InventoryService(ApiService):
    """
    Inventory Service - handles stock management.

    Request Types:
    - check_availability: Check if product is in stock
    - reserve_stock: Reserve stock for order (called by OrderService)
    - update_stock: Update stock levels
    - release_reservation: Release reserved stock (e.g., on order cancel)

    Dependencies:
    - inventory_db: Inventory database (strong consistency, row-level locking)

    Note: This is a leaf service (no downstream service dependencies)
    """

    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "inventory")
        self.supported_request_types = [
            "check_availability",
            "reserve_stock",
            "update_stock",
            "release_reservation"
        ]
