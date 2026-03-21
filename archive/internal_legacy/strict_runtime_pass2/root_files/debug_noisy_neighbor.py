#!/usr/bin/env python3
"""
Debug script to analyze noisy neighbor issues:
1. Check if noisy neighbor impact is working correctly
2. Verify fault removal is working
3. Analyze why fault injection always picks consumer nodes
4. Check why queue impact not detected in fault propagation
"""

import json
import sys
import networkx as nx

def analyze_dataset(ep_dir):
    """Analyze a specific episode."""
    print(f"\n{'='*80}")
    print(f"ANALYZING: {ep_dir}")
    print(f"{'='*80}\n")

    # Load label
    with open(f"{ep_dir}/label.json") as f:
        label = json.load(f)

    # Load topology
    with open(f"{ep_dir}/topology.json") as f:
        topo = json.load(f)

    # Load fault propagation
    with open(f"{ep_dir}/fault_propagation.json") as f:
        fault_prop = json.load(f)

    # Load metrics
    with open(f"{ep_dir}/metrics.jsonl") as f:
        metrics = [json.loads(line) for line in f]

    print(f"1. FAULT DETAILS")
    print(f"   Root cause: {label['root_cause_node']}")
    print(f"   Fault type: {label['fault_type']}")
    print(f"   Fault start: {label['fault_start_time']}s")
    print(f"   Recovery start: {label['recovery_start_time']}s")
    print(f"   Fault params: {label.get('fault_params', {})}")

    # Find the root cause node details
    root_node = None
    for node in topo['nodes']:
        if node['id'] == label['root_cause_node']:
            root_node = node
            break

    print(f"\n2. ROOT CAUSE NODE ANALYSIS")
    if root_node:
        print(f"   Type: {root_node['type']}")
        print(f"   Role: {root_node.get('role', 'N/A')}")

        # Find all edges involving this node
        incoming = [e for e in topo['edges'] if e['target'] == root_node['id']]
        outgoing = [e for e in topo['edges'] if e['source'] == root_node['id']]

        print(f"   Incoming edges: {len(incoming)}")
        for edge in incoming:
            print(f"     - {edge['source']} -> {root_node['id']} (type: {edge['type']})")

        print(f"   Outgoing edges: {len(outgoing)}")
        for edge in outgoing:
            print(f"     - {root_node['id']} -> {edge['target']} (type: {edge['type']})")

        # Check if this is a queue consumer
        is_consumer = any(e['type'] == 'async_consume' for e in incoming)
        print(f"   Is queue consumer: {is_consumer}")

    print(f"\n3. FAULT PROPAGATION ANALYSIS")
    print(f"   Nodes analyzed: {fault_prop['propagation_statistics']['total_nodes_analyzed']}")
    print(f"   Critically impacted: {fault_prop['propagation_statistics']['nodes_critically_impacted']}")
    print(f"   Highly impacted: {fault_prop['propagation_statistics']['nodes_highly_impacted']}")
    print(f"   Moderately impacted: {fault_prop['propagation_statistics']['nodes_moderately_impacted']}")

    # Check if any queue nodes show impact
    queue_reports = [r for r in fault_prop['node_reports'] if 'queue' in r['node_id'].lower()]
    print(f"   Queue nodes in report: {len(queue_reports)}")
    for qr in queue_reports:
        print(f"     - {qr['node_id']}: {qr['overall_severity']} (score: {qr['overall_severity_score']:.3f})")

    # Check upstream propagation
    if root_node:
        # Find nodes that call or consume from the root node
        upstream_nodes = [e['source'] for e in incoming]
        print(f"\n   Upstream nodes (should be impacted): {len(upstream_nodes)}")
        for un in upstream_nodes:
            report = next((r for r in fault_prop['node_reports'] if r['node_id'] == un), None)
            if report:
                print(f"     - {un}: {report['overall_severity']} (score: {report['overall_severity_score']:.3f})")
            else:
                print(f"     - {un}: NOT IN REPORT!")

    print(f"\n4. NOISY NEIGHBOR SPECIFIC ANALYSIS")
    if label['fault_type'] == 'noisy_neighbor':
        # Get CPU metrics for the faulty service and its pods
        service_id = label['root_cause_node']

        # Find pods for this service
        pod_ids = [n['id'] for n in topo['nodes']
                  if n.get('type') == 'Pod' and n.get('parent_service') == service_id]

        print(f"   Service: {service_id}")
        print(f"   Pods: {pod_ids}")

        # Get CPU metrics for each pod
        for pod_id in pod_ids:
            cpu_metrics = [m for m in metrics
                          if m.get('name') == 'container.cpu.utilization'
                          and pod_id in m.get('labels', {}).get('container.id', '')]

            if cpu_metrics:
                # Get baseline vs fault period
                baseline = [m for m in cpu_metrics
                           if float(m['labels'].get('sim.time', 0)) < label['fault_start_time']]
                fault_period = [m for m in cpu_metrics
                               if label['fault_start_time'] <= float(m['labels'].get('sim.time', 0)) < label['recovery_start_time']]

                if baseline and fault_period:
                    baseline_avg = sum(m['value'] for m in baseline) / len(baseline)
                    fault_avg = sum(m['value'] for m in fault_period) / len(fault_period)
                    print(f"     {pod_id}:")
                    print(f"       Baseline CPU: {baseline_avg:.1f}%")
                    print(f"       Fault CPU: {fault_avg:.1f}%")
                    print(f"       Increase: {fault_avg - baseline_avg:.1f}% (+{(fault_avg/baseline_avg - 1)*100:.1f}%)")

        # Check if multiple pods affected or just one
        print(f"\n   ISSUE CHECK: Should only ONE pod have high CPU (aggressor)")

        # Get request distribution across pods
        print(f"\n   Request distribution:")
        for pod_id in pod_ids:
            req_metrics = [m for m in metrics
                          if 'request' in m.get('name', '').lower()
                          and pod_id in m.get('labels', {}).get('container.id', '')]

            if req_metrics:
                fault_reqs = [m for m in req_metrics
                             if label['fault_start_time'] <= float(m['labels'].get('sim.time', 0)) < label['recovery_start_time']]
                if fault_reqs:
                    total_reqs = sum(m['value'] for m in fault_reqs if 'count' in m.get('name', ''))
                    print(f"     {pod_id}: {total_reqs} requests during fault")

    print(f"\n5. FAULT REMOVAL VERIFICATION")
    # Check metrics after recovery
    recovery_metrics = [m for m in metrics
                       if float(m['labels'].get('sim.time', 0)) >= label['recovery_complete_time']]

    print(f"   Recovery complete time: {label['recovery_complete_time']}s")
    print(f"   Metrics after recovery: {len(recovery_metrics)}")

    if label['fault_type'] == 'noisy_neighbor':
        # Check CPU returns to baseline
        for pod_id in pod_ids:
            recovery_cpu = [m for m in metrics
                           if m.get('name') == 'container.cpu.utilization'
                           and pod_id in m.get('labels', {}).get('container.id', '')
                           and float(m['labels'].get('sim.time', 0)) >= label['recovery_complete_time']]

            if recovery_cpu and len(recovery_cpu) >= 3:
                # Check last few measurements
                last_cpus = [m['value'] for m in recovery_cpu[-5:]]
                avg_recovery = sum(last_cpus) / len(last_cpus)
                print(f"     {pod_id} post-recovery CPU: {avg_recovery:.1f}%")

                if avg_recovery > 50:
                    print(f"       WARNING: CPU still high after recovery!")

    print(f"\n6. TARGET SELECTION BIAS ANALYSIS")
    # Analyze why this node was selected
    print(f"   Node selection analysis for: {label['root_cause_node']}")

    if root_node:
        # Calculate connectivity score as done in generate_dataset.py
        G = nx.DiGraph()
        for edge in topo['edges']:
            G.add_edge(edge['source'], edge['target'])

        predecessors = list(G.predecessors(root_node['id']))
        second_order = set()
        for pred in predecessors:
            second_order.update(G.predecessors(pred))

        score = len(predecessors) * 10 + len(second_order)

        print(f"   Direct callers (predecessors): {len(predecessors)}")
        print(f"   Second-order callers: {len(second_order)}")
        print(f"   Connectivity score: {score}")

        # Compare with other service nodes
        print(f"\n   Comparison with other service nodes:")
        service_nodes = [n for n in topo['nodes'] if n.get('role') == 'service']
        scores = []
        for sn in service_nodes:
            preds = list(G.predecessors(sn['id']))
            second = set()
            for pred in preds:
                second.update(G.predecessors(pred))
            s = len(preds) * 10 + len(second)
            scores.append((sn['id'], s, len(preds)))

        scores.sort(key=lambda x: x[1], reverse=True)
        for node_id, node_score, num_preds in scores[:5]:
            marker = " <-- SELECTED" if node_id == root_node['id'] else ""
            print(f"     {node_id}: score={node_score}, predecessors={num_preds}{marker}")

        print(f"\n   ISSUE: High predecessor count favors CONSUMERS (nodes with incoming edges)")
        print(f"   SUGGESTION: Should score based on SUCCESSORS (downstream impact) not predecessors")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_dataset(sys.argv[1])
    else:
        analyze_dataset("data/data_20251206_104254/ep_0")
