#!/usr/bin/env python3
"""
Investigate memory_pressure fault issue in dataset.
"""
import json
import sys
from collections import defaultdict

dataset_dir = "data/batch_run/data_20251210_143521/ep_0"

# Read run parameters
with open(f"{dataset_dir}/run_parameters.json", 'r') as f:
    params = json.load(f)

print("=" * 80)
print("MEMORY PRESSURE FAULT INVESTIGATION")
print("=" * 80)
print(f"\nFault Configuration:")
print(f"  Type: {params['fault']['type']}")
print(f"  Root Cause: {params['fault']['root_cause_node']}")
print(f"  Severity: {params['fault']['params']['severity']}")
print(f"\nTimeline (adjusted sim.time):")
print(f"  Fault Start: {params['timeline']['fault_start_time']}s")
print(f"  Fault Full Effect: {params['timeline']['fault_full_effect_time']}s")
print(f"  Recovery Start: {params['timeline']['recovery_start_time']}s")
print(f"  Recovery Complete: {params['timeline']['recovery_complete_time']}s")

# Read metrics
print("\n" + "=" * 80)
print("METRICS ANALYSIS")
print("=" * 80)

with open(f"{dataset_dir}/metrics.jsonl", 'r') as f:
    lines = f.readlines()

# Extract data
memory_by_time = defaultdict(list)
latency_by_time = defaultdict(list)
cpu_by_time = defaultdict(list)

for line in lines:
    try:
        data = json.loads(line)
        sim_time = data.get('labels', {}).get('sim.time')
        if sim_time is None:
            continue
        
        component_id = data.get('labels', {}).get('component.id', '')
        if 'tenant_service' not in component_id:
            continue
            
        name = data.get('name', '')
        
        if name == 'container.memory.usage_mb':
            memory_by_time[sim_time].append(data.get('value', 0))
        elif name == 'service.tenant_service.duration':
            summary = data.get('summary', {})
            if summary and 'p99' in summary:
                latency_by_time[sim_time].append(summary['p99'])
        elif name == 'container.cpu.utilization':
            cpu_by_time[sim_time].append(data.get('value', 0))
    except Exception as e:
        pass

# Print key timepoints
print("\nKey Timepoints Analysis:")
print("-" * 80)
print(f"{'Time':>6} | {'Avg Memory (MB)':>15} | {'Max Memory (MB)':>15} | {'Avg P99 Latency (ms)':>20} | {'Max P99 Latency (ms)':>20}")
print("-" * 80)

key_times = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
for t in key_times:
    if t in memory_by_time:
        avg_mem = sum(memory_by_time[t]) / len(memory_by_time[t])
        max_mem = max(memory_by_time[t])
        avg_lat = sum(latency_by_time[t]) / len(latency_by_time[t]) if latency_by_time[t] else 0
        max_lat = max(latency_by_time[t]) if latency_by_time[t] else 0
        phase = ""
        if t < 60:
            phase = "Baseline"
        elif t < 90:
            phase = "Ramp"
        elif t < 210:
            phase = "Fault"
        elif t < 240:
            phase = "Recovery"
        else:
            phase = "Post-Recovery"
        print(f"{t:6.0f} | {avg_mem:15.1f} | {max_mem:15.1f} | {avg_lat:20.1f} | {max_lat:20.1f} | {phase}")

# Check if memory actually increased
baseline_mem = sum(memory_by_time[30]) / len(memory_by_time[30]) if memory_by_time[30] else 0
fault_mem = sum(memory_by_time[150]) / len(memory_by_time[150]) if memory_by_time[150] else 0
recovery_mem = sum(memory_by_time[270]) / len(memory_by_time[270]) if memory_by_time[270] else 0

print("\n" + "=" * 80)
print("ISSUE ANALYSIS")
print("=" * 80)
print(f"\nMemory Change:")
print(f"  Baseline (30s): {baseline_mem:.1f} MB")
print(f"  During Fault (150s): {fault_mem:.1f} MB (change: {fault_mem - baseline_mem:+.1f} MB)")
print(f"  After Recovery (270s): {recovery_mem:.1f} MB (change: {recovery_mem - baseline_mem:+.1f} MB)")

if abs(fault_mem - baseline_mem) < 10:
    print("\n  ⚠️  PROBLEM: Memory did not increase significantly during fault!")
    print("     Expected: Memory should increase by ~100-200 MB based on severity 0.5")

baseline_lat = sum(latency_by_time[30]) / len(latency_by_time[30]) if latency_by_time[30] else 0
fault_lat = sum(latency_by_time[150]) / len(latency_by_time[150]) if latency_by_time[150] else 0
recovery_lat = sum(latency_by_time[270]) / len(latency_by_time[270]) if latency_by_time[270] else 0

print(f"\nLatency Change:")
print(f"  Baseline (30s): {baseline_lat:.1f} ms")
print(f"  During Fault (150s): {fault_lat:.1f} ms (change: {fault_lat - baseline_lat:+.1f} ms)")
print(f"  After Recovery (270s): {recovery_lat:.1f} ms (change: {recovery_lat - baseline_lat:+.1f} ms)")

if recovery_lat > baseline_lat * 1.5:
    print("\n  ⚠️  PROBLEM: Latency remains high after recovery!")
    print("     Expected: Latency should return close to baseline after recovery completes")

# Check logs for fault injection/revert messages
print("\n" + "=" * 80)
print("CHECKING SIMULATION LOGS")
print("=" * 80)

try:
    with open(f"{dataset_dir}/simulation.log", 'r') as f:
        log_lines = f.readlines()
    
    fault_injected = False
    fault_reverted = False
    
    for line in log_lines:
        if 'memory_pressure' in line.lower() and 'inject' in line.lower():
            print(f"  Found: {line.strip()}")
            fault_injected = True
        if 'memory_pressure' in line.lower() and ('revert' in line.lower() or 'recover' in line.lower()):
            print(f"  Found: {line.strip()}")
            fault_reverted = True
    
    if not fault_injected:
        print("  ⚠️  WARNING: No memory_pressure injection found in logs")
    if not fault_reverted:
        print("  ⚠️  WARNING: No memory_pressure revert found in logs")
        
except Exception as e:
    print(f"  Could not read simulation.log: {e}")

print("\n" + "=" * 80)

