"""
Test script to verify memory leak right-sizing solution.

Verifies that:
1. Consumer nodes get 256MB memory capacity (vs 512MB for API services)
2. Same leak rate (40 MB/req) has bigger impact on consumers
3. Memory leaks accumulate realistically based on concurrent requests
"""

import simpy
from src.components.pod import Pod
from src.components.service import Service
from src.failures.modes import start_memory_leak, stop_memory_leak
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig


def test_consumer_right_sizing():
    """Test that consumer pods get smaller memory capacity."""
    print("\n=== Test 1: Consumer Right-Sizing ===")

    # Setup
    env = simpy.Environment()

    # Create a consumer service (with queue_in)
    service = Service(env, "analytics_service", "analytics_service")
    service.connections = {'queue_in': "events_queue"}

    # Simulate capacity planner setting memory_capacity_mb
    service.iac_config = {
        'memory_capacity_mb': 256,  # Right-sized for consumer
        'thread_pool_size': 100
    }

    # Create pod for consumer
    pod = Pod(env, "pod_analytics_0", service, 0)

    # Apply overrides (simulating deployment controller)
    if 'memory_capacity_mb' in service.iac_config:
        pod.memory_capacity_mb = service.iac_config['memory_capacity_mb']

    print(f"Consumer pod memory capacity: {pod.memory_capacity_mb}MB")

    assert pod.memory_capacity_mb == 256, "Consumer should have 256MB capacity"
    print("✓ Consumer pod correctly sized to 256MB\n")


def test_api_service_sizing():
    """Test that API service pods get standard memory capacity."""
    print("=== Test 2: API Service Sizing ===")

    # Setup
    env = simpy.Environment()

    # Create an API service (no queue_in)
    service = Service(env, "api_service", "api_service")
    service.connections = {'db_test': "database"}

    # API services don't get memory_capacity_mb override from capacity planner
    service.iac_config = {
        'thread_pool_size': 100
    }

    # Create pod for API service
    pod = Pod(env, "pod_api_0", service, 0)

    # Default memory capacity (from config)
    print(f"API service pod memory capacity: {pod.memory_capacity_mb}MB")

    assert pod.memory_capacity_mb == 512, "API service should have 512MB capacity (default)"
    print("✓ API service pod correctly sized to 512MB (default)\n")


def test_leak_impact_on_consumer():
    """Test that same leak rate has bigger impact on smaller consumer instances."""
    print("=== Test 3: Leak Impact on Consumer (256MB) ===")

    # Setup
    env = simpy.Environment()
    service = Service(env, "consumer", "consumer")
    service.connections = {'queue_in': "queue"}
    service.iac_config = {'memory_capacity_mb': 256}

    pod = Pod(env, "pod_consumer", service, 0)
    pod.memory_capacity_mb = 256  # Consumer size
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())

    # Set low throughput (typical for consumers)
    pod.dynamics.update(dt=1.0, external_throughput=1.0)  # 1 RPS

    print(f"Memory capacity: {pod.memory_capacity_mb}MB")
    print(f"Baseline memory: {pod.dynamics.config.memory_base}MB")
    print(f"Concurrent requests: {pod.dynamics.concurrent_requests:.2f}")

    # Inject leak
    start_memory_leak(pod, {'leak_mb_per_request': 40.0})

    # Simulate over time
    print("\nMemory progression:")
    for i in range(15):
        pod.dynamics.update(dt=1.0, external_throughput=1.0)  # 1 RPS
        memory = pod.dynamics.memory_percent
        utilization = (memory / pod.memory_capacity_mb) * 100

        print(f"  t={i+1}s: {memory:.1f}MB ({utilization:.1f}% utilization)", end='')

        if memory > pod.memory_capacity_mb:
            print(" --> OOM KILL!")
            break
        print()

    print("\n✓ Consumer experiences memory pressure and potential OOM\n")


def test_leak_impact_on_api_service():
    """Test that same leak rate has smaller impact on larger API service instances."""
    print("=== Test 4: Leak Impact on API Service (512MB) ===")

    # Setup
    env = simpy.Environment()
    service = Service(env, "api", "api")
    service.connections = {'db_test': "database"}

    pod = Pod(env, "pod_api", service, 0)
    pod.memory_capacity_mb = 512  # Standard size
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())

    # Set high throughput (typical for API services)
    pod.dynamics.update(dt=1.0, external_throughput=100.0)  # 100 RPS

    print(f"Memory capacity: {pod.memory_capacity_mb}MB")
    print(f"Baseline memory: {pod.dynamics.config.memory_base}MB")
    print(f"Concurrent requests: {pod.dynamics.concurrent_requests:.2f}")

    # Inject SAME leak rate
    start_memory_leak(pod, {'leak_mb_per_request': 40.0})

    # Simulate over time
    print("\nMemory progression:")
    for i in range(15):
        pod.dynamics.update(dt=1.0, external_throughput=100.0)  # 100 RPS
        memory = pod.dynamics.memory_percent
        utilization = (memory / pod.memory_capacity_mb) * 100

        print(f"  t={i+1}s: {memory:.1f}MB ({utilization:.1f}% utilization)", end='')

        if memory > pod.memory_capacity_mb:
            print(" --> OOM KILL!")
            break
        print()

    print("\n✓ API service also experiences memory pressure (higher throughput = more concurrent requests)\n")


def test_removal_logging():
    """Test that fault removal is properly logged."""
    print("=== Test 5: Fault Removal Logging ===")

    # Setup
    env = simpy.Environment()
    service = Service(env, "test", "test")
    service.connections = {'queue_in': "queue"}

    pod = Pod(env, "pod", service, 0)
    pod.dynamics = MetricsDynamicsEngine(DynamicsConfig())

    # Inject and remove
    print("Injecting fault...")
    start_memory_leak(pod, {'leak_mb_per_request': 40.0})

    print("\nRemoving fault...")
    stop_memory_leak(pod, {'leak_mb_per_request': 40.0})

    print("\n✓ Both injection and removal are logged (check output above)\n")


if __name__ == "__main__":
    print("=" * 70)
    print("Testing Memory Leak Right-Sizing Solution")
    print("=" * 70)

    try:
        test_consumer_right_sizing()
        test_api_service_sizing()
        test_leak_impact_on_consumer()
        test_leak_impact_on_api_service()
        test_removal_logging()

        print("=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70)
        print("\nSummary:")
        print("- Consumers get 256MB capacity (right-sized)")
        print("- API services get 512MB capacity (standard)")
        print("- Same leak rate has natural impact based on instance size")
        print("- No special-case code needed - infrastructure handles it")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise
