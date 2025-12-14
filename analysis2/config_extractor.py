"""
config_extractor.py

Extracts configuration limits (timeouts, pool sizes, memory limits).
Provides context to SelfHealthAnalyzer to define "Saturation".
"""

from typing import Dict, Any

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