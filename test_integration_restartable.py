"""
Test integration of RestartableComponent pattern with the full simulation.

This test verifies that DeploymentController creates ComponentLifecycleManagers
and that Services properly track pod instances through restarts.
"""

import simpy
from src.components.service import Service
from src.components.deployment_controller import DeploymentController
from src.components.compute_node import ComputeNode
from src.core.simulation_config import get_simulation_config


def test_deployment_controller_integration():
    """
    Test that DeploymentController creates and manages pod lifecycle managers.
    """
    print("\n" + "="*70)
    print("TEST: DeploymentController Integration with RestartableComponent")
    print("="*70 + "\n")

    env = simpy.Environment()

    # Create a service
    service = Service(
        env=env,
        component_id="test_service",
        service_name="test_service",
        desired_replicas=2
    )

    # Create compute nodes
    node1 = ComputeNode(env, "node1", cpu_cores=4, memory_gb=8)
    node2 = ComputeNode(env, "node2", cpu_cores=4, memory_gb=8)

    # Start nodes (they need to be running to accept pods)
    env.process(node1.run())
    env.process(node2.run())

    # Create deployment controller
    controller = DeploymentController(env)
    controller.register_service(service)
    controller.register_node(node1)
    controller.register_node(node2)

    # Start controller
    env.process(controller.run())

    # Run simulation for a bit
    print(f"[t=0.0s] Starting simulation...")
    env.run(until=10.0)

    # Verify pod managers were created
    print(f"\n[t={env.now:.1f}s] Checking results...")
    print(f"✓ Service has {len(service.pod_managers)} pod managers")
    print(f"✓ Service has {len(service.pods)} pod instances")

    assert len(service.pod_managers) == 2, f"Expected 2 pod managers, got {len(service.pod_managers)}"
    print(f"✓ PASS: DeploymentController created 2 pod managers")

    # Verify pods were created and registered
    assert len(service.pods) >= 2, f"Expected at least 2 pods, got {len(service.pods)}"
    print(f"✓ PASS: Pod instances were registered with service")

    # Verify pods are RestartablePod instances
    for pod in service.pods:
        from src.components.pod_restartable import RestartablePod
        assert isinstance(pod, RestartablePod), f"Pod is not a RestartablePod: {type(pod)}"
    print(f"✓ PASS: All pods are RestartablePod instances")

    # Verify pods have correct parent service
    for pod in service.pods:
        assert pod.parent_service == service, "Pod parent_service not set correctly"
    print(f"✓ PASS: Pod parent_service references are correct")

    print("\n" + "="*70)
    print("✓✓✓ INTEGRATION TEST PASSED ✓✓✓")
    print("="*70 + "\n")


def test_pod_restart_integration():
    """
    Test that pod restarts work correctly through the lifecycle manager.
    """
    print("\n" + "="*70)
    print("TEST: Pod Restart Through Lifecycle Manager")
    print("="*70 + "\n")

    env = simpy.Environment()

    # Create a service
    service = Service(
        env=env,
        component_id="test_service",
        service_name="test_service",
        desired_replicas=1
    )

    # Create compute node
    node = ComputeNode(env, "node1", cpu_cores=4, memory_gb=8)

    # Start node (needs to be running to accept pods)
    env.process(node.run())

    # Create deployment controller
    controller = DeploymentController(env)
    controller.register_service(service)
    controller.register_node(node)

    # Start controller
    env.process(controller.run())

    # Run until pods are created
    print(f"[t=0.0s] Starting simulation...")
    env.run(until=10.0)

    print(f"\n[t={env.now:.1f}s] Initial state:")
    print(f"  - Pod managers: {len(service.pod_managers)}")
    print(f"  - Pod instances: {len(service.pods)}")

    # Get the pod manager and current pod instance
    pod_manager = service.pod_managers[0]
    original_pod = pod_manager.current_instance
    original_pod_id = original_pod.instance_id
    original_thread_pool_id = id(original_pod.thread_pool)

    print(f"  - Original pod: {original_pod_id}")
    print(f"  - Original thread_pool ID: {original_thread_pool_id}")

    # Trigger a crash
    print(f"\n[t={env.now:.1f}s] >>> TRIGGERING POD CRASH <<<")
    pod_manager.trigger_crash("OOMKilled")

    # Run simulation to allow restart
    env.run(until=env.now + 15.0)

    # Verify new pod instance was created
    new_pod = pod_manager.current_instance
    print(f"\n[t={env.now:.1f}s] After restart:")
    print(f"  - Pod managers: {len(service.pod_managers)}")
    print(f"  - Pod instances: {len(service.pods)}")

    if new_pod:
        new_pod_id = new_pod.instance_id
        new_thread_pool_id = id(new_pod.thread_pool)

        print(f"  - New pod: {new_pod_id}")
        print(f"  - New thread_pool ID: {new_thread_pool_id}")

        # Verify it's a different instance
        assert new_pod_id != original_pod_id, "Pod instance ID didn't change!"
        print(f"✓ PASS: New pod instance created with different ID")

        # Verify it's a different thread_pool object (proves state isolation)
        assert new_thread_pool_id != original_thread_pool_id, "Thread pool wasn't recreated!"
        print(f"✓ PASS: New pod has fresh thread_pool (state isolation works)")

        # Verify still only 1 pod manager
        assert len(service.pod_managers) == 1, f"Expected 1 pod manager, got {len(service.pod_managers)}"
        print(f"✓ PASS: Still only 1 pod manager (persistent)")

        # Verify service.pods list was updated correctly
        assert new_pod in service.pods, "New pod not in service.pods list!"
        assert original_pod not in service.pods, "Old pod still in service.pods list!"
        print(f"✓ PASS: Service.pods list updated correctly via callbacks")

    else:
        print(f"✗ FAIL: No new pod instance created after restart!")
        assert False, "Pod restart failed"

    print("\n" + "="*70)
    print("✓✓✓ RESTART INTEGRATION TEST PASSED ✓✓✓")
    print("="*70 + "\n")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("RESTARTABLE COMPONENT INTEGRATION TESTS")
    print("="*70 + "\n")

    test_deployment_controller_integration()
    print("\n")
    test_pod_restart_integration()

    print("\n" + "="*70)
    print("ALL INTEGRATION TESTS PASSED!")
    print("="*70)
    print("\nThe RestartableComponent pattern is now integrated into the simulation!")
    print("DeploymentController creates ComponentLifecycleManagers that:")
    print("  1. ✓ Create fresh RestartablePod instances")
    print("  2. ✓ Handle restarts automatically")
    print("  3. ✓ Update Service.pods list via callbacks")
    print("  4. ✓ Ensure state isolation on every restart")
    print("="*70 + "\n")
