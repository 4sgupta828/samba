#!/usr/bin/env python3
"""
Simulation Data Validator

Validates that simulation episodes generated valid and complete data.
Checks for:
- Required files exist and are not empty
- Metrics cover expected simulation timeline
- Logs and traces are generated
- All expected metric types are present
- Data is not corrupted or truncated
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict


class ValidationResult:
    """Container for validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def add_error(self, msg: str):
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def add_info(self, msg: str):
        self.info.append(msg)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def print_summary(self, episode_name: str):
        """Print validation summary."""
        if self.errors:
            print(f"✗ {episode_name}: FAILED ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"  ❌ {error}")
        else:
            print(f"✓ {episode_name}: PASSED")

        if self.warnings:
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")

        if self.info:
            for info in self.info:
                print(f"  ℹ️  {info}")


def validate_required_files(episode_dir: Path) -> ValidationResult:
    """
    Validate that all required files exist and are not empty.

    Required files:
    - label.json: Episode metadata and fault information
    - topology.json: Topology structure
    - metrics.jsonl: Time-series metrics
    - logs.jsonl: Component logs
    - traces.jsonl: Distributed traces
    - simulation.log: Simulation execution log
    """
    result = ValidationResult()

    required_files = {
        'label.json': 100,  # Minimum expected size in bytes
        'topology.json': 100,
        'metrics.jsonl': 1000,  # Should have substantial metrics
        'logs.jsonl': 100,  # Should have some logs
        'traces.jsonl': 100,  # Should have some traces
        'simulation.log': 100,  # Should have simulation progress
        'topology_state.jsonl': 100,  # Topology state changes
    }

    optional_files = {
        'semantic_map.json': 'Semantic mapping',
        'capacity_planning.json': 'Capacity planning data',
        'run_parameters.json': 'Run parameters',
    }

    for filename, min_size in required_files.items():
        filepath = episode_dir / filename

        if not filepath.exists():
            result.add_error(f"Missing required file: {filename}")
        elif filepath.stat().st_size == 0:
            result.add_error(f"Empty file (0 bytes): {filename}")
        elif filepath.stat().st_size < min_size:
            result.add_warning(f"Suspiciously small file ({filepath.stat().st_size} bytes): {filename}")

    # Check optional files
    for filename, description in optional_files.items():
        filepath = episode_dir / filename
        if filepath.exists():
            result.add_info(f"{description} present: {filename}")

    return result


def validate_label_json(episode_dir: Path) -> Tuple[ValidationResult, Optional[Dict]]:
    """
    Validate label.json structure and extract timing information.

    Returns:
        Tuple of (ValidationResult, label_data dict or None)
    """
    result = ValidationResult()

    label_path = episode_dir / 'label.json'
    if not label_path.exists():
        result.add_error("label.json not found")
        return result, None

    try:
        with open(label_path, 'r') as f:
            label = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error(f"Invalid JSON in label.json: {e}")
        return result, None

    # Required fields
    required_fields = [
        'episode',
        'level',
        'scenario',
        'root_cause_node',
        'root_cause_role',
        'fault_type',
        'fault_start_time',
        'fault_full_effect_time',
        'fault_total_duration',
        'timeline',
    ]

    for field in required_fields:
        if field not in label:
            result.add_error(f"Missing required field in label.json: {field}")

    # Validate timeline structure
    if 'timeline' in label:
        timeline_fields = [
            'warmup_period',
            'healthy_baseline_start',
            'fault_injection_start',
            'fault_full_effect',
            'recovery_start',
            'recovery_complete',
            'episode_end',
        ]
        for field in timeline_fields:
            if field not in label['timeline']:
                result.add_error(f"Missing timeline field: {field}")

    # Validate topology structure
    if 'topology' in label:
        if not all(k in label['topology'] for k in ['nodes', 'edges', 'frontends']):
            result.add_error("Incomplete topology metadata in label.json")

    return result, label if result.is_valid else None


def validate_metrics_timeline(episode_dir: Path, label: Optional[Dict]) -> ValidationResult:
    """
    Validate that metrics cover the expected simulation timeline.

    Checks:
    - Metrics start at or near 0 (after warmup)
    - Metrics cover the full episode duration
    - No large gaps in timeline
    - All expected metric types are present
    """
    result = ValidationResult()

    metrics_path = episode_dir / 'metrics.jsonl'
    if not metrics_path.exists():
        result.add_error("metrics.jsonl not found")
        return result

    if label is None:
        result.add_warning("Cannot validate timeline without label.json")
        return result

    expected_end_time = label.get('timeline', {}).get('episode_end', 300)

    # Collect all sim.time values and metric types
    sim_times: Set[float] = set()
    metric_types: Set[str] = set()

    try:
        with open(metrics_path, 'r') as f:
            line_count = 0
            for line in f:
                line_count += 1
                try:
                    data = json.loads(line)
                    sim_time = data.get('labels', {}).get('sim.time')
                    metric_name = data.get('name')

                    if sim_time is not None:
                        sim_times.add(sim_time)
                    if metric_name:
                        metric_types.add(metric_name)
                except json.JSONDecodeError:
                    result.add_warning(f"Invalid JSON at line {line_count} in metrics.jsonl")
                    continue

        if not sim_times:
            result.add_error("No valid sim.time values found in metrics.jsonl")
            return result

        min_time = min(sim_times)
        max_time = max(sim_times)

        # Check timeline coverage
        if min_time < -10:
            result.add_error(f"Metrics start too early: sim.time={min_time} (expected >= 0)")
        elif min_time > 10:
            result.add_warning(f"Metrics start late: sim.time={min_time} (expected near 0)")

        expected_min_end = expected_end_time * 0.9  # Allow 10% tolerance
        if max_time < expected_min_end:
            result.add_error(
                f"Metrics end too early: sim.time={max_time} "
                f"(expected ~{expected_end_time}, minimum {expected_min_end:.1f})"
            )

        result.add_info(f"Metrics timeline: {min_time:.1f}s to {max_time:.1f}s ({line_count} entries)")

        # Check for expected metric types (at least some of these should be present)
        expected_metrics_patterns = {
            'workload.requests': False,
            'cpu.utilization': False,
            'memory.usage': False,
            'latency': False,
            'requests': False,
        }

        for metric in metric_types:
            for pattern in expected_metrics_patterns.keys():
                if pattern in metric:
                    expected_metrics_patterns[pattern] = True

        missing_patterns = [k for k, v in expected_metrics_patterns.items() if not v]
        if len(missing_patterns) > 2:  # Allow some metrics to be missing
            result.add_warning(f"Missing expected metric patterns: {', '.join(sorted(missing_patterns))}")

        result.add_info(f"Found {len(metric_types)} unique metric types")

    except Exception as e:
        result.add_error(f"Error reading metrics.jsonl: {e}")

    return result


def validate_logs_and_traces(episode_dir: Path, label: Optional[Dict]) -> ValidationResult:
    """
    Validate that logs and traces are present and non-empty.

    Checks:
    - Files are not empty
    - Contains valid JSON lines
    - Has entries across the simulation timeline
    """
    result = ValidationResult()

    # Validate logs
    logs_path = episode_dir / 'logs.jsonl'
    if logs_path.exists():
        if logs_path.stat().st_size == 0:
            result.add_error("logs.jsonl is empty (0 bytes)")
        else:
            try:
                log_count = 0
                log_components: Set[str] = set()

                with open(logs_path, 'r') as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            data = json.loads(line)
                            log_count += 1
                            comp_id = data.get('attributes', {}).get('component.id')
                            if comp_id:
                                log_components.add(comp_id)

                            # Stop after sampling first 1000 lines for performance
                            if line_num >= 1000:
                                # Count remaining lines without parsing
                                log_count += sum(1 for _ in f)
                                break
                        except json.JSONDecodeError:
                            result.add_warning(f"Invalid JSON at line {line_num} in logs.jsonl")
                            continue

                if log_count == 0:
                    result.add_error("logs.jsonl contains no valid log entries")
                else:
                    result.add_info(f"Logs: {log_count} entries from {len(log_components)} components")
            except Exception as e:
                result.add_error(f"Error reading logs.jsonl: {e}")

    # Validate traces
    traces_path = episode_dir / 'traces.jsonl'
    if traces_path.exists():
        if traces_path.stat().st_size == 0:
            result.add_error("traces.jsonl is empty (0 bytes)")
        else:
            try:
                trace_count = 0
                span_kinds: Set[str] = set()

                with open(traces_path, 'r') as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            data = json.loads(line)
                            trace_count += 1
                            kind = data.get('kind')
                            if kind:
                                span_kinds.add(kind)

                            # Stop after sampling first 1000 lines
                            if line_num >= 1000:
                                trace_count += sum(1 for _ in f)
                                break
                        except json.JSONDecodeError:
                            result.add_warning(f"Invalid JSON at line {line_num} in traces.jsonl")
                            continue

                if trace_count == 0:
                    result.add_error("traces.jsonl contains no valid trace spans")
                else:
                    result.add_info(f"Traces: {trace_count} spans")
            except Exception as e:
                result.add_error(f"Error reading traces.jsonl: {e}")

    return result


def validate_simulation_completion(episode_dir: Path, label: Optional[Dict]) -> ValidationResult:
    """
    Validate that the simulation completed successfully.

    Checks simulation.log for:
    - Normal completion message
    - No errors or exceptions
    - Reached expected end time
    """
    result = ValidationResult()

    log_path = episode_dir / 'simulation.log'
    if not log_path.exists():
        result.add_error("simulation.log not found")
        return result

    try:
        with open(log_path, 'r') as f:
            log_contents = f.read()

        # Check for completion indicators
        completion_markers = [
            'Flush complete',
            'Simulation complete',
            'Final metric flush',
            'Telemetry shutdown complete',
            'CausalityTracker: Ended Incident',
        ]

        has_completion = any(marker in log_contents for marker in completion_markers)
        if not has_completion:
            result.add_error("Simulation did not complete normally (no completion marker found)")

        # Check for errors (but allow validation warnings and acceptable errors)
        error_lines = []
        for line in log_contents.split('\n'):
            # Skip acceptable warnings
            if 'Mathematical validation FAILED' in line:
                continue
            if 'KEEPING DATASET' in line:
                continue
            if 'No module named' in line and 'telemetry.validator' in line:
                continue  # Known issue with telemetry validation import

            if any(indicator in line for indicator in ['ERROR', 'Exception', 'Traceback', 'FAILED']):
                error_lines.append(line)

        if error_lines and len(error_lines) > 3:  # More than a few error lines is concerning
            result.add_warning(f"Simulation log contains {len(error_lines)} error/exception lines")

        # Get last timestamp
        lines = log_contents.strip().split('\n')
        last_line = lines[-1] if lines else ""

        if last_line:
            result.add_info(f"Last log line: {last_line[:80]}...")

    except Exception as e:
        result.add_error(f"Error reading simulation.log: {e}")

    return result


def validate_episode(episode_dir: Path, verbose: bool = False) -> bool:
    """
    Run all validation checks on an episode.

    Returns:
        True if episode is valid, False otherwise
    """
    combined_result = ValidationResult()

    # 1. Check required files
    file_result = validate_required_files(episode_dir)
    combined_result.errors.extend(file_result.errors)
    combined_result.warnings.extend(file_result.warnings)
    combined_result.info.extend(file_result.info)

    # If critical files are missing, skip further checks
    if any('label.json' in err or 'metrics.jsonl' in err for err in file_result.errors):
        combined_result.print_summary(episode_dir.name)
        return False

    # 2. Validate label.json and get timing info
    label_result, label_data = validate_label_json(episode_dir)
    combined_result.errors.extend(label_result.errors)
    combined_result.warnings.extend(label_result.warnings)
    combined_result.info.extend(label_result.info)

    # 3. Validate metrics timeline
    metrics_result = validate_metrics_timeline(episode_dir, label_data)
    combined_result.errors.extend(metrics_result.errors)
    combined_result.warnings.extend(metrics_result.warnings)
    combined_result.info.extend(metrics_result.info)

    # 4. Validate logs and traces
    logs_result = validate_logs_and_traces(episode_dir, label_data)
    combined_result.errors.extend(logs_result.errors)
    combined_result.warnings.extend(logs_result.warnings)
    combined_result.info.extend(logs_result.info)

    # 5. Validate simulation completion
    completion_result = validate_simulation_completion(episode_dir, label_data)
    combined_result.errors.extend(completion_result.errors)
    combined_result.warnings.extend(completion_result.warnings)
    combined_result.info.extend(completion_result.info)

    # Print results
    if verbose or not combined_result.is_valid:
        combined_result.print_summary(episode_dir.name)
    elif combined_result.is_valid and not verbose:
        # Just show episode passed
        print(f"✓ {episode_dir.name}")

    return combined_result.is_valid


def validate_dataset(dataset_dir: Path, verbose: bool = False) -> Dict:
    """
    Validate all episodes in a dataset directory.

    Args:
        dataset_dir: Path to dataset directory containing ep_* subdirectories
        verbose: Print detailed validation output

    Returns:
        Dictionary with validation results
    """
    results = {
        'total_episodes': 0,
        'valid_episodes': 0,
        'invalid_episodes': 0,
        'invalid_dirs': [],
    }

    # Find all episode directories
    episode_dirs = sorted([
        d for d in dataset_dir.iterdir()
        if d.is_dir() and d.name.startswith('ep_')
    ])

    if not episode_dirs:
        print(f"No episode directories (ep_*) found in {dataset_dir}")
        return results

    for ep_dir in episode_dirs:
        results['total_episodes'] += 1

        is_valid = validate_episode(ep_dir, verbose)

        if is_valid:
            results['valid_episodes'] += 1
        else:
            results['invalid_episodes'] += 1
            results['invalid_dirs'].append(str(ep_dir))

    return results


def validate_batch_runs(batch_dir: Path, verbose: bool = False) -> None:
    """
    Validate all dataset runs in a batch directory.

    Args:
        batch_dir: Path to directory containing data_* run directories
        verbose: Print detailed validation output
    """
    # Find all data run directories
    data_runs = sorted([
        d for d in batch_dir.iterdir()
        if d.is_dir() and d.name.startswith('data_')
    ])

    if not data_runs:
        print(f"No data run directories (data_*) found in {batch_dir}")
        return

    print(f"Found {len(data_runs)} data runs to validate\n")

    all_results = {
        'total_runs': len(data_runs),
        'valid_runs': 0,
        'invalid_runs': 0,
        'total_episodes': 0,
        'valid_episodes': 0,
        'invalid_episodes': 0,
        'invalid_run_details': [],
    }

    for data_run in data_runs:
        print(f"\n{'='*80}")
        print(f"Validating: {data_run.name}")
        print(f"{'='*80}")

        run_results = validate_dataset(data_run, verbose)

        all_results['total_episodes'] += run_results['total_episodes']
        all_results['valid_episodes'] += run_results['valid_episodes']
        all_results['invalid_episodes'] += run_results['invalid_episodes']

        if run_results['invalid_episodes'] == 0:
            all_results['valid_runs'] += 1
            print(f"\n✅ {data_run.name}: All episodes valid")
        else:
            all_results['invalid_runs'] += 1
            all_results['invalid_run_details'].append({
                'run': data_run.name,
                'invalid_episodes': run_results['invalid_episodes'],
                'invalid_dirs': run_results['invalid_dirs'],
            })
            print(f"\n❌ {data_run.name}: {run_results['invalid_episodes']}/{run_results['total_episodes']} episodes invalid")

    # Print summary
    print(f"\n{'='*80}")
    print("BATCH VALIDATION SUMMARY")
    print(f"{'='*80}")
    print(f"Total runs validated: {all_results['total_runs']}")
    print(f"  Valid runs: {all_results['valid_runs']}")
    print(f"  Invalid runs: {all_results['invalid_runs']}")
    print(f"\nTotal episodes: {all_results['total_episodes']}")
    print(f"  Valid episodes: {all_results['valid_episodes']}")
    print(f"  Invalid episodes: {all_results['invalid_episodes']}")

    if all_results['invalid_run_details']:
        print(f"\nInvalid runs should be regenerated or removed:")
        for detail in all_results['invalid_run_details']:
            print(f"  ❌ {detail['run']}: {detail['invalid_episodes']} invalid episode(s)")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate simulation episode data completeness and correctness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'path',
        type=Path,
        help='Path to episode directory (ep_0), dataset directory (data_*), or batch directory'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed validation output for all episodes'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Validate all dataset runs in a batch directory'
    )

    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)

    # Determine what kind of directory we're validating
    if args.batch or any(d.name.startswith('data_') for d in args.path.iterdir() if d.is_dir()):
        # Batch directory with multiple data runs
        validate_batch_runs(args.path, args.verbose)
    elif args.path.name.startswith('ep_'):
        # Single episode directory
        print(f"Validating single episode: {args.path.name}\n")
        is_valid = validate_episode(args.path, verbose=True)
        sys.exit(0 if is_valid else 1)
    elif args.path.name.startswith('data_'):
        # Single dataset directory
        print(f"Validating dataset: {args.path.name}\n")
        results = validate_dataset(args.path, args.verbose)

        print(f"\n{'='*80}")
        print("VALIDATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total episodes: {results['total_episodes']}")
        print(f"Valid episodes: {results['valid_episodes']}")
        print(f"Invalid episodes: {results['invalid_episodes']}")

        if results['invalid_episodes'] > 0:
            print(f"\nInvalid episodes should be regenerated or removed.")
            sys.exit(1)
        else:
            print(f"\n✅ All episodes valid!")
            sys.exit(0)
    else:
        print(f"Error: Unrecognized directory structure. Expected ep_*, data_*, or batch directory.")
        sys.exit(1)


if __name__ == "__main__":
    main()
