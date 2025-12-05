#!/usr/bin/env python3
"""
Fast Fault Index Generator (using pre-computed metadata).

This script generates a topology-fault compatibility index using PRE-COMPUTED
fault targets and propagation predictions from the topology bank.

This is MUCH faster than generate_fault_index.py since it just loads existing
JSON files instead of calling LLMs.

Usage:
    python generate_fault_index_fast.py --topology-bank data/topology_bank --output data/fault_index.json

Requirements:
    - Topology bank must have been generated with --precompute-faults flag
    - Each topology directory must contain fault_targets.json
"""
import argparse
import json
import os
import glob
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Generate fault index from pre-computed metadata')
    parser.add_argument(
        '--topology-bank',
        type=str,
        required=True,
        help='Directory containing topology bank with pre-computed metadata'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/fault_index.json',
        help='Output path for the fault index JSON'
    )

    args = parser.parse_args()

    # Validate topology bank exists
    if not os.path.exists(args.topology_bank):
        print(f"Error: Topology bank directory not found: {args.topology_bank}")
        return 1

    # Find all topology directories
    topology_dirs = [d for d in glob.glob(f"{args.topology_bank}/*")
                     if os.path.isdir(d)]

    if not topology_dirs:
        print(f"Error: No topology directories found in {args.topology_bank}")
        return 1

    print(f"Found {len(topology_dirs)} topologies in {args.topology_bank}")
    print(f"Loading pre-computed fault metadata...")
    print()

    # Initialize fault index
    fault_index = {}

    # Count stats
    total_topologies = len(topology_dirs)
    topologies_with_metadata = 0
    topologies_without_metadata = 0

    for topo_dir in topology_dirs:
        topology_id = os.path.basename(topo_dir)
        fault_targets_file = os.path.join(topo_dir, 'fault_targets.json')

        # Check if this topology has pre-computed metadata
        if not os.path.exists(fault_targets_file):
            topologies_without_metadata += 1
            print(f"⚠ {topology_id}: No fault_targets.json found (skipping)")
            continue

        topologies_with_metadata += 1

        # Load pre-computed fault targets
        with open(fault_targets_file, 'r') as f:
            fault_targets = json.load(f)

        # Load semantic map for domain info
        semantic_map_file = os.path.join(topo_dir, 'semantic_map.json')
        domain = 'Unknown'
        if os.path.exists(semantic_map_file):
            with open(semantic_map_file, 'r') as f:
                semantic_map = json.load(f)
                domain = semantic_map.get('domain', 'Unknown')

        # Add to index
        for fault_key, candidates in fault_targets.items():
            if fault_key not in fault_index:
                fault_index[fault_key] = []

            fault_index[fault_key].append({
                'topology_id': topology_id,
                'topology_path': topo_dir,
                'domain': domain,
                'candidates': candidates,
                'num_candidates': len(candidates)
            })

    # Save index
    with open(args.output, 'w') as f:
        json.dump(fault_index, f, indent=2)

    print()
    print("="*60)
    print("FAULT INDEX GENERATION COMPLETE")
    print("="*60)
    print(f"Topologies processed: {total_topologies}")
    print(f"  - With metadata: {topologies_with_metadata}")
    print(f"  - Without metadata: {topologies_without_metadata}")
    print(f"Fault type-role combinations: {len(fault_index)}")
    print(f"Index saved to: {args.output}")
    print()

    # Print summary statistics
    print("="*60)
    print("COVERAGE SUMMARY")
    print("="*60)

    # Count total combinations
    total_combinations = sum(len(topos) for topos in fault_index.values())
    print(f"Total fault-topology combinations: {total_combinations}")
    print()

    # Show distribution
    well_covered = []
    moderately_covered = []
    poorly_covered = []

    for fault_key, compatible_topos in sorted(fault_index.items()):
        count = len(compatible_topos)
        if count >= 10:
            well_covered.append((fault_key, count))
        elif count >= 5:
            moderately_covered.append((fault_key, count))
        else:
            poorly_covered.append((fault_key, count))

    if well_covered:
        print("✓ Well-covered (>=10 topologies):")
        for fault_key, count in sorted(well_covered, key=lambda x: -x[1])[:10]:
            print(f"  {fault_key:40s} : {count:3d} topologies")

    if moderately_covered:
        print()
        print("~ Moderately-covered (5-9 topologies):")
        for fault_key, count in sorted(moderately_covered, key=lambda x: -x[1])[:10]:
            print(f"  {fault_key:40s} : {count:3d} topologies")

    if poorly_covered:
        print()
        print("⚠ Under-represented (<5 topologies):")
        for fault_key, count in sorted(poorly_covered, key=lambda x: x[1])[:10]:
            print(f"  {fault_key:40s} : {count:3d} topologies")

    print()
    print("="*60)

    if topologies_without_metadata > 0:
        print()
        print("⚠ WARNING:")
        print(f"  {topologies_without_metadata} topologies don't have pre-computed metadata")
        print("  To generate metadata, run:")
        print(f"    python generate_topology_bank.py --precompute-faults")
        print()

    return 0


if __name__ == '__main__':
    exit(main())
