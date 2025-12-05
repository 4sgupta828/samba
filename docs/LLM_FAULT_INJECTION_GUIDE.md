# LLM-Enhanced Fault Injection and Propagation Analysis

## Overview

This system extends the fault injection framework with LLM-powered intelligence for:

1. **Intelligent Fault Target Selection** - LLM analyzes topology to select optimal fault injection targets
2. **Fault Propagation Prediction** - LLM predicts how faults will propagate before simulation runs
3. **Topology-Fault Compatibility Indexing** - Automatically index which topologies support which fault types
4. **Expected vs Actual Comparison** - Post-simulation analysis compares predicted vs observed behavior

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ LLM-Enhanced Fault Injection Pipeline                      │
│                                                             │
│ 1. Topology Loading                                         │
│    └─ LLM-generated or procedural topologies                │
│                                                             │
│ 2. Fault Target Selection                                   │
│    ├─ [NEW] LLMFaultTargetSelector                          │
│    │   ├─ Analyzes topology structure                       │
│    │   ├─ Considers impact radius & hidden dependencies     │
│    │   └─ Returns ranked candidates with reasoning          │
│    └─ [LEGACY] Heuristic-based connectivity scoring         │
│                                                             │
│ 3. Fault Propagation Prediction                             │
│    └─ [NEW] LLMFaultPropagationPredictor                    │
│        ├─ Predicts fault spread patterns                    │
│        ├─ Identifies propagation mechanisms                 │
│        ├─ Estimates impact radius (0-hop, 1-hop, 2-hop)     │
│        └─ Saves to expected_propagation.json                │
│                                                             │
│ 4. Simulation Execution                                     │
│    └─ Run SimPy simulation with fault injection             │
│                                                             │
│ 5. Post-Simulation Analysis                                 │
│    └─ [ENHANCED] LLM-based analysis with comparison         │
│        ├─ Analyze actual fault propagation                  │
│        ├─ Compare expected vs actual                        │
│        └─ Identify discrepancies & lessons learned          │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. LLMFaultTargetSelector

**File:** `src/failures/llm_target_selector.py`

**Purpose:** Intelligently selects fault injection targets using LLM reasoning.

**Key Features:**
- Analyzes topology structure (nodes, edges, flows)
- Considers impact radius (1-hop, 2-hop dependencies)
- Identifies hidden dependencies (shared compute nodes, async paths)
- Returns scored candidates with detailed reasoning

**Usage:**
```python
from src.failures.llm_target_selector import LLMFaultTargetSelector

selector = LLMFaultTargetSelector()
candidates = selector.select_candidates(
    topology=nx_graph,
    fault_type='cpu_saturation',
    fault_target_role='service',
    top_k=3
)

best_target = candidates[0]
print(f"Target: {best_target['node_id']}")
print(f"Score: {best_target['score']}")
print(f"Reasoning: {best_target['reasoning']}")
print(f"Impact Radius: {best_target['impact_radius']}")
```

**Example Output:**
```json
{
  "node_id": "payment_service",
  "score": 0.95,
  "reasoning": "Central service with high fan-out to 5 downstream services. Critical path for all transactions. Failure will cascade to cart_service, order_service, and notification_service.",
  "impact_radius": {
    "direct": ["cart_service", "order_service", "notification_service"],
    "one_hop": ["gateway", "inventory_service", "email_service"],
    "two_hop": ["user_service", "analytics_service"]
  },
  "hidden_dependencies": [
    "Shares compute node with inventory_service",
    "Gateway depends on this for all POST requests"
  ]
}
```

### 2. LLMFaultPropagationPredictor

**File:** `src/failures/llm_propagation_predictor.py`

**Purpose:** Predicts how a fault will propagate through the system before simulation runs.

**Key Features:**
- Analyzes N-hop neighborhoods (upstream/downstream)
- Predicts propagation mechanisms (latency buildup, backpressure, resource starvation)
- Identifies hidden impacts (shared compute nodes, async consumers)
- Generates timeline of expected events
- Predicts recovery patterns

**Usage:**
```python
from src.failures.llm_propagation_predictor import LLMFaultPropagationPredictor

predictor = LLMFaultPropagationPredictor()
prediction = predictor.predict_propagation(
    topology=nx_graph,
    fault_node_id='payment_service',
    fault_type='cpu_saturation',
    fault_params={'cpu_percent': 95}
)

print(f"Summary: {prediction['fault_summary']}")
print(f"Impact Timeline: {prediction['impact_timeline']}")
print(f"Propagation Mechanisms: {prediction['propagation_mechanisms']}")
```

**Example Output:**
```json
{
  "fault_summary": "CPU saturation on payment_service will cause severe latency increases, cascading to 8 services within 60 seconds.",
  "impact_timeline": [
    {"time_range": "0-30s", "event": "payment_service latency increases to 500ms"},
    {"time_range": "30-60s", "event": "cart_service begins timing out waiting for payment_service"},
    {"time_range": "60s+", "event": "Gateway error rate increases, cascading failures"}
  ],
  "impact_by_hop": {
    "0-hop": {
      "nodes": ["payment_service"],
      "symptoms": ["CPU 95%", "Latency 500ms", "Thread queueing"],
      "severity": "CRITICAL"
    },
    "1-hop": {
      "nodes": ["cart_service", "order_service"],
      "symptoms": ["Timeout increase", "Request queueing"],
      "propagation_mechanism": "Latency buildup - clients wait for slow responses",
      "severity": "MAJOR"
    }
  },
  "propagation_mechanisms": [
    "Latency buildup: Slow responses cascade to callers",
    "Thread exhaustion: Clients run out of threads waiting for responses"
  ],
  "critical_paths": [
    {"flow": "POST /api/checkout", "impact": "HIGH", "reason": "All checkout requests traverse payment_service"}
  ]
}
```

### 3. Topology-Fault Index Generator

**File:** `generate_fault_index.py`

**Purpose:** Pre-generates an index mapping fault types to compatible topologies.

**Usage:**
```bash
python generate_fault_index.py \
  --topology-bank data/topology_bank \
  --output data/fault_index.json \
  --top-k 3
```

**Output:**
```json
{
  "cpu_saturation:service": [
    {
      "topology_id": "hierarchical_banking_0",
      "topology_file": "data/topology_bank/hierarchical_banking_0.json",
      "domain": "Banking System",
      "candidates": [...]
    }
  ],
  "slow_queries:database": [...]
}
```

**Benefits:**
- Quick lookup of compatible topologies for any fault type
- Pre-computed target candidates for faster dataset generation
- Coverage analysis - identify under-represented fault types
- Dataset balancing - ensure diverse fault-topology combinations

## Dataset Generation with LLM Features

### Command-Line Interface

#### Basic Usage (Heuristic Target Selection)
```bash
python generate_dataset.py \
  --episodes 10 \
  --output data/train \
  --llm-topologies \
  --verbose
```

#### With LLM Target Selection
```bash
python generate_dataset.py \
  --episodes 10 \
  --output data/train \
  --llm-topologies \
  --llm-target-selection \
  --verbose
```

**What happens:**
1. Loads topology from topology bank
2. **LLM analyzes topology** and selects optimal fault target
3. Shows reasoning for target selection
4. Continues with standard simulation

**Example Output:**
```
[LLM-based Target Selection]
  Using LLM to select optimal fault target for cpu_saturation on service...
  ✓ LLM selected: payment_service
    Score: 0.95
    Reasoning: Central service with high fan-out to 5 downstream services...
    Expected Impact:
      - Direct: 5 nodes
      - 1-hop: 8 nodes
      - 2-hop: 3 nodes
```

#### With Fault Propagation Prediction
```bash
python generate_dataset.py \
  --episodes 10 \
  --output data/train \
  --llm-topologies \
  --llm-propagation-prediction \
  --verbose
```

**What happens:**
1. Loads topology and selects fault target
2. **LLM predicts fault propagation** before simulation
3. Saves prediction to `expected_propagation.json`
4. Runs simulation
5. Compares expected vs actual in post-simulation analysis

**Example Output:**
```
[LLM-based Fault Propagation Prediction]
  Generating expected propagation pattern...
  ✓ Expected propagation saved to: data/train/ep_0/expected_propagation.json
    Summary: CPU saturation on payment_service will cause severe latency increases...
    0-hop: 1 nodes (CRITICAL)
    1-hop: 5 nodes (MAJOR)
    2-hop: 3 nodes (MINOR)
```

#### Full LLM Pipeline (Recommended)
```bash
python generate_dataset.py \
  --episodes 10 \
  --output data/train \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --enable-llm-analysis \
  --verbose
```

**What happens:**
1. Uses LLM-generated topologies
2. Uses LLM for intelligent target selection
3. Generates fault propagation prediction
4. Runs simulation
5. Performs comprehensive LLM analysis
6. Compares expected vs actual propagation
7. Outputs lessons learned

### Output Files

Each episode directory contains:

**Standard Files:**
- `label.json` - Ground truth fault information
- `topology.json` - System topology graph
- `metrics.jsonl` - Time-series metrics
- `logs.jsonl` - Component logs
- `fault_propagation.json` - Observed propagation analysis

**New LLM-Enhanced Files:**
- `expected_propagation.json` - Pre-simulation propagation prediction
- `llm_analysis.json` - Enhanced with expected vs actual comparison

### Expected vs Actual Comparison

When both `expected_propagation.json` and `llm_analysis.json` exist, the analysis includes:

```json
{
  "propagation_comparison": {
    "overall_accuracy": "MEDIUM",
    "accuracy_summary": "Predicted impact radius was accurate, but missed shared compute node contention affecting 2 additional services.",
    "accurate_predictions": [
      {
        "aspect": "Impact radius",
        "details": "Predicted 5 nodes in 1-hop, actual was 5 nodes"
      },
      {
        "aspect": "Propagation mechanism",
        "details": "Correctly predicted latency buildup would cause upstream timeouts"
      }
    ],
    "inaccurate_predictions": [
      {
        "aspect": "Hidden impacts",
        "details": "Did not predict shared compute node contention would affect inventory_service"
      }
    ],
    "unexpected_behaviors": [
      {
        "behavior": "inventory_service failed unexpectedly",
        "reason": "Shared compute node with payment_service caused CPU starvation"
      }
    ],
    "lessons_learned": [
      "Shared compute node contention is difficult to predict from topology alone",
      "Pod colocation has non-obvious performance impacts"
    ]
  }
}
```

## Advanced Usage

### Using Fault Index for Dataset Balancing

```python
import json

# Load fault index
with open('data/fault_index.json', 'r') as f:
    fault_index = json.load(f)

# Find topologies that support a specific fault type
compatible_topos = fault_index.get('cpu_saturation:service', [])

# Select topology with most candidates
best_topo = max(compatible_topos, key=lambda t: len(t['candidates']))

# Generate episode with this topology
python generate_dataset.py \
  --episodes 1 \
  --llm-topologies \
  --topology-name {best_topo['topology_id']} \
  --fault-type cpu_saturation \
  --fault-role service
```

### Custom LLM Models

```bash
# Use Anthropic Claude (default)
python generate_dataset.py \
  --llm-target-selection \
  --llm-propagation-prediction

# Use OpenAI GPT-4
python generate_dataset.py \
  --llm-target-selection \
  --llm-propagation-prediction \
  --llm-provider openai \
  --llm-model gpt-4o
```

### Debugging LLM Predictions

```python
# Load expected propagation
with open('data/train/ep_0/expected_propagation.json', 'r') as f:
    expected = json.load(f)

# Load actual analysis
with open('data/train/ep_0/llm_analysis.json', 'r') as f:
    actual = json.load(f)

# Compare impact radius
print("Expected 1-hop:", expected['impact_by_hop']['1-hop']['nodes'])
print("Actual impact:", actual['impacted_services'])

# Check propagation mechanisms
print("Predicted mechanisms:", expected['propagation_mechanisms'])
print("Observed propagation:", actual['propagation_summary'])
```

## Performance Considerations

### LLM Call Costs

| Feature | LLM Calls per Episode | Approx. Tokens | Cost (Claude Sonnet) |
|---------|----------------------|----------------|---------------------|
| Target Selection | 1 | ~2000-3000 | $0.01 |
| Propagation Prediction | 1 | ~4000-6000 | $0.02 |
| Post-Sim Analysis | 5 | ~15000-20000 | $0.10 |
| Expected vs Actual | 1 | ~5000-8000 | $0.03 |
| **Total per Episode** | ~8 | ~30000 | $0.16 |

### Optimization Tips

1. **Batch Generation:** Generate multiple episodes in parallel to amortize LLM overhead
2. **Selective Features:** Use `--llm-target-selection` only, skip propagation prediction for faster runs
3. **Cache Fault Index:** Pre-generate topology-fault index to avoid repeated LLM calls
4. **Use Haiku for Quick Tests:** Use `claude-haiku` model for development/testing

```bash
# Fast mode - target selection only
python generate_dataset.py \
  --episodes 100 \
  --llm-target-selection \
  --output data/train_fast

# Full mode - all LLM features
python generate_dataset.py \
  --episodes 20 \
  --llm-target-selection \
  --llm-propagation-prediction \
  --enable-llm-analysis \
  --output data/train_full
```

## Evaluation & Metrics

### Target Selection Accuracy

Compare LLM-selected targets vs heuristic-selected targets:

```bash
# Generate with heuristic
python generate_dataset.py --episodes 50 --output data/heuristic

# Generate with LLM
python generate_dataset.py --episodes 50 --llm-target-selection --output data/llm

# Compare blast radius
python analysis/compare_target_quality.py \
  --baseline data/heuristic \
  --experiment data/llm
```

### Propagation Prediction Accuracy

Analyze prediction accuracy across episodes:

```bash
python analysis/evaluate_propagation_predictions.py \
  --episodes data/train/ep_* \
  --output analysis/prediction_accuracy.json
```

Expected output:
```json
{
  "overall_accuracy": 0.72,
  "accuracy_by_fault_type": {
    "cpu_saturation": 0.85,
    "slow_queries": 0.68,
    "cache_failure": 0.60
  },
  "common_misses": [
    "Shared compute node contention (40% miss rate)",
    "Async consumer lag amplification (25% miss rate)"
  ]
}
```

## Troubleshooting

### LLM Returns No Candidates

**Symptom:** `LLM returned no candidates, falling back to heuristic selection`

**Causes:**
- Topology too small/simple for meaningful analysis
- No nodes matching fault_target_role
- LLM response parsing error

**Solution:**
```bash
# Check topology has required roles
python -c "
import json
with open('data/topology_bank/topo_0/graph.json') as f:
    g = json.load(f)
    roles = {n['role'] for n in g['nodes']}
    print('Available roles:', roles)
"

# Increase verbosity to see LLM response
python generate_dataset.py --llm-target-selection --verbose
```

### Expected Propagation Missing

**Symptom:** No `expected_propagation.json` file generated

**Causes:**
- `--llm-propagation-prediction` flag not set
- Fault injection failed before prediction
- LLM API error

**Solution:**
```bash
# Verify flag is set
python generate_dataset.py \
  --llm-propagation-prediction \
  --verbose \
  --episodes 1

# Check for errors in episode log
cat data/train/ep_0/simulation.log | grep -i error
```

### Comparison Analysis Missing

**Symptom:** No `propagation_comparison` in `llm_analysis.json`

**Causes:**
- `expected_propagation.json` not generated
- `--enable-llm-analysis` not set
- Post-simulation analysis disabled

**Solution:**
```bash
# Ensure all flags are set
python generate_dataset.py \
  --llm-propagation-prediction \
  --enable-llm-analysis \
  --episodes 1
```

## Best Practices

1. **Start Small:** Test with 1-2 episodes before large runs
2. **Use Topology Bank:** Pre-generate topologies to avoid repeated LLM calls
3. **Generate Fault Index:** Run `generate_fault_index.py` once for the topology bank
4. **Monitor Costs:** Track LLM API usage during large dataset generation
5. **Validate Predictions:** Regularly review expected vs actual comparisons
6. **Tune Selection:** Adjust `top_k` parameter based on prediction accuracy
7. **Combine with Forensics:** Use predictions to improve GNN training labels

## Future Enhancements

- [ ] Adaptive prediction refinement based on historical accuracy
- [ ] Multi-fault interaction prediction
- [ ] Real-time prediction updates during simulation
- [ ] Prediction confidence scores
- [ ] Active learning from prediction errors
- [ ] Topology mutation suggestions to test edge cases

## References

- **LLM Target Selector:** `src/failures/llm_target_selector.py`
- **LLM Propagation Predictor:** `src/failures/llm_propagation_predictor.py`
- **Enhanced Analysis:** `llm_analysis.py`
- **Dataset Generation:** `generate_dataset.py`
- **Fault Index Generator:** `generate_fault_index.py`
