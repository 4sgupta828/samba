"""
Shared constants for simulation configuration.
"""

# Multipliers for semantic resource profiles
# Used by both CapacityPlanner (provisioning) and Pod (execution)
PROFILE_MULTIPLIERS = {
    "cpu_intensive": 2.5,       # Heavy computation
    "io_intensive": 1.1,        # I/O wait overhead
    "latency_sensitive": 0.8,   # Optimized/lightweight
    "standard": 1.0
}

def get_profile_multiplier(profile_name: str) -> float:
    """
    Get the multiplier for a given resource profile.

    Args:
        profile_name: The resource profile name (e.g., "cpu_intensive", "io_intensive")

    Returns:
        The multiplier value for the profile (defaults to 1.0 if unknown)
    """
    return PROFILE_MULTIPLIERS.get(profile_name, 1.0)
