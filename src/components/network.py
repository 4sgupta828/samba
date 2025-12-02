"""
Network layer component for simulating network-level errors and latency.

This component sits between other components and introduces realistic network
failures like connection timeouts, packet loss, DNS failures, etc.
"""
from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
import simpy
import random


class NetworkLink(EnrichedComponent):
    """
    Simulates a network link between components with realistic network errors.

    This component models:
    - Network latency (base + jitter)
    - Packet loss and retransmission
    - Connection establishment failures
    - Connection resets
    - DNS resolution failures
    - TLS handshake failures
    - Network partitions
    """

    def __init__(self, env: simpy.Environment, component_id: str):
        super().__init__(env, component_id, "NetworkLink")

        # Load centralized configuration
        config = get_simulation_config().network

        # Network characteristics
        self.base_latency_ms = config.base_latency_ms
        self.latency_jitter_ms = config.latency_jitter_ms
        self.bandwidth_mbps = config.bandwidth_mbps

        # NEW: Bandwidth contention (optional) - wire can only transmit one packet at a time
        # When disabled, packets can overlap (infinite bandwidth)
        self.enable_bandwidth_contention = getattr(config, 'enable_bandwidth_contention', True)
        self.transmission_resource = simpy.Resource(env, capacity=1) if self.enable_bandwidth_contention else None

        # Metrics
        self.bytes_transmitted_counter = self.meter.create_counter(
            "network.bytes.transmitted",
            description="Total bytes transmitted through network"
        )
        self.bytes_received_counter = self.meter.create_counter(
            "network.bytes.received",
            description="Total bytes received through network"
        )
        self.latency_histogram = self.meter.create_histogram(
            "network.latency",
            unit="ms",
            description="Network latency distribution"
        )
        self.retransmit_counter = self.meter.create_counter(
            "network.retransmits",
            description="Number of packet retransmissions"
        )

    def _apply_hcl_config(self):
        """Apply IaC configuration to network link."""
        if 'base_latency_ms' in self.iac_config:
            self.base_latency_ms = self.iac_config['base_latency_ms']
        if 'latency_jitter_ms' in self.iac_config:
            self.latency_jitter_ms = self.iac_config['latency_jitter_ms']
        if 'bandwidth_mbps' in self.iac_config:
            self.bandwidth_mbps = self.iac_config['bandwidth_mbps']

    def run(self):
        """Network link is passive - it doesn't have its own process."""
        yield self.env.process(super().run())

    def transmit(self, data_size_bytes: int = 1024, should_trace: bool = False, parent_span_context=None):
        """
        Simulate transmitting data over the network with realistic errors.

        Args:
            data_size_bytes: Size of data to transmit
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing

        Yields:
            SimPy timeout for network latency

        Raises:
            Exception: On network failures (connection reset, timeout, etc.)
        """
        if should_trace and parent_span_context:
            with self._start_span("network.transmit", parent_span_context=parent_span_context) as span:
                span.set_attribute("network.bytes", data_size_bytes)
                yield from self._transmit_internal(data_size_bytes, span)
        else:
            yield from self._transmit_internal(data_size_bytes, None)

    def _transmit_internal(self, data_size_bytes: int, span=None, target_component_type: str = None):
        """Internal transmission logic with error injection.

        Args:
            data_size_bytes: Size of data being transmitted
            span: Optional tracing span
            target_component_type: Optional component type (e.g., "SqlDatabase", "InMemoryCache")
                                  to determine component-specific network latency
        """
        # Check for connection establishment failure
        if self._should_transient_error_occur('connection_failure'):
            if span:
                span.set_attribute("error", True)
            self._raise_transient_error('connection_failure')

        # Check for DNS failure (happens before connection)
        if self._should_transient_error_occur('dns_failure'):
            if span:
                span.set_attribute("error", True)
            self._raise_transient_error('dns_failure')

        # Check for TLS handshake failure
        if self._should_transient_error_occur('tls_handshake_failure'):
            if span:
                span.set_attribute("error", True)
            self._raise_transient_error('tls_handshake_failure')

        # Calculate network latency with component-specific overrides
        config = get_simulation_config().network

        # Determine base latency based on target component type
        component_base_latency_ms = self.base_latency_ms  # Default
        if target_component_type and hasattr(config, 'component_latencies'):
            # Map component type to network latency category (deterministic)
            latency_category = self._map_component_type_to_latency_category(target_component_type)
            component_latencies = config.component_latencies
            if latency_category in component_latencies:
                component_base_latency_ms = component_latencies[latency_category]
            elif 'default' in component_latencies:
                component_base_latency_ms = component_latencies['default']

        base_latency = random.gauss(component_base_latency_ms, self.latency_jitter_ms) / 1000.0
        base_latency = max(base_latency, config.latency_minimum_ms / 1000.0)

        # Add fault injection latency if active
        injected_latency = self.injected_latency_ms / 1000.0 if self.injected_latency_ms > 0 else 0

        # Calculate transmission time based on bandwidth (serialization delay)
        serialization_delay = (data_size_bytes * 8) / (self.bandwidth_mbps * 1_000_000)  # Convert to seconds

        # Check for packet loss (requires retransmission)
        packet_loss_multiplier = 1.0
        if self._should_transient_error_occur('packet_loss'):
            self._emit_log("WARN", "Packet loss detected, retransmitting")
            self.retransmit_counter.add(1, {"component.id": self.id})
            if span:
                span.add_event("packet_loss_retransmit")
            # Retransmission adds latency
            packet_loss_multiplier = config.packet_loss_latency_multiplier

        # NEW: Bandwidth contention (if enabled) - wait for exclusive access to the wire
        if self.enable_bandwidth_contention and self.transmission_resource:
            with self.transmission_resource.request() as req:
                yield req  # Wait in queue if wire is busy
                # Now we have exclusive access - transmit the packet
                yield self.env.timeout(serialization_delay * packet_loss_multiplier)
        else:
            # No contention - packets can overlap (infinite bandwidth model)
            yield self.env.timeout(serialization_delay * packet_loss_multiplier)

        # Propagation delay (light speed + routing delay) - happens after transmission
        yield self.env.timeout(base_latency + injected_latency)

        # Check for connection reset during transmission
        if self._should_transient_error_occur('connection_reset'):
            if span:
                span.set_attribute("error", True)
            self._raise_transient_error('connection_reset')

        # Check for timeout
        if self._should_transient_error_occur('timeout'):
            if span:
                span.set_attribute("error", True)
            self._raise_transient_error('timeout')

        # Success - record metrics
        self.bytes_transmitted_counter.add(data_size_bytes, {"component.id": self.id})
        self.bytes_received_counter.add(data_size_bytes, {"component.id": self.id})

    def _map_component_type_to_latency_category(self, component_type: str) -> str:
        """
        Map component type to network latency category (deterministic).

        Args:
            component_type: Component type string (e.g., "SqlDatabase", "InMemoryCache")

        Returns:
            Latency category key from config (e.g., "database", "cache", "message_queue")

        Examples:
            "SqlDatabase" -> "database"
            "NoSqlDatabase" -> "database"
            "InMemoryCache" -> "cache"
            "MessageQueue" -> "message_queue"
            "ObjectStorage" -> "object_storage"
        """
        # Deterministic mapping from component type to latency category
        type_to_category = {
            "SqlDatabase": "database",
            "NoSqlDatabase": "database",
            "InMemoryCache": "cache",
            "MessageQueue": "message_queue",
            "ObjectStorage": "object_storage",
            "RequestGateway": "default",  # Load balancers use default (fast)
            "ApiService": "default",
            "ComputeAgent": "default",
        }

        return type_to_category.get(component_type, "default")

    def establish_connection(self, target_component_id: str):
        """
        Simulate establishing a network connection to a target component.

        Args:
            target_component_id: ID of the component to connect to

        Yields:
            SimPy timeout for connection establishment

        Raises:
            Exception: On connection failures
        """
        with self._start_span(f"network.connect:{target_component_id}") as span:
            span.set_attribute("network.target", target_component_id)

            # Check for connection failure
            if self._should_transient_error_occur('connection_failure'):
                span.set_attribute("error", True)
                self._raise_transient_error('connection_failure')

            # Check for DNS failure
            if self._should_transient_error_occur('dns_failure'):
                span.set_attribute("error", True)
                self._raise_transient_error('dns_failure')

            # Check for TLS handshake failure
            if self._should_transient_error_occur('tls_handshake_failure'):
                span.set_attribute("error", True)
                self._raise_transient_error('tls_handshake_failure')

            # Simulate TCP handshake time (SYN, SYN-ACK, ACK)
            config = get_simulation_config().network
            handshake_time = random.gauss(self.base_latency_ms * config.tcp_handshake_time_multiplier, self.latency_jitter_ms) / 1000.0
            handshake_time = max(handshake_time, config.tcp_handshake_minimum_ms / 1000.0)

            yield self.env.timeout(handshake_time)

            self._emit_log("DEBUG", f"Established connection to {target_component_id}")
