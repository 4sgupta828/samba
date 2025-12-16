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
    def __init__(self, config_extractor: ConfigExtractor = None, threshold_config=None):
        self.config_extractor = config_extractor or ConfigExtractor()

        # Load threshold configuration
        from rca_config import get_thresholds
        self.thresholds = get_thresholds(threshold_config)

        self.resource_metrics = [
            'cpu_usage', 'memory_usage', 'thread_pool_active',
            'garbage_collection_time', 'internal_error_rate'
        ]

        # Performance degradation metrics (latency, errors, queue)
        self.performance_metrics = [
            'avg_latency', 'internal_error_rate', 'queue_depth', 'queue_lag'
        ]

    def analyze(self, node_id: str, node_type: str, 
                baseline: Dict[str, np.ndarray], 
                current: Dict[str, np.ndarray]) -> SelfHealthResult:
        
        symptoms = []
        max_effect_size = 0.0
        resource_score = 0.0
        
        # 1. Check Resource Saturation
        limits = self.config_extractor.get_limits_for_node(node_id, node_type)
        
        for metric in self.resource_metrics:
            if metric in current and metric in baseline:
                stat = compare_distributions(baseline[metric], current[metric])
                
                # Check for Limit Saturation (e.g., Active Threads near Max Threads)
                curr_max = np.max(current[metric]) if len(current[metric]) > 0 else 0

                limit_hit = False
                if metric == 'thread_pool_active' and curr_max > limits['max_threads'] * self.thresholds.resource_saturation_threshold:
                    symptoms.append(f"Thread Pool Saturation ({curr_max}/{limits['max_threads']})")
                    limit_hit = True

                if stat.significant and stat.effect_size > self.thresholds.min_effect_size_small:
                    symptoms.append(f"{metric} increased (d={stat.effect_size:.2f})")
                    max_effect_size = max(max_effect_size, stat.effect_size)

                    if limit_hit or stat.effect_size > self.thresholds.min_effect_size_large:
                        resource_score = max(resource_score, 10.0) # Definite saturation
                    else:
                        resource_score = max(resource_score, min(10.0, stat.effect_size * 2.5))

        # 2. Check Performance Degradation (Latency, Errors, Queue Depth)
        performance_score = 0.0

        # Check Latency Degradation
        if 'avg_latency' in current and 'avg_latency' in baseline:
            lat_stat = compare_distributions(baseline['avg_latency'], current['avg_latency'])
            if lat_stat.significant and lat_stat.effect_size > self.thresholds.min_effect_size_medium:
                symptoms.append(f"Latency increased (d={lat_stat.effect_size:.2f})")
                max_effect_size = max(max_effect_size, lat_stat.effect_size)

                # Latency increase is strong evidence of root cause
                if lat_stat.effect_size > self.thresholds.min_effect_size_very_large:
                    performance_score = max(performance_score, 10.0)
                elif lat_stat.effect_size > self.thresholds.min_effect_size_large:
                    performance_score = max(performance_score, 8.0)
                else:
                    performance_score = max(performance_score, min(10.0, lat_stat.effect_size * 3.0))

        # Check Error Rate Increase
        if 'internal_error_rate' in current and 'internal_error_rate' in baseline:
            err_stat = compare_distributions(baseline['internal_error_rate'], current['internal_error_rate'])
            curr_err_mean = np.mean(current['internal_error_rate']) if len(current['internal_error_rate']) > 0 else 0
            base_err_mean = np.mean(baseline['internal_error_rate']) if len(baseline['internal_error_rate']) > 0 else 0

            # Check for significant absolute increase or relative increase
            if (curr_err_mean > self.thresholds.error_rate_minor and curr_err_mean > base_err_mean * 1.5) or err_stat.effect_size > self.thresholds.min_effect_size_medium:
                symptoms.append(f"Error rate increased ({curr_err_mean:.1%})")
                max_effect_size = max(max_effect_size, err_stat.effect_size)

                # Error rate increase is strong evidence
                if curr_err_mean > self.thresholds.error_rate_severe:
                    performance_score = max(performance_score, 10.0)
                elif curr_err_mean > self.thresholds.error_rate_moderate:
                    performance_score = max(performance_score, 8.0)
                else:
                    performance_score = max(performance_score, 6.0)

        # Check Queue Depth/Lag Increase
        for queue_metric in ['queue_depth', 'queue_lag']:
            if queue_metric in current and queue_metric in baseline:
                q_stat = compare_distributions(baseline[queue_metric], current[queue_metric])
                if q_stat.significant and q_stat.effect_size > 1.5:
                    symptoms.append(f"{queue_metric} increased (d={q_stat.effect_size:.2f})")
                    max_effect_size = max(max_effect_size, q_stat.effect_size)

                    # Queue buildup is evidence of bottleneck
                    if q_stat.effect_size > 3.0:
                        performance_score = max(performance_score, 10.0)
                    else:
                        performance_score = max(performance_score, min(10.0, q_stat.effect_size * 2.5))
                    break  # Only report once for queue metrics

        # 3. Check for "Limp Mode" / Deadlock Patterns
        lat_stat = self._check_metric('avg_latency', baseline, current)
        cpu_stat = self._check_metric('cpu_usage', baseline, current)

        limp_mode_score = 0.0

        # Pattern A: High Latency + LOW CPU = Process is hung/deadlocked
        if lat_stat.effect_size > 1.5 and cpu_stat.effect_size < -0.2:
            symptoms.append("⚠️ Potential Deadlock (High Latency / Low CPU)")
            limp_mode_score = 10.0 # Critical finding

        # Pattern B: Thread Saturation + Zero Throughput = Zombie Pod (all threads deadlocked)
        # This catches pods that have all threads blocked but aren't serving any traffic
        if 'thread_pool_active' in current and 'inbound_rps' in current:
            curr_threads = np.mean(current['thread_pool_active']) if len(current['thread_pool_active']) > 0 else 0
            curr_rps = np.mean(current['inbound_rps']) if len(current['inbound_rps']) > 0 else 0
            base_rps = np.mean(baseline.get('inbound_rps', np.array([0]))) if 'inbound_rps' in baseline else 0

            # High thread usage but zero/minimal throughput + was previously active
            thread_saturation = curr_threads > limits['max_threads'] * self.thresholds.thread_saturation_threshold
            zero_throughput = curr_rps < self.thresholds.throughput_near_zero_absolute
            was_active = base_rps > self.thresholds.was_active_absolute

            if thread_saturation and zero_throughput and was_active:
                symptoms.append(f"⚠️ Zombie Pod (Thread Deadlock): {curr_threads:.0f}/{limits['max_threads']} threads saturated, RPS dropped from {base_rps:.1f} to {curr_rps:.1f}")
                limp_mode_score = max(limp_mode_score, 10.0) # Critical finding

        # 4. Final Scoring
        final_score = max(resource_score, performance_score, limp_mode_score)
        
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