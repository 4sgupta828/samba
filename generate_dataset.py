#!/usr/bin/env python3
"""
Dataset generator - orchestrates labeled microservice simulation episodes.

Produces diverse topologies, faults, metrics, logs, traces, and ground truth
for the Dataraft simulator and whitebox RCA / dashboard workflows.

Usage:
    python generate_dataset.py -n 100 -o data/train
"""
import simpy
import random
import os
import json
import yaml
import tempfile
import argparse
from pathlib import Path
from multiprocessing import Process

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'analysis2'))

from src.topology.generator import TopologyGenerator
from src.topology.adapter import TopologyAdapter, print_topology_summary
from src.topology.semantic_mapper import SemanticMapper
from src.scenarios.library import ScenarioLibrary, EpisodeConfig
from src.simulation import Simulation
from src.failures.training_injector import TrainingFailureInjector
from src.failures.fault_tuner import FaultParameterTuner
from src.workloads.tuner import WorkloadTuner
from src.telemetry.topology_state_exporter import TopologyStateExporter
from src.components.service import Service
from src.components.pod import Pod
from src.components.compute_node import ComputeNode
from src.components.deployment_controller import DeploymentController
from analysis.propagation_analyzer import analyze_episode
from llm_analysis import create_llm_provider, SimulationAnalyzer, save_analysis_results
from validate_baseline_health import validate_episode_health
from src.validation.health_validator import validate_system_health
from src.core.capacity_planner import CapacityPlanner
import networkx as nx

# Whitebox RCA imports
try:
    from run_rca_batch import DatasetAdapter
    from whitebox_rca import WhiteboxRCAEngine
    WHITEBOX_RCA_AVAILABLE = True
except ImportError:
    WHITEBOX_RCA_AVAILABLE = False
    print("Warning: Whitebox RCA not available (analysis2 folder not found)")


def load_random_template(bank_dir: str = "data/topology_bank", topology_name: str = None) -> tuple:
    """
    Load a random LLM-generated topology from the topology bank.

    Args:
        bank_dir: Directory containing topology bank
        topology_name: Optional specific topology name to load (if None, picks randomly)

    Returns:
        Tuple of (nx_graph, semantic_map, chosen_topology_name)
    """
    if not os.path.exists(bank_dir):
        raise ValueError(f"Topology bank not found at {bank_dir}. Run generate_topology_bank.py first.")

    # Get all topology directories
    topology_dirs = [d for d in os.listdir(bank_dir)
                    if os.path.isdir(os.path.join(bank_dir, d))]

    if not topology_dirs:
        raise ValueError(f"No topologies found in {bank_dir}")

    # Pick topology
    if topology_name:
        if topology_name not in topology_dirs:
            raise ValueError(f"Topology '{topology_name}' not found in {bank_dir}. Available: {', '.join(topology_dirs)}")
        chosen = topology_name
    else:
        chosen = random.choice(topology_dirs)

    topo_path = os.path.join(bank_dir, chosen)

    # Load graph
    graph_path = os.path.join(topo_path, 'graph.json')
    with open(graph_path, 'r') as f:
        graph_data = json.load(f)
    nx_graph = nx.node_link_graph(graph_data)

    # Load semantic map
    semantic_path = os.path.join(topo_path, 'semantic_map.json')
    with open(semantic_path, 'r') as f:
        semantic_map = json.load(f)

    return nx_graph, semantic_map, chosen


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

    # Create request mix with realistic HTTP method distribution
    # Each frontend service handles ALL request types with typical traffic patterns:
    # - GET (read): 60% (most common - browsing, listing, retrieving data)
    # - POST (create): 25% (creating new resources, submitting forms)
    # - PUT (update): 10% (updating existing resources)
    # - DELETE: 5% (removing resources)

    request_type_distribution = {
        'GET': 0.60,    # 60% read operations
        'POST': 0.25,   # 25% create operations
        'PUT': 0.10,    # 10% update operations
        'DELETE': 0.05  # 5% delete operations
    }

    request_mix = []
    for svc in frontends:
        # Each service handles all request types with the standard distribution
        for req_type, type_fraction in request_type_distribution.items():
            # Weight = (service share) × (type distribution)
            # E.g., if 2 frontends: each gets 50 weight, then split by type distribution
            request_mix.append({
                'type': req_type,
                'service': svc,
                'weight': int(weight * type_fraction)
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


def generate_episode(episode_id: int, output_dir: str, scenario_lib: ScenarioLibrary, verbose: bool = False, topology_size: int = None, force_fault_type: str = None, force_fault_role: str = None, use_llm_topologies: bool = False, topology_bank_dir: str = "data/topology_bank", topology_name: str = None, skip_analysis: bool = True, llm_provider: str = "openai", llm_model: str = None, enable_enhanced_analysis: bool = False, replay_params: dict = None, force_root_cause: str = None, force_phi: float = None, fault_severity: float = 0.5):
    """
    Generate a single training episode.

    Args:
        episode_id: Unique episode identifier
        output_dir: Base output directory
        scenario_lib: Scenario library instance
        verbose: Print detailed progress
        topology_size: Optional override for topology size (number of nodes)
        force_fault_type: Force a specific fault type (e.g., 'queue_consumer_slowdown')
        force_fault_role: Force a specific fault role (e.g., 'queue')
        use_llm_topologies: Use LLM-generated topologies from topology bank
        topology_bank_dir: Directory containing LLM-generated topologies
        skip_analysis: Skip LLM analysis to speed up generation
        llm_provider: LLM provider to use (openai, anthropic) - default: openai
        llm_model: Specific model to use (default: gpt-4 for openai, claude-opus-4-5 for anthropic)
        enable_enhanced_analysis: Enable enhanced fault propagation analysis (latency, config, causal chains)
        replay_params: Dictionary of parameters to replay a previous run
        force_root_cause: Force a specific root cause component
        force_phi: Force a specific fragility index value
        fault_severity: Fault injection severity scale (0.0-1.0)

    Returns:
        Dictionary with episode metadata
    """
    # Performance timing
    import time
    phase_timings = {}
    episode_start = time.time()

    # 0. Setup episode directory and logging
    phase_start = time.time()
    episode_dir = os.path.join(output_dir, f'ep_{episode_id}')
    os.makedirs(episode_dir, exist_ok=True)
    phase_timings['setup'] = time.time() - phase_start

    # Initialize variables for cleanup
    workload_path = None
    log_file = None
    file_handler = None

    # Set up logging to file in episode directory
    import logging
    simulation_log_path = os.path.join(episode_dir, 'simulation.log')

    # Create a file handler for this episode
    file_handler = logging.FileHandler(simulation_log_path, mode='w')
    file_handler.setLevel(logging.ERROR)  # Only log ERROR level and above
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Get the root logger and add the file handler
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    # Also set up console output to be duplicated to the log file
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    class TeeStream:
        """Stream that writes to both file and console"""
        def __init__(self, file_obj, console_obj):
            self.file = file_obj
            self.console = console_obj

        def write(self, data):
            self.file.write(data)
            self.console.write(data)

        def flush(self):
            self.file.flush()
            self.console.flush()

    # Open log file for stdout/stderr capture
    log_file = open(simulation_log_path, 'a')
    sys.stdout = TeeStream(log_file, original_stdout)
    sys.stderr = TeeStream(log_file, original_stderr)

    # REPLAY MODE: Override parameters if replay_params is provided
    if replay_params:
        if verbose:
            print(f"\n[REPLAY MODE ACTIVE]")
            print(f"  Overriding parameters from replay config...")

        # Override topology selection
        use_llm_topologies = True  # Replay only works with LLM topologies
        topology_name = replay_params['topology']['name']
        # Override topology bank directory if provided
        if 'bank_dir' in replay_params['topology']:
            topology_bank_dir = replay_params['topology']['bank_dir']

        # Override fault parameters
        force_fault_type = replay_params['fault']['type']
        force_fault_role = replay_params['fault']['role']
        force_root_cause = replay_params['fault']['root_cause_node']

        # Override capacity parameters
        force_phi = replay_params['capacity']['phi']

        if verbose:
            print(f"    Topology: {topology_name}")
            print(f"    Topology Bank: {topology_bank_dir}")
            print(f"    Fault: {force_fault_type} ({force_fault_role})")
            print(f"    Root Cause: {force_root_cause}")
            print(f"    Phi: {force_phi:.3f}")

    # Apply force_root_cause / force_phi even if not in replay mode
    # (allows manual override via command line)

    # 1. Generate Topology first to see what node types are available
    phase_start = time.time()

    # LLM Topology Mode: Load from pre-generated bank
    if use_llm_topologies:
        if verbose:
            print(f"\n[LLM Topology Mode]")
            print(f"  Loading from topology bank: {topology_bank_dir}")

        # Load random LLM-designed topology
        nx_graph, semantic_overlay, chosen_topology_name = load_random_template(topology_bank_dir, topology_name)
        # Store the actual topology directory name for replay
        topology_name = chosen_topology_name

        # Get available node roles from the loaded topology
        available_roles = set(data.get('role') for _, data in nx_graph.nodes(data=True))

        if verbose:
            print(f"  Loaded: {semantic_overlay.get('architecture_name', 'Unknown')}")
            print(f"  Domain: {semantic_overlay.get('domain', 'unknown')}")
            print(f"  Nodes: {len(nx_graph.nodes)}, Edges: {len(nx_graph.edges)}")
            print(f"  Available roles: {', '.join(sorted(available_roles))}")

        # Special handling for no_fault: create baseline episode without fault injection
        if force_fault_type == 'no_fault':
            cfg = EpisodeConfig(
                level=1,
                topology_size=len(nx_graph.nodes),
                duration=600,
                fault_type='no_fault',
                fault_target_role='service',  # Dummy value, not used
                export_interval=5,
                description='Baseline episode without fault injection',
                progression={'type': 'none'},
                fault_params={},
                fault_severity=0.0  # No fault
            )
            if verbose:
                print(f"  No fault mode: Running baseline simulation without fault injection")

        # If only force_fault_type is specified (no role), auto-select compatible role
        elif force_fault_type and not force_fault_role:
            # Find all scenarios matching the fault type
            matching_scenarios = []
            for level in [1, 2, 3, 4]:
                scenarios = scenario_lib.levels[level]
                for scenario in scenarios:
                    if scenario.fault_type == force_fault_type:
                        # For network_partition, any scenario works
                        # For other faults, check if topology has required role
                        if scenario.fault_type == 'network_partition' or scenario.fault_target_role in available_roles:
                            matching_scenarios.append(scenario)

            if not matching_scenarios:
                print(f"Error: Could not find compatible scenario with fault_type='{force_fault_type}' for this topology")
                print(f"  Available roles: {available_roles}")
                return None

            # Pick the first compatible scenario (could randomize if desired)
            chosen_scenario = matching_scenarios[0]
            cfg = EpisodeConfig(
                level=chosen_scenario.level,
                topology_size=len(nx_graph.nodes),
                duration=chosen_scenario.duration,
                fault_type=chosen_scenario.fault_type,
                fault_target_role=chosen_scenario.fault_target_role,
                export_interval=chosen_scenario.export_interval,
                description=chosen_scenario.description,
                progression=chosen_scenario.progression,
                fault_params=chosen_scenario.fault_params,
                fault_severity=chosen_scenario.fault_severity
            )

            if verbose:
                print(f"  Auto-selected scenario: {cfg.description}")
                print(f"  Fault type: {cfg.fault_type}, Target role: {cfg.fault_target_role} (auto-selected from {len(matching_scenarios)} compatible scenarios)")

        # If both force_fault_type and force_fault_role are specified, find exact match
        elif force_fault_type and force_fault_role:
            # Find a scenario that matches the forced parameters
            cfg = None
            for level in [1, 2, 3, 4]:
                scenarios = scenario_lib.levels[level]
                for scenario in scenarios:
                    if scenario.fault_type == force_fault_type and scenario.fault_target_role == force_fault_role:
                        # Found a match - create a copy with updated topology size
                        cfg = EpisodeConfig(
                            level=scenario.level,
                            topology_size=len(nx_graph.nodes),
                            duration=scenario.duration,
                            fault_type=scenario.fault_type,
                            fault_target_role=scenario.fault_target_role,
                            export_interval=scenario.export_interval,
                            description=scenario.description,
                            progression=scenario.progression,
                            fault_params=scenario.fault_params,
                            fault_severity=scenario.fault_severity
                        )
                        break
                if cfg:
                    break

            if cfg is None:
                print(f"Error: Could not find scenario with fault_type='{force_fault_type}' and role='{force_fault_role}'")
                return None

            # Verify the topology has the required role (skip for network_partition)
            if cfg.fault_type != 'network_partition' and cfg.fault_target_role not in available_roles:
                print(f"Warning: LLM topology does not have required role '{cfg.fault_target_role}', skipping episode {episode_id}")
                return None

            if verbose:
                print(f"  Forced scenario: {cfg.description}")
                print(f"  Fault type: {cfg.fault_type}, Target role: {cfg.fault_target_role}")

        else:
            # Try to find a compatible scenario (max 10 attempts)
            cfg = None
            for attempt in range(10):
                level = scenario_lib.sample_level(seed=episode_id + attempt)
                temp_cfg = scenario_lib.get_episode(level, seed=episode_id + attempt)
                temp_cfg.topology_size = len(nx_graph.nodes)

                # Check if this scenario's target role exists in the topology
                # Skip role check for network_partition (it works with any topology)
                if temp_cfg.fault_type == 'network_partition' or temp_cfg.fault_target_role in available_roles:
                    cfg = temp_cfg
                    break

            if cfg is None:
                print(f"Warning: Could not find compatible scenario for LLM topology with roles {available_roles}, skipping episode {episode_id}")
                return None

        level = cfg.level
        phase_timings['topology_generation'] = time.time() - phase_start

    # Procedural Topology Mode: Generate from scratch
    else:
        # Override topology size if specified, otherwise use random size between 8-15
        if topology_size is not None:
            actual_topology_size = topology_size
        else:
            # Default: random number of nodes between 8-15
            actual_topology_size = random.randint(8, 15)

        # Special handling for no_fault: create baseline episode without fault injection
        if force_fault_type == 'no_fault':
            cfg = EpisodeConfig(
                level=1,
                topology_size=actual_topology_size if actual_topology_size is not None else 10,
                duration=600,
                fault_type='no_fault',
                fault_target_role='service',  # Dummy value, not used
                export_interval=5,
                description='Baseline episode without fault injection',
                progression={'type': 'none'},
                fault_params={},
                fault_severity=0.0  # No fault
            )
            if verbose:
                print(f"  No fault mode: Running baseline simulation without fault injection")

        # If only force_fault_type is specified (no role), auto-select first matching scenario
        elif force_fault_type and not force_fault_role:
            # Find the first scenario matching the fault type
            cfg = None
            for level in [1, 2, 3, 4]:
                scenarios = scenario_lib.levels[level]
                for scenario in scenarios:
                    if scenario.fault_type == force_fault_type:
                        cfg = EpisodeConfig(
                            level=scenario.level,
                            topology_size=actual_topology_size if actual_topology_size is not None else scenario.topology_size,
                            duration=scenario.duration,
                            fault_type=scenario.fault_type,
                            fault_target_role=scenario.fault_target_role,
                            export_interval=scenario.export_interval,
                            description=scenario.description,
                            progression=scenario.progression,
                            fault_params=scenario.fault_params,
                            fault_severity=scenario.fault_severity
                        )
                        break
                if cfg:
                    break

            if cfg is None:
                print(f"Error: Could not find scenario with fault_type='{force_fault_type}'")
                return None

            # Generate topology that includes the required role
            topo_gen = TopologyGenerator(seed=episode_id)
            nx_graph = topo_gen.generate_complex_graph(cfg.topology_size)

            # Verify the topology has the required role (skip for network_partition)
            if cfg.fault_type != 'network_partition':
                available_roles = set(data.get('role') for _, data in nx_graph.nodes(data=True))
                if cfg.fault_target_role not in available_roles:
                    print(f"Error: Generated topology doesn't have required role '{cfg.fault_target_role}'")
                    return None

            if verbose:
                print(f"  Auto-selected scenario: {cfg.description}")
                print(f"  Fault type: {cfg.fault_type}, Target role: {cfg.fault_target_role} (auto-selected)")

            level = cfg.topology_size  # Use topology size as level for display

        # If both force_fault_type and force_fault_role are specified, find exact match
        elif force_fault_type and force_fault_role:
            # Find a scenario that matches the forced parameters by searching all levels directly
            cfg = None
            for level in [1, 2, 3, 4]:
                scenarios = scenario_lib.levels[level]
                for scenario in scenarios:
                    if scenario.fault_type == force_fault_type and scenario.fault_target_role == force_fault_role:
                        # Found a match - create a copy with updated topology size
                        cfg = EpisodeConfig(
                            level=scenario.level,
                            topology_size=actual_topology_size if actual_topology_size is not None else scenario.topology_size,
                            duration=scenario.duration,
                            fault_type=scenario.fault_type,
                            fault_target_role=scenario.fault_target_role,
                            export_interval=scenario.export_interval,
                            description=scenario.description,
                            progression=scenario.progression,
                            fault_params=scenario.fault_params,
                            fault_severity=scenario.fault_severity
                        )
                        break
                if cfg:
                    break

            if cfg is None:
                print(f"Error: Could not find scenario with fault_type='{force_fault_type}' and role='{force_fault_role}'")
                return None

            # Generate topology that includes the required role
            topo_gen = TopologyGenerator(seed=episode_id)
            nx_graph = topo_gen.generate_complex_graph(cfg.topology_size)

            # Verify the topology has the required role (skip for network_partition)
            if cfg.fault_type != 'network_partition':
                available_roles = set(data.get('role') for _, data in nx_graph.nodes(data=True))
                if cfg.fault_target_role not in available_roles:
                    print(f"Error: Generated topology doesn't have required role '{cfg.fault_target_role}'")
                    return None

            level = cfg.topology_size  # Use topology size as level for display
        # If topology_size is specified, generate topology first to determine available node types
        elif actual_topology_size is not None:
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
                # Skip role check for network_partition (it works with any topology)
                if temp_cfg.fault_type == 'network_partition' or temp_cfg.fault_target_role in available_roles:
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

        phase_timings['topology_generation'] = time.time() - phase_start
        semantic_overlay = None  # Will be generated later

    # Override fault severity with user-provided value
    cfg.fault_severity = fault_severity

    if verbose:
        print(f"\n{'='*60}")
        print(f"Episode {episode_id} [Level {level}]")
        print(f"  Scenario: {cfg.description}")
        print(f"  Topology: {len(nx_graph.nodes)} nodes")
        print(f"  Duration: {cfg.duration}s")
        print(f"  Fault: {cfg.fault_type} on {cfg.fault_target_role}")
        print(f"{'='*60}")
        print_topology_summary(nx_graph)

    # 2.3. Generate Semantic Overlay using Claude (if enabled and not using LLM topologies)
    phase_start = time.time()
    from src.core.simulation_config import get_simulation_config
    sim_config_obj = get_simulation_config()
    semantic_config = getattr(sim_config_obj, 'semantic', None)
    semantic_enabled = semantic_config.get('enabled', True) if semantic_config and isinstance(semantic_config, dict) else True

    # Skip semantic overlay generation if using LLM topologies (already loaded)
    if not use_llm_topologies:
        if semantic_enabled:
            if verbose:
                print(f"\n[Semantic Mapping]")
                print(f"  Analyzing topology with Claude AI...")

            # Initialize SemanticMapper with Anthropic API key
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            mapper = SemanticMapper(api_key=api_key)

            # Generate semantic overlay
            semantic_overlay = mapper.generate_semantic_overlay(nx_graph)

            if verbose:
                print(f"  Domain: {semantic_overlay.get('domain', 'unknown')}")
                print(f"  Request types: {', '.join(semantic_overlay.get('request_types', []))}")
                print(f"  Services profiled: {len(semantic_overlay.get('services', {}))}")

                # Show a few example service profiles
                services = semantic_overlay.get('services', {})
                if services:
                    print(f"\n  Example service profiles:")
                    for i, (node_id, service_data) in enumerate(list(services.items())[:3]):
                        print(f"    {node_id}: {service_data.get('name', 'Unknown')} ({service_data.get('profile', 'standard')})")
        else:
            if verbose:
                print(f"\n[Semantic Mapping]")
                print(f"  Semantic overlay DISABLED (using standard profiles and probabilistic routing)")
            semantic_overlay = None

    phase_timings['semantic_overlay'] = time.time() - phase_start

    # --- Deterministic Capacity Planning ---
    phase_start = time.time()
    if verbose:
        print(f"\n[Capacity Planning]")
        print(f"  Analyzing flows and tuning resources...")

    # 1. Define Target Workload (Fixed high load to stress the system)
    target_rps = 200

    # 2. Randomize Fragility (Curriculum Learning)
    # phi -> 1.0 means system is tuned "just in time" (metastable)
    # phi -> 0.0 means system is over-provisioned (robust)
    if force_phi is not None:
        phi = force_phi
        if verbose:
            print(f"  Fragility Index (phi): {phi:.2f} [FORCED]")
    else:
        phi = random.uniform(0.6, 0.95)
        if verbose:
            print(f"  Fragility Index (phi): {phi:.2f}")

    # 3. Run Capacity Planner
    planner = CapacityPlanner(nx_graph, semantic_overlay)
    tuned_configs = planner.plan_capacity(target_rps, phi)

    # 4. Apply Configs to Graph Nodes (Service level)
    for node_id, config in tuned_configs.items():
        nx_graph.nodes[node_id]['iac_config_overrides'] = config

    # 5. Adjust Pod Counts to Match Capacity Planning
    # When using LLM topologies, pods are pre-created. We need to add or remove pods
    # to match the capacity planner's desired_replicas.
    for node_id, config in tuned_configs.items():
        if 'desired_replicas' not in config:
            continue  # Skip non-service nodes (databases, caches, etc.)

        desired_replicas = config['desired_replicas']

        # Find all existing pods for this service
        existing_pods = [
            pod_id for pod_id, attrs in nx_graph.nodes(data=True)
            if attrs.get('type') == 'Pod' and attrs.get('parent_service') == node_id
        ]
        current_replica_count = len(existing_pods)

        if current_replica_count == desired_replicas:
            continue  # Already correct

        if verbose:
            print(f"  Adjusting {node_id}: {current_replica_count} -> {desired_replicas} pods")

        if current_replica_count < desired_replicas:
            # Need to ADD pods
            pods_to_add = desired_replicas - current_replica_count

            # Find the compute nodes and pod_pool edges for this service
            compute_nodes = []
            for pod_id in existing_pods:
                for neighbor in nx_graph.neighbors(pod_id):
                    if nx_graph.nodes[neighbor].get('type') == 'ComputeNode':
                        compute_nodes.append(neighbor)

            # If no compute nodes found, try to find them from the service
            if not compute_nodes:
                # Find compute nodes connected to existing pods of other services
                all_compute_nodes = [
                    n for n, attrs in nx_graph.nodes(data=True)
                    if attrs.get('type') == 'ComputeNode'
                ]
                compute_nodes = all_compute_nodes

            # Create new pods
            for i in range(pods_to_add):
                new_pod_id = f"pod_{node_id}_{current_replica_count + i}"

                # Add pod node
                nx_graph.add_node(new_pod_id, type='Pod', parent_service=node_id)

                # Add pod_pool edge from service to pod
                nx_graph.add_edge(node_id, new_pod_id, type='pod_pool')

                # Add pod_placement edge to a compute node (round-robin)
                if compute_nodes:
                    target_compute_node = compute_nodes[(current_replica_count + i) % len(compute_nodes)]
                    nx_graph.add_edge(new_pod_id, target_compute_node, type='pod_placement')

        elif current_replica_count > desired_replicas:
            # Need to REMOVE pods
            pods_to_remove = current_replica_count - desired_replicas

            # Remove the last N pods (highest indices)
            pods_to_delete = sorted(existing_pods)[-pods_to_remove:]

            for pod_id in pods_to_delete:
                # Remove all edges connected to this pod
                nx_graph.remove_node(pod_id)

    # 6. Propagate Configs to Pods (Infrastructure level)
    # Since Pods are separate nodes in the graph, we need to copy the parent service's
    # thread/connection pool settings to the pod nodes so Adapter picks them up.
    for node_id, attrs in nx_graph.nodes(data=True):
        if attrs.get('type') == 'Pod':
            parent_svc = attrs.get('parent_service')
            if parent_svc and parent_svc in tuned_configs:
                # Copy relevant resource configs to pod
                svc_config = tuned_configs[parent_svc]
                pod_override = {}

                # Only copy non-None values
                if 'thread_pool_size' in svc_config and svc_config['thread_pool_size'] is not None:
                    pod_override['thread_pool_size'] = svc_config['thread_pool_size']
                if 'db_connection_pool_capacity' in svc_config and svc_config['db_connection_pool_capacity'] is not None:
                    pod_override['db_connection_pool_capacity'] = svc_config['db_connection_pool_capacity']
                if 'message_concurrency' in svc_config and svc_config['message_concurrency'] is not None:
                    pod_override['message_concurrency'] = svc_config['message_concurrency']
                if 'timeouts' in svc_config and svc_config['timeouts'] is not None:
                    pod_override['timeouts'] = svc_config['timeouts']

                if pod_override:  # Only set if we have something to override
                    nx_graph.nodes[node_id]['iac_config_overrides'] = pod_override

    # 7. Create Workload Config matching the target RPS
    workload_path = create_dynamic_workload(nx_graph, base_rps=int(target_rps*0.8), peak_rps=target_rps)

    # --- End Capacity Planning ---
    phase_timings['capacity_planning'] = time.time() - phase_start

    # 4. Configure Simulation (episode_dir already created in step 0)
    phase_start = time.time()

    # Export capacity planning analysis
    capacity_export = {
        'target_rps': target_rps,
        'fragility_index': phi,
        'tuned_nodes': len(tuned_configs),
        'configurations': tuned_configs
    }

    with open(os.path.join(episode_dir, 'capacity_planning.json'), 'w') as f:
        json.dump(capacity_export, f, indent=2)

    if verbose:
        print(f"  ✓ Capacity planning saved to: {episode_dir}/capacity_planning.json")

    # IMPORTANT: Extend simulation duration to include warmup period
    # For a 600s requested duration with 60s warmup:
    #   - Total physical time: 660s (0-60s warmup + 60-660s simulation)
    #   - Metrics collected: 600s (sim.time 0-600 in metrics)
    warmup_period_sec = 60.0
    total_physical_duration = cfg.duration + warmup_period_sec

    sim_config = {
        'simulation': {
            'duration': total_physical_duration,  # Extended to include warmup
            'output_dir': episode_dir,
            'warmup_period': warmup_period_sec
        },
        'telemetry': {
            'metric_export_interval': cfg.export_interval,
            'exporter_type': 'file'
        },
        'workload': {
            'path': workload_path
        },
        'infrastructure': {
            'path': 'generated_internal'
        },
        # [FIX 3] Explicitly set massive workload capacity
        'workload_generator': {
            'connection_pool_size': 5000,
            'request_timeout_seconds': 60.0,
            'max_queue_size': 10000,
            'circuit_breaker': {
                'enabled': True,
                'failure_threshold': 0.9,
                'success_threshold': 0.8,
                'window_size': 100
            }
        }
    }

    # 5. Initialize Simulation (bypass IaC parsing)
    sim = Simulation(sim_config)

    # Initialize simulation timestamp (normally done in sim.run())
    import time
    now_ns = int(time.time() * 1_000_000_000)
    duration_ns = int(cfg.duration * 1_000_000_000)
    sim.simulation_start_timestamp_ns = now_ns - duration_ns

    # 5.5. Setup Topology State Exporter BEFORE creating components
    # This allows the DeploymentController to receive the exporter and track pod lifecycle events
    topology_exporter = TopologyStateExporter(sim.env, episode_dir)

    # 6. Setup Simulation Environment using Simulation's env (CRITICAL FIX!)
    # NEW: Pass semantic overlay AND topology_exporter to adapter
    adapter = TopologyAdapter(sim.env, semantic_overlay=semantic_overlay, topology_exporter=topology_exporter)
    registry = adapter.graph_to_registry(nx_graph)
    sim.component_registry = registry  # Directly set registry

    # Register all components with the exporter
    for component_id, component in registry.items():
        if isinstance(component, Service):
            topology_exporter.register_service(component)
        elif isinstance(component, Pod):
            topology_exporter.register_pod(component)
        elif isinstance(component, ComputeNode):
            topology_exporter.register_node(component)
        elif isinstance(component, DeploymentController):
            topology_exporter.register_controller(component)

    if verbose:
        print(f"\n[Topology State Exporter]")
        print(f"  Registered {len([c for c in registry.values() if isinstance(c, Service)])} services")
        print(f"  Registered {len([c for c in registry.values() if isinstance(c, Pod)])} pods")
        print(f"  Registered {len([c for c in registry.values() if isinstance(c, ComputeNode)])} nodes")
        print(f"  Registered {len([c for c in registry.values() if isinstance(c, DeploymentController)])} controllers")

    # 7. Inject Fault Programmatically (GRADUAL APPLICATION)
    # Special handling for no_fault: skip all fault injection logic
    if cfg.fault_type == 'no_fault':
        actual_target_id = None
        params = {}
        if verbose:
            print(f"\n[No Fault Mode]")
            print(f"  Skipping fault injection - running baseline simulation")
    # Special handling for network_partition
    elif cfg.fault_type == 'network_partition':
        # Network partition requires two components that COMMUNICATE with each other
        # Find all edges in the topology (communication paths)
        all_edges = list(nx_graph.edges())
        if len(all_edges) < 1:
            print(f"Error: Network partition requires at least 1 edge (communication path), found {len(all_edges)}")
            return None

        # Filter out pod_pool and pod_placement edges (internal infrastructure)
        # We want to partition actual service-to-service or service-to-database communication
        valid_edges = [
            (src, tgt) for src, tgt in all_edges
            if nx_graph.get_edge_data(src, tgt).get('type') not in ['pod_pool', 'pod_placement']
        ]

        if not valid_edges:
            print(f"Error: Network partition requires at least 1 non-infrastructure edge, found none")
            return None

        # Randomly select one edge to partition
        source_id, target_id = random.choice(valid_edges)

        # Get edge type for logging
        edge_data = nx_graph.get_edge_data(source_id, target_id)
        edge_type = edge_data.get('type', 'unknown') if edge_data else 'unknown'

        # Update params with the selected components
        params = cfg.get_failure_params()
        params['source_component_id'] = source_id
        params['target_component_id'] = target_id

        # For network partition, the target is the global_network NetworkLink
        # We need to ensure it exists in the registry
        if 'global_network' not in registry:
            # Create the global NetworkLink if it doesn't exist
            from src.components.network import NetworkLink
            registry['global_network'] = NetworkLink(sim.env, 'global_network')

        # Register the global network link for partition checks across all components
        # Import is at module level to avoid UnboundLocalError
        sim_module = __import__('src.simulation', fromlist=['Simulation'])
        sim_module.Simulation.set_global_network(registry['global_network'])

        # Set target_id to global_network for fault injection
        actual_target_id = 'global_network'

        # Add global_network node to topology graph so it can be analyzed by RCA
        # This represents the network infrastructure that controls connectivity
        nx_graph.add_node('global_network',
                         type='NetworkLink',
                         role='network',
                         service_name='global_network',
                         semantic_name='global_network',
                         # Store partition details for RCA to explain which edge is broken
                         partition_metadata={
                             'partitioned_edge': {
                                 'source': source_id,
                                 'target': target_id,
                                 'edge_type': edge_type,
                                 'bidirectional': params.get('bidirectional', True)
                             }
                         })

        if verbose:
            print(f"\n[Network Partition Setup]")
            print(f"  Partitioning edge: {source_id} -> {target_id}")
            print(f"  Edge type: {edge_type}")
            print(f"  This will block all communication on this edge")
            print(f"  Target component for injection: {actual_target_id}")
            print(f"  Added global_network node to topology for RCA analysis")
    else:
        # Normal fault injection: select one component with matching role
        valid_targets = [
            nid for nid, data in nx_graph.nodes(data=True)
            if data.get('role') == cfg.fault_target_role
        ]

        # ADDITIONAL CONSTRAINT for hot_shard: only select services with sync HTTP ingress
        # hot_shard works by skewing traffic at the load balancer level, which only applies
        # to synchronous request routing, not queue-based async consumers
        if cfg.fault_type == 'hot_shard':
            # Filter to only services that have incoming sync_http edges
            valid_targets = [
                nid for nid in valid_targets
                if any(
                    edge_data.get('type') == 'sync_http'
                    for pred in nx_graph.predecessors(nid)
                    for edge_data in [nx_graph.get_edge_data(pred, nid)]
                )
            ]
            if verbose and valid_targets:
                print(f"\n[hot_shard constraint] Filtered to {len(valid_targets)} services with sync HTTP ingress")
            if not valid_targets:
                print(f"Warning: No services with sync HTTP ingress for hot_shard, skipping episode {episode_id}")
                return None

        # This should never happen now since we pre-validate scenarios
        if not valid_targets:
            raise ValueError(f"Internal error: No valid targets for role '{cfg.fault_target_role}' in episode {episode_id}")

        # ROOT CAUSE SELECTION: Use force_root_cause if provided, otherwise random
        if force_root_cause:
            # Verify the forced root cause exists in valid targets
            if force_root_cause not in valid_targets:
                print(f"Error: Forced root cause '{force_root_cause}' not found in valid targets: {valid_targets}")
                return None
            target_id = force_root_cause
        else:
            # UNIFORM SELECTION: Use simple random selection to avoid bias
            # Previous approach favored nodes with many predecessors (consumers)
            # Now we want uniform distribution across all valid targets
            target_id = random.choice(valid_targets)

        # Calculate connectivity for logging only (not for selection)
        def get_connectivity_info(target_node):
            """Get connectivity information for logging."""
            predecessors = list(nx_graph.predecessors(target_node))
            successors = list(nx_graph.successors(target_node))

            # Second-order downstream (potential propagation)
            second_order_downstream = set()
            for succ in successors:
                second_order_downstream.update(nx_graph.successors(succ))

            return {
                'predecessors': len(predecessors),
                'successors': len(successors),
                'downstream_reach': len(second_order_downstream)
            }

        if verbose:
            conn_info = get_connectivity_info(target_id)
            selection_method = "FORCED" if force_root_cause else "uniform random"
            print(f"  Selected target {target_id} ({selection_method})")
            print(f"    Connectivity: {conn_info['predecessors']} upstream, {conn_info['successors']} downstream, {conn_info['downstream_reach']} 2nd-order downstream")

        actual_target_id = target_id
        params = cfg.get_failure_params()

    # === CAPACITY-AWARE FAULT TUNING ===
    # Tune fault parameters based on node capacity, replicas, and topology position
    # This ensures faults are strong enough to cause visible impact regardless of scale
    # NOTE: No phi parameter! Phi is already factored into capacity planning.
    fault_tuner = FaultParameterTuner(
        nx_graph=nx_graph,
        capacity_configs=tuned_configs,
        target_rps=target_rps
    )

    tuned_params = fault_tuner.tune_fault_parameters(
        target_node_id=actual_target_id,
        fault_type=cfg.fault_type,
        baseline_params=params,
        severity=cfg.fault_severity,
        verbose=verbose
    )

    # Use tuned parameters for fault injection
    params = tuned_params

    # Calculate A-B-A timeline (Healthy -> Fault -> Recovery):
    # - Warmup: 0 to warmup_period (no metrics collected)
    # - Healthy Baseline: warmup_period to fault_start (healthy system with metrics)
    # - Fault Ramp: fault_start to fault_start + ramp_duration (degradation)
    # - Fault Sustain: fault_start + ramp_duration to recovery_start (full failure)
    # - Recovery: recovery_start to recovery_start + ramp_duration (healing)
    # - Post-Recovery: recovery_start + ramp_duration to end (recovered baseline)

    # Use the warmup period defined earlier
    warmup_period = warmup_period_sec

    # Calculate fault timing relative to requested duration (cfg.duration)
    # This ensures we have a healthy baseline period after warmup before fault injection
    # The fault timing is based on the REQUESTED duration, not the extended physical duration
    fault_start_time = int(warmup_period + cfg.duration * 0.20)  # Start at warmup + 20% of requested duration
    fault_ramp_duration = int(cfg.duration * 0.10)  # Fast ramp (10% of requested duration)
    fault_sustain_duration = int(cfg.duration * 0.40)  # Sustain fault for 40% of requested duration
    recovery_start_time = fault_start_time + fault_ramp_duration + fault_sustain_duration

    if verbose:
        print(f"\n[Fault Injection - A-B-A TIMELINE]")
        print(f"  Target: {actual_target_id}")
        if cfg.fault_type == 'network_partition':
            print(f"  Partitioned components: {source_id} <-> {target_id}")
        print(f"  Total Physical Duration: {total_physical_duration}s (requested: {cfg.duration}s + warmup: {int(warmup_period)}s)")
        print(f"  Warmup (No Metrics): 0s - {int(warmup_period)}s")
        print(f"  Phase A (Healthy Baseline): {int(warmup_period)}s - {fault_start_time}s")
        print(f"  Phase B Ramp (Degradation): {fault_start_time}s - {fault_start_time + fault_ramp_duration}s")
        print(f"  Phase B Sustain (Full Fault): {fault_start_time + fault_ramp_duration}s - {recovery_start_time}s")
        print(f"  Phase A Recovery: {recovery_start_time}s - {recovery_start_time + fault_ramp_duration}s")
        print(f"  Phase A Post-Recovery: {recovery_start_time + fault_ramp_duration}s - {total_physical_duration}s")

    # Initialize new training-focused injector
    injector = TrainingFailureInjector(
        sim.env,
        registry,
        sim.tracker,
        simulation_start_timestamp_ns=sim.simulation_start_timestamp_ns
    )

    # Schedule GRADUAL fault injection (Phase A -> B) - skip for no_fault
    if actual_target_id is not None:
        injector.inject_gradual_failure(
            target_id=actual_target_id,
            failure_mode=cfg.fault_type,
            start_time=fault_start_time,
            duration=fault_ramp_duration,
            params=params,
            progression=cfg.progression,
            episode_id=f'ep{episode_id}_fault'
        )

        # Schedule GRADUAL fault revert (Phase B -> A Recovery)
        def schedule_revert():
            """SimPy process to schedule the recovery phase."""
            # Wait until recovery should start
            yield sim.env.timeout(recovery_start_time)

            # Apply gradual revert (which may or may not be a generator itself)
            revert_result = injector.revert_gradual_failure(
                target_id=actual_target_id,
                failure_mode=cfg.fault_type,
                params=params,
                duration=fault_ramp_duration  # Symmetric recovery duration
            )

            # If revert_gradual_failure returned a generator (e.g., for cache_failure), yield from it
            if revert_result is not None:
                yield from revert_result

        # Start the revert scheduling process
        sim.env.process(schedule_revert())

    # 8. Save Ground Truth Label (WITH A-B-A TIMELINE)
    # IMPORTANT: All times in the label are in ADJUSTED sim.time (post-warmup)
    # This matches the metrics, which restart from 0 after warmup
    # To get physical time, add warmup_period to any time value

    # Adjust all times to match metrics timeline (subtract warmup)
    adjusted_fault_start = fault_start_time - int(warmup_period)
    adjusted_fault_full_effect = (fault_start_time + fault_ramp_duration) - int(warmup_period)
    adjusted_recovery_start = recovery_start_time - int(warmup_period)
    adjusted_recovery_complete = (recovery_start_time + fault_ramp_duration) - int(warmup_period)
    adjusted_episode_end = cfg.duration  # Full requested duration in metrics timeline

    label = {
        'episode': episode_id,
        'level': level,
        'scenario': cfg.description,
        'root_cause_node': actual_target_id,
        'root_cause_role': cfg.fault_target_role,
        'fault_type': cfg.fault_type,
        'warmup_period': int(warmup_period),
        'fault_start_time': adjusted_fault_start,
        'fault_ramp_duration': fault_ramp_duration,
        'fault_full_effect_time': adjusted_fault_full_effect,
        'recovery_start_time': adjusted_recovery_start,
        'recovery_complete_time': adjusted_recovery_complete,
        'fault_total_duration': adjusted_episode_end - adjusted_fault_start,
        'timeline': {
            'warmup_period': int(warmup_period),
            'healthy_baseline_start': 0,  # Metrics start at 0
            'fault_injection_start': adjusted_fault_start,
            'fault_full_effect': adjusted_fault_full_effect,
            'recovery_start': adjusted_recovery_start,
            'recovery_complete': adjusted_recovery_complete,
            'episode_end': adjusted_episode_end
        },
        'physical_timeline': {
            'note': 'Physical timeline with warmup included (for reference only)',
            'warmup_period': int(warmup_period),
            'warmup_end': int(warmup_period),
            'healthy_baseline_start': int(warmup_period),
            'fault_injection_start': fault_start_time,
            'fault_full_effect': fault_start_time + fault_ramp_duration,
            'recovery_start': recovery_start_time,
            'recovery_complete': recovery_start_time + fault_ramp_duration,
            'episode_end': total_physical_duration
        },
        'timing_note': 'All times in this label are in adjusted sim.time (metrics timeline) starting from 0 after warmup. To convert to physical time, add warmup_period.',
        'progression': {
            'type': cfg.progression,
            'description': f'A-B-A timeline in adjusted sim.time: Healthy Baseline -> Fault ({cfg.progression} over {fault_ramp_duration}s) -> Recovery ({fault_ramp_duration}s)',
            'phases': {
                'healthy_baseline': f'0s - {adjusted_fault_start}s (metrics timeline)',
                'degradation_ramp': f'{adjusted_fault_start}s - {adjusted_fault_full_effect}s',
                'full_failure': f'{adjusted_fault_full_effect}s - {adjusted_recovery_start}s',
                'recovery_ramp': f'{adjusted_recovery_start}s - {adjusted_recovery_complete}s',
                'recovered_baseline': f'{adjusted_recovery_complete}s - {adjusted_episode_end}s'
            },
            'physical_phases': {
                'note': 'Physical timeline with warmup (for reference only)',
                'warmup': f'0s - {int(warmup_period)}s (no metrics collected)',
                'healthy_baseline': f'{int(warmup_period)}s - {fault_start_time}s',
                'degradation_ramp': f'{fault_start_time}s - {fault_start_time + fault_ramp_duration}s',
                'full_failure': f'{fault_start_time + fault_ramp_duration}s - {recovery_start_time}s',
                'recovery_ramp': f'{recovery_start_time}s - {recovery_start_time + fault_ramp_duration}s',
                'recovered_baseline': f'{recovery_start_time + fault_ramp_duration}s - {total_physical_duration}s'
            }
        },
        'fault_params': params,
        'fault_params_baseline': cfg.get_failure_params(),  # Original params from scenario library
        'fault_params_tuned': params,  # Capacity-aware tuned params
        'fault_tuning_applied': True,
        'topology': {
            'nodes': len(nx_graph.nodes),
            'edges': len(nx_graph.edges),
            'frontends': [n for n, d in nx_graph.nodes(data=True) if d.get('is_frontend')]
        }
    }

    # Add network partition specific information to label
    if cfg.fault_type == 'network_partition':
        label['network_partition'] = {
            'source_component': source_id,
            'target_component': target_id,
            'bidirectional': params.get('bidirectional', True)
        }

    label_path = os.path.join(episode_dir, 'label.json')
    with open(label_path, 'w') as f:
        json.dump(label, f, indent=2)

    # Save complete topology graph for GNN training
    topology_data = serialize_topology_graph(nx_graph)
    topology_path = os.path.join(episode_dir, 'topology.json')
    with open(topology_path, 'w') as f:
        json.dump(topology_data, f, indent=2)

    # NEW: Save semantic overlay (if enabled)
    if semantic_overlay:
        semantic_path = os.path.join(episode_dir, 'semantic_map.json')
        with open(semantic_path, 'w') as f:
            json.dump(semantic_overlay, f, indent=2)

    # NEW: Save run parameters for reproducibility (LLM topologies only)
    if use_llm_topologies:
        from datetime import datetime
        run_params = {
            'version': '1.0',
            'generated_at': datetime.now().isoformat(),
            'episode_id': episode_id,
            'topology': {
                'mode': 'llm',
                'name': topology_name,  # This is the actual directory name in topology_bank
                'architecture_name': semantic_overlay.get('architecture_name', 'unknown') if semantic_overlay else 'unknown',
                'bank_dir': topology_bank_dir,
                'num_nodes': len(nx_graph.nodes),
                'num_edges': len(nx_graph.edges),
                'domain': semantic_overlay.get('domain', 'unknown') if semantic_overlay else 'unknown'
            },
            'fault': {
                'type': cfg.fault_type,
                'role': cfg.fault_target_role,
                'root_cause_node': actual_target_id,
                'params': params,
                'progression': cfg.progression
            },
            'capacity': {
                'target_rps': target_rps,
                'phi': phi,
                'phi_forced': force_phi is not None
            },
            'scenario': {
                'level': level,
                'description': cfg.description,
                'duration': cfg.duration,
                'export_interval': cfg.export_interval
            },
            'timeline': {
                'warmup_period': int(warmup_period),
                'fault_start_time': adjusted_fault_start,
                'fault_ramp_duration': fault_ramp_duration,
                'fault_full_effect_time': adjusted_fault_full_effect,
                'recovery_start_time': adjusted_recovery_start,
                'recovery_complete_time': adjusted_recovery_complete,
                'total_duration': adjusted_episode_end
            },
            'replay_instructions': {
                'command': f'python generate_dataset.py --replay {episode_dir}/run_parameters.json --episodes 1 -v',
                'note': 'Use --replay to reproduce this exact scenario. All randomization will be overridden.'
            }
        }

        run_params_path = os.path.join(episode_dir, 'run_parameters.json')
        with open(run_params_path, 'w') as f:
            json.dump(run_params, f, indent=2)

    if verbose:
        print(f"\n[Ground Truth]")
        print(f"  Label saved to: {label_path}")
        print(f"  Topology saved to: {topology_path}")
        if semantic_overlay:
            semantic_path = os.path.join(episode_dir, 'semantic_map.json')
            print(f"  Semantic map saved to: {semantic_path}")
        if use_llm_topologies:
            print(f"  Run parameters saved to: {run_params_path}")
        print(f"  Topology: {topology_data['num_nodes']} nodes, {topology_data['num_edges']} edges")
        if semantic_overlay:
            print(f"  Domain: {semantic_overlay.get('domain', 'unknown')}")

    # 9. Export Initial Topology State
    topology_exporter.export_initial_state()

    if verbose:
        print(f"\n[Initial Topology State]")
        print(f"  Exported initial snapshot at t=0")

    phase_timings['simulation_setup'] = time.time() - phase_start

    # 10. Run Simulation
    phase_start = time.time()
    try:
        if verbose:
            print(f"\n[Simulation]")
            print(f"  Running for {cfg.duration}s...")

        sim.run()

        # Export final topology state
        topology_exporter.export_final_snapshot()

        if verbose:
            print(f"  Completed successfully")
            print(f"  Exported final topology snapshot")
            print(f"  Output directory: {episode_dir}")

        phase_timings['simulation_run'] = time.time() - phase_start

        # 11. Run Whitebox RCA Analysis
        phase_start = time.time()
        if verbose:
            print(f"\n[Whitebox RCA Analysis]")
            print(f"  Running root cause analysis...")

        try:
            if WHITEBOX_RCA_AVAILABLE:
                # Load episode data using DatasetAdapter
                adapter = DatasetAdapter(Path(episode_dir))
                baseline_pods, current_pods = adapter.get_data_windows()

                # Aggregate to service level
                baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
                current_services = adapter.aggregate_pods_to_services(current_pods)

                # Get fault metadata
                ground_truth_node = adapter.label.get('root_cause_node')
                fault_start_time = adapter.label.get('fault_start_time', 0)

                # Check for traces file
                traces_file = Path(episode_dir) / 'traces.jsonl'
                if not traces_file.exists():
                    traces_file = None

                # Run whitebox RCA analysis
                engine = WhiteboxRCAEngine(adapter.topology)
                results = engine.analyze_incident(
                    baseline_services, current_services,
                    metrics_df=adapter.metrics_df,
                    fault_start_time=fault_start_time,
                    traces_file=traces_file,
                    baseline_pods=baseline_pods,
                    current_pods=current_pods
                )

                # Compute rank and found_in_top_k for UI display
                rank = None
                found_in_top_k = False
                top_k = 5  # Standard top-K threshold

                if results:
                    # Find rank of ground truth in rankings
                    for i, result in enumerate(results, 1):
                        if result['node'] == ground_truth_node:
                            rank = i
                            found_in_top_k = (i <= top_k)
                            break

                # Save results (using backward-compatible filename)
                output_path = os.path.join(episode_dir, 'rca_analysis.json')
                with open(output_path, 'w') as f:
                    json.dump({
                        'rankings': results,
                        'ground_truth': ground_truth_node,
                        'fault_start_time': fault_start_time,
                        'rank': rank,
                        'found_in_top_k': found_in_top_k,
                        'top_k': top_k
                    }, f, indent=2)

                if verbose:
                    print(f"  Whitebox RCA analysis saved to: {output_path}")
                    if results:
                        top_result = results[0]
                        print(f"  Top candidate: {top_result['node']} (Score: {top_result['score']:.1f})")
                        print(f"  Ground truth: {ground_truth_node}")
                        top_k_nodes = [r['node'] for r in results[:5]]
                        if ground_truth_node in top_k_nodes:
                            rank = top_k_nodes.index(ground_truth_node) + 1
                            print(f"  Ground truth rank: {rank}/5")
                        else:
                            print(f"  Ground truth rank: >5")
            else:
                print(f"  Warning: Whitebox RCA not available, skipping analysis")

        except Exception as e:
            # Don't fail the entire episode if analysis fails
            print(f"  Warning: Whitebox RCA analysis failed: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

        # 11.5. Run LLM-based Analysis (unless skipped)
        if not skip_analysis:
            if verbose:
                print(f"\n[LLM Analysis]")
                print(f"  Running comprehensive LLM-based simulation analysis...")
                print(f"  Provider: {llm_provider}, Model: {llm_model or 'default'}")

            try:
                # Create LLM provider
                llm = create_llm_provider(llm_provider, llm_model)

                # Create analyzer
                analyzer = SimulationAnalyzer(llm)

                # Analyze episode
                analysis_result = analyzer.analyze_episode(Path(episode_dir))

                # Save results (JSON + Markdown)
                save_analysis_results(analysis_result, Path(episode_dir))

                if verbose:
                    print(f"  LLM analysis complete:")
                    print(f"    - Fault succeeded: {analysis_result.fault_succeeded}")
                    print(f"    - Services impacted: {len(analysis_result.impacted_services)}")
                    print(f"    - Propagation steps: {len(analysis_result.propagation_chain)}")
                    print(f"    - Services recovered: {len(analysis_result.fully_recovered)}")
                    print(f"    - Key findings: {len(analysis_result.key_findings)}")
                    print(f"  Reports saved to:")
                    print(f"    - {os.path.join(episode_dir, 'llm_analysis.json')}")
                    print(f"    - {os.path.join(episode_dir, 'llm_analysis.md')}")

            except Exception as e:
                # Don't fail the entire episode if LLM analysis fails
                print(f"  Warning: LLM analysis failed: {e}")
                if verbose:
                    import traceback
                    traceback.print_exc()
        elif verbose:
            print(f"\n[LLM Analysis]")
            print(f"  Skipped (--skip-analysis enabled)")

        # 12. Validate Baseline Health (Mathematical)
        if verbose:
            print(f"\n[Baseline Health Validation - Mathematical]")

        try:
            # Use mathematical validation
            is_valid, reason, validation_details = validate_system_health(
                metrics_file=Path(os.path.join(episode_dir, 'metrics.jsonl')),
                topology_file=Path(topology_path),
                fault_start_time=fault_start_time,
                thresholds={
                    'max_utilization': 0.85, # Relaxed slightly
                    'max_error_rate': 0.05,  # Relaxed to 5% for training noise
                    'min_success_rate': 0.80, # Relaxed to 80%
                    'min_health_score': 0.60,
                }
            )

            if not is_valid:
                print(f"  ⚠️ Mathematical validation FAILED: {reason}")
                if verbose and validation_details:
                    print(f"    Details: {validation_details}")

                print(f"  KEEPING DATASET FOR TRAINING DIVERSITY (Marked as 'unhealthy_baseline')")

                # Mark the episode but DO NOT DELETE
                validation_marker = os.path.join(episode_dir, '.validation_failed')
                with open(validation_marker, 'w') as f:
                    json.dump({
                        'validation_type': 'mathematical',
                        'reason': reason,
                        'details': validation_details
                    }, f, indent=2)

                # CRITICAL CHANGE: Do not return None, keep the episode for training diversity
            else:
                if verbose:
                    print(f"  ✓ Mathematical validation PASSED: {reason}")

        except Exception as e:
            print(f"  Warning: Mathematical validation failed with error: {e}")
            # Keep going even if validation crashes

    except Exception as e:
        print(f"Error in episode {episode_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        # Cleanup temp workload file
        if workload_path and os.path.exists(workload_path):
            os.remove(workload_path)

        # Restore stdout/stderr and close log file
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        if log_file:
            log_file.close()

        # Remove the file handler from root logger to prevent leaking file descriptors
        if file_handler:
            root_logger.removeHandler(file_handler)
            file_handler.close()

    # Record post-processing time
    phase_timings['post_processing'] = time.time() - phase_start
    phase_timings['total'] = time.time() - episode_start

    # Save performance timing data
    timing_file = os.path.join(episode_dir, 'performance_timing.json')
    with open(timing_file, 'w') as f:
        json.dump(phase_timings, f, indent=2)

    # Add to replay history (LLM topologies only)
    if use_llm_topologies:
        try:
            from src.utils.replay_history import add_to_history
            run_params_path = os.path.join(episode_dir, 'run_parameters.json')
            if os.path.exists(run_params_path):
                # Determine outcome based on validation
                validation_failed = os.path.exists(os.path.join(episode_dir, '.validation_failed'))
                outcome = 'unhealthy_baseline' if validation_failed else 'success'

                # Generate tags
                tags = [cfg.fault_type, actual_target_id]
                if semantic_overlay and 'domain' in semantic_overlay:
                    tags.append(semantic_overlay['domain'])

                add_to_history(
                    run_params_path,
                    tags=tags,
                    notes=f"Episode {episode_id}: {cfg.description}",
                    outcome=outcome
                )

                if verbose:
                    print(f"  ✓ Added to replay history: ~/dataraft/repeatfaults/history.jsonl")
        except Exception as e:
            if verbose:
                print(f"  Warning: Could not add to replay history: {e}")

    if verbose:
        print(f"\n{'='*60}")
        print(f"PERFORMANCE TIMING BREAKDOWN")
        print(f"{'='*60}")
        for phase, duration in phase_timings.items():
            if phase != 'total':
                pct = (duration / phase_timings['total']) * 100 if phase_timings['total'] > 0 else 0
                print(f"  {phase:25s}: {duration:6.2f}s ({pct:5.1f}%)")
        print(f"  {'='*25}   {'='*6}   {'='*7}")
        print(f"  {'TOTAL':25s}: {phase_timings['total']:6.2f}s (100.0%)")
        print(f"{'='*60}\n")

    return {
        'episode_id': episode_id,
        'level': level,
        'output_dir': episode_dir,
        'root_cause': actual_target_id,
        'fault_type': cfg.fault_type,
        'performance_timings': phase_timings
    }


def _generate_episode_process(episode_id, run_dir, verbose, topology_size, force_fault_type, force_fault_role, use_llm_topologies, topology_bank_dir, topology_name, skip_analysis, llm_provider, llm_model, enable_enhanced_analysis, replay_params, force_root_cause, force_phi, fault_severity):
    """
    Wrapper function to run generate_episode in a separate process.
    Each process has completely fresh global state (including OpenTelemetry).
    """
    lib = ScenarioLibrary()
    return generate_episode(episode_id, run_dir, lib, verbose=verbose, topology_size=topology_size, force_fault_type=force_fault_type, force_fault_role=force_fault_role, use_llm_topologies=use_llm_topologies, topology_bank_dir=topology_bank_dir, topology_name=topology_name, skip_analysis=skip_analysis, llm_provider=llm_provider, llm_model=llm_model, enable_enhanced_analysis=enable_enhanced_analysis, replay_params=replay_params, force_root_cause=force_root_cause, force_phi=force_phi, fault_severity=fault_severity)


def generate_dataset(num_episodes: int, output_dir: str, verbose: bool = False, topology_size: int = None, force_fault_type: str = None, force_fault_role: str = None, use_llm_topologies: bool = False, topology_bank_dir: str = "data/topology_bank", topology_name: str = None, skip_analysis: bool = True, llm_provider: str = "openai", llm_model: str = None, enable_enhanced_analysis: bool = False, replay_params: dict = None, force_root_cause: str = None, force_phi: float = None, fault_severity: float = 0.5):
    """
    Generate a full training dataset with multiple episodes.
    Each episode runs in its own process for complete isolation.

    Args:
        num_episodes: Number of episodes to generate
        output_dir: Base output directory (e.g., 'data')
        verbose: Print detailed progress
        topology_size: Optional override for topology size (number of nodes)
        force_fault_type: Force a specific fault type for all episodes
        force_fault_role: Force a specific fault role for all episodes
        use_llm_topologies: Use LLM-generated topologies from topology bank
        topology_bank_dir: Directory containing LLM-generated topologies
        skip_analysis: Skip LLM analysis to speed up generation
        llm_provider: LLM provider to use (openai, anthropic)
        llm_model: Specific model to use
        enable_enhanced_analysis: Enable enhanced fault propagation analysis (latency, config, causal chains)
        replay_params: Dictionary of parameters to replay a previous run
        force_root_cause: Force a specific root cause component
        force_phi: Force a specific fragility index value
        fault_severity: Fault injection severity scale (0.0-1.0)
    """
    print(f"\n{'='*60}")
    print(f"SPATIOTEMPORAL DATA FACTORY")
    print(f"{'='*60}")
    print(f"Generating {num_episodes} training episodes...")
    print(f"Base output directory: {output_dir}")
    if use_llm_topologies:
        print(f"Using LLM-generated topologies from: {topology_bank_dir}")
    else:
        print(f"Using procedural topology generation")
    print(f"Using multiprocessing for complete episode isolation")
    print(f"{'='*60}\n")

    # Create timestamped run directory: data/data_YYYYMMDD_HHMMSS
    from datetime import datetime
    run_id = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(output_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    print(f"Run directory: {run_dir}\n")

    # Initialize scenario library (for metadata collection)
    lib = ScenarioLibrary()

    # Generate episodes under the run directory - each in its own process
    results = []
    for i in range(num_episodes):
        max_retries = 3  # Retry up to 3 times if baseline validation fails
        success = False

        for attempt in range(max_retries):
            if attempt > 0:
                print(f"Retrying episode {i} (attempt {attempt + 1}/{max_retries})...")
            else:
                print(f"Starting episode {i}...")

            # Run episode in a separate process for complete isolation
            process = Process(
                target=_generate_episode_process,
                args=(i, run_dir, verbose, topology_size, force_fault_type, force_fault_role, use_llm_topologies, topology_bank_dir, topology_name, skip_analysis, llm_provider, llm_model, enable_enhanced_analysis, replay_params, force_root_cause, force_phi, fault_severity)
            )
            process.start()
            process.join()  # Wait for completion

            # Check if episode was successful by looking for the label file
            episode_dir = os.path.join(run_dir, f'ep_{i}')
            label_path = os.path.join(episode_dir, 'label.json')
            validation_failed_marker = os.path.join(episode_dir, '.validation_failed')

            # NEW BEHAVIOR: Keep episodes even if validation failed (for training diversity)
            # Check for label.json existence (means episode completed, even if unhealthy)
            if os.path.exists(label_path):
                with open(label_path, 'r') as f:
                    label_data = json.load(f)
                    results.append({
                        'episode_id': i,
                        'level': label_data.get('level'),
                        'output_dir': episode_dir,
                        'root_cause': label_data.get('root_cause_node'),
                        'fault_type': label_data.get('fault_type')
                    })
                # Indicate if episode had validation issues but was kept
                if os.path.exists(validation_failed_marker):
                    print(f"Episode {i} completed (unhealthy baseline kept for training diversity)\n")
                else:
                    print(f"Episode {i} completed successfully\n")
                success = True
                break
            else:
                print(f"Episode {i} failed (no label file found, attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    # Clean up for retry
                    import shutil
                    if os.path.exists(episode_dir):
                        shutil.rmtree(episode_dir)

        if not success:
            print(f"WARNING: Episode {i} could not be generated after {max_retries} attempts\n")

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

    # Validate generated dataset
    print(f"\n{'='*60}")
    print(f"VALIDATING GENERATED DATASET")
    print(f"{'='*60}")

    try:
        from validate_simulation_data import validate_dataset
        from pathlib import Path

        validation_results = validate_dataset(Path(run_dir), verbose=False)

        if validation_results['invalid_episodes'] > 0:
            print(f"⚠️  WARNING: {validation_results['invalid_episodes']}/{validation_results['total_episodes']} episodes failed validation")
            print(f"   Invalid episodes may have incomplete data and should be regenerated.")
            for invalid_dir in validation_results['invalid_dirs']:
                print(f"   - {invalid_dir}")
        else:
            print(f"✅ All {validation_results['valid_episodes']} episodes passed validation")
    except Exception as e:
        print(f"⚠️  Could not validate dataset: {e}")
        print(f"   You can manually validate using: python validate_simulation_data.py {run_dir}")

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
        default=1,
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
    parser.add_argument(
        '--fault-type',
        type=str,
        default=None,
        help='Force a specific fault type (e.g., queue_consumer_slowdown, inject_latency, cpu_saturation)'
    )
    parser.add_argument(
        '--fault-role',
        type=str,
        default=None,
        help='Force a specific fault target role (e.g., queue, service, database, external)'
    )
    parser.add_argument(
        '--llm-topologies',
        action='store_true',
        help='Use LLM-generated topologies from topology bank instead of procedural generation'
    )
    parser.add_argument(
        '--topology-bank',
        type=str,
        default='data/topology_bank',
        help='Directory containing LLM-generated topology bank (default: data/topology_bank)'
    )
    parser.add_argument(
        '--topology-name',
        type=str,
        default=None,
        help='Specific topology name to load from topology bank (if not specified, picks randomly)'
    )
    parser.add_argument(
        '--enable-enhanced-analysis',
        action='store_true',
        default=False,
        help='Enable enhanced fault propagation analysis (latency, config, causal chains) - adds ~6-8s per episode'
    )
    parser.add_argument(
        '--enable-llm-analysis',
        action='store_true',
        default=False,
        help='Enable LLM analysis (disabled by default to speed up generation)'
    )
    parser.add_argument(
        '--llm-provider',
        type=str,
        default='openai',
        choices=['openai', 'anthropic'],
        help='LLM provider to use for analysis (default: openai)'
    )
    parser.add_argument(
        '--llm-model',
        type=str,
        default=None,
        help='Specific LLM model to use (default: gpt-4o for openai, claude-opus-4-5-20251101 for anthropic)'
    )
    parser.add_argument(
        '--fault-severity',
        type=float,
        default=0.5,
        help='Fault injection severity scale (0.0-1.0): 0.0-0.3=Subtle, 0.3-0.7=Moderate, 0.7-1.0=Severe (default: 0.5)'
    )
    parser.add_argument(
        '--replay',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to run_parameters.json file to replay an exact scenario (e.g., data/old_run/ep_0/run_parameters.json)'
    )
    parser.add_argument(
        '--root-cause',
        type=str,
        default=None,
        help='Force a specific root cause component (e.g., notification_service, db_0)'
    )
    parser.add_argument(
        '--phi',
        type=float,
        default=None,
        help='Force a specific fragility index value (0.0-1.0, where 1.0 is most fragile)'
    )

    args = parser.parse_args()

    # Load replay parameters if provided
    replay_params = None
    if args.replay:
        print(f"[REPLAY MODE] Loading parameters from: {args.replay}")
        with open(args.replay, 'r') as f:
            replay_params = json.load(f)
        print(f"  Topology: {replay_params['topology']['name']}")
        print(f"  Fault: {replay_params['fault']['type']} on {replay_params['fault']['root_cause_node']}")
        print(f"  Phi: {replay_params['capacity']['phi']:.3f}")

    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)

    # Generate dataset
    generate_dataset(
        num_episodes=args.episodes,
        output_dir=args.output,
        verbose=args.verbose,
        topology_size=args.topology_size,
        force_fault_type=args.fault_type,
        force_fault_role=args.fault_role,
        use_llm_topologies=args.llm_topologies,
        topology_bank_dir=args.topology_bank,
        topology_name=args.topology_name,
        skip_analysis=not args.enable_llm_analysis,  # Invert the flag
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        enable_enhanced_analysis=args.enable_enhanced_analysis,
        replay_params=replay_params,
        force_root_cause=args.root_cause,
        force_phi=args.phi,
        fault_severity=args.fault_severity
    )


if __name__ == "__main__":
    main()
