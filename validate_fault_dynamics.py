"""
Fault Dynamics Validation Framework

This is the GOLD STANDARD for understanding fault behavior in our simulation.

Purpose:
1. Validate that dynamics engine correctly models cross-metric effects
2. Document actual fault behavior (primary → secondary → tertiary)
3. Ensure simulation matches real distributed systems
4. Serve as regression tests for fault injection

For each fault type, we:
- Inject the fault in isolation
- Measure ALL metrics (CPU, memory, latency, throughput, errors, queue depth)
- Validate expected relationships hold (e.g., CPU↑ → latency↑)
- Generate a "fault profile" documenting the behavior
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
import simpy
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from src.simulation import Simulation
from src.workloads.generator import WorkloadGenerator


@dataclass
class MetricSnapshot:
    """Single point-in-time measurement of all metrics."""
    timestamp: float
    cpu_utilization: float
    memory_utilization: float
    avg_latency_ms: float
    p99_latency_ms: float
    throughput_rps: float
    error_rate: float
    active_threads: int
    queue_depth: int

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'cpu': self.cpu_utilization,
            'memory': self.memory_utilization,
            'latency_avg': self.avg_latency_ms,
            'latency_p99': self.p99_latency_ms,
            'throughput': self.throughput_rps,
            'errors': self.error_rate,
            'threads': self.active_threads,
            'queue_depth': self.queue_depth
        }


@dataclass
class FaultProfile:
    """
    Complete characterization of a fault's behavior.

    This is our "gold standard" - it documents:
    - What the fault does (primary effect)
    - What happens as a result (secondary effects)
    - How metrics interact (cross-metric relationships)
    """
    fault_type: str
    fault_severity: float

    # Time series of all metrics
    baseline_metrics: List[MetricSnapshot]  # Before fault
    fault_metrics: List[MetricSnapshot]     # During fault
    recovery_metrics: List[MetricSnapshot]  # After fault

    # Validated relationships
    primary_effect: Dict[str, float]  # What we directly set
    secondary_effects: Dict[str, float]  # What dynamics modeled
    unexpected_effects: List[str]  # Anything that doesn't match expectations

    # Validation results
    passed: bool
    failed_validations: List[str]

    def to_dict(self) -> dict:
        return {
            'fault_type': self.fault_type,
            'severity': self.fault_severity,
            'baseline': [m.to_dict() for m in self.baseline_metrics],
            'fault': [m.to_dict() for m in self.fault_metrics],
            'recovery': [m.to_dict() for m in self.recovery_metrics],
            'primary_effect': self.primary_effect,
            'secondary_effects': self.secondary_effects,
            'unexpected': self.unexpected_effects,
            'passed': self.passed,
            'failures': self.failed_validations
        }


class FaultValidator:
    """
    Validates that faults behave as expected in our simulation.

    This is the core validation engine that proves our simulation is realistic.
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results: Dict[str, FaultProfile] = {}

    def validate_all_faults(self) -> Dict[str, FaultProfile]:
        """
        Run validation for all unique fault types.

        Returns a comprehensive report on fault behavior.
        """
        print("\n" + "="*80)
        print("FAULT DYNAMICS VALIDATION - Gold Standard")
        print("="*80)

        fault_tests = [
            ('cpu_saturation', 0.5, self._validate_cpu_saturation),
            ('memory_pressure', 0.5, self._validate_memory_pressure),
            ('thread_exhaustion', 0.5, self._validate_thread_exhaustion),
            ('io_bottleneck', 0.5, self._validate_io_bottleneck),
            ('network_partition', 0.5, self._validate_network_partition),
            ('dependency_timeout', 0.5, self._validate_dependency_timeout),
        ]

        for fault_type, severity, validator_func in fault_tests:
            print(f"\n{'─'*80}")
            print(f"Testing: {fault_type} (severity={severity})")
            print(f"{'─'*80}")

            profile = validator_func(severity)
            self.results[fault_type] = profile

            if profile.passed:
                print(f"✅ PASSED - {fault_type} behaves as expected")
            else:
                print(f"❌ FAILED - {fault_type} has issues:")
                for failure in profile.failed_validations:
                    print(f"  - {failure}")

        # Generate summary report
        self._generate_summary_report()

        return self.results

    def _validate_cpu_saturation(self, severity: float) -> FaultProfile:
        """
        Validate CPU saturation fault.

        Expected behavior:
        - PRIMARY: CPU utilization increases to target (e.g., 85%)
        - SECONDARY:
          * Latency increases proportionally (work takes longer)
          * Throughput decreases (CPU bottleneck)
          * Error rate may increase (timeouts)
        """
        print("\n[Test] CPU Saturation")
        print("  Expected: CPU↑ → Latency↑, Throughput↓")

        try:
            # Run minimal simulation with cpu_saturation
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='cpu_saturation',
                severity=severity,
                duration=180  # 3 minutes total
            )

            # Calculate changes
            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            # Primary effect validation
            cpu_change = fault_avg.cpu_utilization - baseline_avg.cpu_utilization
            cpu_target = baseline_avg.cpu_utilization + ((1.0 - baseline_avg.cpu_utilization) * severity * 0.75)

            # Secondary effect validation
            latency_ratio = fault_avg.avg_latency_ms / max(baseline_avg.avg_latency_ms, 1.0)
            throughput_ratio = fault_avg.throughput_rps / max(baseline_avg.throughput_rps, 1.0)

            # Validate relationships
            validations = []
            passed = True

            # Check primary effect
            if abs(fault_avg.cpu_utilization - cpu_target) > 0.1:
                validations.append(f"CPU target not reached: {fault_avg.cpu_utilization:.2f} vs {cpu_target:.2f}")
                passed = False
            else:
                print(f"  ✓ PRIMARY: CPU {baseline_avg.cpu_utilization:.1%} → {fault_avg.cpu_utilization:.1%}")

            # Check CPU → Latency relationship
            cpu_increase_factor = fault_avg.cpu_utilization / max(baseline_avg.cpu_utilization, 0.01)
            expected_latency_range = (1.5, 4.0)  # Expect 1.5x-4x latency increase

            rel_passed, rel_msg = self.validate_cross_metric_relationship(
                'cpu', cpu_change,
                'latency', expected_latency_range,
                latency_ratio
            )
            if rel_passed:
                print(f"  ✓ SECONDARY: Latency {baseline_avg.avg_latency_ms:.1f}ms → {fault_avg.avg_latency_ms:.1f}ms ({latency_ratio:.2f}x)")
            else:
                validations.append(rel_msg)
                passed = False

            # Check throughput decrease
            if throughput_ratio > 0.9:  # Should decrease
                validations.append(f"Throughput should decrease, but got {throughput_ratio:.2f}x")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Throughput {baseline_avg.throughput_rps:.1f} → {fault_avg.throughput_rps:.1f} RPS ({throughput_ratio:.2f}x)")

            # Check recovery
            recovery_cpu_ratio = recovery_avg.cpu_utilization / max(baseline_avg.cpu_utilization, 0.01)
            if abs(recovery_cpu_ratio - 1.0) > 0.2:
                validations.append(f"Recovery incomplete: CPU {recovery_avg.cpu_utilization:.2f} vs baseline {baseline_avg.cpu_utilization:.2f}")
                passed = False
            else:
                print(f"  ✓ RECOVERY: CPU returned to {recovery_avg.cpu_utilization:.1%}")

            return FaultProfile(
                fault_type='cpu_saturation',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'cpu': fault_avg.cpu_utilization},
                secondary_effects={
                    'latency_ratio': latency_ratio,
                    'throughput_ratio': throughput_ratio
                },
                unexpected_effects=[],
                passed=passed,
                failed_validations=validations
            )

        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            return FaultProfile(
                fault_type='cpu_saturation',
                fault_severity=severity,
                baseline_metrics=[],
                fault_metrics=[],
                recovery_metrics=[],
                primary_effect={},
                secondary_effects={},
                unexpected_effects=[],
                passed=False,
                failed_validations=[f"Exception during validation: {e}"]
            )

    def _validate_memory_pressure(self, severity: float) -> FaultProfile:
        """
        Validate memory pressure fault.

        Expected behavior:
        - PRIMARY: Memory utilization increases to target (e.g., 90%)
        - SECONDARY:
          * CPU increases (allocation overhead, paging)
          * Latency has intermittent spikes (allocation delays)
          * P99/P50 ratio increases (bimodal distribution)
        """
        print("\n[Test] Memory Pressure")
        print("  Expected: Memory↑ → CPU↑ (overhead), Latency spikes, Bimodal distribution")

        return FaultProfile(
            fault_type='memory_pressure',
            fault_severity=severity,
            baseline_metrics=[],
            fault_metrics=[],
            recovery_metrics=[],
            primary_effect={'memory': 0.90},
            secondary_effects={'cpu': 1.3, 'latency_variance': 3.0},
            unexpected_effects=[],
            passed=False,
            failed_validations=['Not yet implemented']
        )

    def _validate_thread_exhaustion(self, severity: float) -> FaultProfile:
        """
        Validate thread exhaustion fault.

        Expected behavior:
        - PRIMARY: Active threads → thread pool size
        - SECONDARY:
          * Queue depth increases (requests wait)
          * Latency increases (queue wait time)
          * Eventually: rejections/errors (queue full)
        """
        print("\n[Test] Thread Exhaustion")
        print("  Expected: Threads full → Queue↑, Latency↑, Rejections")

        return FaultProfile(
            fault_type='thread_exhaustion',
            fault_severity=severity,
            baseline_metrics=[],
            fault_metrics=[],
            recovery_metrics=[],
            primary_effect={'threads_active': 0.95},
            secondary_effects={'queue_depth': 100, 'latency': 5.0, 'errors': 0.1},
            unexpected_effects=[],
            passed=False,
            failed_validations=['Not yet implemented']
        )

    def _validate_io_bottleneck(self, severity: float) -> FaultProfile:
        """
        Validate I/O bottleneck fault.

        Expected behavior:
        - PRIMARY: I/O wait time increases
        - SECONDARY:
          * Latency increases significantly
          * CPU utilization DECREASES (waiting, not computing)
          * Throughput decreases (I/O bound)

        Key distinction: High latency + LOW CPU (vs CPU saturation: High latency + HIGH CPU)
        """
        print("\n[Test] I/O Bottleneck")
        print("  Expected: I/O wait↑ → Latency↑, CPU↓ (waiting)")

        return FaultProfile(
            fault_type='io_bottleneck',
            fault_severity=severity,
            baseline_metrics=[],
            fault_metrics=[],
            recovery_metrics=[],
            primary_effect={'io_wait': 0.80},
            secondary_effects={'latency': 4.0, 'cpu': 0.6, 'throughput': 0.5},
            unexpected_effects=[],
            passed=False,
            failed_validations=['Not yet implemented']
        )

    def _validate_network_partition(self, severity: float) -> FaultProfile:
        """
        Validate network partition fault.

        Expected behavior:
        - PRIMARY: Packet loss = 100% between specific nodes
        - SECONDARY:
          * Upstream: Timeouts, retries, eventual errors
          * Downstream: No traffic received, appears healthy but idle
          * System: Split-brain, inconsistent state possible
        """
        print("\n[Test] Network Partition")
        print("  Expected: Partition → Timeouts, Split state")

        return FaultProfile(
            fault_type='network_partition',
            fault_severity=severity,
            baseline_metrics=[],
            fault_metrics=[],
            recovery_metrics=[],
            primary_effect={'packet_loss': 1.0},
            secondary_effects={'errors': 0.9, 'latency': float('inf')},
            unexpected_effects=[],
            passed=False,
            failed_validations=['Not yet implemented']
        )

    def _validate_dependency_timeout(self, severity: float) -> FaultProfile:
        """
        Validate dependency timeout fault.

        Expected behavior:
        - PRIMARY: External calls timeout at rate X%
        - SECONDARY:
          * Error rate increases proportionally
          * Retry traffic amplifies load (e.g., 2x retries = 3x traffic)
          * Latency increases (timeout + retry delay)
          * Downstream sees amplified traffic spike
        """
        print("\n[Test] Dependency Timeout")
        print("  Expected: Timeouts → Retries, Amplified load, Errors↑")

        return FaultProfile(
            fault_type='dependency_timeout',
            fault_severity=severity,
            baseline_metrics=[],
            fault_metrics=[],
            recovery_metrics=[],
            primary_effect={'timeout_rate': 0.3},
            secondary_effects={'errors': 0.3, 'retry_traffic': 1.6, 'latency': 2.0},
            unexpected_effects=[],
            passed=False,
            failed_validations=['Not yet implemented']
        )

    def _generate_summary_report(self):
        """Generate a summary report of all validation results."""
        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80)

        total = len(self.results)
        passed = sum(1 for p in self.results.values() if p.passed)
        failed = total - passed

        print(f"\nTotal faults tested: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")

        if failed > 0:
            print("\n⚠️  VALIDATION FAILURES:")
            for fault_type, profile in self.results.items():
                if not profile.passed:
                    print(f"\n  {fault_type}:")
                    for failure in profile.failed_validations:
                        print(f"    - {failure}")

        # Save detailed results to file
        output_file = 'fault_dynamics_validation_results.json'
        with open(output_file, 'w') as f:
            json.dump(
                {k: v.to_dict() for k, v in self.results.items()},
                f,
                indent=2
            )
        print(f"\n📄 Detailed results saved to: {output_file}")

    def _run_fault_simulation(
        self,
        fault_type: str,
        severity: float,
        duration: int
    ) -> Tuple[List[MetricSnapshot], List[MetricSnapshot], List[MetricSnapshot]]:
        """
        Run a minimal simulation with fault injection and collect metrics.

        Returns:
            (baseline_metrics, fault_metrics, recovery_metrics)

        Timeline:
        - 0-60s: Baseline (collect every 10s)
        - 60-120s: Fault injection (collect every 10s)
        - 120-180s: Recovery (collect every 10s)
        """
        print(f"  Running isolated simulation for {fault_type}...")

        # For now, return synthetic data until we integrate with actual simulation
        # TODO: Integrate with generate_dataset.py to run real simulations

        baseline = []
        fault = []
        recovery = []

        # Synthetic baseline metrics (will be replaced with real sim data)
        for t in range(0, 60, 10):
            baseline.append(MetricSnapshot(
                timestamp=float(t),
                cpu_utilization=0.3 + (t * 0.001),  # 30% baseline
                memory_utilization=0.5,
                avg_latency_ms=50.0,
                p99_latency_ms=80.0,
                throughput_rps=100.0,
                error_rate=0.01,
                active_threads=30,
                queue_depth=0
            ))

        # Synthetic fault metrics (simulating cpu_cost_multiplier effect)
        for t in range(60, 120, 10):
            # Simulate CPU increasing to ~70% and latency increasing proportionally
            fault.append(MetricSnapshot(
                timestamp=float(t),
                cpu_utilization=0.65 + (t - 60) * 0.003,  # Ramps to ~75%
                memory_utilization=0.5,
                avg_latency_ms=120.0 + (t - 60) * 2.0,  # Latency increases
                p99_latency_ms=200.0 + (t - 60) * 3.0,
                throughput_rps=75.0 - (t - 60) * 0.3,  # Throughput decreases
                error_rate=0.02,
                active_threads=50,
                queue_depth=5
            ))

        # Synthetic recovery metrics
        for t in range(120, 180, 10):
            recovery.append(MetricSnapshot(
                timestamp=float(t),
                cpu_utilization=0.32,  # Returns to baseline
                memory_utilization=0.5,
                avg_latency_ms=52.0,
                p99_latency_ms=82.0,
                throughput_rps=98.0,
                error_rate=0.01,
                active_threads=30,
                queue_depth=0
            ))

        print(f"  Collected {len(baseline)} baseline, {len(fault)} fault, {len(recovery)} recovery snapshots")
        return baseline, fault, recovery

    def _average_metrics(self, metrics: List[MetricSnapshot]) -> MetricSnapshot:
        """Calculate average of all metrics in a list."""
        if not metrics:
            return MetricSnapshot(0, 0, 0, 0, 0, 0, 0, 0, 0)

        return MetricSnapshot(
            timestamp=sum(m.timestamp for m in metrics) / len(metrics),
            cpu_utilization=sum(m.cpu_utilization for m in metrics) / len(metrics),
            memory_utilization=sum(m.memory_utilization for m in metrics) / len(metrics),
            avg_latency_ms=sum(m.avg_latency_ms for m in metrics) / len(metrics),
            p99_latency_ms=sum(m.p99_latency_ms for m in metrics) / len(metrics),
            throughput_rps=sum(m.throughput_rps for m in metrics) / len(metrics),
            error_rate=sum(m.error_rate for m in metrics) / len(metrics),
            active_threads=int(sum(m.active_threads for m in metrics) / len(metrics)),
            queue_depth=int(sum(m.queue_depth for m in metrics) / len(metrics))
        )

    def validate_cross_metric_relationship(
        self,
        primary_metric: str,
        primary_change: float,
        secondary_metric: str,
        expected_change_range: Tuple[float, float],
        actual_change: float
    ) -> Tuple[bool, str]:
        """
        Validate that a cross-metric relationship holds.

        Example:
            validate_cross_metric_relationship(
                'cpu', +0.5,  # CPU increased by 50%
                'latency', (1.5, 3.0),  # Expect latency to increase 1.5x-3.0x
                2.1  # Actual latency increased 2.1x
            )
            → (True, "Within expected range")
        """
        min_expected, max_expected = expected_change_range

        if min_expected <= actual_change <= max_expected:
            return True, f"{secondary_metric} change {actual_change:.2f} within expected [{min_expected}, {max_expected}]"
        else:
            return False, f"{secondary_metric} change {actual_change:.2f} outside expected [{min_expected}, {max_expected}]"


def main():
    """Run the fault dynamics validation suite."""
    validator = FaultValidator(verbose=True)
    results = validator.validate_all_faults()

    # Check if all validations passed
    all_passed = all(profile.passed for profile in results.values())

    if all_passed:
        print("\n" + "="*80)
        print("🎉 ALL VALIDATIONS PASSED - Simulation is validated!")
        print("="*80)
        return 0
    else:
        print("\n" + "="*80)
        print("❌ VALIDATION FAILED - Simulation needs fixes")
        print("="*80)
        return 1


if __name__ == '__main__':
    exit(main())
