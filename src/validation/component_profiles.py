"""
Component Performance Profiles

Real-world performance characteristics for different component types.
Based on industry benchmarks and production data.

Sources:
- AWS DynamoDB: 1-5ms single-item reads
- Redis: 0.1-2ms for cache operations
- PostgreSQL: 1-10ms for simple queries, 10-100ms for complex
- REST APIs: 20-100ms (internal), 100-500ms (external)
- Message Queues: 1-5ms publish, 5-50ms processing
"""
from dataclasses import dataclass
from typing import Dict, Tuple
from enum import Enum


class ComponentType(Enum):
    """Types of components in the system."""
    GATEWAY = "gateway"
    SERVICE = "service"
    DATABASE = "database"
    CACHE = "cache"
    QUEUE = "queue"
    EXTERNAL = "external"


@dataclass
class LatencyProfile:
    """
    Latency profile for a component type.

    All values in milliseconds.
    Represents PROCESSING TIME only (not including network/dependencies).
    """
    # Base processing time (median/p50)
    p50: float

    # 90th percentile (typical high load)
    p90: float

    # 99th percentile (tail latency)
    p99: float

    # Maximum observed latency (outliers)
    max: float

    # Service rate (requests per second this component can handle)
    # Calculated as: 1 / processing_time_seconds
    max_rps: float

    # Description
    description: str


@dataclass
class ResourceProfile:
    """
    Resource requirements for a component type.
    """
    # CPU per request (milliseconds of CPU time)
    cpu_ms_per_request: float

    # Memory per concurrent request (MB)
    memory_mb_per_request: float

    # Max concurrent requests before degradation
    max_concurrent: int

    # Connection pool size (for clients)
    connection_pool_size: int


# ============================================================================
# Component Profiles Based on Real-World Data
# ============================================================================

COMPONENT_LATENCY_PROFILES: Dict[ComponentType, LatencyProfile] = {
    # Gateway: Load balancer / API gateway
    # Examples: AWS ALB, NGINX, Envoy
    # Primarily routing, minimal processing
    ComponentType.GATEWAY: LatencyProfile(
        p50=2.0,      # Fast routing
        p90=5.0,      # Some queuing
        p99=10.0,     # Heavy load
        max=50.0,     # Pathological cases
        max_rps=10000,  # Modern load balancers handle 10k+ RPS
        description="API Gateway / Load Balancer"
    ),

    # Service: Business logic tier
    # Examples: Node.js/Python/Go microservices
    # Includes processing, serialization, validation
    ComponentType.SERVICE: LatencyProfile(
        p50=20.0,     # Typical REST endpoint
        p90=50.0,     # With some DB calls
        p99=100.0,    # Including retries/fallbacks
        max=500.0,    # Timeout scenarios
        max_rps=500,  # Typical service: 500 RPS per instance
        description="Microservice (Business Logic)"
    ),

    # Database: Persistent storage
    # Examples: PostgreSQL, MySQL, DynamoDB
    # Single-item reads/writes, indexed queries
    ComponentType.DATABASE: LatencyProfile(
        p50=5.0,      # Indexed query, hot cache
        p90=15.0,     # Cold cache, simple JOIN
        p99=50.0,     # Complex query, lock contention
        max=200.0,    # Full table scan, deadlock recovery
        max_rps=5000, # Modern DB: 5k simple queries/sec
        description="Database (SQL/NoSQL)"
    ),

    # Cache: In-memory key-value store
    # Examples: Redis, Memcached
    # GET/SET operations on hot keys
    ComponentType.CACHE: LatencyProfile(
        p50=1.0,      # In-memory lookup
        p90=2.0,      # Network overhead
        p99=5.0,      # Eviction happening
        max=20.0,     # Memory pressure / resharding
        max_rps=50000, # Redis: 50k+ ops/sec single instance
        description="In-Memory Cache (Redis/Memcached)"
    ),

    # Queue: Asynchronous message broker
    # Examples: RabbitMQ, Kafka, SQS
    # Publish and consume operations
    ComponentType.QUEUE: LatencyProfile(
        p50=5.0,      # Fast publish (in-memory queue)
        p90=15.0,     # Persist to disk
        p99=50.0,     # Replication lag
        max=200.0,    # Queue full, backpressure
        max_rps=10000, # Kafka: 10k+ messages/sec
        description="Message Queue (Kafka/RabbitMQ/SQS)"
    ),

    # External: Third-party APIs
    # Examples: Payment gateways, Auth providers, External services
    # Over internet, out of our control
    ComponentType.EXTERNAL: LatencyProfile(
        p50=100.0,    # Good external API
        p90=200.0,    # Typical variability
        p99=500.0,    # Rate limiting / retries
        max=2000.0,   # Timeout / circuit breaker
        max_rps=100,  # Rate limited by provider
        description="External Third-Party API"
    ),
}


COMPONENT_RESOURCE_PROFILES: Dict[ComponentType, ResourceProfile] = {
    ComponentType.GATEWAY: ResourceProfile(
        cpu_ms_per_request=0.5,   # Minimal CPU (just routing)
        memory_mb_per_request=0.1, # Minimal memory
        max_concurrent=10000,      # Very high concurrency
        connection_pool_size=1000,
    ),

    ComponentType.SERVICE: ResourceProfile(
        cpu_ms_per_request=5.0,    # Business logic processing
        memory_mb_per_request=2.0,  # Request context, buffers
        max_concurrent=500,         # Typical async runtime
        connection_pool_size=100,   # Connection to downstream
    ),

    ComponentType.DATABASE: ResourceProfile(
        cpu_ms_per_request=2.0,    # Query parsing, execution
        memory_mb_per_request=1.0,  # Query buffers
        max_concurrent=1000,        # High connection pool
        connection_pool_size=500,   # Client-side pool
    ),

    ComponentType.CACHE: ResourceProfile(
        cpu_ms_per_request=0.2,    # Hash lookup
        memory_mb_per_request=0.5,  # Key-value pair
        max_concurrent=10000,       # Very high concurrency
        connection_pool_size=200,
    ),

    ComponentType.QUEUE: ResourceProfile(
        cpu_ms_per_request=1.0,    # Serialize/publish
        memory_mb_per_request=1.0,  # Message buffer
        max_concurrent=5000,
        connection_pool_size=100,
    ),

    ComponentType.EXTERNAL: ResourceProfile(
        cpu_ms_per_request=1.0,    # HTTP serialization
        memory_mb_per_request=2.0,  # HTTP buffers
        max_concurrent=100,         # Rate limited
        connection_pool_size=50,    # Small pool (rate limited)
    ),
}


# ============================================================================
# Network Latency Profiles
# ============================================================================

@dataclass
class NetworkLatency:
    """Network latency between components."""
    p50: float
    p90: float
    p99: float
    description: str


NETWORK_LATENCIES = {
    # Same availability zone (local network)
    'local': NetworkLatency(
        p50=1.0,
        p90=2.0,
        p99=5.0,
        description="Same AZ / Local Network"
    ),

    # Cross-AZ within same region
    'cross_az': NetworkLatency(
        p50=2.0,
        p90=5.0,
        p99=10.0,
        description="Cross-AZ within Region"
    ),

    # Cross-region
    'cross_region': NetworkLatency(
        p50=50.0,
        p90=100.0,
        p99=200.0,
        description="Cross-Region"
    ),

    # Internet (external)
    'internet': NetworkLatency(
        p50=20.0,
        p90=50.0,
        p99=100.0,
        description="Public Internet"
    ),
}


def get_component_profile(component_role: str) -> Tuple[LatencyProfile, ResourceProfile]:
    """
    Get latency and resource profiles for a component.

    Args:
        component_role: Role string (e.g., 'service', 'database', 'cache')

    Returns:
        (LatencyProfile, ResourceProfile)
    """
    try:
        comp_type = ComponentType(component_role.lower())
        return (
            COMPONENT_LATENCY_PROFILES[comp_type],
            COMPONENT_RESOURCE_PROFILES[comp_type]
        )
    except (ValueError, KeyError):
        # Default to service profile if unknown
        return (
            COMPONENT_LATENCY_PROFILES[ComponentType.SERVICE],
            COMPONENT_RESOURCE_PROFILES[ComponentType.SERVICE]
        )


def get_network_latency(edge_type: str) -> NetworkLatency:
    """
    Get network latency for an edge type.

    Args:
        edge_type: Type of connection (e.g., 'sync_http', 'sync_db', 'sync_external')

    Returns:
        NetworkLatency profile
    """
    if 'external' in edge_type:
        return NETWORK_LATENCIES['internet']
    elif 'cross_az' in edge_type or 'cross-az' in edge_type:
        return NETWORK_LATENCIES['cross_az']
    else:
        return NETWORK_LATENCIES['local']


def calculate_end_to_end_latency(
    path_components: list,
    percentile: str = 'p50'
) -> float:
    """
    Calculate end-to-end latency for a path through the system.

    Args:
        path_components: List of (component_role, edge_type) tuples
        percentile: Which percentile to calculate ('p50', 'p90', 'p99')

    Returns:
        Total latency in milliseconds

    Example:
        path = [
            ('gateway', 'sync_http'),
            ('service', 'sync_db'),
            ('database', None)
        ]
        latency = calculate_end_to_end_latency(path, 'p99')
    """
    total_latency = 0.0

    for i, (role, edge_type) in enumerate(path_components):
        # Add processing time for this component
        latency_profile, _ = get_component_profile(role)
        total_latency += getattr(latency_profile, percentile)

        # Add network latency to next hop (if not last component)
        if edge_type and i < len(path_components) - 1:
            network = get_network_latency(edge_type)
            total_latency += getattr(network, percentile)

    return total_latency


def estimate_component_capacity(
    component_role: str,
    num_replicas: int = 1,
    thread_pool_size: int = None,
    db_connection_pool_size: int = None,
    service_pipeline: list = None,
    cache_hit_rate: float = 0.7
) -> Dict[str, float]:
    """
    Estimate capacity for a component based on its profile AND resource constraints.

    This function properly accounts for:
    1. Processing time limits (base throughput)
    2. Thread pool limits (concurrency constraint)
    3. DB connection pool limits (resource constraint with actual DB latency)

    NOTE: Workload generator connection pool is NOT a constraint on topology capacity.
    It should be sized to support the topology's capacity, not limit it.

    Args:
        component_role: Component type (service, database, cache, etc.)
        num_replicas: Number of replicas
        thread_pool_size: Thread pool size per replica
        db_connection_pool_size: DB connection pool size per replica
        service_pipeline: Processing pipeline steps (to determine DB usage)
        cache_hit_rate: Cache hit rate (default 0.7 = 70%)

    Returns:
        {
            'max_rps': Maximum requests per second (constrained by topology resources),
            'target_rps': Target RPS (70% of max for headroom),
            'max_concurrent': Maximum concurrent requests,
            'processing_time_p50': Processing time in seconds (p50),
            'limiting_factor': Which constraint is the bottleneck,
            'thread_pool_limited_rps': Capacity limited by thread pool (if applicable),
            'db_pool_limited_rps': Capacity limited by DB connection pool (if applicable),
            'processing_limited_rps': Capacity limited by processing time
        }
    """
    latency_profile, resource_profile = get_component_profile(component_role)

    # === Constraint 1: Processing Time Limit ===
    # Service rate = 1 / processing_time (original logic)
    processing_time_sec = latency_profile.p50 / 1000.0
    processing_limited_rps = (1.0 / processing_time_sec if processing_time_sec > 0 else float('inf')) * num_replicas

    # === Constraint 2: Thread Pool Limit ===
    # Using Little's Law: Capacity = Concurrency / Latency
    # If we have N threads and latency L, max throughput = N / L
    thread_pool_limited_rps = None
    if thread_pool_size is not None:
        # Total threads across all replicas
        total_threads = thread_pool_size * num_replicas
        # Max RPS = threads / latency
        thread_pool_limited_rps = total_threads / processing_time_sec if processing_time_sec > 0 else float('inf')

    # === Constraint 3: DB Connection Pool Limit ===
    # Use ACTUAL DB latency from component profiles, not a hardcoded fraction
    db_pool_limited_rps = None
    if db_connection_pool_size is not None and component_role == 'service':
        # Check if this service's pipeline uses database
        has_db_query = False
        if service_pipeline:
            has_db_query = any(step.get('type') == 'db_query' for step in service_pipeline)

        if has_db_query:
            # Get actual DB latency from component profiles
            db_latency_profile, _ = get_component_profile('database')
            db_query_time_sec = db_latency_profile.p50 / 1000.0

            # Account for cache hit rate (if cache is in pipeline, DB is only called on cache miss)
            has_cache = False
            if service_pipeline:
                has_cache = any(step.get('type') == 'cache_check' for step in service_pipeline)

            # Effective DB call rate = (1 - cache_hit_rate) if cache exists, else 1.0
            db_call_probability = (1.0 - cache_hit_rate) if has_cache else 1.0

            # Effective time a connection is held per request
            effective_db_time = db_query_time_sec * db_call_probability

            total_db_connections = db_connection_pool_size * num_replicas
            # Max RPS = connections / effective_db_time
            if effective_db_time > 0:
                db_pool_limited_rps = total_db_connections / effective_db_time
            else:
                db_pool_limited_rps = float('inf')

    # === Find the Bottleneck (Minimum Constraint) ===
    # NOTE: Workload generator pool is NOT included here - it's not a topology constraint
    constraints = {
        'processing_time': processing_limited_rps,
    }

    if thread_pool_limited_rps is not None:
        constraints['thread_pool'] = thread_pool_limited_rps

    if db_pool_limited_rps is not None:
        constraints['db_connection_pool'] = db_pool_limited_rps

    # Find the limiting factor (minimum capacity)
    limiting_factor = min(constraints, key=constraints.get)
    max_rps = constraints[limiting_factor]

    # Apply 70% safety margin for target
    target_rps = max_rps * 0.70

    return {
        'max_rps': max_rps,
        'target_rps': target_rps,
        'max_concurrent': resource_profile.max_concurrent * num_replicas,
        'processing_time_p50': processing_time_sec,
        'limiting_factor': limiting_factor,
        'thread_pool_limited_rps': thread_pool_limited_rps,
        'db_pool_limited_rps': db_pool_limited_rps,
        'processing_limited_rps': processing_limited_rps,
    }


# ============================================================================
# Real-World Validation Data
# ============================================================================

# Based on public performance benchmarks:
# - AWS DynamoDB: https://aws.amazon.com/blogs/database/amazon-dynamodb-accelerator-dax-a-read-through-write-through-cache-for-dynamodb/
# - Redis: https://redis.io/topics/benchmarks
# - PostgreSQL: https://www.enterprisedb.com/postgres-tutorials/postgresql-query-performance-insights
# - NGINX: https://www.nginx.com/blog/testing-the-performance-of-nginx-and-nginx-plus-web-servers/
# - Kafka: https://engineering.linkedin.com/kafka/benchmarking-apache-kafka-2-million-writes-second-three-cheap-machines

BENCHMARKS = {
    'redis_get': {'p50': 0.5, 'p99': 2.0, 'source': 'redis.io/topics/benchmarks'},
    'dynamodb_get': {'p50': 1.5, 'p99': 10.0, 'source': 'AWS DynamoDB benchmarks'},
    'postgres_simple': {'p50': 3.0, 'p99': 20.0, 'source': 'PostgreSQL query performance'},
    'nginx_proxy': {'p50': 1.0, 'p99': 5.0, 'source': 'NGINX benchmarks'},
    'kafka_produce': {'p50': 2.0, 'p99': 15.0, 'source': 'Kafka benchmarks'},
}
