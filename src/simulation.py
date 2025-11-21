"""
Core Simulation Orchestrator.
This module contains the Simulation class that manages the setup and execution
of the SimPy environment and all its components.
"""
import simpy
import os
import yaml
from datetime import datetime
from src.core.ground_truth import CausalityTracker
from src.telemetry.setup import setup_telemetry
from src.telemetry.infra_context_exporter import InfrastructureContextExporter
from src.workloads.generator import WorkloadGenerator
from src.failures.injector import FailureInjector
from src.core.logging_setup import get_logger
from src.components.base_component import EnrichedComponent

class Simulation:
    def __init__(self, config: dict):
        self.config = config
        self.env = simpy.Environment()
        self.reports = []
        self.tracker = CausalityTracker()
        self.tracker.reset()
        self.telemetry_shutdown = None
        self.telemetry_collector = None
        self.log_handler = None
        self.meter_provider = None
        self.metric_reader = None
        self.logger = get_logger(__name__)
        self.output_dir = None
        self.simulation_id = None
        self.component_registry = None

    def _periodic_metric_flush(self, interval: int = 60):
        """
        SimPy process that periodically flushes metrics based on simulation time.

        This ensures metrics are exported uniformly across the simulation timeline,
        not based on wall-clock time (which would result in sparse exports since
        simulations complete quickly in real-time).

        With the SimulationTimeMetricReader, we notify it of the current simulation
        time, and it decides whether to actually collect and export metrics based
        on the configured export interval. This enables proper histogram aggregation.

        Args:
            interval: Check interval in simulation seconds (default: 60)
        """
        while True:
            yield self.env.timeout(interval)
            if self.metric_reader:
                # Notify metric reader of current simulation time
                # It will decide whether to actually collect/export based on its export interval
                should_collect = self.metric_reader.notify_sim_time(self.env.now)
                if should_collect:
                    # Trigger collection and export
                    self.meter_provider.force_flush()
                    self.logger.debug(f"[{self.env.now:.2f}s] Collected and exported metrics")
            elif self.meter_provider:
                # Fallback for non-SimulationTimeMetricReader (e.g., console exporter)
                self.meter_provider.force_flush()
                self.logger.debug(f"[{self.env.now:.2f}s] Flushed metrics to file")

    def run(self):
        """Sets up and runs the full simulation."""
        sim_config = self.config.get('simulation', {})
        duration = sim_config.get('duration', 3600)

        # Map simulation timestamps to real-world time window: [now - duration, now]
        # This makes telemetry data have realistic timestamps by default
        import time
        now_ns = int(time.time() * 1_000_000_000)  # Use time.time() to get actual UTC epoch time
        duration_ns = int(duration * 1_000_000_000)
        self.simulation_start_timestamp_ns = now_ns - duration_ns

        # Get or create output directory
        # If output_dir is a full path (already includes run_id), use it directly
        # Otherwise, create a timestamped subdirectory
        base_output_dir = sim_config.get('output_dir', 'output')

        # Check if this is already a full path with timestamp (created by UI)
        # Pattern: ends with data_YYYYMMDD_HHMMSS
        import re
        if re.search(r'data_\d{8}_\d{6}$', base_output_dir):
            # This is already a full path with run_id
            self.output_dir = base_output_dir
            # Extract simulation_id from path
            self.simulation_id = os.path.basename(base_output_dir)
        else:
            # Create new timestamped subdirectory (CLI usage)
            self.simulation_id = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.output_dir = os.path.join(base_output_dir, self.simulation_id)

        os.makedirs(self.output_dir, exist_ok=True)
        self.logger.info(f"Output directory: {self.output_dir}")

        # 1. Setup Telemetry
        self.logger.info("[Phase 1/5] Setting up Telemetry...")
        telemetry_config = self.config.get('telemetry', {}).copy()

        # Force file exporter for separate file output
        telemetry_config['exporter'] = 'file'

        # Pass warmup_period from simulation config to telemetry config
        warmup_period = sim_config.get('warmup_period', 0)
        if warmup_period > 0:
            telemetry_config['warmup_period'] = warmup_period

        self.telemetry_shutdown, self.telemetry_collector, self.log_handler, self.meter_provider, self.metric_reader = setup_telemetry(
            telemetry_config,
            output_dir=self.output_dir,
            simulation_id=self.simulation_id,
            simulation_start_timestamp_ns=self.simulation_start_timestamp_ns
        )

        # Set the log handler for all components
        if self.log_handler:
            EnrichedComponent.set_log_handler(self.log_handler)

        # 2. Parse IaC and Build Graph (or use pre-built registry)
        if self.component_registry is None:
            self.logger.info("[Phase 2/5] Parsing IaC and building infrastructure graph...")
            iac_path = self.config.get('infrastructure', {}).get('path')
            # Skip IaC parsing if path indicates procedural generation
            if iac_path and iac_path != 'generated_internal':
                try:
                    from src.iac.parser import parse_tf_directory
                    from src.iac.graph_builder import build_component_graph
                    parsed_hcl = parse_tf_directory(iac_path)
                    component_registry = build_component_graph(parsed_hcl, self.env)
                    self.component_registry = component_registry
                except (ImportError, FileNotFoundError) as e:
                    self.logger.warning(f"IaC parsing skipped: {e}")
                    if self.component_registry is None:
                        raise ValueError("No component registry provided and IaC parsing failed")
            else:
                self.logger.info("[Phase 2/5] Using procedurally generated topology (skipping IaC)")
        else:
            self.logger.info(f"[Phase 2/5] Using pre-built component registry with {len(self.component_registry)} components")

        component_registry = self.component_registry
        if not component_registry:
            raise ValueError("Component registry is empty!")
        self.logger.info(f"Successfully modeled {len(component_registry)} components.")

        # 3. Start all component processes FIRST (so compute agents can reach RUNNING state)
        self.logger.info("[Phase 3/5] Starting all component processes...")
        for component in component_registry.values():
            self.env.process(component.run())

        # 4. Initialize Workload Generator (after components are starting)
        self.logger.info("[Phase 4/5] Initializing workload generator...")
        workload_path = self.config.get('workload', {}).get('path')
        workload_generator = WorkloadGenerator(self.env, workload_path, component_registry)
        self.env.process(workload_generator.run())

        # 5. Initialize Failure Injector
        self.logger.info("[Phase 5/5] Initializing failure injector...")
        self.failure_injector = None
        scenario_path = self.config.get('failures', {}).get('scenario_path')
        if scenario_path:
            self.failure_injector = FailureInjector(
                self.env,
                scenario_path,
                component_registry,
                self.tracker,
                simulation_duration=duration,
                simulation_start_timestamp_ns=self.simulation_start_timestamp_ns
            )
            # Pre-flight validation: check that all target components exist
            try:
                self.failure_injector.validate_scenario()
                self.logger.info("Failure scenario validation passed")
            except ValueError as e:
                self.logger.error(f"Failure scenario validation failed: {e}")
                raise
            self.env.process(self.failure_injector.run())

        # Deployment Controller and Infrastructure Change Processor are optional
        # (not needed for basic training data generation)
        self.logger.info("Skipping deployment controller and infrastructure change processor...")

        # Start periodic metric flushing process
        if self.meter_provider:
            flush_interval = sim_config.get('metric_flush_interval', 5)  # 5 seconds for smooth visualization (deduplication prevents size explosion)
            self.logger.info(f"Starting periodic metric flush process (every {flush_interval} simulation seconds)...")
            self.env.process(self._periodic_metric_flush(interval=flush_interval))

        # Run the simulation
        self.logger.info(f"[Phase 5/5] Running simulation for {duration} seconds...")

        # Track simulation start/end times in collector
        if self.telemetry_collector:
            self.telemetry_collector.set_simulation_times(0, duration)

        self.env.run(until=duration)

        # Check for any unterminated incident
        if self.tracker.active_incident:
             self.reports.append(self.tracker.end_incident(self.env.now))

        # Save artifacts and shutdown telemetry
        self.save_artifacts_and_shutdown()

        # Return simulation results
        return {
            'output_dir': self.output_dir,
            'simulation_id': self.simulation_id,
            'duration': duration,
            'components_created': len(component_registry)
        }

    def save_artifacts_and_shutdown(self):
        """Saves simulation outputs and gracefully shuts down telemetry."""
        # Use the timestamped output directory
        output_dir = self.output_dir or self.config.get('simulation', {}).get('output_dir', 'output')

        # Add any reports from the failure injector
        self.reports.extend(FailureInjector.get_completed_reports())

        if not self.reports:
            self.logger.info("No incidents were generated during this run.")
        else:
            for report in self.reports:
                if report:
                    # Save incident report to timestamped directory
                    report_path = os.path.join(output_dir, f"{report.incident_id}.json")
                    with open(report_path, 'w') as f:
                        f.write(report.to_json())
                    self.logger.info(f"Saved incident report: {report_path}")

                    # Add incident to telemetry collector
                    if self.telemetry_collector:
                        self.telemetry_collector.add_incident(report)

        # Crucial shutdown call - do this first to ensure all telemetry is exported
        if self.telemetry_shutdown:
            self.telemetry_shutdown()

        # Finalize telemetry collector and save metadata
        if self.telemetry_collector:
            self.telemetry_collector.finalize()

            # Add failure injection timeline if available (deprecated - for backward compatibility)
            if self.failure_injector:
                failure_timeline = self.failure_injector.get_failure_timeline()
                self.telemetry_collector.add_failure_timeline(failure_timeline)

            # Export scenario events (ground truth for RCA) to dedicated file
            from src.core.scenario_events import ScenarioEventTracker
            scenario_event_tracker = ScenarioEventTracker()
            scenario_events = scenario_event_tracker.export_to_dict()

            # Determine simulation name based on scenario type
            simulation_name = self._determine_simulation_name()

            # Save to dedicated ground_truth.json file (first-class)
            ground_truth_path = os.path.join(output_dir, "ground_truth.json")
            scenario_event_tracker.export_to_json(ground_truth_path, simulation_name=simulation_name)
            self.logger.info(f"Saved ground truth scenarios: {ground_truth_path} ({len(scenario_events)} events)")

            metadata_path = os.path.join(output_dir, "metadata.json")
            self.telemetry_collector.save_metadata(metadata_path)
            self.logger.info(f"Saved telemetry metadata: {metadata_path}")

        # Export infrastructure context for RCA
        if self.component_registry:
            self.logger.info("Exporting infrastructure context for RCA...")
            # Get deployment events from DeploymentController (optional)
            deployment_events = []
            try:
                from src.components.control_plane import DeploymentController
                deployment_events = DeploymentController.get_deployment_events()
                if deployment_events:
                    self.logger.info(f"Including {len(deployment_events)} deployment events in infrastructure context")
            except (ImportError, AttributeError):
                # Deployment controller not available, skip
                pass
            exporter = InfrastructureContextExporter(self.component_registry, deployment_events)
            infra_context_path = exporter.export_to_file(output_dir)
            self.logger.info(f"Saved infrastructure context: {infra_context_path}")

        # Store simulation configs for reproducibility
        self._store_configs(output_dir)

        # Run telemetry validation
        self._run_validation(output_dir)

    def _determine_simulation_name(self) -> str:
        """
        Determine simulation name based on scenario type.
        
        Returns:
            Name indicating the scenario type: "Failure Scenario", "Deployment Scenario",
            "Deployment + Failure Scenario", or "Baseline (No Failures)"
        """
        has_failure_scenario = self.failure_injector is not None
        has_deployment_scenario = self.config.get('deployments') is not None
        
        if has_failure_scenario and has_deployment_scenario:
            return "Deployment + Failure Scenario"
        elif has_failure_scenario:
            return "Failure Scenario"
        elif has_deployment_scenario:
            return "Deployment Scenario"
        else:
            return "Baseline (No Failures)"

    def _store_configs(self, output_dir: str):
        """
        Store all simulation configurations in the output directory for reproducibility.

        This includes:
        - Main simulation config
        - Failure scenario config (if any)
        - Deployment scenario config (if any)
        """
        import shutil
        import json

        configs_dir = os.path.join(output_dir, "configs")
        os.makedirs(configs_dir, exist_ok=True)

        # 1. Store main simulation config
        try:
            main_config_path = os.path.join(configs_dir, "simulation_config.json")
            with open(main_config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            self.logger.info(f"Stored simulation config: {main_config_path}")
        except Exception as e:
            self.logger.warning(f"Failed to store simulation config: {e}")

        # 2. Store failure scenario config (if available)
        if self.failure_injector:
            try:
                scenario_path = self.config.get('failures', {}).get('scenario_path')
                if scenario_path and os.path.exists(scenario_path):
                    scenario_filename = os.path.basename(scenario_path)
                    dest_path = os.path.join(configs_dir, f"failure_scenario_{scenario_filename}")
                    shutil.copy2(scenario_path, dest_path)
                    self.logger.info(f"Stored failure scenario config: {dest_path}")

                    # Also store the scenario object with scaled timings
                    scenario_processed_path = os.path.join(configs_dir, "failure_scenario_processed.json")
                    with open(scenario_processed_path, 'w') as f:
                        json.dump(self.failure_injector.scenario, f, indent=2)
                    self.logger.info(f"Stored processed failure scenario: {scenario_processed_path}")
            except Exception as e:
                self.logger.warning(f"Failed to store failure scenario config: {e}")

        # 3. Store deployment scenario config (if available)
        deployment_config = self.config.get('deployments')
        if deployment_config:
            try:
                # Store the deployment config itself
                deployment_config_path = os.path.join(configs_dir, "deployment_config.json")
                with open(deployment_config_path, 'w') as f:
                    json.dump(deployment_config, f, indent=2)
                self.logger.info(f"Stored deployment config: {deployment_config_path}")

                # Store the deployment scenario YAML file if it has a path
                if 'scenario_path' in deployment_config:
                    scenario_path = deployment_config['scenario_path']
                    if os.path.exists(scenario_path):
                        scenario_filename = os.path.basename(scenario_path)
                        dest_path = os.path.join(configs_dir, f"deployment_scenario_{scenario_filename}")
                        shutil.copy2(scenario_path, dest_path)
                        self.logger.info(f"Stored deployment scenario config: {dest_path}")
            except Exception as e:
                self.logger.warning(f"Failed to store deployment config: {e}")

        self.logger.info(f"All configs stored in: {configs_dir}")

    def _run_validation(self, output_dir: str):
        """Run telemetry validation on the generated output."""
        # Check if validation is enabled in config
        sim_config = self.config.get('simulation', {})
        validate_output = sim_config.get('validate_output', True)

        if not validate_output:
            self.logger.info("Telemetry validation disabled in config")
            return

        self.logger.info("Running telemetry validation...")

        try:
            from telemetry.validator import TelemetryValidator

            validator = TelemetryValidator(output_dir)
            passed, results = validator.validate_all()

            # Print validation report
            validator.print_report()

            # Log summary
            errors = sum(1 for r in results if not r.passed and r.severity == "ERROR")
            warnings = sum(1 for r in results if not r.passed and r.severity == "WARNING")

            if errors > 0:
                self.logger.warning(f"Validation FAILED with {errors} error(s) and {warnings} warning(s)")
            elif warnings > 0:
                self.logger.info(f"Validation passed with {warnings} warning(s)")
            else:
                self.logger.info("Validation PASSED - all checks successful")

        except Exception as e:
            self.logger.error(f"Failed to run validation: {e}")
            import traceback
            traceback.print_exc()