#!/usr/bin/env python3
"""
Test full simulation pipeline with external service fault injection.
Mimics generate_dataset.py but with debugging.
"""
import simpy
import sys
import json
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.topology.generator import TopologyGenerator
from src.topology.adapter import TopologyAdapter
from src.scenarios.library import ScenarioLibrary
from src.simulation import Simulation
from src.failures.training_injector import TrainingFailureInjector
import random

def test_full_pipeline():
    """Test the full simulation pipeline with external service fault."""

    print(f"\n{'='*70}")
    print("FULL PIPELINE TEST - External Service Fault Injection")
    print(f"{'='*70}")

    # 1. Generate a simple topology with external service
    print("\n[Step 1] Generating topology...")
    topo_gen = TopologyGenerator(seed=12345)
    nx_graph = topo_gen.generate_complex_graph(num_nodes=10)

    # Check if external service exists
    external_nodes = [
        (nid, data) for nid, data in nx_graph.nodes(data=True)
        if data.get('role') == 'external'
    ]

    print(f"  Total nodes: {nx_graph.number_of_nodes()}")
    print(f"  External service nodes: {len(external_nodes)}")
    if external_nodes:
        for nid, data in external_nodes:
            print(f"    - {nid}: type={data.get('type')}, role={data.get('role')}")

    if not external_nodes:
        print("  ERROR: No external service nodes in topology!")
        return False

    # 2. Setup simulation config (minimal)
    print("\n[Step 2] Setting up simulation...")
    episode_dir = tempfile.mkdtemp(prefix='test_ext_fault_')
    print(f"  Output dir: {episode_dir}")

    sim_config = {
        'simulation': {
            'duration': 60,  # 1 minute
            'output_dir': episode_dir
        },
        'telemetry': {
            'metric_export_interval': 5,
            'exporter_type': 'file'
        },
        'workload': {
            'path': None  # Will create dummy workload
        },
        'infrastructure': {
            'path': 'generated_internal'
        }
    }

    # Create minimal workload file
    frontends = [n for n, d in nx_graph.nodes(data=True) if d.get('is_frontend')]
    if not frontends:
        frontends = [n for n, d in nx_graph.nodes(data=True) if d.get('role') == 'service']

    workload_config = {
        'name': 'Test Workload',
        'pattern': 'constant',
        'baseline_rps': 50,
        'peak_rps': 50,
        'request_mix': [{'type': 'GET', 'service': frontends[0], 'weight': 100}]
    }

    workload_path = os.path.join(episode_dir, 'workload.yaml')
    import yaml
    with open(workload_path, 'w') as f:
        yaml.dump(workload_config, f)

    sim_config['workload']['path'] = workload_path

    # 3. Initialize simulation
    sim = Simulation(sim_config)

    # 4. Build component registry from topology
    print("\n[Step 3] Building component registry...")
    adapter = TopologyAdapter(sim.env)
    registry = adapter.graph_to_registry(nx_graph)
    sim.component_registry = registry

    print(f"  Registry size: {len(registry)}")
    print(f"  Registry keys: {list(registry.keys())[:10]}...")

    # Check if external service is in registry
    external_in_registry = [k for k in registry.keys() if 'ext' in k]
    print(f"  External services in registry: {external_in_registry}")

    if not external_in_registry:
        print("  ERROR: No external service in registry!")
        return False

    target_id = external_in_registry[0]
    target_component = registry[target_id]

    print(f"\n[Step 4] Target component details:")
    print(f"  ID: {target_id}")
    print(f"  Type: {target_component.type}")
    print(f"  Has forced_error_rate: {hasattr(target_component, 'forced_error_rate')}")
    print(f"  Initial forced_error_rate: {getattr(target_component, 'forced_error_rate', 'N/A')}")

    # 5. Initialize injector
    print("\n[Step 5] Initializing fault injector...")
    injector = TrainingFailureInjector(
        env=sim.env,
        component_registry=registry,
        tracker=sim.tracker,
        simulation_start_timestamp_ns=0
    )

    # 6. Inject fault
    print("\n[Step 6] Injecting fault...")
    print(f"  Target: {target_id}")
    print(f"  Fault type: inject_errors")
    print(f"  Error rate: 0.3")
    print(f"  Start time: 10s")
    print(f"  Duration: 20s")

    injector.inject_gradual_failure(
        target_id=target_id,
        failure_mode='inject_errors',
        start_time=10.0,
        duration=20.0,
        params={'error_rate': 0.3},
        progression='step',
        episode_id='test_full'
    )

    # 7. Run simulation
    print("\n[Step 7] Running simulation...")
    print(f"  Duration: 60s")

    # Check forced_error_rate at different times
    def check_error_rate():
        """Background process to check error rate periodically."""
        for t in [0, 5, 15, 25, 35, 45]:
            yield sim.env.timeout(t if t == 0 else 10)
            current_rate = getattr(target_component, 'forced_error_rate', -1)
            print(f"  [t={sim.env.now:.0f}s] forced_error_rate = {current_rate:.2f}")

    sim.env.process(check_error_rate())

    # Run simulation (don't use sim.run() as it might have workload/gateway issues)
    try:
        sim.env.run(until=60)
    except Exception as e:
        print(f"  Simulation error (expected if no workload): {e}")

    # 8. Verify final state
    print("\n[Step 8] Final verification:")
    final_rate = getattr(target_component, 'forced_error_rate', -1)
    print(f"  Final forced_error_rate: {final_rate}")
    print(f"  Expected: 0.3")

    # 9. Check if any traces/logs were generated
    print("\n[Step 9] Checking output files...")
    logs_file = os.path.join(episode_dir, 'logs.jsonl')
    if os.path.exists(logs_file):
        with open(logs_file) as f:
            logs = [json.loads(line) for line in f]
        error_inject_logs = [
            l for l in logs
            if 'inject' in l.get('message', '').lower() or 'error' in l.get('message', '').lower()
        ]
        print(f"  Total logs: {len(logs)}")
        print(f"  Error injection logs: {len(error_inject_logs)}")
        if error_inject_logs:
            print("\n  Sample error injection logs:")
            for log in error_inject_logs[:3]:
                print(f"    - [{log.get('level')}] {log.get('message')}")
    else:
        print(f"  No logs file found at {logs_file}")

    # Cleanup
    import shutil
    shutil.rmtree(episode_dir, ignore_errors=True)

    # Final result
    print(f"\n{'='*70}")
    if final_rate == 0.3:
        print("✓ TEST PASSED - Fault injection worked in full pipeline")
        print(f"{'='*70}")
        return True
    else:
        print("✗ TEST FAILED - Fault injection did not work")
        print(f"  Expected: 0.3, Got: {final_rate}")
        print(f"{'='*70}")
        return False

if __name__ == '__main__':
    success = test_full_pipeline()
    sys.exit(0 if success else 1)
