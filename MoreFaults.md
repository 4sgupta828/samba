Here is the detailed technical specification for implementing **Structural Pathologies** (Noisy Neighbor, Hot Shard, Network Partition, Deadlock). This moves the simulation from "parameter tuning" to "structural interaction."

-----

# Technical Spec: Structural Failure Modes Implementation

## 1\. Noisy Neighbor (Infrastructure Contention)

**Goal:** Simulate resource contention where a "victim" pod degrades because an "aggressor" pod on the same node saturates shared resources.

### A. `src/components/compute_node.py`

**Requirement:** The Node must calculate a "contention penalty" based on total utilization of all pods it hosts.

**Changes:**

1.  **Add `contention_config`:** In `__init__`, define thresholds (e.g., CPU \> 90%, Memory \> 95%).
2.  **Implement `get_contention_penalty()`:**
      * Calculate `total_cpu_util` = sum(pod.cpu) / node.capacity.
      * If `total_cpu_util < 0.9`: Return 0.
      * If `total_cpu_util >= 0.9`: Calculate **Steal Time**.
      * *Formula:* `penalty_ms = base_penalty * exp((util - 0.9) * sensitivity)`
      * *Example:* At 95% util, add 50ms. At 99% util, add 500ms.

### B. `src/components/pod.py`

**Requirement:** The Pod must check its Node status on every request and pay the "Steal Time" tax.

**Changes:**

1.  **Update `_handle_request_internal`:**
      * Inside the `with self.thread_pool.request()` block:
      * Call `self.compute_node.get_contention_penalty()`.
      * If `penalty > 0`:
          * Log `DEBUG`: "CPU Steal Time: {penalty}ms".
          * `yield self.env.timeout(penalty / 1000.0)`.
      * *Note:* This adds latency *without* doing useful work, simulating OS scheduler waiting.

### C. `src/failures/modes.py`

**New Fault:** `noisy_neighbor`

  * **Target:** A specific `Pod` (the aggressor).
  * **Mechanism:**
      * Set `pod.dynamics.fault_cpu_floor_percent = 100.0` (Pin the CPU).
      * This raises the Node's total utilization.
      * Other pods on the same node (victims) automatically start seeing positive values from `get_contention_penalty()`.

-----

## 2\. Hot Shard (Data Skew)

**Goal:** Break the assumption of uniform load balancing. One pod receives disproportionate traffic, causing it to fail while peers remain healthy.

### A. `src/components/service.py`

**Requirement:** Support weighted routing logic.

**Changes:**

1.  **Add State:** `self.traffic_weights = {}` (Map of pod\_id -\> weight).
2.  **Update `get_pod_target()`:**
      * Default behavior: `random.choice(healthy_pods)`.
      * **New Logic:**
          * If `self.traffic_weights` is set:
          * Filter `healthy_pods`.
          * Normalize weights for available pods.
          * Use `random.choices(population=pods, weights=..., k=1)` to select target.

### B. `src/failures/modes.py`

**New Fault:** `hot_shard`

  * **Target:** A `Service`.
  * **Params:** `target_pod_index` (int), `skew_factor` (float, e.g., 0.8 for 80%).
  * **Mechanism:**
      * Identify the specific pod from `service.pods`.
      * Update `service.traffic_weights`: Set target pod to `skew_factor`, distribute remaining `1.0 - skew_factor` among others.
      * *Revert:* Reset `service.traffic_weights` to empty/uniform.

-----

## 3\. Network Partition (Topological Cut)

**Goal:** Simulate network segmentation. Requests fail instantly or timeout depending on TCP retry configuration, but the service itself remains "healthy" (green on dashboard).

### A. `src/components/network.py`

**Requirement:** A central registry of "broken links."

**Changes:**

1.  **Add State:** `self.partition_rules = set()` (Set of `(source_id, target_id)` tuples).
2.  **Update `transmit()` / `_transmit_internal()`:**
      * Add argument `source_id`. (Needs to be passed down from Pod/Service).
      * Before calculating latency:
          * Check `if (source_id, target_id) in self.partition_rules`.
          * If True: `raise NetworkPartitionError("Connection timed out")`.

### B. `src/failures/modes.py`

**New Fault:** `network_partition`

  * **Target:** `NetworkLink` (or the `RequestGateway` representing the network).
  * **Params:** `source_component_id`, `target_component_id`, `bidirectional` (bool).
  * **Mechanism:**
      * Add tuple `(source, target)` to `network_layer.partition_rules`.
      * If bidirectional, add `(target, source)` too.
      * *Revert:* Remove tuples.

-----

## 4\. Logical Deadlock (The "Zombie")

**Goal:** Consume threads without consuming CPU, simulating a lock wait or circular dependency.

### A. `src/failures/modes.py`

**New Fault:** `force_deadlock`

  * **Target:** `Pod`.
  * **Params:** `locked_threads` (int, default=all), `duration` (float).
  * **Mechanism:**
      * Define an internal process `_zombie_task(pod, duration)`:
        ```python
        with pod.thread_pool.request() as req:
            yield req  # Acquire thread
            # Do NOT consume CPU (no dynamics update)
            # Just sleep
            yield pod.env.timeout(duration)
        ```
      * Spawn `locked_threads` count of these processes using `pod.env.process()`.
      * **Result:** `thread_pool.count` goes to max. `cpu_utilization` stays low. New requests queue up and time out.

-----

## 5\. Integration: GNN Training Signal

To ensure the GNN learns from these, the **Label Generation** (`label.json`) in `generate_dataset.py` must capture the *nature* of the fault, not just the location.

**Update `ScenarioEventTracker`:**
Ensure these new modes record specific metadata:

  * **Noisy Neighbor:** Record `shared_node_id`. GNN must learn `Node(A) == Node(B)`.
  * **Partition:** Record `source` and `destination`. GNN must learn "Link Failure" vs "Node Failure."

### Summary Checklist for Coding Agent

1.  **`ComputeNode`**: Implement `get_contention_penalty` math.
2.  **`Pod`**: Call contention penalty in request path.
3.  **`Service`**: Implement weighted routing in `get_pod_target`.
4.  **`NetworkLink`**: Implement partition table lookup.
5.  **`modes.py`**: Add functions: `noisy_neighbor`, `hot_shard`, `network_partition`, `force_deadlock`.
6.  **`simulation_config.py`**: Add default configs for contention sensitivity.