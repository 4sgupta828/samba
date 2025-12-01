"""
Workload Generator Module.
Drives the simulation by generating requests based on configured patterns.

Features realistic client behavior:
- Connection pool (limited concurrent connections)
- Request timeout handling
- Circuit breaker pattern (fail-fast during outages)
- Backpressure (queue saturation)
"""
import simpy
import yaml
import random
import math
from typing import Dict, List, Optional
from opentelemetry import metrics

from src.workloads import patterns
from src.workloads.circuit_breaker import CircuitBreaker
from src.core.simulation_config import get_simulation_config


class WorkloadGenerator:
    def __init__(
        self,
        env: simpy.Environment,
        config_path: str,
        component_registry: Dict,
        connection_pool_size: Optional[int] = None,
        request_timeout: Optional[float] = None,
        max_queue_size: Optional[int] = None
    ):
        self.env = env
        self.component_registry = component_registry
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Pre-process the request mix for weighted random choice
        self.request_types: List[str] = [item['type'] for item in self.config['request_mix']]
        self.request_weights: List[int] = [item['weight'] for item in self.config['request_mix']]

        # Load workload generator configuration (with override support)
        sim_config = get_simulation_config()
        wg_config = sim_config.workload_generator if hasattr(sim_config, 'workload_generator') else None

        # Connection pool configuration (mimics real HTTP client behavior)
        # Priority: explicit parameters > config file > fallback defaults
        if connection_pool_size is not None:
            # Explicit override (e.g., from safe workload calculation)
            self.connection_pool_size = connection_pool_size
            self.request_timeout = request_timeout if request_timeout is not None else 30.0
            self.max_queue_size = max_queue_size if max_queue_size is not None else connection_pool_size * 2
        elif wg_config:
            # Load from config file
            self.connection_pool_size = wg_config.connection_pool_size
            self.request_timeout = wg_config.request_timeout_seconds
            self.max_queue_size = wg_config.max_queue_size
        else:
            # Fallback defaults if config not available
            # FIXED: Increased from 50 to 200 to handle peak RPS (200) with high latency (200ms)
            # Required: 200 RPS × 0.2s = 40 connections minimum, 5x buffer = 200
            self.connection_pool_size = 200
            self.request_timeout = 30.0
            self.max_queue_size = 100

        # Connection pool (simpy.Resource limits concurrent requests)
        self.connection_pool = simpy.Resource(env, capacity=self.connection_pool_size)

        # Circuit breaker configuration
        if wg_config and wg_config.circuit_breaker:
            cb_config = wg_config.circuit_breaker
            self.circuit_breaker_enabled = cb_config.enabled
            self.circuit_breaker: Optional[CircuitBreaker] = None
            if self.circuit_breaker_enabled:
                self.circuit_breaker = CircuitBreaker(
                    failure_threshold=cb_config.failure_threshold,
                    success_threshold=cb_config.success_threshold,
                    window_size=cb_config.window_size,
                    open_duration=cb_config.open_duration_seconds,
                    half_open_max_requests=cb_config.half_open_max_requests,
                )
        else:
            # Fallback: circuit breaker enabled with defaults
            # FIXED: Relaxed thresholds to prevent false positives during healthy baseline
            self.circuit_breaker_enabled = True
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=0.9,          # Opens at 90% failure (was 0.7)
                success_threshold=0.8,
                window_size=100,                # Larger window for smoother decisions (was 50)
                open_duration=10.0,             # Shorter duration to recover faster (was 15.0)
                half_open_max_requests=10,
            )

        # Metrics tracking
        self._setup_metrics()

        # Request outcome tracking
        self.total_requests_attempted = 0
        self.total_requests_successful = 0
        self.total_requests_failed = 0
        self.total_requests_rejected_circuit_open = 0
        self.total_requests_rejected_queue_full = 0
        self.total_requests_timeout = 0

        # Queue tracking (we'll track in-flight requests manually)
        self.in_flight_requests = 0

    def _setup_metrics(self):
        """Setup OpenTelemetry metrics for workload generator."""
        meter = metrics.get_meter(__name__)

        # Connection pool metrics
        self.connection_pool_utilization_gauge = meter.create_observable_gauge(
            "workload.connection_pool.utilization",
            description="Connection pool utilization (active connections / total)",
            unit="1",
            callbacks=[self._observe_connection_pool_utilization]
        )

        self.connection_pool_active_gauge = meter.create_observable_gauge(
            "workload.connection_pool.active",
            description="Number of active connections in use",
            unit="1",
            callbacks=[self._observe_connection_pool_active]
        )

        # In-flight request tracking (queue depth)
        self.in_flight_requests_gauge = meter.create_observable_gauge(
            "workload.requests.in_flight",
            description="Number of requests currently in flight",
            unit="1",
            callbacks=[self._observe_in_flight_requests]
        )

        # Request outcome counters
        self.requests_counter = meter.create_counter(
            "workload.requests",
            description="Total requests attempted by workload generator",
            unit="1",
        )

        self.requests_rejected_counter = meter.create_counter(
            "workload.requests.rejected",
            description="Requests rejected (circuit breaker, queue full, etc.)",
            unit="1",
        )

        # Circuit breaker state
        if self.circuit_breaker_enabled:
            self.circuit_breaker_state_gauge = meter.create_observable_gauge(
                "workload.circuit_breaker.state",
                description="Circuit breaker state (0=closed, 1=open, 2=half_open)",
                unit="1",
                callbacks=[self._observe_circuit_breaker_state]
            )

    def _observe_connection_pool_utilization(self, options):  # noqa: ARG002
        """Callback for connection pool utilization gauge."""
        utilization = self.connection_pool.count / self.connection_pool_size if self.connection_pool_size > 0 else 0.0
        yield metrics.Observation(utilization, {})

    def _observe_connection_pool_active(self, options):  # noqa: ARG002
        """Callback for active connections gauge."""
        yield metrics.Observation(self.connection_pool.count, {})

    def _observe_in_flight_requests(self, options):  # noqa: ARG002
        """Callback for in-flight requests gauge."""
        yield metrics.Observation(self.in_flight_requests, {})

    def _observe_circuit_breaker_state(self, options):  # noqa: ARG002
        """Callback for circuit breaker state gauge."""
        if not self.circuit_breaker:
            yield metrics.Observation(0, {})
            return

        state_map = {"closed": 0, "open": 1, "half_open": 2}
        state_value = state_map.get(self.circuit_breaker.get_state(), 0)
        yield metrics.Observation(state_value, {})

    def run(self):
        """Main generator process to create traffic."""
        print(f"[{self.env.now:.2f}s] WorkloadGenerator starting with '{self.config['name']}' profile.")
        print(f"[{self.env.now:.2f}s] Connection pool: {self.connection_pool_size} connections")
        print(f"[{self.env.now:.2f}s] Request timeout: {self.request_timeout}s")
        print(f"[{self.env.now:.2f}s] Circuit breaker: {'enabled' if self.circuit_breaker_enabled else 'disabled'}")

        gateway = next((c for c in self.component_registry.values() if c.type == 'RequestGateway'), None)
        if not gateway:
            print("ERROR: [WorkloadGenerator] No RequestGateway found to send workload to. Stopping.")
            return

        # Wait until at least one healthy backend is available before starting workload
        print(f"[{self.env.now:.2f}s] Waiting for healthy backend targets...")
        while True:
            # Check if we have services (microservices architecture) or direct compute (legacy)
            has_services = len(gateway.request_to_service_map) > 0
            has_direct_compute = gateway.get_backend_target() is not None

            # For services, check that at least one service has healthy pods
            services_ready = False
            if has_services:
                # Check that at least one service can handle requests
                for service in gateway.request_to_service_map.values():
                    target = service.get_pod_target()
                    if target is not None:
                        services_ready = True
                        break

            if (has_services and services_ready) or has_direct_compute:
                if has_services:
                    print(f"[{self.env.now:.2f}s] Healthy services found ({len(gateway.request_to_service_map)} request types mapped). Starting workload generation.")
                else:
                    print(f"[{self.env.now:.2f}s] Healthy backend found. Starting workload generation.")
                break
            yield self.env.timeout(1.0)  # Check every second

        while True:
            # 1. Calculate how long to wait until the next request (based on time pattern)
            inter_arrival_time = patterns.get_inter_arrival_time(self.config, self.env.now)

            # If the wait time is infinite, stop generating for a while to avoid busy-looping
            if math.isinf(inter_arrival_time):
                yield self.env.timeout(60) # Check again in 60s
                continue

            yield self.env.timeout(inter_arrival_time)

            # 2. Choose what kind of request to send based on the mix weights
            selected_request_type = random.choices(self.request_types, self.request_weights, k=1)[0]

            # 3. Send the request through connection pool (spawns as separate process)
            # This allows multiple concurrent requests up to connection_pool_size
            self.env.process(self._send_request(gateway, selected_request_type))

    def _send_request(self, gateway, request_type: str):
        """
        Send a request through the connection pool with circuit breaker and timeout.

        This mimics real HTTP client behavior:
        1. Check circuit breaker (fail-fast if open)
        2. Acquire connection from pool (blocks if pool exhausted)
        3. Send request with timeout
        4. Record outcome and update circuit breaker

        State tracking:
        - in_flight_requests: Incremented when we start trying to send (includes waiting for connection)
        - connection_acquired: Track whether we successfully got a connection (must release)
        """
        self.total_requests_attempted += 1
        self.requests_counter.add(1, {"type": "attempted"})

        # Check circuit breaker first (fail-fast)
        if self.circuit_breaker_enabled and self.circuit_breaker:
            if not self.circuit_breaker.should_allow_request(self.env.now):
                # Circuit is open - reject immediately
                self.total_requests_rejected_circuit_open += 1
                self.requests_rejected_counter.add(1, {"reason": "circuit_breaker_open"})
                # Don't even try to send - this is the whole point of circuit breaker!
                return

        # Check if queue is full (backpressure / load shedding)
        if self.in_flight_requests >= self.max_queue_size:
            self.total_requests_rejected_queue_full += 1
            self.requests_rejected_counter.add(1, {"reason": "queue_full"})
            if self.circuit_breaker_enabled and self.circuit_breaker:
                self.circuit_breaker.record_failure(self.env.now)
            return

        # Track in-flight request (includes time waiting for connection)
        self.in_flight_requests += 1
        connection_acquired = False  # Track if we successfully got a connection
        connection_request = None

        try:
            # Phase 1: Try to acquire connection from pool (blocks if pool exhausted)
            connection_request = self.connection_pool.request()
            connection_timeout = self.env.timeout(self.request_timeout)

            # Wait for connection with timeout
            result = yield connection_request | connection_timeout

            # Check if we got the connection or timed out waiting
            if connection_request not in result:
                # Timed out waiting for connection (pool exhausted)
                # Note: connection_request is still queued in SimPy, but we give up
                self.total_requests_timeout += 1
                self.requests_counter.add(1, {"type": "timeout", "phase": "connection_wait"})
                if self.circuit_breaker_enabled and self.circuit_breaker:
                    self.circuit_breaker.record_failure(self.env.now)
                return  # Exit early - connection_acquired is still False, won't try to release

            # Successfully acquired connection
            connection_acquired = True

            # Phase 2: Send request through gateway with separate timeout
            try:
                request_process = self.env.process(gateway.handle_request(request_type))
                request_timeout = self.env.timeout(self.request_timeout)

                result = yield request_process | request_timeout

                if request_process not in result:
                    # Request execution timed out
                    self.total_requests_timeout += 1
                    self.requests_counter.add(1, {"type": "timeout", "phase": "request_execution"})
                    if self.circuit_breaker_enabled and self.circuit_breaker:
                        self.circuit_breaker.record_failure(self.env.now)
                else:
                    # Request completed successfully
                    self.total_requests_successful += 1
                    self.requests_counter.add(1, {"type": "success"})
                    if self.circuit_breaker_enabled and self.circuit_breaker:
                        self.circuit_breaker.record_success(self.env.now)

            except Exception:
                # Request failed with exception
                self.total_requests_failed += 1
                self.requests_counter.add(1, {"type": "failed"})
                if self.circuit_breaker_enabled and self.circuit_breaker:
                    self.circuit_breaker.record_failure(self.env.now)

        finally:
            # Cleanup: Release connection only if we successfully acquired it
            if connection_acquired and connection_request:
                self.connection_pool.release(connection_request)

            # Always decrement in-flight counter
            self.in_flight_requests -= 1

    def get_statistics(self) -> dict:
        """Get workload generator statistics."""
        stats = {
            "total_requests_attempted": self.total_requests_attempted,
            "total_requests_successful": self.total_requests_successful,
            "total_requests_failed": self.total_requests_failed,
            "total_requests_timeout": self.total_requests_timeout,
            "total_requests_rejected_circuit_open": self.total_requests_rejected_circuit_open,
            "total_requests_rejected_queue_full": self.total_requests_rejected_queue_full,
            "connection_pool_size": self.connection_pool_size,
            "connection_pool_active": self.connection_pool.count,
            "in_flight_requests": self.in_flight_requests,
        }

        # Add circuit breaker stats if enabled
        if self.circuit_breaker_enabled and self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_statistics()

        return stats