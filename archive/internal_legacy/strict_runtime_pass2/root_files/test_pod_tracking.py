#!/usr/bin/env python3
"""
Test pod ID tracking robustness for structural faults.

Validates that faults correctly track and revert specific pods even when
pods are dynamically replaced by the DeploymentController.
"""

import simpy
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.components.service import Service
from src.components.pod import Pod
from src.failures.modes import noisy_neighbor, revert_noisy_neighbor, thread_exhaustion, revert_thread_exhaustion


def test_noisy_neighbor_pod_tracking():
    """Test that noisy_neighbor tracks the correct pod ID."""
    print("\n" + "="*60)
    print("TEST: Noisy Neighbor Pod ID Tracking")
    print("="*60)

    env = simpy.Environment()

    # Create service with 3 pods
    service = Service(env, "service_1", "test_service", desired_replicas=3)
    pod1 = Pod(env, "pod_1", parent_service=service)
    pod2 = Pod(env, "pod_2", parent_service=service)
    pod3 = Pod(env, "pod_3", parent_service=service)

    pod1.state.operational = "RUNNING"
    pod2.state.operational = "RUNNING"
    pod3.state.operational = "RUNNING"

    service.pods = [pod1, pod2, pod3]

    print(f"\nInitial pods: {[p.id for p in service.pods]}")

    # Apply noisy_neighbor to service (should target pod_1)
    print(f"\nApplying noisy_neighbor to service...")
    noisy_neighbor(service, {"cpu_percent": 100.0})

    # Verify pod ID was tracked
    assert hasattr(service, '_noisy_neighbor_pod_id'), "Pod ID not tracked on service"
    tracked_pod_id = service._noisy_neighbor_pod_id
    print(f"✅ Tracked pod ID: {tracked_pod_id}")

    # Verify fault was applied
    assert pod1.dynamics.fault_cpu_floor_percent == 100.0, "Fault not applied"
    print(f"✅ Fault applied to {pod1.id}: CPU floor = {pod1.dynamics.fault_cpu_floor_percent}%")

    # Simulate pod replacement (pod_1 dies, new pod_4 takes its place)
    print(f"\nSimulating pod replacement...")
    service.pods.remove(pod1)
    pod4 = Pod(env, "pod_4", parent_service=service)
    pod4.state.operational = "RUNNING"
    service.pods.insert(0, pod4)  # New pod at position 0

    print(f"Updated pods: {[p.id for p in service.pods]}")
    print(f"Note: pod_1 (with fault) removed, pod_4 (clean) added at position 0")

    # Try to revert - should detect pod is gone
    print(f"\nAttempting to revert noisy_neighbor...")
    revert_noisy_neighbor(service, {})

    # Verify tracking was cleaned up
    assert not hasattr(service, '_noisy_neighbor_pod_id'), "Pod ID tracking not cleaned up"
    print(f"✅ Gracefully handled missing pod - tracking cleaned up")

    print(f"\n✅ TEST PASSED: Pod ID tracking is robust against pod replacement")
    return True


def test_thread_exhaustion_pod_tracking():
    """Test that thread_exhaustion tracks the correct pod ID."""
    print("\n" + "="*60)
    print("TEST: Thread Exhaustion Pod ID Tracking")
    print("="*60)

    env = simpy.Environment()

    # Create service with 2 pods
    service = Service(env, "service_1", "test_service", desired_replicas=2)
    pod1 = Pod(env, "pod_1", parent_service=service)
    pod2 = Pod(env, "pod_2", parent_service=service)

    pod1.state.operational = "RUNNING"
    pod2.state.operational = "RUNNING"

    service.pods = [pod1, pod2]

    print(f"\nInitial pods: {[p.id for p in service.pods]}")

    # Apply thread_exhaustion to service (should target pod_1)
    print(f"\nApplying thread_exhaustion to service...")
    thread_exhaustion(service, {"locked_threads": 5, "duration": 10.0})

    # Run simulation to let zombie tasks acquire threads
    env.run(until=0.1)

    # Verify pod ID was tracked
    assert hasattr(service, '_force_deadlock_pod_id'), "Pod ID not tracked on service"
    tracked_pod_id = service._force_deadlock_pod_id
    print(f"✅ Tracked pod ID: {tracked_pod_id}")

    # Verify threads were locked
    assert pod1.thread_pool.count == 5, f"Expected 5 locked threads, got {pod1.thread_pool.count}"
    print(f"✅ 5 threads locked on {pod1.id}")

    # Revert on the correct pod (pod still exists)
    print(f"\nReverting thread_exhaustion (pod still exists)...")
    revert_thread_exhaustion(service, {})

    # Run simulation to process interrupts
    env.run(until=0.2)

    # Verify threads were released
    assert pod1.thread_pool.count == 0, f"Expected 0 threads, got {pod1.thread_pool.count}"
    print(f"✅ All threads released on {pod1.id}")

    # Verify tracking was cleaned up
    assert not hasattr(service, '_force_deadlock_pod_id'), "Pod ID tracking not cleaned up"
    print(f"✅ Pod ID tracking cleaned up")

    print(f"\n✅ TEST PASSED: Pod ID tracking correctly reverts on the tracked pod")
    return True


def test_concurrent_faults():
    """Test that multiple faults track different pods independently."""
    print("\n" + "="*60)
    print("TEST: Concurrent Faults on Different Pods")
    print("="*60)

    env = simpy.Environment()

    # Create service with 3 pods
    service = Service(env, "service_1", "test_service", desired_replicas=3)
    pod1 = Pod(env, "pod_1", parent_service=service)
    pod2 = Pod(env, "pod_2", parent_service=service)
    pod3 = Pod(env, "pod_3", parent_service=service)

    for pod in [pod1, pod2, pod3]:
        pod.state.operational = "RUNNING"

    service.pods = [pod1, pod2, pod3]

    print(f"\nInitial pods: {[p.id for p in service.pods]}")

    # Apply noisy_neighbor (should target pod_1)
    print(f"\nApplying noisy_neighbor...")
    noisy_neighbor(service, {"cpu_percent": 100.0})
    noisy_pod_id = service._noisy_neighbor_pod_id
    print(f"✅ noisy_neighbor tracking: {noisy_pod_id}")

    # Apply thread_exhaustion (should also target pod_1, but tracked separately)
    print(f"\nApplying thread_exhaustion...")
    thread_exhaustion(service, {"locked_threads": 3, "duration": 10.0})
    env.run(until=0.1)
    deadlock_pod_id = service._force_deadlock_pod_id
    print(f"✅ thread_exhaustion tracking: {deadlock_pod_id}")

    # Both should track the same pod (pod_1) but independently
    assert noisy_pod_id == deadlock_pod_id == "pod_1"
    print(f"✅ Both faults correctly track pod_1")

    # Verify both faults are active
    assert pod1.dynamics.fault_cpu_floor_percent == 100.0
    assert pod1.thread_pool.count == 3
    print(f"✅ Both faults active on {pod1.id}")

    # Revert noisy_neighbor first
    print(f"\nReverting noisy_neighbor...")
    revert_noisy_neighbor(service, {})
    assert not hasattr(service, '_noisy_neighbor_pod_id')
    assert pod1.dynamics.fault_cpu_floor_percent is None
    print(f"✅ noisy_neighbor reverted, tracking cleaned up")

    # Revert thread_exhaustion second
    print(f"\nReverting thread_exhaustion...")
    revert_thread_exhaustion(service, {})
    env.run(until=0.2)
    assert not hasattr(service, '_force_deadlock_pod_id')
    assert pod1.thread_pool.count == 0
    print(f"✅ thread_exhaustion reverted, tracking cleaned up")

    print(f"\n✅ TEST PASSED: Multiple faults track independently")
    return True


def main():
    """Run all pod tracking tests."""
    print("\n" + "="*60)
    print("POD ID TRACKING ROBUSTNESS TEST SUITE")
    print("="*60)

    results = []

    # Run all tests
    try:
        results.append(("Noisy Neighbor Pod Tracking", test_noisy_neighbor_pod_tracking()))
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        results.append(("Noisy Neighbor Pod Tracking", False))

    try:
        results.append(("Thread Exhaustion Pod Tracking", test_thread_exhaustion_pod_tracking()))
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        results.append(("Thread Exhaustion Pod Tracking", False))

    try:
        results.append(("Concurrent Faults", test_concurrent_faults()))
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        results.append(("Concurrent Faults", False))

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {name}: {status}")

    total_passed = sum(1 for _, passed in results if passed)
    total_tests = len(results)

    print(f"\nTotal: {total_passed}/{total_tests} tests passed")

    if total_passed == total_tests:
        print("\n🎉 All pod tracking tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total_tests - total_passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
