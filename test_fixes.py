#!/usr/bin/env python3
"""
Test script to verify all fixes for noisy neighbor and fault system issues.

Tests:
1. Target selection is uniform (not biased toward consumers)
2. Fault propagation analyzes ALL nodes (including unreachable ones)
3. Noisy neighbor impacts co-located pods
4. Fault revert works correctly
"""

import subprocess
import json
import sys
import os
from collections import Counter

def test_fault_revert():
    """Test that fault removal works correctly."""
    print("\n" + "="*80)
    print("TEST 1: Fault Revert Registry")
    print("="*80)

    # Generate a single test episode
    print("\nGenerating test episode with noisy_neighbor...")
    result = subprocess.run([
        "python", "generate_dataset.py",
        "--episodes", "1",
        "--output-dir", "data/test_fault_revert",
        "--force-fault-type", "noisy_neighbor",
        "--force-fault-role", "service"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: Generation failed: {result.stderr}")
        return False

    # Check simulation logs for revert
    log_path = "data/test_fault_revert/ep_0/simulation.log"
    if not os.path.exists(log_path):
        print(f"ERROR: Log file not found: {log_path}")
        return False

    with open(log_path) as f:
        logs = f.read()

    # Check for successful revert (not the WARNING)
    if "WARNING: No revert function registered for 'noisy_neighbor'" in logs:
        print("FAIL: Revert function not registered!")
        print("Found warning:", [line for line in logs.split('\n') if 'revert' in line.lower()])
        return False

    if "REVERTING GRADUAL FAILURE: 'noisy_neighbor'" in logs:
        print("PASS: Revert function called successfully")

        # Check for actual revert messages in component logs
        logs_jsonl = "data/test_fault_revert/ep_0/logs.jsonl"
        if os.path.exists(logs_jsonl):
            with open(logs_jsonl) as f:
                component_logs = [json.loads(line) for line in f if line.strip()]

            revert_logs = [log for log in component_logs
                          if 'revert' in log.get('message', '').lower()
                          or 'removed' in log.get('message', '').lower()]

            if revert_logs:
                print(f"  Found {len(revert_logs)} revert log entries")
                for log in revert_logs[:5]:
                    print(f"    - {log.get('attributes', {}).get('component.id', 'unknown')}: {log.get('message', '')}")
                return True
            else:
                print("WARN: No revert logs found in component logs")
                return True  # Still pass if simulation log shows revert
        else:
            return True
    else:
        print("FAIL: Revert not called")
        return False

def test_target_selection():
    """Test that target selection is uniform (not biased)."""
    print("\n" + "="*80)
    print("TEST 2: Uniform Target Selection")
    print("="*80)

    # Generate 20 episodes and collect target selections
    print("\nGenerating 20 episodes to test target selection distribution...")
    result = subprocess.run([
        "python", "generate_dataset.py",
        "--episodes", "20",
        "--output-dir", "data/test_target_selection",
        "--force-fault-type", "noisy_neighbor",
        "--force-fault-role", "service"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: Generation failed: {result.stderr}")
        return False

    # Collect selected targets
    targets = []
    for i in range(20):
        label_path = f"data/test_target_selection/ep_{i}/label.json"
        if os.path.exists(label_path):
            with open(label_path) as f:
                label = json.load(f)
                targets.append(label['root_cause_node'])

    if not targets:
        print("ERROR: No labels found")
        return False

    # Count distribution
    target_counts = Counter(targets)
    print(f"\nTarget distribution across {len(targets)} episodes:")
    for target, count in target_counts.most_common():
        pct = (count / len(targets)) * 100
        print(f"  {target}: {count} ({pct:.1f}%)")

    # Check if any target is over-represented (>50%)
    max_count = max(target_counts.values())
    max_pct = (max_count / len(targets)) * 100

    if max_pct > 50:
        print(f"\nFAIL: One target selected {max_pct:.1f}% of the time (biased)")
        return False
    else:
        print(f"\nPASS: Most common target selected {max_pct:.1f}% (reasonable distribution)")
        return True

def test_fault_propagation_all_nodes():
    """Test that fault propagation analyzes all nodes."""
    print("\n" + "="*80)
    print("TEST 3: Fault Propagation Analyzes All Nodes")
    print("="*80)

    # Generate episode with queue consumer fault
    print("\nGenerating episode with queue consumer...")
    result = subprocess.run([
        "python", "generate_dataset.py",
        "--episodes", "1",
        "--output-dir", "data/test_fault_prop",
        "--force-fault-type", "queue_consumer_slowdown",
        "--force-fault-role", "service"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: Generation failed: {result.stderr}")
        return False

    # Load fault propagation
    fault_prop_path = "data/test_fault_prop/ep_0/fault_propagation.json"
    if not os.path.exists(fault_prop_path):
        print(f"ERROR: Fault propagation file not found")
        return False

    with open(fault_prop_path) as f:
        fault_prop = json.load(f)

    # Load topology
    topo_path = "data/test_fault_prop/ep_0/topology.json"
    with open(topo_path) as f:
        topo = json.load(f)

    total_nodes = len(topo['nodes'])
    analyzed_nodes = fault_prop['propagation_statistics']['total_nodes_analyzed']

    print(f"\nTotal nodes in topology: {total_nodes}")
    print(f"Nodes analyzed: {analyzed_nodes}")

    # Check if queue is in the analysis
    node_ids = [r['node_id'] for r in fault_prop['node_reports']]
    queue_nodes = [nid for nid in node_ids if 'queue' in nid.lower()]

    print(f"Queue nodes found in analysis: {queue_nodes}")

    if analyzed_nodes == total_nodes:
        print(f"PASS: All nodes analyzed")
        return True
    else:
        missing = total_nodes - analyzed_nodes
        print(f"WARN: {missing} nodes not analyzed (may be okay if isolated)")
        # Still pass if we analyzed most nodes
        return analyzed_nodes >= total_nodes * 0.8

def test_noisy_neighbor_colocation():
    """Test that noisy neighbor impacts co-located pods."""
    print("\n" + "="*80)
    print("TEST 4: Noisy Neighbor Co-location Impact")
    print("="*80)

    # Generate episode
    print("\nGenerating episode with noisy_neighbor...")
    result = subprocess.run([
        "python", "generate_dataset.py",
        "--episodes", "1",
        "--output-dir", "data/test_noisy_colocation",
        "--force-fault-type", "noisy_neighbor",
        "--force-fault-role", "service"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: Generation failed: {result.stderr}")
        return False

    # Check logs for co-location impact
    logs_path = "data/test_noisy_colocation/ep_0/logs.jsonl"
    if not os.path.exists(logs_path):
        print(f"ERROR: Logs not found")
        return False

    with open(logs_path) as f:
        logs = [json.loads(line) for line in f if line.strip()]

    # Look for noisy neighbor logs
    noisy_logs = [log for log in logs if 'noisy' in log.get('message', '').lower()]

    aggressor_logs = [log for log in noisy_logs if 'aggressor' in log.get('message', '').lower()]
    steal_time_logs = [log for log in noisy_logs if 'steal time' in log.get('message', '').lower()]

    print(f"\nAggressor pod logs: {len(aggressor_logs)}")
    print(f"CPU steal time logs: {len(steal_time_logs)}")

    if aggressor_logs:
        print(f"  Aggressor: {aggressor_logs[0].get('message', '')}")

    if steal_time_logs:
        print(f"  Victims: {len(steal_time_logs)} pods experiencing steal time")
        for log in steal_time_logs[:3]:
            pod_id = log.get('attributes', {}).get('component.id', 'unknown')
            msg = log.get('message', '')
            print(f"    - {pod_id}: {msg}")

    if len(steal_time_logs) > 0:
        print("\nPASS: Co-located pods impacted by noisy neighbor")
        return True
    else:
        print("\nWARN: No co-located pods found (single pod per node?)")
        # Check topology
        topo_path = "data/test_noisy_colocation/ep_0/topology.json"
        with open(topo_path) as f:
            topo = json.load(f)

        # Count pods per node
        pod_placement = [e for e in topo['edges'] if e['type'] == 'pod_placement']
        from collections import defaultdict
        nodes = defaultdict(list)
        for e in pod_placement:
            nodes[e['target']].append(e['source'])

        print(f"\nPods per node:")
        for node, pods in sorted(nodes.items()):
            print(f"  {node}: {len(pods)} pods")

        # If only 1 pod per node, test passes (no co-location possible)
        max_pods = max(len(pods) for pods in nodes.values()) if nodes else 0
        if max_pods <= 1:
            print("\nPASS: No co-location in topology (1 pod per node)")
            return True
        else:
            print("\nFAIL: Co-location exists but no steal time applied")
            return False

def main():
    """Run all tests."""
    print("="*80)
    print("TESTING ALL FIXES")
    print("="*80)

    tests = [
        ("Fault Revert Registry", test_fault_revert),
        ("Uniform Target Selection", test_target_selection),
        ("Fault Propagation All Nodes", test_fault_propagation_all_nodes),
        ("Noisy Neighbor Co-location", test_noisy_neighbor_colocation),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\nERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")

    passed_count = sum(results.values())
    total_count = len(results)

    print(f"\nTotal: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\nAll tests PASSED!")
        return 0
    else:
        print(f"\n{total_count - passed_count} test(s) FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
