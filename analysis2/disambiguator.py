"""
disambiguator.py

Resolves causality between two connected nodes (Caller -> Callee).
Solves: "Did Caller overload Callee? Or is Callee just slow?"
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
        
        # 1. Analyze Traffic (RPS) - Did Caller send more?
        rps_stat = compare_distributions(
            caller_metrics_base.get('outbound_rps', np.array([])),
            caller_metrics_curr.get('outbound_rps', np.array([]))
        )
        
        # 2. Analyze Latency - Did Callee get slower?
        lat_stat = compare_distributions(
            caller_metrics_base.get('dependency_latency', np.array([])),
            caller_metrics_curr.get('dependency_latency', np.array([]))
        )

        # 3. Analyze Errors - Did Callee fail?
        err_stat = compare_distributions(
            caller_metrics_base.get('dependency_error_rate', np.array([])),
            caller_metrics_curr.get('dependency_error_rate', np.array([]))
        )

        # --- HEURISTICS ---

        # Case A: Traffic Spike (DDoS / Flash Crowd)
        # Significant RPS increase, Latency follows
        if rps_stat.significant and rps_stat.effect_size > 1.0:
            return EdgeVerdict(
                blames_caller=True, blames_callee=False,
                reason=f"Traffic Spike (RPS d={rps_stat.effect_size:.2f})",
                confidence=0.9
            )

        # Case B: Callee Fault (Latency/Error up, RPS stable)
        if (lat_stat.significant or err_stat.significant) and (not rps_stat.significant or rps_stat.effect_size < 0.5):
            return EdgeVerdict(
                blames_caller=False, blames_callee=True,
                reason=f"Callee Degradation (Lat d={lat_stat.effect_size:.2f}) with stable load",
                confidence=0.95
            )

        # Case C: Retry Storm (Both Up)
        # RPS High AND Error High. Usually implies Callee failed first, causing retries.
        if rps_stat.significant and err_stat.significant:
            return EdgeVerdict(
                blames_caller=False, blames_callee=True,
                reason="Retry Storm detected (Errors causing RPS spike)",
                confidence=0.7
            )

        # Default: Shared/Unclear
        return EdgeVerdict(False, False, "Inconclusive", 0.0)