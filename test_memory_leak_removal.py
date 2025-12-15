#!/usr/bin/env python3
"""Test script to verify memory_leak fault removal fix."""

import sys
sys.path.insert(0, '/Users/sgupta/samba')

from src.components.pod import Pod
from src.components.service import Service
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
from src.failures.modes import start_memory_leak, stop_memory_leak
import simpy


def test_memory_leak_removal():
    """Test that memory_leak removal works correctly on pods."""

    # Create environment and service with pods
    env = simpy.Environment()

    # Create a service with 2 pods
    service = Service(env, "test_service", "TestService", desired_replicas=2)

    # Create pods manually
    for i in range(2):
        pod = Pod(env, f"pod_test_service_{i}", service)
        service.pods.append(pod)

    # Setup dynamics for each pod
    for pod in service.pods:
        pod.dynamics = MetricsDynamicsEngine(
            config=DynamicsConfig(
                memory_base=200.0,
                memory_per_request_mb=5.0
            )
        )
        pod.dynamics.concurrent_requests = 1.0  # Simulate some load

    print("=" * 60)
    print("TEST: Memory Leak Injection and Removal")
    print("=" * 60)

    # Check initial state
    print("\n1. Initial state:")
    for i, pod in enumerate(service.pods):
        mem_per_req = pod.dynamics.config.memory_per_request_mb
        print(f"   Pod {i}: memory_per_request_mb = {mem_per_req:.2f} MB")

    # Inject memory leak
    print("\n2. Injecting memory leak (+40 MB/request)...")
    params = {"leak_mb_per_request": 40.0}

    for pod in service.pods:
        start_memory_leak(pod, params)

    print("   After injection:")
    for i, pod in enumerate(service.pods):
        mem_per_req = pod.dynamics.config.memory_per_request_mb
        print(f"   Pod {i}: memory_per_request_mb = {mem_per_req:.2f} MB")

    # Verify injection worked
    for pod in service.pods:
        assert pod.dynamics.config.memory_per_request_mb == 45.0, \
            f"Expected 45.0, got {pod.dynamics.config.memory_per_request_mb}"
    print("   ✓ Injection successful")

    # Remove memory leak - TEST THE FIX
    print("\n3. Removing memory leak...")

    # OLD CODE (buggy): This would be called on the service
    # stop_memory_leak(service, params)  # This would silently fail!

    # NEW CODE (fixed): Apply to each pod
    for pod in service.pods:
        stop_memory_leak(pod, params)

    print("   After removal:")
    for i, pod in enumerate(service.pods):
        mem_per_req = pod.dynamics.config.memory_per_request_mb
        mem_current = pod.dynamics.memory_percent
        print(f"   Pod {i}: memory_per_request_mb = {mem_per_req:.2f} MB, current_memory = {mem_current:.0f} MB")

    # Verify removal worked
    for pod in service.pods:
        # Should be back to ~5.0 MB (original value)
        assert pod.dynamics.config.memory_per_request_mb == 5.0, \
            f"Expected 5.0, got {pod.dynamics.config.memory_per_request_mb}"
    print("   ✓ Removal successful")

    print("\n" + "=" * 60)
    print("TEST PASSED: Memory leak removal is working correctly!")
    print("=" * 60)


if __name__ == "__main__":
    test_memory_leak_removal()
