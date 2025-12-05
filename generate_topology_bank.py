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
from src.failures.llm_target_selector import LLMFaultTargetSelector
from src.failures.llm_propagation_predictor import LLMFaultPropagationPredictor
from src.scenarios.library import ScenarioLibrary


def precompute_fault_metadata(G: nx.DiGraph, topology_path: str, top_k: int = 3):
    """
    Pre-compute fault targets and propagation predictions for all fault types.

    This is expensive (many LLM calls) but only needs to be done once per topology.
    Results are cached and can be loaded during dataset generation.

    Args:
        G: NetworkX graph of the topology
        topology_path: Path to save pre-computed metadata
        top_k: Number of top targets to compute per fault type
    """
    print(f"      🔮 Pre-computing fault metadata...")

    # Initialize LLM tools
    target_selector = LLMFaultTargetSelector()
    propagation_predictor = LLMFaultPropagationPredictor()

    # Get all unique (fault_type, fault_target_role) pairs from scenario library
    scenario_lib = ScenarioLibrary()
    fault_type_role_pairs = set()
    for level in [1, 2, 3, 4]:
        for scenario in scenario_lib.levels[level]:
            fault_type_role_pairs.add((scenario.fault_type, scenario.fault_target_role))

    # Initialize storage
    fault_targets = {}  # {fault_type:role -> [candidates]}
    propagation_predictions = {}  # {fault_type:role:target_id -> prediction}

    # Get available roles in this topology
    available_roles = set(data.get('role') for _, data in G.nodes(data=True))

    print(f"         Available roles: {available_roles}")
    print(f"         Computing for {len(fault_type_role_pairs)} fault type-role combinations...")

    computed_count = 0
    skipped_count = 0

    for fault_type, fault_target_role in sorted(fault_type_role_pairs):
        fault_key = f"{fault_type}:{fault_target_role}"

        # Skip if this topology doesn't have the required role
        # Exception: network_partition works on any topology
        if fault_type != 'network_partition' and fault_target_role not in available_roles:
            skipped_count += 1
            continue

        try:
            # 1. Select top-k fault targets
            candidates = target_selector.select_candidates(
                topology=G,
                fault_type=fault_type,
                fault_target_role=fault_target_role,
                top_k=top_k
            )

            if not candidates:
                skipped_count += 1
                continue

            fault_targets[fault_key] = candidates

            # 2. For each candidate, predict propagation
            for candidate in candidates:
                target_id = candidate['node_id']
                prediction_key = f"{fault_key}:{target_id}"

                # Get default fault params for this fault type
                from src.scenarios.library import EpisodeConfig
                dummy_cfg = EpisodeConfig(
                    level=1,
                    topology_size=len(G.nodes),
                    duration=300,
                    fault_type=fault_type,
                    fault_target_role=fault_target_role,
                    export_interval=5,
                    description="dummy"
                )
                fault_params = dummy_cfg.get_failure_params()

                # Predict propagation
                prediction = propagation_predictor.predict_propagation(
                    topology=G,
                    fault_node_id=target_id,
                    fault_type=fault_type,
                    fault_params=fault_params
                )

                propagation_predictions[prediction_key] = prediction

            computed_count += 1
            print(f"         ✓ {fault_key}: {len(candidates)} targets computed")

        except Exception as e:
            print(f"         ⚠ {fault_key}: Failed ({e})")
            skipped_count += 1
            continue

    # Save to disk
    fault_targets_path = os.path.join(topology_path, 'fault_targets.json')
    with open(fault_targets_path, 'w') as f:
        json.dump(fault_targets, f, indent=2)

    propagation_dir = os.path.join(topology_path, 'propagation_predictions')
    os.makedirs(propagation_dir, exist_ok=True)

    # Save each prediction as a separate file for easier loading
    for prediction_key, prediction in propagation_predictions.items():
        prediction_path = os.path.join(propagation_dir, f'{prediction_key}.json')
        with open(prediction_path, 'w') as f:
            json.dump(prediction, f, indent=2)

    print(f"      ✅ Pre-computed metadata saved:")
    print(f"         - Fault targets: {computed_count} fault types")
    print(f"         - Propagation predictions: {len(propagation_predictions)} predictions")
    print(f"         - Skipped: {skipped_count} (role not available)")


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
        default=3,
        help='Number of samples per scenario (default: 3)'
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
        default=3,
        help='Number of top fault targets to compute per fault type (default: 3)'
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

                # Save the semantic map (flows + descriptions)
                # We normalize this to the structure expected by CapacityPlanner
                semantic_map = {
                    "domain": topo_data.get('meta', {}).get('domain', 'unknown'),
                    "description": topo_data.get('meta', {}).get('description', ''),
                    "architecture_name": topo_data.get('meta', {}).get('architecture_name', ''),
                    "archetype": topo_data.get('meta', {}).get('archetype', archetype),
                    "pros": topo_data.get('meta', {}).get('pros', []),
                    "cons": topo_data.get('meta', {}).get('cons', []),
                    "request_flows": topo_data.get('flows', {}),
                    "services": {n['id']: n for n in topo_data['nodes']} # Quick lookup
                }
                with open(f"{path}/semantic_map.json", 'w') as f:
                    json.dump(semantic_map, f, indent=2)

                # Also save the raw LLM output for debugging
                with open(f"{path}/raw_llm_output.json", 'w') as f:
                    json.dump(topo_data, f, indent=2)

                # Pre-compute fault metadata if requested
                if args.precompute_faults:
                    try:
                        precompute_fault_metadata(G, path, top_k=args.top_k_targets)
                    except Exception as e:
                        print(f"      ⚠ Fault pre-computation failed: {e}")
                        print(f"      (Topology is still valid, but fault metadata not available)")

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
