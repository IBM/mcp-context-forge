# Scaling MCP Gateway

> Comprehensive guide to scaling MCP Gateway from development to production, covering vertical scaling, horizontal scaling, connection pooling, performance tuning, and Kubernetes deployment strategies.

## Overview

MCP Gateway is designed to scale from single-container development environments to distributed multi-node production deployments. This guide covers:

- **Vertical Scaling**: Optimizing single-instance performance with Gunicorn workers
- **Horizontal Scaling**: Multi-container deployments with shared state
- **Database Optimization**: PostgreSQL connection pooling and settings
- **Cache Architecture**: Redis for distributed caching
- **Performance Tuning**: Configuration and benchmarking
- **Kubernetes Deployment**: HPA, resource limits, and best practices

---

## Table of Contents

1. [Understanding the GIL and Worker Architecture](#1-understanding-the-gil-and-worker-architecture)
2. [Vertical Scaling with Gunicorn](#2-vertical-scaling-with-gunicorn)
3. [Future: Python 3.14 and PostgreSQL 18](#3-future-python-314-and-postgresql-18)
4. [Horizontal Scaling with Kubernetes](#4-horizontal-scaling-with-kubernetes)
5. [Database Connection Pooling](#5-database-connection-pooling)
6. [Redis for Distributed Caching](#6-redis-for-distributed-caching)
7. [Performance Tuning](#7-performance-tuning)
8. [Benchmarking and Load Testing](#8-benchmarking-and-load-testing)
9. [Health Checks and Readiness](#9-health-checks-and-readiness)
10. [Stateless Architecture and Long-Running Connections](#10-stateless-architecture-and-long-running-connections)
11. [Kubernetes Production Deployment](#11-kubernetes-production-deployment)
12. [Monitoring and Observability](#12-monitoring-and-observability)

---

## 1. Understanding the GIL and Worker Architecture

### The Python Global Interpreter Lock (GIL)

Python's Global Interpreter Lock (GIL) prevents multiple native threads from executing Python bytecode simultaneously. This means:

- **Single worker** = Single CPU core usage (even on multi-core systems)
- **I/O-bound workloads** (API calls, database queries) benefit from async/await
- **CPU-bound workloads** (JSON parsing, encryption) require multiple processes

### Pydantic v2: Rust-Powered Performance

MCP Gateway leverages **Pydantic v2.11+** for all request/response validation and schema definitions. Unlike pure Python libraries, Pydantic v2 includes a **Rust-based core** (`pydantic-core`) that significantly improves performance:

**Performance benefits:**

- **5-50x faster validation** compared to Pydantic v1
- **JSON parsing** in Rust (bypasses GIL for serialization/deserialization)
- **Schema validation** runs in compiled Rust code
- **Reduced CPU overhead** for request processing

**Impact on scaling:**

- 5,463 lines of Pydantic schemas (`mcpgateway/schemas.py`)
- Every API request validated through Rust-optimized code
- Lower CPU usage per request = higher throughput per worker
- Rust components release the GIL during execution

This means that even within a single worker process, Pydantic's Rust core can run concurrently with Python code for validation-heavy workloads.

### MCP Gateway's Solution: Gunicorn with Multiple Workers

MCP Gateway uses **Gunicorn with UvicornWorker** to spawn multiple worker processes:

```python
# gunicorn.config.py
workers = 8                    # Multiple processes bypass the GIL
worker_class = "uvicorn.workers.UvicornWorker"  # Async support
timeout = 600                  # 10-minute timeout for long-running operations
preload_app = True            # Load app once, then fork (memory efficient)
```

**Key benefits:**

- Each worker is a separate process with its own GIL
- 8 workers = ability to use 8 CPU cores
- UvicornWorker enables async I/O within each worker
- Preloading reduces memory footprint (shared code segments)

The trade-off is that you are running multiple Python interpreter instances, and each consumes additional memory.

This also requires having shared state (e.g. Redis or a Database).
---

## 2. Vertical Scaling with Gunicorn

### Worker Count Calculation

**Formula**: `workers = (2 × CPU_cores) + 1`

**Examples:**

| CPU Cores | Recommended Workers | Use Case |
|-----------|---------------------|----------|
| 1 | 2-3 | Development/testing |
| 2 | 4-5 | Small production |
| 4 | 8-9 | Medium production |
| 8 | 16-17 | Large production |

### Configuration Methods

#### Environment Variables

```bash
# Automatic detection based on CPU cores
export GUNICORN_WORKERS=auto

# Manual override
export GUNICORN_WORKERS=16
export GUNICORN_TIMEOUT=600
export GUNICORN_MAX_REQUESTS=100000
export GUNICORN_MAX_REQUESTS_JITTER=100
export GUNICORN_PRELOAD_APP=true
```

#### Kubernetes ConfigMap

```yaml
# charts/mcp-stack/values.yaml
mcpContextForge:
  config:
    GUNICORN_WORKERS: "16"               # Number of worker processes
    GUNICORN_TIMEOUT: "600"              # Worker timeout (seconds)
    GUNICORN_MAX_REQUESTS: "100000"      # Requests before worker restart
    GUNICORN_MAX_REQUESTS_JITTER: "100"  # Prevents thundering herd
    GUNICORN_PRELOAD_APP: "true"         # Memory optimization
```

### Resource Allocation

**CPU**: Allocate 1 CPU core per 2 workers (allows for I/O wait)

**Memory**:

- Base: 256MB
- Per worker: 128-256MB (depending on workload)
- Formula: `memory = 256 + (workers × 200)` MB

**Example for 16 workers:**

- CPU: `8-10 cores` (allows headroom)
- Memory: `3.5-4 GB` (256 + 16×200 = 3.5GB)

```yaml
# Kubernetes resource limits
resources:
  limits:
    cpu: 10000m        # 10 cores
    memory: 4Gi
  requests:
    cpu: 8000m         # 8 cores
    memory: 3584Mi     # 3.5GB
```

---

## 3. Future: Python 3.14 and PostgreSQL 18

### Python 3.14 (Free-Threaded Mode)

**Status**: Beta (as of July 2025) - [PEP 703](https://peps.python.org/pep-0703/)

Python 3.14 introduces **optional free-threading** (GIL removal), a groundbreaking change that enables true parallel multi-threading:

```bash
# Enable free-threading mode
python3.14 -X gil=0 -m gunicorn ...

# Or use PYTHON_GIL environment variable
PYTHON_GIL=0 python3.14 -m gunicorn ...
```

**Performance characteristics:**

| Workload Type | Expected Impact |
|---------------|----------------|
| Single-threaded | **3-15% slower** (overhead from thread-safety mechanisms) |
| Multi-threaded (I/O-bound) | **Minimal impact** (already benefits from async/await) |
| Multi-threaded (CPU-bound) | **Near-linear scaling** with CPU cores |
| Multi-process (current) | **No change** (already bypasses GIL) |

**Benefits when available:**

- **True parallel threads**: Multiple threads execute Python code simultaneously
- **Lower memory overhead**: Threads share memory (vs. separate processes)
- **Faster inter-thread communication**: Shared memory, no IPC overhead
- **Better resource efficiency**: One interpreter instance instead of multiple processes

**Trade-offs:**

- **Single-threaded penalty**: 3-15% slower due to fine-grained locking
- **Library compatibility**: Some C extensions need updates (most popular libraries already compatible)
- **Different scaling model**: Move from `workers=16` to `workers=2 --threads=32`

**Migration strategy:**

1. **Now (Python 3.11-3.13)**: Continue using multi-process Gunicorn
   ```python
   workers = 16                    # Multiple processes
   worker_class = "uvicorn.workers.UvicornWorker"
   ```

2. **Python 3.14 beta**: Test in staging environment
   ```bash
   # Build free-threaded Python
   ./configure --enable-experimental-jit --with-pydebug
   make

   # Test with free-threading
   PYTHON_GIL=0 python3.14 -m pytest tests/
   ```

3. **Python 3.14 stable**: Evaluate hybrid approach
   ```python
   workers = 4                     # Fewer processes
   threads = 8                     # More threads per process
   worker_class = "uvicorn.workers.UvicornWorker"
   ```

4. **Post-migration**: Thread-based scaling
   ```python
   workers = 2                     # Minimal processes
   threads = 32                    # Scale with threads
   preload_app = True              # Single app load
   ```

**Current recommendation**:

- **Production**: Use Python 3.11-3.13 with multi-process Gunicorn (proven, stable)
- **Testing**: Experiment with Python 3.14 beta in non-production environments
- **Monitoring**: Watch for library compatibility announcements

**Why MCP Gateway is well-positioned for free-threading:**

MCP Gateway's architecture already benefits from components that will perform even better with Python 3.14:

1. **Pydantic v2 Rust core**: Already bypasses GIL for validation - will work seamlessly with free-threading
2. **FastAPI/Uvicorn**: Built for async I/O - natural fit for thread-based concurrency
3. **SQLAlchemy async**: Database operations already non-blocking
4. **Stateless design**: No shared mutable state between requests

**Resources:**

- [Python 3.14 Free-Threading Guide](https://www.pythoncheatsheet.org/blog/python-3-14-breaking-free-from-gil)
- [PEP 703: Making the GIL Optional](https://peps.python.org/pep-0703/)
- [Python 3.14 Release Schedule](https://peps.python.org/pep-0745/)
- [Pydantic v2 Performance](https://docs.pydantic.dev/latest/blog/pydantic-v2/)

### PostgreSQL 18 (Async I/O)

**Status**: Development (expected 2025)

PostgreSQL 18 introduces native async I/O:

- **Improved connection handling**: Better async query performance
- **Reduced latency**: Non-blocking I/O operations
- **Better scalability**: Efficient connection multiplexing

**Current recommendation**: PostgreSQL 16+ (stable async support via asyncpg)

```bash
# Production-ready now
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/mcp
```

---

## 4. Horizontal Scaling with Kubernetes

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Load Balancer                          │
│                    (Kubernetes Service)                     │
└────────────┬────────────────────────────────┬───────────────┘
             │                                │
    ┌────────▼─────────┐            ┌────────▼─────────┐
    │  Nginx Cache 1   │            │  Nginx Cache 2   │
    │  (proxy layer)   │            │  (proxy layer)   │
    └────────┬─────────┘            └────────┬─────────┘
             │                                │
    ┌────────▼─────────┐            ┌────────▼─────────┐
    │  Gateway Pod 1   │            │  Gateway Pod 2   │
    │  (8 workers)     │            │  (8 workers)     │
    └────────┬─────────┘            └────────┬─────────┘
             │                                │
             └────────────┬───────────────────┘
                          │
          ┌───────────────▼───────────────────────┐
          │                                       │
    ┌─────▼──────┐                    ┌──────────▼─────┐
    │ PostgreSQL │                    │     Redis      │
    │  (shared)  │                    │   (shared)     │
    └────────────┘                    └────────────────┘
```

### Shared State Requirements

For multi-pod deployments:

1. **Shared PostgreSQL**: All data (servers, tools, users, teams)
2. **Shared Redis**: Distributed caching and session management
3. **Stateless pods**: No local state, can be killed/restarted anytime

### Kubernetes Deployment

#### Helm Chart Configuration

```yaml
# charts/mcp-stack/values.yaml
mcpContextForge:
  replicaCount: 3                   # Start with 3 pods

  # Horizontal Pod Autoscaler
  hpa:
    enabled: true
    minReplicas: 3                  # Never scale below 3
    maxReplicas: 20                 # Scale up to 20 pods
    targetCPUUtilizationPercentage: 70    # Scale at 70% CPU
    targetMemoryUtilizationPercentage: 80 # Scale at 80% memory

  # Pod resources
  resources:
    limits:
      cpu: 2000m                    # 2 cores per pod
      memory: 4Gi
    requests:
      cpu: 1000m                    # 1 core per pod
      memory: 2Gi

  # Environment configuration
  config:
    GUNICORN_WORKERS: "8"           # 8 workers per pod
    CACHE_TYPE: redis               # Shared cache
    DB_POOL_SIZE: "50"              # Per-pod pool size

# Shared PostgreSQL
postgres:
  enabled: true
  resources:
    limits:
      cpu: 4000m                    # 4 cores
      memory: 8Gi
    requests:
      cpu: 2000m
      memory: 4Gi

  # Important: Set max_connections
  # Formula: (num_pods × DB_POOL_SIZE × 1.2) + 20
  # Example: (20 pods × 50 pool × 1.2) + 20 = 1220
  config:
    max_connections: 1500           # Adjust based on scale

# Shared Redis
redis:
  enabled: true
  resources:
    limits:
      cpu: 2000m
      memory: 4Gi
    requests:
      cpu: 1000m
      memory: 2Gi
```

#### Deploy with Helm

```bash
# Install/upgrade with custom values
helm upgrade --install mcp-stack ./charts/mcp-stack \
  --namespace mcp-gateway \
  --create-namespace \
  --values production-values.yaml

# Verify HPA
kubectl get hpa -n mcp-gateway
```

### Horizontal Scaling Calculation

**Total capacity** = `pods × workers × requests_per_second`

**Example:**

- 10 pods × 8 workers × 100 RPS = **8,000 RPS**

**Database connections needed:**

- 10 pods × 50 pool size = **500 connections**
- Add 20% overhead = **600 connections**
- Set `max_connections=1000` (buffer for maintenance)

---

## 5. Database Connection Pooling

### Connection Pool Architecture

SQLAlchemy manages a connection pool per process:

```
Pod 1 (8 workers) → 8 connection pools → PostgreSQL
Pod 2 (8 workers) → 8 connection pools → PostgreSQL
Pod N (8 workers) → 8 connection pools → PostgreSQL
```

### Pool Configuration

#### Environment Variables

```bash
# Connection pool settings
DB_POOL_SIZE=50              # Persistent connections per worker
DB_MAX_OVERFLOW=10           # Additional connections allowed
DB_POOL_TIMEOUT=60           # Wait time before timeout (seconds)
DB_POOL_RECYCLE=3600         # Recycle connections after 1 hour
DB_MAX_RETRIES=5             # Retry attempts on failure
DB_RETRY_INTERVAL_MS=2000    # Retry interval
```

#### Configuration in Code

```python
# mcpgateway/config.py
@property
def database_settings(self) -> dict:
    return {
        "pool_size": self.db_pool_size,          # 50
        "max_overflow": self.db_max_overflow,    # 10
        "pool_timeout": self.db_pool_timeout,    # 60s
        "pool_recycle": self.db_pool_recycle,    # 3600s
    }
```

### PostgreSQL Configuration

#### Calculate max_connections

```bash
# Formula
max_connections = (num_pods × num_workers × pool_size × 1.2) + buffer

# Example: 10 pods, 8 workers, 50 pool size
max_connections = (10 × 8 × 50 × 1.2) + 200 = 5000 connections
```

#### PostgreSQL Configuration File

```ini
# postgresql.conf
max_connections = 5000
shared_buffers = 16GB              # 25% of RAM
effective_cache_size = 48GB        # 75% of RAM
work_mem = 16MB                    # Per operation
maintenance_work_mem = 2GB
```

#### Managed Services

**IBM Cloud Databases for PostgreSQL:**
```bash
# Increase max_connections via CLI
ibmcloud cdb deployment-configuration postgres \
  --configuration max_connections=5000
```

**AWS RDS:**
```bash
# Via parameter group
max_connections = {DBInstanceClassMemory/9531392}
```

**Google Cloud SQL:**
```bash
# Auto-scales based on instance size
# 4 vCPU = 400 connections
# 8 vCPU = 800 connections
```

### Connection Pool Monitoring

```python
# Health endpoint checks pool status
@app.get("/health")
async def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

```bash
# Check PostgreSQL connections
kubectl exec -it postgres-pod -- psql -U admin -d postgresdb \
  -c "SELECT count(*) FROM pg_stat_activity;"
```

---

## 6. Redis for Distributed Caching

### Architecture

Redis provides shared state across all Gateway pods:

- **Session storage**: User sessions (TTL: 3600s)
- **Message cache**: Ephemeral data (TTL: 600s)
- **Federation cache**: Gateway peer discovery

### Configuration

#### Enable Redis Caching

```bash
# .env or Kubernetes ConfigMap
CACHE_TYPE=redis
REDIS_URL=redis://redis-service:6379/0
CACHE_PREFIX=mcpgw:
SESSION_TTL=3600
MESSAGE_TTL=600
REDIS_MAX_RETRIES=3
REDIS_RETRY_INTERVAL_MS=2000
```

#### Kubernetes Deployment

```yaml
# charts/mcp-stack/values.yaml
redis:
  enabled: true

  resources:
    limits:
      cpu: 2000m
      memory: 4Gi
    requests:
      cpu: 1000m
      memory: 2Gi

  # Enable persistence
  persistence:
    enabled: true
    size: 10Gi
```

### Redis Sizing

**Memory calculation:**

- Sessions: `concurrent_users × 50KB`
- Messages: `messages_per_minute × 100KB × (TTL/60)`

**Example:**

- 10,000 users × 50KB = 500MB
- 1,000 msg/min × 100KB × 10min = 1GB
- **Total: 1.5GB + 50% overhead = 2.5GB**

### High Availability

**Redis Sentinel** (3+ nodes):
```yaml
redis:
  sentinel:
    enabled: true
    quorum: 2

  replicas: 3  # 1 primary + 2 replicas
```

**Redis Cluster** (6+ nodes):
```bash
REDIS_URL=redis://redis-cluster:6379/0?cluster=true
```

---

## 7. Performance Tuning

### Application Architecture Performance

MCP Gateway's technology stack is optimized for high performance:

**Rust-Powered Components:**

- **Pydantic v2** (5-50x faster validation via Rust core)
- **Uvicorn** (ASGI server with Rust-based httptools)

**Async-First Design:**

- **FastAPI** (async request handling)
- **SQLAlchemy 2.0** (async database operations)
- **asyncio** event loop per worker

**Performance characteristics:**

- Request validation: **< 1ms** (Pydantic v2 Rust core)
- JSON serialization: **3-5x faster** than pure Python
- Database queries: Non-blocking async I/O
- Concurrent requests per worker: **1000+** (async event loop)

### System-Level Optimization

#### Kernel Parameters

```bash
# /etc/sysctl.conf
net.core.somaxconn=4096
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.ip_local_port_range=1024 65535
net.ipv4.tcp_tw_reuse=1
fs.file-max=2097152

# Apply changes
sysctl -p
```

#### File Descriptors

```bash
# /etc/security/limits.conf
* soft nofile 1048576
* hard nofile 1048576

# Verify
ulimit -n
```

### Gunicorn Tuning

#### Optimal Settings

```python
# gunicorn.config.py
workers = (CPU_cores × 2) + 1
timeout = 600                    # Long enough for LLM calls
max_requests = 100000            # Prevent memory leaks
max_requests_jitter = 100        # Randomize restart
preload_app = True              # Reduce memory
reuse_port = True               # Load balance across workers
```

#### Worker Class Selection

**UvicornWorker** (default - best for async):
```python
worker_class = "uvicorn.workers.UvicornWorker"
```

**Gevent** (alternative for I/O-heavy):
```bash
pip install gunicorn[gevent]
worker_class = "gevent"
worker_connections = 1000
```

### Application Tuning

```bash
# Resource limits
TOOL_TIMEOUT=60
TOOL_CONCURRENT_LIMIT=10
RESOURCE_CACHE_SIZE=1000
RESOURCE_CACHE_TTL=3600

# Retry configuration
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY=1.0
RETRY_MAX_DELAY=60

# Health check intervals
HEALTH_CHECK_INTERVAL=60
HEALTH_CHECK_TIMEOUT=10
UNHEALTHY_THRESHOLD=3
```

### Nginx Caching Proxy (CDN-like Performance)

**Overview**: Deploy an nginx reverse proxy with intelligent caching to dramatically reduce backend load and improve response times.

The MCP Gateway includes a production-ready nginx caching proxy configuration (`nginx/`) with three dedicated cache zones:

1. **Static Assets Cache** (1GB, 30-day TTL): CSS, JS, images, fonts
2. **API Response Cache** (512MB, 5-minute TTL): Read-only endpoints
3. **Schema Cache** (256MB, 24-hour TTL): OpenAPI specs, docs

**Performance Benefits**:

- **Static assets**: 80-95% faster (20-50ms → 1-5ms)
- **API endpoints**: 60-80% faster with cache hits
- **Backend load**: 60-80% reduction in requests
- **Cache hit rates**: 40-99% depending on endpoint type
- **Database pressure**: 40-70% fewer queries

**Docker Compose Setup**:

```bash
# Start with nginx caching proxy
docker-compose up -d nginx

# Access via caching proxy
curl http://localhost:8080/health  # Cached
curl http://localhost:4444/health  # Direct (bypass cache)

# Verify caching
curl -I http://localhost:8080/openapi.json | grep X-Cache-Status
# X-Cache-Status: MISS (first request)
# X-Cache-Status: HIT  (subsequent requests)
```

**Kubernetes Deployment**:

Add nginx sidecar to gateway pods:

```yaml
# production-values.yaml
mcpContextForge:
  # Enable nginx caching sidecar
  nginx:
    enabled: true
    cacheSize: 2Gi              # Total cache size
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
      requests:
        cpu: 250m
        memory: 256Mi

  # Gateway configuration remains the same
  replicaCount: 5
  resources:
    limits:
      cpu: 4000m
      memory: 8Gi
```

**Cache Configuration**:

```bash
# Nginx cache zones are pre-configured in nginx/nginx.conf
# Adjust TTLs by editing nginx.conf:

# Static assets: 30 days (aggressive caching)
proxy_cache_valid 200 30d;

# API responses: 5 minutes (balance freshness/performance)
proxy_cache_valid 200 5m;

# OpenAPI schema: 24 hours (rarely changes)
proxy_cache_valid 200 24h;
```

**Cache Bypass Rules**:

Nginx automatically bypasses cache for:

- POST, PUT, PATCH, DELETE requests
- WebSocket connections (`/servers/*/ws`)
- Server-Sent Events (`/servers/*/sse`)
- JSON-RPC endpoint (`/`)

**Monitoring**:

```bash
# Check cache status (via X-Cache-Status header)
curl -I http://localhost:8080/tools | grep X-Cache-Status

# View cache size
docker-compose exec nginx du -sh /var/cache/nginx/*

# Analyze cache hit rate
docker-compose exec nginx cat /var/log/nginx/access.log | \
  grep -oP 'cache_status=\K\w+' | sort | uniq -c
```

**When to Use**:

- ✅ High traffic (>1000 req/sec)
- ✅ Read-heavy workloads
- ✅ Static asset delivery
- ✅ Mobile/remote clients (reduces bandwidth)
- ❌ Write-heavy workloads (limited benefit)
- ❌ Real-time updates required (<1 min staleness)

**Documentation**: See `nginx/README.md` for detailed configuration.

---

### Response Compression

**Bandwidth Optimization**: Reduce data transfer by 30-70% with automatic response compression.

MCP Gateway includes built-in response compression middleware that automatically compresses JSON, HTML, CSS, and JavaScript responses:

```bash
# Enable compression (default: true)
COMPRESSION_ENABLED=true

# Minimum response size to compress (bytes)
# Responses smaller than this won't be compressed
COMPRESSION_MINIMUM_SIZE=500

# Compression quality levels
COMPRESSION_GZIP_LEVEL=6          # GZip: 1-9 (6=balanced)
COMPRESSION_BROTLI_QUALITY=4      # Brotli: 0-11 (4=balanced)
COMPRESSION_ZSTD_LEVEL=3          # Zstd: 1-22 (3=fast)
```

**Algorithm Priority**: Brotli (best) > Zstd (fast) > GZip (universal)

**Performance Impact**:

- **Bandwidth reduction**: 30-70% for JSON/HTML responses
- **CPU overhead**: <5% (Brotli level 4, GZip level 6)
- **Latency**: Minimal (<10ms for typical responses)
- **Scalability**: Increases effective throughput per pod

**Tuning for Scale**:

```bash
# High-traffic production (optimize for speed)
COMPRESSION_GZIP_LEVEL=4          # Faster compression
COMPRESSION_BROTLI_QUALITY=3      # Lower quality, faster
COMPRESSION_ZSTD_LEVEL=1          # Fastest

# Bandwidth-constrained (optimize for size)
COMPRESSION_GZIP_LEVEL=9          # Best compression
COMPRESSION_BROTLI_QUALITY=11     # Maximum quality
COMPRESSION_ZSTD_LEVEL=9          # Balanced slow

# Development (disable compression)
COMPRESSION_ENABLED=false         # No compression overhead
```

**Benefits at Scale**:

- **Lower bandwidth costs**: 30-70% reduction in egress traffic
- **Faster response times**: Smaller payloads transfer faster
- **Higher throughput**: More requests per second with same bandwidth
- **Better cache hit rates**: Smaller cached responses
- **Mobile-friendly**: Critical for mobile clients on slow networks

**Kubernetes Configuration**:

```yaml
# production-values.yaml
mcpContextForge:
  config:
    COMPRESSION_ENABLED: "true"
    COMPRESSION_MINIMUM_SIZE: "500"
    COMPRESSION_GZIP_LEVEL: "6"
    COMPRESSION_BROTLI_QUALITY: "4"
    COMPRESSION_ZSTD_LEVEL: "3"
```

**Monitoring Compression**:

```bash
# Check compression in action
curl -H "Accept-Encoding: br" https://gateway.example.com/openapi.json -v \
  | grep -i "content-encoding"
# Should show: content-encoding: br

# Measure compression ratio
UNCOMPRESSED=$(curl -s https://gateway.example.com/openapi.json | wc -c)
COMPRESSED=$(curl -H "Accept-Encoding: br" -s https://gateway.example.com/openapi.json | wc -c)
echo "Compression ratio: $((100 - COMPRESSED * 100 / UNCOMPRESSED))%"
```

---

## 8. Benchmarking and Load Testing

### Tools

**hey** - HTTP load generator
```bash
# Install
brew install hey           # macOS
sudo apt install hey       # Ubuntu

# Or from source
go install github.com/rakyll/hey@latest
```

**k6** - Modern load testing
```bash
brew install k6            # macOS
```

### Baseline Test

#### Prepare Environment

```bash
# Get JWT token
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 0 --secret my-test-key)

# Create test payload
cat > payload.json <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
EOF
```

#### Run Load Test

```bash
#!/bin/bash
# test-load.sh

# Test parameters
REQUESTS=10000
CONCURRENCY=200
URL="http://localhost:4444/"

# Run test
hey -n $REQUESTS -c $CONCURRENCY \
    -m POST \
    -T application/json \
    -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
    -D payload.json \
    $URL
```

### Interpret Results

```
Summary:
  Total:        5.2341 secs
  Slowest:      0.5234 secs
  Fastest:      0.0123 secs
  Average:      0.1045 secs
  Requests/sec: 1910.5623      ← Target metric

Status code distribution:
  [200] 10000 responses

Response time histogram:
  0.012 [1]     |
  0.050 [2341]  |■■■■■■■■■■■
  0.100 [4523]  |■■■■■■■■■■■■■■■■■■■■■■
  0.150 [2234]  |■■■■■■■■■■■
  0.200 [901]   |■■■■
  0.250 [0]     |
```

**Key metrics:**

- **Requests/sec**: Throughput (target: >1000 RPS per pod)
- **P99 latency**: 99th percentile (target: <500ms)
- **Error rate**: 5xx responses (target: <0.1%)

### Kubernetes Load Test

```bash
# Deploy test pod
kubectl run load-test --image=williamyeh/hey:latest \
  --rm -it --restart=Never -- \
  -n 100000 -c 500 \
  -H "Authorization: Bearer $TOKEN" \
  http://mcp-gateway-service/
```

### Advanced: k6 Script

```javascript
// load-test.k6.js
import http from 'k6/http';
import { check } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 100 },   // Ramp up
    { duration: '5m', target: 100 },   // Sustained
    { duration: '2m', target: 500 },   // Spike
    { duration: '5m', target: 500 },   // High load
    { duration: '2m', target: 0 },     // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(99)<500'],  // 99% < 500ms
    http_req_failed: ['rate<0.01'],    // <1% errors
  },
};

export default function () {
  const payload = JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/list',
    params: {},
  });

  const res = http.post('http://localhost:4444/', payload, {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${__ENV.TOKEN}`,
    },
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });
}
```

```bash
# Run k6 test
TOKEN=$MCPGATEWAY_BEARER_TOKEN k6 run load-test.k6.js
```

---

## 9. Health Checks and Readiness

### Health Check Endpoints

MCP Gateway provides two health endpoints:

#### Liveness Probe: `/health`

**Purpose**: Is the application alive?

```python
@app.get("/health")
async def healthcheck(db: Session = Depends(get_db)):
    """Check database connectivity"""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

**Response:**
```json
{
  "status": "healthy"
}
```

#### Readiness Probe: `/ready`

**Purpose**: Is the application ready to receive traffic?

```python
@app.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """Check if ready to serve traffic"""
    try:
        await asyncio.to_thread(db.execute, text("SELECT 1"))
        return JSONResponse({"status": "ready"}, status_code=200)
    except Exception as e:
        return JSONResponse(
            {"status": "not ready", "error": str(e)},
            status_code=503
        )
```

### Kubernetes Probe Configuration

```yaml
# charts/mcp-stack/templates/deployment-mcpgateway.yaml
containers:

  - name: mcp-context-forge

    # Startup probe (initial readiness)
    startupProbe:
      exec:
        command:

          - python3
          - /app/mcpgateway/utils/db_isready.py
          - --max-tries=1
          - --timeout=2
      initialDelaySeconds: 10
      periodSeconds: 5
      failureThreshold: 60        # 5 minutes max

    # Readiness probe (traffic routing)
    readinessProbe:
      httpGet:
        path: /ready
        port: 4444
      initialDelaySeconds: 15
      periodSeconds: 10
      timeoutSeconds: 2
      successThreshold: 1
      failureThreshold: 3

    # Liveness probe (restart if unhealthy)
    livenessProbe:
      httpGet:
        path: /health
        port: 4444
      initialDelaySeconds: 10
      periodSeconds: 15
      timeoutSeconds: 2
      successThreshold: 1
      failureThreshold: 3
```

### Probe Tuning Guidelines

**Startup Probe:**

- Use for slow initialization (database migrations, model loading)
- `failureThreshold × periodSeconds` = max startup time
- Example: 60 × 5s = 5 minutes

**Readiness Probe:**

- Aggressive: Remove pod from load balancer quickly
- `failureThreshold` = 3 (fail fast)
- `periodSeconds` = 10 (frequent checks)

**Liveness Probe:**

- Conservative: Avoid unnecessary restarts
- `failureThreshold` = 5 (tolerate transient issues)
- `periodSeconds` = 15 (less frequent)

### Monitoring Health

```bash
# Check pod health
kubectl get pods -n mcp-gateway

# Detailed status
kubectl describe pod <pod-name> -n mcp-gateway

# Check readiness
kubectl get pods -n mcp-gateway \
  -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}'

# Test health endpoint
kubectl exec -it <pod-name> -n mcp-gateway -- \
  curl http://localhost:4444/health

# View probe failures
kubectl get events -n mcp-gateway \
  --field-selector involvedObject.name=<pod-name>
```

---

## 10. Stateless Architecture and Long-Running Connections

### Stateless Design Principles

MCP Gateway is designed to be **stateless**, enabling horizontal scaling:

1. **No local session storage**: All sessions in Redis
2. **No in-memory caching** (in production): Use Redis
3. **Database-backed state**: All data in PostgreSQL
4. **Shared configuration**: Environment variables via ConfigMap

### Session Management

#### Stateful Sessions (Not Recommended for Scale)

```bash
USE_STATEFUL_SESSIONS=true  # Event store in database
```

**Limitations:**

- Sessions tied to specific pods
- Requires sticky sessions (session affinity)
- Doesn't scale horizontally

#### Stateless Sessions (Recommended)

```bash
USE_STATEFUL_SESSIONS=false
JSON_RESPONSE_ENABLED=true
CACHE_TYPE=redis
```

**Benefits:**

- Any pod can handle any request
- True horizontal scaling
- Automatic failover

### Long-Running Connections

MCP Gateway supports long-running connections for streaming:

#### Server-Sent Events (SSE)

```python
# Endpoint: /servers/{id}/sse
@app.get("/servers/{server_id}/sse")
async def sse_endpoint(server_id: int):
    """Stream events to client"""
    # Connection can last minutes/hours
```

#### WebSocket

```python
# Endpoint: /servers/{id}/ws
@app.websocket("/servers/{server_id}/ws")
async def websocket_endpoint(server_id: int):
    """Bidirectional streaming"""
```

### Load Balancer Configuration

**Kubernetes Service** (default):
```yaml
# Distributes connections across pods
apiVersion: v1
kind: Service
metadata:
  name: mcp-gateway-service
spec:
  type: ClusterIP
  sessionAffinity: None        # No sticky sessions
  ports:

    - port: 80
      targetPort: 4444
```

**NGINX Ingress** (for WebSocket):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/websocket-services: "mcp-gateway-service"
spec:
  rules:

    - host: gateway.example.com
      http:
        paths:

          - path: /
            pathType: Prefix
            backend:
              service:
                name: mcp-gateway-service
                port:
                  number: 80
```

### Connection Lifecycle

```
Client → Load Balancer → Pod A (SSE stream)
                ↓
            (Pod A dies)
                ↓
Client ← Load Balancer → Pod B (reconnect)
```

**Best practices:**

1. Client implements reconnection logic
2. Server sets `SSE_KEEPALIVE_INTERVAL=30` (keepalive events)
3. Load balancer timeout > keepalive interval

---

## 11. Kubernetes Production Deployment

### Reference Architecture

```yaml
# production-values.yaml
mcpContextForge:
  # --- Scaling ---
  replicaCount: 5

  hpa:
    enabled: true
    minReplicas: 5
    maxReplicas: 50
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80

  # --- Resources ---
  resources:
    limits:
      cpu: 4000m          # 4 cores per pod
      memory: 8Gi
    requests:
      cpu: 2000m          # 2 cores per pod
      memory: 4Gi

  # --- Configuration ---
  config:
    # Gunicorn
    GUNICORN_WORKERS: "16"
    GUNICORN_TIMEOUT: "600"
    GUNICORN_MAX_REQUESTS: "100000"
    GUNICORN_PRELOAD_APP: "true"

    # Database
    DB_POOL_SIZE: "50"
    DB_MAX_OVERFLOW: "10"
    DB_POOL_TIMEOUT: "60"
    DB_POOL_RECYCLE: "3600"

    # Cache
    CACHE_TYPE: redis
    CACHE_PREFIX: mcpgw:
    SESSION_TTL: "3600"
    MESSAGE_TTL: "600"

    # Performance
    TOOL_CONCURRENT_LIMIT: "20"
    RESOURCE_CACHE_SIZE: "2000"

  # --- Health Checks ---
  probes:
    startup:
      type: exec
      command: ["python3", "/app/mcpgateway/utils/db_isready.py"]
      periodSeconds: 5
      failureThreshold: 60

    readiness:
      type: http
      path: /ready
      port: 4444
      periodSeconds: 10
      failureThreshold: 3

    liveness:
      type: http
      path: /health
      port: 4444
      periodSeconds: 15
      failureThreshold: 5

# --- PostgreSQL ---
postgres:
  enabled: true

  resources:
    limits:
      cpu: 8000m          # 8 cores
      memory: 32Gi
    requests:
      cpu: 4000m
      memory: 16Gi

  persistence:
    enabled: true
    size: 100Gi
    storageClassName: fast-ssd

  # Connection limits
  # max_connections = (50 pods × 16 workers × 50 pool × 1.2) + 200
  config:
    max_connections: 50000
    shared_buffers: 8GB
    effective_cache_size: 24GB
    work_mem: 32MB

# --- Redis ---
redis:
  enabled: true

  resources:
    limits:
      cpu: 4000m
      memory: 16Gi
    requests:
      cpu: 2000m
      memory: 8Gi

  persistence:
    enabled: true
    size: 50Gi
```

### Deployment Steps

```bash
# 1. Create namespace
kubectl create namespace mcp-gateway

# 2. Create secrets
kubectl create secret generic mcp-secrets \
  -n mcp-gateway \
  --from-literal=JWT_SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=AUTH_ENCRYPTION_SECRET=$(openssl rand -hex 32) \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -base64 32)

# 3. Install with Helm
helm upgrade --install mcp-stack ./charts/mcp-stack \
  -n mcp-gateway \
  -f production-values.yaml \
  --wait \
  --timeout 10m

# 4. Verify deployment
kubectl get pods -n mcp-gateway
kubectl get hpa -n mcp-gateway
kubectl get svc -n mcp-gateway

# 5. Run migration job
kubectl get jobs -n mcp-gateway

# 6. Test scaling
kubectl top pods -n mcp-gateway
```

### Pod Disruption Budget

```yaml
# pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: mcp-gateway-pdb
  namespace: mcp-gateway
spec:
  minAvailable: 3         # Keep 3 pods always running
  selector:
    matchLabels:
      app: mcp-gateway
```

### Network Policies

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-gateway-policy
  namespace: mcp-gateway
spec:
  podSelector:
    matchLabels:
      app: mcp-gateway
  policyTypes:

    - Ingress
    - Egress
  ingress:

    - from:
        - podSelector:
            matchLabels:
              app: ingress-nginx
      ports:

        - protocol: TCP
          port: 4444
  egress:

    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:

        - protocol: TCP
          port: 5432

    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:

        - protocol: TCP
          port: 6379
```

---

## 12. Monitoring and Observability

### OpenTelemetry Integration

MCP Gateway includes built-in OpenTelemetry support:

```bash
# Enable observability
OTEL_ENABLE_OBSERVABILITY=true
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317
OTEL_SERVICE_NAME=mcp-gateway
```

### Prometheus Metrics

Deploy Prometheus stack:

```bash
# Add Prometheus Helm repo
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts

# Install kube-prometheus-stack
helm install prometheus prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --create-namespace
```

### Key Metrics to Monitor

**Application Metrics:**

- Request rate: `rate(http_requests_total[1m])`
- Latency: `histogram_quantile(0.99, http_request_duration_seconds)`
- Error rate: `rate(http_requests_total{status=~"5.."}[1m])`

**System Metrics:**

- CPU usage: `container_cpu_usage_seconds_total`
- Memory usage: `container_memory_working_set_bytes`
- Network I/O: `container_network_receive_bytes_total`

**Database Metrics:**

- Connection pool usage: `db_pool_size` / `db_pool_connections_active`
- Query latency: `db_query_duration_seconds`
- Deadlocks: `pg_stat_database_deadlocks`

**HPA Metrics:**
```bash
kubectl get hpa -n mcp-gateway -w
```

### Grafana Dashboards

Import dashboards:

1. **Kubernetes Cluster Monitoring** (ID: 7249)
2. **PostgreSQL** (ID: 9628)
3. **Redis** (ID: 11835)
4. **NGINX Ingress** (ID: 9614)

### Alerting Rules

```yaml
# prometheus-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: mcp-gateway-alerts
  namespace: monitoring
spec:
  groups:

    - name: mcp-gateway
      interval: 30s
      rules:

        - alert: HighErrorRate
          expr: |
            rate(http_requests_total{status=~"5..", namespace="mcp-gateway"}[5m]) > 0.05
          for: 5m
          annotations:
            summary: "High error rate detected"

        - alert: HighLatency
          expr: |
            histogram_quantile(0.99,
              rate(http_request_duration_seconds_bucket[5m])) > 1
          for: 5m
          annotations:
            summary: "P99 latency exceeds 1s"

        - alert: DatabaseConnectionPoolExhausted
          expr: |
            db_pool_connections_active / db_pool_size > 0.9
          for: 2m
          annotations:
            summary: "Database connection pool >90% utilized"
```

---

## Summary and Checklist

### Performance Technology Stack

MCP Gateway is built on a high-performance foundation:

✅ **Pydantic v2.11+** - Rust-powered validation (5-50x faster than v1)
✅ **FastAPI** - Modern async framework with OpenAPI support
✅ **Uvicorn** - ASGI server with Rust-based HTTP parsing
✅ **SQLAlchemy 2.0** - Async database operations
✅ **Python 3.11+** - Current stable with excellent performance
🔮 **Python 3.14** - Future free-threading support (beta)

### Scaling Checklist

- [ ] **Vertical Scaling**
  - [ ] Configure Gunicorn workers: `(2 × CPU) + 1`
  - [ ] Allocate CPU: 1 core per 2 workers
  - [ ] Allocate memory: 256MB + (workers × 200MB)

- [ ] **Horizontal Scaling**
  - [ ] Deploy to Kubernetes with HPA enabled
  - [ ] Set `minReplicas` ≥ 3 for high availability
  - [ ] Configure shared PostgreSQL and Redis

- [ ] **Database Optimization**
  - [ ] Calculate `max_connections`: `(pods × workers × pool) × 1.2`
  - [ ] Set `DB_POOL_SIZE` per worker (recommended: 50)
  - [ ] Configure `DB_POOL_RECYCLE=3600` to prevent stale connections

- [ ] **Caching**
  - [ ] Enable Redis: `CACHE_TYPE=redis`
  - [ ] Set `REDIS_URL` to shared Redis instance
  - [ ] Configure TTLs: `SESSION_TTL=3600`, `MESSAGE_TTL=600`

- [ ] **Performance**
  - [ ] Tune Gunicorn: `GUNICORN_PRELOAD_APP=true`
  - [ ] Set timeouts: `GUNICORN_TIMEOUT=600`
  - [ ] Configure retries: `RETRY_MAX_ATTEMPTS=3`

- [ ] **Health Checks**
  - [ ] Configure `/health` liveness probe
  - [ ] Configure `/ready` readiness probe
  - [ ] Set appropriate thresholds and timeouts

- [ ] **Monitoring**
  - [ ] Enable OpenTelemetry: `OTEL_ENABLE_OBSERVABILITY=true`
  - [ ] Deploy Prometheus and Grafana
  - [ ] Configure alerts for errors, latency, and resources

- [ ] **Load Testing**
  - [ ] Benchmark with `hey` or `k6`
  - [ ] Target: >1000 RPS per pod, P99 <500ms
  - [ ] Test failover scenarios

### Reference Documentation

- [Gunicorn Configuration](../deployment/local.md)
- [Kubernetes Deployment](../deployment/kubernetes.md)
- [Helm Charts](../deployment/helm.md)
- [Performance Testing](../testing/performance.md)
- [Observability](observability.md)
- [Configuration Guide](configuration.md)
- [Database Tuning](tuning.md)

---

## Additional Resources

### External Links

- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Kubernetes HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [PostgreSQL Connection Pooling](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- [Redis Cluster](https://redis.io/docs/reference/cluster-spec/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)

### Community

- [GitHub Discussions](https://github.com/ibm/mcp-context-forge/discussions)
- [Issue Tracker](https://github.com/ibm/mcp-context-forge/issues)

---

*Last updated: 2025-10-02*
