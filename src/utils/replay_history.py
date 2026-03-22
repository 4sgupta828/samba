"""
Replay History Management

Manages a chronological history of fault scenario runs for replay and regression testing.
Default history path: ~/dataraft/repeatfaults/history.jsonl
(override with DATARAFT_REPLAY_DIR or legacy SAMBA_REPLAY_DIR)
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class ReplayHistoryManager:
    """Manages the history of fault scenario runs for reproducibility."""

    def __init__(self, history_dir: str = None):
        """
        Initialize the replay history manager.

        Args:
            history_dir: Directory to store history (default: ~/dataraft/repeatfaults/)
        """
        if history_dir is None:
            history_dir = os.environ.get('DATARAFT_REPLAY_DIR') or os.environ.get(
                'SAMBA_REPLAY_DIR'
            )
            if not history_dir:
                home = Path.home()
                history_dir = os.path.join(home, 'dataraft', 'repeatfaults')

        self.history_dir = Path(history_dir)
        self.history_file = self.history_dir / 'history.jsonl'

        # Create directory if it doesn't exist
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def add_run(self, run_params_path: str, tags: List[str] = None, notes: str = None, outcome: str = 'success'):
        """
        Add a completed run to the history.

        Args:
            run_params_path: Path to the run_parameters.json file
            tags: Optional tags for categorization (e.g., ['deadlock', 'notification_service'])
            notes: Optional notes about this run
            outcome: Outcome of the run ('success', 'failed', 'regression')
        """
        # Load the run parameters
        with open(run_params_path, 'r') as f:
            run_params = json.load(f)

        # Check for duplicates based on key parameters
        existing_runs = self.list_runs()
        for existing in existing_runs:
            existing_summary = existing.get('summary', {})
            # Check if this is a duplicate (same topology, fault, root cause, and phi)
            if (existing_summary.get('topology') == run_params['topology']['name'] and
                existing_summary.get('fault_type') == run_params['fault']['type'] and
                existing_summary.get('root_cause') == run_params['fault']['root_cause_node'] and
                abs(existing_summary.get('phi', 0) - run_params['capacity']['phi']) < 0.001):

                # This is a replay - skip adding to history
                print(f"  [History] Skipping duplicate scenario (already in history)")
                return existing

        # Create history entry with CACHED run_parameters for persistence
        entry = {
            'added_at': datetime.now().isoformat(),
            'run_params_path': str(run_params_path),
            'run_params_cached': run_params,  # Cache full params in case file is deleted
            'outcome': outcome,
            'tags': tags or [],
            'notes': notes or '',
            'summary': {
                'topology': run_params['topology']['name'],
                'fault_type': run_params['fault']['type'],
                'root_cause': run_params['fault']['root_cause_node'],
                'phi': run_params['capacity']['phi'],
                'domain': run_params['topology'].get('domain', 'unknown')
            }
        }

        # Append to history file (JSONL format - one entry per line)
        with open(self.history_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

        print(f"  ✓ Added new scenario to replay history")
        return entry

    def list_runs(self, filter_tags: List[str] = None, filter_outcome: str = None) -> List[Dict]:
        """
        List all runs in history with optional filtering.

        Args:
            filter_tags: Only return runs with these tags
            filter_outcome: Only return runs with this outcome

        Returns:
            List of history entries
        """
        if not self.history_file.exists():
            return []

        entries = []
        with open(self.history_file, 'r') as f:
            for line in f:
                entry = json.loads(line.strip())

                # Apply filters
                if filter_tags:
                    if not any(tag in entry['tags'] for tag in filter_tags):
                        continue

                if filter_outcome and entry['outcome'] != filter_outcome:
                    continue

                entries.append(entry)

        return entries

    def search_runs(self, topology: str = None, fault_type: str = None, root_cause: str = None) -> List[Dict]:
        """
        Search for runs by topology, fault type, or root cause.

        Args:
            topology: Topology name to search for
            fault_type: Fault type to search for
            root_cause: Root cause component to search for

        Returns:
            List of matching history entries
        """
        all_runs = self.list_runs()
        results = []

        for entry in all_runs:
            summary = entry['summary']
            match = True

            if topology and topology.lower() not in summary['topology'].lower():
                match = False

            if fault_type and fault_type.lower() != summary['fault_type'].lower():
                match = False

            if root_cause and root_cause.lower() != summary['root_cause'].lower():
                match = False

            if match:
                results.append(entry)

        return results

    def get_recent_runs(self, limit: int = 10) -> List[Dict]:
        """
        Get the most recent runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of most recent history entries
        """
        all_runs = self.list_runs()
        # Reverse to get most recent first
        return list(reversed(all_runs[-limit:]))

    def export_summary(self, output_path: str = None):
        """
        Export a summary of all runs to a JSON file.

        Args:
            output_path: Path to save summary (default: history_dir/summary.json)
        """
        if output_path is None:
            output_path = self.history_dir / 'summary.json'

        all_runs = self.list_runs()

        # Generate statistics
        summary = {
            'total_runs': len(all_runs),
            'by_outcome': {},
            'by_fault_type': {},
            'by_topology': {},
            'recent_runs': self.get_recent_runs(5)
        }

        # Count by outcome
        for entry in all_runs:
            outcome = entry['outcome']
            summary['by_outcome'][outcome] = summary['by_outcome'].get(outcome, 0) + 1

            fault_type = entry['summary']['fault_type']
            summary['by_fault_type'][fault_type] = summary['by_fault_type'].get(fault_type, 0) + 1

            topology = entry['summary']['topology']
            summary['by_topology'][topology] = summary['by_topology'].get(topology, 0) + 1

        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)

        return summary


def add_to_history(run_params_path: str, tags: List[str] = None, notes: str = None, outcome: str = 'success'):
    """
    Convenience function to add a run to history.

    Args:
        run_params_path: Path to the run_parameters.json file
        tags: Optional tags for categorization
        notes: Optional notes about this run
        outcome: Outcome of the run ('success', 'failed', 'regression')
    """
    manager = ReplayHistoryManager()
    return manager.add_run(run_params_path, tags, notes, outcome)


if __name__ == '__main__':
    # Example usage and testing
    manager = ReplayHistoryManager()

    # List recent runs
    recent = manager.get_recent_runs(5)
    print(f"Recent runs: {len(recent)}")
    for entry in recent:
        print(f"  - {entry['summary']['fault_type']} on {entry['summary']['root_cause']} (phi={entry['summary']['phi']:.2f})")

    # Export summary
    summary = manager.export_summary()
    print(f"\nTotal runs in history: {summary['total_runs']}")
    print(f"By outcome: {summary['by_outcome']}")
