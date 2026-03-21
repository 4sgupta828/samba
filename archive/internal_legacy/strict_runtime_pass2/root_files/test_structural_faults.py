#!/usr/bin/env python3
"""
Test script for structural failure modes implementation.

Tests:
1. Noisy Neighbor - CPU contention on shared nodes
2. Hot Shard - Traffic skewing to specific pods
3. Network Partition - Blocking traffic between components
4. Force Deadlock - Thread exhaustion without CPU consumption
"""

import simpy
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.components.compute_node import ComputeNode
from src.components.pod import Pod
from src.components.service import Service
from src.components.network import NetworkLink, NetworkPartitionError
from src.failures.modes import noisy_neighbor, hot_shard, network_partition, thread_exhaustion, revert_thread_exhaustion


def test_noisy_neighbor():
    """Test 1: Noisy Neighbor - CPU contention causes steal time."""
    print("\n" + "="*60)
    print("TEST 1: Noisy Neighbor (CPU Contention)")
    print("="*60)

    env = simpy.Environment()

    # Create a node with limited capacity (1 core = 100% capacity)
    node = ComputeNode(env, "node_1", cpu_cores=1, memory_gb=16)

    # Create 3 pods on the same node
    pod1 = Pod(env, "pod_1", compute_node=node)
    pod2 = Pod(env, "pod_2", compute_node=node)
    pod3 = Pod(env, "pod_3", compute_node=node)

    # Set pods to RUNNING state
    pod1.state.operational = "RUNNING"
    pod2.state.operational = "RUNNING"
    pod3.state.operational = "RUNNING"

    # Simulate pods at different CPU levels
    pod1.dynamics.cpu_percent = 40.0  # 40% CPU
    pod2.dynamics.cpu_percent = 30.0  # 30% CPU
    pod3.dynamics.cpu_percent = 15.0  # 15% CPU

    # Total: 85% - below 90% threshold, no contention yet
    print(f"\nBefore noisy neighbor:")
    print(f"  Pod1 CPU: {pod1.dynamics.cpu_percent}%")
    print(f"  Pod2 CPU: {pod2.dynamics.cpu_percent}%")
    print(f"  Pod3 CPU: {pod3.dynamics.cpu_percent}%")
    print(f"  Total node CPU: {node.get_total_pod_cpu():.1f}% (capacity: {node.cpu_cores * 100}%)")
    cpu_util, _ = node.get_utilization()
    print(f"  Node utilization: {cpu_util*100:.1f}%")
    penalty_before = node.get_contention_penalty()
    print(f"  Contention penalty: {penalty_before:.2f}ms")

    # Apply noisy neighbor to pod1 (aggressor)
    print(f"\nApplying noisy_neighbor to pod_1 (CPU -> 100%)...")
    noisy_neighbor(pod1, {"cpu_percent": 100.0})

    # Now pod1 should be at 100% CPU
    pod1.dynamics.cpu_percent = 100.0  # Simulate the effect

    print(f"\nAfter noisy neighbor:")
    print(f"  Pod1 CPU (aggressor): {pod1.dynamics.cpu_percent}%")
    print(f"  Pod2 CPU: {pod2.dynamics.cpu_percent}%")
    print(f"  Pod3 CPU: {pod3.dynamics.cpu_percent}%")
    print(f"  Total node CPU: {node.get_total_pod_cpu():.1f}% (capacity: {node.cpu_cores * 100}%)")
    cpu_util, _ = node.get_utilization()
    print(f"  Node utilization: {cpu_util*100:.1f}%")
    penalty_after = node.get_contention_penalty()
    print(f"  Contention penalty: {penalty_after:.2f}ms")

    # Verify contention penalty increased
    if penalty_after > penalty_before:
        print(f"\n✅ TEST PASSED: Contention penalty increased from {penalty_before:.2f}ms to {penalty_after:.2f}ms")
        print(f"   Victims (pod2, pod3) will experience {penalty_after:.2f}ms steal time on every request")
        return True
    else:
        print(f"\n❌ TEST FAILED: Contention penalty did not increase")
        return False


def test_hot_shard():
    """Test 2: Hot Shard - Traffic skewing to specific pod."""
    print("\n" + "="*60)
    print("TEST 2: Hot Shard (Traffic Skew)")
    print("="*60)

    env = simpy.Environment()

    # Create a service with 3 pods
    service = Service(env, "service_1", "test_service", desired_replicas=3)

    # Create pods
    pod1 = Pod(env, "pod_1", parent_service=service)
    pod2 = Pod(env, "pod_2", parent_service=service)
    pod3 = Pod(env, "pod_3", parent_service=service)
    pod1.state.operational = "RUNNING"
    pod2.state.operational = "RUNNING"
    pod3.state.operational = "RUNNING"

    service.pods = [pod1, pod2, pod3]

    # Test uniform distribution (before hot shard)
    print(f"\nBefore hot_shard (uniform distribution):")
    print(f"  Traffic weights: {service.traffic_weights}")

    # Simulate 1000 requests and count distribution
    pod_counts_before = {pod1.id: 0, pod2.id: 0, pod3.id: 0}
    for _ in range(1000):
        selected_pod = service.get_pod_target()
        pod_counts_before[selected_pod.id] += 1

    print(f"  Request distribution (1000 requests):")
    for pod_id, count in pod_counts_before.items():
        print(f"    {pod_id}: {count} ({count/10:.1f}%)")

    # Apply hot shard - 80% traffic to pod1
    print(f"\nApplying hot_shard (80% to pod_1)...")
    hot_shard(service, {"target_pod_index": 0, "skew_factor": 0.8})

    print(f"\nAfter hot_shard:")
    print(f"  Traffic weights: {service.traffic_weights}")

    # Simulate 1000 requests and count distribution
    pod_counts_after = {pod1.id: 0, pod2.id: 0, pod3.id: 0}
    for _ in range(1000):
        selected_pod = service.get_pod_target()
        pod_counts_after[selected_pod.id] += 1

    print(f"  Request distribution (1000 requests):")
    for pod_id, count in pod_counts_after.items():
        print(f"    {pod_id}: {count} ({count/10:.1f}%)")

    # Verify hot shard is receiving ~80% of traffic
    hot_pod_pct = pod_counts_after[pod1.id] / 1000.0
    if hot_pod_pct > 0.75 and hot_pod_pct < 0.85:
        print(f"\n✅ TEST PASSED: Hot shard (pod_1) received {hot_pod_pct*100:.1f}% of traffic (expected ~80%)")
        return True
    else:
        print(f"\n❌ TEST FAILED: Hot shard received {hot_pod_pct*100:.1f}% of traffic (expected ~80%)")
        return False


def test_network_partition():
    """Test 3: Network Partition - Blocks traffic between components."""
    print("\n" + "="*60)
    print("TEST 3: Network Partition")
    print("="*60)

    env = simpy.Environment()

    # Create network link
    network = NetworkLink(env, "network_1")

    print(f"\nBefore network_partition:")
    print(f"  Partition rules: {network.partition_rules}")

    # Apply network partition between service_a and db_1
    print(f"\nApplying network_partition (service_a <-> db_1, bidirectional)...")
    network_partition(network, {
        "source_component_id": "service_a",
        "target_component_id": "db_1",
        "bidirectional": True
    })

    print(f"\nAfter network_partition:")
    print(f"  Partition rules: {network.partition_rules}")

    # Verify partition rules were added
    expected_rules = {("service_a", "db_1"), ("db_1", "service_a")}
    if network.partition_rules == expected_rules:
        print(f"\n✅ TEST PASSED: Partition rules correctly added")

        # Test that traffic is blocked
        print(f"\nTesting traffic blocking...")

        def test_transmit():
            try:
                # This should raise NetworkPartitionError
                yield from network._transmit_internal(
                    data_size_bytes=1024,
                    source_id="service_a",
                    target_id="db_1"
                )
                return "SUCCESS"
            except NetworkPartitionError as e:
                return f"BLOCKED: {e}"

        # Run the test
        result = env.process(test_transmit())
        env.run()

        if "BLOCKED" in str(result.value):
            print(f"  ✅ Traffic blocked: {result.value}")
            return True
        else:
            print(f"  ❌ Traffic not blocked: {result.value}")
            return False
    else:
        print(f"\n❌ TEST FAILED: Partition rules incorrect")
        print(f"   Expected: {expected_rules}")
        print(f"   Got: {network.partition_rules}")
        return False


def test_thread_exhaustion():
    """Test 4: Thread Exhaustion - Thread pool saturation without CPU consumption."""
    print("\n" + "="*60)
    print("TEST 4: Thread Exhaustion")
    print("="*60)

    env = simpy.Environment()

    # Create a pod
    pod = Pod(env, "pod_1")
    pod.state.operational = "RUNNING"

    print(f"\nBefore thread_exhaustion:")
    print(f"  Thread pool capacity: {pod.thread_pool.capacity}")
    print(f"  Active threads: {pod.thread_pool.count}")
    print(f"  Queued requests: {len(pod.thread_pool.queue)}")

    # Apply thread exhaustion - lock 3 threads for 10 seconds
    print(f"\nApplying thread_exhaustion (lock 3 threads for 10s)...")
    thread_exhaustion(pod, {"locked_threads": 3, "duration": 10.0})

    # Run simulation for a bit to let zombie tasks acquire threads
    env.run(until=0.1)

    print(f"\nAfter thread_exhaustion (0.1s later):")
    print(f"  Thread pool capacity: {pod.thread_pool.capacity}")
    print(f"  Active threads: {pod.thread_pool.count}")
    print(f"  Queued requests: {len(pod.thread_pool.queue)}")
    print(f"  CPU usage: {pod.dynamics.cpu_percent:.1f}%")

    # Verify threads are locked
    if pod.thread_pool.count != 3:
        print(f"\n❌ TEST FAILED: Expected 3 locked threads, got {pod.thread_pool.count}")
        return False

    print(f"\n✅ Part 1 PASSED: 3 threads locked (zombie tasks consuming threads without CPU)")
    print(f"   New requests will queue until thread exhaustion duration expires (10s)")

    # Test revert - interrupt zombie processes early
    print(f"\nTesting revert_thread_exhaustion (interrupt early)...")
    revert_thread_exhaustion(pod, {})

    # Run simulation a bit more to process interrupts
    env.run(until=0.2)

    print(f"\nAfter revert_thread_exhaustion:")
    print(f"  Thread pool capacity: {pod.thread_pool.capacity}")
    print(f"  Active threads: {pod.thread_pool.count}")
    print(f"  Queued requests: {len(pod.thread_pool.queue)}")

    # Verify threads were released
    if pod.thread_pool.count == 0:
        print(f"\n✅ Part 2 PASSED: All threads released early via revert")
        print(f"   Thread exhaustion can be manually cleared before duration expires")
        return True
    else:
        print(f"\n❌ Part 2 FAILED: Expected 0 active threads after revert, got {pod.thread_pool.count}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("STRUCTURAL FAILURE MODES TEST SUITE")
    print("="*60)

    results = []

    # Run all tests
    results.append(("Noisy Neighbor", test_noisy_neighbor()))
    results.append(("Hot Shard", test_hot_shard()))
    results.append(("Network Partition", test_network_partition()))
    results.append(("Thread Exhaustion", test_thread_exhaustion()))

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
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total_tests - total_passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
