"""
run_rca_batch.py

Batch processor for Whitebox RCA 3.0.
Handles robust data ingestion, normalization, and outlier removal.
Connects raw JSONL data to the SOTA statistical engine.
"""

import sys
import json
import numpy as np
import pandas as pd
import networkx as nx
from pathlib import Path
from typing import Dict, Tuple, List, Any

# Import the SOTA Engine
from whitebox_rca import WhiteboxRCAEngine

# ==========================================
# 1. CONFIGURATION & MAPPING
# ==========================================

# Maps raw metric names (from simulation) to Engine Signals
# This allows the engine to be agnostic of specific metric naming conventions.
METRIC_MAP = {
    # Resource Signals (Internal Health)
    'container.cpu.utilization': 'cpu_usage',
    'pod.cpu.utilization': 'cpu_usage',
    'process.cpu.usage': 'cpu_usage',
    'container.memory.usage_mb': 'memory_usage',
    'pod.memory.usage': 'memory_usage',
    'jvm.memory.used': 'memory_usage',
    'thread_pool.threads.active': 'thread_pool_active',
    'thread_pool.queue.depth': 'thread_pool_queue',
    
    # Golden Signals (Self Health)
    'service.latency': 'avg_latency',
    'service.duration': 'avg_latency', 
    'service.response_time': 'avg_latency',
    'service.errors': 'internal_error_rate',
    'service.error_rate': 'internal_error_rate',
    'service.requests': 'inbound_rps',
    'service.request_rate': 'inbound_rps',
    'service.throughput': 'inbound_rps',
    
    # Edge Signals (Client-side view of dependencies)
    'client.latency': 'dependency_latency',
    'dependency.latency': 'dependency_latency',
    'client.duration': 'dependency_latency',
    'client.errors': 'dependency_error_rate',
    'dependency.error_rate': 'dependency_error_rate',
    'client.requests': 'outbound_rps',
    'dependency.request_rate': 'outbound_rps'
}

def remove_outliers_iqr(data: np.ndarray) -> np.ndarray:
    """
    Robust outlier removal using Interquartile Range (IQR).
    Prevents short, massive spikes (transients) from skewing mean/std calculations.
    """
    if len(data) < 10: return data
    
    # Remove NaNs first
    clean_data = data[~np.isnan(data)]
    if len(clean_data) < 10: return clean_data

    q1 = np.percentile(clean_data, 25)
    q3 = np.percentile(clean_data, 75)
    iqr = q3 - q1
    
    # Use loose bounds (3.0 * IQR) to keep real signals but remove extreme garbage
    lower = q1 - 3.0 * iqr
    upper = q3 + 3.0 * iqr
    
    return clean_data[(clean_data >= lower) & (clean_data <= upper)]

# ==========================================
# 2. DATA ADAPTER (The Bridge)
# ==========================================

class DatasetAdapter:
    """
    Converts raw simulation output (metrics.jsonl, topology.json) 
    into the clean Numpy-based dictionary format required by WhiteboxRCAEngine.
    """
    
    def __init__(self, episode_dir: Path):
        self.episode_dir = episode_dir
        
        # Load static files
        self.label = self._load_json('label.json')
        self.topology = self._load_topology()
        
        # Load and prep metrics
        self.metrics_df = self._load_metrics()

    def _load_json(self, filename: str) -> Dict:
        path = self.episode_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {filename}")
        with open(path) as f:
            return json.load(f)

    def _load_topology(self) -> nx.DiGraph:
        """Parses topology.json into a NetworkX DiGraph with node metadata."""
        data = self._load_json('topology.json')
        G = nx.DiGraph()
        
        for node in data.get('nodes', []):
            # Store type (Service, Pod, DB) for the SelfHealthAnalyzer
            G.add_node(node['id'], type=node.get('type', 'Service'))
            
        for edge in data.get('edges', []):
            G.add_edge(edge['source'], edge['target'])
            
        return G

    def _load_metrics(self) -> pd.DataFrame:
        """Reads metrics.jsonl and normalizes timestamps/IDs."""
        metrics_path = self.episode_dir / 'metrics.jsonl'
        if not metrics_path.exists():
            raise FileNotFoundError("Missing metrics.jsonl")
            
        # Read JSONL into DataFrame
        try:
            df = pd.read_json(metrics_path, lines=True)
        except ValueError:
            print("  [!] Warning: Empty or malformed metrics.jsonl")
            return pd.DataFrame()
        
        if df.empty:
            return df

        # 1. Normalize Component ID
        # Extract from 'labels' dictionary column
        def extract_id(row):
            labels = row.get('labels', {})
            if not isinstance(labels, dict): return None
            return (
                labels.get('component.id') or 
                labels.get('pod_name') or 
                labels.get('service_name') or
                labels.get('node_id')
            )
            
        df['component_id'] = df.apply(extract_id, axis=1)
        
        # 2. Normalize Timestamp
        # Prefer 'sim.time' in labels, fallback to top-level 'timestamp'
        def extract_time(row):
            labels = row.get('labels', {})
            if isinstance(labels, dict) and 'sim.time' in labels:
                return float(labels['sim.time'])
            if 'timestamp' in row:
                return float(row['timestamp'])
            return 0.0

        df['sim_time'] = df.apply(extract_time, axis=1)
        
        # Filter out rows without ID or Time
        df = df.dropna(subset=['component_id', 'sim_time'])
        return df

    def get_data_windows(self) -> Tuple[Dict, Dict]:
        """
        Splits metrics into Baseline (Pre-Fault) and Current (Post-Fault).
        Returns two dictionaries: {node_id: {signal_name: np.array}}
        """
        if self.metrics_df.empty:
            return {}, {}

        fault_start = self.label.get('fault_start_time', 0)
        
        # Split DataFrame based on time
        base_df = self.metrics_df[self.metrics_df['sim_time'] < fault_start]
        curr_df = self.metrics_df[self.metrics_df['sim_time'] >= fault_start]
        
        # Process into dictionaries
        baseline_data = self._process_window(base_df)
        current_data = self._process_window(curr_df)
        
        return baseline_data, current_data

    def _process_window(self, df: pd.DataFrame) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Pivots DataFrame: Group by Node -> Group by Metric -> Extract Values.
        """
        data = {}
        
        # 1. Group by Node
        for node_id, node_group in df.groupby('component_id'):
            # Optimization: Only process nodes present in topology
            # (Skips irrelevant system metrics or ephemeral pods not in graph)
            if node_id not in self.topology.nodes:
                continue 
                
            node_metrics = {}
            
            # 2. Group by Metric Name
            for raw_metric_name, metric_rows in node_group.groupby('name'):
                
                # 3. Map to Standard Signal Name
                # Check if raw name contains any key from METRIC_MAP
                signal_name = None
                for key, mapped_name in METRIC_MAP.items():
                    if key in raw_metric_name:
                        signal_name = mapped_name
                        break
                
                if not signal_name:
                    continue # Skip metrics we don't know how to use
                
                # 4. Extract Values (Handle simple floats vs summary dicts)
                values_list = []
                for _, row in metric_rows.iterrows():
                    val = row.get('value')
                    
                    # Handle Summary/Histogram metrics (e.g. latency p99)
                    if val is None and 'summary' in row and isinstance(row['summary'], dict):
                        # For latency, prefer P99 (tail latency)
                        # For others, use Mean or Max
                        summary = row['summary']
                        if 'latency' in signal_name:
                            val = summary.get('p99', summary.get('p95', summary.get('mean')))
                        else:
                            val = summary.get('mean', summary.get('max'))
                    
                    if val is not None:
                        try:
                            values_list.append(float(val))
                        except (ValueError, TypeError):
                            pass

                if not values_list:
                    continue

                # Convert to numpy array
                values_array = np.array(values_list, dtype=float)
                
                # 5. Clean Outliers (SOTA Preprocessing)
                clean_values = remove_outliers_iqr(values_array)
                
                # Store (if we already have this signal, append/merge? No, overwrite is usually fine for batch)
                # Ideally we merge if multiple raw metrics map to same signal, but simple overwrite works for MVP
                node_metrics[signal_name] = clean_values
            
            if node_metrics:
                data[node_id] = node_metrics
            
        return data

# ==========================================
# 3. BATCH RUNNER LOGIC
# ==========================================

def process_episode(episode_dir: Path):
    print(f"\nAnalyzing Episode: {episode_dir.name}")
    
    try:
        # 1. Load Data
        adapter = DatasetAdapter(episode_dir)
        baseline, current = adapter.get_data_windows()
        
        ground_truth_node = adapter.label.get('root_cause_node')
        
        # 2. Run Engine
        # Pass the parsed topology and extracted config (limits) if available
        engine = WhiteboxRCAEngine(adapter.topology)
        
        results = engine.analyze_incident(baseline, current)
        
        if not results:
            print("  [!] No anomalies detected.")
            return False

        # 3. Validate Results
        top_candidate = results[0]['node']
        top_score = results[0]['score']
        top_story = results[0].get('story', [])
        
        # Validation: Is Ground Truth in Top 3?
        top_3 = [r['node'] for r in results[:3]]
        
        is_exact = (top_candidate == ground_truth_node)
        is_top3 = (ground_truth_node in top_3)
        
        # 4. Print Report
        print(f"  Ground Truth: {ground_truth_node}")
        print(f"  Top Result:   {top_candidate} (Score: {top_score:.1f})")
        
        if is_exact:
            print("  ✅ EXACT MATCH")
        elif is_top3:
            print(f"  ⚠️  IN TOP 3 (Rank: {top_3.index(ground_truth_node) + 1})")
        else:
            print(f"  ❌ FAIL (Top 3: {top_3})")
            
        # Print the Generated Story (Explanation)
        if top_story:
            print("\n  📜 Causal Narrative:")
            for line in top_story:
                print(f"    {line}")
                
        return is_top3 # Return success if in top 3

    except Exception as e:
        print(f"  [!] Error processing episode: {e}")
        # Uncomment for debugging:
        # import traceback
        # traceback.print_exc()
        return False

def find_all_episodes(base_dir: str) -> List[Path]:
    """Finds all subdirectories starting with 'ep_'."""
    path = Path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {base_dir}")
    return sorted([p for p in path.iterdir() if p.is_dir() and p.name.startswith('ep_')])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_rca_batch.py <data_directory>")
        sys.exit(1)
        
    data_dir = sys.argv[1]
    episodes = find_all_episodes(data_dir)
    
    print(f"Found {len(episodes)} episodes in {data_dir}")
    print("="*60)
    
    success_count = 0
    total_processed = 0
    
    for ep in episodes:
        total_processed += 1
        if process_episode(ep):
            success_count += 1
            
    print("\n" + "="*60)
    print(f"BATCH SUMMARY")
    print("="*60)
    print(f"Total Processed: {total_processed}")
    print(f"Success (Top-3): {success_count}")
    if total_processed > 0:
        print(f"Accuracy:        {(success_count/total_processed)*100:.1f}%")