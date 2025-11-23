"""
External Service Component - Models 3rd party APIs.

Simulates external dependencies like payment gateways, email providers,
SMS services, etc. These are "black boxes" with no internal metrics visibility.
"""
import random
from src.components.service import ApiService


class ExternalService(ApiService):
    """
    Represents a 3rd party API (e.g., Stripe, Twilio, SendGrid).

    Characteristics:
    - Acts as a sink (no downstream dependencies)
    - High latency variance (200ms ± 50ms)
    - Occasional failures (0.5% inherent error rate)
    - No internal metrics available (black box)
    """

    def __init__(self, env, component_id):
        super().__init__(env, component_id, "external_api")
        self.supported_request_types = ['POST', 'GET']

        # External APIs are slower than internal services
        self.base_latency_mean = 0.200  # 200ms
        self.base_latency_std = 0.050   # 50ms jitter

    def handle_request(self, request_type: str, should_trace: bool = False, parent_span_context=None):
        """
        Simulate external API call.

        Args:
            request_type: HTTP method (GET, POST, etc.)
            should_trace: Whether to create tracing spans
            parent_span_context: Parent span context for distributed tracing
        """
        self.request_count += 1

        if should_trace and parent_span_context:
            with self._start_span(f"external:{request_type}", parent_span_context=parent_span_context) as span:
                yield from self._execute_logic(span)
        else:
            yield from self._execute_logic(None)

    def _execute_logic(self, span):
        """Internal execution logic for external API calls."""
        # 1. Network transmission (simulates request to external endpoint)
        yield from self._network_call(
            self.id,
            data_size_bytes=1024,
            target_component_type="ExternalService"
        )

        # 2. Processing latency (black box - we don't know what they're doing)
        injected = self.injected_latency_ms / 1000.0
        latency = max(0.01, random.gauss(self.base_latency_mean, self.base_latency_std))

        yield self.env.timeout(latency + injected)

        # 3. Random failures (external APIs are inherently less reliable)
        # Base 0.5% chance of timeout/error + any injected error rate
        base_error_rate = 0.005  # 0.5%
        total_error_rate = base_error_rate + self.forced_error_rate
        if random.random() < total_error_rate:
            self._emit_log("ERROR", f"External API timeout on {self.id}")
            if span:
                span.set_attribute("error", True)
                span.set_attribute("error.type", "external_timeout")
            raise Exception(f"External API Timeout (504): {self.id}")

        # Success
        if span:
            span.set_attribute("http.status_code", 200)
            span.set_attribute("external.service", self.id)
