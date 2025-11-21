"""
Debug script to understand why workload generator isn't starting.
"""
import json
import simpy
from src.topology.generator import TopologyGenerator
from src.topology.adapter import TopologyAdapter

# Create environment
env = simpy.Environment()

# Generate topology
topo_gen = TopologyGenerator(seed=42)
nx_graph = topo_gen.generate_complex_graph(num_nodes=10)

# Convert to SimPy components
adapter = TopologyAdapter(env)
registry = adapter.graph_to_registry(nx_graph)

# Find gateway
gateway = registry.get('gateway')
print(f"\n=== Gateway Analysis ===")
print(f"Gateway exists: {gateway is not None}")
if gateway:
    print(f"Request-to-service map: {len(gateway.request_to_service_map)} entries")
    for req_type, service in gateway.request_to_service_map.items():
        print(f"  {req_type} -> {service.service_name}")
        compute_pool = service.connections.get('compute_pool', [])
        print(f"    Compute pool size: {len(compute_pool)}")
        for compute in compute_pool:
            print(f"      - {compute.id} (state: {compute.state.operational})")

# Start components
print(f"\n=== Starting Components ===")
for comp_id, component in registry.items():
    if hasattr(component, 'run'):
        env.process(component.run())
        print(f"Started: {comp_id}")

# Run for 5 simulation seconds (enough for compute agents to reach RUNNING)
print(f"\n=== Running simulation for 5s ===")
env.run(until=5)

# Check again
print(f"\n=== Gateway Analysis (After 5s) ===")
if gateway:
    print(f"Request-to-service map: {len(gateway.request_to_service_map)} entries")
    for req_type, service in gateway.request_to_service_map.items():
        print(f"  {req_type} -> {service.service_name}")
        compute_pool = service.connections.get('compute_pool', [])
        print(f"    Compute pool size: {len(compute_pool)}")
        healthy_count = 0
        for compute in compute_pool:
            state = compute.state.operational
            print(f"      - {compute.id} (state: {state})")
            if state == 'RUNNING':
                healthy_count += 1
        print(f"    Healthy compute agents: {healthy_count}")

        # Test get_compute_target()
        target = service.get_compute_target()
        print(f"    get_compute_target() returns: {target.id if target else None}")
