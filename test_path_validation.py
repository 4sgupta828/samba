#!/usr/bin/env python3
"""
Test path validation to ensure only valid directed paths are used.
"""
from src.validation.health_validator import calculate_safe_workload


def test_directed_paths():
    """Test that path finding respects edge directions."""

    # Create a simple topology with directed edges
    topology = {
        'nodes': [
            {'id': 'gateway', 'role': 'gateway'},
            {'id': 'svc_0', 'role': 'service', 'desired_replicas': 3},
            {'id': 'svc_1', 'role': 'service', 'desired_replicas': 3},
            {'id': 'db_0', 'role': 'database'},
        ],
        'edges': [
            # Gateway can reach svc_0
            {'source': 'gateway', 'target': 'svc_0', 'type': 'sync_http'},
            # svc_0 can reach db_0
            {'source': 'svc_0', 'target': 'db_0', 'type': 'sync_db'},
            # svc_1 can reach db_0, but gateway CANNOT reach svc_1
            {'source': 'svc_1', 'target': 'db_0', 'type': 'sync_db'},
        ]
    }

    result = calculate_safe_workload(topology)

    print("=" * 60)
    print("Test: Directed Path Validation")
    print("=" * 60)
    print(f"\nTopology:")
    print(f"  gateway -> svc_0 -> db_0")
    print(f"  svc_1 -> db_0 (NOT reachable from gateway)")

    print(f"\nResults:")
    print(f"  Paths analyzed: {result['num_paths_analyzed']}")
    print(f"  Leaf nodes: {result['num_leaf_nodes']}")
    print(f"  Critical path: {result['critical_path']}")
    print(f"  Safe baseline RPS: {result['safe_baseline_rps']}")
    print(f"  Bottleneck: {result['bottleneck_node']} ({result['bottleneck_role']})")

    # Validate results
    assert result['num_paths_analyzed'] == 1, "Should only find 1 valid path (gateway -> svc_0 -> db_0)"
    assert 'gateway' in result['critical_path'], "Critical path should include gateway"
    assert 'svc_0' in result['critical_path'], "Critical path should include svc_0"
    assert 'db_0' in result['critical_path'], "Critical path should include db_0"
    assert 'svc_1' not in result['critical_path'], "Critical path should NOT include svc_1 (unreachable)"

    print("\n✓ Test PASSED: Path finding correctly respects edge directions")


def test_circular_path_avoidance():
    """Test that circular paths are avoided."""

    # Create topology with potential circular dependency
    topology = {
        'nodes': [
            {'id': 'gateway', 'role': 'gateway'},
            {'id': 'svc_0', 'role': 'service', 'desired_replicas': 3},
            {'id': 'svc_1', 'role': 'service', 'desired_replicas': 3},
            {'id': 'db_0', 'role': 'database'},
        ],
        'edges': [
            {'source': 'gateway', 'target': 'svc_0', 'type': 'sync_http'},
            {'source': 'svc_0', 'target': 'svc_1', 'type': 'sync_rpc'},
            # Circular edge: svc_1 -> svc_0 (should not cause infinite loop)
            {'source': 'svc_1', 'target': 'svc_0', 'type': 'sync_rpc'},
            {'source': 'svc_1', 'target': 'db_0', 'type': 'sync_db'},
        ]
    }

    result = calculate_safe_workload(topology)

    print("\n" + "=" * 60)
    print("Test: Circular Path Avoidance")
    print("=" * 60)
    print(f"\nTopology:")
    print(f"  gateway -> svc_0 -> svc_1 -> db_0")
    print(f"  svc_1 -> svc_0 (circular edge)")

    print(f"\nResults:")
    print(f"  Paths analyzed: {result['num_paths_analyzed']}")
    print(f"  Critical path: {result['critical_path']}")
    print(f"  Safe baseline RPS: {result['safe_baseline_rps']}")

    # Validate: should find path without getting stuck in cycle
    assert result['num_paths_analyzed'] > 0, "Should find at least one path"
    assert 'gateway' in result['critical_path'], "Should start from gateway"
    assert 'db_0' in result['critical_path'], "Should end at db_0"

    print("\n✓ Test PASSED: Circular edges handled correctly (no infinite loops)")


def test_multiple_paths():
    """Test handling of multiple valid paths."""

    topology = {
        'nodes': [
            {'id': 'gateway', 'role': 'gateway'},
            {'id': 'svc_0', 'role': 'service', 'desired_replicas': 3},
            {'id': 'svc_1', 'role': 'service', 'desired_replicas': 3},
            {'id': 'db_0', 'role': 'database'},
            {'id': 'cache_0', 'role': 'cache'},
        ],
        'edges': [
            # Two paths from gateway to db_0
            {'source': 'gateway', 'target': 'svc_0', 'type': 'sync_http'},
            {'source': 'gateway', 'target': 'svc_1', 'type': 'sync_http'},
            {'source': 'svc_0', 'target': 'db_0', 'type': 'sync_db'},
            {'source': 'svc_1', 'target': 'db_0', 'type': 'sync_db'},
            # Path to cache
            {'source': 'svc_0', 'target': 'cache_0', 'type': 'sync_cache'},
        ]
    }

    result = calculate_safe_workload(topology)

    print("\n" + "=" * 60)
    print("Test: Multiple Valid Paths")
    print("=" * 60)
    print(f"\nTopology:")
    print(f"  gateway -> svc_0 -> db_0")
    print(f"  gateway -> svc_1 -> db_0")
    print(f"  gateway -> svc_0 -> cache_0")

    print(f"\nResults:")
    print(f"  Paths analyzed: {result['num_paths_analyzed']}")
    print(f"  Leaf nodes: {result['num_leaf_nodes']}")
    print(f"  Critical path: {result['critical_path']}")
    print(f"  Critical path p99 latency: {result['critical_path_latency_p99_ms']:.1f}ms")
    print(f"  Safe baseline RPS: {result['safe_baseline_rps']}")

    # Should find all 3 paths
    assert result['num_paths_analyzed'] == 3, f"Should find 3 paths, found {result['num_paths_analyzed']}"
    assert result['num_leaf_nodes'] == 2, f"Should have 2 leaf nodes (db_0, cache_0), found {result['num_leaf_nodes']}"

    print("\n✓ Test PASSED: Multiple paths handled correctly")


def test_pod_edges_ignored():
    """Test that pod and node edges are correctly handled."""

    topology = {
        'nodes': [
            {'id': 'gateway', 'role': 'gateway'},
            {'id': 'svc_0', 'role': 'service', 'desired_replicas': 3},
            {'id': 'pod_svc_0_0', 'role': 'pod'},
            {'id': 'node_0', 'role': 'node'},
            {'id': 'db_0', 'role': 'database'},
        ],
        'edges': [
            {'source': 'gateway', 'target': 'svc_0', 'type': 'sync_http'},
            # Pod pool edges (infrastructure, not service path)
            {'source': 'svc_0', 'target': 'pod_svc_0_0', 'type': 'pod_pool'},
            {'source': 'pod_svc_0_0', 'target': 'node_0', 'type': 'pod_placement'},
            # Actual service path
            {'source': 'svc_0', 'target': 'db_0', 'type': 'sync_db'},
        ]
    }

    result = calculate_safe_workload(topology)

    print("\n" + "=" * 60)
    print("Test: Pod/Node Edge Handling")
    print("=" * 60)
    print(f"\nTopology:")
    print(f"  Service path: gateway -> svc_0 -> db_0")
    print(f"  Infrastructure: svc_0 -> pod_svc_0_0 -> node_0")

    print(f"\nResults:")
    print(f"  Paths analyzed: {result['num_paths_analyzed']}")
    print(f"  Critical path: {result['critical_path']}")

    # Should find path to db_0, not to pod/node (those are infrastructure)
    assert 'db_0' in result['critical_path'], "Should include service path to db_0"
    # Pods and nodes are not leaf nodes for service traffic analysis
    assert result['num_leaf_nodes'] == 1, f"Should have 1 leaf (db_0), found {result['num_leaf_nodes']}"

    print("\n✓ Test PASSED: Pod/node infrastructure correctly distinguished from service paths")


if __name__ == '__main__':
    test_directed_paths()
    test_circular_path_avoidance()
    test_multiple_paths()
    test_pod_edges_ignored()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
