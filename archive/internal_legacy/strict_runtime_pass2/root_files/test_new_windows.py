#!/usr/bin/env python3
"""Test new time window selection."""

from pathlib import Path
import sys
sys.path.insert(0, 'analysis2')

from run_rca_batch import DatasetAdapter

episode_dir = Path('data/batch_run_20251218_133824/data_20251218_134507/ep_0')

print("="*70)
print("TESTING DATA-DRIVEN TIME WINDOW SELECTION")
print("="*70)

adapter = DatasetAdapter(episode_dir)

print("\nTimeline from label:")
print(f"  Fault start:      {adapter.label.get('fault_start_time')}s")
print(f"  Fault full effect: {adapter.label.get('fault_full_effect_time')}s")
print(f"  Recovery start:   {adapter.label.get('recovery_start_time')}s")
print(f"  Recovery complete: {adapter.label.get('recovery_complete_time')}s")

# Compute expected analysis time
fault_full = adapter.label.get('fault_full_effect_time')
recovery = adapter.label.get('recovery_start_time')
expected_analysis = (fault_full + recovery) / 2
print(f"\nExpected analysis time: {expected_analysis}s (midpoint of steady fault)")

print("\nPreparing data windows...")
baseline_data, current_data = adapter.get_data_windows()

print(f"\n✓ Windows selected successfully!")
print(f"  Baseline nodes: {len(baseline_data)}")
print(f"  Current nodes: {len(current_data)}")
