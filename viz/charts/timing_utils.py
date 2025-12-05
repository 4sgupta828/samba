"""
Timing utilities for handling warmup period adjustments.

IMPORTANT: As of the warmup fix, label data now contains times in ADJUSTED sim.time
(metrics timeline) that already accounts for warmup. The times start at 0 after warmup,
matching the metrics data directly.

For backward compatibility with physical times, use the physical_timeline field in labels.
"""

from typing import Dict, Optional


def adjust_time_for_warmup(physical_time: float, label_data: Dict) -> float:
    """
    Adjust a physical time to metrics time by subtracting warmup period.

    NOTE: This is only needed for physical times from physical_timeline.
    The main label times (fault_start_time, etc.) are already adjusted.

    Args:
        physical_time: Time in physical simulation seconds (includes warmup)
        label_data: Label data containing warmup_period

    Returns:
        Time in metrics seconds (sim_time, starts at 0 after warmup)
    """
    warmup_period = label_data.get('warmup_period', 0) or 0
    return physical_time - warmup_period


def get_fault_times_adjusted(label_data: Dict) -> Dict[str, Optional[float]]:
    """
    Get fault timing information in sim_time (metrics timeline).

    IMPORTANT: Label times are now ALREADY in adjusted sim.time (post-warmup).
    No adjustment needed - just read them directly.

    Args:
        label_data: Label data containing fault timing information

    Returns:
        Dictionary with times in sim_time (metrics timeline):
        - fault_start: Fault injection time in sim_time
        - recovery_start: Fault removal time in sim_time (None if not available)
        - fault_end: Fault end time in sim_time
    """
    # Label times are already adjusted - read them directly
    fault_start = label_data.get('fault_start_time', 0)

    recovery_start = label_data.get('recovery_start_time')

    # Calculate fault end time
    if recovery_start is not None:
        fault_end = recovery_start
    else:
        fault_duration = label_data.get('fault_total_duration', 0)
        fault_end = fault_start + fault_duration

    return {
        'fault_start': fault_start,
        'recovery_start': recovery_start,
        'fault_end': fault_end
    }
