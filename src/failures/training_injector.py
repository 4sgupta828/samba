"""
Training Failure Injector - Simplified injector for procedural training data generation.

This module provides a clean API for programmatically injecting failures without YAML scenarios.
Supports gradual failure application (realistic infrastructure degradation).
"""
import simpy
from typing import Dict, List, Any
from src.components.base_component import SimulatedComponent
from src.core.ground_truth import CausalityTracker
from src.core.scenario_events import ScenarioEventTracker, sim_time_to_timestamp
from src.failures.modes import FAILURE_MODES


class TrainingFailureInjector:
    """
    Simplified failure injector for training data generation.

    Key differences from FailureInjector:
    - No YAML scenario loading
    - Programmatic API for direct fault injection
    - Built-in support for gradual failure progression
    - Simplified ground truth tracking
    """

    def __init__(
        self,
        env: simpy.Environment,
        component_registry: Dict[str, SimulatedComponent],
        tracker: CausalityTracker,
        simulation_start_timestamp_ns: int = None
    ):
        """
        Initialize the training failure injector.

        Args:
            env: SimPy environment
            component_registry: Dictionary of component_id -> SimulatedComponent
            tracker: CausalityTracker for ground truth
            simulation_start_timestamp_ns: Start timestamp for event tracking
        """
        self.env = env
        self.component_registry = component_registry
        self.tracker = tracker
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.scenario_event_tracker = ScenarioEventTracker()

        # Track all injected failures for export
        self.failure_events = []

    def inject_gradual_failure(
        self,
        target_id: str,
        failure_mode: str,
        start_time: float,
        duration: float,
        params: Dict[str, Any],
        progression: str = "linear",
        episode_id: str = None
    ):
        """
        Inject a failure that applies gradually over time.

        Args:
            target_id: Component ID to target
            failure_mode: Type of failure (e.g., 'inject_latency', 'cpu_saturation')
            start_time: When to start applying the failure (sim time)
            duration: How long it takes to reach full effect
            params: Failure parameters (e.g., {'latency_ms': 2000})
            progression: How to apply ('linear', 'exponential', 'step')
            episode_id: Episode identifier for tracking

        Returns:
            SimPy process handle
        """
        return self.env.process(
            self._apply_gradual_failure(
                target_id=target_id,
                failure_mode=failure_mode,
                start_time=start_time,
                duration=duration,
                params=params,
                progression=progression,
                episode_id=episode_id or f"fault_{int(start_time)}"
            )
        )

    def inject_instant_failure(
        self,
        target_id: str,
        failure_mode: str,
        start_time: float,
        params: Dict[str, Any],
        duration: float = None,
        episode_id: str = None
    ):
        """
        Inject a failure that applies instantly (legacy behavior).

        Args:
            target_id: Component ID to target
            failure_mode: Type of failure
            start_time: When to apply the failure (sim time)
            params: Failure parameters
            duration: Optional duration before auto-revert
            episode_id: Episode identifier

        Returns:
            SimPy process handle
        """
        return self.env.process(
            self._apply_instant_failure(
                target_id=target_id,
                failure_mode=failure_mode,
                start_time=start_time,
                params=params,
                duration=duration,
                episode_id=episode_id or f"fault_{int(start_time)}"
            )
        )

    def _apply_gradual_failure(
        self,
        target_id: str,
        failure_mode: str,
        start_time: float,
        duration: float,
        params: Dict[str, Any],
        progression: str,
        episode_id: str
    ):
        """Internal process for gradual failure application."""
        # Wait until start time
        if start_time > self.env.now:
            yield self.env.timeout(start_time - self.env.now)

        # Get target component
        if target_id not in self.component_registry:
            print(f"ERROR: Target component '{target_id}' not found")
            return

        target = self.component_registry[target_id]

        # Start incident tracking
        if self.tracker.active_incident is None:
            self.tracker.start_incident(
                sim_time=self.env.now,
                root_cause_component_id=target.id,
                root_cause_component_type=target.type,
                failure_mode=failure_mode,
                params=params
            )

        # Record failure injection event
        self._record_failure_event(
            event_id=episode_id,
            mode=failure_mode,
            target=target,
            params=params,
            is_gradual=True,
            duration=duration,
            progression=progression
        )

        print(f"[{self.env.now:.2f}s] >>> GRADUAL FAILURE: '{failure_mode}' on {target_id} "
              f"over {duration:.1f}s ({progression})")

        # Apply failure using component's infrastructure change mechanism
        # Map failure modes to parameters
        if failure_mode == 'inject_latency':
            parameter = 'latency_ms'
            delta = params.get('latency_ms', 1000)
        elif failure_mode == 'inject_errors':
            parameter = 'error_rate'
            delta = params.get('error_rate', 0.5)
        elif failure_mode == 'cpu_saturation':
            # For CPU saturation, we increase the CPU cost per request (first principles)
            # This models the actual increased computational work needed
            parameter = 'cpu_cost_multiplier'
            # Start from 1.0 (normal) and increase by cpu_multiplier - 1.0
            # e.g., cpu_multiplier=3.0 means requests need 3x CPU → delta = 2.0
            delta = params.get('cpu_multiplier', 3.0) - 1.0
        elif failure_mode == 'memory_pressure':
            # memory_pressure has custom gradual logic (like cache_failure)
            # It needs to call the function directly with progress parameter
            print(f"   Applying gradual memory pressure over {duration}s...")
            failure_func = FAILURE_MODES.get(failure_mode)
            if failure_func:
                # For pod-level faults, apply to all pods
                pod_level_faults = ['cpu_saturation', 'memory_leak', 'memory_pressure']
                is_pod_level_fault = failure_mode in pod_level_faults and hasattr(target, 'pods') and target.pods
                targets_to_apply = target.pods if is_pod_level_fault else [target]
                
                if progression == 'step':
                    # Apply in 10% steps
                    steps = 10
                    step_duration = duration / steps
                    for i in range(steps + 1):
                        progress = i / steps
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        for t in targets_to_apply:
                            failure_func(t, params_with_progress)
                        if i < steps:
                            yield self.env.timeout(step_duration)
                    return
                elif progression == 'linear':
                    # Apply continuously - sample at regular intervals
                    num_updates = 20  # Update 20 times during the duration
                    update_interval = duration / num_updates
                    for i in range(num_updates + 1):
                        progress = i / num_updates
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        for t in targets_to_apply:
                            failure_func(t, params_with_progress)
                        if i < num_updates:
                            yield self.env.timeout(update_interval)
                    return
                else:
                    # Unknown progression type - apply instantly
                    params_with_progress = params.copy()
                    params_with_progress['progress'] = 1.0
                    for t in targets_to_apply:
                        failure_func(t, params_with_progress)
                    yield self.env.timeout(duration)
                    return
        elif failure_mode == 'cache_failure':
            # cache_failure has custom gradual logic with multiple parameters
            print(f"   Applying gradual cache degradation over {duration}s...")
            failure_func = FAILURE_MODES.get(failure_mode)
            if failure_func:
                if progression == 'step':
                    # Apply in 10% steps
                    steps = 10
                    step_duration = duration / steps
                    for i in range(steps + 1):
                        progress = i / steps
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        failure_func(target, params_with_progress)
                        if i < steps:
                            yield self.env.timeout(step_duration)
                    return
                elif progression == 'linear':
                    # Apply continuously - sample at regular intervals
                    num_updates = 20  # Update 20 times during the duration
                    update_interval = duration / num_updates
                    for i in range(num_updates + 1):
                        progress = i / num_updates
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        failure_func(target, params_with_progress)
                        if i < num_updates:
                            yield self.env.timeout(update_interval)
                    return
                else:
                    # Unknown progression type - apply instantly
                    params_with_progress = params.copy()
                    params_with_progress['progress'] = 1.0
                    failure_func(target, params_with_progress)
                    yield self.env.timeout(duration)
                    return

        elif failure_mode == 'disk_io_saturation':
            # Gradually increase I/O wait latency
            print(f"   Applying gradual disk I/O saturation over {duration}s...")
            failure_func = FAILURE_MODES.get(failure_mode)
            if failure_func:
                io_wait_ms = params.get('io_wait_ms', 200.0)

                if progression == 'exponential':
                    # Apply exponentially increasing I/O wait
                    num_updates = 20
                    update_interval = duration / num_updates

                    def gradual_io_saturation():
                        for i in range(num_updates + 1):
                            # Exponential curve: progress^2 for faster ramp-up
                            progress = (i / num_updates) ** 2
                            current_io_wait = io_wait_ms * progress

                            # Apply current level
                            if hasattr(target, 'dynamics') and target.dynamics:
                                target.dynamics.fault_latency_additive_ms = current_io_wait
                                if i == 0:
                                    # Set flag on first application
                                    target.dynamics.fault_io_wait_active = True

                            if i < num_updates:
                                yield self.env.timeout(update_interval)

                    yield self.env.process(gradual_io_saturation())
                    print(f"   Gradual I/O saturation complete: {io_wait_ms:.0f}ms I/O wait")
                    return

                elif progression == 'linear':
                    # Linear ramp
                    num_updates = 20
                    update_interval = duration / num_updates

                    def gradual_io_saturation_linear():
                        for i in range(num_updates + 1):
                            progress = i / num_updates
                            current_io_wait = io_wait_ms * progress

                            if hasattr(target, 'dynamics') and target.dynamics:
                                target.dynamics.fault_latency_additive_ms = current_io_wait
                                if i == 0:
                                    target.dynamics.fault_io_wait_active = True

                            if i < num_updates:
                                yield self.env.timeout(update_interval)

                    yield self.env.process(gradual_io_saturation_linear())
                    print(f"   Gradual I/O saturation complete: {io_wait_ms:.0f}ms I/O wait")
                    return
                else:
                    # Instant fallback
                    failure_func(target, params)
                    yield self.env.timeout(duration)
                    return

        if failure_mode not in ['inject_latency', 'inject_errors', 'cpu_saturation', 'memory_pressure', 'cache_failure', 'disk_io_saturation']:
            print(f"WARNING: Gradual mode not implemented for '{failure_mode}', using instant")
            # Fall back to instant application
            failure_func = FAILURE_MODES.get(failure_mode)
            if failure_func:
                # Check if this is a pod-level fault being applied to a service
                # Pod-level faults: memory_leak, cpu_saturation
                pod_level_faults = ['memory_leak', 'cpu_saturation']

                if failure_mode in pod_level_faults and hasattr(target, 'pods') and target.pods:
                    # Apply fault to all pods of the service
                    print(f"   Applying '{failure_mode}' to {len(target.pods)} pods of {target_id}")
                    for pod in target.pods:
                        failure_func(pod, params)
                else:
                    # Apply to target directly
                    failure_func(target, params)
            yield self.env.timeout(duration)
            return

        # Apply the change gradually
        # For pod-level faults (cpu_saturation, memory_leak), apply to all pods if target is a service
        # Note: memory_pressure is handled separately above with custom gradual logic
        pod_level_faults = ['cpu_saturation', 'memory_leak']

        if failure_mode in pod_level_faults and hasattr(target, 'pods') and target.pods:
            # Apply gradual change to all pods of the service
            print(f"   Applying gradual '{failure_mode}' to {len(target.pods)} pods of {target_id}")
            for pod in target.pods:
                pod.apply_infrastructure_change(
                    parameter=parameter,
                    delta=delta,
                    duration=duration,
                    progression=progression,
                    start_time=self.env.now
                )

                # Special handling for cpu_saturation: also set CPU floor to show high utilization
                if failure_mode == 'cpu_saturation' and hasattr(pod, 'dynamics') and pod.dynamics:
                    # Calculate target CPU based on params
                    cpu_multiplier = params.get('cpu_multiplier', 3.0)
                    # Set CPU floor to show saturation (80-95% utilization)
                    target_cpu_percent = min(95.0, 50.0 + (cpu_multiplier * 15.0))
                    pod.dynamics.fault_cpu_floor_percent = target_cpu_percent
                    print(f"      [{pod.id}] Setting CPU floor: {target_cpu_percent:.1f}%")

        else:
            # Apply to target directly
            target.apply_infrastructure_change(
                parameter=parameter,
                delta=delta,
                duration=duration,
                progression=progression,
                start_time=self.env.now
            )

            # Special handling for cpu_saturation on non-service targets
            if failure_mode == 'cpu_saturation' and hasattr(target, 'dynamics') and target.dynamics:
                cpu_multiplier = params.get('cpu_multiplier', 3.0)
                target_cpu_percent = min(95.0, 50.0 + (cpu_multiplier * 15.0))
                target.dynamics.fault_cpu_floor_percent = target_cpu_percent
                print(f"      [{target.id}] Setting CPU floor: {target_cpu_percent:.1f}%")

        # Wait for the change to complete
        yield self.env.timeout(duration)

        print(f"[{self.env.now:.2f}s] <<< FAILURE FULLY APPLIED: '{failure_mode}' on {target_id}")

    def _apply_instant_failure(
        self,
        target_id: str,
        failure_mode: str,
        start_time: float,
        params: Dict[str, Any],
        duration: float,
        episode_id: str
    ):
        """Internal process for instant failure application."""
        # Wait until start time
        if start_time > self.env.now:
            yield self.env.timeout(start_time - self.env.now)

        # Get target component
        if target_id not in self.component_registry:
            print(f"ERROR: Target component '{target_id}' not found")
            return

        target = self.component_registry[target_id]

        # Start incident tracking
        if self.tracker.active_incident is None:
            self.tracker.start_incident(
                sim_time=self.env.now,
                root_cause_component_id=target.id,
                root_cause_component_type=target.type,
                failure_mode=failure_mode,
                params=params
            )

        # Record failure injection event
        self._record_failure_event(
            event_id=episode_id,
            mode=failure_mode,
            target=target,
            params=params,
            is_gradual=False
        )

        print(f"[{self.env.now:.2f}s] >>> INSTANT FAILURE: '{failure_mode}' on {target_id}")

        # Apply failure immediately
        failure_func = FAILURE_MODES.get(failure_mode)
        if not failure_func:
            print(f"ERROR: Unknown failure mode '{failure_mode}'")
            return

        try:
            failure_func(target, params)
        except Exception as e:
            print(f"ERROR: Failed to apply '{failure_mode}': {e}")
            return

        # Wait for duration if specified
        if duration:
            yield self.env.timeout(duration)

            # Auto-revert using REVERT_MODES registry
            from src.failures.modes import REVERT_MODES
            revert_func = REVERT_MODES.get(failure_mode)
            if revert_func:
                print(f"[{self.env.now:.2f}s] <<< REVERTING: '{failure_mode}' on {target_id}")
                revert_func(target, params)
            else:
                print(f"WARNING: No revert function registered for '{failure_mode}'")

            # End incident
            if self.tracker.active_incident:
                self.tracker.end_incident(self.env.now)

    def revert_gradual_failure(
        self,
        target_id: str,
        failure_mode: str,
        params: Dict[str, Any],
        duration: float = 10.0
    ):
        """
        Reverts a gradual failure GRADUALLY over specified duration.

        This enables realistic A-B-A timeline: Healthy -> Fault -> Recovery

        Args:
            target_id: Component ID that had the failure
            failure_mode: Type of failure to revert
            params: Original failure parameters (used to compute inverse)
            duration: How long the recovery takes (gradual revert)

        Note: Uses apply_infrastructure_change with negative deltas for gradual recovery.
        """
        if target_id not in self.component_registry:
            print(f"ERROR: Target component '{target_id}' not found for revert")
            return

        target = self.component_registry[target_id]

        # Log the revert event
        print(f"[{self.env.now:.2f}s] <<< REVERTING GRADUAL FAILURE: '{failure_mode}' on {target_id} over {duration:.1f}s")

        # For most faults, use the REVERT_MODES registry (simple instant revert)
        # Only use gradual revert for specific faults that support it
        from src.failures.modes import REVERT_MODES

        # Check if this is a gradual-revert-capable fault
        gradual_faults = ['inject_latency', 'cpu_saturation', 'inject_errors', 'memory_pressure', 'cache_failure', 'disk_io_saturation']

        if failure_mode not in gradual_faults:
            # Use instant revert from registry
            revert_func = REVERT_MODES.get(failure_mode)
            if revert_func:
                print(f"   Using instant revert for '{failure_mode}'")
                try:
                    revert_func(target, params)
                    print(f"   Revert function completed for '{failure_mode}'")
                except Exception as e:
                    print(f"   ERROR: Revert function failed for '{failure_mode}': {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"   WARNING: No revert function registered for '{failure_mode}'")
            return

        # Apply GRADUAL revert using infrastructure change mechanism
        # Use negative deltas to reverse the fault
        # For pod-level faults, apply to all pods if target is a service
        pod_level_faults = ['cpu_saturation', 'memory_leak', 'memory_pressure']
        is_pod_level_fault = failure_mode in pod_level_faults and hasattr(target, 'pods') and target.pods
        targets_to_revert = target.pods if is_pod_level_fault else [target]

        if failure_mode == 'inject_latency':
            # Gradually remove injected latency
            for t in targets_to_revert:
                t.apply_infrastructure_change(
                    parameter='latency_ms',
                    delta=-params.get('latency_ms', 1000),  # Negative delta removes latency
                    duration=duration,
                    progression='linear',
                    start_time=self.env.now
                )
            print(f"   Gradual latency removal scheduled for {len(targets_to_revert)} target(s)")

        elif failure_mode == 'inject_errors':
            # Gradually remove error rate
            for t in targets_to_revert:
                t.apply_infrastructure_change(
                    parameter='error_rate',
                    delta=-params.get('error_rate', 0.5),  # Negative delta removes errors
                    duration=duration,
                    progression='linear',
                    start_time=self.env.now
                )
            print(f"   Gradual error rate reduction scheduled for {len(targets_to_revert)} target(s)")

        elif failure_mode == 'cpu_saturation':
            # Gradually reduce CPU cost multiplier back to 1.0 (normal)
            for t in targets_to_revert:
                current_multiplier = getattr(t, 'cpu_cost_multiplier', 1.0)
                # Delta to return to 1.0: -(current - 1.0)
                delta_to_normal = -(current_multiplier - 1.0)

                t.apply_infrastructure_change(
                    parameter='cpu_cost_multiplier',
                    delta=delta_to_normal,
                    duration=duration,
                    progression='linear',
                    start_time=self.env.now
                )

                # Remove CPU floor constraint
                if hasattr(t, 'dynamics') and t.dynamics:
                    t.dynamics.fault_cpu_floor_percent = None
                    print(f"      [{t.id}] Removed CPU floor")

            print(f"   Gradual CPU cost reduction scheduled for {len(targets_to_revert)} target(s)")

        elif failure_mode == 'memory_leak':
            # Stop the leak - prevents further memory accumulation
            # This is instant (toggles the leak on/off)
            # Already-leaked memory remains until pod restart (realistic)
            if hasattr(target, 'dynamics') and target.dynamics:
                leak_rate = params.get('leak_mb_per_request', 0.5)
                # Reduce memory per request back to normal
                target.dynamics.config.memory_per_request_mb = max(
                    0.1,
                    target.dynamics.config.memory_per_request_mb - leak_rate
                )
                print(f"   Memory leak stopped (leaked memory remains until restart)")

        # slow_queries removed (2025-12-10) → Use disk_io_saturation instead

        elif failure_mode == 'cache_failure':
            # Cache failure: GRADUALLY restore cache health
            # Use the same cache_failure function with decreasing progress (1.0 -> 0.0)
            from src.failures.modes import cache_failure

            if hasattr(target, 'forced_error_rate'):
                # Gradually restore by calling cache_failure with decreasing progress
                num_updates = 20  # 20 updates over the duration
                update_interval = duration / num_updates

                # Generator to gradually restore cache
                def gradual_cache_restore():
                    for i in range(num_updates + 1):
                        # Progress from 1.0 (full fault) to 0.0 (healthy)
                        progress = 1.0 - (i / num_updates)
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        cache_failure(target, params_with_progress)

                        if i < num_updates:
                            yield self.env.timeout(update_interval)

                # Return the generator so it can be yielded from in generate_dataset.py
                print(f"   Gradual cache restoration scheduled ({num_updates} steps over {duration:.1f}s)")
                return gradual_cache_restore()
            else:
                print(f"   Warning: Target doesn't support cache_failure revert")

        elif failure_mode == 'memory_pressure':
            # Reduce memory pressure gradually (like injection, but in reverse)
            # Use the same gradual mechanism as injection but with decreasing progress
            pod_level_faults = ['cpu_saturation', 'memory_leak', 'memory_pressure']
            is_pod_level_fault = failure_mode in pod_level_faults and hasattr(target, 'pods') and target.pods
            targets_to_revert = target.pods if is_pod_level_fault else [target]
            
            failure_func = FAILURE_MODES.get(failure_mode)
            if failure_func:
                # Apply gradual revert by calling function with decreasing progress
                num_updates = 20  # 20 updates over the duration
                update_interval = duration / num_updates
                
                def gradual_memory_revert():
                    for i in range(num_updates + 1):
                        # Progress from 1.0 (full fault) to 0.0 (healthy)
                        progress = 1.0 - (i / num_updates)
                        params_with_progress = params.copy()
                        params_with_progress['progress'] = progress
                        for t in targets_to_revert:
                            failure_func(t, params_with_progress)
                        
                        if i < num_updates:
                            yield self.env.timeout(update_interval)
                
                # Return the generator so it can be yielded from in generate_dataset.py
                print(f"   Gradual memory pressure reduction scheduled ({num_updates} steps over {duration:.1f}s)")
                return gradual_memory_revert()
            else:
                print(f"   Warning: No memory_pressure function found")

        elif failure_mode == 'disk_io_saturation':
            # Gradually reduce I/O wait latency back to zero
            print(f"   Applying gradual I/O saturation removal over {duration:.1f}s...")

            if hasattr(target, 'dynamics') and target.dynamics:
                io_wait_ms = params.get('io_wait_ms', 100.0)
                num_updates = 20
                update_interval = duration / num_updates

                def gradual_io_recovery():
                    for i in range(num_updates + 1):
                        # Progress from 1.0 (full fault) to 0.0 (healthy)
                        progress = 1.0 - (i / num_updates)
                        current_io_wait = io_wait_ms * progress

                        # Apply decreasing I/O wait
                        target.dynamics.fault_latency_additive_ms = current_io_wait

                        # Clear flag on final step
                        if i == num_updates:
                            target.dynamics.fault_io_wait_active = False
                            print(f"   I/O saturation fully removed, flag cleared")

                        if i < num_updates:
                            yield self.env.timeout(update_interval)

                print(f"   Gradual I/O saturation removal scheduled ({num_updates} steps over {duration:.1f}s)")
                return gradual_io_recovery()
            else:
                print(f"   Warning: Target doesn't have dynamics engine, using instant revert")
                from src.failures.modes import revert_disk_io_saturation
                revert_disk_io_saturation(target, params)
                print(f"   I/O saturation removed (instant fallback)")

        # connection_exhaustion removed (2025-12-10) → Use thread_exhaustion instead

        elif failure_mode == 'queue_consumer_slowdown':
            # Remove consumer slowdown immediately (MessageQueue doesn't support gradual changes)
            from src.failures.modes import revert_queue_consumer_slowdown
            revert_queue_consumer_slowdown(target, params)
            print(f"   Consumer slowdown removed (instant)")

        # enable_background_job removed (2025-12-10) → Use cpu_saturation instead
        # start_db_background_job removed (2025-12-10) → Use cpu_saturation instead
        # inject_db_wear removed (2025-12-10) → Use disk_io_saturation instead

        else:
            print(f"WARNING: Revert logic not implemented for '{failure_mode}'")

        print(f"   Recovery will complete at t={self.env.now + duration:.2f}s")

    def _record_failure_event(
        self,
        event_id: str,
        mode: str,
        target: SimulatedComponent,
        params: Dict[str, Any],
        is_gradual: bool,
        duration: float = None,
        progression: str = None
    ):
        """Record failure event in tracking systems."""
        # Record in local timeline
        event = {
            "id": event_id,
            "sim_time": self.env.now,
            "mode": mode,
            "target": target.id,
            "params": params,
            "is_gradual": is_gradual,
            "duration": duration,
            "progression": progression
        }
        self.failure_events.append(event)

        # Record in ScenarioEventTracker for ground truth
        if self.simulation_start_timestamp_ns:
            timestamp = sim_time_to_timestamp(self.env.now, self.simulation_start_timestamp_ns)

            # Use infrastructure change event for gradual failures
            if is_gradual and duration:
                # Determine the parameter being changed
                parameter = "latency_ms"  # Default
                delta = params.get('latency_ms', 0)

                if mode == 'inject_errors':
                    parameter = "error_rate"
                    delta = params.get('error_rate', 0)
                elif mode == 'cpu_saturation':
                    parameter = "cpu_load"
                    delta = params.get('cpu_latency_ms', 0)

                self.scenario_event_tracker.add_infrastructure_change_event(
                    event_id=event_id,
                    sim_time=self.env.now,
                    timestamp=timestamp,
                    target_component=target.id,
                    parameter=parameter,
                    delta=delta,
                    duration=duration,
                    progression=progression,
                    reason=f"Training episode failure: {mode}"
                )
            else:
                # Use failure injection event for instant failures
                self.scenario_event_tracker.add_failure_injection(
                    event_id=event_id,
                    sim_time=self.env.now,
                    timestamp=timestamp,
                    mode=mode,
                    targets=[target.id],
                    params=params,
                    is_revert=False
                )

    def get_failure_timeline(self) -> List[Dict[str, Any]]:
        """Get the complete timeline of failure injection events."""
        return self.failure_events
