"""
Defines functions for calculating inter-arrival times for different
stochastic and deterministic workload patterns.
"""
import math
import numpy as np
from typing import Dict

def get_inter_arrival_time(config: Dict, current_time: float) -> float:
    """
    Calculates the time to wait before the next request, based on the configured pattern.
    Returns the delay in seconds.
    """
    pattern = config.get("pattern", "constant")

    if pattern == "constant":
        rps = config.get("rps", 1)
        if rps <= 0: return float('inf') # No traffic
        # Use exponential distribution to maintain stochastic behavior
        # but with constant average rate
        return np.random.exponential(1.0 / rps)

    elif pattern == "diurnal":
        peak_rps = config.get("peak_rps", 100)
        baseline_rps = config.get("baseline_rps", 10)

        # Calculate the amplitude and midpoint of the sine wave
        amplitude = (peak_rps - baseline_rps) / 2
        midpoint = (peak_rps + baseline_rps) / 2

        # Optional time offset to start simulation at a specific time of day
        # For example, time_offset=43200 starts at noon (peak), time_offset=0 starts at midnight (trough)
        time_offset = config.get("time_offset", 0)

        # Calculate the current point in a 24-hour (86400s) cycle
        # The sine wave is shifted to have its trough at time 0 (midnight)
        # and its peak at 12 hours (43200s).
        seconds_in_day = 86400
        adjusted_time = current_time + time_offset
        angle = (adjusted_time % seconds_in_day) / seconds_in_day * 2 * math.pi
        # sin(x - pi/2) shifts the wave so the minimum is at x=0
        current_rps = midpoint + amplitude * math.sin(angle - math.pi / 2)
        
        if current_rps <= 0: return float('inf')
        
        # Use exponential distribution for inter-arrival time to model a Poisson process
        return np.random.exponential(1.0 / current_rps)
    
    # Can add other patterns like 'bursty' here in the future
    else:
        raise ValueError(f"Unknown workload pattern: {pattern}")