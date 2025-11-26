"""
Configuration Context Extractor

Extracts relevant configuration settings that affect fault propagation:
- Connection pool capacities
- Retry policies and backoff strategies
- Timeout configurations
- Resource limits

This provides context for understanding why certain behaviors occurred.
"""

from typing import Dict, Optional
from pathlib import Path
import yaml


class ConfigExtractor:
    """Extracts configuration context for fault propagation analysis."""

    def __init__(self, simulation_config_path: Optional[Path] = None):
        """
        Initialize extractor.

        Args:
            simulation_config_path: Path to simulation_config.yaml (optional)
        """
        self.config = {}
        if simulation_config_path and Path(simulation_config_path).exists():
            with open(simulation_config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}

    def extract_database_config(self, node_id: str) -> Dict:
        """
        Extract database configuration.

        Returns connection pool, CPU, and query performance settings.
        """
        db_config = self.config.get('database', {})

        return {
            'connection_pool': {
                'capacity': db_config.get('connection_pool_capacity', 100),
                'description': 'Maximum concurrent connections'
            },
            'resources': {
                'cpu_cores': db_config.get('cpu_cores', 4),
                'memory_mb': db_config.get('memory_capacity_mb', 1024)
            },
            'performance': {
                'query_base_time_ms': db_config.get('query_base_time_mean_seconds', 0.02) * 1000,
                'cpu_usage_per_query_cores': db_config.get('query_cpu_usage_cores', 0.7)
            },
            'background_jobs': {
                'enabled': db_config.get('background_jobs_enabled', True),
                'cpu_cores_used': db_config.get('background_jobs_cpu_cores_used', 1.8),
                'description': 'Background maintenance tasks that can spike CPU'
            }
        }

    def extract_service_config(self, node_id: str, node_type: str) -> Dict:
        """
        Extract service/pod configuration.

        Returns connection pools, retry policies, timeouts.
        """
        compute_config = self.config.get('compute', {})
        defaults = self.config.get('defaults', {})

        # Retry configuration
        retry_config = defaults.get('retry', {})
        retry_info = {
            'max_attempts': retry_config.get('max_attempts', 3),
            'backoff_base_ms': retry_config.get('backoff_base_seconds', 0.1) * 1000,
            'backoff_jitter_range_ms': [
                j * 1000 for j in retry_config.get('backoff_jitter_range_seconds', [0.01, 0.05])
            ],
            'load_amplification_factor': retry_config.get('max_attempts', 3),
            'description': f"Exponential backoff with {retry_config.get('max_attempts', 3)} attempts"
        }

        # Timeout configuration
        timeouts = compute_config.get('timeouts', {})
        timeout_info = {
            'database_call_ms': timeouts.get('database_call_seconds', 5.0) * 1000,
            'cache_call_ms': timeouts.get('cache_call_seconds', 1.0) * 1000,
            'external_api_ms': timeouts.get('external_api_seconds', 10.0) * 1000
        }

        # Connection pool (for services calling DB)
        connection_pool_info = {
            'capacity': compute_config.get('db_connection_pool_capacity', 20),
            'description': 'Service-level DB connection pool'
        }

        # Resources
        resources_info = {
            'cpu_cores': compute_config.get('cpu_capacity_cores', 1.0),
            'memory_mb': compute_config.get('memory_capacity_mb', 512)
        }

        return {
            'connection_pool': connection_pool_info,
            'retry_policy': retry_info,
            'timeouts': timeout_info,
            'resources': resources_info
        }

    def extract_cache_config(self, node_id: str) -> Dict:
        """Extract cache configuration."""
        cache_config = self.config.get('cache', {})

        return {
            'capacity': {
                'max_size_items': cache_config.get('max_size_items', 1000),
                'description': 'Maximum number of cached items'
            },
            'performance': {
                'latency_mean_ms': cache_config.get('latency_mean_ms', 2.0),
                'latency_stdev_ms': cache_config.get('latency_stdev_ms', 0.5)
            }
        }

    def extract_queue_config(self, node_id: str) -> Dict:
        """Extract message queue configuration."""
        queue_config = self.config.get('queue', {})

        return {
            'capacity': {
                'max_messages': queue_config.get('max_messages', 10000),
                'description': 'Maximum queued messages before rejection'
            },
            'performance': {
                'publish_latency_ms': queue_config.get('publish_latency_mean_ms', 5.0),
                'consume_latency_ms': queue_config.get('consume_latency_mean_ms', 5.0)
            }
        }

    def extract_for_node(self, node_id: str, node_type: str) -> Dict:
        """
        Extract configuration for any node type.

        Args:
            node_id: Node identifier
            node_type: Type of node (Service, SqlDatabase, etc.)

        Returns:
            Configuration dictionary specific to node type
        """
        type_mapping = {
            'SqlDatabase': self.extract_database_config,
            'Service': self.extract_service_config,
            'Pod': self.extract_service_config,
            'InMemoryCache': self.extract_cache_config,
            'MessageQueue': self.extract_queue_config,
        }

        extractor = type_mapping.get(node_type)
        if extractor:
            if node_type in ['Service', 'Pod']:
                return extractor(node_id, node_type)
            else:
                return extractor(node_id)

        return {}

    def extract_all(self, topology: Dict) -> Dict[str, Dict]:
        """
        Extract configuration for all nodes in topology.

        Args:
            topology: Topology dictionary with node information

        Returns:
            Dictionary mapping node_id -> configuration
        """
        results = {}

        for node in topology.get('nodes', []):
            node_id = node['id']
            node_type = node.get('type', 'Unknown')

            config = self.extract_for_node(node_id, node_type)
            if config:
                results[node_id] = {
                    'node_id': node_id,
                    'node_type': node_type,
                    'configuration': config
                }

        return results

    def generate_report(self, configs: Dict[str, Dict]) -> str:
        """
        Generate human-readable configuration report.

        Args:
            configs: Dictionary of configuration contexts

        Returns:
            Formatted report string
        """
        if not configs:
            return "No configuration data extracted.\n"

        lines = ["=" * 80, "CONFIGURATION CONTEXT", "=" * 80, ""]

        # Group by type
        by_type = {}
        for node_id, config_data in configs.items():
            node_type = config_data['node_type']
            if node_type not in by_type:
                by_type[node_type] = []
            by_type[node_type].append((node_id, config_data['configuration']))

        for node_type, nodes in sorted(by_type.items()):
            lines.append(f"\n{node_type} Configuration")
            lines.append("-" * 60)

            for node_id, config in nodes[:3]:  # Show first 3 of each type
                lines.append(f"\n  {node_id}:")

                # Connection pool
                if 'connection_pool' in config:
                    pool = config['connection_pool']
                    lines.append(f"    Connection Pool: {pool.get('capacity', 'N/A')} connections")

                # Retry policy
                if 'retry_policy' in config:
                    retry = config['retry_policy']
                    lines.append(f"    Retry Policy: {retry.get('max_attempts', 'N/A')} attempts, "
                               f"{retry.get('backoff_base_ms', 'N/A')}ms base backoff")

                # Timeouts
                if 'timeouts' in config:
                    timeouts = config['timeouts']
                    lines.append(f"    Timeouts: DB={timeouts.get('database_call_ms', 'N/A')}ms, "
                               f"Cache={timeouts.get('cache_call_ms', 'N/A')}ms")

                # Resources
                if 'resources' in config:
                    res = config['resources']
                    lines.append(f"    Resources: {res.get('cpu_cores', 'N/A')} CPU cores, "
                               f"{res.get('memory_mb', 'N/A')}MB memory")

            if len(nodes) > 3:
                lines.append(f"    ... and {len(nodes) - 3} more {node_type} nodes")

        lines.append("\n" + "=" * 80)
        return "\n".join(lines)
