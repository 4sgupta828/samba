#!/usr/bin/env python3
"""
Fault Type Progress Tracker

Tracks which fault types have been successfully generated to avoid regeneration.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Set


class FaultProgressTracker:
    """Tracks completion status of fault type episode generation."""

    def __init__(self, progress_file: str = "data/fault_generation_progress.json"):
        """
        Initialize tracker.

        Args:
            progress_file: Path to JSON file storing progress
        """
        self.progress_file = progress_file
        self.progress = self._load_progress()

    def _load_progress(self) -> Dict[str, List[str]]:
        """Load progress from disk."""
        if os.path.exists(self.progress_file):
            with open(self.progress_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_progress(self):
        """Save progress to disk."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.progress_file), exist_ok=True)

        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def is_completed(self, fault_key: str) -> bool:
        """
        Check if a fault type has been successfully generated.

        Args:
            fault_key: Fault type-role combination (e.g., "cpu_saturation:service")

        Returns:
            True if fault type has successful episode
        """
        return fault_key in self.progress and len(self.progress[fault_key]) > 0

    def mark_completed(self, fault_key: str, episode_path: str):
        """
        Mark a fault type as successfully generated.

        Args:
            fault_key: Fault type-role combination
            episode_path: Path to the generated episode
        """
        if fault_key not in self.progress:
            self.progress[fault_key] = []

        # Add episode path if not already tracked
        if episode_path not in self.progress[fault_key]:
            self.progress[fault_key].append(episode_path)

        self._save_progress()

    def get_completed_fault_types(self) -> Set[str]:
        """Get set of all completed fault types."""
        return set(self.progress.keys())

    def get_episode_paths(self, fault_key: str) -> List[str]:
        """Get all episode paths for a fault type."""
        return self.progress.get(fault_key, [])

    def get_summary(self) -> Dict:
        """Get summary of progress."""
        return {
            "total_completed": len(self.progress),
            "by_fault_type": {
                fault_key: len(paths)
                for fault_key, paths in self.progress.items()
            }
        }

    def reset(self):
        """Clear all progress."""
        self.progress = {}
        self._save_progress()
