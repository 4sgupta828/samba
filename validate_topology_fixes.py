#!/usr/bin/env python3
"""
Validation script to test topology generation fixes.
Run after regenerating topology bank to ensure fixes work correctly.
"""
import json
import networkx as nx
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def load_topology(path: str) -> Tuple[nx.DiGraph, Dict]:
    """Load topology graph and raw LLM output."""
    with open(f"{path}/graph.json") as f:
        graph_json = json.load(f)

    with open(f"{path}/raw_llm_output.json") as f:
        raw_output = json.load(f)

    G = nx.node_link_graph(graph_json)
    return G, raw_output


def validate_pod_counts(G: nx.DiGraph) -> List[str]:
    """Validate pod count matches desired_replicas."""
    errors = []

    for node, data in G.nodes(data=True):
        if data.get('role') == 'service':
            desired = data.get('desired_replicas', 3)
            pods = [n for n in G.successors(node)
                   if G.nodes[n].get('role') == 'pod']

            if len(pods) != desired:
                errors.append(
                    f"❌ {node}: expected {desired} pods, got {len(pods)}"
                )

    return errors


def validate_async_edges(G: nx.DiGraph) -> List[str]:
    """Validate async edges only connect to/from MessageQueues."""
    errors = []

    for src, tgt, data in G.edges(data=True):
        edge_type = data.get('type', '')

        # async_produce must target MessageQueue
        if edge_type == 'async_produce':
            tgt_type = G.nodes[tgt].get('type')
            if tgt_type != 'MessageQueue':
                errors.append(
                    f"❌ async_produce {src} → {tgt}: "
                    f"target is {tgt_type}, not MessageQueue"
                )

        # async_consume must originate from MessageQueue
        if edge_type == 'async_consume':
            src_type = G.nodes[src].get('type')
            if src_type != 'MessageQueue':
                errors.append(
                    f"❌ async_consume {src} → {tgt}: "
                    f"source is {src_type}, not MessageQueue"
                )

    return errors


def validate_minimum_counts(G: nx.DiGraph, raw_output: Dict, expected_archetype: str) -> List[str]:
    """Validate topology meets minimum node counts."""
    errors = []

    # Count node types (from raw LLM output, not graph which includes pods/nodes)
    type_counts = {}
    for node in raw_output.get('nodes', []):
        node_type = node['type']
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    # Define minimums (must match llm_generator.py)
    is_pipeline = 'pipeline' in expected_archetype.lower()
    minimums = {
        "Service": 5,
        "SqlDatabase": 1,
        "ExternalCache": 1,
        "MessageQueue": 3 if is_pipeline else 1,
        "ExternalService": 1
    }

    for node_type, min_count in minimums.items():
        actual = type_counts.get(node_type, 0)
        if actual < min_count:
            errors.append(
                f"❌ {node_type}: need at least {min_count}, got {actual}"
            )

    return errors


def validate_async_consumer_capacity(raw_output: Dict) -> List[str]:
    """Check if services that consume from queues have async_consumer_capacity."""
    warnings = []

    # Build edge map
    edges = raw_output.get('edges', [])
    consumers = set()

    for edge in edges:
        if edge['type'] == 'async_consume':
            consumers.add(edge['target'])

    # Check each consumer service
    nodes = {n['id']: n for n in raw_output.get('nodes', [])}

    for consumer_id in consumers:
        node = nodes.get(consumer_id, {})
        if node.get('type') == 'Service':
            capacity = node.get('async_consumer_capacity')
            if capacity is None:
                warnings.append(
                    f"⚠️  {consumer_id}: consumes from queue but missing async_consumer_capacity"
                )

    return warnings


def validate_topology(path: str) -> bool:
    """Run all validations on a topology."""
    print(f"\n{'='*80}")
    print(f"Validating: {path}")
    print(f"{'='*80}")

    try:
        G, raw_output = load_topology(path)
    except Exception as e:
        print(f"❌ FAILED to load topology: {e}")
        return False

    all_errors = []
    all_warnings = []

    # Get archetype from path
    archetype = Path(path).name.split('_')[0]

    # Run validations
    errors = validate_pod_counts(G)
    if errors:
        all_errors.extend(errors)
    else:
        print("✅ Pod counts match desired_replicas")

    errors = validate_async_edges(G)
    if errors:
        all_errors.extend(errors)
    else:
        print("✅ Async edges are valid (async_produce → Queue, async_consume from Queue)")

    errors = validate_minimum_counts(G, raw_output, archetype)
    if errors:
        all_errors.extend(errors)
    else:
        print(f"✅ Minimum node counts met for {archetype} small topology")

    warnings = validate_async_consumer_capacity(raw_output)
    if warnings:
        all_warnings.extend(warnings)
    else:
        print("✅ All queue consumers have async_consumer_capacity specified")

    # Print summary
    print(f"\n📊 Topology Stats:")
    services = [n for n, d in G.nodes(data=True) if d.get('type') == 'Service']
    databases = [n for n, d in G.nodes(data=True) if d.get('type') == 'SqlDatabase']
    caches = [n for n, d in G.nodes(data=True) if d.get('type') == 'ExternalCache']
    queues = [n for n, d in G.nodes(data=True) if d.get('type') == 'MessageQueue']
    external = [n for n, d in G.nodes(data=True) if d.get('type') == 'ExternalService']

    print(f"   Services: {len(services)}")
    print(f"   Databases: {len(databases)}")
    print(f"   Caches: {len(caches)}")
    print(f"   Queues: {len(queues)}")
    print(f"   External: {len(external)}")
    print(f"   Total nodes (app/infra): {len(services) + len(databases) + len(caches) + len(queues) + len(external)}")

    # Print results
    if all_errors:
        print(f"\n❌ VALIDATION FAILED ({len(all_errors)} errors):")
        for error in all_errors:
            print(f"   {error}")
        return False

    if all_warnings:
        print(f"\n⚠️  WARNINGS ({len(all_warnings)}):")
        for warning in all_warnings:
            print(f"   {warning}")

    print(f"\n✅ ALL VALIDATIONS PASSED")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Validate topology generation fixes'
    )
    parser.add_argument(
        'topology_dir',
        type=str,
        help='Path to topology directory or topology bank'
    )

    args = parser.parse_args()

    topology_path = Path(args.topology_dir)

    # Check if it's a single topology or a bank
    if (topology_path / 'graph.json').exists():
        # Single topology
        success = validate_topology(str(topology_path))
        sys.exit(0 if success else 1)
    else:
        # Topology bank - validate all topologies
        topologies = [d for d in topology_path.iterdir()
                     if d.is_dir() and (d / 'graph.json').exists()]

        if not topologies:
            print(f"❌ No topologies found in {topology_path}")
            sys.exit(1)

        print(f"Found {len(topologies)} topologies to validate")

        results = []
        for topo in sorted(topologies):
            success = validate_topology(str(topo))
            results.append((topo.name, success))

        # Print summary
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")

        passed = sum(1 for _, success in results if success)
        failed = len(results) - passed

        for name, success in results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"   {status}: {name}")

        print(f"\n{'='*80}")
        print(f"✅ Passed: {passed}/{len(results)}")
        print(f"❌ Failed: {failed}/{len(results)}")
        print(f"{'='*80}")

        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
