"""
run_rca_batch.py

Batch processor for Whitebox RCA 2.0.
1. Iterates over episode directories (like batch_rca_discovery.py).
2. Adapts 'metrics.jsonl' and 'topology.json' into the Whitebox Engine format.
3. Runs the analysis and compares result against 'label.json' (Ground Truth).
"""

import sys
import json
import numpy as np
import pandas as pd
import networkx as nx
from pathlib import Path
from typing import Dict, Tuple, List, Any

# Import the Whitebox Engine (Ensure these files are in the same directory)
from whitebox_rca import WhiteboxRCAEngine

# ==========================================
# 1. DATA ADAPTER (The Bridge)
# ==========================================
class DatasetAdapter:
    """
    Converts your simulation output (JSONL/Pandas) into the 
    numpy-based dictionary format required by WhiteboxRCAEngine.
    """
    
    # Mapping from your simulation metric names to Engine signals
    METRIC_MAP = {
        # Resource Signals
        'container.cpu.utilization': 'cpu_usage',
        'pod.cpu.utilization': 'cpu_usage',
        'container.memory.usage_mb': 'memory_usage',
        'pod.memory.usage': 'memory_usage',
        'thread_pool.threads.active': 'thread_pool_active',
        
        # Golden Signals (Self)
        'service.latency': 'avg_latency',
        'service.duration': 'avg_latency', # Often p50/p99 summary
        'service.errors': 'internal_error_rate',
        'service.requests': 'inbound_rps',
        'service.request_rate': 'inbound_rps',
        
        # Edge Signals (Client-side view)
        'client.latency': 'dependency_latency',
        'client.errors': 'dependency_error_rate',
        'client.requests': 'outbound_rps'
    }

    def __init__(self, episode_dir: Path):
        self.episode_dir = episode_dir
        self.topology = self._load_topology()
        self.label = self._load_label()
        self.metrics_df = self._load_metrics()

    def _load_topology(self) -> nx.DiGraph:
        topo_path = self.episode_dir / 'topology.json'
        with open(topo_path) as f:
            data = json.load(f)
        
        G = nx.DiGraph()
        for node in data.get('nodes', []):
            G.add_node(node['id'], type=node.get('type', 'Service'))
            
        for edge in data.get('edges', []):
            G.add_edge(edge['source'], edge['target'])
        return G

    def _load_label(self) -> Dict:
        label_path = self.episode_dir / 'label.json'
        with open(label_path) as f:
            return json.load(f)

    def _load_metrics(self) -> pd.DataFrame:
        metrics_path = self.episode_dir / 'metrics.jsonl'
        # Read JSONL into DataFrame
        df = pd.read_json(metrics_path, lines=True)
        
        # Flatten 'labels' column (extract component.id)
        if 'labels' in df.columns:
            # Extract component.id safely
            def get_comp_id(x):
                return x.get('component.id') or x.get('pod_name') or x.get('service_name')
            
            df['component_id'] = df['labels'].apply(get_comp_id)
            # Extract timestamp if not top-level
            if 'sim.time' not in df.columns and 'timestamp' in df.columns:
                df['sim.time'] = df['timestamp']
            elif 'sim.time' not in df.columns:
                 # Fallback: try to get from labels
                 df['sim.time'] = df['labels'].apply(lambda x: x.get('sim.time', 0))
        
        return df

    def get_data_windows(self) -> Tuple[Dict, Dict]:
        """
        Splits metrics into Baseline and Current based on fault_start_time.
        Returns: (baseline_data, current_data)
        """
        fault_start = self.label.get('fault_start_time', 0)
        
        # Split DataFrame
        base_df = self.metrics_df[self.metrics_df['sim.time'] < fault_start]
        curr_df = self.metrics_df[self.metrics_df['sim.time'] >= fault_start]
        
        baseline_data = self._process_window(base_df)
        current_data = self._process_window(curr_df)
        
        return baseline_data, current_data

    def _process_window(self, df: pd.DataFrame) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Transforms DataFrame rows into the Engine's expected format:
        Dict[node_id, Dict[signal_name, numpy_array]]
        """
        data = {}
        
        # Group by Node
        for node_id, node_group in df.groupby('component_id'):
            if node_id not in self.topology.nodes:
                continue # Skip metrics for nodes not in topology (e.g. unknown pods)
                
            node_metrics = {}
            
            # Group by Metric Name
            for metric_name, metric_rows in node_group.groupby('name'):
                # Map raw metric name to Engine Signal (e.g., 'pod.cpu' -> 'cpu_usage')
                signal_name = self._map_metric_name(metric_name)
                if not signal_name:
                    continue
                
                # Extract numeric values
                if 'value' in metric_rows.columns:
                    # Simple scalar metrics
                    values = metric_rows['value'].to_numpy(dtype=float)
                elif 'summary' in metric_rows.columns:
                    # Histogram/Summary metrics (extract p99 or count)
                    # This depends on your specific JSON structure for summaries
                    values = metric_rows['summary'].apply(
                        lambda x: x.get('p99') if isinstance(x, dict) else x
                    ).to_numpy(dtype=float)
                else:
                    continue
                    
                node_metrics[signal_name] = values
            
            data[node_id] = node_metrics
            
        return data

    def _map_metric_name(self, raw_name: str) -> str:
        """Partial match mapping for metric names."""
        for key, signal in self.METRIC_MAP.items():
            if key in raw_name:
                return signal
        return None

# ==========================================
# 2. BATCH RUNNER
# ==========================================
def process_episode(episode_dir: Path):
    print(f"\nAnalyzing Episode: {episode_dir.name}")
    
    try:
        # 1. Load and Adapt Data
        adapter = DatasetAdapter(episode_dir)
        baseline, current = adapter.get_data_windows()
        ground_truth_node = adapter.label.get('root_cause_node')
        
        # 2. Run Engine
        engine = WhiteboxRCAEngine(adapter.topology)
        results = engine.analyze_incident(baseline, current)
        
        if not results:
            print("  [!] No anomalies detected.")
            return False

        # 3. Validate
        top_candidate = results[0]['node']
        top_score = results[0]['score']
        
        # Check if Ground Truth is in Top 3
        top_3 = [r['node'] for r in results[:3]]
        found_in_top_3 = ground_truth_node in top_3
        
        print(f"  Ground Truth: {ground_truth_node}")
        print(f"  Top Candidate: {top_candidate} (Score: {top_score:.1f})")
        print(f"  Top 3: {top_3}")
        
        if top_candidate == ground_truth_node:
            print("  ✅ EXACT MATCH")
            return True
        elif found_in_top_3:
            print("  ⚠️  IN TOP 3")
            return True # Consider top-3 a success for now
        else:
            print("  ❌ FAIL")
            # Print reason for failure (Top candidate details)
            print(f"     Why {top_candidate}? {results[0]['symptoms']}")
            return False

    except Exception as e:
        print(f"  [!] Error processing episode: {e}")
        # import traceback
        # traceback.print_exc()
        return False

def find_all_episodes(base_dir: str) -> List[Path]:
    path = Path(base_dir)
    return sorted(list(path.glob('ep_*')))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_rca_batch.py <data_directory>")
        sys.exit(1)
        
    data_dir = sys.argv[1]
    episodes = find_all_episodes(data_dir)
    
    print(f"Found {len(episodes)} episodes in {data_dir}")
    
    success_count = 0
    total = 0
    
    for ep in episodes:
        total += 1
        if process_episode(ep):
            success_count += 1
            
    print("\n" + "="*40)
    print(f"BATCH SUMMARY")
    print("="*40)
    print(f"Total Processed: {total}")
    print(f"Success (Top-3): {success_count}")
    print(f"Accuracy:        {(success_count/total)*100:.1f}%")