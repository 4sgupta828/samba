"""
Circuit Breaker Implementation for Workload Generator.

Implements the circuit breaker pattern to prevent request storms during failures.
States: CLOSED (normal), OPEN (failing), HALF_OPEN (testing recovery)
"""
from collections import deque
from enum import Enum
from typing import Optional
import time


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation, requests flow through
    OPEN = "open"  # Failure detected, reject requests immediately
    HALF_OPEN = "half_open"  # Testing if system recovered


class CircuitBreaker:
    """
    Circuit breaker that tracks request outcomes and opens when failure threshold exceeded.

    Real-world behavior:
    - CLOSED: Normal operation, track failures
    - OPEN: Stop sending requests, fail fast
    - HALF_OPEN: Periodically send probe requests to test recovery
    """

    def __init__(
        self,
        failure_threshold: float = 0.5,  # Open circuit at 50% failure rate
        success_threshold: float = 0.7,  # Close circuit at 70% success rate
        window_size: int = 20,  # Track last N requests
        open_duration: float = 10.0,  # Keep circuit open for N seconds before probing
        half_open_max_requests: int = 5,  # Max probe requests in half-open state
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Failure rate to open circuit (0.0-1.0)
            success_threshold: Success rate to close circuit (0.0-1.0)
            window_size: Number of recent requests to track
            open_duration: Seconds to keep circuit open before testing
            half_open_max_requests: Max requests to allow in half-open state
        """
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.window_size = window_size
        self.open_duration = open_duration
        self.half_open_max_requests = half_open_max_requests

        # State tracking
        self.state = CircuitState.CLOSED
        self.request_history = deque(maxlen=window_size)  # True = success, False = failure
        self.opened_at: Optional[float] = None
        self.half_open_request_count = 0

        # Statistics
        self.total_requests = 0
        self.total_failures = 0
        self.times_opened = 0
        self.times_half_opened = 0

    def record_success(self, current_time: Optional[float] = None):
        """Record a successful request.

        Args:
            current_time: Current simulation time (optional, for state transitions)
        """
        self.total_requests += 1
        self.request_history.append(True)

        if self.state == CircuitState.HALF_OPEN:
            self.half_open_request_count += 1
            # Check if we have enough successful probes to close circuit
            if self._get_success_rate() >= self.success_threshold:
                self._transition_to_closed()

    def record_failure(self, current_time: Optional[float] = None):
        """Record a failed request.

        Args:
            current_time: Current simulation time (optional, for state transitions)
        """
        self.total_requests += 1
        self.total_failures += 1
        self.request_history.append(False)

        if self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open immediately reopens circuit
            self._transition_to_open(current_time)
        elif self.state == CircuitState.CLOSED:
            # Check if failure rate exceeds threshold
            if self._get_failure_rate() >= self.failure_threshold:
                self._transition_to_open(current_time)

    def should_allow_request(self, current_time: float) -> bool:
        """
        Check if request should be allowed through circuit breaker.

        Args:
            current_time: Current simulation time in seconds

        Returns:
            True if request should be allowed, False if circuit is open
        """
        if self.state == CircuitState.CLOSED:
            return True

        elif self.state == CircuitState.OPEN:
            # Check if enough time has passed to try probing
            if self.opened_at and (current_time - self.opened_at) >= self.open_duration:
                self._transition_to_half_open()
                return True
            return False

        elif self.state == CircuitState.HALF_OPEN:
            # Allow limited probe requests
            return self.half_open_request_count < self.half_open_max_requests

        return False

    def _transition_to_open(self, current_time: Optional[float] = None):
        """Transition to OPEN state (failing).

        Args:
            current_time: Current simulation time (if not provided, uses wall clock - NOT RECOMMENDED)
        """
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = current_time if current_time is not None else time.time()
            self.times_opened += 1

    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state (testing)."""
        if self.state != CircuitState.HALF_OPEN:
            self.state = CircuitState.HALF_OPEN
            self.half_open_request_count = 0
            self.times_half_opened += 1

    def _transition_to_closed(self):
        """Transition to CLOSED state (recovered)."""
        if self.state != CircuitState.CLOSED:
            self.state = CircuitState.CLOSED
            self.opened_at = None
            self.half_open_request_count = 0

    def _get_failure_rate(self) -> float:
        """Calculate failure rate from recent history."""
        if not self.request_history:
            return 0.0
        failures = sum(1 for success in self.request_history if not success)
        return failures / len(self.request_history)

    def _get_success_rate(self) -> float:
        """Calculate success rate from recent history."""
        return 1.0 - self._get_failure_rate()

    def get_state(self) -> str:
        """Get current state as string."""
        return self.state.value

    def get_statistics(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "state": self.get_state(),
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "overall_failure_rate": self.total_failures / max(1, self.total_requests),
            "recent_failure_rate": self._get_failure_rate(),
            "times_opened": self.times_opened,
            "times_half_opened": self.times_half_opened,
        }
