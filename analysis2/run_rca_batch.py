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
from collections import defaultdict

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

    # Database Signals (Internal Health)
    'db.connections.active': 'thread_pool_active',  # DB connection pool = thread pool
    'db.cpu.utilization': 'cpu_usage',
    'db.query.latency': 'avg_latency',

    # Golden Signals (Self Health)
    'service.latency': 'avg_latency',
    'service.duration': 'avg_latency',
    'service.response_time': 'avg_latency',
    'service.error_rate': 'internal_error_rate',  # NEW: Error rate gauge (0-1) emitted by pods
    '.error_rate': 'internal_error_rate',  # Matches service.X.error_rate
    'service.requests': 'inbound_rps',
    'service.request_rate': 'inbound_rps',
    'service.throughput': 'inbound_rps',

    # Edge Signals (Client-side view of dependencies)
    'client.latency': 'dependency_latency',
    'dependency.latency': 'dependency_latency',
    'client.duration': 'dependency_latency',
    '.dependency.duration': 'dependency_latency',  # Matches service.X.dependency.duration
    'dependency.error_rate': 'dependency_error_rate',  # NEW: Dependency error rate gauge (0-1)
    '.dependency.error_rate': 'dependency_error_rate',  # Matches service.X.dependency.error_rate
    'client.requests': 'outbound_rps',
    'dependency.request_rate': 'outbound_rps',
    '.dependency.requests': 'outbound_rps',  # Matches service.X.dependency.requests

    # Queue Signals - KEEP ORTHOGONAL METRICS SEPARATE!
    # visible = messages waiting in queue (backlog)
    # in_flight = messages being processed (processing delay)
    'queue.depth': 'queue_depth',
    'queue_depth': 'queue_depth',
    'queue.size': 'queue_depth',
    'mq.messages.visible': 'queue_depth',  # Backlog waiting in queue
    'mq.messages.in_flight': 'queue_in_flight',  # Messages being processed (SEPARATE!)
    'mq.messages.age_seconds': 'queue_age',  # Staleness indicator
    'mq.queue.utilization': 'queue_utilization',  # Capacity pressure
    'queue.lag': 'queue_lag',
    'queue_lag': 'queue_lag',
    'consumer.lag': 'queue_lag'
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

    NEW: Also preserves full time-series DataFrame for temporal analysis.
    """

    def __init__(self, episode_dir: Path):
        self.episode_dir = episode_dir

        # Load static files
        self.label = self._load_json('label.json')
        self.topology = self._load_topology()

        # Load and prep metrics (KEEP FULL DF FOR TEMPORAL ANALYSIS)
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
            # Preserve all edge attributes (type, etc.)
            edge_attrs = {k: v for k, v in edge.items() if k not in ['source', 'target']}
            G.add_edge(edge['source'], edge['target'], **edge_attrs)

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
        Splits metrics into Baseline and Current windows using point-in-time analysis.

        Uses TimeWindowSelector for proper window selection:
        - Baseline: Pre-fault period (before fault_start)
        - Current: Window around analysis_time (during steady fault state)

        Returns two dictionaries: {node_id: {signal_name: np.array}}
        """
        if self.metrics_df.empty:
            return {}, {}

        # Import TimeWindowSelector
        from time_window_selector import TimeWindowSelector

        # Extract timing from label
        fault_start = self.label.get('fault_start_time', 0)
        fault_full_effect = self.label.get('fault_full_effect_time', None)
        recovery_start = self.label.get('recovery_start_time', None)
        episode_end_time = self.metrics_df['sim_time'].max()

        # If fault_full_effect not in label, use fault_start + ramp duration
        if fault_full_effect is None:
            fault_ramp = self.label.get('fault_ramp_duration', 0)
            fault_full_effect = fault_start + fault_ramp

        # Initialize window selector
        selector = TimeWindowSelector(
            metrics_df=self.metrics_df,
            episode_start=0,
            episode_end=episode_end_time,
            baseline_pct=0.25,
            current_pct=0.15,
            min_gap_pct=0.05
        )

        # Select analysis time: use selector's suggestion based on episode characteristics
        # This is data-driven without using recovery information (which RCA wouldn't know)
        #
        # The selector will suggest a point during the episode based on:
        # - Episode duration (percentage-based)
        # - Time since fault_start (to ensure fault has propagated)
        analysis_time = selector.suggest_analysis_time(
            fault_start_time=fault_start,
            target_percentile=0.6  # Analyze at 60% through episode
        )

        # Select windows using known fault start (simple, reliable for evaluation)
        windows = selector.select_windows(
            analysis_time=analysis_time,
            known_fault_start=fault_start
        )

        print(f"  [Time Windows]")
        print(f"    Baseline:  {windows.baseline.start:.1f}s - {windows.baseline.end:.1f}s ({windows.baseline.duration:.1f}s)")
        print(f"    Current:   {windows.current.start:.1f}s - {windows.current.end:.1f}s ({windows.current.duration:.1f}s)")
        print(f"    Gap:       {windows.current.start - windows.baseline.end:.1f}s")
        print(f"    Analysis:  {analysis_time:.1f}s (T+{analysis_time - fault_start:.1f}s after fault)")

        # Split DataFrame based on selected windows
        base_df = self.metrics_df[
            (self.metrics_df['sim_time'] >= windows.baseline.start) &
            (self.metrics_df['sim_time'] <= windows.baseline.end)
        ]
        curr_df = self.metrics_df[
            (self.metrics_df['sim_time'] >= windows.current.start) &
            (self.metrics_df['sim_time'] <= windows.current.end)
        ]

        print(f"    Baseline metrics: {len(base_df)}")
        print(f"    Current metrics:  {len(curr_df)}")

        # Store window times for later use (e.g., per-dependency metric extraction)
        self.baseline_window = (windows.baseline.start, windows.baseline.end)
        self.current_window = (windows.current.start, windows.current.end)

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

                # 3. Use RAW metric name (NO MAPPING!)
                # Just store metrics with their original names
                signal_name = raw_metric_name
                
                # 4. Extract Values (Handle simple floats vs summary dicts)
                # CRITICAL FIX: Aggregate by timestamp first!
                # Metrics may have multiple dimensions (e.g., request_type)
                # For counter metrics (errors, requests), SUM across dimensions
                # For gauge metrics (latency, CPU), AVERAGE across dimensions

                # Determine if this is a counter or gauge metric
                # NOTE: error_rate, rps are GAUGES (rates), not counters!
                # Only _count, _total, _requests (without _rate suffix) are counters
                is_gauge_rate = any(signal_name.endswith(suffix) for suffix in [
                    '_rate', '_ratio', 'rps', '_utilization', '_usage'
                ])
                is_counter = not is_gauge_rate and any(keyword in signal_name for keyword in [
                    'request', 'count', 'total', 'error'
                ])

                # Group by timestamp
                timestamp_groups = metric_rows.groupby('sim_time')
                values_list = []

                for timestamp, time_group in timestamp_groups:
                    time_values = []

                    for _, row in time_group.iterrows():
                        val = row.get('value')

                        # Handle Summary/Histogram metrics (e.g. latency p99)
                        # Check for None or NaN
                        if (val is None or (isinstance(val, float) and np.isnan(val))) and 'summary' in row and isinstance(row['summary'], dict):
                            # For latency, prefer P99 (tail latency)
                            # For others, use Mean or Max
                            summary = row['summary']
                            if 'latency' in signal_name or 'duration' in signal_name:
                                val = summary.get('p99', summary.get('p95', summary.get('mean')))
                            else:
                                val = summary.get('mean', summary.get('max'))

                        if val is not None:
                            try:
                                time_values.append(float(val))
                            except (ValueError, TypeError):
                                pass

                    # Aggregate values at this timestamp
                    if time_values:
                        if is_counter:
                            # Sum for counters (e.g., total errors across all request types)
                            aggregated_value = sum(time_values)
                        else:
                            # Average for gauges (e.g., average latency across request types)
                            aggregated_value = np.mean(time_values)

                        values_list.append(aggregated_value)

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

    def aggregate_pods_to_services(self, pod_data: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Aggregate pod-level metrics to service-level.

        For each service with pods:
        - Combine all pod metrics into service-level metrics
        - Use mean for rates/percentages, sum for counts
        - This enables service-level edge analysis

        Args:
            pod_data: {node_id: {metric_name: values}}

        Returns:
            service_data: {service_name: {metric_name: aggregated_values}}
        """
        service_data = {}

        # Group pods by their parent service
        service_to_pods = defaultdict(list)

        for node_id in pod_data.keys():
            node_attrs = self.topology.nodes.get(node_id, {})
            parent_service = node_attrs.get('parent_service')

            if parent_service:
                # This is a pod - add to its parent service
                service_to_pods[parent_service].append(node_id)
            else:
                # This is a standalone node (Service, ExternalService, etc.)
                # Copy its metrics as-is
                service_data[node_id] = pod_data[node_id]

        # Aggregate metrics for each service
        for service_name, pod_ids in service_to_pods.items():
            service_metrics = {}

            # Get all unique metric names across all pods
            all_metric_names = set()
            for pod_id in pod_ids:
                all_metric_names.update(pod_data[pod_id].keys())

            # Aggregate each metric
            for metric_name in all_metric_names:
                # Collect values from all pods that have this metric
                all_values = []
                for pod_id in pod_ids:
                    if metric_name in pod_data[pod_id]:
                        all_values.extend(pod_data[pod_id][metric_name])

                if all_values:
                    # Convert to numpy array
                    service_metrics[metric_name] = np.array(all_values)

            if service_metrics:
                service_data[service_name] = service_metrics

        return service_data

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

def perform_pod_forensics(
    service_name: str,
    topology: nx.DiGraph,
    baseline_pods: Dict[str, Dict[str, np.ndarray]],
    current_pods: Dict[str, Dict[str, np.ndarray]],
    service_result: Dict
) -> Dict:
    """
    LEVEL 2 Analysis: Pod-level forensics within a service.

    When a service is identified as root cause, analyze its pods to determine:
    1. Are all pods degraded uniformly? (Service-wide issue)
    2. Is it just 1-2 outlier pods? (Pod-specific issue)
    3. Which pods are most degraded?

    Args:
        service_name: The service to analyze
        topology: Full topology graph
        baseline_pods: Pod-level baseline metrics
        current_pods: Pod-level current metrics
        service_result: The service-level RCA result

    Returns:
        Dict with pod forensics results
    """
    from self_health_analyzer import SelfHealthAnalyzer
    from config_extractor import ConfigExtractor

    # Find all pods for this service
    service_pods = [
        node for node in topology.nodes
        if topology.nodes[node].get('parent_service') == service_name
    ]

    if not service_pods:
        return {
            'pod_count': 0,
            'analysis': 'No pods found (standalone service)',
            'degraded_pods': [],
            'healthy_pods': []
        }

    # Analyze each pod
    config_extractor = ConfigExtractor({})
    analyzer = SelfHealthAnalyzer(config_extractor)

    pod_analyses = []
    for pod_id in service_pods:
        node_type = topology.nodes[pod_id].get('type', 'Pod')
        baseline_metrics = baseline_pods.get(pod_id, {})
        current_metrics = current_pods.get(pod_id, {})

        if not current_metrics:
            continue

        analysis = analyzer.analyze(pod_id, node_type, baseline_metrics, current_metrics)

        pod_analyses.append({
            'pod_id': pod_id,
            'self_score': float(analysis.self_degradation_score),
            'symptoms': analysis.symptoms,
            'is_degraded': bool(analysis.self_degradation_score > 2.0)  # Explicit bool conversion
        })

    # Sort by degradation score
    pod_analyses.sort(key=lambda x: x['self_score'], reverse=True)

    # Categorize pods
    degraded_pods = [p for p in pod_analyses if p['is_degraded']]
    healthy_pods = [p for p in pod_analyses if not p['is_degraded']]

    # Determine pattern
    if len(degraded_pods) == 0:
        pattern = "No pods showing self-degradation (likely victim of dependency)"
    elif len(degraded_pods) == len(pod_analyses):
        pattern = "All pods degraded uniformly (service-wide issue)"
    elif len(degraded_pods) <= 2:
        pattern = f"Outlier pods detected ({len(degraded_pods)}/{len(pod_analyses)} degraded)"
    else:
        pattern = f"Majority pods degraded ({len(degraded_pods)}/{len(pod_analyses)})"

    # Remove is_degraded from output (not JSON serializable)
    for pod in degraded_pods:
        pod.pop('is_degraded', None)
    for pod in healthy_pods:
        pod.pop('is_degraded', None)

    return {
        'pod_count': int(len(pod_analyses)),
        'degraded_count': int(len(degraded_pods)),
        'healthy_count': int(len(healthy_pods)),
        'pattern': pattern,
        'degraded_pods': degraded_pods[:5],  # Top 5 most degraded
        'healthy_pods': healthy_pods[:3]  # Top 3 healthiest
    }

def aggregate_to_service_level_DEPRECATED(results: List[Dict], topology: nx.DiGraph) -> List[Dict]:
    """
    DEPRECATED: No longer needed with two-level architecture.
    Service-level analysis happens at data aggregation time, not result aggregation time.
    """
    # This function is kept for backwards compatibility but should not be used
    raise NotImplementedError("Use two-level architecture instead")

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
        baseline_pods, current_pods = adapter.get_data_windows()

        ground_truth_node = adapter.label.get('root_cause_node')
        fault_start_time = adapter.label.get('fault_start_time', 0)

        # 2. Aggregate pod metrics to service level (LEVEL 1 DATA)
        baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
        current_services = adapter.aggregate_pods_to_services(current_pods)

        # 3. Prepare optional data sources
        traces_file = episode_dir / 'traces.jsonl'
        if not traces_file.exists():
            traces_file = None

        logs_file = episode_dir / 'logs.jsonl'
        if not logs_file.exists():
            logs_file = None

        # 4. LEVEL 1: Service-level RCA (with pod-level integration)
        engine = WhiteboxRCAEngine(adapter.topology)
        service_results = engine.analyze_incident(
            baseline_services, current_services,
            metrics_df=adapter.metrics_df,
            baseline_window=adapter.baseline_window,
            current_window=adapter.current_window,
            fault_start_time=fault_start_time,
            traces_file=traces_file,
            logs_file=logs_file,  # Add logs for network partition detection
            baseline_pods=baseline_pods,  # Pass pod data for integrated scoring
            current_pods=current_pods
        )

        # 5. LEVEL 2: Pod-level forensics for top service(s)
        # Identify which pods within the root cause service are problematic
        if service_results:
            top_service = service_results[0]['node']
            pod_forensics = perform_pod_forensics(
                top_service, adapter.topology,
                baseline_pods, current_pods,
                service_results[0]
            )
            service_results[0]['pod_forensics'] = pod_forensics

        # Keep results at service level (no aggregation needed - already at service level)
        results = service_results

        # NOTE: Removed "no anomalies" check - we now rank ALL nodes
        if not results:
            print("  ⚠️  No nodes found in topology.")
            error_info = {'error': 'No nodes in topology', 'error_type': 'EmptyTopology'}
            create_marker_file(episode_dir, 'Failed', error_info)
            return {
                'episode': str(episode_dir),
                'status': 'empty_topology',
                'ground_truth': ground_truth_node
            }

        # 5. Validate Results
        top_candidate = results[0]['node']
        top_score = results[0]['score']
        top_story = results[0].get('story', [])

        # Check if ground truth in top-K
        top_k_nodes = [r['node'] for r in results[:top_k]]
        is_in_top_k = ground_truth_node in top_k_nodes

        if is_in_top_k:
            rank = top_k_nodes.index(ground_truth_node) + 1
        else:
            rank = None

        # 6. Print Report
        print(f"\n  Ground Truth: {ground_truth_node}")
        print(f"  Top Result:   {top_candidate} (Score: {top_score:.1f})")

        # Show score breakdown for top result
        top_result = results[0]
        print(f"     Score breakdown:")
        print(f"       - Integrated score: {top_result.get('integrated_score', 0):.1f} (service: {top_result.get('self_score', 0):.1f})")
        health_meta = top_result.get('health_metadata', {})
        if health_meta.get('pod_score', 0) > 0:
            print(f"         Pod contribution: {health_meta['pod_score']:.1f} (coverage: {health_meta.get('coverage', 0):.1%}, pattern: {health_meta.get('pattern', 'N/A')})")
        print(f"       - Guilt ratio: {top_result.get('guilt_ratio', 0):.1f}")
        print(f"       - Temporal: {top_result.get('temporal_score', 0):.1f}")
        print(f"       - Trace: {top_result.get('trace_score', 0):.1f} {'(authoritative)' if top_result.get('is_trace_authoritative') else ''}")
        print(f"       - Blamed by: {top_result.get('blamed_by', [])}")

        # Show pod forensics if available
        pod_forensics = top_result.get('pod_forensics')
        if pod_forensics and pod_forensics.get('pod_count', 0) > 0:
            print(f"\n     Pod Forensics:")
            print(f"       - Pattern: {pod_forensics.get('pattern', 'N/A')}")
            print(f"       - Pods: {pod_forensics.get('degraded_count', 0)}/{pod_forensics.get('pod_count', 0)} degraded")
            if pod_forensics.get('degraded_pods'):
                print(f"       - Top degraded pods:")
                for pod in pod_forensics['degraded_pods'][:3]:
                    symptoms_str = ', '.join(pod['symptoms'][:2]) if pod['symptoms'] else 'No symptoms'
                    print(f"         * {pod['pod_id']}: score={pod['self_score']:.1f} ({symptoms_str})")

        if rank == 1:
            print(f"  ✅ SUCCESS - EXACT MATCH (Rank 1)")
        elif is_in_top_k:
            print(f"  ❌ FAILED - Found at Rank {rank}/{top_k} (requires Rank 1)")
        else:
            print(f"  ❌ FAILED - NOT IN TOP-{top_k}")
            print(f"     Top {min(3, len(top_k_nodes))}: {top_k_nodes[:3]}")

        # Print the Generated Story (Explanation)
        if top_story:
            print("\n  📜 Causal Narrative:")
            for line in top_story:
                print(f"    {line}")

        # 6.5. Validate Ground Truth
        # Check if ground truth label is valid (shows evidence of being faulty)
        gt_validation = engine.validate_ground_truth(ground_truth_node, results)
        gt_validation['ground_truth_rank'] = rank  # Add rank to validation

        # Print validation results
        print(f"\n  Ground Truth Validation:")
        print(f"     Status: {'✅ Valid' if gt_validation['is_valid'] else '❌ Invalid/Questionable'}")
        print(f"     Confidence: {gt_validation['confidence']}")
        print(f"     Evidence Score: {gt_validation['evidence_score']}/{gt_validation['max_evidence_score']}")
        print(f"     {gt_validation['verdict']}")

        if not gt_validation['is_valid']:
            print(f"\n  ⚠️  WARNING: Ground truth shows insufficient evidence of being faulty.")
            print(f"      This may indicate:")
            print(f"        - Fault injection didn't work properly")
            print(f"        - Incorrect ground truth label")
            print(f"        - Component fault doesn't produce detectable signals")
            print(f"      Consider excluding this case from RCA evaluation metrics.")

        # 7. Save results to JSON file
        output_data = {
            'ground_truth': ground_truth_node,
            'top_k': top_k,
            'found_in_top_k': is_in_top_k,
            'rank': rank,
            'ground_truth_validation': gt_validation,  # NEW: Include validation
            'top_candidates': results[:top_k],  # Top K for quick reference
            'all_candidates': results,  # ALL nodes with full analysis
            'total_service_candidates': len(results)
        }

        output_file = episode_dir / 'rca_analysis.json'
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        # 8. Create marker file (SUCCESS = Rank 1 only)
        if rank == 1:
            create_marker_file(episode_dir, 'Investigated', {'rank': rank, 'top_k': top_k})
            status = 'success'
        else:
            status = 'failed'

        return {
            'episode': str(episode_dir),
            'status': status,
            'ground_truth': ground_truth_node,
            'top_result': top_candidate,
            'rank': rank,
            'in_top_k': is_in_top_k,
            'gt_valid': gt_validation['is_valid']
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

def print_summary(results: List[Dict], skipped: Dict[str, int]):
    """Print summary of batch processing."""
    total_processed = len(results)
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    no_anomaly_count = sum(1 for r in results if r['status'] == 'no_anomalies')
    error_count = sum(1 for r in results if r['status'] == 'error')
    empty_topology_count = sum(1 for r in results if r['status'] == 'empty_topology')

    # Ground truth validation stats
    valid_gt_count = sum(1 for r in results if r.get('gt_valid', False))
    invalid_gt_count = sum(1 for r in results if 'gt_valid' in r and not r['gt_valid'])

    print(f"\n{'='*80}")
    print("BATCH WHITEBOX RCA SUMMARY")
    print(f"{'='*80}")
    print(f"Total episodes found: {total_processed + skipped['investigated'] + skipped['failed']}")
    print(f"  Already investigated (Rank 1): {skipped['investigated']}")
    print(f"  Already failed (Not Rank 1): {skipped['failed']}")
    print(f"  Processed this run: {total_processed}")
    print()
    print(f"Results for {total_processed} processed episodes:")
    print(f"  ✅ Success (Rank 1 only): {success_count} ({success_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ❌ Failed (Not Rank 1): {failed_count} ({failed_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ⚠️  No anomalies: {no_anomaly_count} ({no_anomaly_count/max(1,total_processed)*100:.1f}%)")
    print(f"  📭 Empty topology: {empty_topology_count} ({empty_topology_count/max(1,total_processed)*100:.1f}%)")
    print(f"  🔥 Errors: {error_count} ({error_count/max(1,total_processed)*100:.1f}%)")
    print()
    print(f"Ground Truth Validation:")
    print(f"  ✅ Valid: {valid_gt_count} ({valid_gt_count/max(1,total_processed)*100:.1f}%)")
    print(f"  ❌ Invalid: {invalid_gt_count} ({invalid_gt_count/max(1,total_processed)*100:.1f}%)")
    print(f"{'='*80}")

    # Show success rate including previously investigated
    total_investigated = success_count + skipped['investigated']
    total_attempted = total_processed + skipped['investigated'] + skipped['failed']
    if total_attempted > 0:
        print(f"\nOverall success rate (Rank 1): {total_investigated}/{total_attempted} ({total_investigated/total_attempted*100:.1f}%)")

    # Show detailed breakdown of failures
    if failed_count > 0:
        rank_distribution = {}
        for r in results:
            if r['status'] == 'failed' and r.get('rank'):
                rank = r['rank']
                rank_distribution[rank] = rank_distribution.get(rank, 0) + 1

        if rank_distribution:
            print(f"\nFailure rank distribution:")
            for rank in sorted(rank_distribution.keys()):
                print(f"  - Rank {rank}: {rank_distribution[rank]} episodes")

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
    print_summary(results, skipped)