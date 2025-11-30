#!/usr/bin/env python3
"""
Baseline Health Validator

Validates that generated episodes have a healthy baseline period before fault injection.
This ensures the fault injection is actually causing degradation, not improving the system.
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class BaselineHealthMetrics:
    """Container for baseline health metrics."""

    def __init__(self):
        self.successful_requests: List[float] = []
        self.circuit_breaker_rejections: List[float] = []
        self.total_attempts: List[float] = []
        self.error_rates: List[float] = []

    @property
    def avg_success_rate(self) -> float:
        """Calculate average success rate during baseline."""
        if not self.successful_requests:
            return 0.0
        total_success = sum(self.successful_requests)
        total_cb_rejects = sum(self.circuit_breaker_rejections)
        total = total_success + total_cb_rejects
        return (total_success / total * 100) if total > 0 else 0.0

    @property
    def avg_successful_requests(self) -> float:
        """Calculate average successful requests per interval."""
        return sum(self.successful_requests) / len(self.successful_requests) if self.successful_requests else 0.0

    @property
    def avg_cb_rejections(self) -> float:
        """Calculate average circuit breaker rejections per interval."""
        return sum(self.circuit_breaker_rejections) / len(self.circuit_breaker_rejections) if self.circuit_breaker_rejections else 0.0


def extract_baseline_metrics(metrics_file: Path, baseline_end_time: float) -> BaselineHealthMetrics:
    """
    Extract health metrics from the baseline period.

    Args:
        metrics_file: Path to metrics.jsonl file
        baseline_end_time: End time of baseline period (fault start time)

    Returns:
        BaselineHealthMetrics object with collected metrics
    """
    metrics = BaselineHealthMetrics()

    with open(metrics_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            sim_time = data.get('labels', {}).get('sim.time')

            if sim_time is None or sim_time >= baseline_end_time:
                continue

            # Track successful requests
            if data.get('name') == 'workload.requests' and data.get('labels', {}).get('type') == 'success':
                metrics.successful_requests.append(data.get('value', 0))

            # Track circuit breaker rejections
            if data.get('name') == 'workload.requests.rejected' and data.get('labels', {}).get('reason') == 'circuit_breaker_open':
                metrics.circuit_breaker_rejections.append(data.get('value', 0))

    return metrics


def extract_post_fault_metrics(metrics_file: Path, fault_full_effect_time: float, duration: float) -> BaselineHealthMetrics:
    """
    Extract health metrics from the post-fault period (after full effect).

    Args:
        metrics_file: Path to metrics.jsonl file
        fault_full_effect_time: Time when fault reaches full effect
        duration: Total episode duration

    Returns:
        BaselineHealthMetrics object with collected metrics
    """
    metrics = BaselineHealthMetrics()

    with open(metrics_file, 'r') as f:
        for line in f:
            data = json.loads(line)
            sim_time = data.get('labels', {}).get('sim.time')

            if sim_time is None or sim_time < fault_full_effect_time:
                continue

            # Track successful requests
            if data.get('name') == 'workload.requests' and data.get('labels', {}).get('type') == 'success':
                metrics.successful_requests.append(data.get('value', 0))

            # Track circuit breaker rejections
            if data.get('name') == 'workload.requests.rejected' and data.get('labels', {}).get('reason') == 'circuit_breaker_open':
                metrics.circuit_breaker_rejections.append(data.get('value', 0))

    return metrics


def validate_episode_health(
    episode_dir: Path,
    min_baseline_success_rate: float = 50.0,
    min_degradation_ratio: float = 0.8
) -> Tuple[bool, str, Dict]:
    """
    Validate that an episode has a healthy baseline and shows proper degradation.

    Args:
        episode_dir: Path to episode directory
        min_baseline_success_rate: Minimum acceptable success rate during baseline (%)
        min_degradation_ratio: Minimum ratio of (post-fault success) / (baseline success)
                               to confirm degradation (should be < 1.0 for valid fault)

    Returns:
        Tuple of (is_valid, reason, metrics_dict)
    """
    # Load label to get fault timing
    label_file = episode_dir / 'label.json'
    if not label_file.exists():
        return False, "Missing label.json", {}

    with open(label_file, 'r') as f:
        label = json.load(f)

    fault_start_time = label.get('fault_start_time')
    fault_full_effect_time = label.get('fault_full_effect_time')
    duration = label.get('fault_total_duration', 0) + fault_start_time

    if fault_start_time is None or fault_full_effect_time is None:
        return False, "Missing fault timing in label", {}

    # Extract metrics
    metrics_file = episode_dir / 'metrics.jsonl'
    if not metrics_file.exists():
        return False, "Missing metrics.jsonl", {}

    baseline_metrics = extract_baseline_metrics(metrics_file, fault_start_time)
    post_fault_metrics = extract_post_fault_metrics(metrics_file, fault_full_effect_time, duration)

    # Calculate health scores
    baseline_success_rate = baseline_metrics.avg_success_rate
    post_fault_success_rate = post_fault_metrics.avg_success_rate

    # Build metrics dict for reporting
    metrics_dict = {
        'baseline': {
            'success_rate': baseline_success_rate,
            'avg_successful_requests': baseline_metrics.avg_successful_requests,
            'avg_cb_rejections': baseline_metrics.avg_cb_rejections,
        },
        'post_fault': {
            'success_rate': post_fault_success_rate,
            'avg_successful_requests': post_fault_metrics.avg_successful_requests,
            'avg_cb_rejections': post_fault_metrics.avg_cb_rejections,
        }
    }

    # Validation checks

    # Check 1: Baseline must be healthy
    if baseline_success_rate < min_baseline_success_rate:
        return False, f"Unhealthy baseline: {baseline_success_rate:.1f}% success rate (minimum: {min_baseline_success_rate}%)", metrics_dict

    # Check 2: Fault must cause degradation (not improvement)
    if baseline_metrics.avg_successful_requests > 0:
        degradation_ratio = post_fault_metrics.avg_successful_requests / baseline_metrics.avg_successful_requests

        if degradation_ratio > min_degradation_ratio:
            return False, f"System improved after fault: success increased by {(degradation_ratio - 1.0) * 100:.1f}% (degradation_ratio: {degradation_ratio:.2f}, max allowed: {min_degradation_ratio})", metrics_dict

    # All checks passed
    return True, "Baseline is healthy and fault causes proper degradation", metrics_dict


def validate_dataset(
    dataset_dir: Path,
    min_baseline_success_rate: float = 50.0,
    min_degradation_ratio: float = 0.8,
    verbose: bool = False
) -> Dict:
    """
    Validate all episodes in a dataset.

    Args:
        dataset_dir: Path to dataset directory (contains ep_0, ep_1, etc.)
        min_baseline_success_rate: Minimum acceptable baseline success rate (%)
        min_degradation_ratio: Maximum ratio for degradation check
        verbose: Print detailed output

    Returns:
        Dictionary with validation results
    """
    results = {
        'total_episodes': 0,
        'valid_episodes': 0,
        'invalid_episodes': 0,
        'invalid_details': []
    }

    # Find all episode directories
    episode_dirs = sorted([d for d in dataset_dir.iterdir() if d.is_dir() and d.name.startswith('ep_')])

    for ep_dir in episode_dirs:
        results['total_episodes'] += 1

        is_valid, reason, metrics = validate_episode_health(
            ep_dir,
            min_baseline_success_rate,
            min_degradation_ratio
        )

        if is_valid:
            results['valid_episodes'] += 1
            if verbose:
                print(f"✓ {ep_dir.name}: {reason}")
                print(f"  Baseline: {metrics['baseline']['success_rate']:.1f}% success rate")
                print(f"  Post-fault: {metrics['post_fault']['success_rate']:.1f}% success rate")
        else:
            results['invalid_episodes'] += 1
            results['invalid_details'].append({
                'episode': ep_dir.name,
                'reason': reason,
                'metrics': metrics
            })
            print(f"✗ {ep_dir.name}: {reason}")
            if metrics:
                print(f"  Baseline: {metrics['baseline']['success_rate']:.1f}% success rate")
                if metrics['post_fault']['avg_successful_requests'] > 0:
                    print(f"  Post-fault: {metrics['post_fault']['success_rate']:.1f}% success rate")

    return results


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate baseline health for generated episodes",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'dataset_dir',
        type=Path,
        help='Path to dataset directory (e.g., data/data_20251127_114143)'
    )
    parser.add_argument(
        '--min-success-rate',
        type=float,
        default=50.0,
        help='Minimum baseline success rate (%%) to consider healthy'
    )
    parser.add_argument(
        '--min-degradation-ratio',
        type=float,
        default=0.8,
        help='Maximum post-fault/baseline ratio (< 1.0 means degradation)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed validation output'
    )

    args = parser.parse_args()

    if not args.dataset_dir.exists():
        print(f"Error: Dataset directory not found: {args.dataset_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"BASELINE HEALTH VALIDATION")
    print(f"{'='*60}")
    print(f"Dataset: {args.dataset_dir}")
    print(f"Min baseline success rate: {args.min_success_rate}%")
    print(f"Max degradation ratio: {args.min_degradation_ratio}")
    print(f"{'='*60}\n")

    results = validate_dataset(
        args.dataset_dir,
        args.min_success_rate,
        args.min_degradation_ratio,
        args.verbose
    )

    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total episodes: {results['total_episodes']}")
    print(f"Valid episodes: {results['valid_episodes']}")
    print(f"Invalid episodes: {results['invalid_episodes']}")

    if results['invalid_episodes'] > 0:
        print(f"\nInvalid episodes should be regenerated or removed.")
        sys.exit(1)
    else:
        print(f"\n✓ All episodes have healthy baselines!")
        sys.exit(0)


if __name__ == "__main__":
    main()
