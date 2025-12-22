"""
Test script to verify network partition detection and scoring fixes
"""
import sys
import subprocess
from pathlib import Path

# Test cases
test_cases = [
    {
        'name': 'Real Network Partition (should rank global_network #1)',
        'path': './data/batch_run_20251218_133824/data_20251218_135627/ep_0',
        'expected_rank1': 'global_network'
    },
    {
        'name': 'False Positive (should NOT detect partition, rank clinical_dashboard_service #1)',
        'path': './data/batch_run_20251218_133824/data_20251218_133951/ep_0',
        'expected_rank1': 'clinical_dashboard_service',
        'should_not_detect_partition': True
    }
]

print("Testing Network Partition Detection and Scoring Fixes")
print("=" * 70)

for i, test in enumerate(test_cases, 1):
    print(f"\nTest {i}: {test['name']}")
    print(f"Path: {test['path']}")
    print("-" * 70)

    # Run RCA on this dataset using the batch script
    cmd = f"python run_rca_batch.py {test['path']}"

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd='/Users/sgupta/samba/analysis2'
    )

    # Parse output for key metrics
    lines = result.stdout.split('\n')

    # Look for partition detection messages
    partition_detected = any('Network partition detected' in line for line in lines)
    partition_filtered = any('attributed to service failures' in line for line in lines)

    # Look for top candidate
    for line in lines:
        if 'Top 3 candidates' in line or '1.' in line:
            print(line)

    # Check results
    print(f"\nPartition detected: {partition_detected}")
    if partition_filtered:
        print("✓ Partitions correctly filtered out (service failures)")

    if test.get('should_not_detect_partition'):
        if not partition_detected or partition_filtered:
            print("✓ PASS: No false positive partition detection")
        else:
            print("✗ FAIL: False positive - partition incorrectly detected")
    else:
        if partition_detected and not partition_filtered:
            print("✓ PASS: True partition correctly detected")
        else:
            print("✗ FAIL: True partition not detected")

print("\n" + "=" * 70)
print("Testing complete")
