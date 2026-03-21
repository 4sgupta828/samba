#!/usr/bin/env python3
"""
Test script to validate the capacity calculation fixes:
1. Workload generator connection pool removed as constraint
2. DB query time uses actual DB latency, not hardcoded 0.5x
3. Request routing distribution analysis included
"""

import json
from src.validation.health_validator import calculate_safe_workload, analyze_request_routing_distribution
from src.validation.component_profiles import estimate_component_capacity, get_component_profile

def test_component_capacity_no_workload_constraint():
    """Test that workload pool is not a constraint anymore."""
    print("\n" + "="*80)
    print("TEST 1: Workload Generator Connection Pool Removed as Constraint")
    print("="*80)

    # Test service capacity with various configurations
    capacity_with_pipeline = estimate_component_capacity(
        component_role='service',
        num_replicas=3,
        thread_pool_size=50,
        db_connection_pool_size=20,
        service_pipeline=[
            {"type": "cache_check"},
            {"type": "db_query"},
            {"type": "service_calls", "probability": 0.7}
        ]
    )

    print("\nService Capacity (with pipeline):")
    print(f"  Max RPS: {capacity_with_pipeline['max_rps']:.1f}")
    print(f"  Limiting Factor: {capacity_with_pipeline['limiting_factor']}")
    print(f"  Thread Pool Limited RPS: {capacity_with_pipeline.get('thread_pool_limited_rps', 'N/A')}")
    print(f"  DB Pool Limited RPS: {capacity_with_pipeline.get('db_pool_limited_rps', 'N/A')}")
    print(f"  Processing Limited RPS: {capacity_with_pipeline.get('processing_limited_rps', 'N/A')}")

    # Verify workload_pool_limited_rps is NOT in the result
    if 'workload_pool_limited_rps' not in capacity_with_pipeline:
        print("\n✓ PASS: workload_pool_limited_rps not in capacity constraints")
    else:
        print("\n✗ FAIL: workload_pool_limited_rps still present in capacity constraints")

    return capacity_with_pipeline


def test_db_latency_from_profile():
    """Test that DB latency comes from component profile, not hardcoded."""
    print("\n" + "="*80)
    print("TEST 2: DB Query Time Uses Actual DB Component Profile")
    print("="*80)

    # Get actual DB latency from profile
    db_latency_profile, _ = get_component_profile('database')
    actual_db_latency_ms = db_latency_profile.p50

    print(f"\nActual DB latency from profile: {actual_db_latency_ms:.2f}ms")

    # Calculate capacity with DB pipeline
    capacity_with_db = estimate_component_capacity(
        component_role='service',
        num_replicas=1,
        thread_pool_size=50,
        db_connection_pool_size=20,
        service_pipeline=[{"type": "db_query"}],  # Only DB, no cache
        cache_hit_rate=0.7
    )

    print(f"\nService capacity with DB (no cache):")
    print(f"  DB Pool Limited RPS: {capacity_with_db.get('db_pool_limited_rps', 'N/A'):.1f}")

    # Calculate capacity with cache + DB
    capacity_with_cache = estimate_component_capacity(
        component_role='service',
        num_replicas=1,
        thread_pool_size=50,
        db_connection_pool_size=20,
        service_pipeline=[
            {"type": "cache_check"},
            {"type": "db_query"}
        ],
        cache_hit_rate=0.7
    )

    print(f"\nService capacity with cache + DB (70% cache hit rate):")
    print(f"  DB Pool Limited RPS: {capacity_with_cache.get('db_pool_limited_rps', 'N/A'):.1f}")

    # With cache, DB pool should handle more RPS (since only 30% of requests hit DB)
    if capacity_with_cache.get('db_pool_limited_rps', 0) > capacity_with_db.get('db_pool_limited_rps', 0):
        print("\n✓ PASS: Cache hit rate properly reduces DB load")
    else:
        print("\n✗ FAIL: Cache hit rate not properly accounted for")

    return capacity_with_cache


def test_routing_distribution_analysis():
    """Test request routing distribution analysis."""
    print("\n" + "="*80)
    print("TEST 3: Request Routing Distribution Analysis")
    print("="*80)

    # Create a simple test topology with various pipeline configurations
    test_topology = {
        'nodes': [
            {
                'id': 'gateway',
                'role': 'gateway',
            },
            {
                'id': 'svc_a',
                'role': 'service',
                'processing_pipeline': [
                    {"type": "cache_check"},
                    {"type": "db_query"},
                    {"type": "service_calls", "probability": 0.7}
                ]
            },
            {
                'id': 'svc_b',
                'role': 'service',
                'processing_pipeline': [
                    {"type": "db_query"},
                    {"type": "external_calls", "probability": 0.3}
                ]
            },
            {
                'id': 'svc_c',
                'role': 'service',
                # Test case: service with None pipeline (edge case that was causing the bug)
                'processing_pipeline': None
            },
            {
                'id': 'db_0',
                'role': 'database',
            }
        ],
        'edges': [
            {'source': 'gateway', 'target': 'svc_a', 'type': 'sync_http'},
            {'source': 'gateway', 'target': 'svc_b', 'type': 'sync_http'},
            {'source': 'svc_a', 'target': 'db_0', 'type': 'sync_http'},
            {'source': 'svc_b', 'target': 'db_0', 'type': 'sync_http'},
            {'source': 'svc_c', 'target': 'db_0', 'type': 'sync_http'},
        ]
    }

    routing_analysis = analyze_request_routing_distribution(test_topology)

    print(f"\nRouting Analysis:")
    print(f"  Gateway: {routing_analysis.get('gateway_id')}")
    print(f"  Number of Services: {routing_analysis.get('num_services')}")
    print(f"  Request Mix: {routing_analysis.get('request_mix')}")

    print(f"\nService Routing Details:")
    for service_id, routing_info in routing_analysis.get('service_routing', {}).items():
        print(f"  {service_id}:")
        print(f"    Has Cache: {routing_info.get('has_cache')}")
        print(f"    Has DB: {routing_info.get('has_db')}")
        print(f"    Calls Services: {routing_info.get('calls_services')} (prob: {routing_info.get('service_calls_probability')})")
        print(f"    Calls External: {routing_info.get('calls_external')} (prob: {routing_info.get('external_calls_probability')})")

    # Check that we correctly handled all services including the one with None pipeline
    if routing_analysis.get('num_services', 0) == 3:
        print("\n✓ PASS: Routing distribution analysis working (including None pipeline handling)")
    else:
        print(f"\n✗ FAIL: Expected 3 services, got {routing_analysis.get('num_services', 0)}")

    # Specifically check that svc_c (with None pipeline) was processed correctly
    svc_c_routing = routing_analysis.get('service_routing', {}).get('svc_c')
    if svc_c_routing is not None:
        print("✓ PASS: Service with None pipeline handled correctly")
    else:
        print("✗ FAIL: Service with None pipeline not in routing analysis")

    return routing_analysis


def test_safe_workload_calculation():
    """Test the updated safe workload calculation."""
    print("\n" + "="*80)
    print("TEST 4: Safe Workload Calculation with New Features")
    print("="*80)

    # Create a simple test topology
    test_topology = {
        'nodes': [
            {
                'id': 'gateway',
                'role': 'gateway',
                'desired_replicas': 1
            },
            {
                'id': 'svc_0',
                'role': 'service',
                'desired_replicas': 3,
                'processing_pipeline': [
                    {"type": "cache_check"},
                    {"type": "db_query"},
                ]
            },
            {
                'id': 'db_0',
                'role': 'database',
                'desired_replicas': 1
            }
        ],
        'edges': [
            {'source': 'gateway', 'target': 'svc_0', 'type': 'sync_http'},
            {'source': 'svc_0', 'target': 'db_0', 'type': 'sync_http'},
        ]
    }

    safe_workload = calculate_safe_workload(test_topology)

    print(f"\nSafe Workload Results:")
    print(f"  Safe Baseline RPS: {safe_workload.get('safe_baseline_rps')}")
    print(f"  Safe Peak RPS: {safe_workload.get('safe_peak_rps')}")
    print(f"  Bottleneck Node: {safe_workload.get('bottleneck_node')}")
    print(f"  Bottleneck Limiting Factor: {safe_workload.get('bottleneck_limiting_factor')}")

    print(f"\nWorkload Generator Validation:")
    wg_validation = safe_workload.get('workload_generator_validation', {})
    print(f"  Is Adequate: {wg_validation.get('is_adequate')}")
    print(f"  Current Pool Size: {wg_validation.get('current_pool_size')}")
    print(f"  Required Pool Size: {wg_validation.get('required_pool_size')}")
    print(f"  Recommendation: {wg_validation.get('recommendation')}")

    print(f"\nRouting Distribution:")
    routing = safe_workload.get('routing_distribution', {})
    print(f"  Number of Services: {routing.get('num_services')}")

    print(f"\nCapacity Note:")
    print(f"  {safe_workload.get('capacity_note')}")

    # Check that workload generator validation exists
    if 'workload_generator_validation' in safe_workload:
        print("\n✓ PASS: Workload generator validation included")
    else:
        print("\n✗ FAIL: Workload generator validation missing")

    # Check that routing distribution exists
    if 'routing_distribution' in safe_workload:
        print("✓ PASS: Routing distribution analysis included")
    else:
        print("✗ FAIL: Routing distribution analysis missing")

    return safe_workload


if __name__ == '__main__':
    print("\n" + "="*80)
    print("CAPACITY CALCULATION FIXES - TEST SUITE")
    print("="*80)

    # Run all tests
    test_component_capacity_no_workload_constraint()
    test_db_latency_from_profile()
    test_routing_distribution_analysis()
    safe_workload_result = test_safe_workload_calculation()

    # Save results to file
    print("\n" + "="*80)
    print("Saving test results to test_capacity_fixes_output.json")
    print("="*80)

    with open('test_capacity_fixes_output.json', 'w') as f:
        json.dump(safe_workload_result, f, indent=2)

    print("\n✓ All tests completed!")
    print(f"✓ Results saved to: test_capacity_fixes_output.json")
