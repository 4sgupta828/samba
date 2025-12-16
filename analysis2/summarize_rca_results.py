#!/usr/bin/env python3
import json
from pathlib import Path
import sys

batch_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../data/batch_run_20251215_164016")

results = []
for rca_file in sorted(batch_dir.rglob("rca_analysis.json")):
    with open(rca_file) as f:
        data = json.load(f)

    rank = data.get('rank')
    gt = data['ground_truth']
    val = data.get('ground_truth_validation', {})

    results.append({
        'rank': rank,
        'gt': gt,
        'valid': val.get('is_valid', False),
        'confidence': val.get('confidence', 'N/A'),
        'evidence': val.get('evidence_score', 0),
        'dir': rca_file.parent.parent.name
    })

print("\n" + "="*100)
print("RCA RESULTS SUMMARY WITH GROUND TRUTH VALIDATION")
print("="*100)
print(f"{'Status':<8} {'Rank':<6} {'Ground Truth':<25} {'Valid':<7} {'Confidence':<10} {'Evidence':<10} {'Episode'}")
print("-"*100)

for r in sorted(results, key=lambda x: (x['rank'] != 1, x['rank'] if x['rank'] else 999, not x['valid'])):
    marker = '✅' if r['rank'] == 1 else '❌'
    valid_marker = '✅' if r['valid'] else '❌'
    rank_str = f"R{r['rank']}" if r['rank'] else "R?"
    print(f"{marker:<8} {rank_str:<6} {r['gt']:<25} {valid_marker:<7} {r['confidence']:<10} {r['evidence']:>2}/12      {r['dir']}")

# Stats
print("\n" + "="*100)
print("STATISTICS")
print("="*100)

rank1 = [r for r in results if r['rank'] == 1]
valid_cases = [r for r in results if r['valid']]
invalid_cases = [r for r in results if not r['valid']]

print(f"Total episodes: {len(results)}")
print(f"  ✅ Rank 1 (Success): {len(rank1)} ({len(rank1)/len(results)*100:.1f}%)")
print(f"  ❌ Not Rank 1 (Failure): {len(results) - len(rank1)} ({(len(results)-len(rank1))/len(results)*100:.1f}%)")
print()
print(f"Ground Truth Validation:")
print(f"  ✅ Valid: {len(valid_cases)} ({len(valid_cases)/len(results)*100:.1f}%)")
print(f"  ❌ Invalid: {len(invalid_cases)} ({len(invalid_cases)/len(results)*100:.1f}%)")
print()

# Success rate on valid cases only
valid_rank1 = [r for r in valid_cases if r['rank'] == 1]
print(f"Performance on VALID ground truths only:")
print(f"  Success rate: {len(valid_rank1)}/{len(valid_cases)} ({len(valid_rank1)/len(valid_cases)*100 if valid_cases else 0:.1f}%)")
print()

# Invalid cases that are rank 1 (good - RCA worked despite invalid label)
invalid_rank1 = [r for r in invalid_cases if r['rank'] == 1]
if invalid_rank1:
    print(f"Cases where RCA succeeded despite invalid ground truth: {len(invalid_rank1)}")
    for r in invalid_rank1:
        print(f"  - {r['gt']} ({r['dir']}): {r['confidence']} confidence, {r['evidence']}/12 evidence")

print("="*100)
