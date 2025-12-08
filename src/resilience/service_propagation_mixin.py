"""
Service Propagation Mixin - Adds fault propagation capabilities to services.

This mixin adds resilience patterns (retry, circuit breaker, timeout) and
error propagation logic to service components. It transforms graceful error
handling into realistic cascading failures for GNN training.

Usage:
    from src.resilience.service_propagation_mixin import ServicePropagationMixin

    class ApiService(EnrichedComponent, ServicePropagationMixin):
        def __init__(self, ...):
            EnrichedComponent.__init__(...)
            ServicePropagationMixin.__init__(self, env)
"""
import random
import simpy
from typing import Dict, Any, Callable
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenException
from .retry_policy import RetryPolicy
from .propagation_config import PropagationConfig, get_default_propagation_config


class DependencyTimeoutException(Exception):
    """Exception raised when a dependency call times out."""
    pass


class DependencyFailureException(Exception):
    """Exception raised when a dependency fails and error propagates."""
    pass


class ServicePropagationMixin:
    """
    Mixin that adds fault propagation capabilities to service components.

    This mixin provides:
    1. Circuit breakers for each dependency
    2. Retry logic with exponential backoff
    3. Timeout detection
    4. Probabilistic error propagation
    5. Enhanced metrics for GNN training
    """

    def __init__(self, env: simpy.Environment, propagation_config: PropagationConfig = None):
        """
        Initialize propagation mixin.

        Args:
            env: SimPy environment
            propagation_config: Configuration for fault propagation behavior
        """
        self.env = env
        self.propagation_config = propagation_config or get_default_propagation_config()

        # Circuit breakers for each dependency (lazy initialization)
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Retry policies for each dependency (lazy initialization)
        self._retry_policies: Dict[str, RetryPolicy] = {}

        # Initialize propagation metrics (must be called after meter is initialized)
        self._propagation_metrics_initialized = False

    def _initialize_propagation_metrics(self, service_name: str):
        """
        Initialize propagation-specific metrics.

        Must be called after self.meter is initialized (after parent __init__).

        Args:
            service_name: Name of the service (for metric namespace)
        """
        if self._propagation_metrics_initialized:
            return

        # Circuit breaker state metrics (per dependency)
        self.circuit_breaker_state_gauge = self.meter.create_observable_gauge(
            f"service.{service_name}.dependency.circuit_breaker_state",
            callbacks=[self._report_circuit_breaker_states],
            description="Circuit breaker state (0=closed, 0.5=half-open, 1=open)"
        )

        # Retry metrics
        self.retry_counter = self.meter.create_counter(
            f"service.{service_name}.dependency.retries",
            description="Number of retry attempts on dependency calls",
            unit="1"
        )

        # Timeout metrics
        self.timeout_counter = self.meter.create_counter(
            f"service.{service_name}.dependency.timeouts",
            description="Number of timeout errors on dependency calls",
            unit="1"
        )

        # Propagated error metrics
        self.propagated_error_counter = self.meter.create_counter(
            f"service.{service_name}.errors.propagated",
            description="Number of errors propagated from dependencies",
            unit="1"
        )

        # Circuit breaker rejection metrics
        self.circuit_breaker_rejection_counter = self.meter.create_counter(
            f"service.{service_name}.dependency.circuit_breaker_rejections",
            description="Number of requests rejected by circuit breaker",
            unit="1"
        )

        self._propagation_metrics_initialized = True

    def _report_circuit_breaker_states(self, options):
        """Callback to report circuit breaker states as metrics."""
        # Return observations in the format expected by OpenTelemetry
        # Each observation should be a dict-like object with 'value' and 'attributes'
        for dep_name, cb in self._circuit_breakers.items():
            from opentelemetry.metrics import Observation
            yield Observation(
                value=cb.state.get_state_value(),
                attributes={
                    "dependency_name": dep_name,
                    "component.id": self.id
                }
            )

    def _get_or_create_circuit_breaker(self, dep_name: str, dep_type: str) -> CircuitBreaker:
        """
        Get or create circuit breaker for a dependency.

        Args:
            dep_name: Dependency name (e.g., "ext_payment_api")
            dep_type: Dependency type ('external', 'database', 'cache', 'service')

        Returns:
            CircuitBreaker instance
        """
        if dep_name not in self._circuit_breakers:
            config = self.propagation_config.get_circuit_breaker_config_for_dependency(dep_type)
            self._circuit_breakers[dep_name] = CircuitBreaker(
                config=config,
                dependency_name=dep_name,
                env=self.env
            )
        return self._circuit_breakers[dep_name]

    def _get_or_create_retry_policy(self, dep_name: str, dep_type: str) -> RetryPolicy:
        """
        Get or create retry policy for a dependency.

        Args:
            dep_name: Dependency name
            dep_type: Dependency type ('external', 'database', 'cache', 'service')

        Returns:
            RetryPolicy instance
        """
        if dep_name not in self._retry_policies:
            config = self.propagation_config.get_retry_config_for_dependency(dep_type)
            self._retry_policies[dep_name] = RetryPolicy(
                config=config,
                env=self.env
            )
        return self._retry_policies[dep_name]

    def call_dependency_with_propagation(
        self,
        dep_name: str,
        dep_type: str,
        call_func: Callable,
        span=None,
        source_id: str = None,
        target_id: str = None
    ):
        """
        Call a dependency with full propagation logic.

        This is the core method that implements:
        1. Network partition check
        2. Circuit breaker check
        3. Retry logic
        4. Timeout detection
        5. Error propagation

        Args:
            dep_name: Dependency name (for metrics/logging)
            dep_type: Dependency type ('external', 'database', 'cache', 'service')
            call_func: Function that makes the actual call (must be generator for SimPy)
            span: OpenTelemetry span (optional)
            source_id: Source component ID (for network partition checks)
            target_id: Target component ID (for network partition checks)

        Yields:
            SimPy timeout events

        Raises:
            CircuitBreakerOpenException: If circuit breaker is open
            DependencyTimeoutException: If call times out
            DependencyFailureException: If call fails and error propagates
        """
        # Check for network partition FIRST (before circuit breaker)
        if source_id and target_id:
            try:
                from src.components.network import check_network_partition
                check_network_partition(source_id, target_id, self._emit_log if hasattr(self, '_emit_log') else None)
            except Exception as e:
                # Add span event if available
                if span:
                    span.add_event("network_partition", {
                        "source": source_id,
                        "target": target_id,
                        "dependency": dep_name
                    })
                # Re-raise the exception
                raise

        # Get circuit breaker and check if request should proceed
        circuit_breaker = self._get_or_create_circuit_breaker(dep_name, dep_type)

        if not circuit_breaker.state.should_allow_request():
            # Circuit is open - reject immediately
            self.circuit_breaker_rejection_counter.add(1, {
                "dependency_name": dep_name,
                "dependency_type": dep_type,
                "component.id": self.id
            })

            if span:
                span.add_event("circuit_breaker_open", {
                    "dependency": dep_name,
                    "state": circuit_breaker.state.get_state_value()
                })

            raise CircuitBreakerOpenException(f"Circuit breaker open for {dep_name}")

        # Get retry policy
        retry_policy = self._get_or_create_retry_policy(dep_name, dep_type)

        # Get timeout threshold
        timeout_ms = self.propagation_config.get_timeout_for_dependency(dep_type)

        # Track total time for timeout detection
        call_start_time = self.env.now
        last_exception = None
        retry_count = 0

        for attempt in range(1, retry_policy.config.max_attempts + 1):
            try:
                # Check if we've already exceeded timeout (from retries)
                elapsed_time_ms = (self.env.now - call_start_time) * 1000
                if elapsed_time_ms >= timeout_ms:
                    # Timeout exceeded
                    self.timeout_counter.add(1, {
                        "dependency_name": dep_name,
                        "dependency_type": dep_type,
                        "component.id": self.id
                    })

                    if span:
                        span.add_event("dependency_timeout", {
                            "dependency": dep_name,
                            "elapsed_ms": elapsed_time_ms,
                            "timeout_ms": timeout_ms
                        })

                    # Record failure in circuit breaker
                    circuit_breaker.state.record_failure()

                    raise DependencyTimeoutException(
                        f"Dependency {dep_name} timed out after {elapsed_time_ms:.0f}ms"
                    )

                # Make the actual call
                attempt_start = self.env.now
                yield from call_func()
                attempt_duration = (self.env.now - attempt_start) * 1000

                # Success! Record in circuit breaker
                circuit_breaker.state.record_success()

                if span and retry_count > 0:
                    span.add_event("dependency_call_succeeded_after_retries", {
                        "dependency": dep_name,
                        "retry_count": retry_count,
                        "total_duration_ms": (self.env.now - call_start_time) * 1000
                    })

                return  # Success

            except Exception as e:
                last_exception = e
                retry_count = attempt - 1

                # Record retry metric
                if attempt > 1:
                    self.retry_counter.add(1, {
                        "dependency_name": dep_name,
                        "dependency_type": dep_type,
                        "attempt": attempt,
                        "component.id": self.id
                    })

                # If this was the last attempt, handle failure
                if attempt >= retry_policy.config.max_attempts:
                    # Record failure in circuit breaker
                    circuit_breaker.state.record_failure()

                    # Check if error should propagate
                    if self._should_propagate_error(dep_type, e):
                        # Propagate error
                        self.propagated_error_counter.add(1, {
                            "dependency_name": dep_name,
                            "dependency_type": dep_type,
                            "error_type": type(e).__name__,
                            "component.id": self.id
                        })

                        if span:
                            span.add_event("dependency_error_propagated", {
                                "dependency": dep_name,
                                "error": str(e),
                                "retry_count": retry_count
                            })

                        raise DependencyFailureException(
                            f"Dependency {dep_name} failed: {e}"
                        ) from e
                    else:
                        # Graceful handling - log but don't propagate
                        if hasattr(self, '_emit_log'):
                            self._emit_log("WARN", f"Dependency {dep_name} failed but handled gracefully: {e}")

                        if span:
                            span.add_event("dependency_error_handled", {
                                "dependency": dep_name,
                                "error": str(e),
                                "retry_count": retry_count
                            })

                        return  # Continue processing

                # Calculate backoff delay for retry
                delay_ms = retry_policy._calculate_backoff_delay(attempt)
                yield self.env.timeout(delay_ms / 1000.0)

                if span:
                    span.add_event("dependency_retry", {
                        "dependency": dep_name,
                        "attempt": attempt,
                        "delay_ms": delay_ms,
                        "error": str(e)
                    })

    def _should_propagate_error(self, dep_type: str, exception: Exception) -> bool:
        """
        Determine if an error should propagate or be handled gracefully.

        Uses probabilistic propagation based on configuration.

        Args:
            dep_type: Dependency type
            exception: Exception that occurred

        Returns:
            True if error should propagate, False if handled gracefully
        """
        # Timeout always causes error if configured
        if isinstance(exception, DependencyTimeoutException):
            return self.propagation_config.timeout_causes_error

        # Circuit breaker open always propagates
        if isinstance(exception, CircuitBreakerOpenException):
            return True

        # Probabilistic propagation for other errors
        return random.random() < self.propagation_config.error_propagation_probability
