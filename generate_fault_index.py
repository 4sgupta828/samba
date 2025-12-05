#!/usr/bin/env python3
"""
Generate Topology-Fault Compatibility Index.

This script analyzes a topology bank and creates an index mapping:
- fault_type:fault_target_role -> list of compatible topologies with ranked candidates

This index enables:
1. Quick lookup of topologies that support specific fault types
2. Intelligent fault target selection (using LLM reasoning)
3. Dataset balancing across fault types and topologies

Usage:
    python generate_fault_index.py --topology-bank data/topology_bank --output data/fault_index.json

Example output structure:
{
  "cpu_saturation:service": [
    {
      "topology_id": "hierarchical_banking_0",
      "topology_file": "data/topology_bank/hierarchical_banking_0.json",
      "domain": "Banking System",
      "candidates": [
        {
          "node_id": "payment_service",
          "score": 0.95,
          "reasoning": "Central service with high fan-out...",
          "impact_radius": {...}
        }
      ]
    }
  ],
  "slow_queries:database": [...]
}
"""
import argparse
import json
import os
from src.failures.llm_target_selector import LLMFaultTargetSelector


def main():
    parser = argparse.ArgumentParser(description='Generate topology-fault compatibility index')
    parser.add_argument(
        '--topology-bank',
        type=str,
        required=True,
        help='Directory containing topology JSON files'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/fault_index.json',
        help='Output path for the fault index JSON'
    )
    parser.add_argument(
        '--top-k',
        type=int,
        default=3,
        help='Number of top candidates per topology (default: 3)'
    )

    args = parser.parse_args()

    # Validate topology bank exists
    if not os.path.exists(args.topology_bank):
        print(f"Error: Topology bank directory not found: {args.topology_bank}")
        return 1

    # Count topology files
    topology_files = [f for f in os.listdir(args.topology_bank) if f.endswith('.json')]
    if not topology_files:
        print(f"Error: No topology JSON files found in {args.topology_bank}")
        return 1

    print(f"Found {len(topology_files)} topology files in {args.topology_bank}")
    print(f"Generating fault index with top-{args.top_k} candidates per topology...")
    print()

    # Initialize LLM target selector
    selector = LLMFaultTargetSelector()

    # Generate index (this will call LLM for each topology-fault combination)
    fault_index = selector.generate_topology_fault_index(
        topology_bank_dir=args.topology_bank,
        output_path=args.output
    )

    # Print summary statistics
    print("\n" + "="*60)
    print("FAULT INDEX SUMMARY")
    print("="*60)

    total_combinations = 0
    for fault_key, compatible_topos in fault_index.items():
        total_combinations += len(compatible_topos)
        if compatible_topos:
            print(f"{fault_key:40s} : {len(compatible_topos):3d} topologies")

    print("="*60)
    print(f"Total fault-topology combinations: {total_combinations}")
    print(f"Index saved to: {args.output}")

    # Identify under-represented fault types
    print("\n" + "="*60)
    print("COVERAGE ANALYSIS")
    print("="*60)

    well_covered = []
    poorly_covered = []

    for fault_key, compatible_topos in fault_index.items():
        if len(compatible_topos) >= 10:
            well_covered.append((fault_key, len(compatible_topos)))
        elif len(compatible_topos) < 5:
            poorly_covered.append((fault_key, len(compatible_topos)))

    if well_covered:
        print("\n✓ Well-covered fault types (>=10 topologies):")
        for fault_key, count in sorted(well_covered, key=lambda x: -x[1]):
            print(f"  {fault_key:40s} : {count}")

    if poorly_covered:
        print("\n⚠ Under-represented fault types (<5 topologies):")
        for fault_key, count in sorted(poorly_covered, key=lambda x: x[1]):
            print(f"  {fault_key:40s} : {count}")
        print("\nConsider generating more topologies with these component roles:")
        under_rep_roles = set(fault_key.split(':')[1] for fault_key, _ in poorly_covered)
        for role in under_rep_roles:
            print(f"  - {role}")

    return 0


if __name__ == '__main__':
    exit(main())
