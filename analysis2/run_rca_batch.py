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
            # Store all node attributes (type, parent_service, role, etc.)
            node_attrs = {
                'type': node.get('type', 'Service'),
                'parent_service': node.get('parent_service'),
                'role': node.get('role'),
                'service_name': node.get('service_name')
            }
            G.add_node(node['id'], **node_attrs)

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
                
                # Store (overwrite if duplicates map to same signal)
                node_metrics[signal_name] = clean_values
            
            if node_metrics:
                data[node_id] = node_metrics
            
        return data

# ==========================================
# 3. BATCH RUNNER LOGIC
# ==========================================

def is_episode_processed(episode_dir: Path) -> Tuple[bool, str]:
    """
    Check if episode has already been processed.

    Returns:
        (is_processed, status) where status is 'investigated', 'failed', or 'not_processed'
    """
    if (episode_dir / 'RCAInvestigated.marker').exists():
        return True, 'investigated'
    elif (episode_dir / 'RCAFailed.marker').exists():
        return True, 'failed'
    else:
        return False, 'not_processed'

def create_marker_file(episode_dir: Path, marker_type: str, data: Dict = None):
    """Create a marker file to indicate processing status."""
    marker_file = episode_dir / f'RCA{marker_type}.marker'
    with open(marker_file, 'w') as f:
        if data:
            json.dump(data, f, indent=2)
        else:
            f.write(f"Analysis completed: {marker_type}\n")

def aggregate_to_service_level(results: List[Dict], topology: nx.DiGraph) -> List[Dict]:
    """
    Aggregate pod-level results to service-level for comparison with ground truth.

    Args:
        results: List of pod/node-level results
        topology: NetworkX topology graph with node metadata

    Returns:
        List of service-level aggregated results
    """
    from collections import defaultdict

    # Group results by parent service
    service_groups = defaultdict(lambda: {
        'pods': [],
        'total_score': 0.0,
        'max_score': 0.0,
        'symptoms': set(),
        'blamed_by': set(),
        'stories': []
    })

    for result in results:
        node_id = result['node']
        node_data = topology.nodes.get(node_id, {})

        # Get parent service (for pods) or use node itself (for services)
        parent_service = node_data.get('parent_service', node_id)

        # Aggregate data
        group = service_groups[parent_service]
        group['pods'].append(node_id)
        group['total_score'] += result['score']
        group['max_score'] = max(group['max_score'], result['score'])
        group['symptoms'].update(result.get('symptoms', []))
        group['blamed_by'].update(result.get('blamed_by', []))
        if result.get('story'):
            group['stories'].append((node_id, result['story']))

    # Convert to result format
    service_results = []
    for service_name, group in service_groups.items():
        # Use average score across pods, weighted by max
        avg_score = group['total_score'] / len(group['pods'])
        final_score = (avg_score + group['max_score']) / 2  # Blend average and max

        service_results.append({
            'node': service_name,
            'score': round(final_score, 2),
            'pod_count': len(group['pods']),
            'affected_pods': group['pods'],
            'symptoms': list(group['symptoms']),
            'blamed_by': list(group['blamed_by']),
            'story': group['stories'][0][1] if group['stories'] else []  # Use first pod's story
        })

    # Sort by score descending
    return sorted(service_results, key=lambda x: x['score'], reverse=True)

def process_episode(episode_dir: Path, top_k: int = 5) -> Dict:
    """
    Process a single episode with error handling and marker creation.

    Args:
        episode_dir: Path to episode directory
        top_k: Number of top candidates to check

    Returns:
        Dictionary with processing results
    """
    import traceback

    try:
        print(f"\n{'='*80}")
        print(f"Processing: {episode_dir}")
        print(f"{'='*80}")

        # 1. Load Data
        adapter = DatasetAdapter(episode_dir)
        baseline, current = adapter.get_data_windows()

        ground_truth_node = adapter.label.get('root_cause_node')

        # 2. Run Engine
        engine = WhiteboxRCAEngine(adapter.topology)
        pod_results = engine.analyze_incident(baseline, current)

        # 3. Aggregate to service level
        results = aggregate_to_service_level(pod_results, adapter.topology)

        if not results:
            print("  ❌ No anomalies detected.")
            error_info = {'error': 'No anomalies detected', 'error_type': 'NoAnomalies'}
            create_marker_file(episode_dir, 'Failed', error_info)
            return {
                'episode': str(episode_dir),
                'status': 'no_anomalies',
                'ground_truth': ground_truth_node
            }

        # 4. Validate Results
        top_candidate = results[0]['node']
        top_score = results[0]['score']
        affected_pods = results[0].get('affected_pods', [])
        top_story = results[0].get('story', [])

        # Check if ground truth in top-K
        top_k_nodes = [r['node'] for r in results[:top_k]]
        is_in_top_k = ground_truth_node in top_k_nodes

        if is_in_top_k:
            rank = top_k_nodes.index(ground_truth_node) + 1
        else:
            rank = None

        # 5. Print Report
        print(f"\n  Ground Truth: {ground_truth_node}")
        print(f"  Top Result:   {top_candidate} (Score: {top_score:.1f})")
        if affected_pods:
            print(f"     Affected pods: {', '.join(affected_pods[:3])}{'...' if len(affected_pods) > 3 else ''}")

        if rank == 1:
            print(f"  ✅ EXACT MATCH (Rank 1/{top_k})")
        elif is_in_top_k:
            print(f"  ✅ IN TOP-{top_k} (Rank {rank}/{top_k})")
        else:
            print(f"  ❌ NOT IN TOP-{top_k}")
            print(f"     Top {min(3, len(top_k_nodes))}: {top_k_nodes[:3]}")

        # Print the Generated Story (Explanation)
        if top_story:
            print("\n  📜 Causal Narrative:")
            for line in top_story:
                print(f"    {line}")

        # 6. Save results to JSON file
        output_data = {
            'ground_truth': ground_truth_node,
            'top_k': top_k,
            'found_in_top_k': is_in_top_k,
            'rank': rank,
            'service_level_candidates': results[:top_k],
            'pod_level_candidates': pod_results[:top_k * 3] if pod_results else [],  # Save more pod details
            'total_service_candidates': len(results),
            'total_pod_candidates': len(pod_results) if pod_results else 0
        }

        output_file = episode_dir / 'rca_analysis.json'
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        # 7. Create marker file
        if is_in_top_k:
            create_marker_file(episode_dir, 'Investigated', {'rank': rank, 'top_k': top_k})
            status = 'success'
        else:
            status = 'not_in_top_k'

        return {
            'episode': str(episode_dir),
            'status': status,
            'ground_truth': ground_truth_node,
            'top_result': top_candidate,
            'rank': rank,
            'in_top_k': is_in_top_k
        }

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        tb = traceback.format_exc()

        print(f"\n  ❌ ERROR processing {episode_dir.name}: {error_msg}")
        print(f"     Error type: {error_type}")

        # Create failure marker
        error_info = {
            'error': error_msg,
            'error_type': error_type,
            'traceback': tb
        }
        create_marker_file(episode_dir, 'Failed', error_info)

        return {
            'episode': str(episode_dir),
            'status': 'error',
            'error': error_msg,
            'error_type': error_type
        }

def find_all_episodes(base_dir: str) -> List[Path]:
    """
    Find all episode directories in the base directory.

    Args:
        base_dir: Base directory to search (supports nested structure)

    Returns:
        List of episode directory paths
    """
    path = Path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {base_dir}")

    episodes = []

    # Check if this is a single dataset directory (has ep_* directly)
    direct_episodes = list(path.glob('ep_*'))
    if direct_episodes:
        for ep_dir in direct_episodes:
            if ep_dir.is_dir():
                # Verify it has required files
                if (ep_dir / 'label.json').exists() and \
                   (ep_dir / 'topology.json').exists() and \
                   (ep_dir / 'metrics.jsonl').exists():
                    episodes.append(ep_dir)
    else:
        # This is a batch directory containing multiple datasets
        for dataset_dir in path.iterdir():
            if dataset_dir.is_dir():
                for ep_dir in dataset_dir.glob('ep_*'):
                    if ep_dir.is_dir():
                        # Verify it has required files
                        if (ep_dir / 'label.json').exists() and \
                           (ep_dir / 'topology.json').exists() and \
                           (ep_dir / 'metrics.jsonl').exists():
                            episodes.append(ep_dir)

    return sorted(episodes)

def print_summary(results: List[Dict], skipped: Dict[str, int], top_k: int):
    """Print summary of batch processing."""
    total_processed = len(results)
    success_count = sum(1 for r in results if r['status'] == 'success')
    not_in_top_k_count = sum(1 for r in results if r['status'] == 'not_in_top_k')
    no_anomaly_count = sum(1 for r in results if r['status'] == 'no_anomalies')
    error_count = sum(1 for r in results if r['status'] == 'error')

    print(f"\n{'='*80}")
    print("BATCH WHITEBOX RCA SUMMARY")
    print(f"{'='*80}")
    print(f"Total episodes found: {total_processed + skipped['investigated'] + skipped['failed']}")
    print(f"  Already investigated: {skipped['investigated']}")
    print(f"  Already failed: {skipped['failed']}")
    print(f"  Processed this run: {total_processed}")
    print()
    print(f"Results for {total_processed} processed episodes:")
    print(f"  ✅ Success (found in top-{top_k}): {success_count} ({success_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ❌ Not in top-{top_k}: {not_in_top_k_count} ({not_in_top_k_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ⚠️  No anomalies: {no_anomaly_count} ({no_anomaly_count/max(1,total_processed)*100:.1f}%)")
    print(f"  🔥 Errors: {error_count} ({error_count/max(1,total_processed)*100:.1f}%)")
    print(f"{'='*80}")

    # Show success rate including previously investigated
    total_investigated = success_count + skipped['investigated']
    total_attempted = total_processed + skipped['investigated'] + skipped['failed']
    if total_attempted > 0:
        print(f"\nOverall success rate: {total_investigated}/{total_attempted} ({total_investigated/total_attempted*100:.1f}%)")

    # Show errors if any
    if error_count > 0:
        print(f"\nEpisodes with errors:")
        for r in results:
            if r['status'] == 'error':
                print(f"  - {Path(r['episode']).name}: {r['error_type']}")

def clear_episode_markers_and_output(episode_dir: Path):
    """Remove marker files and analysis output from an episode directory."""
    files_to_remove = [
        'RCAInvestigated.marker',
        'RCAFailed.marker',
        'rca_analysis.json'
    ]

    removed = []
    for filename in files_to_remove:
        filepath = episode_dir / filename
        if filepath.exists():
            filepath.unlink()
            removed.append(filename)

    return removed

if __name__ == "__main__":
    # Configuration
    top_k = 5  # Check top-5 candidates by default
    reprocess = False

    if len(sys.argv) < 2:
        print("Usage: python run_rca_batch.py <data_directory> [top_k] [--reprocess]")
        print("Example: python run_rca_batch.py ../data/batch_run 5")
        print("         python run_rca_batch.py ../data/batch_run 5 --reprocess")
        print()
        print("Options:")
        print("  --reprocess    Clear all marker files and analysis outputs before running")
        sys.exit(1)

    data_dir = sys.argv[1]

    # Parse arguments
    for arg in sys.argv[2:]:
        if arg == '--reprocess':
            reprocess = True
        else:
            try:
                top_k = int(arg)
            except ValueError:
                print(f"Warning: Invalid argument '{arg}', ignoring")

    print(f"{'='*80}")
    print("BATCH WHITEBOX RCA ANALYSIS")
    print(f"{'='*80}")
    print(f"Base directory: {data_dir}")
    print(f"Top-K candidates: {top_k}")
    if reprocess:
        print(f"Mode: REPROCESS (clearing old markers and outputs)")
    print(f"{'='*80}\n")

    # Find all episodes
    try:
        episodes = find_all_episodes(data_dir)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    if not episodes:
        print(f"No episodes found in {data_dir}")
        sys.exit(0)

    print(f"Found {len(episodes)} episodes")

    # Reprocess mode: clear all markers and outputs
    if reprocess:
        print("\n🔄 Clearing old markers and outputs...")
        total_cleared = 0
        for ep in episodes:
            removed = clear_episode_markers_and_output(ep)
            if removed:
                total_cleared += 1
        print(f"   Cleared {total_cleared} episode(s)")
        print()

    # Check which episodes are already processed
    skipped = {'investigated': 0, 'failed': 0}
    to_process = []

    for ep in episodes:
        is_processed, status = is_episode_processed(ep)
        if is_processed:
            if status == 'investigated':
                skipped['investigated'] += 1
            else:
                skipped['failed'] += 1
        else:
            to_process.append(ep)

    print(f"  Already investigated: {skipped['investigated']}")
    print(f"  Already failed: {skipped['failed']}")
    print(f"  To process: {len(to_process)}")

    if not to_process:
        print("\n✅ All episodes already processed!")
        sys.exit(0)

    # Process episodes
    results = []
    for i, episode_dir in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] ", end='')
        result = process_episode(episode_dir, top_k)
        results.append(result)

    # Print summary
    print_summary(results, skipped, top_k)