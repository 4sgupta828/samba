"""
self_health_analyzer.py

Analyzes a single node to determine if it has INTERNAL degradation.
Distinguishes between:
1. Self-Degradation (High CPU, Memory, Internal 500s) -> Root Cause
2. Dependency-Degradation (High Latency to downstream) -> Victim
"""

import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass
from statistical_utils import compare_distributions

@dataclass
class SelfHealthResult:
    node_id: str
    is_root_cause_candidate: bool
    self_degradation_score: float # 0.0 to 10.0
    symptoms: List[str]

class SelfHealthAnalyzer:
    def __init__(self):
        # Metrics that indicate INTERNAL faults
        self.internal_metrics = [
            'cpu_usage', 'memory_usage', 'disk_io', 
            'thread_pool_active', 'garbage_collection_time',
            'internal_error_rate' # 500s not caused by dependencies
        ]

    def analyze(self, node_id: str, baseline_metrics: Dict[str, np.ndarray], current_metrics: Dict[str, np.ndarray]) -> SelfHealthResult:
        symptoms = []
        max_effect_size = 0.0
        
        # 1. Check Resource Saturation (CPU, Mem, Threads)
        for metric in self.internal_metrics:
            if metric in current_metrics and metric in baseline_metrics:
                stat = compare_distributions(baseline_metrics[metric], current_metrics[metric])
                
                if stat.significant and stat.effect_size > 0: # Only care about INCREASE
                    symptoms.append(f"{metric} increased (d={stat.effect_size:.2f})")
                    max_effect_size = max(max_effect_size, stat.effect_size)

        # 2. Check for "Limp Mode" (High Latency but LOW CPU/Throughput)
        # If latency is up but CPU is down, it might be a deadlock or thread starvation
        latency_stat = self._check_metric('avg_latency', baseline_metrics, current_metrics)
        cpu_stat = self._check_metric('cpu_usage', baseline_metrics, current_metrics)
        
        if latency_stat.effect_size > 1.0 and cpu_stat.effect_size < -0.5:
            symptoms.append("Potential Deadlock (High Latency / Low CPU)")
            max_effect_size = max(max_effect_size, 3.0) # High confidence

        # Score calculation (Map effect size 0.5-3.0 to Score 0-10)
        score = min(10.0, max_effect_size * 2.5)
        
        return SelfHealthResult(
            node_id=node_id,
            is_root_cause_candidate=(score > 3.0),
            self_degradation_score=score,
            symptoms=symptoms
        )

    def _check_metric(self, name, baseline, current):
        if name in baseline and name in current:
            return compare_distributions(baseline[name], current[name])
        return type('obj', (object,), {'effect_size': 0.0})