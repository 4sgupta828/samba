"""
Example integration of TimeWindowSelector with RCA batch runner.

Shows how to properly use point-in-time analysis with auto-detected baselines.
"""

from pathlib import Path
import pandas as pd
import json
from time_window_selector import TimeWindowSelector


def run_rca_with_proper_windows(episode_dir: Path):
    """
    Run RCA with properly selected time windows.

    This demonstrates the correct approach:
    1. Load episode data
    2. Select analysis_time (when RCA would run in production)
    3. Auto-detect healthy baseline
    4. Run RCA comparing baseline vs current window
    """

    # Load episode data
    with open(episode_dir / 'label.json') as f:
        label = json.load(f)

    # Load metrics
    metrics = []
    with open(episode_dir / 'metrics.jsonl') as f:
        for line in f:
            metrics.append(json.loads(line))
    metrics_df = pd.DataFrame(metrics)

    # Flatten labels if needed
    if 'labels' in metrics_df.columns:
        metrics_df['sim_time'] = metrics_df['labels'].apply(lambda x: x.get('sim.time', 0))
        metrics_df['component_id'] = metrics_df['labels'].apply(lambda x: x.get('component.id', ''))

    # === STEP 1: Initialize Window Selector ===
    # Use episode bounds (NOT recovery information)
    episode_start = 0
    episode_end = metrics_df['sim_time'].max()

    selector = TimeWindowSelector(
        metrics_df=metrics_df,
        episode_start=episode_start,
        episode_end=episode_end,
        baseline_pct=0.25,   # Baseline window = 25% of episode
        current_pct=0.15,    # Current window = 15% of episode
        min_gap_pct=0.05     # Minimum 5% gap between windows
    )

    print(f"Episode duration: {selector.episode_duration:.1f}s")
    print(f"Baseline window size: {selector.baseline_window_size:.1f}s")
    print(f"Current window size: {selector.current_window_size:.1f}s")
    print()

    # === STEP 2: Select Analysis Time ===
    # This is when RCA would run in production
    # In evaluation, we can use fault timing to simulate realistic analysis time

    # Option A: If we know fault_start (we do, from labels), suggest analysis time
    fault_start = label.get('fault_start_time', 0)
    analysis_time = selector.suggest_analysis_time(
        fault_start_time=fault_start,
        target_percentile=0.6  # Analyze at 60% through episode
    )

    print(f"Fault starts at: {fault_start:.1f}s")
    print(f"Analysis will run at: {analysis_time:.1f}s")
    print(f"  (This simulates RCA running {analysis_time - fault_start:.1f}s after fault detection)")
    print()

    # === STEP 3: Auto-Detect Baseline and Select Windows ===
    windows = selector.select_windows(
        analysis_time=analysis_time,
        auto_detect_baseline=True  # Let it find healthy period
    )

    print("="*70)
    print("SELECTED WINDOWS")
    print("="*70)
    print(f"Baseline: {windows.baseline}")
    print(f"  Health score: {windows.baseline_health_score:.2f}/10.0")
    print(f"  Method: {windows.selection_metadata['baseline_method']}")
    print()
    print(f"Current: {windows.current}")
    print()
    print(f"Gap between windows: {windows.selection_metadata['gap_duration']:.1f}s "
          f"({windows.selection_metadata['gap_pct']*100:.1f}% of episode)")
    print()

    # Validate
    is_valid, message = windows.validate()
    print(f"Validation: {message}")
    print()

    # === STEP 4: Extract Data for RCA ===
    baseline_df = metrics_df[
        (metrics_df['sim_time'] >= windows.baseline.start) &
        (metrics_df['sim_time'] <= windows.baseline.end)
    ]

    current_df = metrics_df[
        (metrics_df['sim_time'] >= windows.current.start) &
        (metrics_df['sim_time'] <= windows.current.end)
    ]

    print(f"Baseline data: {len(baseline_df)} metrics")
    print(f"Current data: {len(current_df)} metrics")
    print()

    # === STEP 5: Process into RCA format ===
    baseline_data = process_window_to_dict(baseline_df)
    current_data = process_window_to_dict(current_df)

    print(f"Baseline nodes: {len(baseline_data)}")
    print(f"Current nodes: {len(current_data)}")
    print()

    # Now baseline_data and current_data are ready for RCA
    # They represent:
    # - baseline_data: confirmed healthy period (auto-detected)
    # - current_data: recent metrics at analysis_time

    return {
        'baseline_data': baseline_data,
        'current_data': current_data,
        'windows': windows,
        'analysis_time': analysis_time,
        'label': label
    }


def process_window_to_dict(df: pd.DataFrame):
    """
    Convert metrics DataFrame to dict format expected by RCA.

    Returns: Dict[node_id, Dict[metric_name, np.ndarray]]
    """
    import numpy as np

    data = {}
    for node_id, node_group in df.groupby('component_id'):
        data[node_id] = {}
        for metric_name, metric_group in node_group.groupby('name'):
            data[node_id][metric_name] = metric_group['value'].values

    return data


def demonstrate_multiple_analysis_times(episode_dir: Path):
    """
    Demonstrate that we can run RCA at multiple points in time.

    This shows that RCA is a point-in-time analysis, not an aggregate.
    In production, you might run RCA every 30 seconds during an incident.
    """

    # Load data
    with open(episode_dir / 'label.json') as f:
        label = json.load(f)

    metrics = []
    with open(episode_dir / 'metrics.jsonl') as f:
        for line in f:
            metrics.append(json.loads(line))
    metrics_df = pd.DataFrame(metrics)

    if 'labels' in metrics_df.columns:
        metrics_df['sim_time'] = metrics_df['labels'].apply(lambda x: x.get('sim.time', 0))
        metrics_df['component_id'] = metrics_df['labels'].apply(lambda x: x.get('component.id', ''))

    selector = TimeWindowSelector(
        metrics_df=metrics_df,
        episode_start=0,
        episode_end=metrics_df['sim_time'].max()
    )

    fault_start = label.get('fault_start_time', 0)

    print("="*70)
    print("RUNNING RCA AT MULTIPLE TIME POINTS")
    print("="*70)
    print()

    # Simulate running RCA at different times during the incident
    analysis_times = [
        fault_start + 30,   # 30s after fault detected
        fault_start + 60,   # 1 min after
        fault_start + 90,   # 1.5 min after
    ]

    for analysis_time in analysis_times:
        if analysis_time > selector.episode_end - 30:
            continue  # Skip if too close to episode end

        print(f"Analysis Time: {analysis_time:.1f}s (T+{analysis_time - fault_start:.1f}s after fault)")

        try:
            windows = selector.select_windows(analysis_time=analysis_time, auto_detect_baseline=True)
            print(f"  Baseline: {windows.baseline.start:.1f}s - {windows.baseline.end:.1f}s "
                  f"(health={windows.baseline_health_score:.2f})")
            print(f"  Current:  {windows.current.start:.1f}s - {windows.current.end:.1f}s")
            print()

            # In real scenario, you would:
            # 1. Run RCA with these windows
            # 2. Get ranked candidates
            # 3. Track how candidates change over time
            # 4. Build confidence as consistent signal emerges

        except ValueError as e:
            print(f"  Cannot analyze at this time: {e}")
            print()


if __name__ == "__main__":
    # Example usage
    episode_dir = Path("data/batch_run_20251218_133824/data_20251218_134507/ep_0")

    if episode_dir.exists():
        print("EXAMPLE 1: Single RCA Analysis")
        print("="*70)
        result = run_rca_with_proper_windows(episode_dir)
        print()
        print()

        print("EXAMPLE 2: Multiple Analysis Times")
        print("="*70)
        demonstrate_multiple_analysis_times(episode_dir)
    else:
        print(f"Episode directory not found: {episode_dir}")
        print("Update the path to point to a valid episode directory")
