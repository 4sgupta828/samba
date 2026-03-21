#!/usr/bin/env python3
"""
Test that memory_pressure fault respects pod OOM limits.

This test verifies that the fix prevents pods from OOM killing by:
1. Using pod's actual memory_capacity_mb (not dynamics.config.memory_max)
2. Leaving safety margin for concurrent requests
3. Preventing memory from exceeding OOM kill threshold
"""

from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
from src.failures.modes import memory_pressure
from src.components.pod import Pod  # Import Pod for isinstance check

class MockPod(Pod):
    """Mock pod component for testing"""
    def __init__(self, memory_capacity_mb=512.0):
        # Don't call super().__init__() to avoid SimPy dependency
        # Just set the attributes we need for testing
        self.memory_capacity_mb = memory_capacity_mb  # Kubernetes memory limit (OOM kill threshold)

        # Dynamics engine with much higher max (this was the bug)
        self.dynamics = MetricsDynamicsEngine(DynamicsConfig(
            memory_max=2000.0,  # Dynamics engine allows up to 2000 MB
            memory_base=100.0,   # Baseline 100 MB
            memory_per_request_mb=5.0
        ))

        self.logs = []

    def _emit_log(self, level, message):
        self.logs.append((level, message))
        print(f"[{level}] {message}")


def test_oom_prevention():
    """Test that memory_pressure respects pod OOM limits"""

    print("Testing OOM Prevention with Fixed memory_pressure")
    print("=" * 60)

    # Create a pod with 512 MB limit
    pod = MockPod(memory_capacity_mb=512.0)

    print(f"\nPod Configuration:")
    print(f"  OOM kill limit: {pod.memory_capacity_mb} MB")
    print(f"  Dynamics max: {pod.dynamics.config.memory_max} MB")
    print(f"  Memory baseline: {pod.dynamics.config.memory_base} MB")
    print(f"  Memory per request: {pod.dynamics.config.memory_per_request_mb} MB")

    # Apply memory_pressure fault at full progress (severity 0.5)
    print(f"\nApplying memory_pressure fault (severity=0.5, progress=1.0)...")
    memory_pressure(pod, {'severity': 0.5, 'progress': 1.0})

    # Check the new memory baseline
    new_baseline = pod.dynamics.config.memory_base

    print(f"\nResults:")
    print(f"  New memory baseline: {new_baseline:.1f} MB")

    # Simulate high load (20 concurrent requests)
    estimated_concurrent_memory = 20 * pod.dynamics.config.memory_per_request_mb
    estimated_peak_memory = new_baseline + estimated_concurrent_memory

    print(f"  Estimated peak memory (20 concurrent): {estimated_peak_memory:.1f} MB")
    print(f"  OOM kill threshold: {pod.memory_capacity_mb} MB")

    # Verify memory stays below OOM threshold
    margin = pod.memory_capacity_mb - estimated_peak_memory
    print(f"  Safety margin: {margin:.1f} MB")

    # Check if fix worked
    checks = []

    # Memory should stay below OOM limit
    check1 = estimated_peak_memory < pod.memory_capacity_mb
    checks.append(("Memory stays below OOM limit", check1,
                   f"{estimated_peak_memory:.1f} < {pod.memory_capacity_mb:.1f} MB"))

    # Should have reasonable margin (at least 30 MB)
    check2 = margin >= 30.0
    checks.append(("Adequate safety margin", check2, f"{margin:.1f} MB"))

    # Memory should still be elevated (pressure applied)
    check3 = new_baseline > 100.0
    checks.append(("Memory pressure applied", check3, f"{new_baseline:.1f} > 100.0 MB"))

    # Should not have skipped due to insufficient headroom
    skip_log = any("skipped" in msg.lower() for _, msg in pod.logs)
    check4 = not skip_log
    checks.append(("Fault not skipped", check4, "Applied successfully"))

    print(f"\nVerification:")
    all_passed = True
    for check_name, passed, detail in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} {check_name}: {detail}")
        if not passed:
            all_passed = False

    return all_passed


def test_insufficient_headroom():
    """Test that memory_pressure skips when there's insufficient headroom"""

    print("\n" + "=" * 60)
    print("Testing Insufficient Headroom Handling")
    print("=" * 60)

    # Create a pod with high baseline (already near limit)
    pod = MockPod(memory_capacity_mb=512.0)
    pod.dynamics.config.memory_base = 450.0  # Already at 450 MB (87.9%)

    print(f"\nPod Configuration:")
    print(f"  OOM kill limit: {pod.memory_capacity_mb} MB")
    print(f"  Memory baseline: {pod.dynamics.config.memory_base} MB ({pod.dynamics.config.memory_base/pod.memory_capacity_mb*100:.1f}%)")

    # Try to apply memory_pressure
    print(f"\nAttempting to apply memory_pressure fault...")
    memory_pressure(pod, {'severity': 0.5, 'progress': 1.0})

    # Check if it was skipped
    skip_log = any("skipped" in msg.lower() for _, msg in pod.logs)

    print(f"\nResult:")
    if skip_log:
        print(f"  ✓ PASS: Fault correctly skipped due to insufficient headroom")
        return True
    else:
        print(f"  ✗ FAIL: Fault should have been skipped but wasn't")
        return False


def test_before_fix_would_oom():
    """Demonstrate what would happen with the old buggy code"""

    print("\n" + "=" * 60)
    print("Demonstrating Bug (Old Code Behavior)")
    print("=" * 60)

    pod = MockPod(memory_capacity_mb=512.0)

    # Simulate old buggy calculation
    old_memory_max = pod.dynamics.config.memory_max  # 2000 MB (WRONG!)
    old_available_headroom = old_memory_max - pod.dynamics.config.memory_base

    severity = 0.5
    scale = 0.8  # For severity 0.5
    old_target_increase = old_available_headroom * 0.70 * scale
    old_target_increase = min(old_available_headroom * 0.9, old_target_increase)

    old_new_baseline = pod.dynamics.config.memory_base + old_target_increase
    old_peak_memory = old_new_baseline + (20 * pod.dynamics.config.memory_per_request_mb)

    print(f"\nOld (buggy) calculation:")
    print(f"  Used dynamics.memory_max: {old_memory_max} MB (WRONG!)")
    print(f"  Calculated increase: +{old_target_increase:.1f} MB")
    print(f"  New baseline would be: {old_new_baseline:.1f} MB")
    print(f"  Peak memory would be: {old_peak_memory:.1f} MB")
    print(f"  OOM limit: {pod.memory_capacity_mb} MB")
    print(f"  Result: {'❌ OOM KILL!' if old_peak_memory > pod.memory_capacity_mb else '✓ OK'}")

    # Now show new calculation
    new_memory_max = pod.memory_capacity_mb  # 512 MB (CORRECT!)
    safety_margin = max(50.0, pod.dynamics.config.memory_per_request_mb * 20)
    new_available_headroom = new_memory_max - pod.dynamics.config.memory_base - safety_margin
    new_target_increase = new_available_headroom * 0.70 * scale
    new_target_increase = min(new_available_headroom * 0.85, new_target_increase)

    new_new_baseline = pod.dynamics.config.memory_base + new_target_increase
    new_peak_memory = new_new_baseline + (20 * pod.dynamics.config.memory_per_request_mb)

    print(f"\nNew (fixed) calculation:")
    print(f"  Uses pod.memory_capacity_mb: {new_memory_max} MB (CORRECT!)")
    print(f"  Safety margin: {safety_margin:.1f} MB")
    print(f"  Available headroom: {new_available_headroom:.1f} MB")
    print(f"  Calculated increase: +{new_target_increase:.1f} MB")
    print(f"  New baseline would be: {new_new_baseline:.1f} MB")
    print(f"  Peak memory would be: {new_peak_memory:.1f} MB")
    print(f"  OOM limit: {pod.memory_capacity_mb} MB")
    print(f"  Result: {'✓ NO OOM!' if new_peak_memory < pod.memory_capacity_mb else '❌ OOM KILL!'}")

    return new_peak_memory < pod.memory_capacity_mb


if __name__ == "__main__":
    print("Memory Pressure OOM Fix Validation")
    print("=" * 60)
    print()

    test1 = test_oom_prevention()
    test2 = test_insufficient_headroom()
    test3 = test_before_fix_would_oom()

    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)

    if test1 and test2 and test3:
        print("✅ ALL TESTS PASSED")
        print("\nThe fix successfully prevents OOM kills by:")
        print("1. Using pod's actual memory_capacity_mb (not dynamics.memory_max)")
        print("2. Leaving safety margin for concurrent requests")
        print("3. Preventing memory from exceeding OOM threshold")
    else:
        print("❌ SOME TESTS FAILED")
        exit(1)
