"""
Fault Propagation Configuration - Controls how failures cascade.

This module defines how faults propagate through the dependency graph:
- Error propagation probability
- Latency propagation multipliers
- Timeout thresholds
- Resource exhaustion triggers

These configurations are critical for generating realistic GNN training data
where faults cascade through multiple hops in the dependency graph.
"""
from dataclasses import dataclass
from .retry_policy import RetryConfig, STANDARD_RETRY, AGGRESSIVE_RETRY, CONSERVATIVE_RETRY
from .circuit_breaker import CircuitBreakerConfig


@dataclass
class PropagationConfig:
    """
    Configuration for fault propagation behavior.

    Controls how failures in dependencies affect calling services.
    """

    # Error Propagation
    error_propagation_probability: float = 0.5  # 50% of dep failures cause request failure
    timeout_causes_error: bool = True            # Timeouts should fail the request

    # Latency Propagation
    latency_propagation_enabled: bool = True
    retry_latency_multiplier: float = 1.0       # Multiply retry delay by this
    timeout_latency_add_ms: float = 0.0         # Extra latency when timeout occurs

    # Timeout Configuration (per dependency type)
    timeout_external_ms: float = 5000.0         # 5s for external APIs
    timeout_database_ms: float = 2000.0         # 2s for databases
    timeout_cache_ms: float = 1000.0            # 1s for caches
    timeout_service_ms: float = 3000.0          # 3s for service-to-service
    timeout_queue_ms: float = 10000.0           # 10s for queue operations

    # Resource Exhaustion
    thread_pool_exhaustion_threshold: float = 0.9   # 90% utilization
    thread_pool_exhaustion_error_rate: float = 0.2  # +20% error rate when exhausted
    connection_pool_wait_threshold_ms: float = 1000.0  # 1s wait is concerning

    # Retry Configuration (per dependency type)
    retry_external: RetryConfig = CONSERVATIVE_RETRY    # External APIs are expensive
    retry_database: RetryConfig = STANDARD_RETRY       # DB retries are standard
    retry_cache: RetryConfig = CONSERVATIVE_RETRY      # Cache should be fast
    retry_service: RetryConfig = STANDARD_RETRY        # Service calls are standard
    retry_queue: RetryConfig = AGGRESSIVE_RETRY        # Queue ops should succeed

    # Circuit Breaker Configuration (per dependency type)
    circuit_breaker_external: CircuitBreakerConfig = None  # Will be initialized in __post_init__
    circuit_breaker_database: CircuitBreakerConfig = None
    circuit_breaker_cache: CircuitBreakerConfig = None
    circuit_breaker_service: CircuitBreakerConfig = None

    def __post_init__(self):
        """Initialize circuit breaker configs with sensible defaults."""
        if self.circuit_breaker_external is None:
            self.circuit_breaker_external = CircuitBreakerConfig(
                failure_threshold=0.5,      # 50% error rate
                success_threshold=0.8,      # 80% success to close
                timeout_seconds=10.0,       # 10s before half-open
                sample_window=20,           # Look at last 20 calls
            )

        if self.circuit_breaker_database is None:
            self.circuit_breaker_database = CircuitBreakerConfig(
                failure_threshold=0.6,      # DB failures are more serious
                timeout_seconds=15.0,       # Give DB more time to recover
            )

        if self.circuit_breaker_cache is None:
            self.circuit_breaker_cache = CircuitBreakerConfig(
                failure_threshold=0.7,      # Cache can tolerate more failures
                timeout_seconds=5.0,        # Recover quickly
            )

        if self.circuit_breaker_service is None:
            self.circuit_breaker_service = CircuitBreakerConfig(
                failure_threshold=0.5,
                timeout_seconds=10.0,
            )

    def get_timeout_for_dependency(self, dep_type: str) -> float:
        """
        Get timeout threshold for a dependency type.

        Args:
            dep_type: Dependency type ('external', 'database', 'cache', 'service', 'queue')

        Returns:
            Timeout in milliseconds
        """
        timeout_map = {
            'external': self.timeout_external_ms,
            'database': self.timeout_database_ms,
            'cache': self.timeout_cache_ms,
            'service': self.timeout_service_ms,
            'queue': self.timeout_queue_ms,
        }
        return timeout_map.get(dep_type, self.timeout_service_ms)

    def get_retry_config_for_dependency(self, dep_type: str) -> RetryConfig:
        """
        Get retry configuration for a dependency type.

        Args:
            dep_type: Dependency type ('external', 'database', 'cache', 'service', 'queue')

        Returns:
            RetryConfig instance
        """
        retry_map = {
            'external': self.retry_external,
            'database': self.retry_database,
            'cache': self.retry_cache,
            'service': self.retry_service,
            'queue': self.retry_queue,
        }
        return retry_map.get(dep_type, self.retry_service)

    def get_circuit_breaker_config_for_dependency(self, dep_type: str) -> CircuitBreakerConfig:
        """
        Get circuit breaker configuration for a dependency type.

        Args:
            dep_type: Dependency type ('external', 'database', 'cache', 'service')

        Returns:
            CircuitBreakerConfig instance
        """
        cb_map = {
            'external': self.circuit_breaker_external,
            'database': self.circuit_breaker_database,
            'cache': self.circuit_breaker_cache,
            'service': self.circuit_breaker_service,
        }
        return cb_map.get(dep_type, self.circuit_breaker_service)


# Pre-configured propagation profiles

# AGGRESSIVE: Faults propagate strongly (good for training data diversity)
AGGRESSIVE_PROPAGATION = PropagationConfig(
    error_propagation_probability=0.7,  # 70% of dep failures cause request failure
    timeout_causes_error=True,
    thread_pool_exhaustion_error_rate=0.3,  # +30% error rate when exhausted
    retry_external=AGGRESSIVE_RETRY,
    retry_database=AGGRESSIVE_RETRY,
    retry_service=AGGRESSIVE_RETRY,
)

# STANDARD: Balanced propagation (default for most scenarios)
# FIX: Increased error_propagation_probability to 0.9 for stronger fault propagation
# FIX: Increased thread_pool_exhaustion_error_rate to 1.0 (must reject when pool full)
STANDARD_PROPAGATION = PropagationConfig(
    error_propagation_probability=0.9,  # 90% of dep failures cause request failure
    timeout_causes_error=True,
    thread_pool_exhaustion_error_rate=1.0,  # 100% error rate when thread pool exhausted
)

# RESILIENT: Services are highly resilient (good for testing GNN on hard cases)
RESILIENT_PROPAGATION = PropagationConfig(
    error_propagation_probability=0.3,  # Only 30% of dep failures cause request failure
    timeout_causes_error=False,         # Timeouts don't fail request (fallback logic)
    thread_pool_exhaustion_error_rate=0.1,  # +10% error rate when exhausted
    retry_external=CONSERVATIVE_RETRY,
    retry_database=CONSERVATIVE_RETRY,
    retry_service=CONSERVATIVE_RETRY,
)


def get_default_propagation_config() -> PropagationConfig:
    """Get default propagation configuration."""
    return STANDARD_PROPAGATION
