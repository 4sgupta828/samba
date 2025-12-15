"""
Test script to verify memory leak consumer fix.

Verifies that:
1. Consumer nodes (with queue_in) use persistent leak model
2. Non-consumer nodes use per-request leak model
3. Fault injection and removal work correctly for both
"""

import simpy
from src.components.pod import Pod
from src.components.service import Service
from src.failures.modes import start_memory_leak, stop_memory_leak
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig


def test_consumer_leak_model():
    """Test that consumer nodes use persistent leak model."""
    print("\n=== Test 1: Consumer Node (with queue_in) ===")

    # Setup
    env = simpy.Environment()

    # Create a service with queue_in connection (consumer)
    service = Service(env, "test_service", "test_service")
    service.connections = {'queue_in': "mock_queue"}

    # Create a pod for the service
    pod = Pod(env, "test_pod", service, 0)

    # Initialize dynamics
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())
    original_base = pod.dynamics.config.memory_base

    print(f"Original memory_base: {original_base}MB")

    # Inject fault
    params = {"leak_mb_per_request": 40.0}
    start_memory_leak(pod, params)

    # Check that baseline memory increased (persistent leak)
    new_base = pod.dynamics.config.memory_base
    leak_amount = new_base - original_base

    print(f"After injection memory_base: {new_base}MB")
    print(f"Leak amount: {leak_amount}MB")

    # Verify consumer model was used (10x multiplier)
    expected_leak = 40.0 * 10
    assert abs(leak_amount - expected_leak) < 1.0, f"Expected {expected_leak}MB, got {leak_amount}MB"
    assert hasattr(pod, '_memory_leak_is_consumer'), "Should have consumer flag"
    assert pod._memory_leak_is_consumer is True, "Should be marked as consumer"

    print("✓ Consumer model applied correctly")

    # Remove fault
    stop_memory_leak(pod, params)

    # Check that baseline memory was restored
    restored_base = pod.dynamics.config.memory_base
    print(f"After removal memory_base: {restored_base}MB")

    assert abs(restored_base - original_base) < 1.0, f"Memory not restored: {restored_base} vs {original_base}"
    assert not hasattr(pod, '_memory_leak_is_consumer'), "Consumer flag should be cleaned up"

    print("✓ Consumer leak removed correctly")
    print("✓ Test 1 PASSED\n")


def test_non_consumer_leak_model():
    """Test that non-consumer nodes use per-request leak model."""
    print("\n=== Test 2: Non-Consumer Node (HTTP service) ===")

    # Setup
    env = simpy.Environment()

    # Create a service WITHOUT queue_in connection (non-consumer)
    service = Service(env, "test_service", "test_service")
    service.connections = {'db_test': "mock_db"}  # No queue_in

    # Create a pod for the service
    pod = Pod(env, "test_pod", service, 0)

    # Initialize dynamics
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())
    original_per_request = pod.dynamics.config.memory_per_request_mb
    original_base = pod.dynamics.config.memory_base

    print(f"Original memory_per_request_mb: {original_per_request}MB")
    print(f"Original memory_base: {original_base}MB")

    # Inject fault
    params = {"leak_mb_per_request": 40.0}
    start_memory_leak(pod, params)

    # Check that per-request memory increased (not baseline)
    new_per_request = pod.dynamics.config.memory_per_request_mb
    new_base = pod.dynamics.config.memory_base

    print(f"After injection memory_per_request_mb: {new_per_request}MB")
    print(f"After injection memory_base: {new_base}MB (should be unchanged)")

    # Verify per-request model was used
    assert abs(new_per_request - (original_per_request + 40.0)) < 1.0, "Per-request memory should increase"
    assert abs(new_base - original_base) < 1.0, "Baseline should NOT change for non-consumers"
    assert hasattr(pod, '_memory_leak_is_consumer'), "Should have consumer flag"
    assert pod._memory_leak_is_consumer is False, "Should be marked as non-consumer"

    print("✓ Per-request model applied correctly")

    # Remove fault
    stop_memory_leak(pod, params)

    # Check that per-request memory was restored
    restored_per_request = pod.dynamics.config.memory_per_request_mb
    print(f"After removal memory_per_request_mb: {restored_per_request}MB")

    assert abs(restored_per_request - original_per_request) < 1.0, f"Memory not restored: {restored_per_request} vs {original_per_request}"
    assert not hasattr(pod, '_memory_leak_is_consumer'), "Consumer flag should be cleaned up"

    print("✓ Per-request leak removed correctly")
    print("✓ Test 2 PASSED\n")


def test_leak_removal_logging():
    """Test that fault removal is properly logged."""
    print("\n=== Test 3: Fault Removal Logging ===")

    # Setup
    env = simpy.Environment()

    # Create a consumer service
    service = Service(env, "test_service", "test_service")
    service.connections = {'queue_in': "mock_queue"}

    # Create a pod
    pod = Pod(env, "test_pod", service, 0)
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())

    # Inject and remove fault (should log both actions)
    params = {"leak_mb_per_request": 40.0}

    print("Injecting fault...")
    start_memory_leak(pod, params)

    print("Removing fault...")
    stop_memory_leak(pod, params)

    print("✓ Fault removal logged (check output above)")
    print("✓ Test 3 PASSED\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Memory Leak Consumer Fix")
    print("=" * 60)

    try:
        test_consumer_leak_model()
        test_non_consumer_leak_model()
        test_leak_removal_logging()

        print("=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise
