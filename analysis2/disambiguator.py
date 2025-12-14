"""
disambiguator.py

Resolves causality between Caller -> Callee.
Uses SOTA heuristics to distinguish:
1. Traffic Spike (DDoS)
2. Callee Fault (Performance degradation)
3. Retry Storm (Amplification)
4. Network Partition (100% Error Rate)
"""

import numpy as np
from dataclasses import dataclass
from statistical_utils import compare_distributions

@dataclass
class EdgeVerdict:
    blames_caller: bool
    blames_callee: bool
    reason: str
    confidence: float # 0.0 to 1.0

class CallerCalleeDisambiguator:
    def analyze_edge(self, 
                     caller_metrics_base: dict, caller_metrics_curr: dict,
                     callee_metrics_base: dict, callee_metrics_curr: dict) -> EdgeVerdict:
        
        # 1. Analyze Traffic (RPS)
        rps_stat = compare_distributions(
            caller_metrics_base.get('outbound_rps', np.array([])),
            caller_metrics_curr.get('outbound_rps', np.array([]))
        )
        
        # 2. Analyze Latency (Prefer P99 if available)
        lat_key = 'dependency_latency_p99' if 'dependency_latency_p99' in caller_metrics_curr else 'dependency_latency'
        lat_stat = compare_distributions(
            caller_metrics_base.get(lat_key, np.array([])),
            caller_metrics_curr.get(lat_key, np.array([]))
        )

        # 3. Analyze Errors
        err_stat = compare_distributions(
            caller_metrics_base.get('dependency_error_rate', np.array([])),
            caller_metrics_curr.get('dependency_error_rate', np.array([]))
        )
        
        # Check for Network Partition (100% Error Rate Spike)
        curr_err_rate = np.mean(caller_metrics_curr.get('dependency_error_rate', [0]))
        if curr_err_rate > 0.95:
             return EdgeVerdict(
                blames_caller=False, blames_callee=False, # Shared infrastructure fault
                reason=f"Network Partition detected (100% Error Rate)",
                confidence=0.95
            )

        # --- HEURISTICS ---

        # Case A: Traffic Spike (DDoS / Flash Crowd)
        # Significant RPS increase (>50%), Latency follows
        if rps_stat.significant and rps_stat.effect_size > 2.0:
            return EdgeVerdict(
                blames_caller=True, blames_callee=False,
                reason=f"Traffic Spike (RPS increased significantly, d={rps_stat.effect_size:.2f})",
                confidence=0.9
            )

        # Case B: Callee Fault (Latency/Error up, RPS stable/down)
        # Standard service degradation
        if (lat_stat.significant or err_stat.significant) and (not rps_stat.significant or rps_stat.effect_size < 0.2):
            return EdgeVerdict(
                blames_caller=False, blames_callee=True,
                reason=f"Callee Degradation (Lat d={lat_stat.effect_size:.2f}) with stable load",
                confidence=0.95
            )

        # Case C: Retry Storm (Both Up)
        # RPS High AND Error High -> Callee failed first, Caller retrying aggressively
        if rps_stat.significant and rps_stat.effect_size > 0.5 and err_stat.significant:
            return EdgeVerdict(
                blames_caller=False, blames_callee=True,
                reason="Retry Storm detected (Errors driving RPS spike)",
                confidence=0.8
            )

        # Default: Inconclusive / Shared
        return EdgeVerdict(False, False, "Inconclusive (No clear signal)", 0.0)