"""
Unified Scenario Event Model - First-class representation of all injected scenarios.

This module provides a unified model for tracking all simulation scenarios including:
- Failure injections
- Deployments
- Configuration changes
- Instance lifecycle events (restarts, terminations, additions)

These events represent the ground truth for anomalies and are used for:
1. RCA training data
2. UI visualization markers
3. Correlation analysis
"""

import dataclasses
import json
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime


def sim_time_to_timestamp(sim_time: float, simulation_start_timestamp_ns: int) -> str:
    """
    Convert simulation time to ISO timestamp string.

    Args:
        sim_time: Simulation time in seconds
        simulation_start_timestamp_ns: Base timestamp in nanoseconds

    Returns:
        ISO format timestamp string
    """
    timestamp_ns = simulation_start_timestamp_ns + int(sim_time * 1_000_000_000)
    timestamp_dt = datetime.utcfromtimestamp(timestamp_ns / 1_000_000_000)
    return timestamp_dt.isoformat()


class ScenarioEventType(Enum):
    """Types of scenario events that can occur in the simulation."""
    FAILURE_INJECTION = "failure_injection"
    FAILURE_REVERT = "failure_revert"
    DEPLOYMENT = "deployment"
    DEPLOYMENT_ROLLBACK = "deployment_rollback"
    CONFIG_CHANGE = "config_change"
    INSTANCE_START = "instance_start"
    INSTANCE_RESTART = "instance_restart"
    INSTANCE_TERMINATE = "instance_terminate"
    SCALING_EVENT = "scaling_event"
    INFRASTRUCTURE_CHANGE = "infrastructure_change"


@dataclasses.dataclass
class ScenarioEvent:
    """
    First-class representation of a scenario event.

    This represents ground truth for anomalies that can be used for:
    - Independent RCA training
    - UI chronological display
    - Impact correlation analysis
    """
    # Core identification
    event_id: str                    # Unique identifier for this event
    event_type: ScenarioEventType    # Type of event

    # Timing information
    sim_time: float                  # Simulation time when event was injected (seconds)
    timestamp: str                   # ISO format timestamp for visualization

    # Affected components
    affected_components: List[str]   # List of component IDs affected by this event

    # Event description
    description: str                 # Human-readable description of the event

    # Change parameters - all parameters that define the change
    parameters: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # Categorization
    category: Optional[str] = None   # Category for grouping (e.g., "performance", "availability")
    severity: Optional[str] = None   # Severity level (e.g., "low", "medium", "high", "critical")

    # Additional metadata
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "sim_time": self.sim_time,
            "timestamp": self.timestamp,
            "affected_components": self.affected_components,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "severity": self.severity,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScenarioEvent':
        """Create from dictionary."""
        data = data.copy()
        data['event_type'] = ScenarioEventType(data['event_type'])
        return cls(**data)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class ScenarioEventTracker:
    """
    Central tracker for all scenario events during simulation.

    This singleton maintains a chronological list of all injected scenarios
    and provides methods to query and export them.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ScenarioEventTracker, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.events: List[ScenarioEvent] = []
        self._initialized = True

    def reset(self):
        """Reset the tracker (useful for new simulation runs)."""
        self.events = []

    def add_event(self, event: ScenarioEvent):
        """Add a new scenario event."""
        self.events.append(event)

    def add_failure_injection(
        self,
        event_id: str,
        sim_time: float,
        timestamp: str,
        mode: str,
        targets: List[str],
        params: Dict[str, Any],
        is_revert: bool = False
    ) -> ScenarioEvent:
        """Add a failure injection event."""
        event_type = ScenarioEventType.FAILURE_REVERT if is_revert else ScenarioEventType.FAILURE_INJECTION

        description = f"{'Reverted' if is_revert else 'Injected'} failure mode '{mode}' on {len(targets)} component(s)"
        if params:
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            description += f" ({param_str})"

        event = ScenarioEvent(
            event_id=event_id,
            event_type=event_type,
            sim_time=sim_time,
            timestamp=timestamp,
            affected_components=targets,
            description=description,
            parameters={
                "failure_mode": mode,
                **params
            },
            category="failure",
            severity="high" if not is_revert else None,
            metadata={
                "is_revert": is_revert,
                "mode": mode
            }
        )
        self.add_event(event)
        return event

    def add_deployment_event(
        self,
        event_id: str,
        sim_time: float,
        timestamp: str,
        service_name: str,
        commit_id: str,
        commit_message: str,
        affected_components: List[str],
        changes_applied: Dict[str, Any],
        is_rollback: bool = False,
        author: str = "unknown"
    ) -> ScenarioEvent:
        """Add a deployment event."""
        event_type = ScenarioEventType.DEPLOYMENT_ROLLBACK if is_rollback else ScenarioEventType.DEPLOYMENT

        description = f"{'Rolled back' if is_rollback else 'Deployed'} {service_name}: {commit_message}"

        event = ScenarioEvent(
            event_id=event_id,
            event_type=event_type,
            sim_time=sim_time,
            timestamp=timestamp,
            affected_components=affected_components,
            description=description,
            parameters=changes_applied,
            category="deployment",
            severity="medium",
            metadata={
                "service_name": service_name,
                "commit_id": commit_id,
                "commit_message": commit_message,
                "author": author,
                "is_rollback": is_rollback
            }
        )
        self.add_event(event)
        return event

    def add_instance_lifecycle_event(
        self,
        event_id: str,
        sim_time: float,
        timestamp: str,
        component_id: str,
        event_type: ScenarioEventType,
        reason: str = "",
        metadata: Dict[str, Any] = None
    ) -> ScenarioEvent:
        """Add an instance lifecycle event (start, restart, terminate)."""
        descriptions = {
            ScenarioEventType.INSTANCE_START: f"Instance {component_id} started",
            ScenarioEventType.INSTANCE_RESTART: f"Instance {component_id} restarted",
            ScenarioEventType.INSTANCE_TERMINATE: f"Instance {component_id} terminated"
        }

        description = descriptions.get(event_type, f"Instance {component_id} lifecycle event")
        if reason:
            description += f": {reason}"

        event = ScenarioEvent(
            event_id=event_id,
            event_type=event_type,
            sim_time=sim_time,
            timestamp=timestamp,
            affected_components=[component_id],
            description=description,
            parameters={},
            category="instance_lifecycle",
            severity="low",
            metadata=metadata or {}
        )
        self.add_event(event)
        return event

    def add_infrastructure_change_event(
        self,
        event_id: str,
        sim_time: float,
        timestamp: str,
        target_component: str,
        parameter: str,
        delta: float,
        duration: float,
        progression: str = "linear",
        linked_service: Optional[str] = None,
        linked_deployment: Optional[str] = None,
        reason: Optional[str] = None
    ) -> ScenarioEvent:
        """Add an infrastructure behavioral change event."""
        description = f"Infrastructure change on {target_component}: {parameter} "
        if delta > 0:
            description += f"increases by {delta}"
        else:
            description += f"decreases by {abs(delta)}"
        description += f" over {duration}s ({progression})"

        if reason:
            description += f" - {reason}"

        metadata = {
            "linked_service": linked_service,
            "linked_deployment": linked_deployment,
            "reason": reason,
            "progression": progression
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        event = ScenarioEvent(
            event_id=event_id,
            event_type=ScenarioEventType.INFRASTRUCTURE_CHANGE,
            sim_time=sim_time,
            timestamp=timestamp,
            affected_components=[target_component],
            description=description,
            parameters={
                "parameter": parameter,
                "delta": delta,
                "duration": duration,
                "progression": progression
            },
            category="infrastructure",
            severity="medium",
            metadata=metadata
        )
        self.add_event(event)
        return event

    def get_events(
        self,
        event_type: Optional[ScenarioEventType] = None,
        category: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[ScenarioEvent]:
        """
        Query events with optional filters.

        Args:
            event_type: Filter by event type
            category: Filter by category
            start_time: Filter events after this sim_time
            end_time: Filter events before this sim_time

        Returns:
            List of matching events, sorted by sim_time
        """
        filtered = self.events

        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]

        if category:
            filtered = [e for e in filtered if e.category == category]

        if start_time is not None:
            filtered = [e for e in filtered if e.sim_time >= start_time]

        if end_time is not None:
            filtered = [e for e in filtered if e.sim_time <= end_time]

        return sorted(filtered, key=lambda e: e.sim_time)

    def get_events_by_component(self, component_id: str) -> List[ScenarioEvent]:
        """Get all events affecting a specific component."""
        return [e for e in self.events if component_id in e.affected_components]

    def export_to_dict(self) -> List[Dict[str, Any]]:
        """Export all events to a list of dictionaries."""
        return [event.to_dict() for event in sorted(self.events, key=lambda e: e.sim_time)]

    def export_to_json(self, file_path: str, include_summary: bool = True, simulation_name: str = None):
        """
        Export all events to a JSON file with optional summary.

        Args:
            file_path: Path to save the JSON file
            include_summary: If True, includes summary statistics
            simulation_name: Optional name for the simulation based on scenario type
        """
        if include_summary:
            data = {
                "version": "1.0",
                "description": "Ground truth scenario events - injected anomalies for RCA training",
                "summary": self.get_summary(),
                "events": self.export_to_dict()
            }
            if simulation_name:
                data["simulation_name"] = simulation_name
        else:
            data = self.export_to_dict()
            if simulation_name:
                data["simulation_name"] = simulation_name

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all events."""
        by_type = {}
        by_category = {}

        for event in self.events:
            event_type_str = event.event_type.value
            by_type[event_type_str] = by_type.get(event_type_str, 0) + 1

            if event.category:
                by_category[event.category] = by_category.get(event.category, 0) + 1

        return {
            "total_events": len(self.events),
            "by_type": by_type,
            "by_category": by_category,
            "time_range": {
                "start": min((e.sim_time for e in self.events), default=0),
                "end": max((e.sim_time for e in self.events), default=0)
            }
        }
