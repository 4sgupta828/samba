"""
Test script for the new Service/Pod/Node architecture.

This script creates a simple topology using:
- Service: Lightweight coordinator
- Pod: Container instances
- ComputeNode: Physical/VM resources
- DeploymentController: Centralized orchestrator
"""
import simpy
import sys
sys.path.insert(0, '/Users/sgupta/samba')

from src.components.service import Service
from src.components.pod import Pod
from src.components.compute_node import ComputeNode
from src.components.deployment_controller import DeploymentController
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache
from src.components.networking import RequestGateway
from src.core.simulation_config import get_simulation_config


def create_simple_topology():
    """
    Create a simple topology with:
    - 1 Service with 2 Pods
    - 1 ComputeNode hosting both pods
    - 1 Database
    - 1 Cache
    - 1 Gateway
    - 1 DeploymentController
    """
    # Initialize simulation environment
    env = simpy.Environment()

    # Load configuration (will use defaults from config file)
    config = get_simulation_config()

    print("Creating components...")

    # Create infrastructure
    gateway = RequestGateway(env, "gateway")
    database = SqlDatabase(env, "db_0")
    cache = InMemoryCache(env, "cache_0")

    # Create compute node
    node = ComputeNode(env, "node_0", cpu_cores=8, memory_gb=32)

    # Create service with processing pipeline
    service = Service(
        env,
        "svc_a",
        service_name="service_a",
        supported_request_types=["GET", "POST"],
        processing_pipeline=[
            {"type": "cache_check"},
            {"type": "db_query"},
        ],
        desired_replicas=2
    )

    # Connect service to infrastructure
    service.connections['database'] = database
    service.connections['cache'] = cache

    # Create pods
    pod_1 = Pod(env, "pod_a_0", parent_service=service, compute_node=node)
    pod_2 = Pod(env, "pod_a_1", parent_service=service, compute_node=node)

    # Add pods to service
    service.pods = [pod_1, pod_2]

    # Create deployment controller
    controller = DeploymentController(env, "deployment_controller")
    controller.register_service(service)
    controller.register_node(node)

    # Register service with gateway
    gateway.register_service(service, service.supported_request_types)

    print(f"✓ Created Service: {service.service_name}")
    print(f"✓ Created {len(service.pods)} Pods: {[p.id for p in service.pods]}")
    print(f"✓ Created ComputeNode: {node.id}")
    print(f"✓ Created DeploymentController: {controller.id}")
    print(f"✓ Connected to Database: {database.id}")
    print(f"✓ Connected to Cache: {cache.id}")

    # Start all components
    print("\nStarting components...")
    env.process(gateway.run())
    env.process(database.run())
    env.process(cache.run())
    env.process(node.run())
    env.process(controller.run())
    env.process(pod_1.run())
    env.process(pod_2.run())

    print("✓ All components started")

    # Run a simple test
    print("\nRunning simulation for 10 seconds...")

    def test_requests():
        """Generate a few test requests."""
        for i in range(5):
            yield env.timeout(1.0)
            try:
                print(f"  [{env.now:.1f}s] Sending request #{i+1}")
                yield from service.handle_request("GET", should_trace=False)
                print(f"  [{env.now:.1f}s] Request #{i+1} completed successfully")
            except Exception as e:
                print(f"  [{env.now:.1f}s] Request #{i+1} failed: {e}")

    env.process(test_requests())

    # Run simulation
    try:
        env.run(until=15)
        print(f"\n✓ Simulation completed successfully at t={env.now:.1f}s")
        return True
    except Exception as e:
        print(f"\n✗ Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Testing New Service/Pod/Node Architecture")
    print("=" * 60)
    print()

    success = create_simple_topology()

    print()
    print("=" * 60)
    if success:
        print("✓ TEST PASSED: New architecture works correctly!")
    else:
        print("✗ TEST FAILED: See errors above")
    print("=" * 60)
