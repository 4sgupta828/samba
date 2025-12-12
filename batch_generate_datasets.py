#!/usr/bin/env python3
"""
Batch Dataset Generator - Generate datasets for all fault types and topologies.

This script orchestrates dataset generation for GNN training by iterating through
all combinations of fault types and topologies in the bank. It handles:
- Timeouts (10 minute limit per run)
- Error recovery (continue on failure)
- Clear logging and progress tracking
- Retry failed runs later

Usage:
    python batch_generate_datasets.py --episodes-per-config 5 --output data/batch_run
    python batch_generate_datasets.py --retry failed_runs.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

# Fault type configurations - synchronized with viz/app.py VALID_FAULT_COMBINATIONS
FAULT_CONFIGS = [
    # Level 1: Core Resource Saturation (service-level)
    {'fault_type': 'cpu_saturation', 'fault_role': 'service', 'level': 1},
    {'fault_type': 'memory_leak', 'fault_role': 'service', 'level': 1},
    {'fault_type': 'memory_pressure', 'fault_role': 'service', 'level': 1},
    {'fault_type': 'memory_thrashing', 'fault_role': 'service', 'level': 1},
    {'fault_type': 'thread_exhaustion', 'fault_role': 'service', 'level': 1},

    # Level 2: Database-specific resource saturation
    {'fault_type': 'thread_exhaustion', 'fault_role': 'database', 'level': 2},
    {'fault_type': 'disk_io_saturation', 'fault_role': 'database', 'level': 2},

    # Level 3: Interaction Failures - service latency/errors
    {'fault_type': 'inject_latency', 'fault_role': 'service', 'level': 3},
    {'fault_type': 'inject_errors', 'fault_role': 'service', 'level': 3},

    # Level 4: Interaction Failures - cache/queue/external
    {'fault_type': 'cache_failure', 'fault_role': 'cache', 'level': 4},
    {'fault_type': 'inject_latency', 'fault_role': 'cache', 'level': 4},
    {'fault_type': 'queue_consumer_slowdown', 'fault_role': 'queue', 'level': 4},
    {'fault_type': 'inject_latency', 'fault_role': 'external', 'level': 4},
    {'fault_type': 'inject_errors', 'fault_role': 'external', 'level': 4},

    # Level 5: Structural/Distributed Faults
    {'fault_type': 'noisy_neighbor', 'fault_role': 'service', 'level': 5},
    {'fault_type': 'hot_shard', 'fault_role': 'service', 'level': 5},
    {'fault_type': 'force_deadlock', 'fault_role': 'service', 'level': 5},
    {'fault_type': 'network_partition', 'fault_role': 'network', 'level': 5},
]


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def get_topology_bank_dirs(topology_bank_path: str = "data/topology_bank") -> List[str]:
    """Get all topology directories from the topology bank."""
    bank_path = Path(topology_bank_path)
    if not bank_path.exists():
        print(f"{Colors.FAIL}Error: Topology bank not found at {topology_bank_path}{Colors.ENDC}")
        sys.exit(1)

    topologies = [d.name for d in bank_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
    return sorted(topologies)


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def run_dataset_generation(
    fault_config: Dict,
    topology_name: str,
    episodes: int,
    output_dir: str,
    timeout_seconds: int = 600,
    verbose: bool = False
) -> Tuple[bool, str, float, Dict]:
    """
    Run dataset generation for a specific fault-topology combination.

    Returns:
        Tuple of (success, error_message, duration, metadata)
    """
    start_time = time.time()

    # Build command (use python3 explicitly for macOS compatibility)
    cmd = [
        'python3', 'generate_dataset.py',
        '--llm-topologies',
        '--topology-name', topology_name,
        '--fault-type', fault_config['fault_type'],
        '--fault-role', fault_config['fault_role'],
        '--episodes', str(episodes),
        '--output', output_dir,
    ]

    if verbose:
        cmd.append('-v')

    config_name = f"{fault_config['fault_type']}_{fault_config['fault_role']}_{topology_name}"

    print(f"{Colors.OKCYAN}▶ Starting: {config_name}{Colors.ENDC}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Timeout: {timeout_seconds}s ({timeout_seconds//60}m)")

    try:
        # Run with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=os.getcwd()
        )

        duration = time.time() - start_time

        if result.returncode == 0:
            print(f"{Colors.OKGREEN}✓ Success: {config_name} ({format_duration(duration)}){Colors.ENDC}")
            return True, "", duration, {
                'stdout': result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout,  # Last 1000 chars
                'stderr': result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
            }
        else:
            error_msg = f"Exit code {result.returncode}"
            print(f"{Colors.FAIL}✗ Failed: {config_name} ({error_msg}){Colors.ENDC}")
            print(f"  Error output: {result.stderr[-500:]}")  # Last 500 chars
            return False, error_msg, duration, {
                'stdout': result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout,
                'stderr': result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
            }

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        error_msg = f"Timeout after {timeout_seconds}s"
        print(f"{Colors.WARNING}⏱ Timeout: {config_name} (exceeded {timeout_seconds}s){Colors.ENDC}")
        return False, error_msg, duration, {}

    except Exception as e:
        duration = time.time() - start_time
        error_msg = str(e)
        print(f"{Colors.FAIL}✗ Error: {config_name} ({error_msg}){Colors.ENDC}")
        return False, error_msg, duration, {}


def save_progress(
    output_file: str,
    results: List[Dict],
    failed: List[Dict]
):
    """Save progress to JSON files."""
    # Save all results
    results_file = output_file.replace('.json', '_results.json')
    with open(results_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total_runs': len(results),
            'successful': len([r for r in results if r['success']]),
            'failed': len([r for r in results if not r['success']]),
            'results': results
        }, f, indent=2)

    # Save failed runs for retry
    if failed:
        failed_file = output_file.replace('.json', '_failed.json')
        with open(failed_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'failed_count': len(failed),
                'failed_runs': failed
            }, f, indent=2)
        print(f"\n{Colors.WARNING}Failed runs saved to: {failed_file}{Colors.ENDC}")

    print(f"Results saved to: {results_file}")


def print_summary(results: List[Dict], total_duration: float):
    """Print execution summary."""
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]

    print(f"\n{Colors.HEADER}{'='*70}")
    print(f"BATCH GENERATION SUMMARY")
    print(f"{'='*70}{Colors.ENDC}")
    print(f"Total runs: {len(results)}")
    print(f"{Colors.OKGREEN}Successful: {len(successful)}{Colors.ENDC}")
    print(f"{Colors.FAIL}Failed: {len(failed)}{Colors.ENDC}")
    print(f"Total duration: {format_duration(total_duration)}")

    if successful:
        avg_duration = sum(r['duration'] for r in successful) / len(successful)
        print(f"Average duration (successful): {format_duration(avg_duration)}")

    if failed:
        print(f"\n{Colors.WARNING}Failed runs:{Colors.ENDC}")
        for r in failed:
            print(f"  - {r['fault_type']}_{r['fault_role']}_{r['topology']}: {r['error']}")

    print(f"{Colors.HEADER}{'='*70}{Colors.ENDC}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Batch generate datasets for all fault types and topologies",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-e', '--episodes-per-config',
        type=int,
        default=5,
        help='Number of episodes to generate per fault-topology combination'
    )
    parser.add_argument(
        '-o', '--output',
        default='data',
        help='Base output directory for datasets'
    )
    parser.add_argument(
        '--topology-bank',
        default='data/topology_bank',
        help='Path to topology bank directory'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=600,
        help='Timeout in seconds for each dataset generation (default: 600s = 10 minutes)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output for each dataset generation'
    )
    parser.add_argument(
        '--retry',
        type=str,
        default=None,
        help='Retry failed runs from a previous batch (provide path to *_failed.json file)'
    )
    parser.add_argument(
        '--filter-fault',
        type=str,
        default=None,
        help='Only run specific fault type (e.g., cpu_saturation)'
    )
    parser.add_argument(
        '--filter-topology',
        type=str,
        default=None,
        help='Only run specific topology (e.g., hierarchical_medium_0)'
    )
    parser.add_argument(
        '--results-file',
        default='batch_results.json',
        help='Output file for results (in current directory)'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt and start immediately'
    )

    args = parser.parse_args()

    # Load retry configuration if provided
    if args.retry:
        print(f"{Colors.HEADER}RETRY MODE: Loading failed runs from {args.retry}{Colors.ENDC}\n")
        with open(args.retry, 'r') as f:
            retry_data = json.load(f)

        # Convert failed runs back to configs
        configs_to_run = []
        for run in retry_data['failed_runs']:
            configs_to_run.append({
                'fault_config': {
                    'fault_type': run['fault_type'],
                    'fault_role': run['fault_role'],
                    'level': run.get('level', 1)
                },
                'topology': run['topology']
            })
    else:
        # Get all topologies
        topologies = get_topology_bank_dirs(args.topology_bank)

        # Apply filters
        fault_configs = FAULT_CONFIGS
        if args.filter_fault:
            fault_configs = [fc for fc in fault_configs if fc['fault_type'] == args.filter_fault]

        if args.filter_topology:
            topologies = [t for t in topologies if t == args.filter_topology]

        # Generate all combinations
        configs_to_run = [
            {'fault_config': fc, 'topology': topo}
            for fc in fault_configs
            for topo in topologies
        ]

    total_configs = len(configs_to_run)

    # Create timestamped batch run directory name (preview)
    batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_run_dir_preview = os.path.join(args.output, f"batch_run_{batch_timestamp}")

    # Print header
    print(f"{Colors.HEADER}{'='*70}")
    print(f"BATCH DATASET GENERATION")
    print(f"{'='*70}{Colors.ENDC}")
    print(f"Total configurations: {total_configs}")
    print(f"Episodes per config: {args.episodes_per_config}")
    print(f"Total episodes to generate: {total_configs * args.episodes_per_config}")
    print(f"Timeout per run: {args.timeout}s ({args.timeout//60}m)")
    print(f"Estimated max duration: {format_duration(total_configs * args.timeout)}")
    print(f"Base output directory: {args.output}")
    print(f"Batch run directory: {batch_run_dir_preview}")
    print(f"{Colors.HEADER}{'='*70}{Colors.ENDC}\n")

    # Confirm start (unless --yes flag is used)
    if not args.yes:
        response = input(f"Start batch generation? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return

    # Create timestamped batch run directory
    batch_run_dir = os.path.join(args.output, f"batch_run_{batch_timestamp}")
    os.makedirs(batch_run_dir, exist_ok=True)

    print(f"{Colors.OKGREEN}Created batch run directory: {batch_run_dir}{Colors.ENDC}\n")

    # Run all configurations
    results = []
    failed_runs = []
    batch_start_time = time.time()

    for idx, config in enumerate(configs_to_run, 1):
        fault_config = config['fault_config']
        topology = config['topology']

        print(f"\n{Colors.BOLD}[{idx}/{total_configs}] Processing: {fault_config['fault_type']} / {fault_config['fault_role']} / {topology}{Colors.ENDC}")

        success, error_msg, duration, metadata = run_dataset_generation(
            fault_config=fault_config,
            topology_name=topology,
            episodes=args.episodes_per_config,
            output_dir=batch_run_dir,
            timeout_seconds=args.timeout,
            verbose=args.verbose
        )

        result = {
            'fault_type': fault_config['fault_type'],
            'fault_role': fault_config['fault_role'],
            'level': fault_config['level'],
            'topology': topology,
            'episodes': args.episodes_per_config,
            'success': success,
            'error': error_msg,
            'duration': duration,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata
        }

        results.append(result)

        if not success:
            failed_runs.append(result)

        # Save progress periodically (every 10 runs)
        if idx % 10 == 0 or idx == total_configs:
            progress_results_file = os.path.join(batch_run_dir, 'batch_results.json')
            save_progress(progress_results_file, results, failed_runs)

    batch_duration = time.time() - batch_start_time

    # Save results to batch run directory
    batch_results_file = os.path.join(batch_run_dir, 'batch_results.json')
    save_progress(batch_results_file, results, failed_runs)

    # Print summary
    print_summary(results, batch_duration)

    # Exit with appropriate code
    sys.exit(0 if not failed_runs else 1)


if __name__ == "__main__":
    main()
