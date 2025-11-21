"""
Ground Truth and Causality Tracking Module.

This module provides the CausalityTracker singleton that acts as an "oracle"
during simulation runs. It records the exact root cause of failures and tracks
the complete propagation chain of impacts through the system.
"""
import dataclasses
import json
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class FailureInfo:
    """Information about a failure that occurred in the system."""
    component_id: str
    component_type: str
    failure_mode: str
    params: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ImpactRecord:
    """Records a single impact event in the failure propagation chain."""
    component_id: str
    component_type: str
    impact_type: str
    timestamp: float
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class IncidentReport:
    """Complete incident report containing root cause and propagation chain."""
    incident_id: str
    start_time: float
    root_cause: FailureInfo
    end_time: Optional[float] = None
    propagation_chain: List[ImpactRecord] = dataclasses.field(default_factory=list)
    symptoms: List[str] = dataclasses.field(default_factory=list)

    def to_json(self) -> str:
        """Serialize the incident report to JSON."""
        return json.dumps(dataclasses.asdict(self), indent=2)


class CausalityTracker:
    """
    Singleton tracker that maintains ground truth about incidents.

    This class is responsible for:
    - Starting new incidents when failures are injected
    - Recording the propagation of impacts through the system
    - Ending incidents and generating complete reports
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CausalityTracker, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.active_incident: Optional[IncidentReport] = None
        self.incident_counter = 0
        self._initialized = True

    def start_incident(
        self,
        sim_time: float,
        root_cause_component_id: str,
        root_cause_component_type: str,
        failure_mode: str,
        params: Dict
    ):
        """Start tracking a new incident."""
        self.incident_counter += 1
        incident_id = f"inc_{self.incident_counter:03d}"
        self.active_incident = IncidentReport(
            incident_id=incident_id,
            start_time=sim_time,
            root_cause=FailureInfo(
                component_id=root_cause_component_id,
                component_type=root_cause_component_type,
                failure_mode=failure_mode,
                params=params
            )
        )
        print(f"[{sim_time:.2f}s] CausalityTracker: Started Incident {incident_id}")

    def record_impact(
        self,
        sim_time: float,
        component_id: str,
        component_type: str,
        impact_type: str,
        details: Dict
    ):
        """Record an impact event in the active incident's propagation chain."""
        if self.active_incident:
            self.active_incident.propagation_chain.append(
                ImpactRecord(
                    component_id=component_id,
                    component_type=component_type,
                    impact_type=impact_type,
                    timestamp=sim_time,
                    details=details
                )
            )

    def end_incident(self, sim_time: float) -> Optional[IncidentReport]:
        """End the active incident and return the complete report."""
        if not self.active_incident:
            return None

        self.active_incident.end_time = sim_time
        report = self.active_incident
        self.active_incident = None
        print(f"[{sim_time:.2f}s] CausalityTracker: Ended Incident {report.incident_id}")
        return report

    def reset(self):
        """Reset the tracker to initial state."""
        self.active_incident = None
        self.incident_counter = 0
