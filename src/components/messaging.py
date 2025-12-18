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

        # Queue capacity limit (matching real-world systems)
        # RabbitMQ: queue max-length, Kafka: retention limits, SQS: 120k in-flight
        # Defaults to 10000, but can be overridden via IAC config
        self.capacity = 10000  # Will be set by capacity planner or IAC config

        # SimPy resource to manage messages with capacity limit
        # This enables backpressure - producers block when queue is full
        self.store = simpy.Store(env, capacity=self.capacity)

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

        # Backpressure tracking for producer throttling metrics
        self.producer_blocked_times = []  # List of (timestamp, blocked_duration_ms) tuples
        self.producer_blocked_count = 0  # Total number of times producers were blocked

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

        # Counter for message processing failures (visibility timeout expiration)
        self.message_timeout_failures_counter = self.meter.create_counter(
            "mq.messages.timeout_failures",
            description="Messages that failed processing due to visibility timeout expiration",
            unit="1"
        )

        # Counter for successfully processed messages
        self.messages_deleted_counter = self.meter.create_counter(
            "mq.messages.deleted",
            description="Messages successfully processed and deleted",
            unit="1"
        )

        # Backpressure metrics (matching real-world queue monitoring)
        self.queue_capacity_gauge = self.meter.create_observable_gauge(
            "mq.queue.capacity",
            callbacks=[self._report_queue_capacity],
            description="Maximum queue capacity (message limit)"
        )
        self.queue_utilization_gauge = self.meter.create_observable_gauge(
            "mq.queue.utilization",
            callbacks=[self._report_queue_utilization],
            description="Queue utilization as percentage (depth/capacity)"
        )
        self.producer_blocked_counter = self.meter.create_counter(
            "mq.producer.blocked",
            description="Number of times producers were blocked due to full queue",
            unit="1"
        )
        self.producer_blocked_time_gauge = self.meter.create_observable_gauge(
            "mq.producer.blocked_time_ms",
            callbacks=[self._report_producer_blocked_time],
            description="Average time producers spent blocked waiting for queue space (ms)"
        )
        self.producer_waiting_gauge = self.meter.create_observable_gauge(
            "mq.producer.waiting",
            callbacks=[self._report_producers_waiting],
            description="Number of producers currently waiting for queue space"
        )

    def _apply_hcl_config(self):
        self.visibility_timeout = self.iac_config.get('visibility_timeout_seconds', 60)

        # Apply queue capacity if specified in IAC config
        # Capacity planner will set this based on production/consumption rates
        if 'capacity' in self.iac_config:
            old_capacity = self.capacity
            self.capacity = self.iac_config['capacity']

            # Recreate the store with new capacity if it changed
            if self.capacity != old_capacity:
                # Preserve existing messages
                existing_msgs = list(self.store.items) if hasattr(self.store, 'items') else []

                # Create new store with updated capacity
                self.store = simpy.Store(self.env, capacity=self.capacity)

                # Restore messages (up to new capacity)
                for msg in existing_msgs[:self.capacity]:
                    self.store.items.append(msg)

                self._emit_log("INFO", f"Queue capacity updated: {old_capacity} → {self.capacity}")

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

    def _report_queue_capacity(self, options):
        """Callback for queue capacity gauge."""
        from opentelemetry.metrics import Observation
        yield Observation(self.capacity, {
            "component.id": self.id
        })

    def _report_queue_utilization(self, options):
        """Callback for queue utilization gauge - reports current depth as % of capacity."""
        from opentelemetry.metrics import Observation
        current_depth = len(self.store.items)
        utilization = (current_depth / self.capacity * 100.0) if self.capacity > 0 else 0.0
        yield Observation(utilization, {
            "component.id": self.id
        })

    def _report_producer_blocked_time(self, options):
        """Callback for average producer blocked time - windowed average like other metrics."""
        from opentelemetry.metrics import Observation

        # Calculate average blocked time over the sample window
        cutoff_time = self.env.now - self.sample_window
        recent_blocks = [(t, d) for t, d in self.producer_blocked_times if t > cutoff_time]

        if recent_blocks:
            avg_blocked_ms = sum(d for _, d in recent_blocks) / len(recent_blocks)
        else:
            avg_blocked_ms = 0.0

        yield Observation(avg_blocked_ms, {
            "component.id": self.id
        })

    def _report_producers_waiting(self, options):
        """Callback for number of producers currently waiting for queue space."""
        from opentelemetry.metrics import Observation
        # SimPy Store tracks waiting producers in put_queue
        waiting_count = len(self.store.put_queue) if hasattr(self.store, 'put_queue') else 0
        yield Observation(waiting_count, {
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
        """
        Producer calls this to add a message to the queue.
        Blocks (applies backpressure) if queue is at capacity.
        Tracks blocked time for backpressure metrics.
        """
        self.message_counter += 1
        msg = Message(self.message_counter, body, self.env.now)

        # Track if producer gets blocked waiting for queue space
        start_time = self.env.now
        queue_was_full = len(self.store.items) >= self.capacity

        if queue_was_full:
            self._emit_log("WARN", f"Queue at capacity ({self.capacity}), producer blocked for message {msg.id}")

        # This will block if queue is full (capacity limit)
        yield self.store.put(msg)

        # Track backpressure metrics if producer was blocked
        if queue_was_full:
            blocked_time_ms = (self.env.now - start_time) * 1000.0
            self.producer_blocked_times.append((self.env.now, blocked_time_ms))
            self.producer_blocked_count += 1

            # Emit counter metric for blocked event
            self.producer_blocked_counter.add(1, {
                "component.id": self.id
            })

            # Clean up old blocked time samples (keep only within window)
            cutoff_time = self.env.now - self.sample_window
            self.producer_blocked_times = [(t, d) for t, d in self.producer_blocked_times if t > cutoff_time]

            self._emit_log("INFO", f"Producer unblocked after {blocked_time_ms:.1f}ms, message {msg.id} sent to queue.")
        else:
            self._emit_log("INFO", f"Message {msg.id} sent to queue.")

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
            # Track successful message processing
            self.messages_deleted_counter.add(1, {
                "component.id": self.id
            })
        else:
            self._emit_log("WARN", f"Attempted to delete message {msg.id} which was not in-flight.")
            
    def _handle_visibility_timeout(self, msg: Message):
        """Simulates the visibility timeout for a message.

        If processing takes longer than visibility timeout, treat it as a
        message processing failure (similar to DLQ behavior in production).
        """
        yield self.env.timeout(self.visibility_timeout)

        # If the message is still in-flight after the timeout, it means the consumer failed.
        if msg.id in self.in_flight_messages:
            self._emit_log("ERROR", f"Visibility timeout for message {msg.id} expired after {self.visibility_timeout}s. Message processing failed.")
            del self.in_flight_messages[msg.id]

            # Track as a message processing failure (like DLQ in production)
            # Do NOT re-queue to avoid infinite retry loops
            self.message_timeout_failures_counter.add(1, {
                "component.id": self.id,
                "failure_reason": "visibility_timeout_expired"
            })