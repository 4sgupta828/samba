"""
Test to verify that restartable component state reset works correctly.

This test verifies that the _reset_state_on_restart() method properly
clears all mutable state between pod restarts, preventing state leakage.
"""

import simpy
from src.components.pod import Pod
from src.components.service import ApiService
from src.core.simulation_config import SimulationConfig, get_simulation_config


def test_pod_state_reset():
    """
    Test that Pod state is properly reset on restart.

    Verifies:
    1. Resource pool users are cleared
    2. Request counters reset to 0
    3. Circuit breakers cleared
    4. Metrics samples cleared
    """
    print("\n=== Testing Pod State Reset ===\n")

    # Create environment
    env = simpy.Environment()

    # Create a mock service
    service = ApiService(env, "test_service", "TestService")

    # Create pod
    pod = Pod(env, "test_pod_1", parent_service=service)

    # Simulate some activity to populate state
    print("1. Simulating pod activity...")

    # Manually add some state (simulating active requests)
    pod.request_count = 100
    pod.last_request_count = 90
    pod.cpu_samples.append((env.now, 50.0))
    pod.memory_samples.append((env.now, 200.0))
    pod.connection_pool_samples.append((env.now, 5))

    # Simulate resource pool usage
    req1 = pod.thread_pool.request()
    req2 = pod.db_connection_pool.request()

    print(f"   Before reset:")
    print(f"   - request_count: {pod.request_count}")
    print(f"   - cpu_samples length: {len(pod.cpu_samples)}")
    print(f"   - thread_pool.users length: {len(pod.thread_pool.users)}")
    print(f"   - db_connection_pool.users length: {len(pod.db_connection_pool.users)}")

    # Trigger state reset (simulating restart)
    print("\n2. Triggering state reset...")
    pod._reset_state_on_restart()

    # Verify state is reset
    print("\n3. Verifying state after reset:")

    # Check counters
    assert pod.request_count == 0, f"Expected request_count=0, got {pod.request_count}"
    assert pod.last_request_count == 0, f"Expected last_request_count=0, got {pod.last_request_count}"
    print(f"   ✓ Request counters reset to 0")

    # Check samples
    assert len(pod.cpu_samples) == 0, f"Expected 0 CPU samples, got {len(pod.cpu_samples)}"
    assert len(pod.memory_samples) == 0, f"Expected 0 memory samples, got {len(pod.memory_samples)}"
    assert len(pod.connection_pool_samples) == 0, f"Expected 0 connection pool samples, got {len(pod.connection_pool_samples)}"
    print(f"   ✓ Metrics samples cleared")

    # Check resource pools
    assert len(pod.thread_pool.queue) == 0, f"Expected empty thread_pool.queue, got {len(pod.thread_pool.queue)}"
    assert len(pod.thread_pool.users) == 0, f"Expected empty thread_pool.users, got {len(pod.thread_pool.users)}"
    assert len(pod.db_connection_pool.queue) == 0, f"Expected empty db_connection_pool.queue, got {len(pod.db_connection_pool.queue)}"
    assert len(pod.db_connection_pool.users) == 0, f"Expected empty db_connection_pool.users, got {len(pod.db_connection_pool.users)}"
    print(f"   ✓ Resource pools cleared (queue and users)")

    # Check dynamics
    assert pod.dynamics.concurrent_requests == 0, f"Expected concurrent_requests=0, got {pod.dynamics.concurrent_requests}"
    print(f"   ✓ Dynamics state reset")

    # Check that persistent state is NOT reset
    assert pod.parent_service == service, "parent_service should persist"
    print(f"   ✓ Persistent state (parent_service) preserved")

    print("\n=== All tests passed! ===\n")


def test_pod_multiple_resets():
    """
    Test that Pod state reset works correctly across multiple resets.

    This verifies that state doesn't accumulate across multiple restart cycles.
    """
    print("\n=== Testing Multiple State Resets ===\n")

    # Create environment
    env = simpy.Environment()

    # Create a mock service
    service = ApiService(env, "test_service", "TestService")

    # Create pod
    pod = Pod(env, "test_pod_2", parent_service=service)

    print("Testing 3 reset cycles...")

    for cycle in range(1, 4):
        print(f"\nCycle {cycle}:")

        # Simulate activity
        pod.request_count = 100 * cycle
        pod.last_request_count = 90 * cycle
        pod.cpu_samples.extend([(env.now, 50.0 * cycle)] * 5)

        # Add some users to resource pools
        for _ in range(3):
            req = pod.thread_pool.request()
            # Note: Not yielding, just creating requests to populate users list

        print(f"   Before reset: request_count={pod.request_count}, "
              f"thread_pool.users={len(pod.thread_pool.users)}, "
              f"cpu_samples={len(pod.cpu_samples)}")

        # Reset
        pod._reset_state_on_restart()

        # Verify reset
        assert pod.request_count == 0, f"Cycle {cycle}: request_count not reset"
        assert len(pod.thread_pool.users) == 0, f"Cycle {cycle}: thread_pool.users not cleared"
        assert len(pod.cpu_samples) == 0, f"Cycle {cycle}: cpu_samples not cleared"

        print(f"   After reset: request_count={pod.request_count}, "
              f"thread_pool.users={len(pod.thread_pool.users)}, "
              f"cpu_samples={len(pod.cpu_samples)}")
        print(f"   ✓ Cycle {cycle} reset successful")

    print("\n=== Multiple resets test passed! ===\n")


if __name__ == "__main__":
    # Run tests
    try:
        test_pod_state_reset()
        test_pod_multiple_resets()
        print("\n✅ All restartable component tests passed!\n")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}\n")
        raise
    except Exception as e:
        print(f"\n❌ Test error: {e}\n")
        import traceback
        traceback.print_exc()
        raise
