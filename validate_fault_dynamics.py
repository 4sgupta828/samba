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

        try:
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='memory_pressure',
                severity=severity,
                duration=180
            )

            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            validations = []
            passed = True

            # Primary effect: Memory should increase
            memory_ratio = fault_avg.memory_utilization / max(baseline_avg.memory_utilization, 1.0)
            if memory_ratio < 1.5:  # Should increase by at least 1.5x
                validations.append(f"Memory didn't increase enough: {memory_ratio:.2f}x (expected >1.5x)")
                passed = False
            else:
                print(f"  ✓ PRIMARY: Memory {baseline_avg.memory_utilization:.1f}% → {fault_avg.memory_utilization:.1f}% ({memory_ratio:.2f}x)")

            # Secondary effect: CPU should increase due to overhead
            cpu_ratio = fault_avg.cpu_utilization / max(baseline_avg.cpu_utilization, 1.0)
            if cpu_ratio < 1.2 or cpu_ratio > 1.5:
                validations.append(f"CPU overhead out of range: {cpu_ratio:.2f}x (expected 1.2-1.5x)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: CPU {baseline_avg.cpu_utilization:.1f}% → {fault_avg.cpu_utilization:.1f}% ({cpu_ratio:.2f}x)")

            # Check latency variance (P99/P50 ratio)
            p50_baseline = baseline_avg.avg_latency_ms
            p99_baseline = baseline_avg.p99_latency_ms
            p50_fault = fault_avg.avg_latency_ms
            p99_fault = fault_avg.p99_latency_ms

            variance_baseline = p99_baseline / max(p50_baseline, 1.0)
            variance_fault = p99_fault / max(p50_fault, 1.0)

            if variance_fault / max(variance_baseline, 1.0) < 2.0:
                validations.append(f"Latency variance didn't increase enough (bimodal distribution expected)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Latency variance P99/P50: {variance_baseline:.2f} → {variance_fault:.2f}")

            return FaultProfile(
                fault_type='memory_pressure',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'memory': fault_avg.memory_utilization},
                secondary_effects={
                    'cpu_ratio': cpu_ratio,
                    'latency_variance': variance_fault
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
                fault_type='memory_pressure',
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

        try:
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='thread_exhaustion',
                severity=severity,
                duration=180
            )

            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            validations = []
            passed = True

            # Primary effect: Thread saturation
            thread_saturation = fault_avg.active_threads / 50.0  # Default thread pool size
            if thread_saturation < 0.7:
                validations.append(f"Thread saturation too low: {thread_saturation:.2f} (expected >0.7)")
                passed = False
            else:
                print(f"  ✓ PRIMARY: Thread saturation {thread_saturation:.1%}")

            # Secondary effect: Queue depth should increase
            if fault_avg.queue_depth <= baseline_avg.queue_depth:
                validations.append(f"Queue depth didn't increase: {fault_avg.queue_depth} vs baseline {baseline_avg.queue_depth}")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Queue depth {baseline_avg.queue_depth} → {fault_avg.queue_depth}")

            # Secondary effect: Latency should increase
            latency_ratio = fault_avg.avg_latency_ms / max(baseline_avg.avg_latency_ms, 1.0)
            if latency_ratio < 1.5:
                validations.append(f"Latency didn't increase enough: {latency_ratio:.2f}x (expected >1.5x)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Latency {baseline_avg.avg_latency_ms:.1f}ms → {fault_avg.avg_latency_ms:.1f}ms ({latency_ratio:.2f}x)")

            return FaultProfile(
                fault_type='thread_exhaustion',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'thread_saturation': thread_saturation},
                secondary_effects={
                    'queue_depth': fault_avg.queue_depth,
                    'latency_ratio': latency_ratio
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
                fault_type='thread_exhaustion',
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

        try:
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='io_bottleneck',
                severity=severity,
                duration=180
            )

            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            validations = []
            passed = True

            # Primary effect: Latency should increase significantly
            latency_ratio = fault_avg.avg_latency_ms / max(baseline_avg.avg_latency_ms, 1.0)
            if latency_ratio < 3.0:
                validations.append(f"Latency increase too small: {latency_ratio:.2f}x (expected >3x)")
                passed = False
            else:
                print(f"  ✓ PRIMARY: Latency {baseline_avg.avg_latency_ms:.1f}ms → {fault_avg.avg_latency_ms:.1f}ms ({latency_ratio:.2f}x)")

            # KEY VALIDATION: CPU should NOT increase much (I/O bound, not CPU bound)
            cpu_ratio = fault_avg.cpu_utilization / max(baseline_avg.cpu_utilization, 1.0)
            if cpu_ratio > 1.3:  # CPU shouldn't increase much for I/O bottleneck
                validations.append(f"CPU increased too much: {cpu_ratio:.2f}x (expected <1.3x for I/O bottleneck)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: CPU relatively stable {baseline_avg.cpu_utilization:.1f}% → {fault_avg.cpu_utilization:.1f}% ({cpu_ratio:.2f}x)")

            # Throughput should decrease
            throughput_ratio = fault_avg.throughput_rps / max(baseline_avg.throughput_rps, 1.0)
            if throughput_ratio > 0.7:
                validations.append(f"Throughput didn't decrease enough: {throughput_ratio:.2f}x (expected <0.7x)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Throughput {baseline_avg.throughput_rps:.1f} → {fault_avg.throughput_rps:.1f} RPS ({throughput_ratio:.2f}x)")

            return FaultProfile(
                fault_type='io_bottleneck',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'latency_ratio': latency_ratio},
                secondary_effects={
                    'cpu_ratio': cpu_ratio,
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
                fault_type='io_bottleneck',
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

        try:
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='network_partition',
                severity=severity,
                duration=180
            )

            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            validations = []
            passed = True

            # Primary effect: Errors should spike dramatically
            error_ratio = fault_avg.error_rate / max(baseline_avg.error_rate, 0.01)
            if error_ratio < 10.0:  # Should increase by at least 10x
                validations.append(f"Error rate didn't spike enough: {error_ratio:.2f}x (expected >10x)")
                passed = False
            else:
                print(f"  ✓ PRIMARY: Error rate {baseline_avg.error_rate:.2f}% → {fault_avg.error_rate:.2f}% ({error_ratio:.2f}x)")

            # Secondary effect: Latency should increase significantly (timeouts)
            latency_ratio = fault_avg.avg_latency_ms / max(baseline_avg.avg_latency_ms, 1.0)
            if latency_ratio < 5.0:
                validations.append(f"Latency didn't spike enough: {latency_ratio:.2f}x (expected >5x for timeouts)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Latency {baseline_avg.avg_latency_ms:.1f}ms → {fault_avg.avg_latency_ms:.1f}ms ({latency_ratio:.2f}x)")

            # Throughput should collapse
            throughput_ratio = fault_avg.throughput_rps / max(baseline_avg.throughput_rps, 1.0)
            if throughput_ratio > 0.3:
                validations.append(f"Throughput didn't collapse: {throughput_ratio:.2f}x (expected <0.3x)")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Throughput {baseline_avg.throughput_rps:.1f} → {fault_avg.throughput_rps:.1f} RPS ({throughput_ratio:.2f}x)")

            return FaultProfile(
                fault_type='network_partition',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'error_ratio': error_ratio},
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
                fault_type='network_partition',
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

        try:
            baseline_metrics, fault_metrics, recovery_metrics = self._run_fault_simulation(
                fault_type='dependency_timeout',
                severity=severity,
                duration=180
            )

            baseline_avg = self._average_metrics(baseline_metrics)
            fault_avg = self._average_metrics(fault_metrics)
            recovery_avg = self._average_metrics(recovery_metrics)

            validations = []
            passed = True

            # Primary effect: Latency should increase (timeouts)
            latency_ratio = fault_avg.avg_latency_ms / max(baseline_avg.avg_latency_ms, 1.0)
            if latency_ratio < 1.5:
                validations.append(f"Latency didn't increase enough: {latency_ratio:.2f}x (expected >1.5x)")
                passed = False
            else:
                print(f"  ✓ PRIMARY: Latency {baseline_avg.avg_latency_ms:.1f}ms → {fault_avg.avg_latency_ms:.1f}ms ({latency_ratio:.2f}x)")

            # Secondary effect: Errors should increase proportionally
            error_increase = fault_avg.error_rate - baseline_avg.error_rate
            expected_error_increase = severity * 30.0  # 30% at severity=1.0
            if abs(error_increase - expected_error_increase) > 15.0:  # ±15% tolerance
                validations.append(f"Error rate increase doesn't match severity: {error_increase:.2f}% vs expected {expected_error_increase:.2f}%")
                passed = False
            else:
                print(f"  ✓ SECONDARY: Error rate {baseline_avg.error_rate:.2f}% → {fault_avg.error_rate:.2f}% (+{error_increase:.2f}%)")

            # Check that errors are reasonable for dependency timeouts
            if fault_avg.error_rate > 50.0:
                validations.append(f"Error rate too high: {fault_avg.error_rate:.2f}% (partial timeout should not cause 100% errors)")
                passed = False

            return FaultProfile(
                fault_type='dependency_timeout',
                fault_severity=severity,
                baseline_metrics=baseline_metrics,
                fault_metrics=fault_metrics,
                recovery_metrics=recovery_metrics,
                primary_effect={'latency_ratio': latency_ratio},
                secondary_effects={
                    'error_increase': error_increase,
                    'error_rate': fault_avg.error_rate
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
                fault_type='dependency_timeout',
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

        # Create a minimal test topology
        env = simpy.Environment()

        # Import required components
        from src.components.pod import Pod
        from src.components.compute_node import ComputeNode
        from src.components.service import Service
        from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig

        # Create a simple service with a pod for testing
        compute_node = ComputeNode(env, "node_0", cpu_cores=4, memory_gb=8)

        # Create a pod with dynamics engine enabled
        pod = Pod(
            env=env,
            component_id="pod_test_0",
            compute_node=compute_node
        )

        # Override the pod's dynamics config for testing
        if pod.dynamics:
            pod.dynamics.config.latency_base = 50.0
            pod.dynamics.config.cpu_from_concurrent_coef = 0.5
            pod.dynamics.config.memory_base = 200.0
            pod.dynamics.config.memory_per_request_mb = 5.0
            pod.dynamics.config.throughput_capacity = 100.0

        # Mark pod as RUNNING (needed for service routing)
        pod.state.operational = "RUNNING"

        # Create service
        service = Service(
            env=env,
            component_id="service_test",
            service_name="test_service",
            supported_request_types=["GET"],
            desired_replicas=1
        )
        service.pods = [pod]
        pod.parent_service = service

        # Component registry
        component_registry = {
            "node_0": compute_node,
            "pod_test_0": pod,
            "service_test": service
        }

        # Metric collection containers
        baseline = []
        fault = []
        recovery = []

        # Workload process to generate requests
        def workload_generator():
            """Generate constant workload throughout simulation."""
            request_interval = 1.0 / 50.0  # 50 RPS
            while True:
                try:
                    # Make request to service
                    yield from service.handle_request("GET", should_trace=False)
                except Exception as e:
                    pass  # Ignore errors for validation
                yield env.timeout(request_interval)

        # Metrics collection process
        def collect_metrics(phase: str, collection_list: List[MetricSnapshot], start: float, end: float):
            """Collect metrics every 10 seconds."""
            t = start
            while t < end:
                yield env.timeout(min(10.0, end - t))
                t = env.now

                # Collect metrics from pod's dynamics engine
                if pod.dynamics:
                    snapshot = MetricSnapshot(
                        timestamp=t,
                        cpu_utilization=pod.dynamics.get_cpu_percent(),
                        memory_utilization=pod.dynamics.get_memory() / pod.memory_capacity_mb * 100.0,  # Convert MB to %
                        avg_latency_ms=pod.dynamics.get_latency(),
                        p99_latency_ms=pod.dynamics.get_latency_percentile(99),
                        throughput_rps=pod.dynamics.get_throughput(),
                        error_rate=pod.dynamics.get_error_rate() * 100.0,  # Convert to %
                        active_threads=int(pod.dynamics.concurrent_requests),
                        queue_depth=pod.dynamics.queue_depth
                    )
                    collection_list.append(snapshot)
                    if self.verbose:
                        print(f"    [{phase} {t:.0f}s] CPU={snapshot.cpu_utilization:.1f}% Latency={snapshot.avg_latency_ms:.1f}ms Throughput={snapshot.throughput_rps:.1f}rps")

        # Fault injection process
        def inject_fault():
            """Inject fault at t=60s."""
            yield env.timeout(60.0)

            # Apply fault based on type
            if fault_type == 'cpu_saturation':
                # Inject CPU saturation via cpu_cost_multiplier
                target_cpu = 0.85  # Target 85% CPU
                baseline_cpu = pod.dynamics.get_cpu_percent() / 100.0
                cpu_multiplier = (target_cpu / max(baseline_cpu, 0.1)) * severity
                pod.dynamics.cpu_multiplier = max(1.0, cpu_multiplier)
                print(f"  → Injected cpu_saturation: cpu_multiplier={cpu_multiplier:.2f}")

            elif fault_type == 'memory_pressure':
                # Inject memory pressure via increased memory per request
                pod.dynamics.config.memory_per_request_mb *= (1.0 + severity * 3.0)
                print(f"  → Injected memory_pressure: memory_per_request={pod.dynamics.config.memory_per_request_mb:.1f}MB")

            elif fault_type == 'thread_exhaustion':
                # Inject thread exhaustion by limiting thread pool
                pod.dynamics.thread_pool_size = max(10, int(pod.dynamics.thread_pool_size * (1.0 - severity)))
                print(f"  → Injected thread_exhaustion: thread_pool_size={pod.dynamics.thread_pool_size}")

            elif fault_type == 'io_bottleneck':
                # Inject I/O bottleneck via latency increase
                pod.dynamics.latency_multiplier = 1.0 + severity * 4.0
                print(f"  → Injected io_bottleneck: latency_multiplier={pod.dynamics.latency_multiplier:.2f}")

            elif fault_type == 'network_partition':
                # Inject network partition via error injection
                pod.dynamics.fault_error_additive = severity * 0.9
                pod.dynamics.fault_latency_additive_ms = 5000  # Timeout delay
                print(f"  → Injected network_partition: error_rate={pod.dynamics.fault_error_additive:.2f}")

            elif fault_type == 'dependency_timeout':
                # Inject dependency timeout via latency and errors
                pod.dynamics.fault_latency_additive_ms = severity * 3000
                pod.dynamics.fault_error_additive = severity * 0.3
                print(f"  → Injected dependency_timeout: latency_additive={pod.dynamics.fault_latency_additive_ms:.0f}ms")

            # Wait for fault duration (60s)
            yield env.timeout(60.0)

            # Revert fault at t=120s
            pod.dynamics.cpu_multiplier = 1.0
            pod.dynamics.latency_multiplier = 1.0
            pod.dynamics.error_rate_multiplier = 1.0
            pod.dynamics.fault_latency_additive_ms = 0.0
            pod.dynamics.fault_error_additive = 0.0
            pod.dynamics.fault_cpu_floor_percent = None
            pod.dynamics.fault_latency_floor_ms = None
            print(f"  → Reverted fault at t={env.now:.0f}s")

        # Start all processes
        env.process(workload_generator())
        env.process(collect_metrics("BASELINE", baseline, 0, 60))
        env.process(inject_fault())
        env.process(collect_metrics("FAULT", fault, 60, 120))
        env.process(collect_metrics("RECOVERY", recovery, 120, 180))

        # Run simulation
        env.run(until=duration)

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
