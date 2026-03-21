# Quick Start: Topology Filtering

## 1-Minute Setup

### Generate Filtered Topologies

```bash
# Option 1: Auto-generate for all episodes (recommended)
./generate_filtered_topologies.sh

# Option 2: Generate for specific data run
./generate_filtered_topologies.sh data/data_20251121_185526

# Option 3: Generate for single episode
python filter_topology_by_root_cause.py data/data_20251121_185526/ep_0
```

### View in UI

```bash
# Start the dashboard
python viz/app.py

# Then in the browser:
# 1. Select a data run
# 2. Select an episode
# 3. Click "Load Episode"
# 4. Toggle "Filter by Root Cause" ✓
```

## What You'll See

### Before (Full Topology)
```
Showing full topology (25 nodes)
```
- All services, databases, caches, queues shown
- Can be cluttered for large systems

### After (Filtered Topology)
```
Showing 14 nodes reachable from root cause (11 nodes hidden)
```
- Only nodes affected by root cause
- Cleaner, focused view
- Same interactivity (click nodes for details)

## Example Output

```bash
$ ./generate_filtered_topologies.sh

==========================================
Filtered Topology Generator
==========================================

Found 1 data run(s)

Processing: data_20251121_185526
  ✓ ep_0: Generated filtered topology
  ✓ ep_1: Generated filtered topology

==========================================
Summary
==========================================
Total episodes: 2
Filtered topologies: 2

✓ All episodes have filtered topologies!

You can now use the 'Filter by Root Cause' toggle in the UI
to view filtered topologies.
```

## Common Scenarios

### Scenario 1: External API Failure
**Root Cause**: `ext_0` (external service)

**Full Topology**: 25 nodes
- 14 services, 4 databases, 3 caches, 2 queues, 1 external, 1 gateway

**Filtered Topology**: 14 nodes
- Only services calling ext_0 and their upstreams
- **Removed**: 11 nodes (44% reduction)

**Why**: Services not calling ext_0 cannot be affected

### Scenario 2: Database Failure
**Root Cause**: `db_0` (database)

**Full Topology**: 10 nodes
- 5 services, 2 databases, 1 cache, 1 queue, 1 gateway

**Filtered Topology**: 8 nodes
- Services using db_0 and gateway
- **Removed**: 2 nodes (20% reduction)

**Why**: Services using other databases unaffected

## Commands Cheat Sheet

```bash
# Generate all
./generate_filtered_topologies.sh

# Single episode
python filter_topology_by_root_cause.py <episode_dir>

# Batch process data run
python batch_filter_topologies.py <data_run_dir>

# Specify custom root cause
python filter_topology_by_root_cause.py <episode_dir> --root-cause svc_5

# Quiet mode (no output)
python filter_topology_by_root_cause.py <episode_dir> --quiet

# Custom output path
python filter_topology_by_root_cause.py <episode_dir> -o custom.json

# Test integration
python test_filtered_topology_integration.py

# Start dashboard
python viz/app.py
```

## Troubleshooting

### Toggle is Disabled
**Problem**: "Filter by Root Cause (not generated)"
**Solution**: Run `./generate_filtered_topologies.sh`

### No Filtering Effect
**Problem**: All nodes still visible
**Solution**: Root cause may be highly connected (gateway/frontend)

### Script Errors
**Problem**: "Root cause node not found"
**Solution**: Check `label.json` has `root_cause_node` field

## Integration with Existing Workflow

```bash
# Standard workflow
python generate_dataset.py -n 10              # Generate episodes
./generate_filtered_topologies.sh             # Generate filtered topologies
python viz/app.py                             # Visualize

# In UI:
# - Toggle "Filter by Root Cause" to focus analysis
# - Click nodes to see component details
# - Compare full vs filtered views
```

## File Locations

```
data/data_20251121_185526/
└── ep_0/
    ├── topology.json           ← Original (always present)
    ├── topology_filtered.json  ← Filtered (generated on-demand)
    ├── label.json              ← Contains root_cause_node
    └── metrics.jsonl
```

## Performance

- **Generation**: ~50ms per episode
- **UI Toggle**: Instant (<10ms)
- **Batch Processing**: ~2-5 seconds for 100 episodes

## Next Steps

- Read [TOPOLOGY_FILTERING.md](TOPOLOGY_FILTERING.md) for detailed documentation
- Check [README.md](README.md) for full Samba features
- Try toggling between views in the UI to compare

## Support

For issues or questions:
1. Check [TOPOLOGY_FILTERING.md](TOPOLOGY_FILTERING.md) troubleshooting section
2. Run test script: `python test_filtered_topology_integration.py`
3. Verify files exist: `ls data/*/ep_*/topology*.json`
