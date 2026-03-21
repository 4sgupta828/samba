#!/usr/bin/env python3
"""
Workload Analysis Tool - Quickly understand what happened in an episode.

Usage:
    python analyze_workload.py data/data_20251124_191951/ep_0
"""
import json
import sys
from pathlib import Path
from collections import defaultdict


def analyze_workload(episode_dir: str):
    """Analyze workload generator metrics and print summary."""
    ep_path = Path(episode_dir)

    # Load label
    with open(ep_path / "label.json") as f:
        label = json.load(f)

    print("="*80)
    print(f"WORKLOAD ANALYSIS: {ep_path.name}")
    print("="*80)
    print()

    # Episode info
    print("📋 EPISODE INFO")
    print(f"  Scenario: {label['scenario']}")
    print(f"  Root Cause: {label['root_cause_node']} ({label['root_cause_role']})")
    print(f"  Fault Type: {label['fault_type']}")
    print(f"  Duration: {label['fault_total_duration']}s")
    print()

    # Load and analyze metrics
    metrics = defaultdict(lambda: defaultdict(int))

    with open(ep_path / "metrics.jsonl") as f:
        for line in f:
            m = json.loads(line)
            if m['name'].startswith('workload.'):
                metric_name = m['name']
                labels = m.get('labels', {})
                value = m.get('value', 0)

                if metric_name == "workload.requests":
                    req_type = labels.get('type', 'unknown')
                    metrics['requests'][req_type] += value

                elif metric_name == "workload.requests.rejected":
                    reason = labels.get('reason', 'unknown')
                    metrics['rejected'][reason] += value

                elif metric_name == "workload.circuit_breaker.state":
                    state = int(value)
                    metrics['cb_states'][state] += 1

                elif metric_name == "workload.connection_pool.utilization":
                    metrics['pool_util']['samples'] += 1
                    metrics['pool_util']['sum'] += value

                elif metric_name == "workload.connection_pool.active":
                    metrics['pool_active']['max'] = max(metrics['pool_active']['max'], value)

                elif metric_name == "workload.requests.in_flight":
                    metrics['in_flight']['max'] = max(metrics['in_flight']['max'], value)

    # Print request summary
    print("📊 REQUEST SUMMARY")
    attempted = metrics['requests']['attempted']
    success = metrics['requests']['success']
    failed = metrics['requests']['failed']
    timeout = metrics['requests']['timeout']
    timeout_conn = metrics['requests'].get('timeout_connection_wait', 0)
    timeout_exec = metrics['requests'].get('timeout_request_execution', 0)

    print(f"  Total Attempted: {attempted:,}")
    print(f"  ✅ Successful:   {success:,} ({success/attempted*100:.1f}%)")
    print(f"  ❌ Failed:       {failed:,} ({failed/attempted*100:.1f}%)")
    print(f"  ⏱️  Timeout:      {timeout:,} ({timeout/attempted*100:.1f}%)")
    if timeout_conn > 0:
        print(f"     └─ Conn Wait: {timeout_conn:,}")
    if timeout_exec > 0:
        print(f"     └─ Execution: {timeout_exec:,}")
    print()

    # Print rejection summary
    if metrics['rejected']:
        print("🚫 REJECTION SUMMARY")
        total_rejected = sum(metrics['rejected'].values())
        print(f"  Total Rejected: {total_rejected:,}")
        for reason, count in sorted(metrics['rejected'].items(), key=lambda x: -x[1]):
            pct = count / attempted * 100 if attempted > 0 else 0
            print(f"  └─ {reason}: {count:,} ({pct:.1f}%)")
        print()

    # Print circuit breaker analysis
    print("🔌 CIRCUIT BREAKER")
    cb_states = metrics['cb_states']
    total_samples = sum(cb_states.values())
    if total_samples > 0:
        closed_pct = cb_states[0] / total_samples * 100
        open_pct = cb_states[1] / total_samples * 100
        half_open_pct = cb_states[2] / total_samples * 100

        print(f"  CLOSED (healthy):   {cb_states[0]:,} samples ({closed_pct:.1f}%)")
        print(f"  OPEN (failing):     {cb_states[1]:,} samples ({open_pct:.1f}%)")
        print(f"  HALF_OPEN (testing):{cb_states[2]:,} samples ({half_open_pct:.1f}%)")

        if open_pct > 50:
            print(f"\n  ⚠️  WARNING: Circuit breaker was OPEN for {open_pct:.0f}% of the time!")
            print(f"     This means the workload generator detected high failure rates")
            print(f"     and stopped sending most requests to protect the system.")
    print()

    # Print connection pool analysis
    print("🔗 CONNECTION POOL")
    if metrics['pool_util']['samples'] > 0:
        avg_util = metrics['pool_util']['sum'] / metrics['pool_util']['samples']
        print(f"  Average Utilization: {avg_util*100:.1f}%")
    max_active = metrics['pool_active']['max']
    print(f"  Max Active Connections: {max_active}")
    max_inflight = metrics['in_flight']['max']
    print(f"  Max In-Flight Requests: {max_inflight}")

    if avg_util > 0.9:
        print(f"\n  ⚠️  WARNING: Connection pool was {avg_util*100:.0f}% utilized!")
        print(f"     High utilization indicates the workload generator was struggling")
        print(f"     to send requests due to slow backend responses.")
    print()

    # Print diagnosis
    print("🔍 DIAGNOSIS")
    if open_pct > 50:
        print("  ❌ ISSUE: Workload circuit breaker triggered")
        print("     Root cause: Backend services failing at high rate")
        print("     Impact: Most requests were rejected to prevent overload")
        print()
        print("  💡 WHY IT HAPPENED:")

        # Check logs for early failures
        try:
            import subprocess
            result = subprocess.run(
                f'grep -E "ERROR|WARN" {ep_path}/logs.jsonl | head -10',
                shell=True, capture_output=True, text=True
            )
            if result.stdout:
                print("     Early failures in logs:")
                for line in result.stdout.split('\n')[:3]:
                    if line:
                        log = json.loads(line)
                        ts_sec = (log['timestamp'] - log['timestamp'] // 1000000000 * 1000000000) / 1e9
                        print(f"       t={ts_sec:.1f}s: {log.get('message', '')[:60]}")
        except:
            pass

        print()
        print("  🔧 WHAT THIS MEANS FOR GNN TRAINING:")
        print("     ✅ This is VALUABLE training data!")
        print("     ✅ GNN learns: Circuit breaker behavior")
        print("     ✅ GNN learns: Cascading failures from startup issues")
        print("     ✅ GNN learns: Low-traffic outage scenarios")
        print()
        print("     Generate more episodes to get a mix of healthy and failing scenarios.")
    else:
        print("  ✅ Workload generated successfully")
        print(f"     Success rate: {success/attempted*100:.1f}%")
        print(f"     Circuit breaker: Mostly closed ({closed_pct:.0f}%)")

    print()
    print("="*80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_workload.py <episode_dir>")
        print("Example: python analyze_workload.py data/data_20251124_191951/ep_0")
        sys.exit(1)

    analyze_workload(sys.argv[1])
