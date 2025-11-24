"""
Test topology state tracking with dynamic Service/Pod/Node mappings.

This demonstrates how to capture and export dynamic topology state over time.
"""
import simpy
import sys
import json
sys.path.insert(0, '/Users/sgupta/samba')

from src.components.service import Service
from src.components.pod import Pod
from src.components.compute_node import ComputeNode
from src.components.deployment_controller import DeploymentController
from src.components.database import SqlDatabase
from src.components.storage import InMemoryCache
from src.telemetry.topology_state_exporter import TopologyStateExporter
from src.core.simulation_config import get_simulation_config


def test_topology_tracking():
    """Test topology state tracking with dynamic changes."""
    print("=" * 70)
    print("TOPOLOGY STATE TRACKING TEST")
    print("=" * 70)

    # Initialize
    env = simpy.Environment()
    config = get_simulation_config()

    # Create topology state exporter (event-driven only)
    print("\n[1] Creating Topology State Exporter (Event-Driven)")
    exporter = TopologyStateExporter(
        env,
        output_dir="data/test_topology_tracking"
    )

    print(f"    Output directory: {exporter.output_dir}")
    print(f"    Export mode: Event-driven (only on pod/node changes)")

    # Create infrastructure
    print("\n[2] Creating Infrastructure")
    db = SqlDatabase(env, "db_0")
    cache = InMemoryCache(env, "cache_0")

    # Create compute nodes
    print("\n[3] Creating Compute Nodes")
    node_0 = ComputeNode(env, "node_0", cpu_cores=4, memory_gb=16)
    node_1 = ComputeNode(env, "node_1", cpu_cores=4, memory_gb=16)

    exporter.register_node(node_0)
    exporter.register_node(node_1)
    print(f"    Registered 2 nodes: {node_0.id}, {node_1.id}")

    # Create services
    print("\n[4] Creating Services")
    service_a = Service(
        env, "svc_a", "service_a",
        processing_pipeline=[
            {"type": "cache_check"},
            {"type": "db_query"},
        ],
        desired_replicas=3
    )
    service_b = Service(
        env, "svc_b", "service_b",
        processing_pipeline=[
            {"type": "db_query"},
        ],
        desired_replicas=2
    )

    # Connect services
    service_a.connections['database'] = db
    service_a.connections['cache'] = cache
    service_b.connections['database'] = db

    exporter.register_service(service_a)
    exporter.register_service(service_b)
    print(f"    Registered 2 services: {service_a.service_name}, {service_b.service_name}")

    # Create deployment controller with exporter
    print("\n[5] Creating DeploymentController with Topology Tracking")
    controller = DeploymentController(env, "controller", topology_exporter=exporter)
    controller.register_service(service_a)
    controller.register_service(service_b)
    controller.register_node(node_0)
    controller.register_node(node_1)

    exporter.register_controller(controller)
    print("    Controller registered with topology exporter")

    # Create initial pods
    print("\n[6] Creating Initial Pods")
    pods = []
    for i in range(3):
        pod = Pod(env, f"pod_a_{i}",
                 parent_service=service_a,
                 compute_node=node_0 if i < 2 else node_1)
        pods.append(pod)
        service_a.pods.append(pod)
        exporter.register_pod(pod)

    for i in range(2):
        pod = Pod(env, f"pod_b_{i}",
                 parent_service=service_b,
                 compute_node=node_1)
        pods.append(pod)
        service_b.pods.append(pod)
        exporter.register_pod(pod)

    print(f"    Created {len(pods)} pods total")
    print(f"    Service A: 3 pods (2 on node_0, 1 on node_1)")
    print(f"    Service B: 2 pods (both on node_1)")

    # Start components
    print("\n[7] Starting Components")
    env.process(db.run())
    env.process(cache.run())
    env.process(node_0.run())
    env.process(node_1.run())
    env.process(controller.run())

    for pod in pods:
        env.process(pod.run())

    # Export initial topology state
    exporter.export_initial_state()
    print("    All components started, initial topology state exported")

    # Simulate some activity
    print("\n[8] Running Simulation with Dynamic Changes")

    def simulate_workload():
        """Simulate workload and topology changes."""
        # Phase 1: Normal operation
        print("\n    [t=0-15s] Phase 1: Normal operation")
        yield env.timeout(15)

        # Phase 2: Simulate pod failure (controller will track and export)
        print(f"\n    [t={env.now:.1f}s] Phase 2: Simulating pod failure")
        failing_pod = service_a.pods[0]
        print(f"      Terminating {failing_pod.id} (controller will detect and reschedule)")
        failing_pod.state.operational = "TERMINATED"
        if hasattr(failing_pod, 'running_process') and failing_pod.running_process:
            failing_pod.running_process.interrupt("OOMKilled")

        yield env.timeout(10)

        # Phase 3: Controller should have created replacement
        print(f"\n    [t={env.now:.1f}s] Phase 3: Controller reconciliation")
        print(f"      Service A now has {len([p for p in service_a.pods if p.state.operational == 'RUNNING'])} running pods")

        yield env.timeout(15)

        # Phase 4: Simulate node overload
        print(f"\n    [t={env.now:.1f}s] Phase 4: Checking resource utilization")
        for node in [node_0, node_1]:
            cpu_util, mem_util = node.get_utilization()
            print(f"      {node.id}: CPU={cpu_util*100:.1f}%, Memory={mem_util*100:.1f}%")

        yield env.timeout(10)

        print(f"\n    [t={env.now:.1f}s] Simulation complete")

    env.process(simulate_workload())

    # Run simulation
    print("\n[9] Running Simulation for 60 seconds")
    env.run(until=60)

    # Export final snapshot
    print("\n[10] Exporting Final Snapshot")
    exporter.export_final_snapshot()

    # Print summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    summary = exporter.get_summary()
    print(f"\n✓ Total snapshots exported: {summary['total_snapshots']}")
    print(f"✓ Topology state file: {summary['topology_state_file']}")
    print(f"\n   Snapshots are exported only on changes:")
    print(f"   - Initial state (simulation start)")
    print(f"   - Pod created/terminated/rescheduled")
    print(f"   - Final state (simulation end)")

    # Read and display a sample snapshot
    print("\n[Sample Snapshot - Final State]")
    print("-" * 70)
    with open(summary['topology_state_file'], 'r') as f:
        lines = f.readlines()
        if lines:
            final_snapshot = json.loads(lines[-1])
            print(f"Timestamp: {final_snapshot['timestamp']:.1f}s")
            print(f"Snapshot Type: {final_snapshot['snapshot_type']}")
            print(f"\nServices: {len(final_snapshot['services'])}")
            for svc in final_snapshot['services']:
                print(f"  - {svc['service_name']}: {svc['actual_replicas']}/{svc['desired_replicas']} pods running")

            print(f"\nNodes: {len(final_snapshot['nodes'])}")
            for node in final_snapshot['nodes']:
                print(f"  - {node['id']}: {node['running_pods']} pods, "
                      f"CPU={node['cpu_utilization']*100:.1f}%, "
                      f"Memory={node['memory_utilization']*100:.1f}%")

            print(f"\nMappings:")
            mappings = final_snapshot['mappings']
            print(f"  Service → Pods:")
            for svc_id, pod_ids in mappings['service_to_pods'].items():
                print(f"    {svc_id}: {pod_ids}")
            print(f"  Node → Pods:")
            for node_id, pod_ids in mappings['node_to_pods'].items():
                print(f"    {node_id}: {pod_ids}")

    # Show all snapshots with events
    print("\n[All Topology Snapshots]")
    print("-" * 70)
    with open(summary['topology_state_file'], 'r') as f:
        all_snapshots = [json.loads(line) for line in f.readlines()]
        print(f"Total snapshots: {len(all_snapshots)}")
        print("\nSnapshot timeline:")
        for snap in all_snapshots:
            event_info = f" - {snap['event']}" if snap['event'] else ""
            print(f"  [{snap['timestamp']:6.1f}s] {snap['snapshot_type']:10s}{event_info}")

    print("\n" + "=" * 70)
    print("✓ TOPOLOGY STATE TRACKING SUCCESSFUL")
    print("=" * 70)

    return True


if __name__ == "__main__":
    try:
        test_topology_tracking()
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
