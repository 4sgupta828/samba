"""
Data models for forensic analysis.

Contains all dataclasses and enums used throughout the forensic analysis system.
"""

import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Dict, List, Tuple, Optional, Any


class HealthState(Enum):
    """System health states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    FAILED = "failed"


class BottleneckType(Enum):
    """Types of bottlenecks."""
    CPU = "cpu"
    MEMORY = "memory"
    THREAD_POOL = "thread_pool"
    CONNECTION_POOL = "connection_pool"
    QUEUE_DEPTH = "queue_depth"
    NETWORK = "network"
    DATABASE = "database"
    CACHE = "cache"
    EXTERNAL_SERVICE = "external_service"


@dataclass
class CrashEvent:
    """Represents a single crash event."""
    component_id: str
    component_type: str
    crash_time: float
    crash_reason: str
    memory_at_crash: Optional[float]
    cpu_at_crash: Optional[float]
    thread_pool_at_crash: Optional[int]
    queue_depth_at_crash: Optional[int]
    restart_attempts: int
    recovery_time: Optional[float]
    recovered: bool
    crash_loop_detected: bool

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ComponentDegradation:
    """Degradation analysis for a component."""
    component_id: str
    component_type: str
    degradation_pct: float  # Overall degradation percentage
    baseline_metrics: Dict[str, float]  # Healthy baseline values
    degraded_metrics: Dict[str, float]  # Degraded values
    metric_degradations: Dict[str, float]  # Per-metric degradation %
    start_time: float
    end_time: Optional[float]
    severity: str  # "mild", "moderate", "severe", "critical"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BottleneckAnalysis:
    """Analysis of a bottleneck condition."""
    component_id: str
    component_type: str
    bottleneck_type: BottleneckType
    start_time: float
    end_time: Optional[float]
    duration: Optional[float]
    severity: str  # "mild", "moderate", "severe", "critical"
    peak_value: float
    capacity: float
    utilization_pct: float
    impact: str  # Description of impact
    contributing_factors: List[str]
    degradation_pct: float  # Added: percentage degradation

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['bottleneck_type'] = self.bottleneck_type.value
        return result


@dataclass
class QueueAnalysis:
    """Analysis of message queue behavior."""
    queue_id: str
    normal_depth: float
    peak_depth: float
    depth_at_end: float
    backlog_started: Optional[float]
    backlog_cleared: Optional[float]
    producers: List[str]
    consumers: List[str]
    producer_failures: List[Tuple[str, float]]  # (producer_id, failure_time)
    consumer_failures: List[Tuple[str, float]]  # (consumer_id, failure_time)
    backlog_cause: str
    recovery_possible: bool

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CascadeChain:
    """Represents a cascade of failures."""
    cascade_id: int
    root_component: str
    chain: List[Tuple[str, float, str, float]]  # (component, time, mechanism, degradation_pct)
    total_components_affected: int
    cascade_duration: float
    cascade_type: str  # "error", "latency", "resource_exhaustion", "circuit_breaker"
    layers: List[List[str]]  # Components grouped by cascade layer/level
    impact_summary: str  # Human-readable summary

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CircuitBreakerEvent:
    """Circuit breaker state change event."""
    source_component: str
    target_component: str
    timestamp: float
    new_state: float  # 0.0=closed, 0.5=half-open, 1.0=open
    reason: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SystemHealthSnapshot:
    """Snapshot of system health at a point in time."""
    timestamp: float
    overall_health: HealthState
    healthy_services: int
    degraded_services: int
    failed_services: int
    active_bottlenecks: int
    open_circuit_breakers: int
    queue_backlogs: int
    error_rate: float
    avg_latency: float

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['overall_health'] = self.overall_health.value
        return result


@dataclass
class RecoveryRecommendation:
    """Recommendation for system recovery."""
    priority: str  # "critical", "high", "medium", "low"
    component_id: str
    component_type: str
    issue: str
    recommendation: str
    estimated_impact: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ForensicReport:
    """Complete forensic analysis report."""
    episode_id: str
    simulation_duration: float
    fault_injection_time: float
    fault_type: str
    root_cause_component: str

    # Core analyses
    component_degradations: List[ComponentDegradation]  # NEW: Per-component degradation %
    bottlenecks: List[BottleneckAnalysis]
    crashes: List[CrashEvent]
    queue_analyses: List[QueueAnalysis]
    cascades: List[CascadeChain]
    circuit_breaker_events: List[CircuitBreakerEvent]

    # Propagation tracking
    error_propagation_timeline: List[Tuple[float, str, float]]  # (time, component, error_rate)
    latency_propagation_timeline: List[Tuple[float, str, float]]  # (time, component, latency)

    # Health tracking
    health_timeline: List[SystemHealthSnapshot]
    initial_health: SystemHealthSnapshot
    final_health: SystemHealthSnapshot

    # Recovery analysis
    system_recovered: bool
    recovery_recommendations: List[RecoveryRecommendation]

    # Summary statistics
    summary: Dict[str, Any]

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = {
            'episode_id': self.episode_id,
            'simulation_duration': self.simulation_duration,
            'fault_injection_time': self.fault_injection_time,
            'fault_type': self.fault_type,
            'root_cause_component': self.root_cause_component,
            'component_degradations': [d.to_dict() for d in self.component_degradations],
            'bottlenecks': [b.to_dict() for b in self.bottlenecks],
            'crashes': [c.to_dict() for c in self.crashes],
            'queue_analyses': [q.to_dict() for q in self.queue_analyses],
            'cascades': [c.to_dict() for c in self.cascades],
            'circuit_breaker_events': [cb.to_dict() for cb in self.circuit_breaker_events],
            'error_propagation_timeline': self.error_propagation_timeline,
            'latency_propagation_timeline': self.latency_propagation_timeline,
            'health_timeline': [h.to_dict() for h in self.health_timeline],
            'initial_health': self.initial_health.to_dict(),
            'final_health': self.final_health.to_dict(),
            'system_recovered': self.system_recovered,
            'recovery_recommendations': [r.to_dict() for r in self.recovery_recommendations],
            'summary': self.summary
        }
        return result

    def to_json(self, filepath: Optional[str] = None, indent: int = 2) -> str:
        """Convert to JSON."""
        json_str = json.dumps(self.to_dict(), indent=indent, default=str)

        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)

        return json_str
