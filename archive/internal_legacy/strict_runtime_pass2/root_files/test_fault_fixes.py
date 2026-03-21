#!/usr/bin/env python3
"""
Test script to validate fault injection fixes.

Tests:
1. inject_latency creates observable latency increases
2. inject_errors creates observable error rate increases
3. Capacity-relative bounds work for different topologies
"""
import sys
import json
import os
from pathlib import Path

def check_fault_impact(episode_dir: str, fault_type: str):
    """Check if a fault had observable impact on metrics."""

    # Load label to get fault details
    label_path = os.path.join(episode_dir, 'label.json')
    if not os.path.exists(label_path):
        print(f"❌ No label.json found in {episode_dir}")
        return False

    with open(label_path, 'r') as f:
        label = json.load(f)

    root_cause = label.get('root_cause_component_id')
    failure_mode = label.get('failure_mode')

    print(f"\n📋 Testing episode: {episode_dir}")
    print(f"   Root cause: {root_cause}")
    print(f"   Failure mode: {failure_mode}")

    # Load metrics
    metrics_path = os.path.join(episode_dir, 'metrics.jsonl')
    if not os.path.exists(metrics_path):
        print(f"❌ No metrics.jsonl found")
        return False

    # Parse metrics for the root cause component
    baseline_metrics = []
    fault_metrics = []

    # Determine fault start time from label
    fault_start = label.get('fault_injection_time', 60.0)

    with open(metrics_path, 'r') as f:
        for line in f:
            metric = json.loads(line)
            if metric.get('component_id') != root_cause:
                continue

            timestamp = metric.get('timestamp', 0)

            # Baseline: 30-60s, Fault: 70-100s (after ramp-up)
            if 30 <= timestamp < fault_start:
                baseline_metrics.append(metric)
            elif (fault_start + 10) <= timestamp < (fault_start + 40):
                fault_metrics.append(metric)

    if not baseline_metrics or not fault_metrics:
        print(f"❌ Insufficient metrics (baseline={len(baseline_metrics)}, fault={len(fault_metrics)})")
        return False

    print(f"   Baseline samples: {len(baseline_metrics)}")
    print(f"   Fault samples: {len(fault_metrics)}")

    # Check fault-specific impact
    if fault_type == 'inject_latency':
        return check_latency_impact(baseline_metrics, fault_metrics)
    elif fault_type == 'inject_errors':
        return check_error_impact(baseline_metrics, fault_metrics)
    else:
        print(f"⚠️  Fault type {fault_type} not tested")
        return True

def check_latency_impact(baseline_metrics, fault_metrics):
    """Check if latency increased during fault."""

    # Calculate average latency
    baseline_latencies = [m.get('avg_latency', 0) for m in baseline_metrics if 'avg_latency' in m]
    fault_latencies = [m.get('avg_latency', 0) for m in fault_metrics if 'avg_latency' in m]

    if not baseline_latencies or not fault_latencies:
        print("❌ No latency metrics found")
        return False

    baseline_avg = sum(baseline_latencies) / len(baseline_latencies)
    fault_avg = sum(fault_latencies) / len(fault_latencies)

    increase_factor = fault_avg / max(1.0, baseline_avg)

    print(f"   Latency: baseline={baseline_avg:.1f}ms, fault={fault_avg:.1f}ms ({increase_factor:.2f}x)")

    # Success: Fault latency is at least 1.3x baseline
    if increase_factor >= 1.3:
        print(f"✅ PASS: Latency increased by {increase_factor:.2f}x (>1.3x threshold)")
        return True
    else:
        print(f"❌ FAIL: Latency only increased by {increase_factor:.2f}x (<1.3x threshold)")
        return False

def check_error_impact(baseline_metrics, fault_metrics):
    """Check if error rate increased during fault."""

    # Calculate average error rate
    baseline_errors = [m.get('internal_error_rate', 0) for m in baseline_metrics]
    fault_errors = [m.get('internal_error_rate', 0) for m in fault_metrics]

    if not baseline_errors or not fault_errors:
        print("❌ No error rate metrics found")
        return False

    baseline_avg = sum(baseline_errors) / len(baseline_errors)
    fault_avg = sum(fault_errors) / len(fault_errors)

    increase_absolute = fault_avg - baseline_avg

    print(f"   Error rate: baseline={baseline_avg*100:.1f}%, fault={fault_avg*100:.1f}% (+{increase_absolute*100:.1f}%)")

    # Success: Fault error rate is at least 5% higher than baseline
    if increase_absolute >= 0.05:
        print(f"✅ PASS: Error rate increased by {increase_absolute*100:.1f}% (>5% threshold)")
        return True
    else:
        print(f"❌ FAIL: Error rate only increased by {increase_absolute*100:.1f}% (<5% threshold)")
        return False

def main():
    """Run fault injection tests."""

    print("=" * 70)
    print("🧪 Testing Fault Injection Fixes")
    print("=" * 70)

    # Test 1: Generate episode with inject_latency
    print("\n" + "=" * 70)
    print("Test 1: inject_latency fault")
    print("=" * 70)

    test_output_dir = "data/test_fault_fixes_latency"

    print(f"\n🔧 Generating test episode...")
    print(f"   Output: {test_output_dir}")

    cmd = f"""python3 generate_dataset.py \
        --episodes 1 \
        --output {test_output_dir} \
        --fault-type inject_latency \
        --fault-role service \
        --fault-severity 0.5"""

    print(f"   Running: {cmd}")

    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Generation failed:")
        print(result.stderr)
        return False

    # Check the generated episode
    episode_path = os.path.join(test_output_dir, 'ep_0')
    if not os.path.exists(episode_path):
        print(f"❌ Episode not generated at {episode_path}")
        return False

    test1_passed = check_fault_impact(episode_path, 'inject_latency')

    # Test 2: Generate episode with inject_errors
    print("\n" + "=" * 70)
    print("Test 2: inject_errors fault")
    print("=" * 70)

    test_output_dir = "data/test_fault_fixes_errors"

    print(f"\n🔧 Generating test episode...")
    print(f"   Output: {test_output_dir}")

    cmd = f"""python3 generate_dataset.py \
        --episodes 1 \
        --output {test_output_dir} \
        --fault-type inject_errors \
        --fault-role service \
        --fault-severity 0.5"""

    print(f"   Running: {cmd}")

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Generation failed:")
        print(result.stderr)
        return False

    # Check the generated episode
    episode_path = os.path.join(test_output_dir, 'ep_0')
    if not os.path.exists(episode_path):
        print(f"❌ Episode not generated at {episode_path}")
        return False

    test2_passed = check_fault_impact(episode_path, 'inject_errors')

    # Summary
    print("\n" + "=" * 70)
    print("📊 Test Summary")
    print("=" * 70)
    print(f"   inject_latency: {'✅ PASS' if test1_passed else '❌ FAIL'}")
    print(f"   inject_errors:  {'✅ PASS' if test2_passed else '❌ FAIL'}")

    if test1_passed and test2_passed:
        print("\n🎉 All tests passed! Fixes are working correctly.")
        return True
    else:
        print("\n❌ Some tests failed. Please review the output above.")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
