#!/usr/bin/env python3
"""
Test script to debug external service fault injection.
"""
import simpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.components.external import ExternalService
from src.failures.training_injector import TrainingFailureInjector
from src.core.ground_truth import CausalityTracker

def test_external_fault_injection():
    """Test fault injection on ExternalService."""

    # Create simulation environment
    env = simpy.Environment()

    # Create ExternalService instance
    ext_service = ExternalService(env, 'ext_0')

    # Create component registry
    registry = {'ext_0': ext_service}

    # Create tracker
    tracker = CausalityTracker()

    # Create injector
    injector = TrainingFailureInjector(
        env=env,
        component_registry=registry,
        tracker=tracker,
        simulation_start_timestamp_ns=0
    )

    print(f"\n{'='*60}")
    print("Initial State:")
    print(f"{'='*60}")
    print(f"Component ID: {ext_service.id}")
    print(f"Component Type: {ext_service.type}")
    print(f"Has forced_error_rate: {hasattr(ext_service, 'forced_error_rate')}")
    print(f"Initial forced_error_rate: {ext_service.forced_error_rate}")
    print(f"Component in registry: {'ext_0' in registry}")
    print(f"Registry size: {len(registry)}")
    print(f"Registry keys: {list(registry.keys())}")

    # Test 1: Gradual failure injection
    print(f"\n{'='*60}")
    print("TEST 1: Gradual Failure Injection")
    print(f"{'='*60}")

    injector.inject_gradual_failure(
        target_id='ext_0',
        failure_mode='inject_errors',
        start_time=10.0,
        duration=20.0,
        params={'error_rate': 0.3},
        progression='step',
        episode_id='test_gradual'
    )

    # Run simulation for 35 seconds
    print("\nRunning simulation for 35 seconds...")
    env.run(until=35.0)

    print(f"\nAfter gradual injection (at t=35s):")
    print(f"  forced_error_rate: {ext_service.forced_error_rate}")
    print(f"  Expected: 0.3")

    # Reset for Test 2
    ext_service.forced_error_rate = 0.0
    env = simpy.Environment()
    ext_service = ExternalService(env, 'ext_0')
    registry = {'ext_0': ext_service}
    tracker = CausalityTracker()
    injector = TrainingFailureInjector(env, registry, tracker, 0)

    # Test 2: Instant failure injection
    print(f"\n{'='*60}")
    print("TEST 2: Instant Failure Injection")
    print(f"{'='*60}")

    injector.inject_instant_failure(
        target_id='ext_0',
        failure_mode='inject_errors',
        start_time=5.0,
        params={'error_rate': 0.3},
        duration=None,
        episode_id='test_instant'
    )

    # Run simulation for 10 seconds
    print("\nRunning simulation for 10 seconds...")
    env.run(until=10.0)

    print(f"\nAfter instant injection (at t=10s):")
    print(f"  forced_error_rate: {ext_service.forced_error_rate}")
    print(f"  Expected: 0.3")

    # Test 3: Direct attribute manipulation
    print(f"\n{'='*60}")
    print("TEST 3: Direct Attribute Manipulation")
    print(f"{'='*60}")

    ext_service.forced_error_rate = 0.0
    print(f"Before: {ext_service.forced_error_rate}")

    ext_service.apply_infrastructure_change(
        parameter='error_rate',
        delta=0.3,
        duration=0.0,  # Instant
        progression='linear',
        start_time=env.now
    )

    # Run for a moment to let the process execute
    env.run(until=env.now + 1)

    print(f"After: {ext_service.forced_error_rate}")
    print(f"Expected: 0.3")

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    if ext_service.forced_error_rate == 0.3:
        print("✓ Tests PASSED - Fault injection working")
    else:
        print("✗ Tests FAILED - Fault injection not working")
        print(f"  Final forced_error_rate: {ext_service.forced_error_rate}")

if __name__ == '__main__':
    test_external_fault_injection()
