"""
self_health_analyzer.py

Analyzes INTERNAL degradation with PRIMARY vs SECONDARY symptom classification.
Integrates battle-tested queue analysis and threshold configuration.

SOTA Features:
1. Primary Symptoms (Cause): Resource saturation, deadlocks, queue faults
2. Secondary Symptoms (Effect): Latency spikes, error increases
3. Queue-aware analysis: Distinguishes real queue faults from normal buffering
4. Blackbox inference: Virtual sensors for external dependencies
5. Adaptive thresholds: Configurable for different environments
"""

import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass
from statistical_utils import compare_distributions, StatResult
from config_extractor import ConfigExtractor

@dataclass
class SelfHealthResult:
    node_id: str
    is_root_cause_candidate: bool
    self_degradation_score: float
    symptom_type: str  # 'primary' (Cause) vs 'secondary' (Effect)
    symptoms: List[str]
    confidence: str = 'medium'  # 'high', 'medium', 'low'

class SelfHealthAnalyzer:
    def __init__(self, config_extractor: ConfigExtractor = None, threshold_config=None):
        self.config_extractor = config_extractor or ConfigExtractor()

        # Load adaptive threshold configuration
        try:
            from rca_config import get_thresholds
            self.thresholds = get_thresholds(threshold_config)
        except ImportError:
            # Fallback to hardcoded thresholds if rca_config not available
            self.thresholds = type('obj', (), {
                'resource_saturation_threshold': 0.9,
                'min_effect_size_small': 0.5,
                'min_effect_size_medium': 1.0,
                'min_effect_size_large': 2.0,
                'min_effect_size_very_large': 3.0,
                'error_rate_minor': 0.01,
                'error_rate_moderate': 0.1,
                'error_rate_severe': 0.5,
                'thread_saturation_threshold': 0.8,
                'throughput_near_zero_absolute': 0.1,
                'was_active_absolute': 1.0
            })()

        # PRIMARY metrics: Internal resource constraints (The Smoking Gun)
        # Using RAW metric names from simulation
        self.primary_metrics = [
            'container.cpu.utilization', 'pod.cpu.utilization',
            'container.memory.usage_mb', 'pod.memory.usage',
            'thread_pool.threads.active', 'db.connections.active',
            'connection_pool.connections.active'
        ]

        # SECONDARY metrics: Outcome of degradation (The Smoke)
        # These are service-specific, will be built dynamically
        self.secondary_metric_suffixes = [
            'error_rate',  # service.{name}.error_rate
            'duration'     # service.{name}.duration
        ]

        # QUEUE metrics: Special handling (can be primary or secondary depending on root cause)
        self.queue_metrics = [
            'mq.messages.visible',      # Backlog waiting in queue
            'mq.messages.in_flight',    # Messages being processed
            'mq.messages.age_seconds',  # Staleness indicator
            'mq.queue.utilization',     # Capacity pressure
            'consumer.lag', 'queue.lag' # Consumer lag
        ]

    def _get_metric(self, data: Dict[str, np.ndarray], *possible_names) -> np.ndarray:
        """Try multiple possible metric names, return first found."""
        for name in possible_names:
            if name in data and len(data[name]) > 0:
                return data[name]
        return np.array([])

    def _normalize_metrics(self, node_id: str, data: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """Create normalized view with standard names for backward compatibility."""
        normalized = dict(data)  # Start with all raw metrics

        # Map raw names to standard names for backward compatibility
        normalized['cpu_usage'] = self._get_metric(data, 'container.cpu.utilization', 'pod.cpu.utilization', 'db.cpu.utilization')
        normalized['memory_usage'] = self._get_metric(data, 'container.memory.usage_mb', 'pod.memory.usage')
        normalized['thread_pool_active'] = self._get_metric(data, 'thread_pool.threads.active', 'db.connections.active', 'connection_pool.connections.active')
        normalized['thread_pool_queue'] = self._get_metric(data, 'thread_pool.queue.depth', 'connection_pool.queue_depth')

        # Service-specific metrics (build dynamically)
        normalized['avg_latency'] = self._get_metric(data, f'service.{node_id}.duration', 'db.query.latency')
        normalized['internal_error_rate'] = self._get_metric(data, f'service.{node_id}.error_rate')
        normalized['inbound_rps'] = self._get_metric(data, f'service.{node_id}.requests')

        # Cache-specific metrics (for external caches)
        normalized['cache_hit_rate'] = self._get_metric(data, 'cache.hit_rate')
        normalized['cache_errors'] = self._get_metric(data, 'component.errors.total')
        normalized['dependency_latency'] = self._get_metric(data, f'service.{node_id}.dependency.duration')
        normalized['dependency_error_rate'] = self._get_metric(data, f'service.{node_id}.dependency.error_rate')
        normalized['outbound_rps'] = self._get_metric(data, f'service.{node_id}.dependency.requests')

        # Queue metrics
        normalized['queue_depth'] = self._get_metric(data, 'mq.messages.visible', 'queue.depth')
        normalized['queue_in_flight'] = self._get_metric(data, 'mq.messages.in_flight')
        normalized['queue_age'] = self._get_metric(data, 'mq.messages.age_seconds')
        normalized['queue_utilization'] = self._get_metric(data, 'mq.queue.utilization')

        return normalized

    def analyze(self, node_id: str, node_type: str,
                baseline: Dict[str, np.ndarray],
                current: Dict[str, np.ndarray],
                topology=None,
                all_baseline_data: Dict[str, Dict[str, np.ndarray]] = None,
                all_current_data: Dict[str, Dict[str, np.ndarray]] = None) -> SelfHealthResult:
        """
        Analyze node self-health with dependency-aware error attribution.

        Args:
            node_id: Node to analyze
            node_type: Type of node (Service, Queue, etc.)
            baseline: Node's baseline metrics
            current: Node's current metrics
            topology: NetworkX DiGraph (optional, for dependency health check)
            all_baseline_data: All nodes' baseline data (optional, for dependency health check)
            all_current_data: All nodes' current data (optional, for dependency health check)
        """

        # 1. Standard Whitebox Analysis (If metrics exist)
        if current:
            # Normalize metrics to standard names for backward compatibility
            baseline_norm = self._normalize_metrics(node_id, baseline)
            current_norm = self._normalize_metrics(node_id, current)
            return self._analyze_whitebox(
                node_id, node_type, baseline_norm, current_norm,
                topology, all_baseline_data, all_current_data
            )

        # 2. No metrics? Return empty (Caller will handle Blackbox Inference)
        return SelfHealthResult(node_id, False, 0.0, 'secondary', [])

    def infer_blackbox_health(self, node_id: str,
                              callers_baseline: List[Dict],
                              callers_current: List[Dict]) -> SelfHealthResult:
        """
        Synthesizes health for a node based on what its Callers see.
        For blackbox external services without direct metrics.
        """
        symptoms = []
        score = 0.0

        # 1. Check Latency (The main signal for external APIs)
        base_lats = [np.mean(c.get('dependency_latency', [0])) for c in callers_baseline]
        curr_lats = [np.mean(c.get('dependency_latency', [0])) for c in callers_current]

        avg_base_lat = np.mean(base_lats) if base_lats else 0.0
        avg_curr_lat = np.mean(curr_lats) if curr_lats else 0.0

        if avg_curr_lat > 0.01:
            growth = (avg_curr_lat + 0.001) / (avg_base_lat + 0.001)
            if growth > 1.5:
                symptoms.append(f"Inferred High Latency ({growth:.1f}x from callers)")
                score = 10.0
            elif growth > 1.2:
                symptoms.append(f"Inferred Latency Elevation")
                score = 5.0

        # 2. Check Errors
        base_errs = [np.mean(c.get('dependency_error_rate', [0])) for c in callers_baseline]
        curr_errs = [np.mean(c.get('dependency_error_rate', [0])) for c in callers_current]

        avg_curr_err = np.mean(curr_errs) if curr_errs else 0.0
        avg_base_err = np.mean(base_errs) if base_errs else 0.0

        if avg_curr_err - avg_base_err > 0.01:
            symptoms.append(f"Inferred Error Spike ({(avg_curr_err*100):.1f}%)")
            score = 10.0

        # DECISION: Symptom Type
        # For a Blackbox, High Latency/Errors IS the root state (we can't see inside)
        # Treat as PRIMARY since it's the deepest we can observe
        symptom_type = 'primary' if score > 5.0 else 'secondary'

        return SelfHealthResult(
            node_id=node_id,
            is_root_cause_candidate=(score > 4.0),
            self_degradation_score=score,
            symptom_type=symptom_type,
            symptoms=symptoms
        )

    def _check_dependency_health(self, node_id, topology, all_current_data) -> Dict[str, Any]:
        """
        Check if node's dependencies are healthy.

        Returns:
            {
                'has_dependencies': bool,
                'dependencies_healthy': bool,  # All deps have error_rate < 5%
                'max_dep_error_rate': float,
                'degraded_deps': List[str]
            }
        """
        if not topology or not all_current_data:
            return {
                'has_dependencies': False,
                'dependencies_healthy': True,  # Conservative: assume healthy if can't check
                'max_dep_error_rate': 0.0,
                'degraded_deps': []
            }

        # Get dependencies (outgoing edges, excluding pods)
        dependencies = []
        for dep in topology.successors(node_id):
            dep_type = topology.nodes[dep].get('type', '')
            # Skip pod edges (control plane), only consider data plane dependencies
            if not topology.nodes[dep].get('parent_service'):
                dependencies.append(dep)

        if not dependencies:
            return {
                'has_dependencies': False,
                'dependencies_healthy': True,
                'max_dep_error_rate': 0.0,
                'degraded_deps': []
            }

        # Check error rates of dependencies
        degraded_deps = []
        max_error_rate = 0.0

        for dep in dependencies:
            dep_data = all_current_data.get(dep, {})
            if not dep_data:
                continue

            # Check for internal error rate
            error_rate_metric = None
            for key in dep_data.keys():
                if 'error_rate' in key.lower() and 'dependency' not in key.lower():
                    error_rate_metric = key
                    break

            if error_rate_metric:
                dep_error_rate = np.mean(dep_data[error_rate_metric])
                max_error_rate = max(max_error_rate, dep_error_rate)

                # Threshold: 5% is significant degradation
                if dep_error_rate > 0.05:
                    degraded_deps.append((dep, dep_error_rate))

        return {
            'has_dependencies': True,
            'dependencies_healthy': len(degraded_deps) == 0,
            'max_dep_error_rate': max_error_rate,
            'degraded_deps': degraded_deps
        }

    def _analyze_whitebox(self, node_id, node_type, baseline, current,
                          topology=None, all_baseline_data=None, all_current_data=None) -> SelfHealthResult:
        symptoms = []
        resource_score = 0.0
        performance_score = 0.0
        limp_mode_score = 0.0
        found_primary = False

        limits = self.config_extractor.get_limits_for_node(node_id, node_type)

        # === PHASE 1: PRIMARY SYMPTOMS (Resource Saturation) ===
        for metric in self.primary_metrics:
            if metric in current and metric in baseline:
                stat = compare_distributions(baseline[metric], current[metric])
                curr_max = np.max(current[metric]) if len(current[metric]) > 0 else 0

                limit_hit = False
                if metric == 'thread_pool_active' and curr_max > limits['max_threads'] * self.thresholds.resource_saturation_threshold:
                    symptoms.append(f"Thread Pool Saturation ({curr_max:.0f}/{limits['max_threads']})")
                    limit_hit = True

                if stat.significant and stat.effect_size > self.thresholds.min_effect_size_small:
                    symptoms.append(f"{metric} spike (d={stat.effect_size:.2f})")

                    if limit_hit or stat.effect_size > self.thresholds.min_effect_size_large:
                        resource_score = max(resource_score, 10.0)
                        found_primary = True
                    elif stat.effect_size > self.thresholds.min_effect_size_medium:
                        resource_score = max(resource_score, min(10.0, stat.effect_size * 2.5))
                        found_primary = True
                    else:
                        resource_score = max(resource_score, min(10.0, stat.effect_size * 2.5))

        # === PHASE 2: PRIMARY SYMPTOMS (Deadlock Detection) ===
        lat_stat = self._check_metric('avg_latency', baseline, current)
        cpu_stat = self._check_metric('cpu_usage', baseline, current)

        # Pattern A: High Latency + LOW CPU = Process is hung/deadlocked
        if lat_stat.effect_size > 1.5 and cpu_stat.effect_size < -0.2:
            symptoms.append("⚠️ Potential Deadlock (High Latency / Low CPU)")
            limp_mode_score = 10.0
            found_primary = True

        # Pattern B: Zombie Pod - Thread Saturation + Zero Throughput
        if 'thread_pool_active' in current and 'inbound_rps' in current:
            curr_threads = np.mean(current['thread_pool_active']) if len(current['thread_pool_active']) > 0 else 0
            curr_rps = np.mean(current['inbound_rps']) if len(current['inbound_rps']) > 0 else 0
            base_rps = np.mean(baseline.get('inbound_rps', np.array([0]))) if 'inbound_rps' in baseline else 0

            thread_saturation = curr_threads > limits['max_threads'] * self.thresholds.thread_saturation_threshold
            zero_throughput = curr_rps < self.thresholds.throughput_near_zero_absolute
            was_active = base_rps > self.thresholds.was_active_absolute

            if thread_saturation and zero_throughput and was_active:
                symptoms.append(f"⚠️ Zombie Pod (Thread Deadlock): {curr_threads:.0f}/{limits['max_threads']} threads, RPS {base_rps:.1f} → {curr_rps:.1f}")
                limp_mode_score = max(limp_mode_score, 10.0)
                found_primary = True

        # === PHASE 3: QUEUE METRICS (Can be PRIMARY or SECONDARY) ===
        # Use relaxed CV threshold (1.0) for high-variance queue metrics
        queue_fault_count = 0
        queue_buffering_count = 0

        for queue_metric in self.queue_metrics:
            if queue_metric in current and queue_metric in baseline:
                q_stat = compare_distributions(baseline[queue_metric], current[queue_metric], cv_threshold=1.0)

                # Use threshold of 0.5 (medium effect) for queue metrics
                if q_stat.significant and abs(q_stat.effect_size) >= 0.5:
                    # Determine if this is a REAL queue fault or just buffering
                    # CRITICAL: ALL queue metrics must go through rate imbalance analysis
                    # Even in_flight, age, utilization can be due to slow consumer
                    is_queue_fault = self._analyze_queue_rate_imbalance(
                        node_id, node_type, baseline, current, q_stat.effect_size
                    )

                    if is_queue_fault:
                        # TRUE queue fault → PRIMARY symptom
                        symptoms.append(f"{queue_metric} spike (d={q_stat.effect_size:.2f})")
                        if q_stat.effect_size > 3.0:
                            performance_score = max(performance_score, 10.0)
                        else:
                            performance_score = max(performance_score, min(10.0, q_stat.effect_size * 2.5))
                        queue_fault_count += 1
                    else:
                        # Normal buffering → Don't treat as fault
                        # Give minimal score (just for context) - this is NOT the queue's fault!
                        symptoms.append(f"{queue_metric} increased (buffering - producer/consumer imbalance)")
                        # Very small contribution: 0.5 points max per metric
                        performance_score = max(performance_score, min(0.5, q_stat.effect_size * 0.1))
                        queue_buffering_count += 1

        # CRITICAL: Only mark as PRIMARY if MAJORITY of queue symptoms are faults (not buffering)
        # This prevents one false-positive queue metric from contaminating the entire classification
        if queue_fault_count > 0 and queue_fault_count > queue_buffering_count:
            found_primary = True

        # === PHASE 4: SECONDARY SYMPTOMS (Performance Degradation) ===
        if not found_primary:
            # Check Cache Hit Rate (for external caches)
            if 'cache_hit_rate' in current and 'cache_hit_rate' in baseline:
                base_hit = np.mean(baseline['cache_hit_rate']) if len(baseline['cache_hit_rate']) > 0 else 0
                curr_hit = np.mean(current['cache_hit_rate']) if len(current['cache_hit_rate']) > 0 else 0
                hit_rate_drop = base_hit - curr_hit

                if base_hit > 0.1 and hit_rate_drop > 0.2:  # >20% drop in hit rate
                    symptoms.append(f"Cache hit rate dropped ({base_hit:.1%} → {curr_hit:.1%})")
                    # Significant cache degradation - treat as PRIMARY symptom
                    found_primary = True
                    resource_score = max(resource_score, 10.0)

            # Check Error Rate with Dependency-Aware Attribution
            # PRINCIPLE: Errors contribute proportionally to their magnitude
            # BUT: Only if they can be attributed to this node (not cascading from dependencies)
            err_stat = self._check_metric('internal_error_rate', baseline, current)
            if err_stat.significant and err_stat.effect_size > self.thresholds.min_effect_size_medium:
                curr_err_mean = np.mean(current['internal_error_rate']) if len(current['internal_error_rate']) > 0 else 0

                # Check dependency health to determine attribution
                dep_health = self._check_dependency_health(node_id, topology, all_current_data)

                # ATTRIBUTION LOGIC:
                # 1. No dependencies OR all dependencies healthy (error_rate < 5%)
                #    → Errors are intrinsic, score proportionally
                # 2. Dependencies have errors (>5%)
                #    → GRAY AREA: Cannot determine attribution, score 0 (conservative)
                #    → Let physics model determine root cause via coverage

                can_attribute_errors = (
                    not dep_health['has_dependencies'] or  # No deps → errors are intrinsic
                    dep_health['dependencies_healthy']     # Deps healthy → errors are intrinsic
                )

                if can_attribute_errors:
                    # PROPORTIONAL SCORING: error_rate * 10.0 (e.g., 47% → 4.7 score)
                    # Cap at 10.0 to maintain consistency with other signals
                    error_score = min(10.0, curr_err_mean * 10.0)
                    performance_score = max(performance_score, error_score)

                    # Mark as primary if errors are high
                    if curr_err_mean > 0.20:  # 20%+ errors
                        found_primary = True

                    symptoms.append(f"Error rate {curr_err_mean:.1%} (attributed to self)")

                else:
                    # GRAY AREA: Dependencies have errors, cannot attribute cleanly
                    # Conservative approach: Don't score errors, let physics determine attribution
                    # Add note to symptoms explaining why errors not factored
                    degraded_deps_str = ", ".join([f"{dep}({err:.1%})" for dep, err in dep_health['degraded_deps']])
                    symptoms.append(
                        f"Error rate {curr_err_mean:.1%} - not factored into health score "
                        f"(potential dilution from degraded dependencies: {degraded_deps_str})"
                    )
                    # performance_score unchanged - errors NOT attributed to self-health

            # Check Latency
            if lat_stat.significant and lat_stat.effect_size > self.thresholds.min_effect_size_medium:
                symptoms.append(f"Latency spike (d={lat_stat.effect_size:.2f})")
                if lat_stat.effect_size > self.thresholds.min_effect_size_very_large:
                    performance_score = max(performance_score, 10.0)
                elif lat_stat.effect_size > self.thresholds.min_effect_size_large:
                    performance_score = max(performance_score, 8.0)
                else:
                    performance_score = max(performance_score, min(10.0, lat_stat.effect_size * 3.0))

        # === FINAL SCORING ===
        final_score = max(resource_score, performance_score, limp_mode_score)
        confidence = 'high' if final_score > 7.0 else 'medium' if final_score > 4.0 else 'low'

        return SelfHealthResult(
            node_id=node_id,
            is_root_cause_candidate=(final_score > 4.0),
            self_degradation_score=final_score,
            symptom_type='primary' if found_primary else 'secondary',
            symptoms=symptoms,
            confidence=confidence
        )

    def _check_metric(self, name, baseline, current) -> StatResult:
        if name in baseline and name in current:
            return compare_distributions(baseline[name], current[name])
        return type('obj', (object,), {'effect_size': 0.0, 'significant': False})

    def _analyze_queue_rate_imbalance(self, node_id: str, node_type: str,
                                       baseline: Dict, current: Dict,
                                       queue_depth_effect_size: float) -> bool:
        """
        CRITICAL: Distinguishes real queue faults from normal buffering.

        This solves the "audit_queue vs audit_service" problem:
        - If queue depth increases due to slow consumer → NOT queue's fault (SECONDARY)
        - If queue depth increases due to queue capacity/failures → IS queue's fault (PRIMARY)

        Returns:
            True if queue itself is faulty (PRIMARY symptom)
            False if queue is just buffering (SECONDARY effect of consumer/producer issues)
        """
        # Only apply to queue nodes
        if node_type not in ['queue', 'MessageQueue']:
            return False

        curr_queue_depth = np.mean(current.get('queue_depth', np.array([0])))
        base_queue_depth = np.mean(baseline.get('queue_depth', np.array([0])))

        limits = self.config_extractor.get_limits_for_node(node_id, node_type)

        # CHECK 1: Queue capacity saturation
        max_queue_capacity = limits.get('max_queue_depth', float('inf'))
        if max_queue_capacity < float('inf') and curr_queue_depth > max_queue_capacity * 0.9:
            return True  # Queue is undersized → PRIMARY fault

        # CHECK 2: Queue failures/errors
        if 'internal_error_rate' in current:
            curr_err_rate = np.mean(current['internal_error_rate'])
            if curr_err_rate > 0.01:  # >1% error rate
                return True  # Queue has errors → PRIMARY fault

        # CHECK 3: Producer/Consumer rate imbalance
        producer_rate_curr = np.mean(current.get('producer_rate', np.array([0])))
        consumer_rate_curr = np.mean(current.get('consumer_rate', np.array([0])))
        producer_rate_base = np.mean(baseline.get('producer_rate', np.array([0])))
        consumer_rate_base = np.mean(baseline.get('consumer_rate', np.array([0])))

        if producer_rate_curr > 0 or consumer_rate_curr > 0:
            rate_ratio = producer_rate_curr / max(consumer_rate_curr, 0.1)

            if rate_ratio > 1.5:
                return False  # Producer overwhelming consumer → NOT queue's fault

            if consumer_rate_curr < consumer_rate_base * 0.5:
                return False  # Consumer slowed down → NOT queue's fault

            if producer_rate_curr > producer_rate_base * 1.5:
                return False  # Producer sped up → NOT queue's fault

        # CHECK 4: Queue-level latency (queue operations themselves are slow)
        if 'avg_latency' in current and 'avg_latency' in baseline:
            lat_stat = compare_distributions(baseline['avg_latency'], current['avg_latency'])
            if lat_stat.significant and lat_stat.effect_size > 2.0:
                return True  # Queue operations slow → PRIMARY fault

        # CHECK 5: Extremely high queue depth
        if queue_depth_effect_size > 4.0 and curr_queue_depth > 1000:
            return True  # Queue likely undersized → PRIMARY fault

        # Default: Normal buffering, not queue's fault
        return False
