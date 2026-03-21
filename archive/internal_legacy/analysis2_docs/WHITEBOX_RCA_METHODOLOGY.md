# Whitebox RCA 3.0 Methodology

## 1. Overview
The Whitebox RCA engine is a deterministic, physics-based Root Cause Analysis system designed for microservices. Unlike correlation-based ML models, it uses causal reasoning, resource saturation physics, and topology constraints to identify the root cause of incidents. It distinguishes between **Primary Symptoms** (the cause) and **Secondary Symptoms** (the effect) to pinpoint the origin of failure.

## 2. Core Architecture
The system operates in a pipeline:
1.  **Data Ingestion**: Loads metrics, topology, and traces.
2.  **Self-Health Analysis**: Determines the intrinsic health of every node.
3.  **Causal Reasoning**: Propagates faults through the topology to calculate "Physics Coverage".
4.  **Supplemental Evidence**: Layers on temporal, trace, and log evidence.
5.  **Scoring & Ranking**: Aggregates signals into a final score.

## 3. Key Components

### 3.1 Self-Health Analyzer (`self_health_analyzer.py`)
Analyzes individual nodes to determine their health state.
*   **Primary Metrics (The Smoking Gun)**: Resource saturation (CPU, Memory, Threads), Deadlocks, Queue Faults.
*   **Secondary Metrics (The Smoke)**: Latency spikes, Error rate increases.
*   **Queue Analysis**: Uses rate imbalance to distinguish real queue faults (Primary) from normal buffering (Secondary).
*   **Blackbox Inference**: For external dependencies (DBs, APIs) without internal metrics, infers health from caller consensus.

### 3.2 Causal Graph Reasoner (`causal_graph_reasoner.py`)
The "Physics Engine" that validates fault propagation.
*   **Forward Propagation**: Traces impact from root to callers (Latency, Error Bubbling, Capacity Reduction).
*   **Reverse Propagation**: Traces impact from consumer to dependencies (Queue Backup, Reduced Write Throughput).
*   **Noisy Neighbor Detection**: Identifies co-located pods suffering from resource contention.
*   **Physics Coverage**: Calculates a score (0-1) representing the fraction of symptomatic nodes explained by a candidate.

### 3.3 Whitebox RCA Engine (`whitebox_rca.py`)
The orchestrator that integrates all signals.
*   **Pod-Level Forensics**: Aggregates pod metrics to service level but retains outlier/hot-shard patterns.
*   **Network Partition Detection**: Identifies global or link-level network failures.
*   **Scoring**: Combines health, physics, and supplemental scores.

### 3.4 Supplemental Analyzers
*   **Temporal Analyzer (`temporal_analyzer.py`)**: Uses changepoint detection to find the "First to Break" node.
*   **Trace Analyzer (`trace_analyzer.py`)**: Calculates `Self-Time` vs `Total-Time` to authoritatively attribute latency.
*   **Time Window Selector (`time_window_selector.py`)**: Auto-detects stable baseline periods for accurate comparison.

## 4. Scoring Model
Candidates are ranked by a composite score (0-200+):

| Component | Max Score | Description |
|-----------|-----------|-------------|
| **Base Health** | 50 | Severity of internal degradation (Primary > Secondary). |
| **Physics Coverage** | 80 | Explanatory power (Blast Radius). |
| **Semantic Bonus** | 40 | Bonus for Primary symptoms (Cause) vs Secondary (Effect). |
| **Trace Evidence** | 35 | Bonus for authoritative self-time degradation. |
| **Temporal Evidence** | 15 | Bonus for being the first node to degrade. |
| **Log Evidence** | 20 | Bonus for error logs. |

## 5. Fault Detection Capabilities
The system is tuned to detect:
*   **Resource Saturation**: CPU/Memory/Thread exhaustion.
*   **Interaction Faults**: Latency injection, Error spikes.
*   **Structural Faults**: Network partitions, Noisy neighbors, Hot shards.
*   **Application Faults**: Memory leaks, Deadlocks, Infinite loops.
*   **Infrastructure Faults**: Disk I/O saturation, Node failures.

## 6. Configuration
Thresholds and limits are configurable via `rca_config.py` and `config_extractor.py`, allowing adaptation to different environments (e.g., strict vs relaxed latency thresholds).