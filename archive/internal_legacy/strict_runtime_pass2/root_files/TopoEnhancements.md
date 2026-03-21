
  1. Directed Arrows on Topology Edges

  - Added arrow annotations to all edges in the topology visualization
  - Arrows clearly show caller→callee and producer→consumer relationships
  - Async edges (queues) are shown with dashed purple lines with arrows
  - Sync edges are shown with solid gray lines with arrows
  - Each arrow is positioned at 80% along the edge to avoid overlap with nodes
  - Hover text shows the direction and edge type (e.g., "svc_0 → db_0 | Type: sync_db")

  2. Healthy Node Detection Algorithm

  Created a new module viz/health_analyzer.py that:
  - Analyzes metrics before and after fault injection
  - Detects nodes showing no significant degradation (healthy) vs impacted nodes
  - Uses a 15% threshold for metric changes (latency p99, p90, p50, error rates)
  - Returns health scores for each node (0.0 = root cause, 0.3 = impacted, 1.0 = healthy)
  - Provides detailed analysis with reasons for classification

  Test results from your data:
  - Root cause: ext_0 (External Service)
  - Impacted nodes: 3 (gateway, ext_0, svc_6)
  - Healthy nodes: 22 (showing no impact from the fault)

  3. UI Toggle for Hiding Healthy Nodes

  - Added a new toggle switch: "Hide Healthy Nodes" (green) in the topology card header
  - Located next to the existing "Filter by Root Cause" toggle
  - When enabled, hides all healthy nodes from the visualization
  - Root cause is always visible regardless of filters
  - Info text shows: "Healthy: X, Impacted: Y (Z healthy nodes hidden)"

  4. Enhanced Visualization Features

  - Edge colors distinguish async (purple) vs sync (gray) operations
  - Hover text on edges shows source→target and edge type
  - All node filtering works together: type filters + healthy node filter + root cause filter
  - 47 arrow annotations added automatically for the 47 edges in your test topology

  📊 How to Use

  1. Start the dashboard:
  cd viz && python app.py
  1. Then open http://localhost:8050
  2. View directed arrows:
    - Arrows automatically show on all edges
    - Look for purple dashed arrows for async queues (producer→consumer)
    - Gray solid arrows for sync calls (caller→callee)
  3. Toggle healthy nodes:
    - Enable "Hide Healthy Nodes" to focus only on impacted components
    - Useful for root cause analysis by removing noise from unaffected nodes
    - Combine with "Filter by Root Cause" for maximum focus

  🎯 Benefits

  - Clearer understanding of data flow direction (upstream/downstream)
  - Reduced visual clutter by hiding unaffected nodes
  - Faster root cause analysis by focusing on impacted components only
  - Better queue understanding with producer→consumer arrows

  All changes have been tested and verified successfully!