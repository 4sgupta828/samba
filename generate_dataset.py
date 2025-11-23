#!/usr/bin/env python3
"""
Training Data Factory - Generate infinite procedural training episodes.

This script orchestrates the generation of diverse, labeled microservice
topology failures for training Graph Neural Networks (GNNs).

Usage:
    python generate_dataset.py --episodes 100 --output data/train
"""
import simpy
import random
import os
import json
import yaml
import tempfile
import argparse
from pathlib import Path

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.topology.generator import TopologyGenerator
from src.topology.adapter import TopologyAdapter, print_topology_summary
from src.scenarios.library import ScenarioLibrary
from src.simulation import Simulation
from src.failures.training_injector import TrainingFailureInjector
import networkx as nx


def create_dynamic_workload(nx_graph, base_rps: int = 80, peak_rps: int = 200):
    """
    Create a workload configuration that targets the specific frontend services
    in this random topology.

    Args:
        nx_graph: NetworkX graph with topology
        base_rps: Base requests per second
        peak_rps: Peak requests per second

    Returns:
        Path to temporary workload YAML file
    """
    # Find nodes tagged as frontends
    frontends = [n for n, d in nx_graph.nodes(data=True) if d.get('is_frontend')]

    if not frontends:
        # Fallback: pick any service if no frontends tagged
        frontends = [n for n, d in nx_graph.nodes(data=True) if d.get('role') == 'service']

    if not frontends:
        raise ValueError("No services found in topology!")

    # Distribute traffic evenly across frontends
    weight = int(100 / len(frontends))

    request_mix = []
    for svc in frontends:
        # Gateway is configured to route by request type
        # We use 'GET' as a generic type
        request_mix.append({
            'type': 'GET',
            'service': svc,
            'weight': weight
        })

    workload_config = {
        'name': 'Dynamic Random Workload',
        'pattern': 'diurnal',  # Realistic daily traffic pattern
        'baseline_rps': base_rps,  # Baseline requests per second
        'peak_rps': peak_rps,  # Peak requests per second
        'request_mix': request_mix
    }

    # Save to temp file
    fd, path = tempfile.mkstemp(suffix='.yaml', text=True)
    with os.fdopen(fd, 'w') as f:
        yaml.dump(workload_config, f)

    return path


def serialize_topology_graph(nx_graph: nx.DiGraph) -> dict:
    """
    Serialize NetworkX graph to JSON-friendly format for GNN training.

    Args:
        nx_graph: NetworkX directed graph with node and edge attributes

    Returns:
        Dictionary with nodes and edges arrays suitable for GNN input
    """
    # Extract nodes with all attributes
    nodes = []
    for node_id, attrs in nx_graph.nodes(data=True):
        node_data = {'id': node_id}
        node_data.update(attrs)
        nodes.append(node_data)

    # Extract edges with all attributes
    edges = []
    for source, target, attrs in nx_graph.edges(data=True):
        edge_data = {
            'source': source,
            'target': target
        }
        edge_data.update(attrs)
        edges.append(edge_data)

    return {
        'nodes': nodes,
        'edges': edges,
        'num_nodes': len(nodes),
        'num_edges': len(edges),
        'is_directed': nx_graph.is_directed()
    }


def generate_episode(episode_id: int, output_dir: str, scenario_lib: ScenarioLibrary, verbose: bool = False, topology_size: int = None):
    """
    Generate a single training episode.

    Args:
        episode_id: Unique episode identifier
        output_dir: Base output directory
        scenario_lib: Scenario library instance
        verbose: Print detailed progress
        topology_size: Optional override for topology size (number of nodes)

    Returns:
        Dictionary with episode metadata
    """
    # 1. Generate Topology first to see what node types are available
    # Override topology size if specified
    actual_topology_size = topology_size if topology_size is not None else None

    # If topology_size is specified, generate topology first to determine available node types
    if actual_topology_size is not None:
        topo_gen = TopologyGenerator(seed=episode_id)
        nx_graph = topo_gen.generate_complex_graph(actual_topology_size)

        # Get available node roles
        available_roles = set(data.get('role') for _, data in nx_graph.nodes(data=True))

        # Try to find a compatible scenario (max 10 attempts)
        cfg = None
        for attempt in range(10):
            level = scenario_lib.sample_level(seed=episode_id + attempt)
            temp_cfg = scenario_lib.get_episode(level, seed=episode_id + attempt)
            temp_cfg.topology_size = actual_topology_size

            # Check if this scenario's target role exists in the topology
            if temp_cfg.fault_target_role in available_roles:
                cfg = temp_cfg
                break

        if cfg is None:
            print(f"Warning: Could not find compatible scenario for topology with roles {available_roles}, skipping episode {episode_id}")
            return None
    else:
        # Normal flow: select scenario first, then generate topology
        level = scenario_lib.sample_level(seed=episode_id)
        cfg = scenario_lib.get_episode(level, seed=episode_id)

        # 2. Generate Topology
        topo_gen = TopologyGenerator(seed=episode_id)
        nx_graph = topo_gen.generate_complex_graph(cfg.topology_size)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Episode {episode_id} [Level {level}]")
        print(f"  Scenario: {cfg.description}")
        print(f"  Topology: {cfg.topology_size} nodes")
        print(f"  Duration: {cfg.duration}s")
        print(f"  Fault: {cfg.fault_type} on {cfg.fault_target_role}")
        print(f"{'='*60}")
        print_topology_summary(nx_graph)

    # 3. Create Dynamic Workload
    workload_path = create_dynamic_workload(nx_graph)

    # 4. Configure Simulation
    episode_dir = os.path.join(output_dir, f'ep_{episode_id}')
    os.makedirs(episode_dir, exist_ok=True)

    sim_config = {
        'simulation': {
            'duration': cfg.duration,
            'output_dir': episode_dir
        },
        'telemetry': {
            'metric_export_interval': cfg.export_interval,
            'exporter_type': 'file'
        },
        'workload': {
            'path': workload_path
        },
        'infrastructure': {
            'path': 'generated_internal'  # Placeholder (bypassing IaC parsing)
        }
    }

    # 5. Initialize Simulation (bypass IaC parsing)
    sim = Simulation(sim_config)

    # 6. Setup Simulation Environment using Simulation's env (CRITICAL FIX!)
    adapter = TopologyAdapter(sim.env)
    registry = adapter.graph_to_registry(nx_graph)
    sim.component_registry = registry  # Directly set registry

    # Initialize simulation timestamp (normally done in sim.run())
    import time
    now_ns = int(time.time() * 1_000_000_000)
    duration_ns = int(cfg.duration * 1_000_000_000)
    sim.simulation_start_timestamp_ns = now_ns - duration_ns

    # 7. Inject Fault Programmatically (GRADUAL APPLICATION)
    valid_targets = [
        nid for nid, data in nx_graph.nodes(data=True)
        if data.get('role') == cfg.fault_target_role
    ]

    # This should never happen now since we pre-validate scenarios
    if not valid_targets:
        raise ValueError(f"Internal error: No valid targets for role '{cfg.fault_target_role}' in episode {episode_id}")

    target_id = random.choice(valid_targets)

    # Calculate gradual failure timeline:
    # - Start at 20% through episode (earlier than before to see healthy baseline)
    # - Apply gradually over 40% of episode duration
    # - Reach full effect at 60%, remains until end
    start_time = int(cfg.duration * 0.2)
    ramp_duration = int(cfg.duration * 0.4)

    if verbose:
        print(f"\n[Fault Injection - GRADUAL]")
        print(f"  Target: {target_id}")
        print(f"  Start: {start_time}s (20% through episode)")
        print(f"  Ramp: {ramp_duration}s (applies gradually)")
        print(f"  Full effect at: {start_time + ramp_duration}s (60% through)")

    # Initialize new training-focused injector
    injector = TrainingFailureInjector(
        sim.env,
        registry,
        sim.tracker,
        simulation_start_timestamp_ns=sim.simulation_start_timestamp_ns
    )

    # Configure failure parameters based on type
    params = cfg.get_failure_params()

    # Schedule GRADUAL fault injection
    injector.inject_gradual_failure(
        target_id=target_id,
        failure_mode=cfg.fault_type,
        start_time=start_time,
        duration=ramp_duration,
        params=params,
        progression=cfg.progression,
        episode_id=f'ep{episode_id}_fault'
    )

    # 8. Save Ground Truth Label (WITH PROGRESSION INFO)
    label = {
        'episode': episode_id,
        'level': level,
        'scenario': cfg.description,
        'root_cause_node': target_id,
        'root_cause_role': cfg.fault_target_role,
        'fault_type': cfg.fault_type,
        'fault_start_time': start_time,
        'fault_ramp_duration': ramp_duration,
        'fault_full_effect_time': start_time + ramp_duration,
        'fault_total_duration': cfg.duration - start_time,
        'progression': {
            'type': cfg.progression,
            'description': f'{cfg.progression} progression over {ramp_duration}s',
            'timeline': {
                'healthy_baseline': f'0s - {start_time}s',
                'degradation_ramp': f'{start_time}s - {start_time + ramp_duration}s',
                'full_failure': f'{start_time + ramp_duration}s - {cfg.duration}s'
            }
        },
        'fault_params': params,
        'topology': {
            'nodes': len(nx_graph.nodes),
            'edges': len(nx_graph.edges),
            'frontends': [n for n, d in nx_graph.nodes(data=True) if d.get('is_frontend')]
        }
    }

    label_path = os.path.join(episode_dir, 'label.json')
    with open(label_path, 'w') as f:
        json.dump(label, f, indent=2)

    # Save complete topology graph for GNN training
    topology_data = serialize_topology_graph(nx_graph)
    topology_path = os.path.join(episode_dir, 'topology.json')
    with open(topology_path, 'w') as f:
        json.dump(topology_data, f, indent=2)

    if verbose:
        print(f"\n[Ground Truth]")
        print(f"  Label saved to: {label_path}")
        print(f"  Topology saved to: {topology_path}")
        print(f"  Topology: {topology_data['num_nodes']} nodes, {topology_data['num_edges']} edges")

    # 9. Run Simulation
    try:
        if verbose:
            print(f"\n[Simulation]")
            print(f"  Running for {cfg.duration}s...")

        sim.run()

        if verbose:
            print(f"  Completed successfully")
            print(f"  Output directory: {episode_dir}")

    except Exception as e:
        print(f"Error in episode {episode_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        # Cleanup temp workload file
        if os.path.exists(workload_path):
            os.remove(workload_path)

    return {
        'episode_id': episode_id,
        'level': level,
        'output_dir': episode_dir,
        'root_cause': target_id,
        'fault_type': cfg.fault_type
    }


def generate_dataset(num_episodes: int, output_dir: str, verbose: bool = False, topology_size: int = None):
    """
    Generate a full training dataset with multiple episodes.

    Args:
        num_episodes: Number of episodes to generate
        output_dir: Base output directory (e.g., 'data')
        verbose: Print detailed progress
        topology_size: Optional override for topology size (number of nodes)
    """
    print(f"\n{'='*60}")
    print(f"SPATIOTEMPORAL DATA FACTORY")
    print(f"{'='*60}")
    print(f"Generating {num_episodes} training episodes...")
    print(f"Base output directory: {output_dir}")
    print(f"{'='*60}\n")

    # Create timestamped run directory: data/data_YYYYMMDD_HHMMSS
    from datetime import datetime
    run_id = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(output_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    print(f"Run directory: {run_dir}\n")

    # Initialize scenario library
    lib = ScenarioLibrary()

    # Generate episodes under the run directory
    results = []
    for i in range(num_episodes):
        result = generate_episode(i, run_dir, lib, verbose=verbose, topology_size=topology_size)
        if result:
            results.append(result)

        if not verbose and (i + 1) % 10 == 0:
            print(f"Progress: {i + 1}/{num_episodes} episodes completed")

    # Save dataset metadata
    metadata = {
        'run_id': run_id,
        'num_episodes': len(results),
        'curriculum_distribution': lib.get_curriculum_distribution(),
        'episodes': results
    }

    metadata_path = os.path.join(run_dir, 'dataset_metadata.json')
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"  Run ID: {run_id}")
    print(f"  Total episodes: {len(results)}")
    print(f"  Metadata: {metadata_path}")
    print(f"{'='*60}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate training data for GNN root cause analysis",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-n', '--episodes',
        type=int,
        default=10,
        help='Number of episodes to generate'
    )
    parser.add_argument(
        '-o', '--output',
        default='data',
        help='Base output directory for dataset (run directory will be created inside)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed progress for each episode'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=None,
        help='Random seed for reproducibility'
    )
    parser.add_argument(
        '-t', '--topology-size',
        type=int,
        default=None,
        help='Override topology size (number of nodes). Use small values like 2-3 for simple scenarios.'
    )

    args = parser.parse_args()

    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)

    # Generate dataset
    generate_dataset(
        num_episodes=args.episodes,
        output_dir=args.output,
        verbose=args.verbose,
        topology_size=args.topology_size
    )


if __name__ == "__main__":
    main()
