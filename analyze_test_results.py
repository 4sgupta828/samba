#!/usr/bin/env python3
"""
Analyze the results from the fault combination test.
"""
import json
import os
import sys
from pathlib import Path

TEST_DIR = "/var/folders/tx/9fmxvdwn3nsbr4jtn4mh_sl40000gn/T/fault_test_zd5wcm13"

COMBINATIONS = [
    ('cpu_saturation', 'service'),
    ('cpu_saturation', 'database'),
    ('memory_leak', 'service'),
    ('memory_pressure', 'service'),
    ('memory_thrashing', 'service'),
    ('inject_latency', 'service'),
    ('inject_latency', 'cache'),
    ('inject_latency', 'external'),
    ('disk_io_saturation', 'database'),
    ('thread_exhaustion', 'database'),
    ('thread_exhaustion', 'service'),
    ('cache_failure', 'cache'),
    ('inject_errors', 'external'),
    ('queue_consumer_slowdown', 'queue'),
    ('hot_shard', 'service'),
    ('noisy_neighbor', 'service'),
    ('network_partition', 'network'),
    # force_deadlock removed (2025-12-15) - use thread_exhaustion instead
]


def analyze_combination(fault_type, role):
    """Analyze a single combination."""
    combo_key = f"{fault_type}_{role}"
    combo_dir = os.path.join(TEST_DIR, combo_key)

    if not os.path.exists(combo_dir):
        return {
            'status': 'missing',
            'reason': 'directory not found'
        }

    # Find data directory
    data_dirs = [d for d in os.listdir(combo_dir) if d.startswith('data_')]
    if not data_dirs:
        return {
            'status': 'no_data',
            'reason': 'no data directory'
        }

    data_dir = os.path.join(combo_dir, data_dirs[0])

    # Check metadata
    metadata_file = os.path.join(data_dir, 'dataset_metadata.json')
    if not os.path.exists(metadata_file):
        return {
            'status': 'incomplete',
            'reason': 'no metadata'
        }

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    num_episodes = metadata.get('num_episodes', 0)

    if num_episodes == 0:
        return {
            'status': 'no_episodes',
            'reason': 'generation created 0 episodes',
            'metadata': metadata
        }

    # Analyze episodes
    episodes = []
    for ep_data in metadata.get('episodes', []):
        # Episodes can be dict or string
        if isinstance(ep_data, dict):
            ep_name = f"ep_{ep_data['episode_id']}"
        else:
            ep_name = ep_data

        ep_dir = os.path.join(data_dir, ep_name)
        if not os.path.exists(ep_dir):
            continue

        # Check for fault_propagation.json
        prop_file = os.path.join(ep_dir, 'fault_propagation.json')
        if not os.path.exists(prop_file):
            episodes.append({
                'episode': ep_name,
                'has_propagation_file': False,
                'propagation': None
            })
            continue

        with open(prop_file, 'r') as f:
            prop_data = json.load(f)

        # Analyze propagation
        node_reports = prop_data.get('node_reports', [])

        # Count impact levels
        impact_counts = {
            'CRITICAL': 0,
            'HIGH': 0,
            'MEDIUM': 0,
            'LOW': 0,
            'NEGLIGIBLE': 0
        }

        for nr in node_reports:
            severity = nr.get('overall_severity', 'UNKNOWN')
            if severity in impact_counts:
                impact_counts[severity] += 1

        # Check if root cause is in reports
        root_cause = prop_data.get('root_cause', {})
        root_id = root_cause.get('node_id')

        # Calculate meaningful propagation
        # Exclude root cause from affected count
        other_affected = sum(v for k, v in impact_counts.items() if k != 'NEGLIGIBLE')
        if root_id:
            # If root is counted, subtract 1
            other_affected = max(0, other_affected - 1)

        has_propagation = other_affected > 0

        episodes.append({
            'episode': ep_name,
            'has_propagation_file': True,
            'total_nodes': len(node_reports),
            'root_cause': root_id,
            'impact_counts': impact_counts,
            'other_affected': other_affected,
            'has_propagation': has_propagation
        })

    # Summary
    total_episodes = len(episodes)
    with_propagation = sum(1 for ep in episodes if ep.get('has_propagation', False))

    return {
        'status': 'success',
        'total_episodes': total_episodes,
        'episodes_with_propagation': with_propagation,
        'episodes': episodes
    }


def main():
    """Main analysis."""
    print("="*80)
    print("DETAILED ANALYSIS OF FAULT COMBINATION TEST RESULTS")
    print("="*80)
    print(f"\nTest directory: {TEST_DIR}\n")

    results = {}

    for fault_type, role in COMBINATIONS:
        combo_key = f"{fault_type}_{role}"
        print(f"\n{combo_key}:")
        print("-" * 40)

        result = analyze_combination(fault_type, role)
        results[combo_key] = {
            'fault_type': fault_type,
            'role': role,
            'result': result
        }

        print(f"  Status: {result['status']}")

        if result['status'] == 'success':
            print(f"  Episodes: {result['total_episodes']}")
            print(f"  With propagation: {result['episodes_with_propagation']}/{result['total_episodes']}")

            for ep in result['episodes']:
                ep_name = ep['episode']
                if ep.get('has_propagation_file'):
                    print(f"    {ep_name}:")
                    print(f"      Total nodes: {ep['total_nodes']}")
                    print(f"      Root cause: {ep['root_cause']}")
                    print(f"      Impact: {ep['impact_counts']}")
                    print(f"      Other affected: {ep['other_affected']}")
                    print(f"      Propagation: {'✓' if ep['has_propagation'] else '✗'}")
        else:
            print(f"  Reason: {result.get('reason', 'unknown')}")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    success = []
    no_propagation = []
    partial_propagation = []
    failed = []

    for combo_key, data in results.items():
        result = data['result']

        if result['status'] == 'success':
            total = result['total_episodes']
            with_prop = result['episodes_with_propagation']

            if with_prop == total and with_prop > 0:
                success.append(combo_key)
            elif with_prop == 0:
                no_propagation.append((combo_key, total))
            else:
                partial_propagation.append((combo_key, with_prop, total))
        else:
            failed.append((combo_key, result['status'], result.get('reason', 'unknown')))

    print(f"\n✓ Full propagation: {len(success)}/11")
    for combo in success:
        print(f"  - {combo}")

    print(f"\n⚠  Partial propagation: {len(partial_propagation)}/11")
    for combo, with_prop, total in partial_propagation:
        print(f"  - {combo}: {with_prop}/{total} episodes")

    print(f"\n✗ No propagation: {len(no_propagation)}/11")
    for combo, total in no_propagation:
        print(f"  - {combo} ({total} episodes generated)")

    print(f"\n✗ Failed: {len(failed)}/11")
    for combo, status, reason in failed:
        print(f"  - {combo}: {status} - {reason}")

    # Remediation suggestions
    print("\n" + "="*80)
    print("REMEDIATION SUGGESTIONS")
    print("="*80)

    if no_propagation:
        print("\n🔍 NO PROPAGATION DETECTED:")
        print("   These combinations generated episodes but faults didn't propagate beyond root cause.")
        print("   This is the MAIN ISSUE that needs investigation.\n")

        print("   Possible causes:")
        print("   1. Fault severity too low - increase fault parameters")
        print("   2. Fault duration too short - increase duration")
        print("   3. Topology isolation - root cause not well connected")
        print("   4. Workload too low - increase request rate to stress system")
        print("   5. Fault injection not working - check fault implementation\n")

        print("   Affected combinations:")
        for combo, total in no_propagation:
            parts = combo.split('_')
            if len(parts) >= 2:
                role = parts[-1]
                fault = '_'.join(parts[:-1])
                print(f"   - {fault} on {role}")

    if failed:
        print("\n🔍 FAILED GENERATION:")
        for combo, status, reason in failed:
            parts = combo.split('_')
            if len(parts) >= 2:
                role = parts[-1]
                fault = '_'.join(parts[:-1])
                print(f"   - {fault} on {role}: {reason}")

        print("\n   For 'no_episodes' failures:")
        print("     - Check if baseline health validation is too strict")
        print("     - Check if topology generation is failing for this role")
        print("     - Look at generate_dataset.py logs for error messages")

        print("\n   For timeout failures:")
        print("     - Simulation may be too long or complex")
        print("     - Check if fault causes infinite loops or deadlocks")
        print("     - Consider reducing topology size or duration")


if __name__ == '__main__':
    main()
