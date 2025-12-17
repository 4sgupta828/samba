#!/usr/bin/env python3
"""
Topology Bank Generator - Offline LLM-driven architecture generator.

This script uses Claude to design realistic distributed system architectures
with explicit intent, flows, and metadata. Generated topologies are validated
and saved to a bank for consumption by the simulation.

Usage:
    python generate_topology_bank.py --samples 3 --output data/topology_bank
"""
import os
import json
import argparse
import networkx as nx
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.topology.llm_generator import LLMTopologyGenerator


def main():
    parser = argparse.ArgumentParser(
        description='Generate a bank of LLM-architected topologies'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/topology_bank',
        help='Output directory for topology bank (default: data/topology_bank)'
    )
    parser.add_argument(
        '--samples',
        type=int,
        default=1,
        help='Number of samples per scenario (default: 1)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='claude-sonnet-4-20250514',
        help='Claude model to use (default: claude-sonnet-4-20250514)'
    )
    parser.add_argument(
        '--precompute-faults',
        action='store_true',
        default=False,
        help='Pre-compute fault targets and propagation predictions for all fault types (slow but enables fast dataset generation)'
    )
    parser.add_argument(
        '--top-k-targets',
        type=int,
        default=1,
        help='Number of top fault targets to compute per fault type (default: 1)'
    )
    parser.add_argument(
        '--skip-propagation',
        action='store_true',
        default=True,
        help='Skip propagation prediction (only compute fault targets, much faster)'
    )

    args = parser.parse_args()

    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    print(f"🏗️  Initializing LLM Topology Generator (model: {args.model})")
    generator = LLMTopologyGenerator(model=args.model) # Ensure API key env var is set

    # Matrix of scenarios to generate
    # This guarantees diversity of structure
    # Note: Only using medium scale as large topologies often fail validation
    scenarios = [
        ("hierarchical", "medium"),
        ("mesh", "medium"),
        ("pipeline", "medium"),
        ("hub_spoke", "medium")
    ]

    # Generate multiple samples per scenario
    samples_per_scenario = args.samples

    total = len(scenarios) * samples_per_scenario
    count = 0
    successful = 0
    failed = 0

    print(f"\n📊 Generating {total} topologies ({len(scenarios)} scenarios × {samples_per_scenario} samples)")
    print("=" * 80)

    for archetype, scale in scenarios:
        for i in range(samples_per_scenario):
            count += 1
            print(f"\n[{count}/{total}] 🏛️  Architecting {archetype} ({scale})...")

            try:
                # 1. Generate (includes validation)
                topo_data = generator.generate_architecture(archetype, scale)

                # 2. Convert to graph for serialization check
                G = generator.convert_to_simulation_graph(topo_data)
                graph_json = nx.node_link_data(G)

                # 3. Save
                slug = f"{archetype}_{scale}_{i}"
                path = os.path.join(output_dir, slug)
                os.makedirs(path, exist_ok=True)

                # Save the graph structure used by simulation
                with open(f"{path}/graph.json", 'w') as f:
                    json.dump(graph_json, f, indent=2)

                # Save the semantic map (flows + descriptions + topology analysis)
                # We normalize this to the structure expected by CapacityPlanner
                semantic_map = {
                    "domain": topo_data.get('meta', {}).get('domain', 'unknown'),
                    "description": topo_data.get('meta', {}).get('description', ''),
                    "architecture_name": topo_data.get('meta', {}).get('architecture_name', ''),
                    "archetype": topo_data.get('meta', {}).get('archetype', archetype),
                    "pros": topo_data.get('meta', {}).get('pros', []),
                    "cons": topo_data.get('meta', {}).get('cons', []),
                    "request_flows": topo_data.get('flows', {}),
                    "services": {n['id']: n for n in topo_data['nodes']}, # Quick lookup
                    "topology_analysis": topo_data.get('topology_analysis', {}) # NEW: Pre-analysis for RCA
                }
                with open(f"{path}/semantic_map.json", 'w') as f:
                    json.dump(semantic_map, f, indent=2)

                # Also save the raw LLM output for debugging
                with open(f"{path}/raw_llm_output.json", 'w') as f:
                    json.dump(topo_data, f, indent=2)

                successful += 1
                print(f"   ✅ Saved to {path}")
                print(f"   📝 {len(G.nodes)} nodes, {len(G.edges)} edges")
                print(f"   🔄 {len(topo_data.get('flows', {}))} request flow types defined")

            except Exception as e:
                failed += 1
                print(f"   ❌ FAILED: {e}")

    print("\n" + "=" * 80)
    print(f"✅ Successfully generated: {successful}/{total}")
    print(f"❌ Failed: {failed}/{total}")
    print(f"📁 Topology bank saved to: {output_dir}")


if __name__ == "__main__":
    main()
