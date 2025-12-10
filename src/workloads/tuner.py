"""
Workload Tuner - Dynamically adjusts traffic during warmup to ensure healthy baseline.

This module ensures that the simulation starts with a healthy baseline by:
1. Monitoring request success/failure rates during warmup (30-60s)
2. Dynamically adjusting RPS if the system is rejecting requests
3. Finding the maximum sustainable load the topology can handle
"""
import simpy
from typing import Dict
from src.core.logging_setup import get_logger


class WorkloadTuner:
    """
    Dynamically tunes workload during warmup to prevent unhealthy baseline.

    Strategy:
    - First 30s: Normal warmup (system stabilizes)
    - Next 30s: Tuning phase
      * Monitor request metrics every 5s
      * If error rate > threshold: reduce RPS by 10%
      * If error rate < threshold and utilization low: increase RPS by 5%
      * Converge to healthy sustainable load
    """

    def __init__(
        self,
        env: simpy.Environment,
        workload_generator,
        tuning_start: float = 30.0,
        tuning_duration: float = 30.0,
        check_interval: float = 5.0,
        error_rate_threshold: float = 0.02,  # 2% error rate is acceptable for training
        utilization_threshold: float = 0.70,  # Target 70% utilization for healthy baseline
    ):
        """
        Initialize the workload tuner.

        Args:
            env: SimPy environment
            workload_generator: WorkloadGenerator instance to tune
            tuning_start: When to start tuning (simulation time in seconds)
            tuning_duration: How long to run tuning
            check_interval: How often to check metrics and adjust
            error_rate_threshold: Maximum acceptable error rate
            utilization_threshold: Target utilization for healthy baseline
        """
        self.env = env
        self.workload_generator = workload_generator
        self.tuning_start = tuning_start
        self.tuning_duration = tuning_duration
        self.check_interval = check_interval
        self.error_rate_threshold = error_rate_threshold
        self.utilization_threshold = utilization_threshold
        self.logger = get_logger(__name__)

        # Tuning state
        self.tuning_history = []
        self.final_tuned_rps_multiplier = None

    def run(self):
        """Main tuning process (SimPy generator)."""
        # Wait until tuning should start
        if self.tuning_start > self.env.now:
            yield self.env.timeout(self.tuning_start - self.env.now)

        print(f"\n[{self.env.now:.2f}s] === WORKLOAD TUNING STARTED ===")
        print(f"  Goal: Find healthy sustainable load (error rate < {self.error_rate_threshold*100:.1f}%)")
        print(f"  Duration: {self.tuning_duration}s (check every {self.check_interval}s)")
        print(f"  Initial RPS multiplier: {self.workload_generator.rps_multiplier:.3f}")

        tuning_end_time = self.env.now + self.tuning_duration
        last_stats = None

        while self.env.now < tuning_end_time:
            # Wait for next check interval
            yield self.env.timeout(self.check_interval)

            # Get current metrics from workload generator
            current_stats = self.workload_generator.get_statistics()

            # Calculate error rate since last check
            if last_stats is not None:
                delta_attempted = current_stats['total_requests_attempted'] - last_stats['total_requests_attempted']
                delta_failed = current_stats['total_requests_failed'] - last_stats['total_requests_failed']
                delta_timeout = current_stats['total_requests_timeout'] - last_stats['total_requests_timeout']
                delta_rejected_cb = current_stats['total_requests_rejected_circuit_open'] - last_stats['total_requests_rejected_circuit_open']
                delta_rejected_queue = current_stats['total_requests_rejected_queue_full'] - last_stats['total_requests_rejected_queue_full']

                if delta_attempted > 0:
                    error_rate = (delta_failed + delta_timeout + delta_rejected_cb + delta_rejected_queue) / delta_attempted
                else:
                    error_rate = 0.0

                # Calculate connection pool utilization
                pool_utilization = current_stats['connection_pool_active'] / current_stats['connection_pool_size']

                # Get current multiplier from workload generator
                current_multiplier = self.workload_generator.rps_multiplier

                # Record current state
                self.tuning_history.append({
                    'time': self.env.now,
                    'rps_multiplier': current_multiplier,
                    'error_rate': error_rate,
                    'pool_utilization': pool_utilization,
                    'delta_attempted': delta_attempted,
                })

                # Adjustment logic
                adjustment_made = False

                if error_rate > self.error_rate_threshold:
                    # System is overloaded - reduce traffic
                    old_multiplier = current_multiplier
                    new_multiplier = current_multiplier * 0.90  # Reduce by 10%
                    new_multiplier = max(0.5, new_multiplier)  # Don't go below 50%
                    self.workload_generator.rps_multiplier = new_multiplier

                    print(f"[{self.env.now:.2f}s] ⚠️  OVERLOAD DETECTED (error rate: {error_rate*100:.1f}%)")
                    print(f"  Reducing RPS multiplier: {old_multiplier:.3f} -> {new_multiplier:.3f}")
                    adjustment_made = True

                elif error_rate < self.error_rate_threshold * 0.5 and pool_utilization < self.utilization_threshold:
                    # System has headroom - cautiously increase traffic
                    old_multiplier = current_multiplier
                    new_multiplier = current_multiplier * 1.05  # Increase by 5% (conservative)
                    new_multiplier = min(1.2, new_multiplier)  # Cap at 120% of original
                    self.workload_generator.rps_multiplier = new_multiplier

                    print(f"[{self.env.now:.2f}s] ✓ HEADROOM DETECTED (error rate: {error_rate*100:.1f}%, util: {pool_utilization*100:.1f}%)")
                    print(f"  Increasing RPS multiplier: {old_multiplier:.3f} -> {new_multiplier:.3f}")
                    adjustment_made = True

                if not adjustment_made:
                    print(f"[{self.env.now:.2f}s] ✓ STABLE (error rate: {error_rate*100:.1f}%, util: {pool_utilization*100:.1f}%, multiplier: {current_multiplier:.3f})")

            # Update last stats
            last_stats = current_stats

        # Tuning complete - record final multiplier
        self.final_tuned_rps_multiplier = self.workload_generator.rps_multiplier

        print(f"\n[{self.env.now:.2f}s] === WORKLOAD TUNING COMPLETED ===")
        print(f"  Final RPS multiplier: {self.final_tuned_rps_multiplier:.3f}")
        if self.final_tuned_rps_multiplier < 0.95:
            print(f"  ⚠️  System cannot handle target load (operating at {self.final_tuned_rps_multiplier*100:.0f}% of planned)")
        else:
            print(f"  ✓ System is healthy and can handle planned load")

    def get_tuning_results(self) -> Dict:
        """Get tuning results for export."""
        return {
            'tuning_start': self.tuning_start,
            'tuning_duration': self.tuning_duration,
            'original_rps_multiplier': 1.0,
            'final_rps_multiplier': self.final_tuned_rps_multiplier,
            'adjustments_made': len(self.tuning_history),
            'history': self.tuning_history,
            'conclusion': 'healthy' if self.final_tuned_rps_multiplier and self.final_tuned_rps_multiplier >= 0.95 else 'capacity_limited'
        }
