"""
Circuit Breaker Pattern - Prevents cascading failures.

A circuit breaker monitors failures and "opens" when error rate exceeds threshold,
failing fast instead of waiting for timeouts. This is critical for:
1. Preventing resource exhaustion in calling services
2. Giving failing services time to recover
3. Creating clear GNN training signals (state transitions)

States:
- CLOSED (0.0): Normal operation, all requests go through
- OPEN (1.0): Failing fast, no requests to downstream
- HALF_OPEN (0.5): Testing recovery, limited requests
"""
import time
from collections import deque
from typing import Callable, Any
from dataclasses import dataclass


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: float = 0.5  # 50% error rate triggers open
    success_threshold: float = 0.8  # 80% success rate closes circuit
    timeout_seconds: float = 10.0   # Time to wait before half-open
    sample_window: int = 20          # Number of recent requests to track
    half_open_max_calls: int = 3     # Max test calls in half-open state


class CircuitBreakerState:
    """
    Tracks circuit breaker state and recent call history.

    Uses a sliding window to calculate error rate.
    """

    CLOSED = 0.0    # Normal operation
    OPEN = 1.0      # Failing fast
    HALF_OPEN = 0.5 # Testing recovery

    def __init__(self, config: CircuitBreakerConfig, env=None):
        """
        Initialize circuit breaker state.

        Args:
            config: Circuit breaker configuration
            env: SimPy environment (optional, for simulation time)
        """
        self.config = config
        self.env = env
        self.state = self.CLOSED
        self.opened_at = None
        self.half_open_calls = 0

        # Sliding window of recent call results (True = success, False = failure)
        self.recent_results = deque(maxlen=config.sample_window)

        # Statistics
        self.total_calls = 0
        self.total_failures = 0
        self.total_rejected = 0  # Calls rejected due to open circuit

    def get_current_time(self) -> float:
        """Get current time (simulation time if env available, else wall time)."""
        if self.env:
            return self.env.now
        return time.time()

    def record_success(self):
        """Record a successful call."""
        self.total_calls += 1
        self.recent_results.append(True)

        # Check if we should transition from HALF_OPEN to CLOSED
        if self.state == self.HALF_OPEN:
            # Calculate success rate in recent window
            if len(self.recent_results) >= self.config.half_open_max_calls:
                success_rate = sum(self.recent_results) / len(self.recent_results)
                if success_rate >= self.config.success_threshold:
                    self._transition_to_closed()

    def record_failure(self):
        """Record a failed call."""
        self.total_calls += 1
        self.total_failures += 1
        self.recent_results.append(False)

        # Check if we should transition to OPEN
        if self.state == self.CLOSED:
            if len(self.recent_results) >= self.config.sample_window:
                error_rate = sum(not r for r in self.recent_results) / len(self.recent_results)
                if error_rate >= self.config.failure_threshold:
                    self._transition_to_open()

        # In HALF_OPEN, any failure immediately opens circuit
        elif self.state == self.HALF_OPEN:
            self._transition_to_open()

    def should_allow_request(self) -> bool:
        """
        Determine if a request should be allowed through.

        Returns:
            True if request should proceed, False if circuit is open
        """
        if self.state == self.CLOSED:
            return True

        if self.state == self.OPEN:
            # Check if timeout has elapsed
            current_time = self.get_current_time()
            if current_time - self.opened_at >= self.config.timeout_seconds:
                self._transition_to_half_open()
                return True
            else:
                self.total_rejected += 1
                return False

        if self.state == self.HALF_OPEN:
            # Allow limited test calls
            if self.half_open_calls < self.config.half_open_max_calls:
                self.half_open_calls += 1
                return True
            else:
                self.total_rejected += 1
                return False

        return False

    def _transition_to_open(self):
        """Transition to OPEN state."""
        self.state = self.OPEN
        self.opened_at = self.get_current_time()
        self.half_open_calls = 0

    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state."""
        self.state = self.HALF_OPEN
        self.half_open_calls = 0
        # Clear recent results to give service fresh chance
        self.recent_results.clear()

    def _transition_to_closed(self):
        """Transition to CLOSED state."""
        self.state = self.CLOSED
        self.opened_at = None
        self.half_open_calls = 0

    def get_state_value(self) -> float:
        """Get numeric state value for metrics (0.0, 0.5, or 1.0)."""
        return self.state

    def get_error_rate(self) -> float:
        """Calculate current error rate from recent results."""
        if not self.recent_results:
            return 0.0
        return sum(not r for r in self.recent_results) / len(self.recent_results)


class CircuitBreaker:
    """
    Circuit breaker decorator/wrapper for function calls.

    Usage:
        cb = CircuitBreaker(config, dependency_name="ext_api")
        result = cb.call(lambda: external_api.request())
    """

    def __init__(self, config: CircuitBreakerConfig, dependency_name: str, env=None):
        """
        Initialize circuit breaker.

        Args:
            config: Circuit breaker configuration
            dependency_name: Name of the dependency being protected
            env: SimPy environment (optional)
        """
        self.config = config
        self.dependency_name = dependency_name
        self.state = CircuitBreakerState(config, env)

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call

        Raises:
            CircuitBreakerOpenException: If circuit is open
            Exception: If function raises exception (and circuit records failure)
        """
        if not self.state.should_allow_request():
            raise CircuitBreakerOpenException(
                f"Circuit breaker OPEN for {self.dependency_name}"
            )

        try:
            result = func(*args, **kwargs)
            self.state.record_success()
            return result
        except Exception as e:
            self.state.record_failure()
            raise


class CircuitBreakerOpenException(Exception):
    """Exception raised when circuit breaker is open."""
    pass
