"""
Scenario Library - Curriculum learning for GNN training.

This module manages the progression of training difficulty, from simple
single-service failures to complex multi-component interactions.
"""
from dataclasses import dataclass
import random
from typing import List


@dataclass
class EpisodeConfig:
    """Configuration for a single training episode."""
    level: int                    # Difficulty level (1-4)
    topology_size: int            # Number of nodes
    duration: int                 # Simulation duration (seconds)
    fault_type: str              # Type of failure to inject
    fault_target_role: str       # Component role to target
    export_interval: int         # Metric export interval (seconds)
    description: str             # Human-readable description
    progression: str = "linear"  # How failure progresses: linear, exponential, step
    fault_params: dict = None    # Failure-specific parameters
    fault_severity: float = 0.5  # NEW: Fault intensity [0.0-1.0], default 0.5 (balanced)
                                 # 0.0-0.3: Subtle (mild issues)
                                 # 0.3-0.7: Moderate (typical prod issues)
                                 # 0.7-1.0: Severe (cascading failures)

    def get_failure_params(self) -> dict:
        """
        Get failure parameters based on fault type.
        Returns adaptive, randomized parameters for realistic fault injection.

        Philosophy:
        - Use percentages/ranges instead of fixed values
        - Randomize within realistic bounds for diversity
        - Scale to component configuration (thread pools, capacity, etc.)
        - Parameters set here are defaults; they can be overridden at injection time
        """
        if self.fault_params:
            return self.fault_params

        import random

        # Default parameters for each failure type
        # Use ranges and percentages for more realistic, diverse scenarios
        param_defaults = {
            'cpu_saturation': {
                # Randomize multipliers for diversity
                'cpu_multiplier': random.uniform(2.5, 4.0),      # 2.5-4x CPU usage
                'latency_multiplier': random.uniform(1.5, 3.0),  # 1.5-3x latency
                'cpu_latency_ms': random.randint(300, 800)       # 300-800ms added latency
            },
            'memory_leak': {
                # Randomize leak rate for different severities
                'leak_mb_per_request': random.uniform(0.3, 1.0)  # 0.3-1.0 MB per request
            },
            'inject_latency': {
                # Randomize latency for realistic variation
                'latency_ms': random.randint(1500, 3000)  # 1.5-3 seconds
            },
            'slow_queries': {
                # Randomize wear factor
                'wear_factor': random.uniform(0.4, 0.7)  # 40-70% wear
            },
            'connection_exhaustion': {
                # Randomize added latency
                'latency_ms': random.randint(800, 1500)  # 0.8-1.5 seconds
            },
            'enable_background_job': {},
            'cache_failure': {},
            'inject_errors': {
                # Randomize error rate for different severities
                'error_rate': random.uniform(0.2, 0.4)  # 20-40% error rate
            },
            'queue_consumer_slowdown': {
                # Randomize slowdown to exceed visibility timeout variably
                'latency_ms': random.randint(7000, 10000)  # 7-10 seconds
            },
            # Structural failure modes
            'noisy_neighbor': {
                # Randomize CPU contention level (high but not always 100%)
                'cpu_percent': random.uniform(90.0, 100.0),      # 90-100% CPU
                'steal_time_multiplier': random.uniform(1.3, 1.8)  # 1.3-1.8x steal time
            },
            'hot_shard': {
                # Pod will be selected randomly at injection time (see modes.py)
                # Use 'random' to signal random selection
                'target_pod_index': 'random',
                # Randomize skew factor for different severities
                'skew_factor': random.uniform(0.7, 0.9)  # 70-90% traffic to hot pod
            },
            'network_partition': {
                'source_component_id': None,  # Will be set dynamically at injection
                'target_component_id': None,   # Will be set dynamically at injection
                'bidirectional': True
            },
            'force_deadlock': {
                # Percentage-based locking (adaptive to thread pool size)
                'thread_percentage': random.uniform(0.6, 0.8),  # 60-80% of threads
                'duration': 300.0  # 5 minutes (fixed duration for consistent observation window)
            }
        }

        return param_defaults.get(self.fault_type, {})


class ScenarioLibrary:
    """
    Manages curriculum learning for GNN training.

    Implements a 4-level curriculum:
    - Level 1: Simple service failures (CPU, memory)
    - Level 2: Database bottlenecks (queries, connections)
    - Level 3: Complex interactions (caches, queues)
    - Level 4: External dependencies (black box failures)
    """

    def __init__(self):
        """Initialize the scenario library."""
        self.levels = {
            1: self._get_level1_scenarios(),
            2: self._get_level2_scenarios(),
            3: self._get_level3_scenarios(),
            4: self._get_level4_scenarios(),
        }

    def get_episode(self, level: int, seed: int) -> EpisodeConfig:
        """
        Get an episode configuration for the specified level.

        Args:
            level: Difficulty level (1-4)
            seed: Random seed for reproducibility

        Returns:
            EpisodeConfig for this episode

        Raises:
            ValueError: If level is invalid
        """
        if level not in self.levels:
            raise ValueError(f"Invalid level {level}. Must be 1-4.")

        rng = random.Random(seed)
        scenarios = self.levels[level]

        # Pick a random scenario from this level
        return rng.choice(scenarios)

    def _get_level1_scenarios(self) -> List[EpisodeConfig]:
        """Level 1: Simple service failures."""
        return [
            EpisodeConfig(
                level=1,
                topology_size=5,
                duration=300,  # 5 minutes
                fault_type="cpu_saturation",
                fault_target_role="service",
                export_interval=5,
                description="Single service CPU saturation",
                progression="linear"
            ),
            EpisodeConfig(
                level=1,
                topology_size=5,
                duration=300,
                fault_type="memory_leak",
                fault_target_role="service",
                export_interval=5,
                description="Single service memory leak",
                progression="exponential"  # Memory leaks often grow exponentially
            ),
            EpisodeConfig(
                level=1,
                topology_size=5,
                duration=300,
                fault_type="inject_latency",
                fault_target_role="service",
                export_interval=5,
                description="Single service latency spike",
                progression="linear"
            ),
        ]

    def _get_level2_scenarios(self) -> List[EpisodeConfig]:
        """Level 2: Database bottlenecks."""
        return [
            EpisodeConfig(
                level=2,
                topology_size=10,
                duration=600,  # 10 minutes
                fault_type="slow_queries",
                fault_target_role="database",
                export_interval=5,
                description="Database query slowdown",
                progression="exponential"  # DB degradation often accelerates
            ),
            EpisodeConfig(
                level=2,
                topology_size=10,
                duration=600,
                fault_type="connection_exhaustion",
                fault_target_role="database",
                export_interval=5,
                description="Database connection pool exhaustion",
                progression="linear"
            ),
            EpisodeConfig(
                level=2,
                topology_size=10,
                duration=600,
                fault_type="enable_background_job",
                fault_target_role="database",
                export_interval=5,
                description="Database background job contention",
                progression="step"  # Background jobs often start suddenly
            ),
        ]

    def _get_level3_scenarios(self) -> List[EpisodeConfig]:
        """Level 3: Complex interactions (caches, queues, multi-tenancy)."""
        return [
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,  # 15 minutes
                fault_type="cache_failure",
                fault_target_role="cache",
                export_interval=10,
                description="Cache failure causing thundering herd",
                progression="step"  # Cache failures are often sudden
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="inject_latency",
                fault_target_role="cache",
                export_interval=10,
                description="Cache latency spike",
                progression="linear"
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="queue_consumer_slowdown",
                fault_target_role="queue",
                export_interval=10,
                description="Message queue backlog",
                progression="exponential"  # Queue backlogs compound exponentially
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="hot_shard",
                fault_target_role="service",
                export_interval=10,
                description="Hot shard causing traffic skew",
                progression="step"  # Traffic shifts are often sudden
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="force_deadlock",
                fault_target_role="service",
                export_interval=10,
                description="Thread deadlock causing request queueing",
                progression="step"  # Deadlocks occur suddenly
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="noisy_neighbor",
                fault_target_role="service",
                export_interval=10,
                description="Noisy neighbor causing CPU contention",
                progression="linear"  # Resource contention can build gradually
            ),
        ]

    def _get_level4_scenarios(self) -> List[EpisodeConfig]:
        """Level 4: External dependencies and network failures (black swan events)."""
        return [
            EpisodeConfig(
                level=4,
                topology_size=25,
                duration=600,  # 10 minutes
                fault_type="inject_latency",
                fault_target_role="external",
                export_interval=5,
                description="External API latency spike",
                progression="linear"
            ),
            EpisodeConfig(
                level=4,
                topology_size=25,
                duration=600,
                fault_type="inject_errors",
                fault_target_role="external",
                export_interval=5,
                description="External API error rate increase",
                progression="step"  # External failures often happen suddenly
            ),
            EpisodeConfig(
                level=4,
                topology_size=25,
                duration=600,
                fault_type="network_partition",
                fault_target_role="network",
                export_interval=5,
                description="Network partition between components",
                progression="step"  # Network splits are sudden
            ),
        ]

    def get_curriculum_distribution(self) -> dict:
        """
        Get recommended distribution of levels for training.

        Returns:
            Dictionary with level weights
        """
        return {
            1: 0.1,   # 10% easy
            2: 0.3,   # 30% medium
            3: 0.4,   # 40% hard
            4: 0.2,   # 20% very hard (black swan)
        }

    def sample_level(self, seed: int = None) -> int:
        """
        Sample a difficulty level based on curriculum distribution.

        Args:
            seed: Random seed (optional)

        Returns:
            Level (1-4)
        """
        rng = random.Random(seed)
        dist = self.get_curriculum_distribution()
        levels = list(dist.keys())
        weights = [dist[l] for l in levels]
        return rng.choices(levels, weights=weights)[0]
