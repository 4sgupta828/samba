#!/usr/bin/env python3
import json
from pathlib import Path

batch = Path('../data/batch_run_20251215_164016')

# Find the 2 failing valid cases
for rca_file in sorted(batch.rglob('rca_analysis.json')):
    with open(rca_file) as f:
        data = json.load(f)

    val = data.get('ground_truth_validation', {})
    rank = data.get('rank')

    # Valid but not rank 1
    if val.get('is_valid') and rank != 1:
        gt = data['ground_truth']
        print('\n' + '='*80)
        print(f'Episode: {rca_file.parent.parent.name}')
        print(f'Ground Truth: {gt} (Rank: {rank})')
        print(f'Validation: {val.get("confidence")} confidence, {val.get("evidence_score")}/12 evidence')
        print('='*80)

        # Find ground truth in candidates
        gt_candidate = None
        for c in data['all_candidates']:
            if c['node'] == gt:
                gt_candidate = c
                break

        if gt_candidate:
            print('\nGround Truth Analysis:')
            print(f'  Score: {gt_candidate["score"]:.2f}')
            print(f'  Integrated score: {gt_candidate.get("integrated_score", 0):.2f}')
            print(f'  Self score: {gt_candidate.get("self_score", 0):.2f}')
            print(f'  Trace score: {gt_candidate.get("trace_score", 0):.2f}')
            print(f'  Temporal score: {gt_candidate.get("temporal_score", 0):.2f}')
            print(f'  Guilt ratio: {gt_candidate.get("guilt_raw", 0):.2f}')
            print(f'  Is healthy: {gt_candidate.get("is_healthy")}')
            print(f'  Symptoms: {len(gt_candidate.get("symptoms", []))} - {", ".join(gt_candidate.get("symptoms", [])[:3])}')

            trace_info = gt_candidate.get('trace_info', {})
            if trace_info:
                print('\nTrace Info:')
                print(f'  Authoritative: {trace_info.get("is_authoritative")}')
                print(f'  Self-time degradation: {trace_info.get("self_time_degradation", 1.0):.2f}x')
                print(f'  Total-time degradation: {trace_info.get("total_time_degradation", 1.0):.2f}x')
                print(f'  Reason: {trace_info.get("reason", "N/A")}')

        # Show top 5
        print('\nTop 5 Candidates:')
        for i, c in enumerate(data['top_candidates'][:5], 1):
            marker = '👉' if c['node'] == gt else '  '
            auth_marker = '✓' if c.get('is_trace_authoritative') else ' '
            print(f'{marker} {i}. {c["node"]:25} Score: {c["score"]:6.2f} (int:{c.get("integrated_score", 0):5.2f}, trace:{c.get("trace_score", 0):4.2f}, symp:{len(c.get("symptoms", []))}, auth:{auth_marker})')

        # Show all candidates with ground truth
        all_nodes = [c['node'] for c in data['all_candidates']]
        if gt in all_nodes:
            gt_pos = all_nodes.index(gt) + 1
            print(f'\nGround truth position in full ranking: {gt_pos}/{len(all_nodes)}')
