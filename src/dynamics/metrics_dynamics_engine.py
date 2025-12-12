"""
MetricsDynamicsEngine: First-principles dynamics for system metrics.

Implements causal relationships between CPU, latency, errors, and other metrics
using differential equations. Supports:
- Exponential CPU→Latency relationship
- Latency→Error correlation
- Wear/degradation accumulation
- Backpressure effects
- Action-based control (scale up/down, throttle)
"""

import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Dict, Any, Optional

from .correlated_noise import CorrelatedNoiseGenerator, CorrelationConfig


@dataclass
class DynamicsConfig:
    """Configuration parameters for the dynamics engine."""

    # Integration timestep
    dt: float = 1.0

    # CPU dynamics
    cpu_from_throughput_coef: float = 0.50  # CPU increase per RPS (deprecated, use cpu_from_concurrent_coef)
    cpu_from_concurrent_coef: float = 0.5  # CPU increase per concurrent request (replaces throughput)
    cpu_from_connections_coef: float = 1.0  # CPU increase per connection
    cpu_decay_rate: float = 0.90  # Decay toward baseline when idle (faster recovery)
    cpu_min: float = 5.0  # Minimum baseline CPU
    cpu_max: float = 100.0

    # Latency dynamics
    latency_base: float = 20.0  # Base latency in ms
    latency_cpu_threshold: float = 50.0  # CPU% where latency starts increasing
    latency_cpu_scale: float = 30.0  # Scale factor for exponential growth
    latency_queue_coef: float = 0.1  # Queue depth impact on latency
    latency_wear_coef: float = 0.01  # Wear factor impact on latency
    latency_tau: float = 2.0  # Time constant for latency response
    latency_min: float = 5.0
    latency_max: float = 10000.0

    # Error dynamics (adjusted for realistic fault propagation)
    error_base: float = 0.01  # Base error rate (1% - increased from 0.1%)
    error_latency_threshold: float = 100.0  # Latency (ms) where errors start (reduced from 200ms)
    error_latency_scale: float = 150.0  # Scale factor for latency→error (reduced from 200 for sensitivity)
    error_cpu_threshold: float = 50.0  # CPU% where errors start (reduced from 80%)
    error_cpu_scale: float = 30.0  # Scale factor for CPU→error (increased from 20 for sensitivity)
    error_tau: float = 3.0  # Time constant for error response
    error_max: float = 0.5  # Maximum error rate (50%)

    # Memory dynamics
    memory_base: float = 200.0  # Base memory in MB (changed from % to MB for Phase 2)
    memory_per_request_mb: float = 5.0  # Memory per concurrent request in MB
    memory_tau: float = 5.0  # Time constant for memory changes
    memory_from_throughput_coef: float = 0.01  # Deprecated, kept for backward compatibility
    memory_min: float = 10.0
    memory_max: float = 2000.0  # Max memory in MB (increased from 100% to accommodate MB values)

    # Throughput/backpressure dynamics
    throughput_capacity: float = 100.0  # Maximum RPS capacity
    backpressure_error_threshold: float = 0.1  # Error rate triggering backpressure
    backpressure_latency_threshold: float = 500.0  # P99 latency triggering backpressure
    throughput_tau: float = 5.0  # Time constant for throughput adjustment

    # Wear/degradation dynamics
    wear_accumulation_cpu_threshold: float = 70.0
    wear_accumulation_rate: float = 0.1  # Wear added per timestep under stress
    wear_decay_rate: float = 0.02  # Wear removed per timestep when idle
    wear_min: float = 0.0
    wear_max: float = 100.0

    # Noise parameters
    noise_enabled: bool = True
    noise_cpu_stddev: float = 0.02  # 2% multiplicative noise
    noise_latency_stddev: float = 0.05  # 5% multiplicative noise
    noise_error_stddev: float = 0.1  # 10% multiplicative noise
    noise_memory_stddev: float = 0.02
    noise_throughput_stddev: float = 0.05

    # Correlated noise (Phase 4)
    use_correlated_noise: bool = False  # Opt-in for backward compatibility
    correlation_config: Optional[CorrelationConfig] = None  # Uses default if None when enabled

    # Action effects
    action_scale_up_cpu_factor: float = 0.7  # CPU multiplier when scaling up
    action_scale_up_capacity_increase: float = 50.0  # Additional RPS capacity
    action_scale_down_cpu_factor: float = 1.2  # CPU multiplier when scaling down
    action_scale_down_capacity_decrease: float = 50.0
    action_throttle_throughput_factor: float = 0.5  # Throughput multiplier
    action_throttle_latency_factor: float = 0.8  # Latency multiplier
    action_restart_cpu_spike: float = 80.0  # Temporary CPU spike during restart
    action_restart_latency_spike: float = 500.0  # Temporary latency spike


@dataclass
class Action:
    """Represents a control action that can be applied to the system."""
    action_type: str  # "scale_up", "scale_down", "throttle", "noop", "restart"
    magnitude: float = 1.0  # Strength of action
    reason: str = ""  # Human-readable explanation


class MetricsDynamicsEngine:
    """
    Core dynamics engine modeling causal relationships between metrics.

    State Vector:
    - cpu_percent: CPU utilization (0-100%)
    - memory_percent: Memory utilization (0-100%)
    - latency_ms: Request latency in milliseconds
    - throughput_rps: Throughput in requests per second
    - error_rate: Error probability (0-0.5)
    - wear_factor: Cumulative degradation (0-100)

    Key Dynamics:
    - d(CPU)/dt = f(throughput, connections) - decay_to_baseline
    - d(Latency)/dt = drive_toward_target where target = base * exp((CPU-50)/30) * queue_factor
    - d(Error)/dt = drive_toward_target where target = base * exp((Latency-200)/200) * exp((CPU-80)/20)
    - d(Throughput)/dt = drive_toward_external_demand * backpressure_factor(errors, latency)
    - d(Wear)/dt = accumulate_during_stress - decay_during_idle
    """

    def __init__(self, config: Optional[DynamicsConfig] = None, random_seed: Optional[int] = None):
        """
        Initialize the dynamics engine.

        Args:
            config: Configuration parameters (uses defaults if None)
            random_seed: Random seed for reproducibility (None for random)
        """
        self.config = config if config is not None else DynamicsConfig()
        self.rng = random.Random(random_seed)

        # State vector
        self.cpu_percent = self.config.cpu_min
        self.memory_percent = self.config.memory_base
        self.latency_ms = self.config.latency_base
        self.throughput_rps = 0.0
        self.error_rate = self.config.error_base
        self.wear_factor = 0.0

        # Concurrent requests (Phase 2: calculated from throughput * latency)
        self.concurrent_requests = 0.0

        # Auxiliary state (not part of main dynamics but used as inputs)
        self.active_connections = 0
        self.queue_depth = 0
        self.external_throughput_demand = 0.0
        self.thread_pool_size = 50  # Default thread pool size (can be overridden)

        # Deployment multipliers (from buggy code deployments)
        self.cpu_multiplier = 1.0
        self.latency_multiplier = 1.0
        self.error_rate_multiplier = 1.0

        # Fault injection state (FLOOR and ADDITIVE faults)
        self.fault_latency_floor_ms = None      # Minimum latency (for slow_queries, etc.)
        self.fault_latency_additive_ms = 0.0    # Added latency (for inject_latency)
        self.fault_cpu_floor_percent = None     # Minimum CPU (for cpu_saturation)
        self.fault_error_additive = 0.0         # Added error rate (for inject_errors)
        self.fault_io_wait_active = False       # True during I/O wait (threads blocked, low CPU)

        # Latency history for percentile calculation
        self.latency_history: deque = deque(maxlen=1000)  # Keep last 1000 samples

        # Time tracking
        self.current_time = 0.0

        # Correlated noise generator (Phase 4)
        self.correlated_noise_generator = None
        if self.config.use_correlated_noise:
            correlation_config = self.config.correlation_config if self.config.correlation_config is not None else CorrelationConfig()
            self.correlated_noise_generator = CorrelatedNoiseGenerator(correlation_config)

    def update(
        self,
        dt: Optional[float] = None,
        external_throughput: float = 0.0,
        active_connections: int = 0,
        queue_depth: int = 0,
        action: Optional[Action] = None,
        cpu_multiplier: float = 1.0,
        latency_multiplier: float = 1.0,
        error_rate_multiplier: float = 1.0
    ) -> None:
        """
        Main integration step - updates all state variables.

        Args:
            dt: Timestep size (uses config.dt if None)
            external_throughput: External demand in RPS
            active_connections: Number of active connections
            queue_depth: Current queue depth
            action: Optional control action to apply
            cpu_multiplier: Multiplier from deployment bugs (e.g., 6.0 for 6x CPU usage)
            latency_multiplier: Multiplier from deployment bugs (e.g., 2.5 for 2.5x latency)
            error_rate_multiplier: Multiplier from deployment bugs
        """
        if dt is None:
            dt = self.config.dt

        # Update auxiliary state
        self.external_throughput_demand = external_throughput
        self.active_connections = active_connections
        self.queue_depth = queue_depth

        # Update deployment multipliers
        self.cpu_multiplier = cpu_multiplier
        self.latency_multiplier = latency_multiplier
        self.error_rate_multiplier = error_rate_multiplier

        # Phase 2: Calculate concurrent requests from ACTUAL throughput with smoothing
        # CRITICAL: Use external_throughput_demand (actual measured) for fast fault response,
        # but smooth the result to filter noise and maintain physical realism.
        #
        # This hybrid approach:
        # - Responds quickly to sustained throughput drops (network faults)
        # - Filters out 1-second noise spikes (realistic memory inertia)
        # - Maintains Little's Law consistency (L = λW)
        #
        # concurrent = throughput * (latency / 1000)  # Convert ms to seconds
        estimated_concurrent = self.external_throughput_demand * (self.latency_ms / 1000.0)

        # Apply exponential moving average (EMA) smoothing
        # alpha = 0.3: balances responsiveness (responds in ~3 seconds) vs noise filtering
        alpha = 0.3
        self.concurrent_requests = alpha * estimated_concurrent + (1 - alpha) * self.concurrent_requests

        # Apply action if provided
        if action is not None and action.action_type != "noop":
            self._apply_action(action)

        # Compute derivatives
        d_cpu = self._compute_cpu_derivative()
        d_latency = self._compute_latency_derivative()
        d_error = self._compute_error_derivative()
        d_memory = self._compute_memory_derivative()
        d_throughput = self._compute_throughput_derivative()
        d_wear = self._compute_wear_derivative()

        # First-order Euler integration
        self.cpu_percent += d_cpu * dt
        self.latency_ms += d_latency * dt
        self.error_rate += d_error * dt
        self.memory_percent += d_memory * dt
        self.throughput_rps += d_throughput * dt
        self.wear_factor += d_wear * dt

        # Apply noise
        if self.config.noise_enabled:
            self._apply_noise()

        # Clamp to bounds
        self._clamp_state()

        # Record latency for percentiles
        self.latency_history.append(self.latency_ms)

        # Update time
        self.current_time += dt

    def _compute_cpu_derivative(self) -> float:
        """Compute d(CPU)/dt based on concurrent requests, connections, and resource contention.

        Phase 2: Modified to use concurrent_requests instead of throughput.
        Phase 3: Added resource contention modeling (queue depth, thread saturation).

        This creates a feedback loop: high latency → more concurrent → higher CPU → even higher latency.
        Resource exhaustion causes additional CPU overhead from context switching and contention.

        Applies cpu_multiplier from deployments (e.g., inefficient algorithms
        that consume 6x more CPU per request).
        """
        # Calculate target CPU based on current load
        # Phase 2: Use concurrent requests instead of throughput
        # CRITICAL: During I/O wait, connections are BLOCKED (not consuming CPU)
        # Suppress connection CPU contribution when threads are waiting for I/O
        if self.fault_io_wait_active:
            # I/O wait: threads blocked, only count minimal baseline CPU
            target_cpu_from_load = self.config.cpu_min
        else:
            target_cpu_from_load = (
                self.config.cpu_min +
                self.config.cpu_from_concurrent_coef * self.concurrent_requests +
                self.config.cpu_from_connections_coef * self.active_connections
            )

        # Phase 3: Add CPU overhead from resource contention
        # Queue depth causes CPU spike ONLY when threads are actively processing
        # During deadlocks: queue grows but threads are sleeping → minimal CPU
        # During I/O wait: threads are blocked waiting for I/O → minimal CPU
        # The key insight: queue contention CPU should be proportional to THROUGHPUT, not just queue depth
        # If throughput is near zero (deadlock), queue doesn't cause CPU spikes
        active_processing_factor = min(self.throughput_rps / max(self.config.throughput_capacity, 1.0), 1.0)

        # Suppress queue contention CPU during I/O wait (threads blocked, not thrashing)
        if self.fault_io_wait_active:
            queue_contention_cpu = 0.0  # Threads waiting for I/O don't consume CPU
        else:
            queue_contention_cpu = ((self.queue_depth / 10.0) * 5.0) * active_processing_factor  # Max 5% per 10 queued

        # Thread pool saturation causes contention
        # When many threads are blocked on slow I/O, CPU increases from context switching
        # EXCEPT during I/O wait, where threads are sleeping/blocked, not switching
        if self.fault_io_wait_active:
            contention_cpu = 0.0  # I/O wait: threads blocked, not context switching
        elif self.thread_pool_size > 0:
            thread_saturation = self.concurrent_requests / self.thread_pool_size
            # Exponential increase when saturated (>70% utilization)
            if thread_saturation > 0.7:
                contention_cpu = 20.0 * (thread_saturation - 0.7) ** 2
            else:
                contention_cpu = 0.0
        else:
            contention_cpu = 0.0

        # FIX: Add Memory Pressure Overhead (Thrashing/Paging)
        # If memory > 80%, add exponential CPU penalty before OOM kill
        memory_usage_ratio = self.memory_percent / self.config.memory_max
        memory_pressure_cpu = 0.0
        if memory_usage_ratio > 0.8:
            # at 80% -> 0% CPU penalty
            # at 95% -> ~56% CPU penalty
            # at 100% -> ~100% CPU penalty
            memory_pressure_cpu = 100.0 * ((memory_usage_ratio - 0.8) / 0.2) ** 2

        # Combine all CPU sources
        target_cpu = target_cpu_from_load + queue_contention_cpu + contention_cpu + memory_pressure_cpu

        # Apply CPU multiplier from deployments (e.g., buggy code using 6x CPU)
        # This is applied to the TARGET, so the dynamics naturally drive toward the new state
        target_cpu *= self.cpu_multiplier

        # Apply FLOOR fault (e.g., cpu_saturation) - CPU never goes below this
        if self.fault_cpu_floor_percent is not None:
            target_cpu = max(target_cpu, self.fault_cpu_floor_percent)

        # Drive CPU toward target (equilibrium-seeking behavior)
        # This allows CPU to both increase and decrease naturally
        tau = 3.0  # Time constant for CPU adjustment
        return (target_cpu - self.cpu_percent) / tau

    def _compute_latency_derivative(self) -> float:
        """Compute d(Latency)/dt based on CPU, queue, and wear.

        Applies latency_multiplier from deployments (e.g., thread pool exhaustion
        causing 4.8x latency, or inefficient algorithms).
        """
        # Target latency increases exponentially with CPU
        # CRITICAL FIX: Clamp to min 1.0 so latency never goes below base
        # (was causing faults to be canceled out at low CPU)
        cpu_factor = max(1.0, math.exp((self.cpu_percent - self.config.latency_cpu_threshold) / self.config.latency_cpu_scale))

        # Queue depth impact
        queue_factor = 1.0 + self.queue_depth / 10.0 * self.config.latency_queue_coef

        # Wear impact
        wear_factor = 1.0 + self.wear_factor * self.config.latency_wear_coef

        target_latency = self.config.latency_base * cpu_factor * queue_factor * wear_factor

        # Apply latency multiplier from deployments (e.g., thread pool exhaustion)
        # This models bugs like undersized thread pools, inefficient algorithms, etc.
        target_latency *= self.latency_multiplier

        # Apply ADDITIVE fault (e.g., inject_latency)
        target_latency += self.fault_latency_additive_ms

        # Apply FLOOR fault (e.g., slow_queries) - latency never goes below this
        if self.fault_latency_floor_ms is not None:
            target_latency = max(target_latency, self.fault_latency_floor_ms)

        # Drive toward target with time constant
        return (target_latency - self.latency_ms) / self.config.latency_tau

    def _compute_error_derivative(self) -> float:
        """Compute d(Error)/dt based on latency and CPU.

        Applies error_rate_multiplier from deployments (e.g., buggy error handling).
        """
        # Errors increase with high latency
        latency_factor = math.exp(
            (self.latency_ms - self.config.error_latency_threshold) / self.config.error_latency_scale
        )

        # Errors also increase with high CPU
        cpu_factor = math.exp(
            (self.cpu_percent - self.config.error_cpu_threshold) / self.config.error_cpu_scale
        )

        target_error = self.config.error_base * latency_factor * cpu_factor

        # Apply error rate multiplier from deployments (e.g., buggy error handling)
        target_error *= self.error_rate_multiplier

        # Apply ADDITIVE fault (e.g., inject_errors) - adds base error rate
        target_error += self.fault_error_additive

        target_error = min(target_error, self.config.error_max)

        # Drive toward target with time constant
        return (target_error - self.error_rate) / self.config.error_tau

    def _compute_memory_derivative(self) -> float:
        """Compute d(Memory)/dt based on concurrent requests.

        Phase 2: Modified to use concurrent requests instead of throughput.
        Each in-flight request consumes memory, so high latency → more concurrent → more memory.
        """
        # Phase 2: Memory from concurrent requests (each request consumes memory while in-flight)
        memory_from_concurrent = self.config.memory_per_request_mb * self.concurrent_requests
        target_memory = self.config.memory_base + memory_from_concurrent

        # Drive toward target with time constant
        return (target_memory - self.memory_percent) / self.config.memory_tau

    def _compute_throughput_derivative(self) -> float:
        """Compute d(Throughput)/dt based on external demand and backpressure."""
        # Calculate backpressure throttle
        throttle = 1.0

        # Throttle if error rate is high
        if self.error_rate > self.config.backpressure_error_threshold:
            throttle *= 0.5

        # Throttle if latency is high (use P99 if available, else current)
        p99_latency = self.get_latency_percentile(99) if len(self.latency_history) > 10 else self.latency_ms
        if p99_latency > self.config.backpressure_latency_threshold:
            throttle *= 0.8

        # Target throughput considering capacity
        max_capacity = self.config.throughput_capacity
        target_throughput = min(self.external_throughput_demand * throttle, max_capacity)

        # Drive toward target with time constant
        return (target_throughput - self.throughput_rps) / self.config.throughput_tau

    def _compute_wear_derivative(self) -> float:
        """Compute d(Wear)/dt - accumulates under stress, decays when idle."""
        # Accumulate wear when CPU is high
        accumulation = 0.0
        if self.cpu_percent > self.config.wear_accumulation_cpu_threshold:
            accumulation = self.config.wear_accumulation_rate

        # Decay when idle
        is_idle = (self.cpu_percent < 30.0 and self.throughput_rps < 1.0)
        if is_idle:
            decay = self.wear_factor * self.config.wear_decay_rate
        else:
            decay = 0.0

        return accumulation - decay

    def _apply_noise(self) -> None:
        """Apply multiplicative noise to state variables."""
        if self.correlated_noise_generator is not None:
            # Phase 4: Use correlated multivariate noise
            self._apply_correlated_noise()
        else:
            # Original: Independent noise for each metric
            self._apply_independent_noise()

    def _apply_independent_noise(self) -> None:
        """Apply independent Gaussian noise to each metric (original behavior)."""
        # Multiplicative noise proportional to current value
        self.cpu_percent *= (1.0 + self.rng.gauss(0, self.config.noise_cpu_stddev))
        self.latency_ms *= (1.0 + self.rng.gauss(0, self.config.noise_latency_stddev))
        self.error_rate *= (1.0 + self.rng.gauss(0, self.config.noise_error_stddev))
        self.memory_percent *= (1.0 + self.rng.gauss(0, self.config.noise_memory_stddev))

        # Throughput noise is additive (can't go negative easily)
        throughput_noise = self.rng.gauss(0, self.config.noise_throughput_stddev * self.throughput_rps)
        self.throughput_rps = max(0, self.throughput_rps + throughput_noise)

    def _apply_correlated_noise(self) -> None:
        """Apply correlated multivariate noise (Phase 4)."""
        # Generate correlated noise for all metrics at once
        # Order: [CPU, MEM, LAT, TPS, ERR]
        scales = [
            self.config.noise_cpu_stddev,
            self.config.noise_memory_stddev,
            self.config.noise_latency_stddev,
            self.config.noise_throughput_stddev,
            self.config.noise_error_stddev,
        ]

        noise = self.correlated_noise_generator.generate(scales, self.rng)

        # Apply multiplicative noise to each metric
        self.cpu_percent *= (1.0 + noise[0])
        self.memory_percent *= (1.0 + noise[1])
        self.latency_ms *= (1.0 + noise[2])
        self.error_rate *= (1.0 + noise[4])

        # Throughput noise remains additive to prevent negative values
        # Scale by current throughput to make it proportional
        throughput_additive_noise = noise[3] * self.throughput_rps
        self.throughput_rps = max(0, self.throughput_rps + throughput_additive_noise)

    def _clamp_state(self) -> None:
        """Clamp all state variables to physical bounds."""
        self.cpu_percent = max(self.config.cpu_min, min(self.config.cpu_max, self.cpu_percent))
        self.memory_percent = max(self.config.memory_min, min(self.config.memory_max, self.memory_percent))
        self.latency_ms = max(self.config.latency_min, min(self.config.latency_max, self.latency_ms))
        self.throughput_rps = max(0.0, self.throughput_rps)
        self.error_rate = max(0.0, min(self.config.error_max, self.error_rate))
        self.wear_factor = max(self.config.wear_min, min(self.config.wear_max, self.wear_factor))

    def _apply_action(self, action: Action) -> None:
        """Apply a control action to the system state."""
        if action.action_type == "scale_up":
            self.cpu_percent *= self.config.action_scale_up_cpu_factor
            self.config.throughput_capacity += self.config.action_scale_up_capacity_increase * action.magnitude

        elif action.action_type == "scale_down":
            self.cpu_percent *= self.config.action_scale_down_cpu_factor
            self.config.throughput_capacity = max(
                10.0,  # Minimum capacity
                self.config.throughput_capacity - self.config.action_scale_down_capacity_decrease * action.magnitude
            )

        elif action.action_type == "throttle":
            self.throughput_rps *= self.config.action_throttle_throughput_factor * action.magnitude
            self.latency_ms *= self.config.action_throttle_latency_factor

        elif action.action_type == "restart":
            # Temporary spike in CPU and latency
            self.cpu_percent = min(self.config.cpu_max, self.config.action_restart_cpu_spike * action.magnitude)
            self.latency_ms = min(self.config.latency_max, self.config.action_restart_latency_spike * action.magnitude)

    # --- Public API ---

    def get_cpu_percent(self) -> float:
        """Get current CPU utilization percentage."""
        return self.cpu_percent

    def get_memory_percent(self) -> float:
        """Get current memory utilization percentage (deprecated - now returns MB)."""
        return self.memory_percent

    def get_memory(self) -> float:
        """Get current memory usage in MB (Phase 2)."""
        return self.memory_percent  # Now stores MB instead of %

    def get_latency(self) -> float:
        """Get current latency in milliseconds."""
        return self.latency_ms

    def get_throughput(self) -> float:
        """Get current throughput in RPS."""
        return self.throughput_rps

    def get_error_rate(self) -> float:
        """Get current error probability (0-0.5)."""
        return self.error_rate

    def get_wear_factor(self) -> float:
        """Get current wear/degradation factor (0-100)."""
        return self.wear_factor

    def get_latency_percentile(self, percentile: float) -> float:
        """
        Calculate latency percentile from history.

        Args:
            percentile: Percentile to calculate (0-100)

        Returns:
            Latency value at the given percentile
        """
        if not self.latency_history:
            return self.latency_ms

        sorted_latencies = sorted(self.latency_history)
        index = int(len(sorted_latencies) * percentile / 100.0)
        index = min(index, len(sorted_latencies) - 1)
        return sorted_latencies[index]

    def get_state_dict(self) -> Dict[str, Any]:
        """Export full state for debugging and analysis."""
        return {
            'time': self.current_time,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'latency_ms': self.latency_ms,
            'throughput_rps': self.throughput_rps,
            'error_rate': self.error_rate,
            'wear_factor': self.wear_factor,
            'active_connections': self.active_connections,
            'queue_depth': self.queue_depth,
            'external_throughput_demand': self.external_throughput_demand,
            'throughput_capacity': self.config.throughput_capacity,
            'latency_p50': self.get_latency_percentile(50),
            'latency_p90': self.get_latency_percentile(90),
            'latency_p99': self.get_latency_percentile(99),
        }

    def reset(self) -> None:
        """Reset the engine to initial state."""
        self.cpu_percent = self.config.cpu_min
        self.memory_percent = self.config.memory_base
        self.latency_ms = self.config.latency_base
        self.throughput_rps = 0.0
        self.error_rate = self.config.error_base
        self.wear_factor = 0.0
        self.active_connections = 0
        self.queue_depth = 0
        self.external_throughput_demand = 0.0
        self.cpu_multiplier = 1.0
        self.latency_multiplier = 1.0
        self.error_rate_multiplier = 1.0
        self.latency_history.clear()
        self.current_time = 0.0
