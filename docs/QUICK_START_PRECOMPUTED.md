# Quick Start: Pre-computed Fault Metadata

Get started with blazing-fast LLM-enhanced dataset generation in 3 steps!

## Prerequisites

```bash
# Set your Anthropic API key
export ANTHROPIC_API_KEY="your-key-here"
```

## Step 1: Generate Topology Bank (ONE-TIME, ~45 mins)

```bash
python generate_topology_bank.py \
  --samples 3 \
  --output data/topology_bank \
  --precompute-faults \
  --top-k-targets 3
```

**What this does:**
- Generates 12 diverse topologies using Claude
- Pre-computes fault targets for ALL fault types
- Pre-computes propagation predictions for ALL targets
- Saves everything to `data/topology_bank/`

**Cost:** ~$6 (one-time)
**Time:** ~45 minutes (one-time)

**⚠️ This is slow and expensive, but you only do it ONCE!**

---

## Step 2: Generate Fault Index (FAST, ~1 second)

```bash
python generate_fault_index_fast.py \
  --topology-bank data/topology_bank \
  --output data/fault_index.json
```

**What this does:**
- Scans topology bank for pre-computed metadata
- Builds index: `fault_type:role → compatible topologies`
- Shows coverage analysis

**Cost:** $0
**Time:** ~1 second

---

## Step 3: Generate Dataset (BLAZING FAST!)

```bash
python generate_dataset.py \
  --episodes 100 \
  --output data/train \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --verbose
```

**What this does:**
- Loads topology from bank
- **Loads pre-computed fault targets** (instant!)
- **Loads pre-computed propagation predictions** (instant!)
- Runs simulation
- Repeats 100 times

**Cost:** $0 (for target selection & propagation prediction)
**Time:** ~60 minutes for 100 episodes

**🚀 Compare:** Without pre-computation: ~8 hours, $16

---

## Verification

### Check Topology Bank Structure
```bash
ls -R data/topology_bank/hierarchical_medium_0/

# Should see:
# - graph.json
# - semantic_map.json
# - fault_targets.json          ← NEW
# - propagation_predictions/    ← NEW
```

### Check Fault Index
```bash
cat data/fault_index.json | jq 'keys | .[:5]'

# Should see fault type-role combinations:
# [
#   "cache_failure:cache",
#   "cpu_saturation:service",
#   "memory_leak:service",
#   ...
# ]
```

### Check Episode Output
```bash
ls data/train/ep_0/

# Should see:
# - label.json
# - topology.json
# - expected_propagation.json    ← FROM PRE-COMPUTED DATA
# - metrics.jsonl
# - logs.jsonl
```

---

## What You Get

### During Episode Generation:
```
[Pre-computed Fault Targets]
  ✓ Loaded 3 pre-computed targets for cpu_saturation:service
  Selected: payment_service
    Score: 0.95
    Reasoning: Central service with high fan-out to 5 downstream...
```

### No LLM Calls!
- **Target selection:** Loaded from `fault_targets.json`
- **Propagation prediction:** Loaded from `propagation_predictions/`
- **Result:** 10-100x faster, zero cost!

---

## Next Steps

### Generate More Episodes
```bash
# The more episodes you generate, the more you save!
python generate_dataset.py \
  --episodes 1000 \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction
```

### Add More Topologies
```bash
# Expand your topology bank
python generate_topology_bank.py \
  --samples 10 \
  --precompute-faults \
  --output data/topology_bank
```

### View Coverage
```bash
# See which fault types are well-represented
cat data/fault_index.json | jq 'to_entries | .[] | {fault: .key, count: (.value | length)}'
```

---

## Troubleshooting

### "No pre-computed targets found"
**Problem:** Topology bank generated without `--precompute-faults`

**Solution:**
```bash
python generate_topology_bank.py \
  --precompute-faults \
  --output data/topology_bank
```

### Episodes using on-demand LLM
**Problem:** Missing `--llm-topologies` flag

**Solution:**
```bash
# Must use --llm-topologies to load from topology bank
python generate_dataset.py \
  --llm-topologies \     ← REQUIRED
  --llm-target-selection \
  --llm-propagation-prediction
```

---

## Key Points

✅ **Pre-compute once** (Step 1) - Slow & expensive
✅ **Reuse forever** (Step 3) - Fast & free
✅ **Break-even at 38 episodes** - After that, pure savings!
✅ **No code changes** - System auto-detects pre-computed data
✅ **Automatic fallback** - Works even without pre-computation

---

## Cost Breakdown

| Operation | Time | Cost | Frequency |
|-----------|------|------|-----------|
| **Step 1: Pre-compute** | 45 min | $6 | Once |
| **Step 2: Index** | 1 sec | $0 | Once |
| **Step 3: Episode** | 30-60 sec | $0* | Many |

*Per episode, for target selection & propagation prediction

**Total for 100 episodes:**
- **With pre-computation:** 45min + 60min = 105 min, $6 total
- **Without pre-computation:** 8 hours, $16 total
- **Savings:** 6.6x faster, 2.7x cheaper!

**And it gets better:** The more episodes you generate, the more you save!
