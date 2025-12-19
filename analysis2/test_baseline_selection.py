"""
Test and validate baseline selection against labeled ground truth data.

Compares auto-detected baselines with labeled baselines to tune thresholds
and validate the selection algorithm.
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass
from time_window_selector import TimeWindowSelector, TimeWindow


@dataclass
class BaselineValidation:
    """Results of baseline selection validation."""
    episode_id: str
    fault_type: str

    # Labeled baseline (ground truth)
    labeled_baseline_start: float
    labeled_baseline_end: float
    labeled_baseline_duration: float

    # Auto-detected baseline
    detected_baseline_start: float
    detected_baseline_end: float
    detected_baseline_duration: float
    detected_health_score: float
    detection_method: str

    # Overlap analysis
    overlap_start: float
    overlap_end: float
    overlap_duration: float
    overlap_percentage: float  # % of labeled baseline that overlaps with detected

    # Health comparison
    labeled_health_score: float
    current_health_score: float
    health_improvement: float  # labeled - current (positive means baseline is healthier)

    # Validation
    is_valid: bool
    validation_notes: str


def validate_baseline_selection(episode_dir: Path, analysis_time: float = None) -> BaselineValidation:
    """
    Validate baseline selection for a single episode against labeled data.

    Args:
        episode_dir: Path to episode directory
        analysis_time: Analysis time (if None, will be auto-suggested)

    Returns:
        BaselineValidation with detailed comparison
    """
    # Load label
    with open(episode_dir / 'label.json') as f:
        label = json.load(f)

    # Load metrics
    metrics = []
    with open(episode_dir / 'metrics.jsonl') as f:
        for line in f:
            metrics.append(json.loads(line))
    metrics_df = pd.DataFrame(metrics)

    if 'labels' in metrics_df.columns:
        metrics_df['sim_time'] = metrics_df['labels'].apply(lambda x: x.get('sim.time', 0))
        metrics_df['component_id'] = metrics_df['labels'].apply(lambda x: x.get('component.id', ''))

    # Extract labeled baseline from timeline
    timeline = label.get('timeline', {})
    labeled_baseline_start = timeline.get('healthy_baseline_start', 0)
    labeled_baseline_end = label.get('fault_start_time', 60)
    labeled_baseline_duration = labeled_baseline_end - labeled_baseline_start

    # Initialize selector
    selector = TimeWindowSelector(
        metrics_df=metrics_df,
        episode_start=0,
        episode_end=metrics_df['sim_time'].max(),
        baseline_pct=0.25,
        current_pct=0.15
    )

    # Suggest analysis time if not provided
    if analysis_time is None:
        fault_start = label.get('fault_start_time', 0)
        analysis_time = selector.suggest_analysis_time(fault_start)

    # Auto-detect baseline
    windows = selector.select_windows(analysis_time=analysis_time, auto_detect_baseline=True)

    detected_baseline = windows.baseline
    current_window = windows.current

    # Compute overlap
    overlap_start = max(labeled_baseline_start, detected_baseline.start)
    overlap_end = min(labeled_baseline_end, detected_baseline.end)
    overlap_duration = max(0, overlap_end - overlap_start)
    overlap_percentage = (overlap_duration / labeled_baseline_duration * 100) if labeled_baseline_duration > 0 else 0

    # Compute health scores for all periods
    labeled_health, _ = selector._compute_window_health(labeled_baseline_start, labeled_baseline_end)
    current_health, _ = selector._compute_window_health(current_window.start, current_window.end)
    health_improvement = labeled_health - current_health  # Negative means current is worse

    # Validation criteria
    is_valid = True
    validation_notes = []

    # Check 1: Baseline should not overlap with fault period
    fault_start = label.get('fault_start_time', 0)
    if detected_baseline.end > fault_start:
        is_valid = False
        validation_notes.append(f"Baseline extends into fault period (ends at {detected_baseline.end}, fault at {fault_start})")

    # Check 2: Baseline should be healthier than current
    if windows.baseline_health_score >= current_health:
        is_valid = False
        validation_notes.append(f"Baseline not healthier than current ({windows.baseline_health_score:.2f} vs {current_health:.2f})")

    # Check 3: Reasonable overlap with labeled baseline (not too strict)
    if overlap_percentage < 30:
        validation_notes.append(f"Low overlap with labeled baseline ({overlap_percentage:.1f}%)")

    # Check 4: Sufficient duration
    if detected_baseline.duration < 20:
        is_valid = False
        validation_notes.append(f"Baseline too short ({detected_baseline.duration:.1f}s)")

    if not validation_notes:
        validation_notes.append("All checks passed")

    return BaselineValidation(
        episode_id=episode_dir.name,
        fault_type=label.get('fault_type', 'unknown'),
        labeled_baseline_start=labeled_baseline_start,
        labeled_baseline_end=labeled_baseline_end,
        labeled_baseline_duration=labeled_baseline_duration,
        detected_baseline_start=detected_baseline.start,
        detected_baseline_end=detected_baseline.end,
        detected_baseline_duration=detected_baseline.duration,
        detected_health_score=windows.baseline_health_score,
        detection_method=windows.selection_metadata.get('baseline_method', 'unknown'),
        overlap_start=overlap_start,
        overlap_end=overlap_end,
        overlap_duration=overlap_duration,
        overlap_percentage=overlap_percentage,
        labeled_health_score=labeled_health,
        current_health_score=current_health,
        health_improvement=health_improvement,
        is_valid=is_valid,
        validation_notes="; ".join(validation_notes)
    )


def test_batch_baseline_selection(batch_dir: Path) -> List[BaselineValidation]:
    """
    Test baseline selection across all episodes in a batch run.

    Args:
        batch_dir: Path to batch run directory

    Returns:
        List of BaselineValidation results
    """
    results = []

    # Find all episode directories
    episode_dirs = sorted([d for d in batch_dir.iterdir() if d.is_dir() and d.name.startswith('data_')])

    print(f"Testing baseline selection on {len(episode_dirs)} episodes...")
    print("=" * 80)
    print()

    for episode_dir in episode_dirs:
        ep_subdir = episode_dir / 'ep_0'
        if not ep_subdir.exists():
            continue

        try:
            validation = validate_baseline_selection(ep_subdir)
            results.append(validation)

            # Print summary
            status = "✓" if validation.is_valid else "✗"
            print(f"{status} {validation.episode_id} ({validation.fault_type})")
            print(f"  Labeled:  [{validation.labeled_baseline_start:.1f}s - {validation.labeled_baseline_end:.1f}s] "
                  f"(health={validation.labeled_health_score:.2f})")
            print(f"  Detected: [{validation.detected_baseline_start:.1f}s - {validation.detected_baseline_end:.1f}s] "
                  f"(health={validation.detected_health_score:.2f})")
            print(f"  Overlap:  {validation.overlap_percentage:.1f}% ({validation.overlap_duration:.1f}s)")
            print(f"  Method:   {validation.detection_method}")
            print(f"  Notes:    {validation.validation_notes}")
            print()

        except Exception as e:
            print(f"✗ {episode_dir.name}: Error - {e}")
            print()

    # Summary statistics
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total episodes: {len(results)}")
    print(f"Valid baselines: {sum(1 for r in results if r.is_valid)} ({sum(1 for r in results if r.is_valid)/len(results)*100:.1f}%)")
    print()

    # Overlap statistics
    overlaps = [r.overlap_percentage for r in results]
    print(f"Overlap with labeled baseline:")
    print(f"  Mean: {sum(overlaps)/len(overlaps):.1f}%")
    print(f"  Min:  {min(overlaps):.1f}%")
    print(f"  Max:  {max(overlaps):.1f}%")
    print()

    # Health improvement statistics
    improvements = [r.health_improvement for r in results]
    print(f"Health improvement (labeled vs current):")
    print(f"  Mean: {sum(improvements)/len(improvements):.2f}")
    print(f"  Positive (baseline healthier): {sum(1 for i in improvements if i < 0)} episodes")
    print()

    # Detection method breakdown
    methods = {}
    for r in results:
        methods[r.detection_method] = methods.get(r.detection_method, 0) + 1

    print(f"Detection methods:")
    for method, count in sorted(methods.items()):
        print(f"  {method}: {count} ({count/len(results)*100:.1f}%)")
    print()

    return results


def analyze_validation_failures(results: List[BaselineValidation]):
    """
    Analyze why baselines failed validation.

    Args:
        results: List of validation results
    """
    failures = [r for r in results if not r.is_valid]

    if not failures:
        print("No validation failures to analyze!")
        return

    print("=" * 80)
    print(f"ANALYZING {len(failures)} VALIDATION FAILURES")
    print("=" * 80)
    print()

    # Group by failure reason
    failure_reasons = {}
    for result in failures:
        notes = result.validation_notes
        if notes not in failure_reasons:
            failure_reasons[notes] = []
        failure_reasons[notes].append(result)

    for reason, cases in sorted(failure_reasons.items(), key=lambda x: -len(x[1])):
        print(f"Reason: {reason}")
        print(f"Count: {len(cases)} episodes")
        print(f"Episodes: {', '.join(c.episode_id for c in cases[:3])}")
        print()


if __name__ == "__main__":
    # Test on the batch run with false positives
    batch_dir = Path("data/batch_run_20251218_133824")

    if batch_dir.exists():
        results = test_batch_baseline_selection(batch_dir)
        analyze_validation_failures(results)

        # Save results for further analysis
        output_file = batch_dir / "baseline_validation_results.json"
        with open(output_file, 'w') as f:
            json.dump([
                {
                    'episode_id': r.episode_id,
                    'fault_type': r.fault_type,
                    'labeled_baseline': [r.labeled_baseline_start, r.labeled_baseline_end],
                    'detected_baseline': [r.detected_baseline_start, r.detected_baseline_end],
                    'overlap_percentage': r.overlap_percentage,
                    'health_scores': {
                        'labeled': r.labeled_health_score,
                        'detected': r.detected_health_score,
                        'current': r.current_health_score
                    },
                    'is_valid': r.is_valid,
                    'notes': r.validation_notes
                }
                for r in results
            ], f, indent=2)
        print(f"Results saved to: {output_file}")

    else:
        print(f"Batch directory not found: {batch_dir}")
