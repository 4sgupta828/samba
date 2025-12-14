"""
self_health_analyzer.py

Analyzes a single node for INTERNAL degradation.
Distinguishes between:
1. Saturation (High CPU/Mem/Threads) -> Root Cause
2. Limp Mode (High Latency + Low CPU) -> Deadlock/Hang (Root Cause)
3. Dependency-Only (High Latency to downstream) -> Victim
"""

import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass
from statistical_utils import compare_distributions, StatResult
from config_extractor import ConfigExtractor

@dataclass
class SelfHealthResult:
    node_id: str
    is_root_cause_candidate: bool
    self_degradation_score: float # 0.0 to 10.0
    symptoms: List[str]
    confidence: str # 'high', 'medium', 'low'

class SelfHealthAnalyzer:
    def __init__(self, config_extractor: ConfigExtractor = None):
        self.config_extractor = config_extractor or ConfigExtractor()
        
        self.resource_metrics = [
            'cpu_usage', 'memory_usage', 'thread_pool_active', 
            'garbage_collection_time', 'internal_error_rate'
        ]

    def analyze(self, node_id: str, node_type: str, 
                baseline: Dict[str, np.ndarray], 
                current: Dict[str, np.ndarray]) -> SelfHealthResult:
        
        symptoms = []
        max_effect_size = 0.0
        resource_score = 0.0
        
        # 1. Check Resource Saturation (Old Code Logic)
        # We compare against limits if available, otherwise relative increase
        limits = self.config_extractor.get_limits_for_node(node_id, node_type)
        
        for metric in self.resource_metrics:
            if metric in current and metric in baseline:
                stat = compare_distributions(baseline[metric], current[metric])
                
                # Check for Limit Saturation (e.g., Active Threads near Max Threads)
                curr_max = np.max(current[metric]) if len(current[metric]) > 0 else 0
                
                limit_hit = False
                if metric == 'thread_pool_active' and curr_max > limits['max_threads'] * 0.9:
                    symptoms.append(f"Thread Pool Saturation ({curr_max}/{limits['max_threads']})")
                    limit_hit = True
                
                if stat.significant and stat.effect_size > 0.5:
                    symptoms.append(f"{metric} increased (d={stat.effect_size:.2f})")
                    max_effect_size = max(max_effect_size, stat.effect_size)
                    
                    if limit_hit or stat.effect_size > 2.0:
                        resource_score = max(resource_score, 10.0) # Definite saturation
                    else:
                        resource_score = max(resource_score, min(10.0, stat.effect_size * 2.5))

        # 2. Check for "Limp Mode" / Deadlock (New Code Logic)
        # High Latency + LOW CPU = Process is hung/deadlocked
        lat_stat = self._check_metric('avg_latency', baseline, current)
        cpu_stat = self._check_metric('cpu_usage', baseline, current)
        
        limp_mode_score = 0.0
        if lat_stat.effect_size > 1.5 and cpu_stat.effect_size < -0.2:
            symptoms.append("⚠️ Potential Deadlock (High Latency / Low CPU)")
            limp_mode_score = 10.0 # Critical finding
        
        # 3. Final Scoring
        final_score = max(resource_score, limp_mode_score)
        
        return SelfHealthResult(
            node_id=node_id,
            is_root_cause_candidate=(final_score > 4.0),
            self_degradation_score=final_score,
            symptoms=symptoms,
            confidence='high' if final_score > 7.0 else 'medium'
        )

    def _check_metric(self, name, baseline, current) -> StatResult:
        if name in baseline and name in current:
            return compare_distributions(baseline[name], current[name])
        # Return dummy result if missing
        return type('obj', (object,), {'effect_size': 0.0, 'significant': False})