from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
from src.dynamics.metrics_dynamics_engine import MetricsDynamicsEngine, DynamicsConfig
import simpy, random
from typing import Any, Optional
from collections import OrderedDict

class ObjectStorage(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "ObjectStorage")

        # Load centralized configuration
        config = get_simulation_config().storage.object_storage

        # S3 is mostly stateless from a simulation perspective
        self.latency_ms = config.latency_mean_ms
        self.latency_stdev_ms = config.latency_stdev_ms

    def run(self):
        yield self.env.process(super().run())

    def get_object(self, key: str):
        """Simulates getting an object, e.g., from S3."""
        with self._start_span("S3 GetObject") as span:
            span.set_attribute("storage.key", key)

            # Network layer handles connection and transmission errors
            yield from self._network_call(target_component_id=self.id, data_size_bytes=4096, target_component_type=self.type)

            # S3-specific errors (not network-level)
            if self._should_transient_error_occur('service_unavailable'):
                self._raise_transient_error('service_unavailable')

            if self._should_transient_error_occur('throttle_slow_down'):
                self._raise_transient_error('throttle_slow_down')

            # Simulate latency
            base_latency = random.gauss(self.latency_ms, self.latency_stdev_ms) / 1000.0
            # Add fault injection latency if active
            injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0
            yield self.env.timeout(base_latency + injected_latency)

            # Rare eventual consistency issues
            if self._should_transient_error_occur('eventual_consistency'):
                self._emit_log("WARN", f"Eventual consistency detected for key {key}")
                # Return None to simulate stale read

            return f"content for {key}"

class InMemoryCache(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "InMemoryCache")

        # Load centralized configuration
        config = get_simulation_config().storage.inmemory_cache

        # Use an OrderedDict to simulate a simple LRU cache
        self.cache = OrderedDict()
        self.max_size_items = config.max_size_items
        self.latency_ms = config.latency_mean_ms
        self.latency_stdev_ms = config.latency_stdev_ms

        # Track hit/miss samples for rate calculation
        self.hit_miss_samples = []  # [(time, was_hit)]
        self.sample_window = get_simulation_config().defaults.sample_window_seconds
        self.hit_rate_window = config.hit_rate_window_seconds

        # Initialize dynamics engine if enabled
        self.use_dynamics = False
        self.dynamics = None
        self.operation_count = 0
        self.last_operation_count = 0
        global_config = get_simulation_config()
        if hasattr(global_config, 'dynamics') and global_config.dynamics.get('enabled', False):
            cache_dynamics_config = global_config.dynamics.get('components', {}).get('cache', {})
            if cache_dynamics_config.get('enabled', False):
                self.use_dynamics = True
                # Cache-specific dynamics configuration
                dynamics_params = cache_dynamics_config.get('config', {})
                dynamics_cfg = DynamicsConfig(
                    latency_base=dynamics_params.get('latency_base', 2.0),
                    cpu_from_throughput_coef=dynamics_params.get('cpu_from_throughput_coef', 0.005),
                    cpu_from_connections_coef=dynamics_params.get('cpu_from_connections_coef', 0.1),
                    latency_cpu_threshold=dynamics_params.get('latency_cpu_threshold', 50.0),
                    latency_cpu_scale=dynamics_params.get('latency_cpu_scale', 30.0),
                    error_base=dynamics_params.get('error_base', 0.0001),
                    error_latency_threshold=dynamics_params.get('error_latency_threshold', 200.0),
                    error_cpu_threshold=dynamics_params.get('error_cpu_threshold', 80.0),
                    noise_enabled=dynamics_params.get('noise_enabled', True),
                )
                self.dynamics = MetricsDynamicsEngine(config=dynamics_cfg)

        # OTel Metrics - Keep counters for cumulative totals
        self.cache_hits_counter = self.meter.create_counter("cache.hits.total")
        self.cache_misses_counter = self.meter.create_counter("cache.misses.total")
        self.cache_evictions = self.meter.create_counter("cache.evictions")

        # NEW: Add gauge for hit rate (ratio 0-1)
        self.cache_hit_rate_gauge = self.meter.create_observable_gauge(
            "cache.hit_rate",
            callbacks=[self._report_hit_rate],
            unit="1",  # Changed from "%" to "1" for ratio
            description="Cache hit rate ratio (time-averaged)"
        )

    def _apply_hcl_config(self):
        """Apply IaC configuration to the cache."""
        if 'max_size_items' in self.iac_config:
            self.max_size_items = self.iac_config['max_size_items']

    def _report_hit_rate(self, options):
        """Callback for hit rate gauge - reports percentage of hits over recent window."""
        from opentelemetry.metrics import Observation

        # Calculate hit rate over configured window
        current_time = self.env.now
        cutoff_time = current_time - self.hit_rate_window

        # Filter to recent samples
        recent_samples = [(t, h) for t, h in self.hit_miss_samples if t > cutoff_time]

        if recent_samples:
            hits = sum(1 for _, was_hit in recent_samples if was_hit)
            total = len(recent_samples)
            hit_rate = hits / total if total > 0 else 0  # Return ratio (0-1) instead of percentage
        else:
            hit_rate = 0  # No recent activity

        # Clean up old samples
        self.hit_miss_samples = recent_samples

        yield Observation(hit_rate, {
            "component.id": self.id
        })

    def run(self):
        yield self.env.process(super().run())

        # Start dynamics update loop if enabled
        if self.use_dynamics:
            self.env.process(self._update_dynamics_loop())

    def _update_dynamics_loop(self):
        """Background process that updates the dynamics engine every simulation second."""
        while True:
            yield self.env.timeout(1.0)  # Update every simulation second

            # Calculate throughput (operations per second)
            ops_delta = self.operation_count - self.last_operation_count
            self.last_operation_count = self.operation_count

            # Update dynamics engine
            self.dynamics.update(
                dt=1.0,
                external_throughput=ops_delta,
                active_connections=0,
                queue_depth=0
            )

    def get(self, key: str, should_trace: bool = False, parent_span_context = None):
        """Simulates getting a key from the cache.

        Args:
            key: Cache key to retrieve
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Create child span if tracing is enabled and parent context exists
        if should_trace and parent_span_context:
            with self._start_span("CACHE Get", parent_span_context=parent_span_context) as span:
                span.set_attribute("cache.key", key)
                result = yield from self._get_internal(key)
                return result
        else:
            result = yield from self._get_internal(key)
            return result

    def _get_internal(self, key: str):
        """Internal get logic."""
        # Track operation count
        self.operation_count += 1

        # Network layer handles connection and transmission errors
        yield from self._network_call(target_component_id=self.id, data_size_bytes=256, target_component_type=self.type)

        # Use dynamics engine for latency if enabled
        if self.use_dynamics and self.dynamics:
            # Dynamics engine provides latency in milliseconds
            base_latency = self.dynamics.get_latency() / 1000.0

            # Check if operation should fail based on dynamics error rate
            if random.random() < self.dynamics.get_error_rate():
                self._emit_log("ERROR", "Cache get failed due to dynamics-driven error")
                raise Exception("Cache error: Connection timeout")
        else:
            # Original behavior
            base_latency = random.gauss(self.latency_ms, self.latency_stdev_ms) / 1000.0

        # Add fault injection latency if active
        injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0
        yield self.env.timeout(base_latency + injected_latency)

        if key in self.cache:
            # Record hit
            self.cache_hits_counter.add(1, {
                "component.id": self.id
            })
            self.hit_miss_samples.append((self.env.now, True))
            self.cache.move_to_end(key) # Mark as recently used
            return self.cache[key]
        else:
            # Record miss
            self.cache_misses_counter.add(1, {
                "component.id": self.id
            })
            self.hit_miss_samples.append((self.env.now, False))
            return None

    def set(self, key: str, value: Any, should_trace: bool = False, parent_span_context = None):
        """Simulates setting a key in the cache, with eviction.

        Args:
            key: Cache key to set
            value: Value to store
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Create child span if tracing is enabled and parent context exists
        if should_trace and parent_span_context:
            with self._start_span("CACHE Set", parent_span_context=parent_span_context) as span:
                span.set_attribute("cache.key", key)
                yield from self._set_internal(key, value)
        else:
            yield from self._set_internal(key, value)

    def _set_internal(self, key: str, value: Any):
        """Internal set logic."""
        # Track operation count
        self.operation_count += 1

        # Use dynamics engine for latency if enabled
        if self.use_dynamics and self.dynamics:
            # Dynamics engine provides latency in milliseconds
            base_latency = self.dynamics.get_latency() / 1000.0

            # Check if operation should fail based on dynamics error rate
            if random.random() < self.dynamics.get_error_rate():
                self._emit_log("ERROR", "Cache set failed due to dynamics-driven error")
                raise Exception("Cache error: Connection timeout")
        else:
            # Original behavior
            base_latency = random.gauss(self.latency_ms, self.latency_stdev_ms) / 1000.0

        # Add fault injection latency if active
        injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0
        yield self.env.timeout(base_latency + injected_latency)

        if key not in self.cache and len(self.cache) >= self.max_size_items:
            # Evict the least recently used item
            evicted_key, _ = self.cache.popitem(last=False)
            self.cache_evictions.add(1, {
                "component.id": self.id
            })
            self._emit_log("DEBUG", f"Cache full. Evicted key: {evicted_key}")

        self.cache[key] = value


class ExternalCache(EnrichedComponent):
    """
    Represents an external caching service like Redis or Memcached.

    Characteristics:
    - Network-based (not in-process)
    - Lower latency than database (5-15ms typical)
    - Can experience failures, connection issues, latency spikes
    - Supports cache hit/miss metrics
    - Suitable for thundering herd scenarios when fails
    """
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "ExternalCache")

        # Load centralized configuration
        config = get_simulation_config().storage.external_cache

        # Redis-like characteristics (loaded from config)
        self.base_latency_mean = config.base_latency_mean_ms / 1000.0  # Convert ms to seconds
        self.base_latency_std = config.base_latency_std_ms / 1000.0    # Convert ms to seconds
        self.base_error_rate = config.base_error_rate

        # Track hit/miss for metrics
        self.hit_miss_samples = []  # [(time, was_hit)]
        self.hit_rate_window = config.hit_rate_window_seconds

        # OTel Metrics
        self.cache_hits_counter = self.meter.create_counter("cache.hits.total")
        self.cache_misses_counter = self.meter.create_counter("cache.misses.total")

        # Hit rate gauge
        self.cache_hit_rate_gauge = self.meter.create_observable_gauge(
            "cache.hit_rate",
            callbacks=[self._report_hit_rate],
            unit="1",
            description="Cache hit rate ratio (time-averaged)"
        )

        # Error counter for fault propagation
        self.errors_counter = self.meter.create_counter(
            "component.errors.total",
            description=f"Total errors in {component_id}",
            unit="1"
        )

        # Simulated cache state (we track whether cache is "warm" or not)
        # Start at baseline hit rate to simulate a warmed-up cache (loaded from config)
        self.simulated_hit_rate = config.baseline_hit_rate

    def _report_hit_rate(self, options):
        """Callback for hit rate gauge - reports percentage of hits over recent window."""
        from opentelemetry.metrics import Observation

        # Calculate hit rate over configured window
        current_time = self.env.now
        cutoff_time = current_time - self.hit_rate_window

        # Filter to recent samples
        recent_samples = [(t, h) for t, h in self.hit_miss_samples if t > cutoff_time]

        if recent_samples:
            hits = sum(1 for _, was_hit in recent_samples if was_hit)
            total = len(recent_samples)
            hit_rate = hits / total if total > 0 else 0
        else:
            hit_rate = 0  # No recent activity

        # Clean up old samples
        self.hit_miss_samples = recent_samples

        yield Observation(hit_rate, {
            "component.id": self.id
        })

    def run(self):
        yield self.env.process(super().run())

    def get(self, key: str, should_trace: bool = False, parent_span_context = None):
        """Simulates getting a key from external cache (Redis-like).

        Args:
            key: Cache key to retrieve
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Create child span if tracing is enabled and parent context exists
        if should_trace and parent_span_context:
            with self._start_span("REDIS Get", parent_span_context=parent_span_context) as span:
                span.set_attribute("cache.key", key)
                result = yield from self._get_internal(key)
                return result
        else:
            result = yield from self._get_internal(key)
            return result

    def _get_internal(self, key: str):
        """Internal get logic for external cache."""
        # Network call to cache
        yield from self._network_call(
            target_component_id=self.id,
            data_size_bytes=256,
            target_component_type=self.type
        )

        # Check for forced errors (from fault injection)
        total_error_rate = self.base_error_rate + self.forced_error_rate
        if random.random() < total_error_rate:
            self._emit_log("ERROR", "Cache get failed - connection timeout")
            self.errors_counter.add(1, {
                "component.id": self.id,
                "component.type": self.type,
                "error_type": "connection_timeout"
            })
            raise Exception(f"Cache error: Connection timeout to {self.id}")

        # Latency with fault injection
        base_latency = random.gauss(self.base_latency_mean, self.base_latency_std)
        injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0
        yield self.env.timeout(base_latency + injected_latency)

        # Simulate hit/miss based on simulated hit rate
        is_hit = random.random() < self.simulated_hit_rate

        if is_hit:
            # Cache hit
            self.cache_hits_counter.add(1, {"component.id": self.id})
            self.hit_miss_samples.append((self.env.now, True))
            return f"cached_value_for_{key}"
        else:
            # Cache miss
            self.cache_misses_counter.add(1, {"component.id": self.id})
            self.hit_miss_samples.append((self.env.now, False))
            return None

    def set(self, key: str, value: Any, should_trace: bool = False, parent_span_context = None):
        """Simulates setting a key in external cache.

        Args:
            key: Cache key to set
            value: Value to store
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        # Create child span if tracing is enabled and parent context exists
        if should_trace and parent_span_context:
            with self._start_span("REDIS Set", parent_span_context=parent_span_context) as span:
                span.set_attribute("cache.key", key)
                yield from self._set_internal(key, value)
        else:
            yield from self._set_internal(key, value)

    def _set_internal(self, key: str, value: Any):
        """Internal set logic for external cache."""
        # Network call to cache
        yield from self._network_call(
            target_component_id=self.id,
            data_size_bytes=256,
            target_component_type=self.type
        )

        # Check for forced errors (from fault injection)
        total_error_rate = self.base_error_rate + self.forced_error_rate
        if random.random() < total_error_rate:
            self._emit_log("ERROR", "Cache set failed - connection timeout")
            self.errors_counter.add(1, {
                "component.id": self.id,
                "component.type": self.type,
                "error_type": "connection_timeout"
            })
            raise Exception(f"Cache error: Connection timeout to {self.id}")

        # Latency with fault injection
        base_latency = random.gauss(self.base_latency_mean, self.base_latency_std)
        injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0
        yield self.env.timeout(base_latency + injected_latency)