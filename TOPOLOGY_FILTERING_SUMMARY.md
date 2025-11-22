# Topology Filtering Feature - Summary

## What Was Built

A complete topology filtering system that allows users to view only the nodes that can be affected by a root cause, integrated with the Samba Telemetry Dashboard.

## Components Created

### 1. Core Filtering Scripts

#### `filter_topology_by_root_cause.py`
- Single-episode topology filtering
- Uses reverse graph traversal (BFS) to find reachable nodes
- Generates `topology_filtered.json` with metadata
- Command-line tool with various options

**Usage**:
```bash
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0
```

#### `batch_filter_topologies.py`
- Batch processing for multiple episodes
- Processes entire dataset directories
- Progress tracking and error handling

**Usage**:
```bash
python batch_filter_topologies.py data/data_20251121_185526
```

#### `generate_filtered_topologies.sh`
- User-friendly shell script wrapper
- Auto-detects data runs and episodes
- Provides summary statistics

**Usage**:
```bash
./generate_filtered_topologies.sh
```

### 2. UI Integration

#### Updated Files:
- `viz/data_loader.py`: Added filtered topology loading support
- `viz/app.py`: Added toggle and callback for filtered view

#### Features:
- Toggle switch: "Filter by Root Cause" in topology card header
- Automatic detection of filtered topology availability
- Status message showing node reduction
- Works seamlessly with existing type filters
- Instant toggle between full and filtered views

### 3. Documentation

#### `TOPOLOGY_FILTERING.md`
- Comprehensive documentation (350+ lines)
- Usage examples
- Integration guides
- Use cases and patterns

#### Updated `README.md`
- Added quick-start section for topology filtering
- Links to detailed documentation

### 4. Testing

#### `test_filtered_topology_integration.py`
- Validates data loader integration
- Tests filtered topology availability
- Verifies metadata completeness

## How It Works

### Algorithm

1. **Build Reverse Graph**: Create adjacency list where edges point from dependencies to dependents
   - Original: `A -> B` (A calls B)
   - Reversed: `B -> A` (if B fails, A is affected)

2. **BFS Traversal**: Find all nodes reachable from root cause in reverse graph

3. **Filter Topology**: Keep only reachable nodes and their interconnecting edges

4. **Add Metadata**: Include statistics about filtering (nodes removed, edges removed)

### Example

```
Original: 25 nodes, 47 edges
Root Cause: ext_0 (external service)

Filtered: 14 nodes, 22 edges
Removed: 11 nodes (44%), 25 edges (53%)

Reachable nodes: [ext_0, svc_3, svc_4, svc_7, svc_13, svc_1, svc_2,
                  svc_6, svc_0, svc_12, svc_9, gateway, queue_0, queue_1]
```

## UI Workflow

1. **Generate** (one-time):
   ```bash
   ./generate_filtered_topologies.sh
   ```

2. **Start Dashboard**:
   ```bash
   python viz/app.py
   ```

3. **View Filtered Topology**:
   - Load an episode
   - Toggle "Filter by Root Cause"
   - See only affected nodes

## Use Cases

### 1. Focused Analysis
Remove noise by hiding unaffected components

### 2. Impact Scope Understanding
Quickly identify which services are at risk

### 3. Training Data Reduction
Generate focused feature sets for ML models

### 4. Visualization Simplification
Cleaner topology graphs for large systems

## Files Generated

For each episode with filtered topology:

```
data/data_20251121_185526/ep_0/
├── topology.json                # Original (25 nodes)
├── topology_filtered.json       # Filtered (14 nodes)
├── label.json
├── metrics.jsonl
└── ...
```

### Filtered Topology Format

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

## Performance

- **Time Complexity**: O(V + E) - Linear in graph size
- **Space Complexity**: O(V) - Stores reachable set
- **Typical Performance**: <100ms for graphs with 100 nodes

## Testing Results

```
Testing Filtered Topology Integration
============================================================
✓ Found 1 data run(s)
✓ Using data run: data_20251121_185526
✓ Found 2 episode(s)

--- Testing ep_0 ---
✓ Loaded episode data
✓ Filtered topology available: True
  Original nodes: 25
  Filtered nodes: 14
  Reduction: 11 nodes (44.0%)
  ✓ Filter metadata present
  ✓ Filtered graph has nodes

--- Testing ep_1 ---
✓ Loaded episode data
✓ Filtered topology available: True
  Original nodes: 10
  Filtered nodes: 8
  Reduction: 2 nodes (20.0%)
  ✓ Filter metadata present
  ✓ Filtered graph has nodes

============================================================
✓ All tests passed!
```

## Key Benefits

1. **On-Demand**: Generate filtered topologies only when needed
2. **Non-Destructive**: Original topology preserved
3. **Metadata-Rich**: Includes filtering statistics
4. **UI-Integrated**: Seamless toggle in dashboard
5. **Flexible**: Works with any topology size
6. **Fast**: Sub-second performance

## Future Enhancements

Potential improvements documented in TOPOLOGY_FILTERING.md:

1. Multi-root-cause support
2. Distance-based filtering (N-hop neighborhood)
3. Edge weight/criticality filtering
4. Temporal filtering (time-window based)
5. Interactive graph exploration mode
6. Statistical comparison of filtered vs. full topology

## Commands Reference

```bash
# Filter single episode
python filter_topology_by_root_cause.py <episode_dir>

# Batch filter all episodes in a data run
python batch_filter_topologies.py <data_run_dir>

# Auto-discover and filter all data runs
./generate_filtered_topologies.sh

# Test integration
python test_filtered_topology_integration.py

# Start dashboard with filtering support
python viz/app.py
```

## Documentation

- [TOPOLOGY_FILTERING.md](TOPOLOGY_FILTERING.md) - Full documentation
- [README.md](README.md) - Quick start guide

## Summary

This feature provides a powerful way to focus analysis on components that matter, reducing cognitive load when analyzing large microservice architectures. The integration with the UI makes it accessible and easy to use, while the command-line tools provide flexibility for batch processing and automation.
