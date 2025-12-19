"""
Time Window Selector for RCA Analysis

Auto-detects healthy baseline periods and computes analysis windows
based on episode characteristics and analysis time.

Uses percentage-based windows for robustness across variable episode lengths.
"""

import pandas as pd
from typing import Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class TimeWindow:
    """Represents a time window for analysis."""
    start: float
    end: float
    duration: float

    def __repr__(self):
        return f"TimeWindow({self.start:.1f}s - {self.end:.1f}s, duration={self.duration:.1f}s)"


@dataclass
class WindowSelection:
    """Result of window selection."""
    baseline: TimeWindow
    current: TimeWindow
    analysis_time: float
    episode_duration: float
    baseline_health_score: float
    selection_metadata: Dict

    def validate(self) -> Tuple[bool, str]:
        """Validate that windows are properly configured."""
        if self.baseline.end >= self.current.start:
            return False, "Baseline and current windows overlap"

        if self.baseline.duration < 10:
            return False, f"Baseline window too short: {self.baseline.duration}s"

        if self.current.duration < 10:
            return False, f"Current window too short: {self.current.duration}s"

        gap = self.current.start - self.baseline.end
        if gap < 5:
            return False, f"Insufficient gap between windows: {gap}s"

        return True, "Valid"


class TimeWindowSelector:
    """
    Selects appropriate time windows for RCA analysis.

    Auto-detects healthy baseline periods and computes fault analysis windows
    based on percentages of episode duration.
    """

    def __init__(self,
                 metrics_df: pd.DataFrame,
                 episode_start: float = 0,
                 episode_end: float = None,
                 baseline_pct: float = 0.25,
                 current_pct: float = 0.15,
                 min_gap_pct: float = 0.05):
        """
        Initialize window selector.

        Args:
            metrics_df: DataFrame with metrics (must have 'sim_time', 'component_id', 'name', 'value')
            episode_start: Start time of episode
            episode_end: End time of episode (if None, infer from metrics_df)
            baseline_pct: Baseline window size as percentage of episode duration (default: 25%)
            current_pct: Current window size as percentage of episode duration (default: 15%)
            min_gap_pct: Minimum gap between windows as percentage (default: 5%)
        """
        self.metrics_df = metrics_df
        self.episode_start = episode_start
        self.episode_end = episode_end or metrics_df['sim_time'].max()
        self.episode_duration = self.episode_end - self.episode_start

        # Window sizing (as percentages)
        self.baseline_pct = baseline_pct
        self.current_pct = current_pct
        self.min_gap_pct = min_gap_pct

        # Absolute window sizes (computed from percentages)
        self.baseline_window_size = self.episode_duration * baseline_pct
        self.current_window_size = self.episode_duration * current_pct
        self.min_gap = self.episode_duration * min_gap_pct

        # Minimum absolute sizes for very short episodes
        self.baseline_window_size = max(self.baseline_window_size, 30.0)  # At least 30s
        self.current_window_size = max(self.current_window_size, 20.0)    # At least 20s
        self.min_gap = max(self.min_gap, 5.0)  # At least 5s gap

    def _compute_window_health(self, start_time: float, end_time: float) -> Tuple[float, Dict]:
        """
        Compute aggregate health score for a time window.

        Returns health score in [0, 10] where:
        - Lower = healthier (fewer anomalies, more stable)
        - Higher = less healthy (more anomalies, unstable)

        Args:
            start_time: Window start
            end_time: Window end

        Returns:
            (health_score, metadata)
        """
        window_df = self.metrics_df[
            (self.metrics_df['sim_time'] >= start_time) &
            (self.metrics_df['sim_time'] <= end_time)
        ]

        if len(window_df) == 0:
            return 10.0, {'reason': 'no_data'}

        # Analyze key health indicators
        # Use relative thresholds - not looking for perfect health, just relative stability
        health_signals = []
        metadata = {}

        # 1. Error rate intensity (not just presence, but rate)
        error_metrics = window_df[window_df['name'].str.contains('error', case=False, na=False)]
        if len(error_metrics) > 0:
            total_errors = error_metrics['value'].sum()
            duration = end_time - start_time
            error_rate = total_errors / duration if duration > 0 else total_errors

            # Score based on error rate (errors per second)
            if error_rate > 1.0:  # >1 error/sec
                health_signals.append(min(5.0, error_rate))
                metadata['error_rate'] = error_rate
            elif error_rate > 0.1:  # >0.1 error/sec
                health_signals.append(error_rate * 2)
                metadata['error_rate'] = error_rate

        # 2. CPU saturation (not just high usage, but saturation)
        cpu_metrics = window_df[window_df['name'].str.contains('cpu', case=False, na=False)]
        if len(cpu_metrics) > 0:
            p95_cpu = cpu_metrics['value'].quantile(0.95)
            mean_cpu = cpu_metrics['value'].mean()

            # High p95 indicates saturation
            if p95_cpu > 90:
                health_signals.append(min(4.0, (p95_cpu - 90) / 2.5))
                metadata['p95_cpu'] = p95_cpu
            # High variance indicates instability
            if mean_cpu > 0:
                cv = cpu_metrics['value'].std() / mean_cpu
                if cv > 0.5:  # High coefficient of variation
                    health_signals.append(1.0)
                    metadata['cpu_unstable'] = True

        # 3. Memory growth rate
        mem_metrics = window_df[window_df['name'].str.contains('memory', case=False, na=False)]
        if len(mem_metrics) > 0:
            for component in mem_metrics['component_id'].unique()[:10]:  # Limit to 10 components
                comp_mem = mem_metrics[mem_metrics['component_id'] == component]['value']
                if len(comp_mem) > 3:
                    # Linear regression to detect growth trend
                    x = list(range(len(comp_mem)))
                    y = comp_mem.values
                    if len(x) > 0 and y.std() > 0:
                        # Simple slope calculation
                        slope = (y[-1] - y[0]) / len(y)
                        baseline_value = y[0] if y[0] > 0 else 1
                        growth_rate = slope / baseline_value

                        if growth_rate > 0.05:  # >5% growth per measurement
                            health_signals.append(min(2.0, growth_rate * 20))
                            metadata['memory_growth_rate'] = growth_rate
                            break

        # 4. Latency distribution
        latency_metrics = window_df[window_df['name'].str.contains('latency', case=False, na=False)]
        if len(latency_metrics) > 0:
            p95 = latency_metrics['value'].quantile(0.95)
            p50 = latency_metrics['value'].quantile(0.50)

            # Large p95/p50 ratio indicates spikes
            if p50 > 0 and p95 / p50 > 3:  # p95 > 3x median
                health_signals.append(min(3.0, (p95 / p50) / 2))
                metadata['latency_p95_p50_ratio'] = p95 / p50

        # 5. Metric variance (instability indicator)
        # Count how many components have highly variable metrics
        unstable_components = 0
        for component in window_df['component_id'].unique()[:20]:  # Sample 20 components
            comp_df = window_df[window_df['component_id'] == component]
            for metric_name in ['service.latency', 'container.cpu.utilization']:
                metric_data = comp_df[comp_df['name'] == metric_name]['value']
                if len(metric_data) > 3:
                    mean_val = metric_data.mean()
                    if mean_val > 0:
                        cv = metric_data.std() / mean_val
                        if cv > 1.0:  # Very high variance
                            unstable_components += 1
                            break

        if unstable_components > 3:
            health_signals.append(min(2.0, unstable_components / 5))
            metadata['unstable_components'] = unstable_components

        # Aggregate health score
        if len(health_signals) == 0:
            health_score = 0.0  # Stable, no major issues
        else:
            health_score = min(10.0, sum(health_signals))

        metadata['signal_count'] = len(health_signals)
        metadata['window_duration'] = end_time - start_time

        return health_score, metadata

    def _compare_windows_relative(self, window1: TimeWindow, window2: TimeWindow) -> Dict:
        """
        Compare two windows to see which is relatively healthier.

        Returns comparison metrics to help decide which is better baseline.

        Args:
            window1: First window
            window2: Second window

        Returns:
            Dict with comparison metrics
        """
        health1, meta1 = self._compute_window_health(window1.start, window1.end)
        health2, meta2 = self._compute_window_health(window2.start, window2.end)

        # Extract specific metrics for comparison
        error_rate1 = meta1.get('error_rate', 0)
        error_rate2 = meta2.get('error_rate', 0)

        return {
            'window1_health': health1,
            'window2_health': health2,
            'health_diff': health2 - health1,  # Positive means window1 is healthier
            'window1_error_rate': error_rate1,
            'window2_error_rate': error_rate2,
            'error_rate_increase': error_rate2 / (error_rate1 + 0.001),  # Ratio
            'window1_metadata': meta1,
            'window2_metadata': meta2
        }

    def _auto_detect_baseline(self, before_time: float,
                              relative_to_time: Optional[float] = None,
                              health_threshold: float = 3.0,
                              min_duration: float = None) -> Optional[TimeWindow]:
        """
        Auto-detect a relatively healthy baseline period before the given time.

        Strategy: Find period that is relatively healthier than the analysis period.
        Does NOT require perfect health - just better than current state.

        Args:
            before_time: Search for baseline before this time
            relative_to_time: If provided, select baseline that's healthier than this time
            health_threshold: Maximum health score (0-10 scale) - now more lenient (default: 3.0)
            min_duration: Minimum baseline duration (default: self.baseline_window_size * 0.5)

        Returns:
            TimeWindow for baseline or None if no suitable period found
        """
        if min_duration is None:
            min_duration = self.baseline_window_size * 0.5  # At least half of target size

        # Scan time in chunks
        scan_chunk_size = 10.0  # Scan in 10s chunks
        scan_start = self.episode_start
        scan_end = before_time - self.min_gap  # Leave gap before analysis

        if scan_end <= scan_start + min_duration:
            return None  # Not enough time available

        # Compute health scores for sliding windows
        health_timeline = []
        current_time = scan_start

        while current_time + scan_chunk_size <= scan_end:
            window_end = min(current_time + scan_chunk_size, scan_end)
            health_score, _ = self._compute_window_health(current_time, window_end)
            health_timeline.append({
                'time': current_time,
                'end_time': window_end,
                'health': health_score,
                'is_healthy': health_score <= health_threshold
            })
            current_time += scan_chunk_size

        if not health_timeline:
            return None

        # Find longest contiguous healthy period
        best_period = None
        best_duration = 0
        current_period_start = None

        for i, point in enumerate(health_timeline):
            if point['is_healthy']:
                if current_period_start is None:
                    current_period_start = point['time']
            else:
                # End of healthy period
                if current_period_start is not None:
                    duration = health_timeline[i-1]['end_time'] - current_period_start
                    if duration > best_duration and duration >= min_duration:
                        best_duration = duration
                        best_period = (current_period_start, health_timeline[i-1]['end_time'])
                    current_period_start = None

        # Check last period
        if current_period_start is not None:
            duration = health_timeline[-1]['end_time'] - current_period_start
            if duration > best_duration and duration >= min_duration:
                best_duration = duration
                best_period = (current_period_start, health_timeline[-1]['end_time'])

        if best_period is None:
            return None

        # If found period is longer than desired, take the end portion (most recent healthy data)
        start, end = best_period
        if end - start > self.baseline_window_size * 1.5:
            # Take last N seconds of the healthy period
            start = end - self.baseline_window_size

        return TimeWindow(start=start, end=end, duration=end - start)

    def select_windows(self, analysis_time: float,
                       auto_detect_baseline: bool = True,
                       baseline_window: Optional[TimeWindow] = None,
                       known_fault_start: Optional[float] = None) -> WindowSelection:
        """
        Select baseline and current windows for RCA analysis.

        Args:
            analysis_time: Point in time when RCA is being run
            auto_detect_baseline: If True, auto-detect healthy baseline (recommended)
            baseline_window: Manual baseline window (only if auto_detect_baseline=False)
            known_fault_start: If provided, use simple pre-fault baseline (for testing)

        Returns:
            WindowSelection with baseline and current windows

        Raises:
            ValueError: If windows cannot be computed within constraints
        """
        if analysis_time <= self.episode_start:
            raise ValueError(f"analysis_time ({analysis_time}) must be after episode_start ({self.episode_start})")

        if analysis_time > self.episode_end:
            raise ValueError(f"analysis_time ({analysis_time}) exceeds episode_end ({self.episode_end})")

        # === SELECT BASELINE WINDOW ===
        if known_fault_start is not None:
            # Simple approach: use period before fault start
            # This is for testing/validation against labeled data
            baseline_end = known_fault_start
            baseline_start = max(self.episode_start, baseline_end - self.baseline_window_size)
            baseline = TimeWindow(
                start=baseline_start,
                end=baseline_end,
                duration=baseline_end - baseline_start
            )
            baseline_health_score, health_meta = self._compute_window_health(baseline.start, baseline.end)
            selection_metadata = {'baseline_method': 'known_fault_start', 'health_metadata': health_meta}

        elif auto_detect_baseline:
            baseline = self._auto_detect_baseline(
                before_time=analysis_time,
                health_threshold=3.0,  # More lenient
                min_duration=self.baseline_window_size * 0.5
            )

            if baseline is None:
                # Fallback: use early episode period if auto-detect fails
                baseline_end = min(
                    self.episode_start + self.baseline_window_size,
                    analysis_time - self.current_window_size - self.min_gap
                )
                baseline = TimeWindow(
                    start=self.episode_start,
                    end=baseline_end,
                    duration=baseline_end - self.episode_start
                )
                baseline_health_score = 10.0  # Unknown health
                selection_metadata = {'baseline_method': 'fallback', 'reason': 'auto_detect_failed'}
            else:
                baseline_health_score, health_meta = self._compute_window_health(baseline.start, baseline.end)
                selection_metadata = {'baseline_method': 'auto_detected', 'health_metadata': health_meta}
        else:
            if baseline_window is None:
                raise ValueError("baseline_window required when auto_detect_baseline=False")
            baseline = baseline_window
            baseline_health_score, health_meta = self._compute_window_health(baseline.start, baseline.end)
            selection_metadata = {'baseline_method': 'manual', 'health_metadata': health_meta}

        # === SELECT CURRENT WINDOW ===
        # Current window: recent data around analysis_time
        current_end = analysis_time
        current_start = max(
            baseline.end + self.min_gap,  # Must be after baseline + gap
            analysis_time - self.current_window_size  # Desired window size
        )

        # Ensure current window doesn't go past analysis_time
        if current_end - current_start < 10:
            raise ValueError(
                f"Cannot fit current window: only {current_end - current_start:.1f}s available "
                f"between baseline end ({baseline.end:.1f}s) and analysis_time ({analysis_time:.1f}s)"
            )

        current = TimeWindow(
            start=current_start,
            end=current_end,
            duration=current_end - current_start
        )

        # === CREATE RESULT ===
        selection_metadata.update({
            'episode_duration': self.episode_duration,
            'baseline_pct': self.baseline_pct,
            'current_pct': self.current_pct,
            'gap_duration': current.start - baseline.end,
            'gap_pct': (current.start - baseline.end) / self.episode_duration
        })

        result = WindowSelection(
            baseline=baseline,
            current=current,
            analysis_time=analysis_time,
            episode_duration=self.episode_duration,
            baseline_health_score=baseline_health_score,
            selection_metadata=selection_metadata
        )

        # Validate
        is_valid, message = result.validate()
        if not is_valid:
            raise ValueError(f"Invalid window selection: {message}")

        return result

    def suggest_analysis_time(self, fault_start_time: Optional[float] = None,
                             target_percentile: float = 0.6) -> float:
        """
        Suggest a reasonable analysis_time for RCA.

        If fault_start_time is known, suggests a time after fault has had time to propagate.
        Otherwise suggests a point at target_percentile through the episode.

        Args:
            fault_start_time: Known fault injection time (optional)
            target_percentile: Where in episode to analyze (0.6 = 60% through)

        Returns:
            Suggested analysis_time
        """
        if fault_start_time is not None:
            # Analyze after fault has had time to reach steady state
            # Typically: fault_start + 1.5x baseline_window_size
            propagation_time = self.baseline_window_size * 1.5
            suggested_time = fault_start_time + propagation_time

            # Ensure it's within episode bounds
            max_time = self.episode_end - self.current_window_size * 0.5
            suggested_time = min(suggested_time, max_time)
        else:
            # Use percentile of episode
            suggested_time = self.episode_start + (self.episode_duration * target_percentile)

        return suggested_time
