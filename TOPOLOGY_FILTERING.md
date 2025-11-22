# Topology Filtering by Root Cause Reachability

This document explains how to use the topology filtering scripts to generate subset topologies based on root cause reachability.

## Overview

When analyzing failure scenarios, it's useful to focus only on the parts of the system that can be potentially affected by a root cause. These scripts help you:

1. **Identify reachable nodes**: Find all nodes that can be affected by a root cause through graph traversal
2. **Generate filtered topologies**: Create subset topology graphs containing only reachable nodes
3. **Distinguish potential vs. actual impact**: Compare what *can* be affected (filtered topology) with what *is* affected (metrics/logs)

## How It Works

### Graph Traversal Logic

The filtering uses **reverse graph traversal** to find affected nodes:

1. In a microservice call graph: `A -> B` means "A calls B"
2. When B fails, A (the caller) is affected
3. The script builds a reverse graph where `B -> A` means "if B fails, A is affected"
4. BFS traversal from the root cause finds all potentially affected nodes

### Example

```
Original Graph:
  gateway -> svc_1 -> svc_2 -> db_0
                  \-> svc_3 -> ext_0

If ext_0 is the root cause:
  - ext_0 is affected (root cause)
  - svc_3 is affected (calls ext_0)
  - svc_1 is affected (calls svc_3)
  - gateway is affected (calls svc_1)
  - svc_2 and db_0 are NOT affected (not in the call path)
```

## Scripts

### 1. `filter_topology_by_root_cause.py` - Single Episode Filter

Filters a single episode's topology based on the root cause.

#### Usage

```bash
# Basic usage - reads root cause from label.json
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0

# Specify custom output path
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --output custom_filtered.json

# Override root cause node
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --root-cause svc_5

# Quiet mode (no summary)
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0 --quiet
```

#### Output

- Creates `topology_filtered.json` in the episode directory (or custom path)
- Prints summary showing:
  - Root cause node
  - Original vs. filtered node/edge counts
  - List of reachable nodes

#### Output Format

The filtered topology includes all original fields plus metadata:

```json
{
  "nodes": [...],
  "edges": [...],
  "num_nodes": 14,
  "num_edges": 22,
  "is_directed": true,
  "filter_metadata": {
    "original_num_nodes": 25,
    "original_num_edges": 47,
    "reachable_nodes": 14,
    "removed_nodes": 11,
    "removed_edges": 25
  }
}
```

### 2. `batch_filter_topologies.py` - Batch Processing

Filters multiple episodes in a dataset directory.

#### Usage

```bash
# Process all episodes in a dataset
python batch_filter_topologies.py data/data_20251121_185526

# Use custom pattern for episode directories
python batch_filter_topologies.py data/data_20251121_185526 --pattern "episode_*"

# Quiet mode
python batch_filter_topologies.py data/data_20251121_185526 --quiet
```

#### Requirements

Each episode directory must contain:
- `topology.json` - Original topology
- `label.json` - Ground truth with `root_cause_node` field

#### Output

Creates `topology_filtered.json` in each episode directory with summary:

```
Found 2 episode(s) to process

Processing: ep_0
  Root Cause: ext_0
  Nodes: 25 -> 14 (removed 11)
  Edges: 47 -> 22 (removed 25)
  Saved to: topology_filtered.json

Processing: ep_1
  Root Cause: db_0
  Nodes: 10 -> 8 (removed 2)
  Edges: 16 -> 12 (removed 4)
  Saved to: topology_filtered.json

============================================================
Batch Processing Complete
============================================================
Successfully processed: 2/2 episodes
============================================================
```

## Use Cases

### 1. Focus Visualization

Use filtered topologies to simplify visualizations by showing only relevant parts of the system:

```python
# Load filtered topology instead of full topology
with open('data/episode/topology_filtered.json', 'r') as f:
    topology = json.load(f)

# Visualize only the affected subgraph
visualize_topology(topology)
```

### 2. Analysis Scope Reduction

Filter out noise when analyzing metrics/logs:

```python
# Get reachable nodes from filtered topology
reachable_nodes = {node['id'] for node in topology['nodes']}

# Filter metrics to only reachable nodes
filtered_metrics = [m for m in metrics if m['component_id'] in reachable_nodes]
```

### 3. Compare Potential vs. Actual Impact

```python
# Load filtered topology (potential impact)
with open('topology_filtered.json', 'r') as f:
    filtered = json.load(f)
    potentially_affected = {node['id'] for node in filtered['nodes']}

# Analyze metrics to find actually affected nodes
actually_affected = find_degraded_components(metrics)

# Find nodes that were potentially but not actually affected
false_positives = potentially_affected - actually_affected

# Find nodes that were affected but shouldn't be reachable
false_negatives = actually_affected - potentially_affected
```

### 4. Training Data Generation

Generate focused training data for RCA models:

```python
# Only include features for reachable nodes
for episode in episodes:
    topology = load_filtered_topology(episode)
    reachable_nodes = {node['id'] for node in topology['nodes']}

    # Filter features
    features = extract_features(episode, node_filter=reachable_nodes)

    # Train with reduced feature space
    model.train(features, labels)
```

## UI Integration

The topology filtering feature is fully integrated with the Samba Telemetry Dashboard!

### Using the UI

1. **Generate Filtered Topologies** (one-time setup):
   ```bash
   # Generate for all data runs
   ./generate_filtered_topologies.sh

   # Or generate for specific data run
   ./generate_filtered_topologies.sh data/data_20251121_185526

   # Or manually for a single episode
   python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0
   ```

2. **Start the Dashboard**:
   ```bash
   python viz/app.py
   ```

3. **View Filtered Topologies**:
   - Load an episode in the dashboard
   - In the topology card header, toggle **"Filter by Root Cause"**
   - The topology will update to show only reachable nodes
   - A status message shows how many nodes were filtered

### UI Features

#### Filter Toggle
- **Enabled**: When filtered topology exists for the episode
- **Disabled**: Shows "(not generated)" if filtered topology doesn't exist
- **Status**: Displays node count and reduction percentage

#### Behavior
- **When enabled**: Shows only nodes reachable from root cause
- **When disabled**: Shows full topology
- **Works with**: Type filters (Gateway, Service, Database, etc.)
- **Updates**: Instantly when toggled

#### Visual Feedback
Below the topology graph, you'll see:
- `Showing 14 nodes reachable from root cause (11 nodes hidden)` - Filtered view
- `Showing full topology (25 nodes)` - Full view

### Screenshots

```
┌─────────────────────────────────────────────────────────┐
│ 🗺️ System Topology                                      │
│     [✓] Filter by Root Cause   Show: [✓]Service [✓]DB  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│          [Filtered topology graph]                      │
│                                                         │
│  Showing 14 nodes reachable from root cause            │
│  (11 nodes hidden)                                      │
└─────────────────────────────────────────────────────────┘
```

## Command-Line Examples

```bash
# Filter single episode
python filter_topology_by_root_cause.py data/mydata/ep_0

# Batch filter all episodes
python batch_filter_topologies.py data/mydata

# Filter with custom root cause (for testing)
python filter_topology_by_root_cause.py data/mydata/ep_0 --root-cause db_1

# Batch filter with custom pattern
python batch_filter_topologies.py data/mydata --pattern "experiment_*"

# Generate filtered topologies for visualization
python batch_filter_topologies.py data/mydata --quiet && \
  python viz/app.py --use-filtered-topology
```

## Troubleshooting

### Issue: "Root cause node not found in topology"

**Cause**: The root cause node ID in `label.json` doesn't match any node in `topology.json`

**Solution**: Check for typos or use `--root-cause` to override

### Issue: "No episode directories found"

**Cause**: Episode directories don't match the pattern or missing required files

**Solution**:
- Ensure directories match pattern (default: `ep_*`)
- Verify each directory has both `topology.json` and `label.json`
- Use `--pattern` to specify custom pattern

### Issue: All nodes are reachable (no filtering)

**Cause**: The root cause is highly connected (e.g., a gateway or frontend service)

**Explanation**: This is expected behavior - if the root cause affects most of the system, the filtered topology will be similar to the original

## Technical Details

### Algorithm Complexity

- **Time**: O(V + E) where V = nodes, E = edges (BFS traversal)
- **Space**: O(V) for storing reachable set and queue

### Graph Properties

- **Directed Graph**: Preserves edge directions from original topology
- **Weakly Connected**: Original topology is weakly connected by design
- **Reachability**: Computes transitive closure from root cause in reverse direction

### Edge Type Preservation

All edge types are preserved in filtered topology:
- `sync_rpc` - Synchronous RPC calls
- `sync_http` - HTTP requests (gateway)
- `sync_db` - Database queries
- `sync_cache` - Cache operations
- `sync_external` - External API calls
- `async_produce` - Queue message production
- `async_consume` - Queue message consumption

## Future Enhancements

Potential improvements to consider:

1. **Multi-root-cause support**: Handle scenarios with multiple simultaneous failures
2. **Distance filtering**: Only include nodes within N hops from root cause
3. **Edge weight filtering**: Filter based on edge criticality or latency
4. **Temporal filtering**: Include only nodes affected within a time window
5. **Interactive mode**: GUI for selecting root cause and viewing filtered graph
6. **Statistical analysis**: Compare filtered vs. full topology metrics
