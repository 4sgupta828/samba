"""
Utility functions for timestamp transformation in telemetry data.

These utilities help map simulation timestamps to real-world time windows,
useful for creating realistic training datasets with historical timestamps.
"""
from datetime import datetime, timedelta
from typing import Callable


def create_past_window_transform(
    days_ago: int = 0,
    hours_ago: int = 0,
    minutes_ago: int = 0,
    custom_start_time: datetime = None
) -> Callable[[int], int]:
    """
    Create a timestamp transformation function that maps simulation timestamps
    to a past time window.

    This is useful for creating realistic training datasets where you want
    timestamps to appear as if they occurred in the past (e.g., for testing
    time-based ML models or creating historical datasets).

    Args:
        days_ago: Number of days in the past for the time window (default: 0)
        hours_ago: Number of hours in the past for the time window (default: 0)
        minutes_ago: Number of minutes in the past for the time window (default: 0)
        custom_start_time: Custom datetime to use as base (overrides days/hours/minutes_ago)

    Returns:
        A transformation function that takes a timestamp in nanoseconds and returns
        a shifted timestamp in nanoseconds.

    Example:
        # Map simulation to 7 days ago
        transform_fn = create_past_window_transform(days_ago=7)

        # Map simulation to a specific date
        specific_date = datetime(2024, 1, 1, 0, 0, 0)
        transform_fn = create_past_window_transform(custom_start_time=specific_date)

        # Use in telemetry setup
        setup_telemetry(
            config,
            output_dir=output_dir,
            simulation_start_timestamp_ns=sim_start_ns,
            timestamp_transform_fn=transform_fn
        )
    """
    # Calculate the target start time
    if custom_start_time:
        target_start = custom_start_time
    else:
        # Calculate time delta from now
        now = datetime.utcnow()
        delta = timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
        target_start = now - delta

    # Convert target start time to nanoseconds
    target_start_ns = int(target_start.timestamp() * 1_000_000_000)

    def transform_fn(timestamp_ns: int) -> int:
        """
        Transform a timestamp by shifting it to a past time window.

        The transformation preserves the relative time differences between events
        (simulation duration remains the same), but shifts all timestamps to appear
        as if they occurred starting from the target_start time.

        Args:
            timestamp_ns: Original timestamp in nanoseconds

        Returns:
            Shifted timestamp in nanoseconds
        """
        # Get the current "now" in nanoseconds
        current_now_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)

        # Calculate offset: how far back we want to shift
        offset_ns = current_now_ns - target_start_ns

        # Apply the offset to shift timestamp to the past
        return timestamp_ns - offset_ns

    return transform_fn


def create_fixed_start_transform(start_timestamp_ns: int) -> Callable[[int], int]:
    """
    Create a timestamp transformation function that maps simulation to start
    at a fixed timestamp, preserving the simulation duration.

    Args:
        start_timestamp_ns: The target start timestamp in nanoseconds

    Returns:
        A transformation function that shifts timestamps to start at the given time.

    Example:
        # Map simulation to start at Unix epoch 1704067200000000000 (Jan 1, 2024)
        transform_fn = create_fixed_start_transform(1704067200000000000)
    """
    # This will be set when the first timestamp is transformed
    first_original_ts = None

    def transform_fn(timestamp_ns: int) -> int:
        nonlocal first_original_ts

        # Capture the first timestamp we see
        if first_original_ts is None:
            first_original_ts = timestamp_ns

        # Calculate offset from the first timestamp
        offset_from_start = timestamp_ns - first_original_ts

        # Return the fixed start time plus the offset
        return start_timestamp_ns + offset_from_start

    return transform_fn


def format_timestamp_ns(timestamp_ns: int, format_str: str = "%Y-%m-%d %H:%M:%S.%f") -> str:
    """
    Format a nanosecond timestamp as a human-readable string.

    Args:
        timestamp_ns: Timestamp in nanoseconds
        format_str: strftime format string (default: "%Y-%m-%d %H:%M:%S.%f")

    Returns:
        Formatted timestamp string

    Example:
        >>> format_timestamp_ns(1704067200000000000)
        '2024-01-01 00:00:00.000000'
    """
    timestamp_seconds = timestamp_ns / 1_000_000_000
    dt = datetime.utcfromtimestamp(timestamp_seconds)
    return dt.strftime(format_str)
