#!/bin/bash
# LLM-Enhanced Fault Injection Demo
# This script demonstrates the new LLM-based features

set -e

echo "========================================="
echo "LLM-Enhanced Fault Injection Demo"
echo "========================================="
echo ""

# Create demo output directory
DEMO_DIR="data/demo_llm_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEMO_DIR"

echo "Demo output directory: $DEMO_DIR"
echo ""

# ===================================================================
# Demo 1: Basic LLM Target Selection
# ===================================================================
echo "========================================="
echo "Demo 1: LLM Target Selection"
echo "========================================="
echo "Generating 1 episode with LLM-based target selection..."
echo ""

python generate_dataset.py \
  --episodes 1 \
  --output "$DEMO_DIR/demo1_target_selection" \
  --llm-topologies \
  --llm-target-selection \
  --verbose

echo ""
echo "✓ Demo 1 Complete!"
echo "  Check: $DEMO_DIR/demo1_target_selection/ep_0/"
echo "  - LLM selected optimal fault target"
echo "  - See reasoning in console output above"
echo ""
read -p "Press Enter to continue to Demo 2..."
echo ""

# ===================================================================
# Demo 2: Fault Propagation Prediction
# ===================================================================
echo "========================================="
echo "Demo 2: Fault Propagation Prediction"
echo "========================================="
echo "Generating 1 episode with propagation prediction..."
echo ""

python generate_dataset.py \
  --episodes 1 \
  --output "$DEMO_DIR/demo2_propagation_prediction" \
  --llm-topologies \
  --llm-propagation-prediction \
  --verbose

echo ""
echo "✓ Demo 2 Complete!"
echo "  Check: $DEMO_DIR/demo2_propagation_prediction/ep_0/"
echo "  - expected_propagation.json contains pre-simulation prediction"
echo ""
echo "View prediction:"
echo "  cat $DEMO_DIR/demo2_propagation_prediction/ep_0/expected_propagation.json | jq .fault_summary"
echo ""
read -p "Press Enter to continue to Demo 3..."
echo ""

# ===================================================================
# Demo 3: Full LLM Pipeline
# ===================================================================
echo "========================================="
echo "Demo 3: Full LLM Pipeline"
echo "========================================="
echo "Generating 1 episode with all LLM features..."
echo "  - LLM target selection"
echo "  - Propagation prediction"
echo "  - Post-simulation analysis"
echo "  - Expected vs actual comparison"
echo ""

python generate_dataset.py \
  --episodes 1 \
  --output "$DEMO_DIR/demo3_full_pipeline" \
  --llm-topologies \
  --llm-target-selection \
  --llm-propagation-prediction \
  --enable-llm-analysis \
  --verbose

echo ""
echo "✓ Demo 3 Complete!"
echo "  Check: $DEMO_DIR/demo3_full_pipeline/ep_0/"
echo "  - expected_propagation.json: Pre-simulation prediction"
echo "  - llm_analysis.json: Post-simulation analysis with comparison"
echo ""
echo "View comparison:"
echo "  cat $DEMO_DIR/demo3_full_pipeline/ep_0/llm_analysis.json | jq .propagation_comparison"
echo ""
read -p "Press Enter to continue to Demo 4..."
echo ""

# ===================================================================
# Demo 4: Topology-Fault Index Generation
# ===================================================================
echo "========================================="
echo "Demo 4: Topology-Fault Index"
echo "========================================="
echo "Generating topology-fault compatibility index..."
echo "This indexes which topologies support which fault types."
echo ""

if [ ! -d "data/topology_bank" ]; then
    echo "⚠ Topology bank not found at data/topology_bank"
    echo "  Run generate_topology_bank.py first to create topologies"
    echo "  Skipping this demo..."
else
    python generate_fault_index.py \
      --topology-bank data/topology_bank \
      --output "$DEMO_DIR/fault_index.json" \
      --top-k 3

    echo ""
    echo "✓ Demo 4 Complete!"
    echo "  Check: $DEMO_DIR/fault_index.json"
    echo "  - Shows which topologies support which fault types"
    echo "  - Includes pre-computed target candidates"
    echo ""
    echo "View index structure:"
    echo "  cat $DEMO_DIR/fault_index.json | jq 'keys | .[:5]'"
    echo ""
fi

# ===================================================================
# Summary
# ===================================================================
echo ""
echo "========================================="
echo "Demo Complete!"
echo "========================================="
echo ""
echo "Summary of generated data:"
echo "  Demo 1: $DEMO_DIR/demo1_target_selection/"
echo "  Demo 2: $DEMO_DIR/demo2_propagation_prediction/"
echo "  Demo 3: $DEMO_DIR/demo3_full_pipeline/"
echo "  Demo 4: $DEMO_DIR/fault_index.json"
echo ""
echo "Key Files to Inspect:"
echo ""
echo "1. Expected Propagation:"
echo "   cat $DEMO_DIR/demo3_full_pipeline/ep_0/expected_propagation.json | jq ."
echo ""
echo "2. Propagation Comparison:"
echo "   cat $DEMO_DIR/demo3_full_pipeline/ep_0/llm_analysis.json | jq .propagation_comparison"
echo ""
echo "3. Lessons Learned:"
echo "   cat $DEMO_DIR/demo3_full_pipeline/ep_0/llm_analysis.json | jq .propagation_comparison.lessons_learned"
echo ""
echo "4. Fault Index:"
echo "   cat $DEMO_DIR/fault_index.json | jq 'keys | .[:10]'"
echo ""
echo "Next Steps:"
echo "  - Review the generated files"
echo "  - Compare expected vs actual propagation in Demo 3"
echo "  - Experiment with different fault types and topologies"
echo "  - See docs/LLM_FAULT_INJECTION_GUIDE.md for more info"
echo ""
echo "========================================="
