#!/usr/bin/env python3
"""
Generate one episode for each fault type in the fault index.

This script:
1. Loads the fault index
2. For each fault type-role combination
3. Generates one episode with a randomly selected compatible topology
4. Tracks completed fault types to avoid regeneration
"""
import json
import subprocess
import sys
import os
from pathlib import Path
from fault_progress_tracker import FaultProgressTracker

def load_fault_index(index_path: str = "data/fault_index.json"):
    """Load the fault index."""
    with open(index_path, 'r') as f:
        return json.load(f)

def generate_episode_for_fault(fault_key: str, output_dir: str, episode_num: int, tracker: FaultProgressTracker):
    """
    Generate one episode for a specific fault type.

    Args:
        fault_key: Fault type-role combination (e.g., "cpu_saturation:service")
        output_dir: Output directory for episodes
        episode_num: Episode number for naming
        tracker: Progress tracker to record completion

    Returns:
        Tuple of (success: bool, episode_path: str or None)
    """
    # Parse fault key
    fault_type, fault_role = fault_key.split(":")

    print(f"\n{'='*80}")
    print(f"Episode {episode_num}: {fault_key}")
    print(f"{'='*80}")

    # Run generate_dataset.py
    cmd = [
        "python3", "generate_dataset.py",
        "--episodes", "1",
        "--output", output_dir,
        "--llm-topologies",
        "--llm-target-selection",
        "--fault-type", fault_type,
        "--fault-role", fault_role,
        "--verbose"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"⚠️  Failed to generate episode for {fault_key}")
        # Print last few lines of error
        if result.stderr:
            print(f"Error: {result.stderr[-500:]}")
        return (False, None)

    # Find the generated episode directory
    # Look for the most recently created directory with ep_0/label.json
    import glob
    episode_dirs = glob.glob(f"{output_dir}/data_*/ep_0")
    if episode_dirs:
        # Get most recent
        latest_dir = max(episode_dirs, key=os.path.getmtime)
        label_file = os.path.join(latest_dir, "label.json")

        if os.path.exists(label_file):
            # Verify it's the correct fault type
            with open(label_file, 'r') as f:
                label = json.load(f)
                if label.get('fault_type') == fault_type:
                    # Mark as completed in tracker
                    tracker.mark_completed(fault_key, latest_dir)
                    print(f"✅ Episode {episode_num} completed: {fault_key}")
                    print(f"   Saved to: {latest_dir}")
                    return (True, latest_dir)

    print(f"⚠️  Episode generated but could not verify: {fault_key}")
    return (False, None)

def main():
    # Configuration
    fault_index_path = "data/fault_index.json"
    output_dir = "data/all_fault_types"
    progress_file = "data/fault_generation_progress.json"

    print("="*80)
    print("ALL FAULT TYPES DATASET GENERATOR")
    print("="*80)
    print(f"Fault Index: {fault_index_path}")
    print(f"Output Directory: {output_dir}")
    print(f"Progress Tracker: {progress_file}")
    print()

    # Initialize progress tracker
    tracker = FaultProgressTracker(progress_file)

    # Load fault index
    print("Loading fault index...")
    try:
        fault_index = load_fault_index(fault_index_path)
    except FileNotFoundError:
        print(f"❌ Error: Fault index not found at {fault_index_path}")
        print("Run: python generate_fault_index_fast.py --topology-bank data/topology_bank --output data/fault_index.json")
        sys.exit(1)

    fault_keys = list(fault_index.keys())
    print(f"Found {len(fault_keys)} fault type-role combinations")

    # Check existing progress
    completed = tracker.get_completed_fault_types()
    remaining = [key for key in fault_keys if key not in completed]

    print(f"Already completed: {len(completed)}")
    print(f"Remaining: {len(remaining)}")
    print()

    if len(completed) > 0:
        print("✅ Completed fault types:")
        for key in sorted(completed):
            episodes = tracker.get_episode_paths(key)
            print(f"  {key:40s} ({len(episodes)} episodes)")
        print()

    if len(remaining) == 0:
        print("🎉 All fault types already generated!")
        print("\nTo regenerate, delete the progress file:")
        print(f"  rm {progress_file}")
        return

    # Show remaining fault types
    print("🔄 Fault types to generate:")
    for i, key in enumerate(remaining, 1):
        num_topologies = len(fault_index[key])
        print(f"  {i:2d}. {key:40s} ({num_topologies} compatible topologies)")
    print()

    # Generate episodes for remaining fault types
    successful = 0
    failed = 0

    for i, fault_key in enumerate(remaining):
        success, episode_path = generate_episode_for_fault(fault_key, output_dir, i, tracker)
        if success:
            successful += 1
        else:
            failed += 1

    # Summary
    print("\n" + "="*80)
    print("GENERATION COMPLETE")
    print("="*80)
    print(f"Total fault types: {len(fault_keys)}")
    print(f"Previously completed: {len(completed)}")
    print(f"Newly generated: {successful}")
    print(f"Failed: {failed}")
    print(f"Total completed: {len(tracker.get_completed_fault_types())}/{len(fault_keys)}")
    print(f"Output directory: {output_dir}")
    print(f"Progress saved to: {progress_file}")
    print("="*80)

if __name__ == "__main__":
    main()
