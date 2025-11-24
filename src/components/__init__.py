"""
Component exports for the simulation.

New Architecture (Service/Pod/Node):
- Service: Lightweight coordinator
- Pod: Container instances (renamed from ComputeAgent)
- ComputeNode: Physical/VM resources
- DeploymentController: Centralized pod orchestrator

Legacy Architecture (for backward compatibility):
- ApiService: Original service with computation
- ComputeAgent: Original compute agent
"""

# New architecture components
from .service import Service
from .pod import Pod
from .compute_node import ComputeNode
from .deployment_controller import DeploymentController

# Legacy components (for backward compatibility)
from .service import ApiService
from .compute import ComputeAgent

# Infrastructure components
from .base_component import EnrichedComponent
from .database import SqlDatabase
from .storage import InMemoryCache
from .messaging import MessageQueue
from .external import ExternalService
from .networking import RequestGateway

__all__ = [
    # New architecture
    'Service',
    'Pod',
    'ComputeNode',
    'DeploymentController',
    # Legacy
    'ApiService',
    'ComputeAgent',
    # Infrastructure
    'EnrichedComponent',
    'SqlDatabase',
    'InMemoryCache',
    'MessageQueue',
    'ExternalService',
    'RequestGateway',
]
