"""
Failure Injector Module. Orchestrates failure scenarios during a simulation run.
"""
import simpy
import yaml
from typing import Dict, List, Any

from src.core.ground_truth import CausalityTracker
from src.failures.modes import FAILURE_MODES
from src.components.base_component import SimulatedComponent
from src.core.scenario_events import ScenarioEventTracker

class FailureInjector:
    _completed_reports: List = []

    def __init__(self, env: simpy.Environment, scenario_path: str, component_registry: Dict[str, SimulatedComponent], tracker: CausalityTracker, simulation_duration: int = None, simulation_start_timestamp_ns: int = None):
        self.env = env
        self.component_registry = component_registry
        self.tracker = tracker
        self.scenario_event_tracker = ScenarioEventTracker()
        self.simulation_duration = simulation_duration
        self.simulation_start_timestamp_ns = simulation_start_timestamp_ns
        self.time_scale_factor = 1.0

        try:
            with open(scenario_path, 'r') as f:
                self.scenario = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"ERROR: [FailureInjector] Scenario file not found at {scenario_path}. No failures will be injected.")
            self.scenario = {}

        # Calculate time scaling factor if simulation duration and reference duration are provided
        if self.simulation_duration and self.scenario.get('reference_duration'):
            reference_duration = self.scenario['reference_duration']
            self.time_scale_factor = self.simulation_duration / reference_duration
            print(f"[FailureInjector] Scaling scenario timings: reference={reference_duration}s, actual={self.simulation_duration}s, scale_factor={self.time_scale_factor:.2f}")
            
            # Transform the scenario configuration with scaled timings
            self._transform_scenario_timings()

        FailureInjector._completed_reports = []
        # Track all failure injection steps for metadata export
        self.failure_timeline = []

    def _transform_scenario_timings(self):
        """Transform scenario timings by applying the time scale factor to all time-related fields."""
        if self.time_scale_factor == 1.0:
            return  # No transformation needed

        failures = self.scenario.get('failures', [])
        for failure_config in failures:
            # Scale timestamp
            if 'timestamp' in failure_config:
                failure_config['timestamp'] = failure_config['timestamp'] * self.time_scale_factor

            # Scale duration
            if 'duration' in failure_config:
                failure_config['duration'] = failure_config['duration'] * self.time_scale_factor

        print(f"[FailureInjector] Transformed {len(failures)} failure steps with scale factor {self.time_scale_factor:.2f}")

    def validate_scenario(self):
        """
        Pre-flight validation to check that all target components exist in the registry.
        Raises ValueError if any targets are missing.
        """
        failures = self.scenario.get('failures', [])
        if not failures:
            return  # No failures to validate

        missing_targets = []
        for failure_config in failures:
            target_ids = failure_config.get('targets', [])
            for target_id in target_ids:
                if target_id not in self.component_registry:
                    missing_targets.append({
                        'failure_id': failure_config.get('id', 'unknown'),
                        'target_id': target_id
                    })

        if missing_targets:
            available_components = sorted(self.component_registry.keys())
            error_msg = "Pre-flight validation failed: Missing target components in scenario:\n"
            for missing in missing_targets:
                error_msg += f"  - Failure '{missing['failure_id']}' targets non-existent component '{missing['target_id']}'\n"
            error_msg += f"\nAvailable components: {available_components}"
            raise ValueError(error_msg)

    def run(self):
        """Main process to schedule and inject failures based on the scenario file."""
        scenario_name = self.scenario.get('name', 'Unnamed Scenario')
        print(f"[{self.env.now:.2f}s] FailureInjector starting with scenario: '{scenario_name}'")

        failures = self.scenario.get('failures', [])
        if not failures:
            print("No failures defined in scenario.")
            yield self.env.timeout(0)  # Make it a generator even if empty
            return

        # Schedule all failure events in parallel
        for failure_config in failures:
            self.env.process(self._execute_failure_step(failure_config))

        # Keep the process alive until the simulation ends
        yield self.env.timeout(float('inf'))

    def _execute_failure_step(self, config: Dict[str, Any]):
        """A SimPy process that handles a single step from the failure scenario."""
        # Get the (already scaled) timestamp
        start_time = config.get('timestamp', 0)

        # 1. Wait until the scheduled start time
        if start_time > self.env.now:
            yield self.env.timeout(start_time - self.env.now)

        # 2. Find the target components
        target_ids = config.get('targets', [])
        targets = [self.component_registry[tid] for tid in target_ids if tid in self.component_registry]

        # Log missing targets for debugging
        missing_targets = [tid for tid in target_ids if tid not in self.component_registry]
        if missing_targets:
            available_components = sorted(self.component_registry.keys())
            print(f"WARN: [FailureInjector] Missing targets for failure '{config.get('id')}': {missing_targets}")
            print(f"      Available components: {available_components}")

        if not targets:
            print(f"ERROR: [FailureInjector] No valid targets found for failure '{config.get('id')}'. Skipping.")
            return

        # 3. Look up the failure implementation
        mode = config.get('mode')
        failure_func = FAILURE_MODES.get(mode)
        if not failure_func:
            print(f"ERROR: [FailureInjector] Unknown failure mode '{mode}'. Skipping.")
            return

        # Normalize 'impact' to 'params' (scenario files use 'impact', code expects 'params')
        params = config.get('params') or config.get('impact', {})

        # 4. Start an incident with the tracker if this is the root cause
        # We'll assume the first step of a scenario is the root cause for now
        is_root_cause = self.tracker.active_incident is None
        is_revert_step = mode.startswith('revert_') or mode.startswith('reset_')

        if is_root_cause:
            # For simplicity, we'll label the root cause with the first target
            root_cause_target = targets[0]
            self.tracker.start_incident(
                sim_time=self.env.now,
                root_cause_component_id=root_cause_target.id,
                root_cause_component_type=root_cause_target.type,
                failure_mode=mode,
                params=params
            )

        # 5. Apply the failure to all targets
        print(f"[{self.env.now:.2f}s] >>> INJECTING: '{mode}' on {len(targets)} target(s) for step '{config.get('id')}'")

        # Record failure injection in timeline (for backward compatibility with existing code)
        failure_event = {
            "id": config.get('id', 'unknown'),
            "sim_time": self.env.now,
            "mode": mode,
            "targets": [target.id for target in targets],
            "params": params,
            "is_revert": is_revert_step
        }
        self.failure_timeline.append(failure_event)

        # Record in ScenarioEventTracker (ground truth for RCA)
        from src.core.scenario_events import sim_time_to_timestamp
        if self.simulation_start_timestamp_ns:
            timestamp = sim_time_to_timestamp(self.env.now, self.simulation_start_timestamp_ns)
            self.scenario_event_tracker.add_failure_injection(
                event_id=config.get('id', 'unknown'),
                sim_time=self.env.now,
                timestamp=timestamp,
                mode=mode,
                targets=[target.id for target in targets],
                params=params,
                is_revert=is_revert_step
            )

        for target in targets:
            try:
                failure_func(target, params)
            except Exception as e:
                print(f"ERROR: [FailureInjector] Failed to apply failure '{mode}' to '{target.id}': {e}")

        # 6. Handle revert steps - if this is a revert step, end the incident
        if is_revert_step:
            # This is a revert step, end the incident if there's an active incident
            if self.tracker.active_incident:
                report = self.tracker.end_incident(self.env.now)
                if report:
                    FailureInjector._completed_reports.append(report)
            return
        
        # 7. Wait for duration and revert, if specified
        duration = config.get('duration')
        if duration:
            yield self.env.timeout(duration)

            # Find the corresponding "revert" function if it exists
            revert_mode = config.get('revert_mode', f"revert_{mode}")
            revert_func = FAILURE_MODES.get(revert_mode)

            if revert_func:
                print(f"[{self.env.now:.2f}s] <<< REVERTING: '{mode}' on {len(targets)} target(s)")
                for target in targets:
                    revert_func(target, params)
            
            # End the incident if it was the root cause
            if is_root_cause:
                report = self.tracker.end_incident(self.env.now)
                if report:
                    FailureInjector._completed_reports.append(report)

    @classmethod
    def get_completed_reports(cls) -> List:
        return cls._completed_reports

    def get_failure_timeline(self) -> List[Dict]:
        """Get the complete timeline of failure injection events."""
        return self.failure_timeline