"""
Centralized simulation configuration loader.

This module provides a simple interface to load and access all simulation
parameters from the centralized simulation_config.yaml file.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
import yaml
from pathlib import Path


@dataclass
class GlobalConfig:
    """Global simulation settings."""
    time_acceleration: float = 1.0
    random_seed: Optional[int] = None


@dataclass
class TelemetryConfig:
    """Telemetry and observability settings."""
    trace_sampling_rate: float = 0.01
    trace_sampling_rate_errors: float = 0.1
    metric_export_interval_seconds: float = 10.0
    metric_flush_interval_seconds: float = 5.0
    min_log_level: str = "INFO"
    log_throttle_window_seconds: float = 10.0
    log_throttle_cleanup_threshold_seconds: float = 60.0


@dataclass
class HealthCheckConfig:
    """Health check configuration."""
    protocol: str = "HTTP"
    port: int = 80
    path: str = "/"
    interval_seconds: int = 30
    timeout_seconds: int = 5
    healthy_threshold: int = 2
    unhealthy_threshold: int = 2


@dataclass
class RetryConfig:
    """Retry logic configuration."""
    max_attempts: int = 3
    backoff_base_seconds: float = 0.1
    backoff_jitter_range_seconds: List[float] = field(default_factory=lambda: [0.01, 0.05])


@dataclass
class DefaultsConfig:
    """Default settings that apply to all components."""
    sample_window_seconds: float = 5.0
    cpu_sampling_interval_seconds: float = 1.0
    healthcheck: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass
class TimeoutsConfig:
    """Client-side timeout configuration for ComputeAgent calls."""
    database_call_seconds: float = 5.0
    cache_call_seconds: float = 1.0
    external_api_seconds: float = 10.0


@dataclass
class ContentionConfig:
    """Node-level resource contention configuration (Noisy Neighbor)."""
    cpu_threshold: float = 0.90  # CPU utilization threshold for contention (90%)
    base_penalty_ms: float = 10.0  # Base penalty at threshold
    sensitivity: float = 10.0  # Exponential sensitivity factor


@dataclass
class ComputeConfig:
    """Compute component configuration."""
    # Resource capacities
    memory_base_mb: float = 200.0
    memory_capacity_mb: float = 512.0
    cpu_capacity_cores: float = 1.0
    db_connection_pool_capacity: int = 20

    # Node-level contention
    contention: ContentionConfig = field(default_factory=ContentionConfig)

    # Client-side timeouts
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)

    # Startup
    startup_time_range_seconds: List[float] = field(default_factory=lambda: [5, 15])
    startup_backoff_delay_base_seconds: float = 10.0
    startup_backoff_jitter_range_seconds: List[float] = field(default_factory=lambda: [-2, 5])
    startup_max_backoff_seconds: float = 300.0

    # Memory pressure
    memory_pressure_thresholds_mb: List[float] = field(default_factory=lambda: [300, 400, 500])
    memory_pressure_delays_severe_seconds: List[float] = field(default_factory=lambda: [0.25, 0.35])
    memory_pressure_delays_moderate_seconds: List[float] = field(default_factory=lambda: [0.15, 0.25])
    memory_pressure_delays_minor_seconds: List[float] = field(default_factory=lambda: [0.05, 0.15])
    memory_pressure_cpu_severe_percent: List[float] = field(default_factory=lambda: [85.0, 98.0])
    memory_pressure_cpu_moderate_percent: List[float] = field(default_factory=lambda: [60.0, 80.0])
    memory_pressure_cpu_minor_percent: List[float] = field(default_factory=lambda: [40.0, 60.0])

    # OOM
    oom_check_interval_seconds: float = 0.5

    # Request profiles
    request_read_profile_time_mean_seconds: float = 0.05
    request_read_profile_time_stdev_seconds: float = 0.01
    request_read_profile_cpu_spike_range_percent: List[float] = field(default_factory=lambda: [10, 20])

    request_update_profile_time_mean_seconds: float = 0.1
    request_update_profile_time_stdev_seconds: float = 0.03
    request_update_profile_cpu_range_percent: List[float] = field(default_factory=lambda: [30, 50])

    request_generate_report_time_mean_seconds: float = 0.5
    request_generate_report_time_stdev_seconds: float = 0.1
    request_generate_report_cpu_range_percent: List[float] = field(default_factory=lambda: [70, 90])

    request_default_time_mean_seconds: float = 0.05
    request_default_time_stdev_seconds: float = 0.01
    request_default_cpu_spike_range_percent: List[float] = field(default_factory=lambda: [10, 20])

    # Cache interaction
    cache_user_id_range: List[int] = field(default_factory=lambda: [1, 100])
    cache_processing_time_range_seconds: List[float] = field(default_factory=lambda: [0.01, 0.02])

    # Database interaction
    db_max_retries: int = 3
    db_retry_backoff_base_seconds: float = 0.1
    db_retry_backoff_jitter_range_seconds: List[float] = field(default_factory=lambda: [0.01, 0.05])

    # CPU behavior
    cpu_idle_level_percent: float = 5.0
    cpu_processing_range_percent: List[float] = field(default_factory=lambda: [20, 40])
    cpu_additional_work_time_mean_seconds: float = 0.08
    cpu_additional_work_time_stdev_seconds: float = 0.02

    # Autoscaling
    autoscaling_cooldown_seconds: int = 300
    autoscaling_target_metric: str = "cpu_utilization"
    autoscaling_target_value: float = 70.0


@dataclass
class DatabaseConfig:
    """Database component configuration."""
    # Resources
    connection_pool_capacity: int = 100
    cpu_cores: int = 4
    cpu_capacity_cores: float = 4.0
    memory_capacity_mb: float = 1024.0

    # Initial state
    initial_wear_factor: float = 0.0

    # Query performance
    query_base_time_mean_seconds: float = 0.02
    query_base_time_stdev_seconds: float = 0.005
    query_cpu_usage_cores: float = 0.7
    query_degradation_latency_factor: float = 0.1

    # Wear
    wear_enabled: bool = False
    wear_query_increment: float = 0.01

    # Background jobs
    background_jobs_enabled: bool = True
    background_jobs_interval_range_seconds: List[float] = field(default_factory=lambda: [600, 1200])
    background_jobs_duration_range_seconds: List[float] = field(default_factory=lambda: [20, 40])
    background_jobs_cpu_cores_used: float = 1.8


@dataclass
class NetworkConfig:
    """Network component configuration."""
    base_latency_ms: float = 1.0
    latency_jitter_ms: float = 0.2
    bandwidth_mbps: float = 1000.0
    latency_minimum_ms: float = 0.1

    # TCP
    tcp_handshake_time_multiplier: int = 3
    tcp_handshake_minimum_ms: float = 1.0

    # Packet loss
    packet_loss_latency_multiplier: int = 2


@dataclass
class ObjectStorageConfig:
    """Object storage configuration."""
    latency_mean_ms: float = 20.0
    latency_stdev_ms: float = 5.0


@dataclass
class InMemoryCacheConfig:
    """In-memory cache configuration."""
    max_size_items: int = 1000
    latency_mean_ms: float = 2.0
    latency_stdev_ms: float = 0.5
    hit_rate_window_seconds: float = 10.0


@dataclass
class StorageConfig:
    """Storage components configuration."""
    object_storage: ObjectStorageConfig = field(default_factory=ObjectStorageConfig)
    inmemory_cache: InMemoryCacheConfig = field(default_factory=InMemoryCacheConfig)


@dataclass
class MessageQueueConfig:
    """Message queue configuration."""
    visibility_timeout_seconds: int = 60
    metrics_sampling_interval_seconds: float = 1.0


@dataclass
class MessagingConfig:
    """Messaging components configuration."""
    message_queue: MessageQueueConfig = field(default_factory=MessageQueueConfig)


@dataclass
class FaultInjectionConfig:
    """Fault injection configuration."""
    default_injected_latency_ms: float = 0.0
    default_forced_error_rate: float = 0.0


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration for workload generator."""
    enabled: bool = True
    failure_threshold: float = 0.7
    success_threshold: float = 0.8
    window_size: int = 50
    open_duration_seconds: float = 15.0
    half_open_max_requests: int = 10


@dataclass
class WorkloadGeneratorConfig:
    """Workload generator configuration (realistic client behavior)."""
    connection_pool_size: int = 50
    request_timeout_seconds: float = 30.0
    max_queue_size: int = 100
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


@dataclass
class SimulationConfig:
    """
    Centralized simulation configuration.

    Loads all simulation parameters from simulation_config.yaml and provides
    easy access to component-specific configurations.
    """
    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    compute: ComputeConfig = field(default_factory=ComputeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    messaging: MessagingConfig = field(default_factory=MessagingConfig)
    fault_injection: FaultInjectionConfig = field(default_factory=FaultInjectionConfig)
    workload_generator: WorkloadGeneratorConfig = field(default_factory=WorkloadGeneratorConfig)
    dynamics: Dict[str, Any] = field(default_factory=dict)  # Phase 2: Dynamics engine config

    @classmethod
    def load(cls, config_path: str = "config/simulation_config.yaml") -> "SimulationConfig":
        """
        Load simulation configuration from YAML file.

        Args:
            config_path: Path to simulation_config.yaml (relative to project root)

        Returns:
            SimulationConfig instance with all parameters loaded
        """
        # Resolve path relative to project root
        # __file__ is src/core/simulation_config.py, so parent.parent.parent gets us to root
        project_root = Path(__file__).parent.parent.parent
        full_path = project_root / config_path

        if not full_path.exists():
            raise FileNotFoundError(f"Simulation config not found: {full_path}")

        with open(full_path, 'r') as f:
            data = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "SimulationConfig":
        """Parse YAML data into structured config objects."""

        # Global
        global_config = GlobalConfig(
            time_acceleration=data.get('global', {}).get('time_acceleration', 1.0),
            random_seed=data.get('global', {}).get('random_seed')
        )

        # Telemetry
        telem_data = data.get('telemetry', {})
        telemetry = TelemetryConfig(
            trace_sampling_rate=telem_data.get('trace_sampling_rate', 0.01),
            trace_sampling_rate_errors=telem_data.get('trace_sampling_rate_errors', 0.1),
            metric_export_interval_seconds=telem_data.get('metric_export_interval_seconds', 10.0),
            metric_flush_interval_seconds=telem_data.get('metric_flush_interval_seconds', 5.0),
            min_log_level=telem_data.get('min_log_level', 'INFO'),
            log_throttle_window_seconds=telem_data.get('log_throttle_window_seconds', 10.0),
            log_throttle_cleanup_threshold_seconds=telem_data.get('log_throttle_cleanup_threshold_seconds', 60.0)
        )

        # Defaults
        defaults_data = data.get('defaults', {})
        hc_data = defaults_data.get('healthcheck', {})
        retry_data = defaults_data.get('retry', {})

        defaults = DefaultsConfig(
            sample_window_seconds=defaults_data.get('sample_window_seconds', 5.0),
            cpu_sampling_interval_seconds=defaults_data.get('cpu_sampling_interval_seconds', 1.0),
            healthcheck=HealthCheckConfig(
                protocol=hc_data.get('protocol', 'HTTP'),
                port=hc_data.get('port', 80),
                path=hc_data.get('path', '/'),
                interval_seconds=hc_data.get('interval_seconds', 30),
                timeout_seconds=hc_data.get('timeout_seconds', 5),
                healthy_threshold=hc_data.get('healthy_threshold', 2),
                unhealthy_threshold=hc_data.get('unhealthy_threshold', 2)
            ),
            retry=RetryConfig(
                max_attempts=retry_data.get('max_attempts', 3),
                backoff_base_seconds=retry_data.get('backoff_base_seconds', 0.1),
                backoff_jitter_range_seconds=retry_data.get('backoff_jitter_range_seconds', [0.01, 0.05])
            )
        )

        # Compute
        compute_data = data.get('compute', {})

        # Parse contention
        contention_data = compute_data.get('contention', {})
        contention = ContentionConfig(
            cpu_threshold=contention_data.get('cpu_threshold', 0.90),
            base_penalty_ms=contention_data.get('base_penalty_ms', 10.0),
            sensitivity=contention_data.get('sensitivity', 10.0)
        )

        # Parse timeouts
        timeouts_data = compute_data.get('timeouts', {})
        timeouts = TimeoutsConfig(
            database_call_seconds=timeouts_data.get('database_call_seconds', 5.0),
            cache_call_seconds=timeouts_data.get('cache_call_seconds', 1.0),
            external_api_seconds=timeouts_data.get('external_api_seconds', 10.0)
        )

        compute = ComputeConfig(
            memory_base_mb=compute_data.get('resources', {}).get('memory_base_mb', 200.0),
            memory_capacity_mb=compute_data.get('resources', {}).get('memory_capacity_mb', 512.0),
            cpu_capacity_cores=compute_data.get('resources', {}).get('cpu_capacity_cores', 1.0),
            db_connection_pool_capacity=compute_data.get('resources', {}).get('db_connection_pool_capacity', 20),

            contention=contention,
            timeouts=timeouts,

            startup_time_range_seconds=compute_data.get('startup', {}).get('time_range_seconds', [5, 15]),
            startup_backoff_delay_base_seconds=compute_data.get('startup', {}).get('backoff_delay_base_seconds', 10.0),
            startup_backoff_jitter_range_seconds=compute_data.get('startup', {}).get('backoff_jitter_range_seconds', [-2, 5]),
            startup_max_backoff_seconds=compute_data.get('startup', {}).get('max_backoff_seconds', 300.0),

            memory_pressure_thresholds_mb=compute_data.get('memory_pressure', {}).get('thresholds_mb', [300, 400, 500]),
            memory_pressure_delays_severe_seconds=compute_data.get('memory_pressure', {}).get('delays_seconds', {}).get('severe', [0.25, 0.35]),
            memory_pressure_delays_moderate_seconds=compute_data.get('memory_pressure', {}).get('delays_seconds', {}).get('moderate', [0.15, 0.25]),
            memory_pressure_delays_minor_seconds=compute_data.get('memory_pressure', {}).get('delays_seconds', {}).get('minor', [0.05, 0.15]),
            memory_pressure_cpu_severe_percent=compute_data.get('memory_pressure', {}).get('cpu_impact_percent', {}).get('severe', [85.0, 98.0]),
            memory_pressure_cpu_moderate_percent=compute_data.get('memory_pressure', {}).get('cpu_impact_percent', {}).get('moderate', [60.0, 80.0]),
            memory_pressure_cpu_minor_percent=compute_data.get('memory_pressure', {}).get('cpu_impact_percent', {}).get('minor', [40.0, 60.0]),

            oom_check_interval_seconds=compute_data.get('oom', {}).get('check_interval_seconds', 0.5),

            request_read_profile_time_mean_seconds=compute_data.get('request_profiles', {}).get('read_profile', {}).get('processing_time_mean_seconds', 0.05),
            request_read_profile_time_stdev_seconds=compute_data.get('request_profiles', {}).get('read_profile', {}).get('processing_time_stdev_seconds', 0.01),
            request_read_profile_cpu_spike_range_percent=compute_data.get('request_profiles', {}).get('read_profile', {}).get('cpu_spike_range_percent', [10, 20]),

            request_update_profile_time_mean_seconds=compute_data.get('request_profiles', {}).get('update_profile', {}).get('processing_time_mean_seconds', 0.1),
            request_update_profile_time_stdev_seconds=compute_data.get('request_profiles', {}).get('update_profile', {}).get('processing_time_stdev_seconds', 0.03),
            request_update_profile_cpu_range_percent=compute_data.get('request_profiles', {}).get('update_profile', {}).get('cpu_usage_range_percent', [30, 50]),

            request_generate_report_time_mean_seconds=compute_data.get('request_profiles', {}).get('generate_report', {}).get('processing_time_mean_seconds', 0.5),
            request_generate_report_time_stdev_seconds=compute_data.get('request_profiles', {}).get('generate_report', {}).get('processing_time_stdev_seconds', 0.1),
            request_generate_report_cpu_range_percent=compute_data.get('request_profiles', {}).get('generate_report', {}).get('cpu_usage_range_percent', [70, 90]),

            request_default_time_mean_seconds=compute_data.get('request_profiles', {}).get('default', {}).get('processing_time_mean_seconds', 0.05),
            request_default_time_stdev_seconds=compute_data.get('request_profiles', {}).get('default', {}).get('processing_time_stdev_seconds', 0.01),
            request_default_cpu_spike_range_percent=compute_data.get('request_profiles', {}).get('default', {}).get('cpu_spike_range_percent', [10, 20]),

            cache_user_id_range=compute_data.get('cache', {}).get('user_id_range', [1, 100]),
            cache_processing_time_range_seconds=compute_data.get('cache', {}).get('processing_time_range_seconds', [0.01, 0.02]),

            db_max_retries=compute_data.get('database', {}).get('max_retries', 3),
            db_retry_backoff_base_seconds=compute_data.get('database', {}).get('retry_backoff_base_seconds', 0.1),
            db_retry_backoff_jitter_range_seconds=compute_data.get('database', {}).get('retry_backoff_jitter_range_seconds', [0.01, 0.05]),

            cpu_idle_level_percent=compute_data.get('cpu', {}).get('idle_level_percent', 5.0),
            cpu_processing_range_percent=compute_data.get('cpu', {}).get('processing_range_percent', [20, 40]),
            cpu_additional_work_time_mean_seconds=compute_data.get('cpu', {}).get('additional_work_time_mean_seconds', 0.08),
            cpu_additional_work_time_stdev_seconds=compute_data.get('cpu', {}).get('additional_work_time_stdev_seconds', 0.02),

            autoscaling_cooldown_seconds=compute_data.get('autoscaling', {}).get('cooldown_seconds', 300),
            autoscaling_target_metric=compute_data.get('autoscaling', {}).get('target_metric', 'cpu_utilization'),
            autoscaling_target_value=compute_data.get('autoscaling', {}).get('target_value', 70.0)
        )

        # Database
        db_data = data.get('database', {})
        database = DatabaseConfig(
            connection_pool_capacity=db_data.get('resources', {}).get('connection_pool_capacity', 100),
            cpu_cores=db_data.get('resources', {}).get('cpu_cores', 4),
            cpu_capacity_cores=db_data.get('resources', {}).get('cpu_capacity_cores', 4.0),
            memory_capacity_mb=db_data.get('resources', {}).get('memory_capacity_mb', 1024.0),

            initial_wear_factor=db_data.get('initial_state', {}).get('wear_factor', 0.0),

            query_base_time_mean_seconds=db_data.get('query_performance', {}).get('base_query_time_mean_seconds', 0.02),
            query_base_time_stdev_seconds=db_data.get('query_performance', {}).get('base_query_time_stdev_seconds', 0.005),
            query_cpu_usage_cores=db_data.get('query_performance', {}).get('cpu_usage_per_query_cores', 0.7),
            query_degradation_latency_factor=db_data.get('query_performance', {}).get('degradation_latency_factor', 0.1),

            wear_enabled=db_data.get('wear', {}).get('enabled', False),
            wear_query_increment=db_data.get('wear', {}).get('query_wear_increment', 0.01),

            background_jobs_enabled=db_data.get('background_jobs', {}).get('enabled', True),
            background_jobs_interval_range_seconds=db_data.get('background_jobs', {}).get('interval_range_seconds', [600, 1200]),
            background_jobs_duration_range_seconds=db_data.get('background_jobs', {}).get('duration_range_seconds', [20, 40]),
            background_jobs_cpu_cores_used=db_data.get('background_jobs', {}).get('cpu_cores_used', 1.8)
        )

        # Network
        net_data = data.get('network', {})
        network = NetworkConfig(
            base_latency_ms=net_data.get('base_latency_ms', 1.0),
            latency_jitter_ms=net_data.get('latency_jitter_ms', 0.2),
            bandwidth_mbps=net_data.get('bandwidth_mbps', 1000.0),
            latency_minimum_ms=net_data.get('latency_minimum_ms', 0.1),

            tcp_handshake_time_multiplier=net_data.get('tcp', {}).get('handshake_time_multiplier', 3),
            tcp_handshake_minimum_ms=net_data.get('tcp', {}).get('handshake_minimum_ms', 1.0),

            packet_loss_latency_multiplier=net_data.get('packet_loss', {}).get('latency_multiplier', 2)
        )

        # Storage
        storage_data = data.get('storage', {})
        storage = StorageConfig(
            object_storage=ObjectStorageConfig(
                latency_mean_ms=storage_data.get('object_storage', {}).get('latency_mean_ms', 20.0),
                latency_stdev_ms=storage_data.get('object_storage', {}).get('latency_stdev_ms', 5.0)
            ),
            inmemory_cache=InMemoryCacheConfig(
                max_size_items=storage_data.get('inmemory_cache', {}).get('max_size_items', 1000),
                latency_mean_ms=storage_data.get('inmemory_cache', {}).get('latency_mean_ms', 2.0),
                latency_stdev_ms=storage_data.get('inmemory_cache', {}).get('latency_stdev_ms', 0.5),
                hit_rate_window_seconds=storage_data.get('inmemory_cache', {}).get('hit_rate_window_seconds', 10.0)
            )
        )

        # Messaging
        messaging_data = data.get('messaging', {})
        messaging = MessagingConfig(
            message_queue=MessageQueueConfig(
                visibility_timeout_seconds=messaging_data.get('message_queue', {}).get('visibility_timeout_seconds', 60),
                metrics_sampling_interval_seconds=messaging_data.get('message_queue', {}).get('metrics_sampling_interval_seconds', 1.0)
            )
        )

        # Fault injection
        fault_data = data.get('fault_injection', {})
        fault_injection = FaultInjectionConfig(
            default_injected_latency_ms=fault_data.get('default_injected_latency_ms', 0.0),
            default_forced_error_rate=fault_data.get('default_forced_error_rate', 0.0)
        )

        # Workload generator
        wg_data = data.get('workload_generator', {})
        cb_data = wg_data.get('circuit_breaker', {})
        workload_generator = WorkloadGeneratorConfig(
            connection_pool_size=wg_data.get('connection_pool_size', 50),
            request_timeout_seconds=wg_data.get('request_timeout_seconds', 30.0),
            max_queue_size=wg_data.get('max_queue_size', 100),
            circuit_breaker=CircuitBreakerConfig(
                enabled=cb_data.get('enabled', True),
                failure_threshold=cb_data.get('failure_threshold', 0.7),
                success_threshold=cb_data.get('success_threshold', 0.8),
                window_size=cb_data.get('window_size', 50),
                open_duration_seconds=cb_data.get('open_duration_seconds', 15.0),
                half_open_max_requests=cb_data.get('half_open_max_requests', 10)
            )
        )

        # Dynamics engine (Phase 2)
        dynamics = data.get('dynamics', {})

        return cls(
            global_config=global_config,
            telemetry=telemetry,
            defaults=defaults,
            compute=compute,
            database=database,
            network=network,
            storage=storage,
            messaging=messaging,
            fault_injection=fault_injection,
            workload_generator=workload_generator,
            dynamics=dynamics
        )


# Singleton instance for easy access throughout the application
_sim_config: Optional[SimulationConfig] = None


def get_simulation_config() -> SimulationConfig:
    """
    Get the global simulation configuration instance.
    Loads the config on first access.
    """
    global _sim_config
    if _sim_config is None:
        _sim_config = SimulationConfig.load()
    return _sim_config


def reload_simulation_config(config_path: str = "config/simulation_config.yaml") -> SimulationConfig:
    """
    Force reload of the simulation configuration.
    Useful for testing or if config changes during runtime.
    """
    global _sim_config
    _sim_config = SimulationConfig.load(config_path)
    return _sim_config
