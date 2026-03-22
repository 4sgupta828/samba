# Viz UI Fixes - Summary

## Issues Fixed

### 1. ✅ Metrics Not Loading for Clicked Nodes

**Problem**: When clicking on nodes in the topology, the component drill-down showed no metrics.

**Root Cause**: The component_drilldown.py was looking for generic metric names like `container.cpu.utilization`, `http.server.request.duration`, etc., but the actual metrics in the data have component-specific names like `service.svc_0.requests`, `service.svc_0.duration`, etc.

**Solution**:
- Updated all drilldown functions in `charts/component_drilldown.py` to:
  - Query available metrics for each component first
  - Check if expected metrics exist before trying to display them
  - Show a helpful message with available metrics if none match
  - Use the actual metric naming convention from the data

**Files Modified**:
- `viz/charts/component_drilldown.py` - Updated all component-specific drilldown functions

### 2. ✅ Topology Broken Without Compute Agents

**Problem**: When filtering out ComputeAgent nodes, the topology became disconnected with 16 isolated components (islands). Services, caches, databases, and message queues appeared as disconnected nodes.

**Root Cause**: The physical topology has edges structured as:
- `service -> compute_agent` (uses_compute)
- `compute_agent -> database/cache` (uses_database/uses_cache)

When ComputeAgents are filtered out, all these connections are lost, breaking the topology.

**Solution**:
- Created a `build_logical_topology()` function in `data_loader.py` that:
  - Removes ComputeAgent nodes
  - Creates direct edges from services to their dependencies (databases, caches) by traversing through compute agents
  - Preserves all node attributes
- Updated `load_episode()` to return both physical and logical topologies
- Modified `app.py` to use the logical topology for all visualizations

**Files Modified**:
- `viz/data_loader.py` - Added `build_logical_topology()` function
- `viz/app.py` - Updated all callbacks to use `logical_topology_graph`

**Result**: The UI now shows a clean logical topology without ComputeAgent nodes by default, with direct service-to-resource connections.

### 3. ✅ Dark Theme Applied

**Problem**: The UI used a bright white theme that didn't match the control UI in `~/sim/src/control_ui`.

**Solution**:
- Created `static/css/dark_theme.css` with dark color scheme matching the control UI:
  - Background colors: `#1f2937`, `#111827`, `#374151`
  - Text colors: `#f9fafb`, `#d1d5db`
  - Accent color: `#3b82f6` (blue)
- Updated all chart modules to use dark backgrounds:
  - `charts/topology.py` - Dark background for network graph
  - `charts/component_drilldown.py` - Dark backgrounds for metric charts
- Configured Flask to serve static CSS files
- Added dark theme to Dash app's external_stylesheets

**Files Modified**:
- `viz/static/css/dark_theme.css` - New dark theme CSS
- `viz/app.py` - Added static file serving and dark theme stylesheet
- `viz/charts/topology.py` - Updated chart styling
- `viz/charts/component_drilldown.py` - Updated chart styling

## Known Issues (Data-Level Problems)

### Issue A: MessageQueue Nodes Completely Isolated

**Problem**: Message queue nodes (`queue_0`, `queue_1`) have NO incoming or outgoing edges in the topology.

**Root Cause**: The `infra_context.json` file contains no relationships involving message queues. They exist as nodes but are not connected to any other components.

**Impact**: Message queues appear as isolated nodes in the topology, even without any filters applied.

**Recommendation**: This is a **data generation issue** that needs to be fixed in the Dataraft training data generator. Message queues should have edges connecting them to the services that publish to or consume from them.

**Verification**:
```bash
cd viz
python test_topology.py
# Shows: "WARNING: queue_0 is completely isolated!"
```

### Issue B: Topology Still Disconnected (Even in Logical View)

**Problem**: Even with the logical topology (ComputeAgents removed), the topology has 16 separate connected components.

**Root Cause**: The infrastructure context lacks service-to-service edges. Each service is only connected to its local resources (databases, caches), but there are no edges representing service-to-service calls.

**Current Structure**:
```
Component 1: [db_0, svc_0]
Component 2: [svc_1]  (completely isolated)
Component 3: [cache_2, svc_2]
Component 4: [svc_3]  (completely isolated)
... (16 total components)
```

**Expected Structure** (for a connected system):
```
gateway -> svc_X -> svc_Y -> database
        -> svc_Z -> cache
        -> external_service
```

**Recommendation**: This is also a **data generation issue**. The training data should include:
1. Gateway-to-service edges (showing which services the gateway calls)
2. Service-to-service edges (showing the call graph)
3. Service-to-external-service edges
4. Service-to-message-queue edges (publish/subscribe relationships)

**Impact**: While the UI now shows a cleaner view, the underlying topology is fundamentally disconnected, which weakens graph-based analysis (RCA, propagation views) since the structure doesn't represent actual system communication patterns.

## Testing

To verify the fixes work:

1. **Start the dashboard**:
   ```bash
   cd viz
   python app.py
   ```

2. **Open browser**: http://localhost:8050

3. **Test metrics loading**:
   - Load any episode (e.g., ep_0)
   - Click on a service node (blue circle, e.g., `svc_0`)
   - Verify the drill-down shows charts with actual data

4. **Test topology**:
   - Verify no ComputeAgent nodes are shown by default
   - Check that services are connected to their databases/caches
   - Note: Some nodes may still appear isolated (this is expected given the data issues documented above)

5. **Test dark theme**:
   - Verify the UI has a dark background
   - Check that all text is readable
   - Confirm charts have dark backgrounds

## Recommendations for Data Generation Team

1. **Add Service Communication Edges**: Include edges representing actual service-to-service calls in the `relationships` array of `infra_context.json`

2. **Connect Message Queues**: Add edges showing which services publish to and consume from message queues

3. **Connect Gateway**: Add edges from the RequestGateway to the frontend services it routes to

4. **Validate Topology**: Add a validation step in the data generator to ensure:
   - All nodes (except isolated external services) are reachable from the gateway
   - Message queues have at least one producer and one consumer
   - The topology forms a connected graph

Example of what should be added to relationships:
```json
{
  "source": "gateway",
  "target": "svc_6",
  "type": "routes_to"
},
{
  "source": "svc_6",
  "target": "queue_0",
  "type": "publishes_to"
},
{
  "source": "queue_0",
  "target": "svc_7",
  "type": "consumed_by"
}
```

## Files Changed

```
viz/
├── app.py (modified - logical topology, dark theme)
├── data_loader.py (modified - added build_logical_topology)
├── charts/
│   ├── topology.py (modified - dark theme)
│   └── component_drilldown.py (modified - actual metric names, dark theme)
└── static/
    └── css/
        └── dark_theme.css (new - dark theme styling)
```

## Summary

All UI-level issues have been fixed:
- ✅ Metrics now load correctly when clicking nodes
- ✅ Topology shows logical view without compute agents
- ✅ Dark theme matches control UI

Two data-level issues remain (documented above) that require fixes in the training data generator:
- ⚠️ Message queues are not connected to any services
- ⚠️ No service-to-service communication edges exist
