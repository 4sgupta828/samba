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
                description="Single service CPU saturation"
            ),
            EpisodeConfig(
                level=1,
                topology_size=5,
                duration=300,
                fault_type="memory_leak",
                fault_target_role="service",
                export_interval=5,
                description="Single service memory leak"
            ),
            EpisodeConfig(
                level=1,
                topology_size=5,
                duration=300,
                fault_type="inject_latency",
                fault_target_role="service",
                export_interval=5,
                description="Single service latency spike"
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
                description="Database query slowdown"
            ),
            EpisodeConfig(
                level=2,
                topology_size=10,
                duration=600,
                fault_type="connection_exhaustion",
                fault_target_role="database",
                export_interval=5,
                description="Database connection pool exhaustion"
            ),
            EpisodeConfig(
                level=2,
                topology_size=10,
                duration=600,
                fault_type="enable_background_job",
                fault_target_role="database",
                export_interval=5,
                description="Database background job contention"
            ),
        ]

    def _get_level3_scenarios(self) -> List[EpisodeConfig]:
        """Level 3: Complex interactions (caches, queues)."""
        return [
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,  # 15 minutes
                fault_type="cache_failure",
                fault_target_role="cache",
                export_interval=10,
                description="Cache failure causing thundering herd"
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="inject_latency",
                fault_target_role="cache",
                export_interval=10,
                description="Cache latency spike"
            ),
            EpisodeConfig(
                level=3,
                topology_size=20,
                duration=900,
                fault_type="queue_consumer_slowdown",
                fault_target_role="queue",
                export_interval=10,
                description="Message queue backlog"
            ),
        ]

    def _get_level4_scenarios(self) -> List[EpisodeConfig]:
        """Level 4: External dependencies (black swan events)."""
        return [
            EpisodeConfig(
                level=4,
                topology_size=25,
                duration=600,  # 10 minutes
                fault_type="inject_latency",
                fault_target_role="external",
                export_interval=5,
                description="External API latency spike"
            ),
            EpisodeConfig(
                level=4,
                topology_size=25,
                duration=600,
                fault_type="inject_errors",
                fault_target_role="external",
                export_interval=5,
                description="External API error rate increase"
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
