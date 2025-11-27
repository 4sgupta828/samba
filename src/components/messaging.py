from .base_component import EnrichedComponent
from src.core.simulation_config import get_simulation_config
import simpy
from typing import Dict

class Message:
    """Represents a single message in the queue."""
    def __init__(self, message_id: int, body: str, sent_time: float):
        self.id = message_id
        self.body = body
        self.sent_time = sent_time
        self.receive_count = 0

class MessageQueue(EnrichedComponent):
    def __init__(self, env, component_id):
        super().__init__(env, component_id, "MessageQueue")

        # Load centralized configuration
        config = get_simulation_config().messaging.message_queue

        # SimPy resource to manage messages
        self.store = simpy.Store(env)

        # Internal state for visibility timeout simulation
        self.in_flight_messages: Dict[int, Message] = {}
        self.visibility_timeout = config.visibility_timeout_seconds

        self.message_counter = 0

        # Fault injection support
        self.injected_latency_ms = 0  # Set by failure injection (deprecated - use consumer_processing_latency_ms)
        self.consumer_processing_latency_ms = 0  # Latency added to consumer processing (not receive)

        # Track samples for time-averaged gauges (like production systems)
        self.visible_samples = []
        self.in_flight_samples = []
        self.age_samples = []
        self.sample_window = get_simulation_config().defaults.sample_window_seconds
        self.metrics_sampling_interval = config.metrics_sampling_interval_seconds

        # OTel Metrics - time-averaged like CloudWatch SQS metrics
        self.visible_messages_gauge = self.meter.create_observable_gauge(
            "mq.messages.visible",
            callbacks=[self._report_visible_messages],
            description="Visible messages in queue (time-averaged)"
        )
        self.in_flight_messages_gauge = self.meter.create_observable_gauge(
            "mq.messages.in_flight",
            callbacks=[self._report_in_flight_messages],
            description="In-flight messages (time-averaged)"
        )
        self.oldest_message_age_gauge = self.meter.create_observable_gauge(
            "mq.messages.age_seconds",
            callbacks=[self._report_oldest_message_age],
            description="Age of oldest message in seconds (time-averaged)"
        )

    def _apply_hcl_config(self):
        self.visibility_timeout = self.iac_config.get('visibility_timeout_seconds', 60)

    def _report_visible_messages(self, options):
        """Callback for visible messages gauge - reports time-averaged value like production systems."""
        from opentelemetry.metrics import Observation

        # Calculate average visible messages over the sample window
        if self.visible_samples:
            avg_visible = sum(v for _, v in self.visible_samples) / len(self.visible_samples)
        else:
            # Fallback to current count if no samples yet
            avg_visible = len(self.store.items)

        yield Observation(avg_visible, {
            "component.id": self.id
        })

    def _report_in_flight_messages(self, options):
        """Callback for in-flight messages gauge - reports time-averaged value like production systems."""
        from opentelemetry.metrics import Observation

        # Calculate average in-flight messages over the sample window
        if self.in_flight_samples:
            avg_in_flight = sum(v for _, v in self.in_flight_samples) / len(self.in_flight_samples)
        else:
            # Fallback to current count if no samples yet
            avg_in_flight = len(self.in_flight_messages)

        yield Observation(avg_in_flight, {
            "component.id": self.id
        })

    def _report_oldest_message_age(self, options):
        """Callback for message age gauge - reports time-averaged value like production systems."""
        from opentelemetry.metrics import Observation

        # Calculate average age over the sample window
        if self.age_samples:
            avg_age = sum(v for _, v in self.age_samples) / len(self.age_samples)
        else:
            # Fallback to current age if no samples yet
            if self.store.items:
                oldest_msg = self.store.items[0]
                avg_age = self.env.now - oldest_msg.sent_time
            else:
                avg_age = 0

        yield Observation(avg_age, {
            "component.id": self.id
        })
            
    def run(self):
        # Start background sampling process
        self.env.process(self._sample_metrics_periodically())
        # The queue itself is passive, its logic is called by other components.
        yield self.env.process(super().run())

    def _sample_metrics_periodically(self):
        """Background process that samples queue metrics at regular intervals."""
        while True:
            yield self.env.timeout(self.metrics_sampling_interval)

            current_time = self.env.now

            # Sample visible messages
            self.visible_samples.append((current_time, len(self.store.items)))

            # Sample in-flight messages
            self.in_flight_samples.append((current_time, len(self.in_flight_messages)))

            # Sample oldest message age
            if self.store.items:
                oldest_msg = self.store.items[0]
                age = current_time - oldest_msg.sent_time
                self.age_samples.append((current_time, age))
            else:
                self.age_samples.append((current_time, 0))

            # Remove samples older than the window
            cutoff_time = current_time - self.sample_window
            self.visible_samples = [(t, v) for t, v in self.visible_samples if t > cutoff_time]
            self.in_flight_samples = [(t, v) for t, v in self.in_flight_samples if t > cutoff_time]
            self.age_samples = [(t, v) for t, v in self.age_samples if t > cutoff_time]

    def send_message(self, body: str):
        """Producer calls this to add a message to the queue."""
        self.message_counter += 1
        msg = Message(self.message_counter, body, self.env.now)
        self._emit_log("INFO", f"Message {msg.id} sent to queue.")
        return self.store.put(msg)

    def receive_message(self):
        """Consumer calls this to get a message."""
        msg = yield self.store.get()
        msg.receive_count += 1

        # Note: OLD behavior was to inject latency here, but that doesn't simulate
        # consumer slowdown correctly. Consumer slowdown should happen during PROCESSING,
        # not during message receive. See consumer_processing_latency_ms attribute.

        # Move to in-flight and start visibility timeout
        self.in_flight_messages[msg.id] = msg
        self._emit_log("DEBUG", f"Message {msg.id} is now in-flight.")

        # Start a process to handle the timeout
        self.env.process(self._handle_visibility_timeout(msg))

        return msg

    def delete_message(self, msg: Message):
        """Consumer calls this after successfully processing a message."""
        if msg.id in self.in_flight_messages:
            del self.in_flight_messages[msg.id]
            self._emit_log("INFO", f"Message {msg.id} deleted successfully.")
        else:
            self._emit_log("WARN", f"Attempted to delete message {msg.id} which was not in-flight.")
            
    def _handle_visibility_timeout(self, msg: Message):
        """Simulates the visibility timeout for a message."""
        yield self.env.timeout(self.visibility_timeout)
        
        # If the message is still in-flight after the timeout, it means the consumer failed.
        if msg.id in self.in_flight_messages:
            self._emit_log("WARN", f"Visibility timeout for message {msg.id} expired. Re-queuing.")
            del self.in_flight_messages[msg.id]
            # Put it back at the front of the queue
            self.store.items.insert(0, msg)