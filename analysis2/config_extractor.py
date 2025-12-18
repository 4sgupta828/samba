"""
config_extractor.py

Extracts configuration limits (timeouts, pool sizes, memory limits).
Provides context to SelfHealthAnalyzer to define "Saturation".
"""

from typing import Dict, Any

class CausalConstants:
    """Tunable parameters for Causal Physics logic."""
    # Latency: How much relative growth (Current/Base) counts as degradation?
    # 1.2 = 20% slowdown (strict)
    MIN_LATENCY_GROWTH = 1.2

    # Latency (Relaxed): Lower threshold for propagation detection
    # 1.15 = 15% slowdown (more lenient for real-world scenarios)
    MIN_LATENCY_GROWTH_RELAXED = 1.15

    # Propagation: How much of the Callee's pain must the Caller see?
    # 0.2 = Caller must reflect at least 20% of the Callee's relative degradation
    # (Accounts for dilution if Caller also calls healthy services)
    LATENCY_DILUTION_FACTOR = 0.2

    # Errors: What constitutes a "Spike"?
    MIN_ERROR_DELTA = 0.01  # 1% absolute increase

    # Deadlock: Massive latency spike required to suspect deadlock propagation
    DEADLOCK_GROWTH_THRESHOLD = 3.0

    # Capacity: RPS drop threshold
    # 0.2 = 20% drop in RPS indicates capacity reduction
    MIN_RPS_DROP = 0.2

class ConfigExtractor:
    def __init__(self, config_data: Dict[str, Any] = None):
        self.config = config_data or {}

    def get_limits_for_node(self, node_id: str, node_type: str) -> Dict[str, float]:
        """Returns resource limits for a specific node."""
        
        # Default limits (SOTA defaults based on common cloud configs)
        limits = {
            'max_threads': 200,
            'max_connections': 100,
            'memory_limit_mb': 1024,
            'cpu_cores': 4.0,
            'timeout_ms': 5000
        }

        # Override with specific config if available
        # (Implementation would parse actual config.yaml/json here)
        node_conf = self.config.get(node_id, {})
        limits.update(node_conf)
        
        return limits