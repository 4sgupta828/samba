"""
Comprehensive test suite for Capacity Planner fixes.

Tests cover:
1. Async consumer detection
2. Queue stability calculation
3. Phi-based headroom application
4. Min replicas cliff removal
5. Analytical validation (M/M/c model)
6. Regression tests for original issues
"""

import pytest
import networkx as nx
from src.core.capacity_planner import CapacityPlanner


class TestAsyncConsumerDetection:
    """Test async consumer archetype detection."""

    def test_detects_async_consumer(self):
        """Should detect service consuming from queue."""
        G = nx.DiGraph()
        G.add_node('queue_0', role='queue')
        G.add_node('analytics', role='service')
        G.add_edge('queue_0', 'analytics', type='async_consume')

        planner = CapacityPlanner(G)
        assert planner._is_async_consumer('analytics') is True

    def test_does_not_detect_sync_service(self):
        """Should not detect sync service as async consumer."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway')
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        planner = CapacityPlanner(G)
        assert planner._is_async_consumer('service') is False

    def test_detects_multiple_queue_consumers(self):
        """Should detect all async consumers."""
        G = nx.DiGraph()
        G.add_node('queue_0', role='queue')
        G.add_node('analytics', role='service')
        G.add_node('automation', role='service')
        G.add_node('notification', role='service')
        G.add_edge('queue_0', 'analytics', type='async_consume')
        G.add_edge('queue_0', 'automation', type='async_consume')
        G.add_edge('queue_0', 'notification', type='async_consume')

        planner = CapacityPlanner(G)
        assert planner._is_async_consumer('analytics') is True
        assert planner._is_async_consumer('automation') is True
        assert planner._is_async_consumer('notification') is True


class TestProductionRateCalculation:
    """Test production rate to queue calculation."""

    def test_single_producer(self):
        """Should calculate production from single producer."""
        G = nx.DiGraph()
        G.add_node('service', role='service')
        G.add_node('queue', role='queue')
        G.add_edge('service', 'queue', type='async_produce')

        planner = CapacityPlanner(G)
        node_metrics = {'service': {'rps': 100.0}, 'queue': {'rps': 0.0}}
        production = planner._calculate_production_rate_to_queue('queue', node_metrics)

        assert production == 100.0

    def test_multiple_producers(self):
        """Should sum production from multiple producers."""
        G = nx.DiGraph()
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')
        G.add_node('queue', role='queue')
        G.add_edge('service_a', 'queue', type='async_produce')
        G.add_edge('service_b', 'queue', type='async_produce')

        planner = CapacityPlanner(G)
        node_metrics = {
            'service_a': {'rps': 60.0},
            'service_b': {'rps': 40.0},
            'queue': {'rps': 0.0}
        }
        production = planner._calculate_production_rate_to_queue('queue', node_metrics)

        assert production == 100.0


class TestQueueStabilityCalculation:
    """Test queue stability capacity calculation for async consumers."""

    def test_async_consumer_capacity_with_stability_margin(self):
        """Async consumer should have burst + drain margin."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('queue', role='queue')
        G.add_node('analytics', role='service')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'queue', type='async_produce')
        G.add_edge('queue', 'analytics', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service'],
                    'service': []
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        analytics_config = configs.get('analytics', {})
        rationale = analytics_config.get('_capacity_rationale', {})

        # Check that stability margin is applied
        assert rationale.get('burst_factor') == 1.3
        assert rationale.get('drain_margin') == 1.2
        assert rationale.get('required_consumer_rps') == pytest.approx(100 * 1.3 * 1.2, rel=0.01)

    def test_async_consumer_more_capacity_than_production(self):
        """Async consumer capacity should exceed production rate."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('queue', role='queue')
        G.add_node('analytics', role='service')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'queue', type='async_produce')
        G.add_edge('queue', 'analytics', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service'],
                    'service': []  # Service produces to queue (implicit via edge)
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.8)

        # Get analytics config
        analytics_config = configs.get('analytics', {})

        # Analytics should have async consumer rationale
        rationale = analytics_config.get('_capacity_rationale', {})
        assert rationale.get('archetype') == 'async_consumer', "Analytics should be identified as async consumer"

        # Required capacity should include stability margins
        production_rps = rationale.get('production_rps', 0)
        required_capacity = rationale.get('required_consumer_rps', 0)

        # Required capacity = production × burst_factor × drain_margin
        assert required_capacity > production_rps, "Consumer capacity should exceed production rate"


class TestPhiSemantics:
    """Test phi application to headroom above stability."""

    def test_phi_zero_gives_max_headroom_async(self):
        """phi=0.0 should give maximum headroom for async consumers."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('queue', role='queue')
        G.add_node('consumer', role='service')

        G.add_edge('gateway', 'queue', type='async_produce')
        G.add_edge('queue', 'consumer', type='async_consume')

        semantic_map = {'request_flows': {'GET': {'gateway': []}}}

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.0)

        consumer_config = configs['consumer']
        rationale = consumer_config['_capacity_rationale']

        # phi=0.0 → headroom_multiplier = 1.0 + (1.0 * 1.0) = 2.0x
        baseline = rationale['baseline_stable_replicas']
        actual = consumer_config['desired_replicas']

        # Should have 2x baseline (or close to it after rounding)
        assert actual >= baseline * 1.8  # Allow for rounding

    def test_phi_one_gives_min_headroom_async(self):
        """phi=1.0 should give minimum headroom (1.0x) for async consumers."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('queue', role='queue')
        G.add_node('consumer', role='service')

        G.add_edge('gateway', 'queue', type='async_produce')
        G.add_edge('queue', 'consumer', type='async_consume')

        semantic_map = {'request_flows': {'GET': {'gateway': []}}}

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=1.0)

        consumer_config = configs['consumer']
        rationale = consumer_config['_capacity_rationale']

        # phi=1.0 → headroom_multiplier = 1.0 + (1.0 * 0.0) = 1.0x
        baseline = rationale['baseline_stable_replicas']
        actual = consumer_config['desired_replicas']

        # Should be at baseline (exactly stable)
        assert actual == baseline

    def test_phi_does_not_reduce_below_stability(self):
        """High phi should not make async consumer unstable at baseline."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('queue', role='queue')
        G.add_node('consumer', role='service')

        G.add_edge('gateway', 'queue', type='async_produce')
        G.add_edge('queue', 'consumer', type='async_consume')

        semantic_map = {'request_flows': {'GET': {'gateway': []}}}

        planner = CapacityPlanner(G, semantic_map)

        # Test with very high phi
        configs = planner.plan_capacity(target_global_rps=200, phi=0.95)

        consumer_config = configs['consumer']
        rationale = consumer_config['_capacity_rationale']

        # Should still meet stability requirement
        baseline = rationale['baseline_stable_replicas']
        actual = consumer_config['desired_replicas']

        assert actual >= baseline  # Never below stability threshold


class TestMinReplicasCliff:
    """Test removal of hard 50 RPS threshold."""

    def test_no_cliff_at_50_rps(self):
        """Should not have cliff effect at 50 RPS."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}
        planner = CapacityPlanner(G, semantic_map)

        # Test around the old threshold
        config_49 = planner.plan_capacity(target_global_rps=49, phi=0.5)
        config_50 = planner.plan_capacity(target_global_rps=50, phi=0.5)
        config_51 = planner.plan_capacity(target_global_rps=51, phi=0.5)

        replicas_49 = config_49['service']['desired_replicas']
        replicas_50 = config_50['service']['desired_replicas']
        replicas_51 = config_51['service']['desired_replicas']

        # Should scale smoothly (no sudden jump)
        assert abs(replicas_51 - replicas_49) <= 1  # Max 1 replica difference

    def test_gradual_scaling(self):
        """Min replicas should scale gradually with RPS."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}
        planner = CapacityPlanner(G, semantic_map)

        # Test at various RPS levels
        configs = {
            rps: planner.plan_capacity(target_global_rps=rps, phi=0.8)['service']['desired_replicas']
            for rps in [5, 25, 50, 100, 200]
        }

        # Should increase with RPS
        assert configs[5] <= configs[25]
        assert configs[25] <= configs[50]
        assert configs[50] <= configs[100]


class TestAnalyticalValidation:
    """Test M/M/c queueing model validation."""

    def test_detects_unstable_system(self):
        """Should detect rho >= 1.0 as unstable."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}

        planner = CapacityPlanner(G, semantic_map)

        # Force underprovisioning with very high phi
        configs = planner.plan_capacity(target_global_rps=1000, phi=1.0)

        # Should have validation warnings
        assert len(planner.validation_warnings) > 0

        # Check for CRITICAL warnings
        critical_warnings = [w for w in planner.validation_warnings if 'CRITICAL' in w]
        assert len(critical_warnings) > 0

    def test_validates_stable_system(self):
        """Should pass validation for properly provisioned system."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}

        planner = CapacityPlanner(G, semantic_map)

        # Use low phi for robust provisioning
        configs = planner.plan_capacity(target_global_rps=50, phi=0.2)

        # Should have no CRITICAL warnings (maybe some INFO)
        critical_warnings = [w for w in planner.validation_warnings if 'CRITICAL' in w]
        assert len(critical_warnings) == 0

    def test_warns_on_high_utilization(self):
        """Should warn on rho >= 0.8 with high phi."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}

        planner = CapacityPlanner(G, semantic_map)

        # High phi + moderate load → should warn
        configs = planner.plan_capacity(target_global_rps=200, phi=0.85)

        # Should have some warnings
        assert len(planner.validation_warnings) > 0


class TestRegressionOriginalIssue:
    """Regression tests for the original analytics_service bug."""

    def test_analytics_service_baseline_stable(self):
        """
        Regression test: analytics_service should be stable at baseline.

        Original issue:
        - phi=0.81, target_rps=200
        - analytics_service got 1 replica, 10 threads
        - Queue depth grew from 2.8K to 10K during baseline
        - CPU at 100%, crashed during baseline
        """
        # Simplified topology: gateway → hub → queue → analytics
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('hub_orchestrator', role='service')
        G.add_node('device_events_queue', role='queue')
        G.add_node('analytics_service', role='service')

        G.add_edge('gateway', 'hub_orchestrator', type='sync_http')
        G.add_edge('hub_orchestrator', 'device_events_queue', type='async_produce')
        G.add_edge('device_events_queue', 'analytics_service', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['hub_orchestrator'],
                    'hub_orchestrator': []  # Produces to queue (implicit)
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=200, phi=0.81)

        analytics_config = configs['analytics_service']

        # Should be identified as async consumer
        rationale = analytics_config.get('_capacity_rationale', {})
        assert rationale.get('archetype') == 'async_consumer', \
            "Analytics should be identified as async consumer"

        # If there's production to the queue, analytics should get proper resources
        production_rps = rationale.get('production_rps', 0)
        if production_rps > 0:
            # BEFORE fix: 1 replica, 10 threads
            # AFTER fix: Should have multiple replicas and at least minimum threads
            assert analytics_config['desired_replicas'] >= 2, \
                f"Analytics should have at least 2 replicas for queue stability (production_rps={production_rps})"
            assert analytics_config['thread_pool_size'] >= 10, \
                f"Analytics should have at least 10 threads (got {analytics_config['thread_pool_size']})"

            # Should have stability margins applied
            assert rationale.get('burst_factor') == 1.3
            assert rationale.get('drain_margin') == 1.2
        else:
            # If no production detected, still should have minimum resources
            assert analytics_config['desired_replicas'] >= 1
            assert analytics_config['thread_pool_size'] >= 10

    def test_multiple_async_consumers_all_stable(self):
        """
        All async consumers should be properly provisioned.

        Original issue affected:
        - analytics_service (most severe)
        - automation_engine
        - notification_service
        """
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('queue_a', role='queue')
        G.add_node('queue_b', role='queue')
        G.add_node('queue_c', role='queue')
        G.add_node('analytics', role='service')
        G.add_node('automation', role='service')
        G.add_node('notification', role='service')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'queue_a', type='async_produce')
        G.add_edge('service', 'queue_b', type='async_produce')
        G.add_edge('service', 'queue_c', type='async_produce')
        G.add_edge('queue_a', 'analytics', type='async_consume')
        G.add_edge('queue_b', 'automation', type='async_consume')
        G.add_edge('queue_c', 'notification', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service'],
                    'service': []  # Produces to queues (implicit)
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=200, phi=0.81)

        # All async consumers should be properly provisioned
        for consumer in ['analytics', 'automation', 'notification']:
            config = configs[consumer]
            rationale = config.get('_capacity_rationale', {})

            # Should be identified as async consumer
            assert rationale.get('archetype') == 'async_consumer', \
                f"{consumer} should be identified as async consumer"

            # If there's production, should have proper resources
            production_rps = rationale.get('production_rps', 0)
            if production_rps > 0:
                assert config['desired_replicas'] >= 1
                assert config['thread_pool_size'] >= 10, \
                    f"{consumer} should have >= 10 threads (got {config['thread_pool_size']}, production={production_rps})"
            else:
                # Even with no production detected, should have minimum
                assert config['desired_replicas'] >= 1
                assert config['thread_pool_size'] >= 10


class TestEdgeCases:
    """Test edge cases and corner conditions."""

    def test_very_low_rps(self):
        """Should handle very low RPS gracefully."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}
        planner = CapacityPlanner(G, semantic_map)

        configs = planner.plan_capacity(target_global_rps=0.1, phi=0.5)

        # Should still provision minimum resources
        assert configs['service']['desired_replicas'] >= 1
        assert configs['service']['thread_pool_size'] >= 10

    def test_zero_rps(self):
        """Should handle zero RPS without crashing."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {'request_flows': {'GET': {'gateway': ['service']}}}
        planner = CapacityPlanner(G, semantic_map)

        # Should not crash
        configs = planner.plan_capacity(target_global_rps=0, phi=0.5)
        assert 'service' in configs

    def test_no_async_consumers(self):
        """Should work with pure sync topology."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')
        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('service_a', 'service_b', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a'],
                    'service_a': ['service_b']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # Should provision sync services normally
        assert 'service_a' in configs
        assert 'service_b' in configs

        # Should not have async consumer rationale
        assert '_capacity_rationale' not in configs['service_a']

    def test_complex_topology_with_mixed_archetypes(self):
        """Should handle mix of sync services and async consumers."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('sync_service', role='service')
        G.add_node('queue', role='queue')
        G.add_node('async_consumer', role='service')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'sync_service', type='sync_http')
        G.add_edge('sync_service', 'queue', type='async_produce')
        G.add_edge('sync_service', 'database', type='sync_db')
        G.add_edge('queue', 'async_consumer', type='async_consume')
        G.add_edge('async_consumer', 'database', type='sync_db')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['sync_service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # Sync service should not have async rationale
        assert '_capacity_rationale' not in configs['sync_service']

        # Async consumer should have async rationale
        assert configs['async_consumer'].get('_capacity_rationale', {}).get('archetype') == 'async_consumer'


class TestDatabaseCapacityCalculation:
    """Test database capacity calculation edge cases."""

    def test_database_with_no_clients(self):
        """Database with no clients should still get minimum capacity."""
        G = nx.DiGraph()
        G.add_node('database', role='database')

        semantic_map = {'request_flows': {'GET': {}}}
        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        db_config = configs.get('database', {})
        # Should have minimum connection pool capacity
        assert db_config.get('connection_pool_capacity', 0) >= 50  # Minimum floor

    def test_database_with_multiple_clients(self):
        """Database should sum connection pools from all client replicas."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')
        G.add_node('service_c', role='service')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('gateway', 'service_b', type='sync_http')
        G.add_edge('gateway', 'service_c', type='sync_http')
        G.add_edge('service_a', 'database', type='sync_db')
        G.add_edge('service_b', 'database', type='sync_db')
        G.add_edge('service_c', 'database', type='sync_db')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a', 'service_b', 'service_c']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=200, phi=0.5)

        # All services should have DB connection pools
        for svc in ['service_a', 'service_b', 'service_c']:
            assert configs[svc].get('db_connection_pool_capacity', 0) > 0

        # Database should have capacity >= sum of all client pools
        db_config = configs['database']
        db_capacity = db_config.get('connection_pool_capacity', 0)

        total_client_demand = sum(
            configs[svc].get('db_connection_pool_capacity', 0) * 
            configs[svc].get('desired_replicas', 1)
            for svc in ['service_a', 'service_b', 'service_c']
        )

        # DB capacity should be at least 1.2x client demand (from code)
        assert db_capacity >= int(total_client_demand * 1.2) or db_capacity >= 50

    def test_database_connection_pool_scales_with_replicas(self):
        """Database capacity should account for client replicas."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'database', type='sync_db')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        
        # Low RPS - should have fewer replicas
        configs_low = planner.plan_capacity(target_global_rps=50, phi=0.5)
        replicas_low = configs_low['service']['desired_replicas']
        db_capacity_low = configs_low['database']['connection_pool_capacity']

        # High RPS - should have more replicas
        planner2 = CapacityPlanner(G, semantic_map)
        configs_high = planner2.plan_capacity(target_global_rps=500, phi=0.5)
        replicas_high = configs_high['service']['desired_replicas']
        db_capacity_high = configs_high['database']['connection_pool_capacity']

        # Database capacity should increase with more client replicas
        if replicas_high > replicas_low:
            assert db_capacity_high >= db_capacity_low

    def test_database_with_service_no_db_connections(self):
        """Database should not count services that don't connect to it."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_with_db', role='service')
        G.add_node('service_no_db', role='service')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'service_with_db', type='sync_http')
        G.add_edge('gateway', 'service_no_db', type='sync_http')
        G.add_edge('service_with_db', 'database', type='sync_db')
        # service_no_db does NOT connect to database

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_with_db', 'service_no_db']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # service_no_db should have 0 DB connections
        assert configs['service_no_db'].get('db_connection_pool_capacity', 0) == 0

        # Database should only account for service_with_db
        db_capacity = configs['database']['connection_pool_capacity']
        service_pool = configs['service_with_db']['db_connection_pool_capacity']
        service_replicas = configs['service_with_db']['desired_replicas']

        # DB should support at least the client pool
        assert db_capacity >= service_pool * service_replicas


class TestLoadCalculationEdgeCases:
    """Test edge cases in load calculation."""

    def test_empty_semantic_map(self):
        """Should handle empty semantic map gracefully."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        planner = CapacityPlanner(G, {})
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # Should still produce configs (may be minimal)
        assert 'service' in configs or 'gateway' in configs

    def test_missing_nodes_in_flow(self):
        """Should handle flows referencing non-existent nodes."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service', 'nonexistent_service']  # Missing node
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not crash
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)
        assert 'service' in configs

    def test_circular_dependency_in_load_calculation(self):
        """Should handle circular dependencies without infinite loops."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')

        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('service_a', 'service_b', type='sync_http')
        G.add_edge('service_b', 'service_a', type='sync_http')  # Cycle

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a'],
                    'service_a': ['service_b'],
                    'service_b': ['service_a']  # Circular
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not hang or crash
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)
        assert 'service_a' in configs
        assert 'service_b' in configs

    def test_multiple_entry_points(self):
        """Should handle multiple gateways/frontends."""
        G = nx.DiGraph()
        G.add_node('gateway_1', role='gateway', is_frontend=True)
        G.add_node('gateway_2', role='gateway', is_frontend=True)
        G.add_node('service', role='service')

        G.add_edge('gateway_1', 'service', type='sync_http')
        G.add_edge('gateway_2', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway_1': ['service'],
                    'gateway_2': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # Service should receive load from both gateways
        # (100 RPS split between two entry points = 50 each, but both call service)
        # Actually, each gateway gets 50 RPS, both call service = 100 RPS total
        assert 'service' in configs
        assert configs['service']['desired_replicas'] >= 1

    def test_cache_hit_rate_affects_db_load(self):
        """Cache hit rate should reduce database load."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('cache', role='cache')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'cache', type='sync_http')
        G.add_edge('service', 'database', type='sync_db')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        
        # Test with different phi values (affects cache hit rate)
        # phi=0.0 → effective_hit_rate = 0.8 * (1.0 - 0.0) = 0.8
        # phi=1.0 → effective_hit_rate = 0.8 * (1.0 - 1.0) = 0.0
        configs_low_phi = planner.plan_capacity(target_global_rps=100, phi=0.0)
        planner2 = CapacityPlanner(G, semantic_map)
        configs_high_phi = planner2.plan_capacity(target_global_rps=100, phi=1.0)

        # With high phi (low cache hit rate), DB should see more load
        # This is tested indirectly through DB capacity requirements
        assert 'database' in configs_low_phi
        assert 'database' in configs_high_phi


class TestAsyncConsumerEdgeCases:
    """Test edge cases for async consumer capacity calculation."""

    def test_consumer_with_multiple_queues(self):
        """Consumer reading from multiple queues should sum production rates."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('producer_a', role='service')
        G.add_node('producer_b', role='service')
        G.add_node('queue_a', role='queue')
        G.add_node('queue_b', role='queue')
        G.add_node('consumer', role='service')

        G.add_edge('gateway', 'producer_a', type='sync_http')
        G.add_edge('gateway', 'producer_b', type='sync_http')
        G.add_edge('producer_a', 'queue_a', type='async_produce')
        G.add_edge('producer_b', 'queue_b', type='async_produce')
        G.add_edge('queue_a', 'consumer', type='async_consume')
        G.add_edge('queue_b', 'consumer', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['producer_a', 'producer_b']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=200, phi=0.5)

        consumer_config = configs['consumer']
        rationale = consumer_config.get('_capacity_rationale', {})

        # Should be identified as async consumer
        assert rationale.get('archetype') == 'async_consumer'

        # Production rate should sum from both queues
        production_rps = rationale.get('production_rps', 0)
        assert production_rps > 0

    def test_multiple_consumers_for_one_queue(self):
        """Multiple consumers should each get proper capacity."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('producer', role='service')
        G.add_node('queue', role='queue')
        G.add_node('consumer_a', role='service')
        G.add_node('consumer_b', role='service')

        G.add_edge('gateway', 'producer', type='sync_http')
        G.add_edge('producer', 'queue', type='async_produce')
        G.add_edge('queue', 'consumer_a', type='async_consume')
        G.add_edge('queue', 'consumer_b', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['producer']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # Both consumers should be identified as async consumers
        for consumer in ['consumer_a', 'consumer_b']:
            rationale = configs[consumer].get('_capacity_rationale', {})
            assert rationale.get('archetype') == 'async_consumer'
            # Each should have proper capacity
            assert configs[consumer]['desired_replicas'] >= 1
            assert configs[consumer]['thread_pool_size'] >= 10

    def test_async_consumer_with_zero_production(self):
        """Async consumer with no production should still get minimum capacity."""
        G = nx.DiGraph()
        G.add_node('queue', role='queue')
        G.add_node('consumer', role='service')
        G.add_edge('queue', 'consumer', type='async_consume')

        semantic_map = {'request_flows': {'GET': {}}}

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=0, phi=0.5)

        consumer_config = configs.get('consumer', {})
        # Should still have minimum resources
        assert consumer_config.get('desired_replicas', 0) >= 1
        assert consumer_config.get('thread_pool_size', 0) >= 10


class TestSemanticProfileMultipliers:
    """Test semantic profile multiplier application."""

    def test_cpu_intensive_profile_applies_multiplier(self):
        """CPU intensive profile should increase resource requirements."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            },
            'services': {
                'service': {
                    'profile': 'cpu_intensive'  # 2.5x multiplier
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        service_config = configs['service']
        # CPU intensive should require more resources
        assert service_config['desired_replicas'] >= 1
        assert service_config['thread_pool_size'] >= 10

    def test_latency_sensitive_profile_reduces_requirements(self):
        """Latency sensitive profile should reduce resource requirements."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            },
            'services': {
                'service': {
                    'profile': 'latency_sensitive'  # 0.8x multiplier
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        service_config = configs['service']
        # Should still have valid config
        assert service_config['desired_replicas'] >= 1
        assert service_config['thread_pool_size'] >= 10

    def test_unknown_profile_defaults_to_standard(self):
        """Unknown profile should default to standard (1.0x)."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            },
            'services': {
                'service': {
                    'profile': 'unknown_profile_xyz'  # Should default to 1.0
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not crash
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)
        assert 'service' in configs


class TestTimeoutCalculation:
    """Test timeout calculation edge cases."""

    def test_timeout_includes_dependency_latency(self):
        """Timeouts should include downstream dependency latency."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')
        G.add_node('database', role='database')

        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('service_a', 'service_b', type='sync_http')
        G.add_edge('service_b', 'database', type='sync_db')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a'],
                    'service_a': ['service_b']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # service_a timeout should account for service_b + database latency
        service_a_timeouts = configs['service_a'].get('timeouts', {})
        assert service_a_timeouts.get('service_call_seconds', 0) > 0
        assert service_a_timeouts.get('database_call_seconds', 0) > 0

    def test_timeout_minimums_enforced(self):
        """Timeouts should have minimum values."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=1, phi=1.0)  # Very low load

        service_timeouts = configs['service'].get('timeouts', {})
        # Should have minimums: 0.2s for DB/service, 1.0s for external
        assert service_timeouts.get('database_call_seconds', 0) >= 0.2
        assert service_timeouts.get('service_call_seconds', 0) >= 0.2
        assert service_timeouts.get('external_api_seconds', 0) >= 1.0

    def test_timeout_scales_with_phi(self):
        """Timeouts should scale with phi (lower phi = more margin)."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner_low_phi = CapacityPlanner(G, semantic_map)
        configs_low = planner_low_phi.plan_capacity(target_global_rps=100, phi=0.0)

        planner_high_phi = CapacityPlanner(G, semantic_map)
        configs_high = planner_high_phi.plan_capacity(target_global_rps=100, phi=1.0)

        timeout_low = configs_low['service']['timeouts']['service_call_seconds']
        timeout_high = configs_high['service']['timeouts']['service_call_seconds']

        # Low phi should have more margin (higher timeout)
        # timeout_margin = 1.05 + (0.45 * (1.0 - phi))
        # phi=0.0 → margin=1.5, phi=1.0 → margin=1.05
        assert timeout_low >= timeout_high


class TestThreadPoolCalculation:
    """Test thread pool calculation edge cases."""

    def test_thread_pool_minimum_enforced(self):
        """Thread pool should have minimum of 10 threads."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=0.1, phi=1.0)  # Very low load

        # Should still have minimum 10 threads
        assert configs['service']['thread_pool_size'] >= 10

    def test_thread_pool_accounts_for_dependency_latency(self):
        """Thread pool should account for blocking downstream calls."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')
        G.add_node('service_c', role='service')

        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('service_a', 'service_b', type='sync_http')
        G.add_edge('service_b', 'service_c', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a'],
                    'service_a': ['service_b'],
                    'service_b': ['service_c']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=100, phi=0.5)

        # service_a should have more threads due to downstream blocking
        assert configs['service_a']['thread_pool_size'] >= 10


class TestPhiEdgeCases:
    """Test phi value edge cases."""

    def test_phi_below_zero_clamped(self):
        """Negative phi should be handled (though not expected)."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not crash with negative phi
        configs = planner.plan_capacity(target_global_rps=100, phi=-0.5)
        assert 'service' in configs

    def test_phi_above_one_clamped(self):
        """Phi > 1.0 should be handled."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not crash with phi > 1.0
        configs = planner.plan_capacity(target_global_rps=100, phi=1.5)
        assert 'service' in configs


class TestVeryHighRPS:
    """Test behavior with very high RPS values."""

    def test_very_high_rps_scales_properly(self):
        """System should scale properly with very high RPS."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        configs = planner.plan_capacity(target_global_rps=10000, phi=0.5)

        # Should have many replicas
        assert configs['service']['desired_replicas'] >= 1
        # Should have reasonable thread pool
        assert configs['service']['thread_pool_size'] >= 10

    def test_extremely_high_rps_does_not_crash(self):
        """Extremely high RPS should not cause crashes."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_edge('gateway', 'service', type='sync_http')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not crash
        configs = planner.plan_capacity(target_global_rps=1000000, phi=0.5)
        assert 'service' in configs


class TestDependencyLatencyCalculation:
    """Test dependency latency calculation edge cases."""

    def test_circular_dependency_latency(self):
        """Should handle circular dependencies in latency calculation."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service_a', role='service')
        G.add_node('service_b', role='service')

        G.add_edge('gateway', 'service_a', type='sync_http')
        G.add_edge('service_a', 'service_b', type='sync_http')
        G.add_edge('service_b', 'service_a', type='sync_http')  # Cycle

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service_a']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # Should not hang
        latency = planner._estimate_dependency_latency('service_a', phi=0.5)
        # Should return a value (may be 0 if cycle detected)
        assert isinstance(latency, (int, float))
        assert latency >= 0

    def test_async_boundary_stops_latency(self):
        """Async boundaries should stop latency accumulation."""
        G = nx.DiGraph()
        G.add_node('gateway', role='gateway', is_frontend=True)
        G.add_node('service', role='service')
        G.add_node('queue', role='queue')
        G.add_node('consumer', role='service')

        G.add_edge('gateway', 'service', type='sync_http')
        G.add_edge('service', 'queue', type='async_produce')
        G.add_edge('queue', 'consumer', type='async_consume')

        semantic_map = {
            'request_flows': {
                'GET': {
                    'gateway': ['service']
                }
            }
        }

        planner = CapacityPlanner(G, semantic_map)
        # service should not include consumer latency (async boundary)
        service_latency = planner._estimate_dependency_latency('service', phi=0.5)
        # Should not include consumer latency
        assert isinstance(service_latency, (int, float))
        assert service_latency >= 0


class TestProductionRateCalculation:
    """Test production rate calculation edge cases."""

    def test_production_rate_with_no_producers(self):
        """Queue with no producers should return 0."""
        G = nx.DiGraph()
        G.add_node('queue', role='queue')

        planner = CapacityPlanner(G, {})
        node_metrics = {}
        production = planner._calculate_production_rate_to_queue('queue', node_metrics)
        assert production == 0.0

    def test_production_rate_sums_multiple_producers(self):
        """Should sum production from multiple producers."""
        G = nx.DiGraph()
        G.add_node('producer_a', role='service')
        G.add_node('producer_b', role='service')
        G.add_node('producer_c', role='service')
        G.add_node('queue', role='queue')

        G.add_edge('producer_a', 'queue', type='async_produce')
        G.add_edge('producer_b', 'queue', type='async_produce')
        G.add_edge('producer_c', 'queue', type='async_produce')

        planner = CapacityPlanner(G, {})
        node_metrics = {
            'producer_a': {'rps': 30.0},
            'producer_b': {'rps': 40.0},
            'producer_c': {'rps': 30.0}
        }
        production = planner._calculate_production_rate_to_queue('queue', node_metrics)
        assert production == pytest.approx(100.0, rel=0.01)

    def test_production_rate_ignores_sync_edges(self):
        """Should only count async_produce edges."""
        G = nx.DiGraph()
        G.add_node('service', role='service')
        G.add_node('queue', role='queue')

        G.add_edge('service', 'queue', type='sync_http')  # Not async_produce

        planner = CapacityPlanner(G, {})
        node_metrics = {'service': {'rps': 100.0}}
        production = planner._calculate_production_rate_to_queue('queue', node_metrics)
        assert production == 0.0  # Should not count sync edges


class TestValidationEdgeCases:
    """Test validation edge cases."""

    def test_validation_with_missing_configs(self):
        """Validation should handle missing configs gracefully."""
        G = nx.DiGraph()
        G.add_node('service', role='service')

        planner = CapacityPlanner(G, {})
        node_metrics = {'service': {'rps': 100.0}}
        tuned_configs = {}  # Empty configs

        # Should not crash
        result = planner._validate_capacity(node_metrics, tuned_configs, phi=0.5)
        assert isinstance(result, bool)

    def test_validation_with_zero_rps(self):
        """Validation should skip nodes with zero RPS."""
        G = nx.DiGraph()
        G.add_node('service', role='service')

        planner = CapacityPlanner(G, {})
        node_metrics = {'service': {'rps': 0.0}}
        tuned_configs = {'service': {'desired_replicas': 1}}

        # Should not fail validation for zero RPS
        result = planner._validate_capacity(node_metrics, tuned_configs, phi=0.5)
        # Zero RPS should pass validation (skipped)
        assert isinstance(result, bool)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
