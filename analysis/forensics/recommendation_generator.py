"""
Recovery recommendation generation for forensic investigations.

Generates service/node-specific recovery recommendations.
"""

from typing import List
from .models import (
    RecoveryRecommendation, CrashEvent, BottleneckAnalysis,
    QueueAnalysis, BottleneckType
)


class RecommendationGenerator:
    """Generates recovery recommendations."""

    def __init__(
        self,
        crashes: List[CrashEvent],
        bottlenecks: List[BottleneckAnalysis],
        queue_analyses: List[QueueAnalysis],
        simulation_duration: float
    ):
        self.crashes = crashes
        self.bottlenecks = bottlenecks
        self.queue_analyses = queue_analyses
        self.simulation_duration = simulation_duration

    def generate_recommendations(self) -> List[RecoveryRecommendation]:
        """Generate recovery recommendations based on analysis."""
        recommendations = []

        # Recommendations for crashed components
        for crash in self.crashes:
            if not crash.recovered:
                if 'OOM' in crash.crash_reason or (crash.memory_at_crash and crash.memory_at_crash > 512):
                    recommendations.append(RecoveryRecommendation(
                        priority='critical',
                        component_id=crash.component_id,
                        component_type=crash.component_type,
                        issue=f"Component in CrashLoopBackOff due to OOM (peak {crash.memory_at_crash:.0f}MB)",
                        recommendation=f"Increase memory limit to at least {int(crash.memory_at_crash * 1.5)}MB and investigate memory leak",
                        estimated_impact="Restore service availability, clear queue backlog"
                    ))

                if crash.queue_depth_at_crash and crash.queue_depth_at_crash > 5000:
                    recommendations.append(RecoveryRecommendation(
                        priority='high',
                        component_id=crash.component_id,
                        component_type=crash.component_type,
                        issue=f"Thread pool exhausted with {int(crash.queue_depth_at_crash)} queued requests",
                        recommendation="Increase thread pool size to 100-200 threads and implement request shedding",
                        estimated_impact="Prevent request accumulation and memory growth"
                    ))

        # Recommendations for bottlenecks
        for bottleneck in self.bottlenecks:
            if bottleneck.end_time is None or bottleneck.end_time >= self.simulation_duration - 30:
                if bottleneck.bottleneck_type == BottleneckType.CACHE:
                    recommendations.append(RecoveryRecommendation(
                        priority='critical',
                        component_id=bottleneck.component_id,
                        component_type=bottleneck.component_type,
                        issue="Cache unavailable causing thundering herd to database",
                        recommendation="Restore cache service immediately, consider cache replication/failover",
                        estimated_impact="Reduce database load by 70-90%, restore normal latencies"
                    ))

        # Recommendations for queue backlogs
        for queue in self.queue_analyses:
            if queue.depth_at_end > queue.normal_depth * 5:
                recommendations.append(RecoveryRecommendation(
                    priority='high',
                    component_id=queue.queue_id,
                    component_type='MessageQueue',
                    issue=f"Queue backlog at {int(queue.depth_at_end)} messages (normal: {int(queue.normal_depth)})",
                    recommendation=f"Restore consumer services ({', '.join([c[0] for c in queue.consumer_failures])}) or scale up consumers",
                    estimated_impact="Clear backlog, restore async processing"
                ))

        # Sort by priority
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        recommendations.sort(key=lambda r: priority_order[r.priority])

        return recommendations
