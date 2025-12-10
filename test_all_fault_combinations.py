#!/usr/bin/env python3
"""
Test all valid fault type and role combinations.

This script:
1. Runs all valid fault type/role combinations
2. Checks if generation was successful
3. Analyzes fault propagation in successful runs
4. Reports issues and suggests remediations
"""
import subprocess
import os
import json
import sys
from pathlib import Path
from datetime import datetime
import tempfile

# Valid fault type and role combinations
VALID_COMBINATIONS = {
    'cpu_saturation': ['service', 'database'],
    'memory_leak': ['service', 'database'],
    'memory_pressure': ['service', 'database'],
    'memory_thrashing': ['service', 'database'],
    'inject_latency': ['service', 'cache', 'external', 'database'],
    'disk_io_saturation': ['database'],
    'thread_exhaustion': ['service', 'database'],
    'cache_failure': ['cache'],
    'inject_errors': ['service', 'cache', 'external', 'database'],
    'queue_consumer_slowdown': ['queue'],
    'hot_shard': ['service'],
    'noisy_neighbor': ['service'],
    'force_deadlock': ['service', 'database'],
    'network_partition': ['network'],
}


def get_all_combinations():
    """Get all valid fault type and role combinations."""
    combinations = []
    for fault_type, roles in VALID_COMBINATIONS.items():
        for role in roles:
            combinations.append((fault_type, role))
    return combinations


def run_generation(fault_type, role, output_dir, num_episodes=3, verbose=False):
    """
    Run dataset generation for a specific fault type and role combination.

    Returns:
        dict: Result with 'success', 'output_dir', 'stdout', 'stderr', 'error'
    """
    print(f"\n{'='*80}")
    print(f"Testing: {fault_type} on {role}")
    print(f"{'='*80}")

    cmd = [
        'python3', 'generate_dataset.py',
        '--episodes', str(num_episodes),
        '--output', output_dir,
        '--fault-type', fault_type,
        '--fault-role', role,
    ]

    if verbose:
        cmd.append('--verbose')

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1200  # 20 minute timeout
        )

        success = result.returncode == 0

        if success:
            print(f"✓ Generation successful")
        else:
            print(f"✗ Generation failed with return code {result.returncode}")
            if result.stderr:
                print(f"Error output: {result.stderr[:500]}")

        return {
            'success': success,
            'output_dir': output_dir,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
            'error': None
        }

    except subprocess.TimeoutExpired:
        print(f"✗ Generation timed out after 20 minutes")
        return {
            'success': False,
            'output_dir': output_dir,
            'error': 'timeout',
            'stdout': '',
            'stderr': ''
        }
    except Exception as e:
        print(f"✗ Exception during generation: {e}")
        return {
            'success': False,
            'output_dir': output_dir,
            'error': str(e),
            'stdout': '',
            'stderr': ''
        }


def check_episode_files(episode_dir):
    """
    Check if all required files exist for an episode.

    Returns:
        dict: {'complete': bool, 'missing_files': list}
    """
    required_files = [
        'topology.json',
        'label.json',
        'logs.jsonl',
        'metrics.jsonl'
    ]

    missing = []
    for fname in required_files:
        fpath = os.path.join(episode_dir, fname)
        if not os.path.exists(fpath):
            missing.append(fname)

    return {
        'complete': len(missing) == 0,
        'missing_files': missing
    }


def analyze_propagation(episode_dir):
    """
    Analyze fault propagation for an episode.

    Returns:
        dict: Analysis results with propagation info
    """
    try:
        # Import analyzer
        sys.path.insert(0, str(Path(__file__).parent))
        from analysis.propagation_analyzer import analyze_episode

        result = analyze_episode(episode_dir)

        # Check for propagation
        has_propagation = False
        propagation_issues = []

        if result and 'propagation' in result:
            prop = result['propagation']

            # Check if fault propagated
            if 'affected_nodes' in prop:
                num_affected = len(prop['affected_nodes'])
                if num_affected > 1:
                    has_propagation = True
                else:
                    propagation_issues.append(f"Only {num_affected} node affected (no propagation)")

            # Check propagation paths
            if 'paths' in prop:
                paths = prop['paths']
                if len(paths) == 0:
                    propagation_issues.append("No propagation paths found")
                elif len(paths) < 2:
                    propagation_issues.append(f"Only {len(paths)} propagation path found")

            # Check validation issues
            if 'validation' in result and 'issues' in result['validation']:
                issues = result['validation']['issues']
                if issues:
                    propagation_issues.extend(issues)
        else:
            propagation_issues.append("No propagation data in analysis result")

        return {
            'success': True,
            'has_propagation': has_propagation,
            'issues': propagation_issues,
            'result': result
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'has_propagation': False,
            'issues': [f"Analysis failed: {e}"]
        }


def analyze_run(fault_type, role, run_result):
    """
    Analyze a completed run for a fault type/role combination.

    Returns:
        dict: Analysis summary
    """
    if not run_result['success']:
        return {
            'status': 'failed',
            'reason': run_result.get('error', 'generation failed'),
            'stderr': run_result.get('stderr', '')[:500]
        }

    output_dir = run_result['output_dir']

    # Find the actual data directory (has timestamp)
    data_dirs = [d for d in os.listdir(output_dir) if d.startswith('data_')]
    if not data_dirs:
        return {
            'status': 'failed',
            'reason': 'no data directory created'
        }

    data_dir = os.path.join(output_dir, data_dirs[0])

    # Check episodes
    episodes = [d for d in os.listdir(data_dir) if d.startswith('ep_')]
    if not episodes:
        return {
            'status': 'failed',
            'reason': 'no episodes generated'
        }

    # Analyze each episode
    episode_results = []
    for ep in sorted(episodes):
        ep_dir = os.path.join(data_dir, ep)

        # Check files
        file_check = check_episode_files(ep_dir)

        # Analyze propagation
        prop_analysis = analyze_propagation(ep_dir)

        episode_results.append({
            'episode': ep,
            'files_complete': file_check['complete'],
            'missing_files': file_check['missing_files'],
            'propagation_analysis': prop_analysis
        })

    # Summarize
    complete_episodes = sum(1 for ep in episode_results if ep['files_complete'])
    propagating_episodes = sum(
        1 for ep in episode_results
        if ep['propagation_analysis'].get('has_propagation', False)
    )

    all_issues = []
    for ep in episode_results:
        if ep['propagation_analysis'].get('issues'):
            all_issues.extend(ep['propagation_analysis']['issues'])

    return {
        'status': 'success',
        'total_episodes': len(episodes),
        'complete_episodes': complete_episodes,
        'propagating_episodes': propagating_episodes,
        'episodes': episode_results,
        'all_propagation_issues': list(set(all_issues))  # unique issues
    }


def suggest_remediation(fault_type, role, analysis):
    """
    Suggest remediation for propagation issues.

    Returns:
        list: Remediation suggestions
    """
    suggestions = []

    if analysis['status'] == 'failed':
        reason = analysis.get('reason', 'unknown')
        if reason and ('no data directory' in reason or 'no episodes' in reason):
            suggestions.append("Generation failed completely. Check if the fault type/role combination is correctly implemented in scenarios/library.py")
        elif 'timeout' in reason:
            suggestions.append("Generation timed out. May need to reduce simulation duration or topology size")
        else:
            suggestions.append(f"Generation failed: {reason}")
        return suggestions

    # Check for propagation issues
    if analysis.get('propagating_episodes', 0) == 0:
        suggestions.append("⚠️  NO FAULT PROPAGATION DETECTED")
        suggestions.append("   Possible causes:")
        suggestions.append("   - Fault may not be severe enough to propagate")
        suggestions.append("   - Fault target may be isolated in topology")
        suggestions.append("   - Fault injection may not be working correctly")
        suggestions.append(f"   - Check fault implementation for {fault_type}")

    if analysis.get('propagating_episodes', 0) < analysis.get('total_episodes', 1):
        suggestions.append(f"⚠️  Only {analysis.get('propagating_episodes')} of {analysis.get('total_episodes')} episodes show propagation")
        suggestions.append("   This may indicate inconsistent fault injection or topology issues")

    # Specific issues
    issues = analysis.get('all_propagation_issues', [])
    if issues:
        suggestions.append("   Specific issues found:")
        for issue in issues[:5]:  # Top 5 issues
            suggestions.append(f"   - {issue}")

    return suggestions


def main():
    """Main test runner."""
    print("="*80)
    print("FAULT TYPE/ROLE COMBINATION TESTER")
    print("="*80)

    # Create temp output directory
    base_output = tempfile.mkdtemp(prefix='fault_test_')
    print(f"\nOutput directory: {base_output}")

    combinations = get_all_combinations()
    print(f"\nTesting {len(combinations)} combinations")

    results = {}

    # Run all combinations
    for fault_type, role in combinations:
        combo_key = f"{fault_type}_{role}"
        output_dir = os.path.join(base_output, combo_key)
        os.makedirs(output_dir, exist_ok=True)

        # Run generation
        run_result = run_generation(
            fault_type,
            role,
            output_dir,
            num_episodes=3,
            verbose=False
        )

        # Analyze
        analysis = analyze_run(fault_type, role, run_result)

        results[combo_key] = {
            'fault_type': fault_type,
            'role': role,
            'run_result': run_result,
            'analysis': analysis
        }

    # Print summary report
    print("\n" + "="*80)
    print("SUMMARY REPORT")
    print("="*80)

    successful = []
    failed = []
    no_propagation = []
    partial_propagation = []

    for combo_key, res in results.items():
        analysis = res['analysis']

        if analysis['status'] == 'failed':
            failed.append(combo_key)
        elif analysis.get('propagating_episodes', 0) == 0:
            no_propagation.append(combo_key)
        elif analysis.get('propagating_episodes', 0) < analysis.get('total_episodes', 1):
            partial_propagation.append(combo_key)
        else:
            successful.append(combo_key)

    print(f"\n✓ Successful with propagation: {len(successful)}/{len(combinations)}")
    for combo in successful:
        print(f"  - {combo}")

    print(f"\n⚠  Partial propagation: {len(partial_propagation)}/{len(combinations)}")
    for combo in partial_propagation:
        res = results[combo]
        analysis = res['analysis']
        print(f"  - {combo}: {analysis.get('propagating_episodes', 0)}/{analysis.get('total_episodes', 0)} episodes")

    print(f"\n✗ No propagation: {len(no_propagation)}/{len(combinations)}")
    for combo in no_propagation:
        print(f"  - {combo}")

    print(f"\n✗ Failed generation: {len(failed)}/{len(combinations)}")
    for combo in failed:
        res = results[combo]
        print(f"  - {combo}: {res['analysis'].get('reason', 'unknown')}")

    # Detailed analysis for problem cases
    problem_cases = no_propagation + partial_propagation + failed

    if problem_cases:
        print("\n" + "="*80)
        print("DETAILED ANALYSIS - PROBLEM CASES")
        print("="*80)

        for combo in problem_cases:
            res = results[combo]
            print(f"\n{combo}:")
            print(f"  Fault Type: {res['fault_type']}")
            print(f"  Role: {res['role']}")
            print(f"  Status: {res['analysis']['status']}")

            suggestions = suggest_remediation(
                res['fault_type'],
                res['role'],
                res['analysis']
            )

            if suggestions:
                print("  Remediation suggestions:")
                for sugg in suggestions:
                    print(f"    {sugg}")

    # Save detailed results to JSON
    results_file = os.path.join(base_output, 'test_results.json')
    with open(results_file, 'w') as f:
        # Simplify for JSON serialization
        json_results = {}
        for combo_key, res in results.items():
            json_results[combo_key] = {
                'fault_type': res['fault_type'],
                'role': res['role'],
                'status': res['analysis']['status'],
                'analysis': {
                    k: v for k, v in res['analysis'].items()
                    if k not in ['episodes']  # Exclude detailed episode data
                }
            }
        json.dump(json_results, f, indent=2)

    print(f"\n\nDetailed results saved to: {results_file}")
    print(f"Output directory: {base_output}")

    # Return exit code based on results
    if failed or no_propagation:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
