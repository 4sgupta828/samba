#!/usr/bin/env python3
"""
Test script to verify DAG enforcement for synchronous calls.
Ensures no circular dependencies exist in generated topologies.
"""
import networkx as nx
from src.topology.generator import TopologyGenerator


def has_sync_cycles(G: nx.DiGraph) -> bool:
    """
    Check if the graph has any cycles in the synchronous subgraph.

    Returns:
        True if synchronous cycles exist, False otherwise
    """
    # Build subgraph of only synchronous edges
    sync_edges = [
        (s, t) for s, t, d in G.edges(data=True)
        if 'async' not in d.get('type', 'sync')
        and d.get('type') != 'pod_pool'
        and d.get('type') != 'pod_placement'
    ]

    G_sync = nx.DiGraph()
    G_sync.add_nodes_from(G.nodes())
    G_sync.add_edges_from(sync_edges)

    # Check for cycles
    try:
        cycles = list(nx.find_cycle(G_sync, orientation='original'))
        return len(cycles) > 0
    except nx.NetworkXNoCycle:
        return False


def test_dag_enforcement():
    """
    Test that generated topologies have no synchronous cycles.
    """
    print("Testing DAG enforcement for synchronous calls...")
    print("=" * 60)

    # Test multiple topology sizes and seeds
    test_configs = [
        (10, 42),   # Small topology
        (20, 123),  # Medium topology
        (30, 456),  # Larger topology
        (15, 789),  # Another medium
        (25, 999),  # Another large
    ]

    all_passed = True

    for num_nodes, seed in test_configs:
        print(f"\nTest: num_nodes={num_nodes}, seed={seed}")

        generator = TopologyGenerator(seed=seed)
        G = generator.generate_complex_graph(num_nodes=num_nodes)

        # Count edge types
        sync_edges = 0
        async_edges = 0
        infra_edges = 0

        for u, v, data in G.edges(data=True):
            edge_type = data.get('type', 'sync')
            if 'async' in edge_type:
                async_edges += 1
            elif edge_type in ['pod_pool', 'pod_placement']:
                infra_edges += 1
            else:
                sync_edges += 1

        print(f"  Nodes: {G.number_of_nodes()}")
        print(f"  Total Edges: {G.number_of_edges()}")
        print(f"  Sync Edges: {sync_edges}")
        print(f"  Async Edges: {async_edges}")
        print(f"  Infra Edges: {infra_edges}")

        # Check for synchronous cycles
        has_cycles = has_sync_cycles(G)

        if has_cycles:
            print("  ❌ FAILED: Synchronous cycles detected!")
            all_passed = False

            # Find and print the cycles for debugging
            sync_edges_list = [
                (s, t) for s, t, d in G.edges(data=True)
                if 'async' not in d.get('type', 'sync')
                and d.get('type') != 'pod_pool'
                and d.get('type') != 'pod_placement'
            ]
            G_sync = nx.DiGraph()
            G_sync.add_edges_from(sync_edges_list)
            cycles = list(nx.simple_cycles(G_sync))
            print(f"  Found {len(cycles)} cycle(s):")
            for i, cycle in enumerate(cycles[:3]):  # Show first 3 cycles
                print(f"    Cycle {i+1}: {' -> '.join(cycle + [cycle[0]])}")
        else:
            print("  ✅ PASSED: No synchronous cycles detected")

        # Verify graph is still connected (service-layer nodes only)
        if 'gateway' in G:
            reachable = set(nx.descendants(G, 'gateway')) | {'gateway'}
            unreachable = set(G.nodes()) - reachable

            # Check if any unreachable nodes are service-layer (should be zero after cleanup)
            service_layer_roles = ['service', 'database', 'cache', 'queue', 'external']
            unreachable_services = [
                n for n in unreachable
                if G.nodes[n].get('role') in service_layer_roles
            ]

            if len(unreachable_services) == 0:
                print("  ✅ PASSED: All service-layer nodes reachable from gateway")
            else:
                print(f"  ❌ FAILED: {len(unreachable_services)} service-layer nodes unreachable!")
                all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests PASSED! DAG enforcement is working correctly.")
        return 0
    else:
        print("❌ Some tests FAILED! Review the output above.")
        return 1


if __name__ == '__main__':
    exit(test_dag_enforcement())
