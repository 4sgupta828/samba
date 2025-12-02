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
from multiprocessing import Process

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.topology.generator import TopologyGenerator
from src.topology.adapter import TopologyAdapter, print_topology_summary
from src.topology.semantic_mapper import SemanticMapper
from src.scenarios.library import ScenarioLibrary, EpisodeConfig
from src.simulation import Simulation
from src.failures.training_injector import TrainingFailureInjector
from src.telemetry.topology_state_exporter import TopologyStateExporter
from src.components.service import Service
from src.components.pod import Pod
from src.components.compute_node import ComputeNode
from src.components.deployment_controller import DeploymentController
from analysis.propagation_analyzer import analyze_episode
from analysis.forensic_analyzer import analyze_episode as forensic_analyze_episode
from validate_baseline_health import validate_episode_health
from src.validation.health_validator import calculate_safe_workload, validate_system_health
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

    # Create request mix with realistic HTTP method distribution
    # Each frontend service handles ALL request types with typical traffic patterns:
    # - GET (read): 70% (most common - browsing, listing, retrieving data)
    # - POST (create): 30% (creating new resources, submitting forms)
    # NOTE: PUT and DELETE disabled temporarily for testing
    # - PUT (update): 7% (updating existing resources)
    # - DELETE: 3% (removing resources)

    request_type_distribution = {
        'GET': 0.70,    # 70% read operations
        'POST': 0.30,   # 30% create operations
        # 'PUT': 0.07,    # DISABLED - not working yet
        # 'DELETE': 0.03  # DISABLED - not working yet
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


def generate_episode(episode_id: int, output_dir: str, scenario_lib: ScenarioLibrary, verbose: bool = False, topology_size: int = None, force_fault_type: str = None, force_fault_role: str = None):
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

    Returns:
        Dictionary with episode metadata
    """
    # 1. Generate Topology first to see what node types are available
    # Override topology size if specified, otherwise use random size between 8-15
    if topology_size is not None:
        actual_topology_size = topology_size
    else:
        # Default: random number of nodes between 8-15
        actual_topology_size = random.randint(8, 15)

    # If force_fault_type and force_fault_role are specified, find matching scenario
    if force_fault_type and force_fault_role:
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
                        fault_params=scenario.fault_params
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

        # Verify the topology has the required role
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

    # 2.3. Generate Semantic Overlay using Claude
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

    # 2.5. Create initial workload config (for request mix analysis)
    # We'll create it with default RPS first, then adjust after capacity calculation
    # NEW: Use semantic request types if available
    # Note: create_dynamic_workload currently uses HTTP methods, but semantic_overlay has domain-specific types
    # For now, we'll keep HTTP methods for compatibility with existing workload system
    initial_workload_path = create_dynamic_workload(nx_graph, base_rps=80, peak_rps=200)

    # 2.6. Pre-Flight Health Check: Calculate Safe Workload
    if verbose:
        print(f"\n[Pre-Flight Health Check]")
        print(f"  Calculating safe workload using queueing theory...")

    safe_workload = calculate_safe_workload(nx_graph, target_utilization=0.70, workload_config_path=initial_workload_path)

    if verbose:
        print(f"  Critical path latency (p99): {safe_workload['critical_path_latency_p99_ms']:.1f}ms")
        print(f"  Critical path: {safe_workload['critical_path']}")
        print(f"  Bottleneck: {safe_workload['bottleneck_node']} ({safe_workload['bottleneck_role']})")
        print(f"  Bottleneck capacity: {safe_workload['bottleneck_capacity_rps']:.0f} RPS")
        print(f"  Safe baseline RPS: {safe_workload['safe_baseline_rps']} RPS")
        print(f"  Safe peak RPS: {safe_workload['safe_peak_rps']} RPS")
        print(f"  Required connection pool: {safe_workload['required_connection_pool']}")
        print(f"  Paths analyzed: {safe_workload['num_paths_analyzed']}")

    # 3. Create Dynamic Workload (using safe calculated values)
    # Use the smaller of requested or safe workload
    actual_base_rps = min(80, safe_workload['safe_baseline_rps'])
    actual_peak_rps = min(200, safe_workload['safe_peak_rps'])

    if actual_base_rps < 80 or actual_peak_rps < 200:
        if verbose:
            print(f"  ⚠ WARNING: Adjusting workload to safe levels")
            print(f"    Requested: {80}-{200} RPS")
            print(f"    Adjusted:  {actual_base_rps}-{actual_peak_rps} RPS")

    # Recreate workload with adjusted RPS
    workload_path = create_dynamic_workload(nx_graph, base_rps=actual_base_rps, peak_rps=actual_peak_rps)

    # 4. Configure Simulation
    episode_dir = os.path.join(output_dir, f'ep_{episode_id}')
    os.makedirs(episode_dir, exist_ok=True)

    # Export safe workload analysis with rationale
    safe_workload_export = {
        **safe_workload,
        'workload_decision': {
            'requested_baseline_rps': 80,
            'requested_peak_rps': 200,
            'actual_baseline_rps': actual_base_rps,
            'actual_peak_rps': actual_peak_rps,
            'was_adjusted': actual_base_rps < 80 or actual_peak_rps < 200,
            'adjustment_reason': f"Limited by {safe_workload.get('bottleneck_limiting_factor', 'processing_time')} constraint on {safe_workload.get('bottleneck_node', 'unknown')}" if actual_base_rps < 80 or actual_peak_rps < 200 else None
        }
    }

    with open(os.path.join(episode_dir, 'safe_workload_analysis.json'), 'w') as f:
        json.dump(safe_workload_export, f, indent=2)

    if verbose:
        print(f"  ✓ Safe workload analysis saved to: {episode_dir}/safe_workload_analysis.json")

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
    # NEW: Pass semantic overlay to adapter
    adapter = TopologyAdapter(sim.env, semantic_overlay=semantic_overlay)
    registry = adapter.graph_to_registry(nx_graph)
    sim.component_registry = registry  # Directly set registry

    # Initialize simulation timestamp (normally done in sim.run())
    import time
    now_ns = int(time.time() * 1_000_000_000)
    duration_ns = int(cfg.duration * 1_000_000_000)
    sim.simulation_start_timestamp_ns = now_ns - duration_ns

    # 6.5. Setup Topology State Exporter
    topology_exporter = TopologyStateExporter(sim.env, episode_dir)

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
    valid_targets = [
        nid for nid, data in nx_graph.nodes(data=True)
        if data.get('role') == cfg.fault_target_role
    ]

    # This should never happen now since we pre-validate scenarios
    if not valid_targets:
        raise ValueError(f"Internal error: No valid targets for role '{cfg.fault_target_role}' in episode {episode_id}")

    # Select target with good propagation potential
    # Prefer targets with multiple upstream callers for better fault propagation
    def score_target_connectivity(target_node):
        """Score a target based on propagation potential."""
        # Count direct upstream callers (who will be impacted)
        predecessors = list(nx_graph.predecessors(target_node))
        num_callers = len(predecessors)

        # Count second-order callers (propagation depth)
        second_order = set()
        for pred in predecessors:
            second_order.update(nx_graph.predecessors(pred))

        # Higher score = better propagation potential
        # Prioritize: multiple direct callers + deep propagation potential
        return num_callers * 10 + len(second_order)

    # Score all targets and select from top candidates
    target_scores = [(t, score_target_connectivity(t)) for t in valid_targets]
    target_scores.sort(key=lambda x: x[1], reverse=True)

    # Select from top 50% to maintain some randomness but avoid worst cases
    top_half = max(1, len(target_scores) // 2)
    target_candidates = [t for t, score in target_scores[:top_half] if score > 0]

    # Fallback to all targets if no good candidates (shouldn't happen often)
    if not target_candidates:
        target_candidates = valid_targets
        if verbose:
            print(f"  Warning: No well-connected targets found, using all {len(valid_targets)} candidates")

    target_id = random.choice(target_candidates)
    target_score = next((score for t, score in target_scores if t == target_id), 0)

    if verbose and target_score > 0:
        print(f"  Selected target {target_id} (connectivity score: {target_score})")

    # Calculate gradual failure timeline:
    # - Start at 20% through episode (earlier than before to see healthy baseline)
    # - Apply gradually over 40% of episode duration
    # - Reach full effect at 60%, remains until end
    # FIXED: Added minimum 30s warmup to ensure system stabilizes before baseline measurement
    start_time = max(30, int(cfg.duration * 0.2))
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

    # NEW: Save semantic overlay
    semantic_path = os.path.join(episode_dir, 'semantic_map.json')
    with open(semantic_path, 'w') as f:
        json.dump(semantic_overlay, f, indent=2)

    if verbose:
        print(f"\n[Ground Truth]")
        print(f"  Label saved to: {label_path}")
        print(f"  Topology saved to: {topology_path}")
        print(f"  Semantic map saved to: {semantic_path}")
        print(f"  Topology: {topology_data['num_nodes']} nodes, {topology_data['num_edges']} edges")
        print(f"  Domain: {semantic_overlay.get('domain', 'unknown')}")

    # 9. Export Initial Topology State
    topology_exporter.export_initial_state()

    if verbose:
        print(f"\n[Initial Topology State]")
        print(f"  Exported initial snapshot at t=0")

    # 10. Run Simulation
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

        # 11. Auto-generate Fault Propagation Analysis
        if verbose:
            print(f"\n[Fault Propagation Analysis]")
            print(f"  Analyzing fault propagation...")

        try:
            output_path = os.path.join(episode_dir, 'fault_propagation.json')
            summary = analyze_episode(
                episode_dir=episode_dir,
                sample_interval=5,
                output_file=output_path
            )

            if verbose:
                print(f"  Fault propagation analysis saved to: {output_path}")
                print(f"  Quality Score: {summary.validation['quality_score']:.2f}/1.0")
                print(f"  Blast Radius: {summary.validation['blast_radius']} nodes")

        except Exception as e:
            # Don't fail the entire episode if analysis fails
            print(f"  Warning: Fault propagation analysis failed: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

        # 11.5. Run Forensic Analysis
        if verbose:
            print(f"\n[Forensic Analysis]")
            print(f"  Running comprehensive post-simulation forensic analysis...")

        try:
            forensic_report = forensic_analyze_episode(episode_dir)

            if verbose:
                print(f"  Forensic analysis complete:")
                print(f"    - Bottlenecks detected: {forensic_report.summary['total_bottlenecks']}")
                print(f"    - Components crashed: {forensic_report.summary['total_crashes']}")
                print(f"    - Crashes recovered: {forensic_report.summary['crashes_recovered']}")
                print(f"    - Cascades detected: {forensic_report.summary['total_cascades']}")
                print(f"    - Circuit breaker events: {forensic_report.summary['total_circuit_breaker_events']}")
                print(f"    - System recovered: {forensic_report.summary['system_recovered']}")
                print(f"    - Recovery recommendations: {len(forensic_report.recovery_recommendations)}")
                print(f"  Report saved to: {os.path.join(episode_dir, 'forensic_analysis.json')}")

        except Exception as e:
            # Don't fail the entire episode if forensic analysis fails
            print(f"  Warning: Forensic analysis failed: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

        # 12. Validate Baseline Health (Mathematical)
        if verbose:
            print(f"\n[Baseline Health Validation - Mathematical]")
            print(f"  Validating baseline health using queueing theory...")

        try:
            # Use mathematical validation
            is_valid, reason, validation_details = validate_system_health(
                metrics_file=Path(os.path.join(episode_dir, 'metrics.jsonl')),
                topology_file=Path(topology_path),
                fault_start_time=start_time,
                thresholds={
                    'max_utilization': 0.80,
                    'max_error_rate': 0.01,
                    'max_p99_ratio': 10.0,
                    'min_success_rate': 0.95,
                    'min_health_score': 0.80,
                }
            )

            if not is_valid:
                print(f"  ✗ Mathematical validation FAILED: {reason}")
                if verbose and validation_details:
                    print(f"\n  Node-level health details:")
                    for node_id, details in validation_details.items():
                        if not details['is_healthy']:
                            print(f"    {node_id}: {details['reason']}")
                            print(f"      Health score: {details['health_score']:.2f}")
                            print(f"      Error rate: {details['error_rate']:.2%}")
                            print(f"      Success rate: {details['success_rate']:.2%}")

                print(f"  This episode will be marked as INVALID and should be regenerated.")

                # Save validation failure to a marker file
                validation_marker = os.path.join(episode_dir, '.validation_failed')
                with open(validation_marker, 'w') as f:
                    json.dump({
                        'validation_type': 'mathematical',
                        'reason': reason,
                        'details': validation_details
                    }, f, indent=2)

                # Return None to indicate failure
                return None
            else:
                if verbose:
                    print(f"  ✓ Mathematical validation PASSED: {reason}")
                    # Show summary of healthiest and weakest nodes
                    if validation_details:
                        health_scores = {k: v['health_score'] for k, v in validation_details.items() if v['is_healthy']}
                        if health_scores:
                            weakest = min(health_scores, key=health_scores.get)
                            healthiest = max(health_scores, key=health_scores.get)
                            print(f"    Weakest node: {weakest} (score: {health_scores[weakest]:.2f})")
                            print(f"    Healthiest node: {healthiest} (score: {health_scores[healthiest]:.2f})")

        except Exception as e:
            print(f"  Warning: Mathematical validation failed with error: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

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


def _generate_episode_process(episode_id, run_dir, verbose, topology_size, force_fault_type, force_fault_role):
    """
    Wrapper function to run generate_episode in a separate process.
    Each process has completely fresh global state (including OpenTelemetry).
    """
    lib = ScenarioLibrary()
    return generate_episode(episode_id, run_dir, lib, verbose=verbose, topology_size=topology_size, force_fault_type=force_fault_type, force_fault_role=force_fault_role)


def generate_dataset(num_episodes: int, output_dir: str, verbose: bool = False, topology_size: int = None, force_fault_type: str = None, force_fault_role: str = None):
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
    """
    print(f"\n{'='*60}")
    print(f"SPATIOTEMPORAL DATA FACTORY")
    print(f"{'='*60}")
    print(f"Generating {num_episodes} training episodes...")
    print(f"Base output directory: {output_dir}")
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
                args=(i, run_dir, verbose, topology_size, force_fault_type, force_fault_role)
            )
            process.start()
            process.join()  # Wait for completion

            # Check if episode was successful by looking for the label file
            episode_dir = os.path.join(run_dir, f'ep_{i}')
            label_path = os.path.join(episode_dir, 'label.json')
            validation_failed_marker = os.path.join(episode_dir, '.validation_failed')

            if os.path.exists(validation_failed_marker):
                # Episode failed validation, clean up and retry
                print(f"Episode {i} failed baseline validation (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    # Clean up the failed episode directory for retry
                    import shutil
                    if os.path.exists(episode_dir):
                        shutil.rmtree(episode_dir)
                    continue
                else:
                    print(f"Episode {i} failed after {max_retries} attempts\n")
                    break

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

    args = parser.parse_args()

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
        force_fault_role=args.fault_role
    )


if __name__ == "__main__":
    main()
