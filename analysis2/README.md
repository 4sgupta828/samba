Here is a comprehensive `README.md` for your **Whitebox RCA Engine v3.0**.

It documents the architecture, the specific SOTA heuristics employed (like Guilt Ratio and Limp Mode), installation instructions, and how to structure the data.

-----

# Whitebox RCA Engine (SOTA v3.0)

A state-of-the-art **Whitebox Root Cause Analysis (RCA)** engine for cloud infrastructure topologies. This system automates the diagnosis of incidents by analyzing metrics, topology, and causal propagation patterns.

It combines **robust statistical rigor** (Changepoint detection, Mann-Whitney U) with **expert system heuristics** (Deadlock detection, Hub Bias correction) to distinguish true root causes from cascading symptoms.

## 🚀 Key Features

  * **Hub Bias Correction ("Guilt Ratio"):** Prevents central nodes (e.g., Databases, Gateways) from being unfairly blamed simply because many downstream services complain about them.
  * **"Limp Mode" Detection:** Identifies complex deadlock scenarios where a service has high latency but low resource usage (the "hung process" pattern).
  * **Traffic vs. Retry Disambiguation:** Distinguishes between legitimate traffic spikes (DDoS) and internal retry storms caused by downstream failures.
  * **Causal Narratives:** Generates a human-readable story explaining *why* a node was selected (e.g., *"Service A crashed -\> Queue B filled up -\> Service C slowed down"*).
  * **Robust Data Ingestion:** Handles outlier removal, metric normalization, and missing data gracefully using IQR-based cleaning.

## 📂 Project Structure

| File | Description |
| :--- | :--- |
| `run_rca_batch.py` | **Entry Point.** Batch processor that loads data, normalizes metrics, and runs the engine across multiple episode directories. |
| `run_batch_analysis.sh` | **Wrapper Script.** Runs analysis on nested batch directories (e.g., directories containing multiple `data_*` subdirectories). |
| `whitebox_rca.py` | **The Engine.** Orchestrates the 4-phase analysis process (Self-Health, Propagation, Ranking, Storytelling). |
| `statistical_utils.py` | **Math Core.** Implements Mann-Whitney U tests, Cohen's d effect size, and SOTA Changepoint Detection (PELT/BinSeg). |
| `self_health_analyzer.py` | **Internal Diagnostics.** Analyzes a node in isolation to detect Resource Saturation or Limp Mode deadlocks. |
| `disambiguator.py` | **Edge Analysis.** Resolves causality between two connected nodes (e.g., "Did Caller overload Callee, or is Callee just slow?"). |
| `causal_chain_analyzer.py` | **Storyteller.** Traces the graph from the root cause to the symptoms to generate the causal narrative. |
| `config_extractor.py` | **Context.** Provides resource limits (e.g., max threads, memory caps) so the engine understands what "saturation" looks like. |

## 🛠️ Installation

Requires Python 3.8+. Install dependencies via pip:

```bash
pip install numpy pandas networkx scipy ruptures
```

*Note: `ruptures` is required for SOTA changepoint detection. If not installed, the system falls back to simple thresholding.*

## 🏃 Usage

### 1\. Data Organization

The engine expects a directory containing subdirectories for each incident ("episode"). Each episode folder must contain:

  * `metrics.jsonl`: Time-series data (JSON Lines format).
  * `topology.json`: Graph structure of the system.
  * `label.json`: Ground truth metadata (for validation).

**Directory Structure:**

```text
data/
├── ep_01/
│   ├── metrics.jsonl
│   ├── topology.json
│   └── label.json
├── ep_02/
│   └── ...
```

### 2\. Running the Analysis

#### Option A: Single Data Directory

Run the batch processor on a single data directory containing `ep_*` subdirectories:

```bash
python3 run_rca_batch.py ./data/my_data_dir [top_k]
```

The optional `top_k` parameter (default: 5) specifies how many top candidates to consider.

#### Option B: Nested Batch Structure

The script automatically handles nested structures (directories containing multiple `data_*` subdirectories):

```bash
python3 run_rca_batch.py ../data/batch_run 5
```

Or use the wrapper script:

```bash
./run_batch_analysis.sh ../data/batch_run 5
```

#### Key Features:

- **Smart Processing**: Automatically skips already-processed episodes (detects `RCAInvestigated.marker` and `RCAFailed.marker` files)
- **Reprocess Mode**: Use `--reprocess` flag to clear all markers and outputs and re-run analysis
- **Progress Tracking**: Shows `[N/Total]` progress as it processes episodes
- **JSON Output**: Saves detailed results to `rca_analysis.json` in each episode directory
- **Marker Files**: Creates `RCAInvestigated.marker` when ground truth is found in top-K
- **Error Handling**: Creates `RCAFailed.marker` on errors and continues processing other episodes
- **Comprehensive Summary**: Shows success rates, error counts, and overall statistics

#### Reprocessing Episodes:

To clear all markers and outputs and re-run analysis from scratch:

```bash
python3 run_rca_batch.py ../data/batch_run 5 --reprocess
```

Or with the wrapper script:

```bash
./run_batch_analysis.sh ../data/batch_run 5 --reprocess
```

This will:
- Remove all `RCAInvestigated.marker` files
- Remove all `RCAFailed.marker` files
- Remove all `rca_analysis.json` files
- Re-run analysis on all episodes

### 3\. Example Output

```text
================================================================================
BATCH WHITEBOX RCA ANALYSIS
================================================================================
Base directory: ../data/batch_run
Top-K candidates: 5
================================================================================

Found 18 episodes
  Already investigated: 17
  Already failed: 0
  To process: 1

[1/1]
================================================================================
Processing: ../data/batch_run/data_20251212_135507/ep_0
================================================================================

  Ground Truth: tenant_service
  Top Result:   pod_tenant_service_3 (Score: 51.2)
  ✅ IN TOP-5 (Rank 1/5)

  📜 Causal Narrative:
    🔴 ROOT CAUSE: pod_tenant_service_3
       Internal Symptoms: memory_usage increased (d=3.08)
    ⬇️ Propagation:
       - node_3 calls pod_tenant_service_3 (Potential cascading latency)

================================================================================
BATCH WHITEBOX RCA SUMMARY
================================================================================
Total episodes found: 18
  Already investigated: 17
  Already failed: 0
  Processed this run: 1

Results for 1 processed episodes:
  ✅ Success (found in top-5): 1 (100.0%)
  ❌ Not in top-5: 0 (0.0%)
  ⚠️  No anomalies: 0 (0.0%)
  🔥 Errors: 0 (0.0%)
================================================================================

Overall success rate: 18/18 (100.0%)
```

## 🧠 How It Works

The engine operates in **4 Phases**:

### Phase 1: Self-Health Analysis

Every node is analyzed in isolation to detect internal degradation.

  * **Resource Saturation:** Checks if CPU/Memory/Threads exceed limits defined in `config_extractor.py`.
  * **Limp Mode:** Detects if Latency is CRITICAL (\>0.8 effect size) while Resource Usage is LOW (\<0.2), indicating a deadlock.

### Phase 2: Graph Propagation (Edge Disambiguation)

Every connection (Edge) is analyzed to determine the direction of blame.

  * **Traffic Spike:** If `Caller RPS` increases significantly, the Caller is blamed.
  * **Retry Storm:** If `Caller RPS` AND `Caller Errors` increase, it's treated as a retry storm (Callee fault).
  * **Callee Fault:** If `Caller RPS` is stable but `Latency` increases, the Callee is blamed.

### Phase 3: Global Ranking (Hub Bias Correction)

Nodes are ranked based on a composite score:
$$\text{Score} = (\text{Guilt Ratio} \times 100) + (\text{Self Score} \times 5) + \log(\text{Traffic})$$

  * **Guilt Ratio:** The percentage of upstream clients blaming this node. This prevents central DBs from being blamed unless a *majority* of their clients are having issues.

### Phase 4: Story Generation

The `CausalChainAnalyzer` walks the topology graph starting from the top candidate, identifying downstream victims to construct a human-readable narrative of the incident.

## 📊 Data Formats

### `metrics.jsonl`

Standard JSON logs containing metric samples.

```json
{"timestamp": 162000, "name": "container.cpu.utilization", "value": 45.2, "labels": {"component.id": "frontend"}}
{"timestamp": 162005, "name": "service.latency", "value": 0.23, "labels": {"component.id": "frontend"}}
```

### `topology.json`

NetworkX-compatible adjacency list.

```json
{
  "nodes": [{"id": "frontend", "type": "Service"}, {"id": "db", "type": "Database"}],
  "edges": [{"source": "frontend", "target": "db"}]
}
```

### `label.json`

Used for validation in batch runs.

```json
{
  "fault_start_time": 162500,
  "root_cause_node": "db"
}
```