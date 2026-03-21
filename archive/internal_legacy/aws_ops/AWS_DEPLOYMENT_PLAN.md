# AWS Real Service Deployment Plan

## Overview

Transition from simulation to real distributed services on AWS that generate real telemetry data for RCA analysis. This plan provides a minimal starting point and a scalable framework for adding more services.

## Goals

1. **Deploy minimal distributed system** on AWS with core service types
2. **Generate real telemetry** (metrics, logs, traces) in same format as simulation
3. **Use existing RCA tool** (`analysis2/whitebox_rca.py`) without modification
4. **Enable scaling** to more diverse services over time
5. **All services Python-based** for consistency and ease of maintenance

## Architecture

### Component Mapping (Simulation → Real Services)

| Simulation Component | Real AWS Service | Technology | Purpose |
|---------------------|------------------|------------|---------|
| `ApiService` | Python Flask/FastAPI service | ECS/EKS Pod | Business logic service |
| `SqlDatabase` | PostgreSQL RDS | RDS or containerized | Persistent storage |
| `InMemoryCache` | Redis | ElastiCache or containerized | Caching layer |
| `MessageQueue` | RabbitMQ or SQS | Containerized or SQS | Async messaging |
| `ExternalService` | Python mock API | ECS/EKS Pod | 3rd party dependency simulation |
| `RequestGateway` | Python API Gateway | ECS/EKS Pod | Entry point/load balancer |

### Minimal Starting Topology

```
RequestGateway → ApiService (1-2 services)
                    ↓
                 PostgreSQL
                    ↓
                  Redis
```

**Phase 1 (Minimal):**
- 1 Gateway service (Python Flask)
- 1-2 API services (Python Flask/FastAPI)
- 1 PostgreSQL database (RDS or containerized)
- 1 Redis cache (ElastiCache or containerized)

This creates a realistic 4-5 node topology that can exhibit:
- Service failures
- Database bottlenecks
- Cache miss effects
- Dependency propagation

## Implementation Phases

### Phase 1: Foundation Services (Week 1)

#### 1.1 Core Service Framework

Create a shared Python service framework that all services inherit from:

**File Structure:**
```
deployment/
├── shared/
│   ├── __init__.py
│   ├── service_base.py          # Base class for all services
│   ├── telemetry_setup.py       # OpenTelemetry instrumentation
│   ├── health_check.py          # Health endpoint
│   └── common_utils.py
├── services/
│   ├── gateway/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app.py
│   │   └── config.py
│   ├── api_service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app.py
│   │   └── config.py
│   └── external_service/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── app.py
│       └── config.py
├── infrastructure/
│   ├── database/
│   │   ├── init.sql
│   │   └── Dockerfile
│   ├── cache/
│   │   └── redis.conf
│   └── terraform/               # Optional: IaC
│       ├── main.tf
│       ├── ecs.tf
│       └── rds.tf
└── scripts/
    ├── deploy.sh
    ├── collect_telemetry.py
    └── generate_topology.py
```

#### 1.2 Service Base Class

All services should:
- Use OpenTelemetry for instrumentation (same as simulation)
- Expose health endpoints (`/health`)
- Generate structured logs (JSON)
- Export metrics and traces to files (same format as simulation)
- Support configurable dependencies (service URLs, DB connections)

**Key Features:**
- **Metrics**: CPU, memory, request rate, latency, error rate
- **Traces**: Distributed tracing with correlation IDs
- **Logs**: Structured JSON logs with component ID
- **Health**: `/health` endpoint with status

#### 1.3 Telemetry Export

Services export telemetry to **local files** (JSONL format) that match simulation:
- `metrics.jsonl` - Same format as simulation
- `logs.jsonl` - Same format as simulation  
- `traces.jsonl` - Same format as simulation

These files are then collected and aggregated for RCA analysis.

### Phase 2: Deployment Infrastructure (Week 2)

#### 2.1 Deployment Options

**Option A: ECS Fargate (Simplest)**
- No server management
- Easy to scale
- Cost-effective for development
- Use ECS tasks with shared volumes for telemetry collection

**Option B: EKS (Kubernetes)**
- More control
- Better for production
- Pods for each service
- Better matches simulation architecture (pods)

**Option C: EC2 + Docker Compose (Fastest to start)**
- Single EC2 instance
- Docker Compose orchestrates services
- Easiest for initial testing
- Can migrate to ECS/EKS later

**Recommendation: Start with Option C, migrate to Option B (EKS) for production**

#### 2.2 Telemetry Collection Strategy

**Option 1: Sidecar Pattern** (Recommended)
- Each service pod has a sidecar container
- Sidecar collects telemetry from service stdout/files
- Aggregates and exports to shared volume
- Matches simulation's pod-level telemetry

**Option 2: Shared Volume**
- All services write to shared EBS/EFS volume
- Single collector service reads all files
- Aggregates by timestamp
- Simpler but less scalable

**Option 3: CloudWatch + Export**
- Services export to CloudWatch Logs/Metrics
- Periodic script exports to JSONL files
- More AWS-native but requires conversion

### Phase 3: Service Implementation Details

#### 3.1 Gateway Service

```python
# services/gateway/app.py
from shared.service_base import BaseService
from flask import Flask, request, jsonify
import requests

class GatewayService(BaseService):
    def __init__(self):
        super().__init__("gateway", service_type="RequestGateway")
        self.downstream_services = {
            "api_service_1": os.getenv("API_SERVICE_1_URL", "http://api-service-1:5000"),
            "api_service_2": os.getenv("API_SERVICE_2_URL", "http://api-service-2:5000"),
        }
    
    def handle_request(self, service_name, path):
        # Route to downstream service
        # Instrument with OpenTelemetry spans
        # Record metrics (latency, errors)
        pass
```

**Endpoints:**
- `GET /health` - Health check
- `GET /api/*` - Route to services
- `POST /api/*` - Route to services

#### 3.2 API Service

```python
# services/api_service/app.py
from shared.service_base import BaseService
from flask import Flask, request
import psycopg2
import redis

class ApiService(BaseService):
    def __init__(self):
        super().__init__("api_service_1", service_type="Service")
        self.db = self._connect_db()
        self.cache = self._connect_cache()
    
    def handle_request(self, request_type):
        # 1. Check cache
        # 2. Query database
        # 3. Update cache
        # 4. Return response
        # All instrumented with OpenTelemetry
        pass
```

**Endpoints:**
- `GET /health` - Health check
- `GET /data/:id` - Get data (cache → DB)
- `POST /data` - Create data
- `GET /metrics` - Prometheus metrics (optional)

#### 3.3 Database Service

**PostgreSQL Setup:**
- Use official PostgreSQL Docker image
- Initialize with schema from `infrastructure/database/init.sql`
- Expose connection string via environment variables
- Monitor with pg_stat_statements extension

**Or use RDS:**
- Create RDS PostgreSQL instance
- Configure VPC security groups
- Use connection pooling (PgBouncer if needed)

#### 3.4 Cache Service

**Redis Setup:**
- Use official Redis Docker image
- Configure persistence (optional for testing)
- Monitor with Redis INFO command
- Export metrics via Redis exporter or custom script

**Or use ElastiCache:**
- Create ElastiCache Redis cluster
- Configure VPC security groups
- Use Redis cluster mode for scaling

### Phase 4: Telemetry Collection & Format

#### 4.1 Telemetry Collector Script

Create a script that:
1. Reads telemetry files from all services
2. Aggregates by timestamp
3. Converts to simulation format
4. Generates `topology.json` from deployment config
5. Creates episode directory structure

```python
# scripts/collect_telemetry.py
import json
import glob
from pathlib import Path
from datetime import datetime

def collect_episode(
    services_dir: str,
    output_dir: str,
    episode_id: str = "ep_0",
    topology_config: dict = None
):
    """
    Collect telemetry from all services and format for RCA analysis.
    
    Output structure:
    output_dir/
      ep_0/
        metrics.jsonl
        logs.jsonl
        traces.jsonl
        topology.json
        label.json (if fault injected)
    """
    pass
```

#### 4.2 Topology Generation

Generate `topology.json` from deployment configuration:

```python
# scripts/generate_topology.py
def generate_topology_from_deployment(
    services: list,
    connections: dict
) -> dict:
    """
    Generate topology.json from deployed services.
    
    Services list: [{"id": "gateway", "type": "RequestGateway", ...}, ...]
    Connections: {"gateway": ["api_service_1"], "api_service_1": ["db_1", "cache_1"]}
    """
    pass
```

#### 4.3 Metric Format Matching

Ensure metrics match simulation format:

**Simulation format:**
```json
{"name": "container.cpu.utilization", "data": {...}, ...}
```

**Real service should emit:**
```json
{"name": "container.cpu.utilization", "data": {...}, ...}
```

Use OpenTelemetry metrics with custom file exporter that matches simulation format.

### Phase 5: Fault Injection Framework

To test RCA, we need to inject faults (matching simulation scenarios):

#### 5.1 Fault Injection Methods

**1. Service-Level Faults:**
- CPU saturation: `stress-ng --cpu 4` in container
- Memory leak: Allocate memory indefinitely
- Latency spike: Add sleep in request handler
- Error rate increase: Return errors probabilistically

**2. Database Faults:**
- Slow queries: Add artificial delay
- Connection pool exhaustion: Hold connections
- Query timeout: Complex queries

**3. Cache Faults:**
- Eviction storm: Force evictions
- Connection failures: Close connections

**4. Network Faults:**
- Latency injection: Use `tc` (traffic control)
- Packet loss: Use `tc` for packet drop
- Partition: Block service-to-service communication

#### 5.2 Fault Injection API

Add fault injection endpoints to services:

```python
# POST /admin/faults/inject
{
    "fault_type": "cpu_saturation",
    "severity": 0.8,
    "duration_seconds": 300
}

# POST /admin/faults/revert
{
    "fault_id": "fault_123"
}
```

This allows programmatic fault injection matching simulation scenarios.

#### 5.3 Ground Truth Recording

When injecting faults, record ground truth in `label.json`:

```json
{
    "root_cause_node": "api_service_1",
    "fault_type": "cpu_saturation",
    "fault_start_time": 120,
    "fault_duration": 300,
    "severity": 0.8
}
```

### Phase 6: RCA Integration

#### 6.1 Episode Data Structure

After collecting telemetry, structure data like simulation:

```
deployment/outputs/ep_0/
├── metrics.jsonl
├── logs.jsonl
├── traces.jsonl
├── topology.json
├── label.json
└── metadata.json
```

#### 6.2 RCA Analysis

Use existing `analysis2/whitebox_rca.py`:

```python
from analysis2.run_rca_batch import DatasetAdapter
from analysis2.whitebox_rca import WhiteboxRCAEngine

# Load episode data
adapter = DatasetAdapter(Path("deployment/outputs/ep_0"))

# Run RCA (same as simulation)
baseline_pods, current_pods = adapter.get_data_windows()
baseline_services = adapter.aggregate_pods_to_services(baseline_pods)
current_services = adapter.aggregate_pods_to_services(current_pods)

engine = WhiteboxRCAEngine(adapter.topology)
results = engine.analyze_incident(
    baseline_services, current_services,
    metrics_df=adapter.metrics_df,
    fault_start_time=adapter.label.get('fault_start_time'),
    traces_file=Path("deployment/outputs/ep_0/traces.jsonl"),
    baseline_pods=baseline_pods,
    current_pods=current_pods
)
```

**No changes needed to RCA tool!** It expects same data format.

### Phase 7: Scaling Framework

#### 7.1 Service Template

Create a cookiecutter template for new services:

```
cookiecutter service_template/
├── service_name/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py (with BaseService)
│   └── config.py
```

#### 7.2 Service Registry

Maintain a registry of available services:

```yaml
# deployment/services_registry.yaml
services:
  - name: gateway
    type: RequestGateway
    image: gateway:latest
    dependencies: []
  
  - name: user_service
    type: Service
    image: user-service:latest
    dependencies: [postgres, redis]
  
  - name: order_service
    type: Service
    image: order-service:latest
    dependencies: [postgres, redis, payment_service]
  
  - name: payment_service
    type: ExternalService
    image: payment-service:latest
    dependencies: []
```

#### 7.3 Topology Builder

Tool to generate topologies from service registry:

```python
# scripts/build_topology.py
def build_topology(services: list, connections: dict) -> dict:
    """
    Build topology from service registry.
    Supports:
    - Service-to-service (HTTP)
    - Service-to-database (SQL)
    - Service-to-cache (Redis)
    - Service-to-queue (RabbitMQ/SQS)
    - Service-to-external (HTTP)
    """
    pass
```

## Implementation Steps

### Step 1: Create Base Service Framework (2-3 days)

1. Implement `shared/service_base.py` with:
   - OpenTelemetry setup
   - Health endpoints
   - Metric emission
   - Logging setup

2. Test base service locally

### Step 2: Implement Minimal Services (3-4 days)

1. Gateway service (routes to API services)
2. One API service (cache + DB operations)
3. PostgreSQL setup (Docker or RDS)
4. Redis setup (Docker or ElastiCache)

5. Test locally with Docker Compose

### Step 3: Deploy to AWS (2-3 days)

1. Create EC2 instance or ECS cluster
2. Deploy services with Docker
3. Configure networking (security groups, VPC)
4. Test service-to-service communication

### Step 4: Telemetry Collection (2-3 days)

1. Implement telemetry collector script
2. Test metric/log/trace collection
3. Verify format matches simulation
4. Generate topology.json

### Step 5: RCA Integration (1-2 days)

1. Run RCA on collected data
2. Verify RCA works with real data
3. Compare results with simulation

### Step 6: Fault Injection (2-3 days)

1. Implement fault injection endpoints
2. Test fault scenarios
3. Verify ground truth recording

### Step 7: Validation & Scaling (ongoing)

1. Run end-to-end tests
2. Add more services incrementally
3. Document service templates
4. Create deployment automation

## Minimal Base Services

To build most topologies, you need these base service types:

### 1. **Gateway** (Entry Point)
- Routes requests to downstream services
- Load balancing
- Request metrics

### 2. **API Service** (Business Logic)
- Generic API service template
- Configurable dependencies (DB, cache, other services)
- Supports GET/POST/PUT/DELETE operations

### 3. **Database Service** (PostgreSQL)
- Standard SQL operations
- Connection pooling
- Query metrics

### 4. **Cache Service** (Redis)
- GET/SET operations
- TTL support
- Cache hit/miss metrics

### 5. **Queue Service** (RabbitMQ or SQS)
- Publish/subscribe
- Consumer workers
- Queue depth metrics

### 6. **External Service** (Mock 3rd Party)
- Configurable latency
- Configurable error rates
- Simulates external API dependencies

**With these 6 types, you can build:**
- Simple chains: Gateway → Service → DB
- Cached services: Gateway → Service → Cache → DB
- Async processing: Service → Queue → Worker → DB
- Complex topologies: Multiple services with dependencies

## Service Differentiation

Services should be **functionally different** but **structurally similar**:

**User Service:**
- Manages user data
- Uses user_db
- Has user_cache
- Calls notification_service

**Order Service:**
- Manages orders
- Uses order_db
- Has order_cache
- Calls payment_service, notification_service

**Product Service:**
- Manages products
- Uses product_db
- Has product_cache
- Calls inventory_service

**Different data, different dependencies, same structure.**

## Next Steps

1. **Review this plan** - Confirm approach and priorities
2. **Create base service framework** - Start with `shared/service_base.py`
3. **Implement minimal topology** - Gateway + 1 API Service + DB + Cache
4. **Deploy to AWS** - Use EC2 + Docker Compose initially
5. **Test RCA** - Collect telemetry and run RCA analysis
6. **Iterate** - Add services and complexity incrementally

## Questions to Consider

1. **AWS Account Setup**: Do you have an AWS account with appropriate permissions?
2. **Budget**: What's the budget for AWS resources (EC2, RDS, ElastiCache)?
3. **Monitoring**: Do you want CloudWatch integration or file-based telemetry only?
4. **Fault Injection**: Automated or manual fault injection?
5. **Scale**: How many services in Phase 1? Phase 2?

## Dependencies

- Python 3.9+
- Docker & Docker Compose
- AWS CLI configured
- OpenTelemetry Python SDK
- Flask or FastAPI for services
- PostgreSQL client (psycopg2)
- Redis client (redis-py)

