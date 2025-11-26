# Fault Propagation Analysis Enhancement Plan

## Executive Summary

This document outlines a comprehensive plan to enhance fault propagation analysis by adding concrete observational data, configuration context, and causal explanations. The current analysis provides statistical measures but lacks the concrete details needed to understand actual system behavior during faults.

## Current Analysis Gaps

Looking at `data_20251125_160435/ep_1/fault_propagation.json`, we identified these key issues:

### 1. Missing Actual Latency Data
- The analysis shows `db.query.latency: "Insufficient data"` (all null values)
- Service-to-DB `dependency.duration` metrics are also null
- **However**, the `traces.jsonl` file DOES contain actual latency in `attributes.duration.ms`
  - Example: DB queries show ~30-70ms durations in traces
  - This data is just not being extracted for analysis

### 2. No Concrete Numbers
- Current: "Mean increased by 19.2%" for CPU
- Missing: "DB CPU went from 7.6% to 9.0% (baseline) then spiked to 22.9% during fault"
- Missing: "Active connections went from 8.4 avg to peaks of 21-23"

### 3. No Configuration Context
- No visibility into:
  - DB connection pool capacity: 100 connections
  - Service connection pool size: 20 connections per pod
  - Retry configuration: 3 attempts, 200ms base delay, exponential backoff
  - Timeout settings: 5s for DB calls, 10s for external APIs

### 4. No Causal Explanations
- Current: "request rate decreased by 79.2%"
- Missing WHY: Connection pools filling up? Timeouts triggering? Retries amplifying load?

### 5. No Resource Saturation Context
- Missing: DB connections rejected (101 rejections at t=140s!)
- Missing: Service connection pool utilization
- Missing: Retry storm analysis (3x load amplification)

## Comprehensive Enhancement Plan

### Phase 1: Trace-Based Latency Analysis

**Goal**: Extract and analyze actual latency from traces to show concrete degradation

**Implementation**:
```python
# New module: analysis/trace_latency_analyzer.py
class TraceLatencyAnalyzer:
    def extract_latency_by_component(self, traces_file):
        """
        Extract actual latencies from traces, grouped by:
        - Component (db_0, svc_0, etc.)
        - Operation type (SQL SELECT, RPC call, etc.)
        - Time window (baseline vs fault periods)

        Returns:
            {
                "db_0": {
                    "baseline": {
                        "mean_ms": 35.2,
                        "p50_ms": 34.1,
                        "p95_ms": 62.4,
                        "p99_ms": 87.3,
                        "samples": 1250
                    },
                    "fault": {
                        "mean_ms": 245.8,  # 7x increase!
                        "p50_ms": 198.2,
                        "p95_ms": 892.1,
                        "p99_ms": 1250.4,
                        "samples": 342
                    },
                    "degradation_factor": 6.98
                },
                "svc_0->db_0": {
                    # End-to-end latency for service calling DB
                }
            }
        """
```

**Add to fault_propagation.json**:
```json
{
  "node_id": "db_0",
  "latency_analysis": {
    "source": "traces",
    "metric": "SQL SELECT duration",
    "baseline": {
      "mean_ms": 35.2,
      "p50_ms": 34.1,
      "p95_ms": 62.4,
      "sample_count": 1250,
      "time_window": "0s-120s"
    },
    "fault": {
      "mean_ms": 245.8,
      "p50_ms": 198.2,
      "p95_ms": 892.1,
      "sample_count": 342,
      "time_window": "120s-600s"
    },
    "impact": {
      "mean_increase_ms": 210.6,
      "degradation_factor": 6.98,
      "interpretation": "DB query latency increased 7x: from 35ms average to 246ms average"
    }
  }
}
```

### Phase 2: Configuration Context Injection

**Goal**: Capture and report relevant configuration that explains behavior

**Implementation**:
```python
# New module: analysis/config_extractor.py
class ConfigExtractor:
    def extract_resilience_config(self, topology, simulation_config):
        """
        Extract configuration affecting fault propagation:
        - Connection pools (DB, service-level)
        - Retry policies (max attempts, backoff)
        - Timeouts (DB, cache, external)
        - Circuit breaker thresholds

        Returns config context for each service/component
        """
        return {
            "db_0": {
                "connection_pool_capacity": 100,
                "cpu_cores": 4,
                "query_base_latency_ms": 20
            },
            "svc_0": {
                "db_connection_pool_capacity": 20,
                "retry_policy": {
                    "max_attempts": 3,
                    "base_delay_ms": 200,
                    "max_delay_ms": 5000,
                    "backoff_multiplier": 2.0
                },
                "timeouts": {
                    "database_call_ms": 5000,
                    "external_api_ms": 10000
                }
            }
        }
```

**Add to fault_propagation.json**:
```json
{
  "node_id": "svc_0",
  "configuration_context": {
    "connection_pool": {
      "capacity": 20,
      "observed_peak_utilization": 0.95,
      "observed_queue_depth": 15
    },
    "retry_policy": {
      "max_attempts": 3,
      "backoff": "exponential (200ms base, 2x multiplier)",
      "load_amplification_factor": 3.0
    },
    "timeouts": {
      "database_call_ms": 5000,
      "observed_timeout_rate": 0.12
    }
  }
}
```

### Phase 3: Causal Chain Analysis

**Goal**: Explain HOW and WHY impact propagated with mechanistic explanations

**Implementation**:
```python
# New module: analysis/causal_chain_analyzer.py
class CausalChainAnalyzer:
    def analyze_propagation_mechanism(self, node, metrics, traces, config):
        """
        For each impacted node, determine causal mechanism:

        1. Direct dependency latency (DB slow → service slow)
        2. Resource saturation (pool full → request queue)
        3. Retry amplification (1 req → 3 retries → 3x DB load)
        4. Timeout cascade (DB timeout → service timeout → gateway timeout)
        5. Backpressure (downstream slow → upstream queue builds)
        """

        # Example for svc_0:
        return {
            "primary_mechanism": "connection_pool_saturation",
            "causal_chain": [
                {
                    "step": 1,
                    "observation": "DB latency increased 7x (35ms → 246ms)",
                    "cause": "slow_queries fault injected at t=120s"
                },
                {
                    "step": 2,
                    "observation": "Service connection pool utilization spiked to 95%",
                    "cause": "Requests holding connections longer due to slow DB queries"
                },
                {
                    "step": 3,
                    "observation": "15 requests queued waiting for connections",
                    "cause": "All 20 pool connections in use, new requests must wait"
                },
                {
                    "step": 4,
                    "observation": "Retry storms: each failed request retried 3x",
                    "cause": "Some DB calls timeout (5s limit) triggering retries",
                    "impact": "DB load amplified 3x: 100 req/s → 300 req/s effective"
                },
                {
                    "step": 5,
                    "observation": "Request rate dropped 79% (218 → 45 req/s)",
                    "cause": "Backpressure: upstream services see timeouts/errors, circuit breakers open"
                }
            ],
            "root_cause_distance": 1,
            "propagation_delay_s": 0
        }
```

**Add to fault_propagation.json**:
```json
{
  "node_id": "svc_0",
  "causal_analysis": {
    "primary_mechanism": "connection_pool_saturation_with_retry_amplification",
    "why_impacted": "Direct dependency on db_0; slow DB queries caused connection pool to fill up, creating backpressure",
    "how_propagated": [
      {
        "metric": "db.query.latency",
        "change": "35ms → 246ms (7x increase)",
        "consequence": "Service connection pool holds connections 7x longer"
      },
      {
        "metric": "connection_pool.utilization",
        "change": "~40% → 95% (saturated)",
        "consequence": "New requests queue, latency increases linearly with queue depth"
      },
      {
        "metric": "retry_attempts",
        "estimated_amplification": "3x load on DB",
        "consequence": "Timeouts trigger retries (3 attempts), amplifying DB load 3x"
      },
      {
        "metric": "request_rate",
        "change": "218 → 45 req/s (79% drop)",
        "consequence": "Circuit breakers open, upstream services back off"
      }
    ]
  }
}
```

### Phase 4: Resource Saturation Analysis

**Goal**: Show which resources hit limits and how that drove behavior

**Implementation**:
```python
# Enhance existing analyzer with saturation detection
class ResourceSaturationAnalyzer:
    def detect_saturation_events(self, metrics):
        """
        Detect when resources hit capacity:
        - Connection pools > 90% utilization
        - CPU > 80%
        - Memory > 80%
        - Queue depths growing
        - Rejection counters incrementing
        """
        return {
            "db_0": {
                "saturation_events": [
                    {
                        "resource": "connection_pool",
                        "time_s": 140,
                        "utilization": 0.23,  # 23/100
                        "peak_utilization": 0.23,
                        "rejections": 101,
                        "impact": "101 connection attempts rejected, likely causing retries"
                    },
                    {
                        "resource": "cpu",
                        "time_s": 125,
                        "utilization_pct": 22.9,
                        "baseline_pct": 7.6,
                        "spike_factor": 3.0,
                        "impact": "CPU spike from background job or query load"
                    }
                ]
            }
        }
```

### Phase 5: Concrete Impact Summary

**Goal**: Lead with actual numbers, not just percentages

**Add summary section**:
```json
{
  "impact_summary": {
    "root_cause": {
      "component": "db_0",
      "fault": "slow_queries (wear_factor=0.5)",
      "observed_impact": {
        "latency": "DB query latency increased from 35ms to 246ms (7x degradation)",
        "cpu": "CPU utilization increased from 7.6% to peaks of 22.9% (3x spike)",
        "connections": "Active connections averaged 11, spiked to 23",
        "rejections": "101 connection rejections at t=140s"
      }
    },
    "propagation": {
      "svc_0": {
        "distance": 1,
        "mechanism": "connection_pool_saturation",
        "observed_impact": {
          "throughput": "Request rate dropped from 218 req/s to 45 req/s (79% reduction)",
          "connection_pool": "Utilization spiked to 95%, queue depth reached 15",
          "retry_amplification": "Estimated 3x load amplification from retries"
        }
      },
      "gateway": {
        "distance": 2,
        "mechanism": "cascading_timeout",
        "observed_impact": {
          "throughput": "Request rate dropped from 273 req/s to 36 req/s (87% reduction)",
          "end_user_impact": "User-facing requests declined dramatically"
        }
      }
    }
  }
}
```

## Implementation Roadmap

### Step 1: Enhance Data Collection (if needed)
- ✅ Traces already have duration data
- ✅ Metrics have connection pool stats
- ✅ Config is in simulation_config.yaml
- ⚠️ **Need to add**: Connection pool metrics to fault propagation input
- ⚠️ **Need to add**: Retry attempt counters

### Step 2: Create New Analyzer Modules
1. `analysis/trace_latency_analyzer.py` - Extract latencies from traces
2. `analysis/config_extractor.py` - Pull relevant config per component
3. `analysis/causal_chain_analyzer.py` - Build mechanistic explanations
4. `analysis/resource_saturation_detector.py` - Find saturation events

### Step 3: Enhance `analyze_fault_propagation.py`
Integrate new analyzers into the main pipeline:
```python
# After metric impact analysis
latency_analyzer = TraceLatencyAnalyzer()
latency_data = latency_analyzer.analyze(traces_file, fault_start_time)

config_extractor = ConfigExtractor()
config_context = config_extractor.extract(topology, simulation_config)

causal_analyzer = CausalChainAnalyzer()
causal_chains = causal_analyzer.analyze(node_reports, latency_data, config_context)

# Merge into node_reports
for node in node_reports:
    node['latency_analysis'] = latency_data.get(node['node_id'])
    node['configuration_context'] = config_context.get(node['node_id'])
    node['causal_analysis'] = causal_chains.get(node['node_id'])
```

### Step 4: Update Report Generation
Modify the report text to lead with concrete numbers:
```python
"DB query latency increased 7x: from 35ms average (baseline) to 246ms (fault period),
with p95 latency reaching 892ms. This caused svc_0's connection pool to saturate
(95% utilization, 15 requests queued), as each request held a connection 7x longer.
With retry policies configured for 3 attempts, this created ~3x load amplification
on the DB. Eventually circuit breakers opened and request rate dropped 79%."
```

## Expected Output Enhancement

**Before** (current):
```
"Mean decreased by 79.2%. Effect size: very_large (Cohen's d = 4.00)"
```

**After** (enhanced):
```
"Request throughput collapsed from 218 req/s (baseline) to 45 req/s (fault period)
- a 79% reduction.

ROOT CAUSE: DB slow queries increased latency 7x (35ms → 246ms), causing:
  1. Service connection pool saturation (40% → 95% utilization)
  2. Connection queue buildup (15 requests waiting for pool)
  3. Retry amplification (3 attempts × timeouts = 3x DB load)
  4. Cascading backpressure as circuit breakers opened

CONFIGURATION CONTEXT:
  - Service connection pool: 20 connections (hit 95% utilization)
  - Retry policy: 3 attempts, exponential backoff (200ms base)
  - DB timeout: 5000ms
  - DB rejections: 101 connections rejected at t=140s
```

## Benefits

This enhancement will transform the analysis from statistical summaries to actionable incident explanations:

1. **Concrete Observability**: See actual latencies, not just percentages
2. **Configuration Awareness**: Understand retry/timeout/pool settings that shaped behavior
3. **Causal Understanding**: Know WHY things happened, not just WHAT changed
4. **Resource Context**: See which resources saturated and when
5. **Actionable Insights**: Understand what config changes would prevent similar cascades

This provides the mechanistic understanding needed to truly explain fault propagation dynamics!
