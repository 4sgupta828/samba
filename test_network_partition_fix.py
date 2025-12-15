#!/usr/bin/env python3
"""
Test to verify network partition fault correctly fails requests.

This test validates the bug fix where services were marking requests as successful
despite database failures due to network partition.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simpy
from src.components.service import Service
from src.components.pod import Pod
from src.components.database import SqlDatabase
from src.components.network import NetworkLink
from src.telemetry.metrics_manager import MetricsManager
from src.simulation import Simulation


def test_network_partition_fails_requests():
    """
    Test that network partition between service and database causes requests to fail.

    Expected behavior:
    - DB dependency requests should have status="error"
    - Service requests should have status="error" (NOT success!)
    - Processing should fail, not continue silently
    """
    print("\n" + "="*80)
    print("Testing Network Partition Fault - Request Failure Propagation")
    print("="*80 + "\n")

    # Setup simulation
    env = simpy.Environment()
    metrics_mgr = MetricsManager()

    # Create global network link (required for partition checks)
    network = NetworkLink(env, "global_network")
    Simulation._global_network = network
    env.process(network.run())

    # Create components
    db = SqlDatabase(env, "test_db")
    service = Service(env, "test_service", service_name="test_service")
    pod = Pod(env, "test_pod_0", parent_service=service)

    # Wire up connections
    service.connections['db_test_db'] = db
    service.processing_pipeline = [
        {"type": "db_query", "probability": 1.0}
    ]

    # Initialize pod metrics (normally done during topology setup)
    service._pods = [pod]
    pod._initialize_request_metrics()

    # Start components
    env.process(db.run())
    env.process(pod.run())

    # Wait for components to start
    env.run(until=2)

    print("✓ Components started successfully\n")

    # Test 1: Normal operation (should succeed)
    print("Test 1: Normal operation (no faults)")
    print("-" * 40)

    request_failed = False
    def test_normal_request():
        nonlocal request_failed
        try:
            yield env.process(pod.handle_request("GET"))
            print("✓ Request completed successfully")
        except Exception as e:
            request_failed = True
            print(f"✗ Request failed: {e}")

    env.process(test_normal_request())
    env.run(until=5)

    if request_failed:
        print("FAIL: Request should succeed under normal conditions\n")
        return False

    # Test 2: Network partition (should fail)
    print("\nTest 2: Network partition between service and database")
    print("-" * 40)

    # Inject network partition (using the service ID for partition matching)
    network.partition_rules.add(("test_service", "test_db"))
    network.partition_rules.add(("test_db", "test_service"))
    print("✓ Network partition injected: test_service <-> test_db\n")

    request_failed = False
    error_message = None

    def test_partition_request():
        nonlocal request_failed, error_message
        try:
            yield env.process(pod.handle_request("GET"))
            print("✗ Request completed successfully (UNEXPECTED!)")
            print("   This indicates the bug is NOT fixed - requests should FAIL during network partition")
        except Exception as e:
            request_failed = True
            error_message = str(e)
            print(f"✓ Request failed as expected: {type(e).__name__}")

    env.process(test_partition_request())
    env.run(until=10)

    print("\nTest Results:")
    print("=" * 80)

    if not request_failed:
        print("FAIL ✗")
        print("  - Requests are still succeeding despite network partition")
        print("  - The bug is NOT fixed")
        print("  - Expected: Request should fail when DB is unreachable")
        print("  - Actual: Request succeeded (marked as success)\n")
        return False
    else:
        print("PASS ✓")
        print("  - Request correctly failed during network partition")
        print("  - Error propagated properly to caller")
        print("  - The bug is FIXED\n")
        return True


if __name__ == "__main__":
    success = test_network_partition_fails_requests()

    print("="*80)
    if success:
        print("ALL TESTS PASSED ✓")
        print("Network partition now correctly fails requests as expected")
    else:
        print("TESTS FAILED ✗")
        print("Network partition bug is still present")
    print("="*80 + "\n")

    sys.exit(0 if success else 1)
