#!/bin/bash
# Test script for fault propagation enhancement
#
# This script generates test data and validates that fault propagation is working correctly.
#
# Usage: ./test_propagation.sh

set -e  # Exit on error

echo "======================================"
echo "Fault Propagation Enhancement Test"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Generate test dataset
echo "${YELLOW}Step 1: Generating test dataset (1 episode)...${NC}"
python generate_dataset.py -n 1 -v --topology-size 35

# Find the most recent dataset
LATEST_DIR=$(ls -td data/data_* | head -1)
echo "${GREEN}✓ Dataset generated: $LATEST_DIR${NC}"
echo ""

# Step 2: Check if episode has label
echo "${YELLOW}Step 2: Validating episode label...${NC}"
if [ -f "$LATEST_DIR/ep_0/label.json" ]; then
    echo "${GREEN}✓ Label file exists${NC}"
    cat "$LATEST_DIR/ep_0/label.json" | jq '.'
else
    echo "${RED}✗ Label file missing!${NC}"
    exit 1
fi
echo ""

# Step 3: Check root cause component
echo "${YELLOW}Step 3: Identifying root cause...${NC}"
ROOT_CAUSE=$(cat "$LATEST_DIR/ep_0/label.json" | jq -r '.root_cause_node')
FAULT_TYPE=$(cat "$LATEST_DIR/ep_0/label.json" | jq -r '.fault_type')
echo "Root cause: ${GREEN}$ROOT_CAUSE${NC}"
echo "Fault type: ${GREEN}$FAULT_TYPE${NC}"
echo ""

# Step 4: Check for propagation metrics (if mixin is integrated)
echo "${YELLOW}Step 4: Checking for propagation metrics...${NC}"

# Check for retry metrics
RETRY_COUNT=$(cat "$LATEST_DIR/ep_0/metrics.jsonl" | jq 'select(.name | contains("retry"))' | wc -l)
if [ $RETRY_COUNT -gt 0 ]; then
    echo "${GREEN}✓ Found $RETRY_COUNT retry metric samples${NC}"
    echo "Sample:"
    cat "$LATEST_DIR/ep_0/metrics.jsonl" | jq 'select(.name | contains("retry"))' | head -3
else
    echo "${YELLOW}⚠ No retry metrics found (mixin not yet integrated)${NC}"
fi
echo ""

# Check for circuit breaker metrics
CB_COUNT=$(cat "$LATEST_DIR/ep_0/metrics.jsonl" | jq 'select(.name | contains("circuit_breaker"))' | wc -l)
if [ $CB_COUNT -gt 0 ]; then
    echo "${GREEN}✓ Found $CB_COUNT circuit breaker metric samples${NC}"
    echo "Sample:"
    cat "$LATEST_DIR/ep_0/metrics.jsonl" | jq 'select(.name | contains("circuit_breaker"))' | head -3
else
    echo "${YELLOW}⚠ No circuit breaker metrics found (mixin not yet integrated)${NC}"
fi
echo ""

# Step 5: Analyze error propagation
echo "${YELLOW}Step 5: Analyzing error propagation...${NC}"

# Get topology to find 1-hop neighbors
echo "Finding services that depend on $ROOT_CAUSE..."
DEPENDENT_SERVICES=$(cat "$LATEST_DIR/ep_0/topology.json" | jq -r ".edges[] | select(.target == \"$ROOT_CAUSE\") | .source" | sort | uniq | head -3)

if [ -z "$DEPENDENT_SERVICES" ]; then
    echo "${YELLOW}⚠ No dependent services found (root cause may be leaf node)${NC}"
else
    echo "Dependent services:"
    echo "$DEPENDENT_SERVICES" | while read svc; do
        echo "  - $svc"
    done
    echo ""

    # Check error rates for dependent services
    echo "Checking error propagation to dependent services..."
    echo "$DEPENDENT_SERVICES" | while read svc; do
        ERROR_COUNT=$(cat "$LATEST_DIR/ep_0/logs.jsonl" | jq -c "select(.component_id == \"$svc\" and .level == \"ERROR\")" | wc -l)
        if [ $ERROR_COUNT -gt 0 ]; then
            echo "${GREEN}✓ $svc: $ERROR_COUNT errors (propagation working!)${NC}"
        else
            echo "${YELLOW}⚠ $svc: 0 errors (no propagation yet)${NC}"
        fi
    done
fi
echo ""

# Step 6: Check logs for propagation evidence
echo "${YELLOW}Step 6: Checking logs for propagation evidence...${NC}"

# Look for retry log messages
if grep -q "retry" "$LATEST_DIR/ep_0/logs.jsonl" 2>/dev/null; then
    echo "${GREEN}✓ Found retry attempts in logs${NC}"
    cat "$LATEST_DIR/ep_0/logs.jsonl" | jq -c 'select(.message | contains("retry"))' | head -3
else
    echo "${YELLOW}⚠ No retry messages found (mixin not yet integrated)${NC}"
fi
echo ""

# Look for circuit breaker log messages
if grep -q -i "circuit" "$LATEST_DIR/ep_0/logs.jsonl" 2>/dev/null; then
    echo "${GREEN}✓ Found circuit breaker events in logs${NC}"
    cat "$LATEST_DIR/ep_0/logs.jsonl" | jq -c 'select(.message | contains("circuit") or .message | contains("Circuit"))' | head -3
else
    echo "${YELLOW}⚠ No circuit breaker messages found (mixin not yet integrated)${NC}"
fi
echo ""

# Step 7: Summary
echo "======================================"
echo "Test Summary"
echo "======================================"
echo ""
echo "Dataset: $LATEST_DIR"
echo "Root cause: $ROOT_CAUSE ($FAULT_TYPE)"
echo ""

if [ $RETRY_COUNT -gt 0 ] && [ $CB_COUNT -gt 0 ]; then
    echo "${GREEN}✓✓✓ PROPAGATION ENHANCEMENT IS ACTIVE ✓✓✓${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Generate larger dataset (100+ episodes)"
    echo "2. Train GNN model"
    echo "3. Compare accuracy vs. old data"
else
    echo "${YELLOW}⚠⚠⚠ PROPAGATION ENHANCEMENT NOT YET INTEGRATED ⚠⚠⚠${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Follow PROPAGATION_INTEGRATION_GUIDE.md"
    echo "2. Integrate ServicePropagationMixin into ApiService"
    echo "3. Run this test again to validate"
fi
echo ""
