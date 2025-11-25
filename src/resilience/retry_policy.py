"""
Retry Policy - Implements exponential backoff with jitter.

Retries are critical for fault propagation because:
1. They amplify load on failing services (1 request → 3 retries = 3x load)
2. They increase latency in calling services (waiting for retries)
3. They create cascading timeouts (retries exhaust time budget)

This module provides configurable retry policies that create realistic
training data for GNNs to learn retry storm patterns.
"""
import random
from dataclasses import dataclass
from typing import Callable, Any, Type, Tuple
import simpy


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3              # Total attempts (1 initial + 2 retries)
    base_delay_ms: float = 200.0       # Base delay between retries (ms)
    max_delay_ms: float = 5000.0       # Maximum delay cap (ms)
    backoff_multiplier: float = 2.0    # Exponential backoff multiplier
    jitter_factor: float = 0.1         # Random jitter (±10%)

    # Which exceptions should trigger retry
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)

    # Exceptions that should NOT be retried (fail fast)
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,  # Bad input
        TypeError,   # Programming error
    )


class RetryPolicy:
    """
    Implements retry logic with exponential backoff.

    Tracks retry attempts and calculates delays to create realistic
    fault propagation patterns.
    """

    def __init__(self, config: RetryConfig, env: simpy.Environment = None):
        """
        Initialize retry policy.

        Args:
            config: Retry configuration
            env: SimPy environment (optional, for simulation time delays)
        """
        self.config = config
        self.env = env

        # Statistics
        self.total_calls = 0
        self.total_retries = 0
        self.total_failures_after_retries = 0

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic.

        Args:
            func: Function to execute (can be generator for SimPy process)
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call

        Raises:
            Exception: If all retry attempts fail
        """
        self.total_calls += 1
        last_exception = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                # Check if function is a generator (SimPy process)
                if hasattr(func, '__call__'):
                    result = func(*args, **kwargs)

                    # If it's a generator, we need to yield from it
                    if hasattr(result, '__iter__') and not isinstance(result, (str, bytes)):
                        # This is a SimPy process, yield from it
                        yield from result
                        return
                    else:
                        return result
                else:
                    result = func(*args, **kwargs)
                    return result

            except self.config.non_retryable_exceptions as e:
                # Don't retry these exceptions
                raise

            except self.config.retryable_exceptions as e:
                last_exception = e

                # If this was the last attempt, raise the exception
                if attempt >= self.config.max_attempts:
                    self.total_failures_after_retries += 1
                    raise

                # Calculate backoff delay with exponential growth and jitter
                delay_ms = self._calculate_backoff_delay(attempt)

                self.total_retries += 1

                # Wait before retrying (if SimPy env available)
                if self.env:
                    yield self.env.timeout(delay_ms / 1000.0)  # Convert ms to seconds

        # Should never reach here, but raise last exception if we do
        if last_exception:
            raise last_exception

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in milliseconds
        """
        # Exponential backoff: base_delay * (multiplier ^ (attempt - 1))
        delay = self.config.base_delay_ms * (self.config.backoff_multiplier ** (attempt - 1))

        # Cap at max delay
        delay = min(delay, self.config.max_delay_ms)

        # Add random jitter (±jitter_factor)
        jitter_range = delay * self.config.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)
        delay += jitter

        return max(0, delay)  # Ensure non-negative

    def get_retry_count(self) -> int:
        """Get total number of retries performed."""
        return self.total_retries

    def get_failure_rate_after_retries(self) -> float:
        """
        Calculate failure rate after exhausting retries.

        Returns:
            Ratio of failures to total calls
        """
        if self.total_calls == 0:
            return 0.0
        return self.total_failures_after_retries / self.total_calls


# Pre-configured retry policies for common scenarios

# Aggressive retry (for critical dependencies)
AGGRESSIVE_RETRY = RetryConfig(
    max_attempts=5,
    base_delay_ms=100.0,
    backoff_multiplier=2.0,
)

# Standard retry (for normal dependencies)
STANDARD_RETRY = RetryConfig(
    max_attempts=3,
    base_delay_ms=200.0,
    backoff_multiplier=2.0,
)

# Conservative retry (for flaky dependencies)
CONSERVATIVE_RETRY = RetryConfig(
    max_attempts=2,
    base_delay_ms=500.0,
    backoff_multiplier=2.0,
)

# No retry (for idempotency-unsafe operations)
NO_RETRY = RetryConfig(
    max_attempts=1,
)
