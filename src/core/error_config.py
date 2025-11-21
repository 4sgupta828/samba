"""
Centralized error configuration for realistic distributed system simulation.

This module defines baseline error rates and amplification factors for all components.
Error rates can be tuned to simulate different reliability profiles.
"""
from dataclasses import dataclass, field
from typing import Dict
import random


@dataclass
class ComponentErrorConfig:
    """Error configuration for a specific component type."""

    # Baseline transient error rates (0.0 to 1.0)
    connection_failure_rate: float = 0.0
    timeout_rate: float = 0.0
    transient_error_rate: float = 0.0

    # Component-specific error rates
    specific_errors: Dict[str, float] = field(default_factory=dict)

    # Error amplification under stress (multipliers)
    high_cpu_multiplier: float = 1.0
    high_memory_multiplier: float = 1.0
    high_latency_multiplier: float = 1.0

    # Thresholds for stress detection
    cpu_stress_threshold: float = 80.0
    memory_stress_threshold: float = 0.8
    latency_stress_threshold: float = 100.0


@dataclass
class ErrorConfiguration:
    """Global error configuration for all component types."""

    # Enable/disable error injection globally
    enabled: bool = False

    # Baseline error rate multiplier (scales all error rates)
    global_error_multiplier: float = 1.0

    # Component-specific configurations (empty by default - load from YAML)
    database: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    cache: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    object_storage: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    compute: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    message_queue: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    network: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)
    gateway: ComponentErrorConfig = field(default_factory=ComponentErrorConfig)

    def get_config(self, component_type: str) -> ComponentErrorConfig:
        """Get error configuration for a specific component type."""
        component_type_lower = component_type.lower()

        # Map component types to config attributes
        type_mapping = {
            'sqldatabase': 'database',
            'nosqldatabase': 'database',
            'inQuerycache': 'cache',
            'objectstorage': 'object_storage',
            'computeagent': 'compute',
            'messagequeue': 'message_queue',
            'requestgateway': 'gateway',
            'networklink': 'network',
        }

        config_key = type_mapping.get(component_type_lower, None)
        if config_key:
            return getattr(self, config_key)

        # Return default config for unknown types
        return ComponentErrorConfig()

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'ErrorConfiguration':
        """Create ErrorConfiguration from a dictionary (e.g., loaded from YAML)."""
        error_config = cls()

        if 'enabled' in config_dict:
            error_config.enabled = config_dict['enabled']

        if 'global_error_multiplier' in config_dict:
            error_config.global_error_multiplier = config_dict['global_error_multiplier']

        # Load component-specific configs
        for component_type in ['database', 'cache', 'object_storage', 'compute',
                                'message_queue', 'network', 'gateway']:
            if component_type in config_dict:
                comp_config = config_dict[component_type]
                existing = getattr(error_config, component_type)

                # Update fields from config
                for field_name, value in comp_config.items():
                    if hasattr(existing, field_name):
                        setattr(existing, field_name, value)

        return error_config


class ErrorSimulator:
    """Helper class to simulate errors based on configuration and component state."""

    def __init__(self, config: ErrorConfiguration):
        self.config = config

    def should_error_occur(
        self,
        component_type: str,
        error_type: str,
        cpu_utilization: float = 0.0,
        memory_utilization: float = 0.0,
        injected_latency_ms: float = 0.0,
        error_rate_multiplier: float = 1.0
    ) -> bool:
        """
        Determine if an error should occur based on configuration and component state.

        Args:
            component_type: Type of component (e.g., 'SqlDatabase', 'ComputeAgent')
            error_type: Type of error (e.g., 'connection_failure', 'timeout', specific error name)
            cpu_utilization: Current CPU utilization percentage (0-100)
            memory_utilization: Current memory utilization ratio (0-1)
            injected_latency_ms: Current injected latency in milliseconds
            error_rate_multiplier: Deployment-triggered error rate multiplier (1.0 = normal, 3.0 = 3x errors)

        Returns:
            True if error should occur, False otherwise
        """
        if not self.config.enabled:
            return False

        comp_config = self.config.get_config(component_type)

        # Get base error rate
        if error_type == 'connection_failure':
            base_rate = comp_config.connection_failure_rate
        elif error_type == 'timeout':
            base_rate = comp_config.timeout_rate
        elif error_type == 'transient':
            base_rate = comp_config.transient_error_rate
        elif error_type in comp_config.specific_errors:
            base_rate = comp_config.specific_errors[error_type]
        else:
            return False  # Unknown error type

        # Apply global multiplier
        effective_rate = base_rate * self.config.global_error_multiplier

        # Apply deployment-triggered error rate multiplier (from buggy deployments)
        effective_rate = effective_rate * error_rate_multiplier

        # Calculate stress multiplier based on component state
        stress_multiplier = 1.0

        # CPU stress amplification
        if cpu_utilization > comp_config.cpu_stress_threshold:
            stress_multiplier *= comp_config.high_cpu_multiplier

        # Memory stress amplification
        if memory_utilization > comp_config.memory_stress_threshold:
            stress_multiplier *= comp_config.high_memory_multiplier

        # Latency stress amplification (indicates component is already struggling)
        if injected_latency_ms > comp_config.latency_stress_threshold:
            stress_multiplier *= comp_config.high_latency_multiplier

        # Apply stress multiplier
        final_rate = effective_rate * stress_multiplier

        # Cap at 50% to avoid unrealistic failure rates
        final_rate = min(final_rate, 0.5)

        # Probabilistic determination
        return random.random() < final_rate

    def get_error_message(self, component_type: str, error_type: str) -> str:
        """Get a realistic error message for the given component and error type."""

        error_messages = {
            'SqlDatabase': {
                'connection_failure': 'psycopg2.OperationalError: could not connect to server: Connection refused',
                'timeout': 'psycopg2.extensions.QueryCanceledError: canceling statement due to statement timeout',
                'lock_timeout': 'ERROR: could not obtain lock on relation - lock timeout exceeded',
                'deadlock': 'ERROR: deadlock detected',
                'statement_timeout': 'ERROR: canceling statement due to statement timeout',
                'transient': 'psycopg2.OperationalError: server closed the connection unexpectedly',
            },
            'InMemoryCache': {
                'connection_failure': 'redis.exceptions.ConnectionError: Error while reading from socket',
                'timeout': 'redis.exceptions.TimeoutError: Timeout reading from socket',
                'connection_reset': 'redis.exceptions.ConnectionError: Connection closed by server',
                'oom_error': 'redis.exceptions.ResponseError: OOM command not allowed when used memory',
                'cluster_failover': 'redis.exceptions.ClusterError: CLUSTERDOWN The cluster is down',
                'transient': 'redis.exceptions.ConnectionError: Error while reading from socket',
            },
            'ObjectStorage': {
                'connection_failure': 'botocore.exceptions.EndpointConnectionError: Could not connect to the endpoint URL',
                'timeout': 'botocore.exceptions.ReadTimeoutError: Read timeout on endpoint URL',
                'throttle_slow_down': 'S3 SlowDown: Please reduce your request rate',
                'service_unavailable': 'S3 ServiceUnavailable: Service is temporarily unavailable',
                'request_timeout': 'S3 RequestTimeout: Your socket connection to the server was not read from',
                'no_such_key': 'S3 NoSuchKey: The specified key does not exist',
                'eventual_consistency': 'S3 read returned stale data (eventual consistency)',
                'transient': 'botocore.exceptions.ClientError: An error occurred',
            },
            'ComputeAgent': {
                'connection_failure': 'requests.exceptions.ConnectionError: Failed to establish a new connection',
                'timeout': 'requests.exceptions.Timeout: Request timed out',
                'http_client_timeout': 'HTTPConnectionPool: Read timed out',
                'parsing_error': 'json.JSONDecodeError: Expecting value',
                'disk_io_error': 'OSError: [Errno 5] Input/output error',
                'transient': 'Exception: Unexpected error during request processing',
            },
            'MessageQueue': {
                'connection_failure': 'ConnectionError: Unable to connect to message queue',
                'timeout': 'TimeoutError: ReceiveMessage operation timed out',
                'receive_throttle': 'ThrottlingException: Rate exceeded for ReceiveMessage',
                'message_too_large': 'InvalidParameterValue: Message size exceeds 256KB limit',
                'visibility_timeout_conflict': 'ReceiptHandleIsInvalid: Message already being processed',
                'transient': 'ServiceError: Temporary failure receiving message',
            },
            'NetworkLink': {
                'connection_failure': 'ConnectionRefusedError: [Errno 111] Connection refused',
                'timeout': 'TimeoutError: [Errno 110] Connection timed out',
                'packet_loss': 'Network packet loss detected, retransmitting',
                'connection_reset': 'ConnectionResetError: [Errno 104] Connection reset by peer',
                'dns_failure': 'socket.gaierror: [Errno -2] Name or service not known',
                'tls_handshake_failure': 'ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]',
                'transient': 'OSError: Network is unreachable',
            },
            'RequestGateway': {
                'connection_failure': 'ConnectionError: Failed to connect to backend',
                'timeout': 'TimeoutError: Gateway timeout waiting for backend',
                'rate_limit_exceeded': 'HTTP 429: Too Many Requests',
                'invalid_request': 'HTTP 400: Bad Request',
                'transient': 'HTTP 502: Bad Gateway',
            },
        }

        # Get component-specific messages
        comp_messages = error_messages.get(component_type, {})
        return comp_messages.get(error_type, f'{component_type} error: {error_type}')


# Global error configuration instance (loaded from config at runtime)
_global_error_config: ErrorConfiguration = ErrorConfiguration()
_global_error_simulator: ErrorSimulator = ErrorSimulator(_global_error_config)


def get_error_config() -> ErrorConfiguration:
    """Get the global error configuration."""
    return _global_error_config


def get_error_simulator() -> ErrorSimulator:
    """Get the global error simulator."""
    return _global_error_simulator


def set_error_config(config: ErrorConfiguration):
    """Set the global error configuration."""
    global _global_error_config, _global_error_simulator
    _global_error_config = config
    _global_error_simulator = ErrorSimulator(config)
