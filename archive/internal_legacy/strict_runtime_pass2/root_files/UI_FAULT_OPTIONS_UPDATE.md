# UI Fault Options Update

**Date:** 2025-12-10
**File:** `viz/app.py`
**Status:** ✅ Complete

---

## Summary

Updated the Samba Telemetry Dashboard UI to:
1. **Remove deprecated faults** that were redundant
2. **Add new Tier 1 faults** with unique signatures
3. **Update node type filtering** for appropriate fault-component combinations

---

## Changes Made

### ✅ Removed Deprecated Faults

These faults are **no longer available** in the UI:

| Removed Fault | Reason | Replacement |
|---------------|--------|-------------|
| `slow_queries` | Redundant with `disk_io_saturation` | Use `disk_io_saturation` |
| `connection_exhaustion` | Redundant with `thread_exhaustion` | Use `thread_exhaustion` |
| `enable_background_job` | Redundant with `cpu_saturation` | Use `cpu_saturation` |

### ✅ Added New Tier 1 Faults

Three new faults now available in UI:

| New Fault | Description | Applicable Node Types |
|-----------|-------------|----------------------|
| **`memory_thrashing`** | Memory bursts → **bimodal latency** spikes | service, database |
| **`thread_exhaustion`** | Thread pool saturation → **queue buildup** | service, database, queue |
| **`disk_io_saturation`** | **HIGH latency, LOW CPU** → I/O bottleneck | service, database |

### ✅ Updated Node Type Filtering

Faults now show only for appropriate component types:

#### Tier 1: Core Resource Saturation

| Fault | Service | Database | Cache | Queue | External | Network |
|-------|---------|----------|-------|-------|----------|---------|
| `cpu_saturation` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `memory_pressure` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `memory_thrashing` 🆕 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `thread_exhaustion` 🆕 | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `disk_io_saturation` 🆕 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `memory_leak` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

#### Tier 2: Interaction Failures

| Fault | Service | Database | Cache | Queue | External | Network |
|-------|---------|----------|-------|-------|----------|---------|
| `inject_latency` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `inject_errors` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `cache_failure` | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `queue_consumer_slowdown` | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |

#### Structural/Distributed Faults

| Fault | Service | Database | Cache | Queue | External | Network |
|-------|---------|----------|-------|-------|----------|---------|
| `noisy_neighbor` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `hot_shard` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `force_deadlock` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `network_partition` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## Fault Durations Updated

Default durations adjusted based on how long each fault takes to manifest:

| Fault Type | Duration | Reason |
|------------|----------|--------|
| `cpu_saturation` | 5 min | Quick impact, consistent slowdown |
| `memory_pressure` | 5 min | Immediate allocation overhead |
| **`memory_thrashing`** 🆕 | 5 min | Periodic spikes visible quickly |
| **`thread_exhaustion`** 🆕 | 10 min | Queue buildup takes time to manifest |
| **`disk_io_saturation`** 🆕 | 10 min | I/O bottleneck impact accumulates |
| `memory_leak` | 5 min | Gradual but visible |
| `inject_latency` | 5 min | Immediate latency increase |
| `inject_errors` | 10 min | Error propagation and retries |
| `cache_failure` | 15 min | Cascading cache misses (thundering herd) |
| `queue_consumer_slowdown` | 15 min | Queue accumulation |
| `noisy_neighbor` | 15 min | CPU steal accumulation |
| `hot_shard` | 15 min | Traffic skew impact |
| `force_deadlock` | 15 min | Thread blocking and queue buildup |
| `network_partition` | 10 min | Isolation impact on retries |

---

## UI Behavior

### Before (Old System)
```
Node Type: database
Available Faults:
  ✓ slow_queries           [REDUNDANT]
  ✓ connection_exhaustion  [REDUNDANT]
  ✓ enable_background_job  [REDUNDANT]
```

### After (New System)
```
Node Type: database
Available Faults:
  ✓ cpu_saturation         [Tier 1: CPU contention]
  ✓ memory_pressure        [Tier 1: Sustained high memory]
  ✓ memory_thrashing       [Tier 1: Bimodal latency - NEW]
  ✓ thread_exhaustion      [Tier 1: Queue buildup - NEW]
  ✓ disk_io_saturation     [Tier 1: I/O bottleneck - NEW]
  ✓ memory_leak            [Progressive exhaustion]
  ✓ inject_latency         [Generic latency]
  ✓ inject_errors          [Generic errors]
  ✓ force_deadlock         [Thread blocking]
```

---

## Example: Fault Selection Logic

When user selects a node in the topology:

1. **Determine node role** (e.g., "database")
2. **Filter faults** using `VALID_FAULT_COMBINATIONS`
3. **Show only applicable faults** in dropdown
4. **Pre-fill duration** from `FAULT_DURATIONS`

```python
# Example: User clicks on database node
node_role = "database"

# Get valid faults for this role
valid_faults = VALID_ROLE_FAULTS[node_role]
# Returns: ['cpu_saturation', 'memory_pressure', 'memory_thrashing',
#           'thread_exhaustion', 'disk_io_saturation', 'memory_leak',
#           'inject_latency', 'inject_errors', 'force_deadlock']

# User selects 'disk_io_saturation'
selected_fault = 'disk_io_saturation'
default_duration = FAULT_DURATIONS[selected_fault]
# Returns: 600 seconds (10 minutes)
```

---

## Migration for Existing Scenarios

If you have saved scenarios or bookmarks using deprecated faults:

| Old Fault | New Fault | Action Required |
|-----------|-----------|-----------------|
| `slow_queries` on database | `disk_io_saturation` | **Update saved scenarios** |
| `connection_exhaustion` on database | `thread_exhaustion` | **Update saved scenarios** |
| `enable_background_job` on database | `cpu_saturation` | **Update saved scenarios** |

**Note:** The UI will not allow selecting deprecated faults. Users must migrate to new fault types.

---

## Testing

### Manual Testing Steps

1. **Start UI:**
   ```bash
   cd viz
   python app.py
   ```

2. **Test fault filtering:**
   - Select a **service node** → Should see all Tier 1 + structural faults
   - Select a **database node** → Should see Tier 1 faults + generic faults
   - Select a **cache node** → Should see cache_failure + generic faults
   - Select a **queue node** → Should see queue_consumer_slowdown + thread_exhaustion

3. **Test new faults:**
   - Select `memory_thrashing` → Duration should be 300s (5 min)
   - Select `thread_exhaustion` → Duration should be 600s (10 min)
   - Select `disk_io_saturation` → Duration should be 600s (10 min)

4. **Test deprecated faults removed:**
   - Verify `slow_queries` **not in dropdown** for database nodes
   - Verify `connection_exhaustion` **not in dropdown** for database nodes
   - Verify `enable_background_job` **not in dropdown** for database nodes

---

## Code References

**Updated in:** `viz/app.py`

- **Lines 94-122:** `VALID_FAULT_COMBINATIONS` dictionary
- **Lines 124-148:** `FAULT_DURATIONS` dictionary
- **Lines 150-156:** Auto-generated `VALID_ROLE_FAULTS` reverse mapping

**No changes needed in:**
- Dropdown rendering logic (automatically uses updated dictionaries)
- Fault application logic (handled by backend `modes.py`)

---

## Benefits

1. ✅ **Cleaner UI** - No redundant fault options
2. ✅ **Better UX** - Only show applicable faults for each node type
3. ✅ **Correct durations** - Realistic timeframes for fault manifestation
4. ✅ **Educational** - Comments explain what each fault does
5. ✅ **Type-safe** - Node type filtering prevents invalid combinations

---

## Summary Statistics

- **Removed:** 3 deprecated faults
- **Added:** 3 new Tier 1 faults
- **Net change:** 0 (same total, but better quality)
- **Node type mappings updated:** All faults now have correct node types
- **Duration tuning:** Adjusted for realistic fault manifestation times

---

**Status:** ✅ **UI Updated and Ready**

Users can now select from a clean, principled fault catalog with appropriate node type filtering!
