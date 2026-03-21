"""
Test script to verify reverse physics implementation in causal_graph_reasoner.py

Tests:
1. Consumer slowdown → Queue depth increases (backward impact)
2. Consumer slowdown → Reduced throughput to downstream DB (forward impact)
"""

import networkx as nx
import numpy as np
from causal_graph_reasoner import CausalGraphReasoner
from dataclasses import dataclass
from typing import List

@dataclass
class HealthScore:
    """Mock health score for testing"""
    self_degradation_score: float
    symptom_type: str
    symptoms: List[str]
    score: float = 0.0

def test_reverse_physics_queue_backup():
    """
    Test Case 1: Consumer slowdown causes queue depth increase

    Topology:
    producer_service -> audit_queue -> audit_service -> audit_db

    Scenario:
    - audit_service slows down (3x latency)
    - audit_queue should show increased depth (reverse impact)
    """
    print("=" * 60)
    print("Test 1: Consumer Slowdown → Queue Backup")
    print("=" * 60)

    # Create topology
    topology = nx.DiGraph()
    topology.add_node('producer_service', type='Service')
    topology.add_node('audit_queue', type='MessageQueue', role='queue')
    topology.add_node('audit_service', type='Service')
    topology.add_node('audit_db', type='Database')

    topology.add_edge('producer_service', 'audit_queue')
    topology.add_edge('audit_queue', 'audit_service')
    topology.add_edge('audit_service', 'audit_db')

    # Create baseline metrics (healthy state)
    baseline = {
        'audit_service': {
            'service.audit_service.duration': [100, 105, 98, 102, 100],  # ~100ms
            'service.audit_service.error_rate': [0.01, 0.01, 0.01, 0.01, 0.01],  # 1%
            'service.audit_service.requests': [100, 105, 98, 102, 100],  # ~100 RPS
            'service.audit_service.dependency.requests': [50, 52, 48, 51, 49],  # ~50 RPS to DB
        },
        'audit_queue': {
            'mq.messages.depth': [10, 12, 9, 11, 10],  # ~10 messages
            'mq.messages.age': [50, 55, 48, 52, 50],  # ~50ms age
        },
        'audit_db': {
            'service.audit_db.requests': [50, 52, 48, 51, 49],  # ~50 RPS
        },
    }

    # Create current metrics (fault state)
    current = {
        'audit_service': {
            'service.audit_service.duration': [300, 320, 310, 295, 305],  # 3x slower (300ms)
            'service.audit_service.error_rate': [0.05, 0.06, 0.05, 0.05, 0.06],  # 5% errors
            'service.audit_service.requests': [100, 105, 98, 102, 100],  # Same RPS
            'service.audit_service.dependency.requests': [30, 32, 28, 31, 29],  # Reduced to ~30 RPS
        },
        'audit_queue': {
            'mq.messages.depth': [150, 160, 155, 148, 152],  # 15x increase (queue backing up)
            'mq.messages.age': [500, 520, 510, 495, 505],  # 10x older (messages aging)
        },
        'audit_db': {
            'service.audit_db.requests': [30, 32, 28, 31, 29],  # Reduced to ~30 RPS (matches consumer)
        },
    }

    # Create health scores
    health_scores = {
        'audit_service': HealthScore(
            self_degradation_score=5.0,  # Degraded
            symptom_type='primary',
            symptoms=['High latency', 'Errors'],
            score=5.0
        ),
        'audit_queue': HealthScore(
            self_degradation_score=3.0,  # Shows symptoms
            symptom_type='secondary',  # But it's SECONDARY (caused by consumer)
            symptoms=['High queue depth', 'Message aging'],
            score=3.0
        ),
        'audit_db': HealthScore(
            self_degradation_score=2.0,  # Slight degradation
            symptom_type='secondary',
            symptoms=['Reduced load'],
            score=2.0
        ),
    }

    # Run RCA
    reasoner = CausalGraphReasoner(topology)

    # Test audit_service as root cause
    hypothesis = reasoner._trace_blast_radius('audit_service', health_scores, baseline, current)

    print("\nRoot Cause:", hypothesis.root_cause_node)
    print("Explained Nodes:", hypothesis.explained_nodes)
    print("\nNarrative:")
    for line in hypothesis.narrative:
        print(f"  {line}")

    # Verify reverse impact detected
    assert 'audit_queue' in hypothesis.explained_nodes, "❌ Queue should be explained by consumer"
    assert 'audit_db' in hypothesis.explained_nodes, "❌ DB should be explained by consumer"

    # Check for reverse impact in narrative
    reverse_queue_found = any('Reverse impact on audit_queue' in line for line in hypothesis.narrative)
    reverse_db_found = any('Reverse impact on audit_db' in line for line in hypothesis.narrative)

    assert reverse_queue_found, "❌ Should detect reverse impact on queue"
    assert reverse_db_found, "❌ Should detect reverse impact on DB"

    print("\n✅ Test 1 PASSED: Reverse physics detected consumer impact on queue and DB")


def test_no_reverse_impact_when_consumer_healthy():
    """
    Test Case 2: No reverse impact when consumer is healthy

    Scenario:
    - Queue depth increases BUT consumer is healthy
    - Should NOT attribute queue backup to consumer
    """
    print("\n" + "=" * 60)
    print("Test 2: No Reverse Impact When Consumer Healthy")
    print("=" * 60)

    # Create topology
    topology = nx.DiGraph()
    topology.add_node('audit_queue', type='MessageQueue', role='queue')
    topology.add_node('audit_service', type='Service')

    topology.add_edge('audit_queue', 'audit_service')

    # Baseline
    baseline = {
        'audit_service': {
            'service.audit_service.duration': [100, 105, 98, 102, 100],
            'service.audit_service.error_rate': [0.01, 0.01, 0.01, 0.01, 0.01],
        },
        'audit_queue': {
            'mq.messages.depth': [10, 12, 9, 11, 10],
        },
    }

    # Current: Queue backed up but consumer is HEALTHY
    current = {
        'audit_service': {
            'service.audit_service.duration': [102, 105, 98, 100, 103],  # Still healthy
            'service.audit_service.error_rate': [0.01, 0.01, 0.01, 0.01, 0.01],  # No errors
        },
        'audit_queue': {
            'mq.messages.depth': [150, 160, 155, 148, 152],  # Backed up (maybe producer issue)
        },
    }

    health_scores = {
        'audit_service': HealthScore(
            self_degradation_score=1.0,  # Healthy
            symptom_type='healthy',
            symptoms=[],
            score=1.0
        ),
        'audit_queue': HealthScore(
            self_degradation_score=4.0,  # Degraded
            symptom_type='primary',  # Primary fault (not consumer's fault)
            symptoms=['High queue depth'],
            score=4.0
        ),
    }

    # Run RCA
    reasoner = CausalGraphReasoner(topology)
    hypothesis = reasoner._trace_blast_radius('audit_service', health_scores, baseline, current)

    print("\nRoot Cause:", hypothesis.root_cause_node)
    print("Explained Nodes:", hypothesis.explained_nodes)

    # Verify NO reverse impact detected (consumer is healthy)
    reverse_queue_found = any('Reverse impact on audit_queue' in line for line in hypothesis.narrative)

    assert not reverse_queue_found, "❌ Should NOT detect reverse impact when consumer is healthy"

    print("✅ Test 2 PASSED: No false positive reverse impact when consumer is healthy")


if __name__ == '__main__':
    try:
        test_reverse_physics_queue_backup()
        test_no_reverse_impact_when_consumer_healthy()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED - Reverse Physics Implementation Verified")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
