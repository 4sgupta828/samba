#!/usr/bin/env python3
"""
Test what happens to downstream requests when the calling pod crashes.

Scenario:
1. Pod A makes a request to Pod B (downstream service)
2. Pod B is processing the request (takes 20 seconds)
3. Pod A crashes after 5 seconds
4. Question: What happens to the request in Pod B?
"""
import simpy
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from components.pod import Pod
from components.service import Service


def test_downstream_orphan_requests():
    """Test what happens to downstream requests when calling pod crashes."""
    print("\n=== Test: Downstream Orphan Requests on Caller Crash ===")
    env = simpy.Environment()

    # Create two services: ServiceA calls ServiceB
    service_a = Service(env, "service_a", "ServiceA", supported_request_types=["GET"])
    service_b = Service(env, "service_b", "ServiceB", supported_request_types=["GET"])

    # Create pods
    pod_a = Pod(env, "pod_a", parent_service=service_a)
    pod_b = Pod(env, "pod_b", parent_service=service_b)

    service_a.pods.append(pod_a)
    service_b.pods.append(pod_b)

    # Connect ServiceA to ServiceB
    service_a.connections['dep_service_b'] = service_b

    # Initialize metrics
    pod_a._initialize_request_metrics()
    pod_b._initialize_request_metrics()

    # Make ServiceB processing very slow (20 seconds)
    original_execute_b = pod_b._execute_processing_pipeline
    def slow_execute_b(request_type, span):
        print(f"[{env.now:.1f}s] Pod B: Started processing request (will take 20s)")
        yield env.timeout(20.0)  # 20 seconds
        print(f"[{env.now:.1f}s] Pod B: Finished processing request")
    pod_b._execute_processing_pipeline = slow_execute_b

    # Make ServiceA call ServiceB
    service_a.processing_pipeline = [{"type": "service_calls"}]

    # Disable errors
    pod_a.dynamics.config.error_base = 0.0
    pod_b.dynamics.config.error_base = 0.0

    # Start both pods
    env.process(pod_a.run())
    env.process(pod_b.run())
    env.run(until=5)  # Let pods start

    print(f"\n[{env.now:.1f}s] Both pods running")
    print(f"Pod A state: {pod_a.state.operational}")
    print(f"Pod B state: {pod_b.state.operational}")

    # Track request state
    request_state = {
        "pod_a_error": None,
        "pod_b_completed": False,
        "pod_b_interrupted": False
    }

    def calling_request():
        """Request in Pod A that calls Pod B."""
        try:
            print(f"[{env.now:.1f}s] Pod A: Starting request that calls Pod B")
            yield from pod_a.handle_request("GET")
            print(f"[{env.now:.1f}s] Pod A: Request completed (should not happen)")
        except Exception as e:
            request_state["pod_a_error"] = str(e)
            print(f"[{env.now:.1f}s] Pod A: Request failed: {e}")

    # Monkey-patch Pod B to track if it gets interrupted
    original_handle_b = pod_b.handle_request
    def tracked_handle_b(request_type, should_trace=False, parent_span_context=None):
        try:
            yield from original_handle_b(request_type, should_trace, parent_span_context)
            request_state["pod_b_completed"] = True
        except simpy.Interrupt as interrupt:
            request_state["pod_b_interrupted"] = True
            print(f"[{env.now:.1f}s] Pod B: Got interrupted! Cause: {interrupt.cause}")
            raise
        except Exception as e:
            print(f"[{env.now:.1f}s] Pod B: Got exception: {e}")
            raise
    pod_b.handle_request = tracked_handle_b

    env.process(calling_request())

    # Let request start and Pod B start processing
    env.run(until=10)

    print(f"\n[{env.now:.1f}s] Current state:")
    print(f"  Pod A active requests: {len(pod_a.active_request_processes)}")
    print(f"  Pod B active requests: {len(pod_b.active_request_processes)}")
    print(f"  Pod A had error: {request_state['pod_a_error'] is not None}")

    # Now crash Pod A (the caller)
    print(f"\n[{env.now:.1f}s] >>> CRASHING POD A (the caller) <<<")
    if hasattr(pod_a, 'running_process') and pod_a.running_process:
        pod_a.running_process.interrupt("OOMKilled")

    # Let simulation continue
    env.run(until=35)

    print(f"\n[{env.now:.1f}s] Final state:")
    print(f"  Pod A state: {pod_a.state.operational}")
    print(f"  Pod B state: {pod_b.state.operational}")
    print(f"  Pod A error: {request_state['pod_a_error']}")
    print(f"  Pod B completed: {request_state['pod_b_completed']}")
    print(f"  Pod B interrupted: {request_state['pod_b_interrupted']}")
    print(f"  Pod B active requests: {len(pod_b.active_request_processes)}")

    # Restore
    pod_b._execute_processing_pipeline = original_execute_b

    print("\n=== Analysis ===")
    if request_state["pod_b_completed"] and not request_state["pod_b_interrupted"]:
        print("❌ ISSUE: Pod B continued processing even though caller (Pod A) crashed!")
        print("   This is an 'orphan request' - Pod B does wasted work that will never be used.")
        print("   In real systems, the TCP connection would be closed and Pod B would detect it.")
        return False
    elif request_state["pod_b_interrupted"]:
        print("✅ GOOD: Pod B was interrupted when caller crashed")
        return True
    else:
        print("⚠️  UNCLEAR: Pod B did not complete or get interrupted")
        return False


if __name__ == "__main__":
    test_downstream_orphan_requests()
