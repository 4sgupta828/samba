"""
Infrastructure Context Exporter

Exports a rich infrastructure graph with performance baselines, failure patterns,
and remediation knowledge for RCA investigations.
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import os


class InfrastructureContextExporter:
    """Exports infrastructure context for RCA investigations."""

    def __init__(self, component_registry: Dict[str, Any], deployment_events: Optional[List[Dict[str, Any]]] = None):
        self.registry = component_registry
        self.deployment_events = deployment_events or []

    def export_to_file(self, output_dir: str, filename: str = "infra_context.json"):
        """Export infrastructure context to a JSON file."""
        context = self._build_context()

        output_path = os.path.join(output_dir, filename)
        with open(output_path, 'w') as f:
            json.dump(context, f, indent=2)

        return output_path

    def _build_context(self) -> Dict[str, Any]:
        """Build the complete infrastructure context."""
        return {
            "metadata": self._get_metadata(),
            "architecture": self._get_architecture_graph()
        }

    def _get_metadata(self) -> Dict[str, Any]:
        """Get metadata about the infrastructure."""
        return {
            "exported_at": datetime.now().isoformat(),
            "version": "1.1",
            "description": "Infrastructure context for RCA investigations",
            "purpose": "SYSTEM_TOPOLOGY_AND_ONTOLOGY",
            "usage": {
                "role": "This file provides the static system architecture graph, component configurations, deployment history, and knowledge base",
                "for_time_series_data": "Use metrics.jsonl for CPU/memory/latency trends over time",
                "for_logs": "Use logs.jsonl for event timeline and error patterns",
                "for_traces": "Use traces.jsonl for distributed request flows",
                "for_metadata": "Use metadata.json for incident timeline and failure injections",
                "for_deployments": "Each component's deployment_history field shows what code changes were deployed during simulation"
            },
            "state_snapshot": {
                "note": "The 'state' fields show component status at export time, not historical trends",
                "for_rca": "Use time-series telemetry data to analyze changes during the incident window"
            },
            "deployment_tracking": {
                "description": "Each component includes a deployment_history field tracking all deployments that affected it",
                "fields": {
                    "commit_id": "Unique identifier for the deployed commit",
                    "simulation_time": "When the deployment occurred (in simulation seconds)",
                    "service_name": "Service being deployed",
                    "author": "Who made the commit",
                    "message": "Commit message describing the change",
                    "timestamp": "Real-world timestamp of the commit",
                    "change_type": "Type of change (e.g., BUG_INTRODUCTION, PERFORMANCE_IMPROVEMENT)",
                    "changes_applied": "Dictionary of parameters that were modified (e.g., leak_mb_per_request, latency_multiplier)"
                },
                "for_rca": "Correlate deployment events with incident start times to identify if a deployment caused the issue"
            }
        }

    def _get_architecture_graph(self) -> Dict[str, Any]:
        """Build the architecture graph with all components and relationships."""
        components = []
        relationships = []

        for comp_id, component in self.registry.items():
            # Calculate aggregate metrics for services
            state_info = self._get_component_state(component)

            component_info = {
                "id": comp_id,
                "type": component.__class__.__name__,
                "name": getattr(component, 'name', comp_id),
                "config": self._extract_component_config(component),
                "state": state_info,
                "capabilities": self._get_component_capabilities(component),
                "deployment_history": self._get_deployment_history_for_component(comp_id, component)
            }
            components.append(component_info)

            # Extract relationships (dependencies)
            if hasattr(component, 'dependencies'):
                for dep in component.dependencies:
                    relationships.append({
                        "source": comp_id,
                        "target": dep.component_id if hasattr(dep, 'component_id') else str(dep),
                        "type": "depends_on"
                    })

            # Extract connections (for services -> compute agents, etc.)
            if hasattr(component, 'connections'):
                # Handle compute pool connections
                compute_pool = component.connections.get('compute_pool', [])
                for compute_agent in compute_pool:
                    # Extract just the ID, not the string representation
                    agent_id = compute_agent.id if hasattr(compute_agent, 'id') else (
                        compute_agent.component_id if hasattr(compute_agent, 'component_id') else str(compute_agent)
                    )
                    relationships.append({
                        "source": comp_id,
                        "target": agent_id,
                        "type": "uses_compute"
                    })

                # Handle database connections
                database = component.connections.get('database')
                if database:
                    db_id = database.id if hasattr(database, 'id') else (
                        database.component_id if hasattr(database, 'component_id') else str(database)
                    )
                    relationships.append({
                        "source": comp_id,
                        "target": db_id,
                        "type": "uses_database"
                    })

                # Handle cache connections
                cache = component.connections.get('cache')
                if cache:
                    cache_id = cache.id if hasattr(cache, 'id') else (
                        cache.component_id if hasattr(cache, 'component_id') else str(cache)
                    )
                    relationships.append({
                        "source": comp_id,
                        "target": cache_id,
                        "type": "uses_cache"
                    })

                # Handle queue connections
                queue = component.connections.get('queue')
                if queue:
                    queue_id = queue.id if hasattr(queue, 'id') else (
                        queue.component_id if hasattr(queue, 'component_id') else str(queue)
                    )
                    relationships.append({
                        "source": comp_id,
                        "target": queue_id,
                        "type": "uses_queue"
                    })

                # Handle service-to-service connections
                inventory_service = component.connections.get('inventory_service')
                if inventory_service:
                    inv_id = inventory_service.id if hasattr(inventory_service, 'id') else (
                        inventory_service.component_id if hasattr(inventory_service, 'component_id') else str(inventory_service)
                    )
                    relationships.append({
                        "source": comp_id,
                        "target": inv_id,
                        "type": "calls_service"
                    })

        return {
            "components": components,
            "relationships": relationships,
            "component_count": len(components),
            "relationship_count": len(relationships)
        }

    def _get_component_state(self, component: Any) -> Dict[str, Any]:
        """
        Get component state, with aggregation for services.

        For services, aggregate CPU and memory from their compute pool.
        For other components, return direct state.
        """
        # Check if this is a service with compute pool
        if hasattr(component, 'connections'):
            compute_pool = component.connections.get('compute_pool', [])
            if compute_pool and len(compute_pool) > 0:
                # Aggregate metrics from compute agents
                total_cpu = 0.0
                total_memory = 0.0
                healthy_agents = 0

                for agent in compute_pool:
                    if hasattr(agent, 'state'):
                        if agent.state.operational == 'RUNNING':
                            total_cpu += agent.state.cpu_utilization
                            total_memory += agent.state.memory_usage_mb
                            healthy_agents += 1

                if healthy_agents > 0:
                    return {
                        "operational": component.state.operational,
                        "cpu_utilization": total_cpu / healthy_agents,
                        "memory_usage_mb": total_memory / healthy_agents,
                        "compute_pool_size": len(compute_pool),
                        "healthy_compute_agents": healthy_agents
                    }

        # Default: return direct state
        return {
            "operational": component.state.operational,
            "cpu_utilization": component.state.cpu_utilization,
            "memory_usage_mb": component.state.memory_usage_mb
        }

    def _extract_component_config(self, component: Any) -> Dict[str, Any]:
        """Extract configuration from a component.

        This is critical for RCA - change correlation requires knowing versions,
        capacity limits, and configuration parameters.
        """
        config = {}

        # Extract version information (critical for deployment correlation)
        if hasattr(component, 'version'):
            config['version'] = component.version

        # Extract IaC configuration (from Terraform/HCL)
        if hasattr(component, 'iac_config'):
            iac = component.iac_config
            # Common IaC fields
            if 'instance_type' in iac:
                config['instance_type'] = iac['instance_type']
            if 'instance_class' in iac:
                config['instance_class'] = iac['instance_class']
            if 'ami' in iac:
                config['ami'] = iac['ami']
            if 'allocated_storage' in iac:
                config['allocated_storage_gb'] = iac['allocated_storage']
            if 'engine' in iac:
                config['engine'] = iac['engine']
            if 'node_type' in iac:
                config['node_type'] = iac['node_type']

        # Service-specific configuration
        if hasattr(component, 'service_name'):
            config['service_name'] = component.service_name
        if hasattr(component, 'supported_request_types'):
            config['supported_request_types'] = component.supported_request_types

        # Compute Agent configuration
        if hasattr(component, 'memory_capacity_mb'):
            config['memory_limit_mb'] = component.memory_capacity_mb
        if hasattr(component, 'db_connection_pool'):
            config['connection_pool_capacity'] = component.db_connection_pool.capacity
        if hasattr(component, 'restarts'):
            config['restart_count'] = component.restarts

        # Deployment-triggered behavior (for detecting buggy deployments)
        if hasattr(component, 'leak_mb_per_request'):
            if component.leak_mb_per_request > 0:
                config['leak_mb_per_request'] = component.leak_mb_per_request
        if hasattr(component, 'latency_multiplier'):
            if component.latency_multiplier != 1.0:
                config['latency_multiplier'] = component.latency_multiplier
        if hasattr(component, 'error_rate_multiplier'):
            if component.error_rate_multiplier != 1.0:
                config['error_rate_multiplier'] = component.error_rate_multiplier
        if hasattr(component, 'cpu_multiplier'):
            if component.cpu_multiplier != 1.0:
                config['cpu_multiplier'] = component.cpu_multiplier

        # Database configuration (critical for connection pool exhaustion)
        if hasattr(component, 'connection_pool'):
            config['max_connections'] = component.connection_pool.capacity
        if hasattr(component, 'cpu_resource'):
            config['cpu_cores'] = component.cpu_resource.capacity
        if hasattr(component, 'wear_factor'):
            config['db_wear_factor'] = component.wear_factor
        if hasattr(component, 'background_job_enabled'):
            config['background_job_enabled'] = component.background_job_enabled

        # Auto-scaling configuration
        if hasattr(component, 'scaling_policy') and component.scaling_policy:
            policy = component.scaling_policy
            config['min_capacity'] = policy.min_size
            config['max_capacity'] = policy.max_size
            config['desired_capacity'] = policy.desired_capacity
            config['target_cpu_utilization'] = getattr(policy, 'target_value', 70.0)

        # Cache configuration
        if hasattr(component, 'max_memory_mb'):
            config['max_memory_mb'] = component.max_memory_mb
        if hasattr(component, 'eviction_policy'):
            config['eviction_policy'] = component.eviction_policy

        # Queue configuration
        if hasattr(component, 'max_queue_depth'):
            config['max_queue_depth'] = component.max_queue_depth
        if hasattr(component, 'message_retention_seconds'):
            config['message_retention_seconds'] = component.message_retention_seconds

        return config

    def _get_component_capabilities(self, component: Any) -> List[str]:
        """Get capabilities of a component."""
        capabilities = []

        # Check for various capabilities
        if hasattr(component, 'handle_request'):
            capabilities.append("request_handling")
        if hasattr(component, 'execute_query'):
            capabilities.append("database_query")
        if hasattr(component, 'scale'):
            capabilities.append("auto_scaling")
        if hasattr(component, 'route_request'):
            capabilities.append("load_balancing")

        return capabilities

    def _get_deployment_history_for_component(self, component_id: str, component: Any) -> List[Dict[str, Any]]:
        """Get deployment history for a specific component.

        For services (ApiService), return all deployments that targeted that service.
        For other component types, return empty list (deployments tracked at service level).

        Args:
            component_id: ID of the component
            component: The actual component object

        Returns:
            List of deployment events that affected this component
        """
        # Only attach deployment history to service-level components
        # Check if this is a service component (has service_name or is ApiService)
        from src.components.service import ApiService
        if not isinstance(component, ApiService):
            return []  # Only services get deployment history

        component_deployments = []

        for event in self.deployment_events:
            # Match deployment events to this service by checking component_filter
            component_filter = event.get('component_filter', {})

            # Check if this service's compute agents match the deployment filter
            is_match = False
            if hasattr(component, 'connections'):
                compute_pool = component.connections.get('compute_pool', [])
                # Check if any compute agent in this service matches the filter
                for agent in compute_pool:
                    if self._matches_deployment_filter(agent, component_filter):
                        is_match = True
                        break

            if is_match:
                # Create a clean deployment record
                deployment_record = {
                    "commit_id": event["commit_id"],
                    "simulation_time": event["simulation_time"],
                    "service_name": event["service_name"],
                    "author": event["author"],
                    "message": event["message"],
                    "timestamp": event["timestamp"],
                    "change_type": event["change_type"],
                    "changes_applied": event["changes_applied"]
                }
                component_deployments.append(deployment_record)

        # Sort by simulation time
        component_deployments.sort(key=lambda x: x["simulation_time"])

        return component_deployments

    def _matches_deployment_filter(self, agent: Any, component_filter: Dict[str, Any]) -> bool:
        """Check if a compute agent matches the deployment filter.

        Args:
            agent: ComputeAgent to check
            component_filter: Filter criteria from deployment

        Returns:
            True if agent matches filter
        """
        if not component_filter:
            return True  # Empty filter matches all

        # Check IaC config attributes (like ami)
        if hasattr(agent, 'iac_config'):
            for key, value in component_filter.items():
                if agent.iac_config.get(key) != value:
                    return False
        else:
            return False

        return True

    def _get_performance_baselines(self) -> Dict[str, Any]:
        """Get healthy performance baselines for each component type."""
        return {
            "ComputeAgent": {
                "cpu_utilization": {
                    "healthy_range": [20, 60],
                    "warning_threshold": 75,
                    "critical_threshold": 90,
                    "unit": "percent"
                },
                "memory_usage": {
                    "healthy_range": [30, 70],
                    "warning_threshold": 80,
                    "critical_threshold": 95,
                    "unit": "percent_of_limit"
                },
                "response_time": {
                    "healthy_p50": 50,
                    "healthy_p95": 150,
                    "healthy_p99": 300,
                    "warning_threshold": 500,
                    "critical_threshold": 1000,
                    "unit": "milliseconds"
                },
                "error_rate": {
                    "healthy_rate": 0.1,
                    "warning_threshold": 1.0,
                    "critical_threshold": 5.0,
                    "unit": "percent"
                },
                "connection_pool": {
                    "healthy_utilization": 50,
                    "warning_threshold": 80,
                    "critical_threshold": 95,
                    "unit": "percent_of_pool_size"
                }
            },
            "SqlDatabase": {
                "cpu_utilization": {
                    "healthy_range": [20, 50],
                    "warning_threshold": 70,
                    "critical_threshold": 85,
                    "unit": "percent"
                },
                "active_connections": {
                    "healthy_range": [10, 50],
                    "warning_threshold": 80,
                    "critical_threshold": 95,
                    "unit": "percent_of_max_connections"
                },
                "query_latency": {
                    "healthy_p50": 10,
                    "healthy_p95": 50,
                    "healthy_p99": 100,
                    "warning_threshold": 200,
                    "critical_threshold": 500,
                    "unit": "milliseconds"
                },
                "rejected_connections": {
                    "healthy_rate": 0,
                    "warning_threshold": 1,
                    "critical_threshold": 10,
                    "unit": "connections_per_minute"
                }
            },
            "AutoScalingGroup": {
                "instance_count": {
                    "healthy_range": "min_to_max",
                    "scaling_trigger_cpu": 70,
                    "scaling_trigger_memory": 80,
                    "unit": "instances"
                }
            },
            "RequestGateway": {
                "response_time": {
                    "healthy_p50": 100,
                    "healthy_p95": 300,
                    "healthy_p99": 500,
                    "warning_threshold": 1000,
                    "critical_threshold": 3000,
                    "unit": "milliseconds"
                },
                "throughput": {
                    "healthy_range": "workload_dependent",
                    "unit": "requests_per_second"
                }
            },
            "MessageQueue": {
                "queue_depth": {
                    "healthy_range": [0, 100],
                    "warning_threshold": 1000,
                    "critical_threshold": 10000,
                    "unit": "messages"
                },
                "message_age": {
                    "healthy_max": 60,
                    "warning_threshold": 300,
                    "critical_threshold": 600,
                    "unit": "seconds"
                }
            },
            "InMemoryCache": {
                "hit_rate": {
                    "healthy_range": [80, 99],
                    "warning_threshold": 70,
                    "critical_threshold": 50,
                    "unit": "percent"
                },
                "memory_usage": {
                    "healthy_range": [40, 80],
                    "warning_threshold": 90,
                    "critical_threshold": 95,
                    "unit": "percent"
                }
            }
        }

    def _get_failure_patterns(self) -> Dict[str, Any]:
        """Get common failure patterns with symptoms and causes."""
        return {
            "connection_pool_exhaustion": {
                "description": "Database connection pool runs out of available connections",
                "symptoms": [
                    "Increasing queue depth on application servers",
                    "High connection pool utilization (>90%)",
                    "Increased request latency",
                    "Connection timeout errors",
                    "Database shows max connections reached"
                ],
                "root_causes": [
                    "Database queries taking longer than expected (latency injection)",
                    "Connections not being released properly",
                    "Sudden spike in traffic",
                    "Database performance degradation",
                    "Pool size too small for workload"
                ],
                "indicators": {
                    "metric_patterns": [
                        "connection_pool.connections.active approaching max",
                        "connection_pool.queue_depth increasing",
                        "db.query.latency increasing",
                        "request.duration increasing"
                    ],
                    "log_patterns": [
                        "Connection pool exhausted",
                        "Timeout acquiring connection",
                        "Maximum connections reached"
                    ]
                },
                "affected_components": ["ComputeAgent", "SqlDatabase"]
            },
            "memory_leak_oom": {
                "description": "Component experiences memory leak leading to OOM kill",
                "symptoms": [
                    "Steadily increasing memory usage over time",
                    "Container restarts with OOMKilled",
                    "Performance degradation before restart",
                    "Exponential backoff restart pattern"
                ],
                "root_causes": [
                    "Memory not being freed after requests",
                    "Leaked references in application code",
                    "Unbounded cache growth",
                    "Memory leak in third-party library"
                ],
                "indicators": {
                    "metric_patterns": [
                        "container.memory.usage_mb steadily increasing",
                        "memory_usage approaching memory_limit",
                        "Repeated container restarts",
                        "CrashLoopBackOff state"
                    ],
                    "log_patterns": [
                        "OOMKilled",
                        "Out of memory",
                        "Memory limit exceeded",
                        "Container restarting"
                    ]
                },
                "affected_components": ["ComputeAgent", "ProductCatalogService", "OrderService"]
            },
            "database_contention": {
                "description": "Database background jobs compete for CPU/IO resources",
                "symptoms": [
                    "Increased query latency during specific time windows",
                    "High database CPU utilization",
                    "Slow application response times",
                    "Query timeouts"
                ],
                "root_causes": [
                    "VACUUM/ANALYZE jobs running during peak hours",
                    "Index rebuilds during business hours",
                    "Backup operations competing for resources",
                    "Poor maintenance window scheduling"
                ],
                "indicators": {
                    "metric_patterns": [
                        "db.cpu.utilization spikes",
                        "db.query.latency increases during specific periods",
                        "Background job CPU usage visible"
                    ],
                    "log_patterns": [
                        "VACUUM running",
                        "Autovacuum",
                        "Query timeout",
                        "Long-running query"
                    ]
                },
                "affected_components": ["SqlDatabase"]
            },
            "deployment_induced_errors": {
                "description": "New deployment introduces bugs causing errors or performance degradation",
                "symptoms": [
                    "Error rate spike after deployment",
                    "Latency increase after deployment",
                    "CPU usage increase after deployment",
                    "Memory leak starts after deployment"
                ],
                "root_causes": [
                    "Buggy code in new release",
                    "Incompatible dependency versions",
                    "Configuration errors",
                    "Unoptimized algorithms in new code"
                ],
                "indicators": {
                    "metric_patterns": [
                        "error_rate increases after commit deployment",
                        "latency_multiplier > 1.0 correlated with deployment",
                        "cpu_multiplier > 1.0 correlated with deployment"
                    ],
                    "log_patterns": [
                        "Deployment started",
                        "Commit deployed",
                        "Version changed",
                        "Exception in new code path"
                    ],
                    "temporal_correlation": "Symptoms start within minutes of deployment event"
                },
                "affected_components": ["ComputeAgent", "ProductCatalogService", "OrderService", "UserAccountService", "InventoryService"]
            },
            "cascading_failure": {
                "description": "Failure in one component cascades to dependent services",
                "symptoms": [
                    "Multiple services showing degraded state",
                    "Errors propagating through service chain",
                    "Timeouts in upstream services",
                    "Circuit breakers opening"
                ],
                "root_causes": [
                    "Downstream service failure causing upstream timeouts",
                    "Retry storms amplifying load",
                    "Lack of proper timeout/circuit breaker configuration",
                    "Synchronous dependencies without fallbacks"
                ],
                "indicators": {
                    "metric_patterns": [
                        "Errors starting in one component then spreading",
                        "Latency increases propagating upstream",
                        "Multiple components entering DEGRADED state"
                    ],
                    "log_patterns": [
                        "Downstream service unavailable",
                        "Timeout calling dependency",
                        "Circuit breaker open"
                    ],
                    "temporal_correlation": "Failures follow dependency graph topology"
                },
                "affected_components": ["All components with dependencies"]
            },
            "over_provisioning": {
                "description": "Resources allocated far exceed actual usage",
                "symptoms": [
                    "Consistently low CPU utilization (<20%)",
                    "Low memory usage (<30%)",
                    "Excess capacity in connection pools",
                    "High infrastructure costs for workload"
                ],
                "root_causes": [
                    "Conservative capacity planning",
                    "Traffic patterns changed after initial sizing",
                    "Auto-scaling not tuned properly",
                    "Legacy configuration not updated"
                ],
                "indicators": {
                    "metric_patterns": [
                        "cpu_utilization consistently < 20%",
                        "memory_usage consistently < 30%",
                        "connection_pool.connections.active << max_connections"
                    ]
                },
                "affected_components": ["SqlDatabase", "ComputeAgent", "AutoScalingGroup"],
                "optimization_opportunity": True
            }
        }

    def _get_remediation_playbook(self) -> Dict[str, Any]:
        """Get remediation playbook for common issues."""
        return {
            "connection_pool_exhaustion": {
                "immediate_actions": [
                    {
                        "action": "Identify slow queries",
                        "command": "Check db.query.latency metrics for p99 spikes",
                        "expected_result": "Identify queries taking >200ms"
                    },
                    {
                        "action": "Check database health",
                        "command": "Review db.cpu.utilization and db.connections.active",
                        "expected_result": "Determine if DB is bottleneck"
                    },
                    {
                        "action": "Review recent changes",
                        "command": "Check deployment logs for recent code changes",
                        "expected_result": "Identify if new code introduced slow queries"
                    }
                ],
                "short_term_fixes": [
                    "Increase connection pool size on application servers",
                    "Increase database max_connections limit",
                    "Add connection timeouts to prevent indefinite holds",
                    "Scale out application tier to distribute load"
                ],
                "long_term_fixes": [
                    "Optimize slow database queries",
                    "Add database indexes for common queries",
                    "Implement connection pooling best practices",
                    "Add query performance monitoring",
                    "Consider read replicas for read-heavy workloads"
                ],
                "rollback_trigger": "If caused by recent deployment, rollback to previous version"
            },
            "memory_leak_oom": {
                "immediate_actions": [
                    {
                        "action": "Identify leaking component",
                        "command": "Check container.memory.usage_mb trend over time",
                        "expected_result": "Find component with steadily increasing memory"
                    },
                    {
                        "action": "Check recent deployments",
                        "command": "Review deployment timeline vs memory leak start",
                        "expected_result": "Correlate leak with specific deployment"
                    },
                    {
                        "action": "Review component logs",
                        "command": "Check for OOMKilled and restart patterns",
                        "expected_result": "Confirm OOM crashes"
                    }
                ],
                "short_term_fixes": [
                    "Increase memory limits to buy time for proper fix",
                    "Implement periodic component restarts as workaround",
                    "Rollback to previous known-good version"
                ],
                "long_term_fixes": [
                    "Profile application to identify leak source",
                    "Fix memory leak in application code",
                    "Add memory monitoring and alerts",
                    "Implement proper resource cleanup (close connections, clear caches)",
                    "Add unit tests for resource lifecycle"
                ],
                "rollback_trigger": "Immediately if deployment correlation confirmed"
            },
            "database_contention": {
                "immediate_actions": [
                    {
                        "action": "Check database background jobs",
                        "command": "Review database logs for VACUUM, ANALYZE, or backup operations",
                        "expected_result": "Identify resource-intensive background jobs"
                    },
                    {
                        "action": "Monitor database CPU",
                        "command": "Check db.cpu.utilization during incident",
                        "expected_result": "Confirm CPU saturation during specific time windows"
                    }
                ],
                "short_term_fixes": [
                    "Stop or pause non-critical background jobs",
                    "Kill long-running maintenance queries",
                    "Temporarily increase database CPU allocation"
                ],
                "long_term_fixes": [
                    "Reschedule maintenance jobs to off-peak hours",
                    "Tune autovacuum settings to be less aggressive",
                    "Implement maintenance windows",
                    "Add resource limits to background jobs",
                    "Consider read replica for reporting queries"
                ],
                "prevention": [
                    "Schedule VACUUM during low-traffic periods",
                    "Use autovacuum_naptime configuration",
                    "Monitor database maintenance schedule"
                ]
            },
            "deployment_induced_errors": {
                "immediate_actions": [
                    {
                        "action": "Correlate error spike with deployment",
                        "command": "Compare error_rate timeline with deployment events",
                        "expected_result": "Confirm error increase started after specific deployment"
                    },
                    {
                        "action": "Check deployment logs",
                        "command": "Review which commit/version was deployed",
                        "expected_result": "Identify specific code change"
                    },
                    {
                        "action": "Review error messages",
                        "command": "Check application logs for new error patterns",
                        "expected_result": "Understand nature of errors"
                    }
                ],
                "short_term_fixes": [
                    "Rollback to previous known-good version immediately",
                    "Implement feature flag to disable new functionality",
                    "Route traffic away from affected service instances"
                ],
                "long_term_fixes": [
                    "Fix bug in new code",
                    "Add automated tests to catch regression",
                    "Implement canary deployments for gradual rollout",
                    "Add deployment monitoring and auto-rollback",
                    "Improve code review process"
                ],
                "rollback_trigger": "Immediately if error rate exceeds acceptable threshold",
                "prevention": [
                    "Use blue-green or canary deployment strategies",
                    "Implement automated testing in CI/CD",
                    "Add deployment health checks",
                    "Use feature flags for risky changes"
                ]
            },
            "cascading_failure": {
                "immediate_actions": [
                    {
                        "action": "Identify root cause component",
                        "command": "Trace errors backward through dependency graph",
                        "expected_result": "Find the originating failed component"
                    },
                    {
                        "action": "Check component states",
                        "command": "Review operational state of all components",
                        "expected_result": "Map out which components are DOWN or DEGRADED"
                    },
                    {
                        "action": "Isolate failure",
                        "command": "Implement circuit breakers or disable failing dependency",
                        "expected_result": "Prevent failure from spreading further"
                    }
                ],
                "short_term_fixes": [
                    "Fix or restart the root cause component",
                    "Implement circuit breakers to isolate failures",
                    "Add fallback/degraded mode for dependent services",
                    "Scale out healthy instances to handle load"
                ],
                "long_term_fixes": [
                    "Implement proper timeout and retry policies",
                    "Add circuit breakers on all external dependencies",
                    "Design services for graceful degradation",
                    "Reduce synchronous dependencies where possible",
                    "Add chaos engineering tests to validate resilience"
                ],
                "prevention": [
                    "Use bulkheads to isolate failures",
                    "Implement retry with exponential backoff",
                    "Add timeouts to all external calls",
                    "Design for failure scenarios"
                ]
            },
            "over_provisioning": {
                "immediate_actions": [
                    {
                        "action": "Analyze resource utilization trends",
                        "command": "Review cpu_utilization and memory_usage over 7-30 days",
                        "expected_result": "Confirm consistently low utilization"
                    },
                    {
                        "action": "Review capacity vs workload",
                        "command": "Compare provisioned capacity to actual demand",
                        "expected_result": "Quantify excess capacity"
                    }
                ],
                "optimization_steps": [
                    "Right-size database instance to match actual workload",
                    "Reduce connection pool sizes to appropriate levels",
                    "Tune auto-scaling thresholds and min/max instances",
                    "Consider smaller instance types with similar performance"
                ],
                "validation": [
                    "Implement changes in staging first",
                    "Monitor performance under peak load",
                    "Verify cost reduction without performance impact",
                    "Maintain headroom for growth (20-30%)"
                ],
                "caution": "Leave sufficient headroom for traffic spikes and growth. Don't optimize to point of fragility."
            }
        }
