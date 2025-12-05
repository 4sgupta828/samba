# Pre-computed Fault Metadata System

## Overview

The fault injection system now supports **pre-computing** all LLM-based analysis during topology bank generation. This dramatically improves performance and reduces costs during high-volume dataset generation.

## Key Benefits

### 🚀 Performance
- **No LLM calls during dataset generation** - Just load JSON files
- **10-100x faster** dataset generation with LLM features
- **Parallel episode generation** without rate limits

### 💰 Cost Savings
- **Compute once, reuse forever** - Each topology analyzed once
- **~$0.50 per topology** upfront, then free forever
- **Compare:** $0.16 per episode vs $0.00 per episode with pre-computation

### 🎯 Determinism
- **Same topology → same predictions** - Reproducible results
- **No API variability** - Consistent behavior across runs
- **Easier debugging** - Same fault targets every time

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ Phase 1: Topology Bank Generation (ONE-TIME, SLOW)        │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  python generate_topology_bank.py --precompute-faults     │
│                                                            │
│  For each topology:                                        │
│    1. Generate topology with LLM                           │
│    2. For each fault type-role pair:                       │
│       ├─ Call LLM to select top-3 targets                 │
│       └─ For each target:                                  │
│           └─ Call LLM to predict propagation              │
│                                                            │
│  Save to topology_bank/topo_name/:                         │
│    ├─ graph.json                                           │
│    ├─ semantic_map.json                                    │
│    ├─ fault_targets.json          ← NEW                   │
│    └─ propagation_predictions/    ← NEW                   │
│        ├─ cpu_saturation:service:payment_service.json     │
│        ├─ slow_queries:database:db_0.json                 │
│        └─ ...                                              │
│                                                            │
│  ~30-50 LLM calls per topology                             │
│  ~2-5 minutes per topology                                 │
│  Cost: ~$0.50 per topology                                 │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Phase 2: Fault Index Generation (FAST)                    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  python generate_fault_index_fast.py                      │
│                                                            │
│  - Scans topology bank                                     │
│  - Loads pre-computed fault_targets.json from each topo   │
│  - Builds index: fault_type:role → [compatible topos]     │
│                                                            │
│  No LLM calls - just JSON parsing                          │
│  ~1 second for 50 topologies                               │
│  Cost: $0                                                  │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Phase 3: Dataset Generation (BLAZING FAST)                │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  python generate_dataset.py \\                             │
│    --llm-topologies \\                                     │
│    --llm-target-selection \\                               │
│    --llm-propagation-prediction \\                         │
│    --episodes 1000                                         │
│                                                            │
│  For each episode:                                         │
│    1. Load topology from bank                              │
│    2. Load pre-computed fault targets ← JSON file          │
│    3. Load pre-computed propagation ← JSON file            │
│    4. Run simulation                                       │
│                                                            │
│  No LLM calls - all data pre-computed!                     │
│  ~30-60 seconds per episode                                │
│  Cost: $0 (except optional post-sim analysis)             │
└────────────────────────────────────────────────────────────┘
```

## Topology Bank Structure

### Without Pre-computation
```
data/topology_bank/
└── hierarchical_banking_0/
    ├── graph.json                  # NetworkX graph
    ├── semantic_map.json           # Flows + metadata
    └── raw_llm_output.json         # Original LLM response
```

### With Pre-computation (NEW)
```
data/topology_bank/
└── hierarchical_banking_0/
    ├── graph.json
    ├── semantic_map.json
    ├── raw_llm_output.json
    ├── fault_targets.json          ← NEW: All fault targets
    └── propagation_predictions/    ← NEW: All predictions
        ├── cpu_saturation:service:payment_service.json
        ├── cpu_saturation:service:cart_service.json
        ├── cpu_saturation:service:order_service.json
        ├── slow_queries:database:db_0.json
        ├── slow_queries:database:db_1.json
        ├── cache_failure:cache:cache_0.json
        └── ...
```

### fault_targets.json Format
```json
{
  "cpu_saturation:service": [
    {
      "node_id": "payment_service",
      "score": 0.95,
      "reasoning": "Central service with high fan-out...",
      "impact_radius": {
        "direct": ["cart_service", "order_service"],
        "one_hop": ["gateway", "inventory_service"],
        "two_hop": ["analytics_service"]
      },
      "hidden_dependencies": [
        "Shares compute node with inventory_service"
      ]
    },
    {
      "node_id": "order_service",
      "score": 0.87,
      "reasoning": "Critical for checkout flow...",
      ...
    }
  ],
  "slow_queries:database": [...],
  ...
}
```

### Propagation Prediction File Format
**File:** `propagation_predictions/cpu_saturation:service:payment_service.json`
```json
{
  "fault_summary": "CPU saturation on payment_service will cause...",
  "impact_timeline": [
    {"time_range": "0-30s", "event": "Latency increases to 500ms"},
    {"time_range": "30-60s", "event": "Upstream timeouts begin"}
  ],
  "impact_by_hop": {
    "0-hop": {
      "nodes": ["payment_service"],
      "symptoms": ["CPU 95%", "Latency 500ms"],
      "severity": "CRITICAL"
    },
    "1-hop": {
      "nodes": ["cart_service", "order_service"],
      "symptoms": ["Timeout increase"],
      "propagation_mechanism": "Latency buildup",
      "severity": "MAJOR"
    }
  },
  "propagation_mechanisms": [...],
  "critical_paths": [...],
  "expected_recovery": {...}
}
```

## Usage

### Step 1: Generate Topology Bank with Pre-computation

```bash
# Generate 12 topologies with full pre-computation
python generate_topology_bank.py \
  --samples 3 \
  --output data/topology_bank \
  --precompute-faults \
  --top-k-targets 3
```

**Output:**
```
🏗️  Initializing LLM Topology Generator
📊 Generating 12 topologies (4 scenarios × 3 samples)
================================================================================

[1/12] 🏛️  Architecting hierarchical (medium)...
   ✓ Generated valid hierarchical topology on attempt 1
      🔮 Pre-computing fault metadata...
         Available roles: {'service', 'database', 'cache', 'gateway'}
         Computing for 18 fault type-role combinations...
         ✓ cpu_saturation:service: 3 targets computed
         ✓ memory_leak:service: 3 targets computed
         ✓ slow_queries:database: 2 targets computed
         ✓ cache_failure:cache: 1 targets computed
         ...
      ✅ Pre-computed metadata saved:
         - Fault targets: 12 fault types
         - Propagation predictions: 35 predictions
         - Skipped: 6 (role not available)
   ✅ Saved to data/topology_bank/hierarchical_medium_0
   📝 15 nodes, 24 edges
   🔄 4 request flow types defined
...
```

**Time & Cost:**
- **Time:** ~3-5 minutes per topology
- **Cost:** ~$0.50 per topology (30-50 LLM calls)
- **Total for 12 topologies:** ~45 minutes, ~$6

**⚠️ Important:** This is slow and expensive, but you only do it ONCE!

### Step 2: Generate Fault Index (Fast)

```bash
# Generate index from pre-computed metadata
python generate_fault_index_fast.py \
  --topology-bank data/topology_bank \
  --output data/fault_index.json
```

**Output:**
```
Found 12 topologies in data/topology_bank
Loading pre-computed fault metadata...

============================================================
FAULT INDEX GENERATION COMPLETE
============================================================
Topologies processed: 12
  - With metadata: 12
  - Without metadata: 0
Fault type-role combinations: 18
Index saved to: data/fault_index.json

============================================================
COVERAGE SUMMARY
============================================================
Total fault-topology combinations: 142

✓ Well-covered (>=10 topologies):
  cpu_saturation:service                    :  12 topologies
  memory_leak:service                       :  12 topologies
  slow_queries:database                     :  10 topologies
```

**Time & Cost:**
- **Time:** ~1 second
- **Cost:** $0 (no LLM calls!)

### Step 3: Generate Dataset (Blazing Fast!)

```bash
# Generate 100 episodes using pre-computed metadata
python generate_dataset.py \
  --episodes 100 \
  --output data/train \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --verbose
```

**Output per episode:**
```
[Pre-computed Fault Targets]
  ✓ Loaded 3 pre-computed targets for cpu_saturation:service
  Selected: payment_service
    Score: 0.95
    Reasoning: Central service with high fan-out to 5 downstream services...
    Expected Impact:
      - Direct: 5 nodes
      - 1-hop: 8 nodes
      - 2-hop: 3 nodes

[Pre-computed Fault Propagation Prediction]
  ✓ Loaded pre-computed prediction for cpu_saturation:service:payment_service
    Summary: CPU saturation on payment_service will cause severe latency...
    0-hop: 1 nodes (CRITICAL)
    1-hop: 5 nodes (MAJOR)
    2-hop: 3 nodes (MINOR)
```

**Time & Cost:**
- **Time:** ~30-60 seconds per episode
- **Cost:** $0 for target selection and propagation prediction!
- **Total for 100 episodes:** ~60 minutes, $0 (vs 8 hours, $16 with on-demand LLM)

## Fallback Logic

The system automatically falls back to on-demand LLM calls if pre-computed data is missing:

```python
# Smart loading with fallback
if precomputed_targets:
    # Use pre-computed (fast path)
    candidates = precomputed_targets
else:
    # Fall back to LLM (slow path)
    llm_selector = LLMFaultTargetSelector()
    candidates = llm_selector.select_candidates(...)
```

**Fallback scenarios:**
1. **Topology bank generated without `--precompute-faults`**
   - Falls back to on-demand LLM calls
   - Still works, just slower and more expensive

2. **New fault type added to ScenarioLibrary**
   - Pre-computed data doesn't exist for new fault type
   - Falls back to on-demand LLM for that fault type

3. **LLM pre-computation failed for specific fault type**
   - Falls back to heuristic or on-demand LLM

## Performance Comparison

### Scenario: Generate 100 episodes with LLM features

| Approach | Time | Cost | LLM Calls |
|----------|------|------|-----------|
| **On-demand LLM** | ~8 hours | ~$16 | ~800 calls |
| **Pre-computed (this system)** | ~1 hour | ~$0* | 0 calls |

*Excluding one-time pre-computation cost (~$6 for 12 topologies)

### Break-even Analysis

**Pre-computation cost:** $6 (12 topologies)
**Savings per episode:** $0.16
**Break-even:** 38 episodes

After generating 38 episodes, pre-computation pays for itself!

## Best Practices

### 1. Pre-compute Everything During Topology Bank Generation
```bash
# Always use --precompute-faults for production topology banks
python generate_topology_bank.py \
  --samples 5 \
  --precompute-faults \
  --top-k-targets 3
```

### 2. Generate Fault Index After Pre-computation
```bash
# Index enables fast lookups and coverage analysis
python generate_fault_index_fast.py \
  --topology-bank data/topology_bank \
  --output data/fault_index.json
```

### 3. Use Pre-computed Data for High-Volume Generation
```bash
# No --llm-target-selection or --llm-propagation-prediction flags needed
# System automatically uses pre-computed data!
python generate_dataset.py \
  --episodes 1000 \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction
```

### 4. Monitor Pre-computation Coverage
```bash
# Check which fault types are well-covered
cat data/fault_index.json | jq 'keys'

# Check coverage for specific fault type
cat data/fault_index.json | jq '."cpu_saturation:service" | length'
```

### 5. Regenerate Pre-computation When Adding New Fault Types
```bash
# If you add new fault types to ScenarioLibrary, regenerate
python generate_topology_bank.py \
  --precompute-faults \
  --output data/topology_bank  # Same directory, will update existing
```

## Troubleshooting

### Problem: "No pre-computed targets found"
**Symptom:**
```
[LLM-based Target Selection (on-demand)]
  No pre-computed targets found, calling LLM...
```

**Cause:** Topology bank generated without `--precompute-faults`

**Solution:**
```bash
# Regenerate with pre-computation
python generate_topology_bank.py \
  --precompute-faults \
  --output data/topology_bank
```

### Problem: Pre-computation takes too long
**Symptom:** Each topology takes 5+ minutes

**Solution:** This is expected! Pre-computation is slow but only runs once.
- Each topology requires 30-50 LLM calls
- Use `--samples 1` for testing
- Run overnight for production banks

### Problem: Some topologies missing metadata
**Symptom:**
```
⚠ hierarchical_medium_0: No fault_targets.json found (skipping)
```

**Solution:**
```bash
# Check if --precompute-faults was used
ls data/topology_bank/hierarchical_medium_0/

# If missing, regenerate:
python generate_topology_bank.py \
  --precompute-faults \
  --output data/topology_bank
```

### Problem: New fault type not in pre-computed data
**Symptom:** Falls back to on-demand LLM for new fault type

**Solution:**
```bash
# Regenerate pre-computed metadata
# This will add new fault types to existing topologies
python generate_topology_bank.py \
  --precompute-faults \
  --output data/topology_bank
```

## Migration Guide

### From On-demand LLM to Pre-computed

**Step 1:** Generate topology bank with pre-computation
```bash
python generate_topology_bank.py \
  --samples 3 \
  --precompute-faults \
  --output data/topology_bank_precomputed
```

**Step 2:** Generate fault index
```bash
python generate_fault_index_fast.py \
  --topology-bank data/topology_bank_precomputed \
  --output data/fault_index.json
```

**Step 3:** Update dataset generation command
```bash
# OLD: On-demand LLM (slow)
python generate_dataset.py \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --topology-bank data/topology_bank  # Without pre-computation

# NEW: Pre-computed (fast)
python generate_dataset.py \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --topology-bank data/topology_bank_precomputed  # With pre-computation
```

**No code changes needed!** System automatically detects and uses pre-computed data.

## API Reference

### generate_topology_bank.py
```bash
python generate_topology_bank.py \
  --output DIR                    # Topology bank directory
  --samples N                     # Samples per scenario
  --model MODEL                   # Claude model
  --precompute-faults             # Enable pre-computation (NEW)
  --top-k-targets K               # Top targets per fault type (NEW)
```

### generate_fault_index_fast.py
```bash
python generate_fault_index_fast.py \
  --topology-bank DIR             # Topology bank directory
  --output FILE                   # Output index JSON
```

### load_precomputed_fault_metadata()
```python
from generate_dataset import load_precomputed_fault_metadata

# Load pre-computed data for specific fault type
targets, predictions = load_precomputed_fault_metadata(
    topo_path='data/topology_bank/hierarchical_medium_0',
    fault_type='cpu_saturation',
    fault_target_role='service'
)

# Returns (None, None) if no pre-computed data available
```

## Summary

✅ **Pre-compute once** during topology bank generation
✅ **Reuse forever** during dataset generation
✅ **10-100x faster** episode generation
✅ **Zero cost** after initial pre-computation
✅ **Automatic fallback** if pre-computed data missing
✅ **No code changes** needed - just use new flags!

The pre-computed fault metadata system dramatically improves performance and cost efficiency for high-volume dataset generation while maintaining full backward compatibility.
