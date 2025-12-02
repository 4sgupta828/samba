#!/usr/bin/env python3
"""
Test script to verify timeout and queue clearing fixes.

Tests:
1. Server-side request timeout
2. Queue clearing on pod restart
3. Active request interruption on crash
"""
import simpy
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from components.pod import Pod
from components.service import Service
from core.simulation_config import get_simulation_config


def test_queue_clearing_on_restart():
    """Test that queues are cleared when pod restarts."""
    print("\n=== Test 1: Queue Clearing on Pod Restart ===")
    env = simpy.Environment()

    # Create a service and pod
    service = Service(env, "test_service", "TestService", supported_request_types=["GET"])
    pod = Pod(env, "test_pod", parent_service=service)
    service.pods.append(pod)

    # Initialize metrics
    pod._initialize_request_metrics()

    # Start pod
    env.process(pod.run())
    env.run(until=5)  # Let pod start

    print(f"Pod state: {pod.state.operational}")
    print(f"Thread pool queue size: {len(pod.thread_pool.queue)}")
    print(f"DB connection pool queue size: {len(pod.db_connection_pool.queue)}")

    # Artificially fill the thread pool (simulate heavy load)
    # Exhaust all threads by creating dummy processes that hold threads
    def hold_thread(thread_pool, duration):
        """Hold a thread for a specified duration."""
        with thread_pool.request() as req:
            yield req
            yield env.timeout(duration)

    # Exhaust all threads
    for i in range(pod.thread_pool_size):
        env.process(hold_thread(pod.thread_pool, 100))

    # Try to add more requests (these will queue)
    def slow_request(pod_obj, request_id):
        """A request that takes a long time."""
        try:
            yield from pod_obj.handle_request("GET")
            print(f"Request {request_id} completed")
        except Exception as e:
            print(f"Request {request_id} failed: {e}")

    # Queue up 20 requests
    for i in range(20):
        env.process(slow_request(pod, i))

    # Let some requests queue up
    env.run(until=6)

    queued_before = len(pod.thread_pool.queue)
    print(f"\nBefore crash: {queued_before} requests queued in thread pool")

    # Simulate OOM crash
    if hasattr(pod, 'running_process') and pod.running_process:
        pod.running_process.interrupt("OOMKilled")

    # Let pod restart
    env.run(until=30)

    queued_after = len(pod.thread_pool.queue)
    print(f"After restart: {queued_after} requests queued in thread pool")
    print(f"Pod state: {pod.state.operational}")

    if queued_after == 0:
        print("✅ PASS: Queue was cleared on restart")
        return True
    else:
        print(f"❌ FAIL: Queue still has {queued_after} requests")
        return False


def test_server_timeout():
    """Test that server-side timeout works."""
    print("\n=== Test 2: Server-Side Request Timeout ===")
    env = simpy.Environment()

    # Create a service and pod with custom timeout
    service = Service(env, "test_service", "TestService", supported_request_types=["GET"])

    # Create a very slow custom pipeline
    def slow_processing():
        """A pipeline step that takes 35 seconds."""
        yield env.timeout(35.0)  # 35 seconds - exceeds 30s timeout

    service.processing_pipeline = []  # Empty pipeline so we can inject custom logic

    pod = Pod(env, "test_pod", parent_service=service)
    service.pods.append(pod)

    # Initialize metrics
    pod._initialize_request_metrics()

    # Monkey-patch the pipeline execution to inject very slow processing
    original_execute = pod._execute_processing_pipeline
    def slow_execute(request_type, span):
        yield env.timeout(35.0)  # 35 seconds
    pod._execute_processing_pipeline = slow_execute

    # Start pod
    env.process(pod.run())
    env.run(until=5)  # Let pod start

    print(f"Pod state: {pod.state.operational}")
    print(f"Server timeout configured: {get_simulation_config().compute.timeouts.server_request_seconds}s")

    # Disable dynamics errors to test timeout cleanly
    pod.dynamics.config.error_base = 0.0

    request_completed = [False]
    request_error = [None]

    def timeout_test_request():
        """Test request that should timeout."""
        try:
            yield from pod.handle_request("GET")
            request_completed[0] = True
            print("Request completed (should not happen)")
        except Exception as e:
            request_error[0] = str(e)
            print(f"Request failed with error: {e}")

    env.process(timeout_test_request())

    # Run for 40 seconds (enough time for 30s timeout + processing)
    env.run(until=50)

    # Restore original method
    pod._execute_processing_pipeline = original_execute

    if request_error[0] and "timed out" in request_error[0].lower():
        print("✅ PASS: Request timed out on server side")
        return True
    else:
        print(f"❌ FAIL: Request did not timeout properly. Error: {request_error[0]}")
        return False


def test_active_request_interruption():
    """Test that active requests are interrupted on crash."""
    print("\n=== Test 3: Active Request Interruption on Crash ===")
    env = simpy.Environment()

    # Create a service and pod
    service = Service(env, "test_service", "TestService", supported_request_types=["GET"])
    service.processing_pipeline = []  # Empty pipeline

    pod = Pod(env, "test_pod", parent_service=service)
    service.pods.append(pod)

    # Initialize metrics
    pod._initialize_request_metrics()

    # Monkey-patch to inject very slow processing (25 seconds)
    original_execute = pod._execute_processing_pipeline
    def slow_execute(request_type, span):
        yield env.timeout(25.0)  # 25 seconds
    pod._execute_processing_pipeline = slow_execute

    # Disable dynamics errors
    pod.dynamics.config.error_base = 0.0

    # Start pod
    env.process(pod.run())
    env.run(until=5)  # Let pod start

    print(f"Pod state: {pod.state.operational}")
    print(f"Active requests: {len(pod.active_request_processes)}")

    # Start a long-running request
    request_interrupted = [False]
    request_error_msg = [None]

    def long_request():
        """A request that takes a long time."""
        try:
            yield from pod.handle_request("GET")
            print("Request completed (should not happen)")
        except Exception as e:
            request_error_msg[0] = str(e)
            if "crashed" in str(e).lower():
                request_interrupted[0] = True
            print(f"Request failed with error: {e}")

    env.process(long_request())

    # Let request start processing (but not complete - it needs 25s, we only give it 2s)
    env.run(until=7)

    active_before = len(pod.active_request_processes)
    print(f"\nActive requests before crash: {active_before}")

    # Simulate crash
    if hasattr(pod, 'running_process') and pod.running_process:
        pod.running_process.interrupt("OOMKilled")

    # Let pod restart
    env.run(until=30)

    active_after = len(pod.active_request_processes)
    print(f"Active requests after crash: {active_after}")
    print(f"Pod state: {pod.state.operational}")
    print(f"Request error message: {request_error_msg[0]}")

    # Restore
    pod._execute_processing_pipeline = original_execute

    if request_interrupted[0] and active_after == 0:
        print("✅ PASS: Active requests were interrupted on crash")
        return True
    else:
        print(f"❌ FAIL: Active requests not properly interrupted. Interrupted: {request_interrupted[0]}, Active after: {active_after}")
        return False


if __name__ == "__main__":
    print("Testing Timeout and Queue Clearing Fixes")
    print("=" * 60)

    results = []

    try:
        results.append(test_queue_clearing_on_restart())
    except Exception as e:
        print(f"❌ Test 1 crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    try:
        results.append(test_server_timeout())
    except Exception as e:
        print(f"❌ Test 2 crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    try:
        results.append(test_active_request_interruption())
    except Exception as e:
        print(f"❌ Test 3 crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    print("\n" + "=" * 60)
    print(f"Results: {sum(results)}/{len(results)} tests passed")

    if all(results):
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        sys.exit(1)
