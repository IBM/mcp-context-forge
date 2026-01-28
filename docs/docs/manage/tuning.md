# Gateway Tuning Guide

> This page collects practical levers for squeezing the most performance, reliability, and observability out of **MCP Gateway**-no matter where you run the container (Code Engine, Kubernetes, Docker Compose, Nomad, etc.).
>
> **TL;DR**
>
> 1. Tune the **runtime environment** via `.env` and configure mcpgateway to use PostgreSQL and Redis.
> 2. Adjust **Gunicorn** workers & time-outs in `gunicorn.conf.py`.
> 3. Right-size **CPU/RAM** for the container or spin up more instances (with shared Redis state) and change the database settings (ex: connection limits).
> 4. Benchmark with **hey** (or your favourite load-generator) before & after. See also: [performance testing guide](../testing/performance.md)

---

## 1 - Environment variables (`.env`)

|  Variable        |  Default       |  Why you might change it                                                            |
| ---------------- | -------------- | ----------------------------------------------------------------------------------- |
| `AUTH_REQUIRED`  | `true`         | Disable for internal/behind-VPN deployments to shave a few ms per request.          |
| `JWT_SECRET_KEY` | random         | Longer key ➜ slower HMAC verify; still negligible-leave as is.                      |
| `CACHE_TYPE`     | `database`     | Switch to `redis` or `memory` if your workload is read-heavy and latency-sensitive. |
| `DATABASE_URL`   | SQLite         | Move to managed PostgreSQL + connection pooling for anything beyond dev tests.      |
| `HOST`/`PORT`    | `0.0.0.0:4444` | Expose a different port or bind only to `127.0.0.1` behind a reverse-proxy.         |

### Redis Connection Pool Tuning

When using `CACHE_TYPE=redis`, tune the connection pool for your workload:

| Variable | Default | Tuning Guidance |
| -------- | ------- | --------------- |
| `REDIS_MAX_CONNECTIONS` | `50` | Pool size per worker. Formula: `(concurrent_requests / workers) × 1.5` |
| `REDIS_SOCKET_TIMEOUT` | `2.0` | Lower (1.0s) for high-concurrency; Redis ops typically <100ms |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | `2.0` | Keep low to fail fast on network issues |
| `REDIS_HEALTH_CHECK_INTERVAL` | `30` | Lower (15s) for production to detect stale connections faster |

**High-concurrency production settings:**

```bash
REDIS_MAX_CONNECTIONS=100
REDIS_SOCKET_TIMEOUT=1.0
REDIS_SOCKET_CONNECT_TIMEOUT=1.0
REDIS_HEALTH_CHECK_INTERVAL=15
```

> **Tip**  Any change here requires rebuilding or restarting the container if you pass the file with `--env-file`.

---

## 2 - Gunicorn settings (`gunicorn.conf.py`)

|  Knob                    |  Purpose            |  Rule of thumb                                                    |
| ------------------------ | ------------------- | ----------------------------------------------------------------- |
| `workers`                | Parallel processes  | `2-4 × vCPU` for CPU-bound work; fewer if memory-bound.           |
| `threads`                | Per-process threads | Use only with `sync` worker; keeps memory low for I/O workloads.  |
| `timeout`                | Kill stuck worker   | Set ≥ end-to-end model latency. E.g. 600 s for LLM calls.         |
| `preload_app`            | Load app once       | Saves RAM; safe for pure-Python apps.                             |
| `worker_class`           | Async workers       | `gevent` or `eventlet` for many concurrent requests / websockets. |
| `max_requests(+_jitter)` | Self-healing        | Recycle workers to mitigate memory leaks.                         |

Edit the file **before** building the image, then redeploy.

---

## 2b - Uvicorn Performance Extras

MCP Gateway uses `uvicorn[standard]` which includes high-performance components that are automatically detected and used:

| Package | Purpose | Platform | Improvement |
|---------|---------|----------|-------------|
| `uvloop` | Fast event loop (libuv-based, Cython) | Linux, macOS | 20-40% lower latency |
| `httptools` | Fast HTTP parsing (C extension) | All platforms | 40-60% faster parsing |
| `websockets` | Optimized WebSocket handling | All platforms | Better WS performance |
| `watchfiles` | Fast file watching for `--reload` | All platforms | Faster dev cycle |

### Automatic Detection

When Gunicorn spawns Uvicorn workers, these components are automatically detected:

```bash
# Verify extras are installed
pip list | grep -E "uvloop|httptools|websockets|watchfiles"

# Expected output (Linux/macOS):
# httptools    0.6.x
# uvloop       0.21.x
# websockets   15.x.x
# watchfiles   1.x.x
```

### Platform Notes

- **Linux/macOS**: Full performance benefits (uvloop + httptools)
- **Windows**: httptools provides benefits; uvloop unavailable (graceful fallback to asyncio)

### Performance Impact

Combined improvements from uvloop and httptools:

| Workload | Improvement |
|----------|-------------|
| Simple JSON endpoints | 15-25% faster |
| High-concurrency requests | 20-30% higher throughput |
| WebSocket connections | Lower latency, better handling |
| Development `--reload` | Faster file change detection |

> **Note**: These optimizations are transparent - no code or configuration changes needed.

---

## 2c - Granian (Alternative HTTP Server)

MCP Gateway supports two HTTP servers:
- **Gunicorn + Uvicorn** (default) - Battle-tested, mature, excellent stability
- **Granian** (alternative) - Rust-based, native HTTP/2, lower memory

### Usage

```bash
# Local development
make serve                    # Gunicorn + Uvicorn (default)
make serve-granian            # Granian (alternative)
make serve-granian-http2      # Granian with HTTP/2 + TLS

# Container with Gunicorn (default)
make container-run
make container-run-gunicorn-ssl

# Container with Granian (alternative)
make container-run-granian
make container-run-granian-ssl

# Docker Compose (default uses Gunicorn)
docker compose up
```

### Switching HTTP Servers

The `HTTP_SERVER` environment variable controls which server to use:

```bash
# Docker/Podman - use Gunicorn (default)
docker run mcpgateway/mcpgateway

# Docker/Podman - use Granian
docker run -e HTTP_SERVER=granian mcpgateway/mcpgateway

# Docker Compose - set in environment section
environment:
  - HTTP_SERVER=gunicorn  # default
  # - HTTP_SERVER=granian # alternative
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GRANIAN_WORKERS` | auto (CPU cores, max 16) | Worker processes |
| `GRANIAN_RUNTIME_MODE` | auto (mt if >8 workers) | Runtime mode: mt (multi-threaded), st (single-threaded) |
| `GRANIAN_RUNTIME_THREADS` | 1 | Runtime threads per worker |
| `GRANIAN_BLOCKING_THREADS` | 1 | Blocking threads per worker |
| `GRANIAN_HTTP` | auto | HTTP version: auto, 1, 2 |
| `GRANIAN_LOOP` | uvloop | Event loop: uvloop, asyncio, rloop |
| `GRANIAN_TASK_IMPL` | auto | Task implementation: asyncio (Python 3.12+), rust (older) |
| `GRANIAN_HTTP1_PIPELINE_FLUSH` | true | Aggregate HTTP/1 flushes for pipelined responses |
| `GRANIAN_HTTP1_BUFFER_SIZE` | 524288 | HTTP/1 buffer size (512KB) |
| `GRANIAN_BACKLOG` | 2048 | Connection backlog for high concurrency |
| `GRANIAN_BACKPRESSURE` | 512 | Max concurrent requests per worker |
| `GRANIAN_RESPAWN_FAILED` | true | Auto-restart failed workers |
| `GRANIAN_DEV_MODE` | false | Enable hot reload |
| `DISABLE_ACCESS_LOG` | true | Disable access logging for performance |
| `TEMPLATES_AUTO_RELOAD` | false | Disable Jinja2 template auto-reload for production |

**Performance tuning profiles:**

```bash
# High-throughput (fewer workers, more threads per worker)
GRANIAN_WORKERS=4 GRANIAN_RUNTIME_THREADS=4 make serve

# High-concurrency (more workers, max backpressure)
GRANIAN_WORKERS=16 GRANIAN_BACKPRESSURE=1024 GRANIAN_BACKLOG=4096 make serve

# Memory-constrained (fewer workers)
GRANIAN_WORKERS=2 make serve

# Force HTTP/1 only (avoids HTTP/2 overhead)
GRANIAN_HTTP=1 make serve
```

**Notes:**
- On Python 3.12+, the Rust task implementation is unavailable; asyncio is used automatically
- `uvloop` provides best performance on Linux/macOS
- Increase `GRANIAN_BACKLOG` and `GRANIAN_BACKPRESSURE` for high-concurrency workloads

### Backpressure for Overload Protection

Granian's native backpressure prevents unbounded request queuing during overload. When the server reaches capacity, excess requests receive immediate 503 responses instead of waiting in a queue (which can cause memory exhaustion or cascading timeouts).

**How it works:**

```
Incoming Request
       │
       ▼
┌──────────────────────────────────┐
│  Granian Worker (1 of N)         │
│                                  │
│  current_requests < BACKPRESSURE?│
│      │                           │
│      ├── YES → Process request   │
│      │                           │
│      └── NO  → Immediate 503     │
│               (no queuing)       │
└──────────────────────────────────┘
```

**Capacity calculation:**

```
Total capacity = GRANIAN_WORKERS × GRANIAN_BACKPRESSURE

Example with recommended settings:
  Workers: 16
  Backpressure: 64
  Total: 16 × 64 = 1024 concurrent requests

  Requests 1-1024: Processed normally
  Request 1025+: Immediate 503 Service Unavailable
```

**Recommended production settings:**

```yaml
# docker-compose.yml or Kubernetes
environment:
  - HTTP_SERVER=granian
  - GRANIAN_WORKERS=16
  - GRANIAN_BACKLOG=4096        # OS socket queue for pending connections
  - GRANIAN_BACKPRESSURE=64     # Per-worker limit (16×64=1024 total)
```

**Benefits over unbounded queuing:**

| Behavior | Without Backpressure | With Backpressure |
|----------|---------------------|-------------------|
| Under overload | Requests queue indefinitely | Excess rejected immediately |
| Memory usage | Grows unbounded → OOM | Stays bounded |
| Client experience | Long timeouts, then failure | Fast 503, can retry |
| Health checks | May timeout (queued) | Always respond quickly |
| Recovery | Slow (drain queue) | Instant (no queue) |

### When to Use Granian

| Use Granian when... | Use Gunicorn when... |
|---------------------|----------------------|
| You want native HTTP/2 | Maximum stability needed |
| Optimizing for memory | Familiar with Gunicorn |
| Simplest deployment | Need gevent/eventlet workers |
| Benchmarks show gains | Behind HTTP/2 proxy already |

### Performance Comparison

| Metric | Gunicorn+Uvicorn | Granian |
|--------|------------------|---------|
| Simple JSON | Baseline | +20-50% (varies) |
| Memory/worker | ~80MB | ~40MB |
| HTTP/2 | Via proxy | Native |

> **Note**: Always benchmark with your specific workload before switching servers.

### Real-World Performance (Database-Bound Workload)

Under load testing with 2500 concurrent users against PostgreSQL:

| Metric | Gunicorn | Granian | Winner |
|--------|----------|---------|--------|
| **Memory per replica** | ~2.7 GiB | ~4.0 GiB | Gunicorn (32% less) |
| **CPU per replica** | ~740% | ~680% | Granian (8% less) |
| **Throughput (RPS)** | ~2000 | ~2000 | Tie (DB bottleneck) |
| **Backpressure** | ❌ None | ✅ Native | Granian |
| **Overload behavior** | Queues → OOM/timeout | 503 rejection | Granian |

**Key Finding:** When the database is the bottleneck, both servers achieve similar throughput. The main differences are:

- **Memory:** Gunicorn uses 32% less RAM (fork-based model with copy-on-write)
- **CPU:** Granian uses 8% less CPU (more efficient HTTP parsing in Rust)
- **Stability:** Granian handles overload gracefully (backpressure), Gunicorn queues indefinitely

**Recommendation:**

| Scenario | Choose |
|----------|--------|
| Memory-constrained | Gunicorn |
| Load spike protection | Granian |
| Bursty/unpredictable traffic | Granian |
| Stable traffic patterns | Either |

---

## 3 - Container resources

| vCPU × RAM   | Good for              | Notes                                              |
| ------------ | --------------------- | -------------------------------------------------- |
| `0.5 × 1 GB` | Smoke tests / CI      | Smallest footprint; likely CPU-starved under load. |
| `1 × 4 GB`   | Typical dev / staging | Handles a few hundred RPS with default 8 workers.  |
| `2 × 8 GB`   | Small prod            | Allows \~16-20 workers; good concurrency.          |
| `4 × 16 GB`+ | Heavy prod            | Combine with async workers or autoscaling.         |

> Always test with **your** workload; JSON-RPC payload size and backend model latency change the equation.

To change your database connection settings, see the respective documentation for your selected database or managed service. For example, when using IBM Cloud Databases for PostgreSQL - you can [raise the maximum number of connections](https://cloud.ibm.com/docs/databases-for-postgresql?topic=databases-for-postgresql-managing-connections&locale=en#postgres-connection-limits).

---

## 4 - Performance testing

### 4.1 Tooling: **hey**

Install one of:

```bash
brew install hey            # macOS
sudo apt install hey         # Debian/Ubuntu
# or build from source
go install github.com/rakyll/hey@latest  # $GOPATH/bin must be in PATH
```

### 4.2 Sample load-test script (`tests/hey.sh`)

```bash
#!/usr/bin/env bash
# Run 10 000 requests with 200 concurrent workers.
JWT="$(cat jwt.txt)"   # <- place a valid token here
hey -n 10000 -c 200 \
    -m POST \
    -T application/json \
    -H "Authorization: Bearer ${JWT}" \
    -D tests/hey/payload.json \
    http://localhost:4444/rpc
```

**Payload (`tests/hey/payload.json`)**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "convert_time",
  "params": {
    "source_timezone": "Europe/Berlin",
    "target_timezone": "Europe/Dublin",
    "time": "09:00"
  }
}
```

### 4.3 Reading the output

`hey` prints latency distribution, requests/second, and error counts. Focus on:

* **99th percentile latency** - adjust `timeout` if it clips.
* **Errors** - 5xx under load often mean too few workers or DB connections.
* **Throughput (RPS)** - compare before/after tuning.

### 4.4 Common bottlenecks & fixes

| Symptom                  | Likely cause                        | Mitigation                                                 |
| ------------------------ | ----------------------------------- | ---------------------------------------------------------- |
| High % of 5xx under load | Gunicorn workers exhausted          | Increase `workers`, switch to async workers, raise CPU.    |
| Latency > timeout        | Long model call / external API      | Increase `timeout`, add queueing, review upstream latency. |
| Memory OOM               | Too many workers / large batch size | Lower `workers`, disable `preload_app`, add RAM.           |

---

## 5 - Logging & observability

* Set `loglevel = "debug"` in `gunicorn.conf.py` during tests; revert to `info` in prod.
* Forward `stdout`/`stderr` from the container to your platform's log stack (e.g. `kubectl logs`, `docker logs`).
* Expose `/metrics` via a Prometheus exporter (planned) for request timing & queue depth; track enablement in the project roadmap.

---

## 6 - MCP Session Pool Tuning

The MCP session pool maintains persistent connections to upstream MCP servers, providing **10-20x latency improvement** for repeated tool calls from the same user.

!!! note "Disabled by Default"
    Session pooling is disabled by default for safety. Enable it explicitly after testing in your environment:
    ```bash
    MCP_SESSION_POOL_ENABLED=true
    ```

### When to Enable Pooling

| Enable pooling when... | Avoid or tighten isolation when... |
|------------------------|-----------------------------------|
| MCP servers are stable and latency matters | MCP servers maintain per-session state |
| You can tolerate session reuse within user/tenant scope | You rely on request-scoped headers for security/tracing |
| High-throughput tool invocations | Long-running tools (>30s) need custom timeouts |

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SESSION_POOL_ENABLED` | `false` | Enable/disable session pooling |
| `MCP_SESSION_POOL_MAX_PER_KEY` | `10` | Max sessions per (URL, identity, transport). **Increase to 50-200 for high concurrency.** |
| `MCP_SESSION_POOL_TTL` | `300.0` | Session TTL before forced close (seconds) |
| `MCP_SESSION_POOL_TRANSPORT_TIMEOUT` | `30.0` | Timeout for all HTTP operations (seconds) |
| `MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL` | `60.0` | Idle time before health check (seconds) |
| `MCP_SESSION_POOL_HEALTH_CHECK_METHODS` | `ping,skip` | Ordered list of health check methods (ping, list_tools, list_prompts, list_resources, skip) |
| `MCP_SESSION_POOL_HEALTH_CHECK_TIMEOUT` | `5.0` | Timeout per health check attempt (seconds) |
| `MCP_SESSION_POOL_ACQUIRE_TIMEOUT` | `30.0` | Timeout waiting for session slot |
| `MCP_SESSION_POOL_CREATE_TIMEOUT` | `30.0` | Timeout creating new session |
| `MCP_SESSION_POOL_IDLE_EVICTION` | `600.0` | Evict idle pool keys after (seconds) |
| `MCP_SESSION_POOL_CIRCUIT_BREAKER_THRESHOLD` | `5` | Consecutive failures before circuit opens |
| `MCP_SESSION_POOL_CIRCUIT_BREAKER_RESET` | `60.0` | Circuit reset time (seconds) |

### Recommended Production Settings

```bash
# Baseline settings for authenticated deployments (low-to-moderate traffic)
MCP_SESSION_POOL_ENABLED=true
MCP_SESSION_POOL_MAX_PER_KEY=10
MCP_SESSION_POOL_TTL=300
MCP_SESSION_POOL_TRANSPORT_TIMEOUT=30

# High-concurrency settings (1000+ concurrent users)
MCP_SESSION_POOL_ENABLED=true
MCP_SESSION_POOL_MAX_PER_KEY=200          # 50-200 for high concurrency
MCP_SESSION_POOL_TTL=300
MCP_SESSION_POOL_TRANSPORT_TIMEOUT=30
MCP_SESSION_POOL_ACQUIRE_TIMEOUT=60       # Longer timeout under load

# Ensure identity headers are present
ENABLE_HEADER_PASSTHROUGH=true
DEFAULT_PASSTHROUGH_HEADERS="Authorization,X-Tenant-Id,X-User-Id,X-API-Key"
```

### Session Isolation

Sessions are isolated by a composite key: `(URL, identity_hash, transport_type)`. Identity is derived from authentication headers (`Authorization`, `X-Tenant-ID`, `X-User-ID`, `X-API-Key`, `Cookie`).

**Key security considerations:**

1. **Anonymous Pooling**: When no identity headers are present, identity collapses to `"anonymous"` and all such requests share sessions. This is safe **only if** upstream MCP servers are stateless.

2. **Shared Credentials**: With OAuth Client Credentials or static API keys, all users share the same identity hash. Only safe if the upstream MCP server has no per-user state.

3. **Header Passthrough**: If gateway auth is disabled (`AUTH_REQUIRED=false`), enable header passthrough to preserve user identity:
   ```bash
   ENABLE_HEADER_PASSTHROUGH=true
   DEFAULT_PASSTHROUGH_HEADERS="Authorization,X-Tenant-Id,X-User-Id"
   ```

### Long-Running Tools

The transport timeout applies to **all** HTTP operations, not just connection establishment. For tools that take longer than 30 seconds:

```bash
# Increase for long-running tools
MCP_SESSION_POOL_TRANSPORT_TIMEOUT=120
```

### Health Check Timeout Trade-offs

Pool staleness checks use `MCP_SESSION_POOL_TRANSPORT_TIMEOUT` (default 30s) for session acquisition. When `MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=true`, the explicit RPC call uses `HEALTH_CHECK_TIMEOUT` (default 5s).

**Behavior summary:**

| Check Type | Timeout Used | Default |
|------------|--------------|---------|
| Pool staleness check (idle > interval) | `MCP_SESSION_POOL_TRANSPORT_TIMEOUT` | 30s |
| Explicit health RPC (when enabled) | `HEALTH_CHECK_TIMEOUT` | 5s |
| Session creation | `MCP_SESSION_POOL_CREATE_TIMEOUT` | 30s |

**Trade-off**: The 30s transport timeout allows long-running tools to complete but means unhealthy sessions may take longer to detect. If you need faster failure detection:

```bash
# Stricter health checks (5s timeout for explicit RPC)
MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=true
HEALTH_CHECK_TIMEOUT=5

# Or reduce transport timeout (affects all operations)
MCP_SESSION_POOL_TRANSPORT_TIMEOUT=10
```

### Circuit Breaker Behavior

The circuit breaker is keyed by URL only (not per-identity). After `MCP_SESSION_POOL_CIRCUIT_BREAKER_THRESHOLD` consecutive **session creation failures** for a URL, the circuit opens and all requests fail fast for `MCP_SESSION_POOL_CIRCUIT_BREAKER_RESET` seconds.

**Note**: Only session creation failures (connection refused, SSL errors) trip the circuit. Tool call failures do not affect the circuit breaker.

### Monitoring

Monitor pool performance via the metrics endpoint:

```bash
curl -u admin:changeme http://localhost:4444/admin/mcp-pool/metrics
```

Response includes:
- `total_sessions_created` / `total_sessions_reused`: Pool hit ratio
- `pool_hits` / `pool_misses`: Cache effectiveness
- `active_sessions`: Current utilization
- `circuit_breaker_states`: Per-URL circuit status

### Operational Checklist

Before enabling pooling in production:

- [ ] Confirm upstream MCP servers are stateless for any shared/anonymous access
- [ ] Verify identity headers are present and stable
- [ ] Validate tool call durations vs `MCP_SESSION_POOL_TRANSPORT_TIMEOUT`
- [ ] Ensure tracing headers are not relied upon in pooled sessions

After enabling pooling:

- [ ] Monitor pool metrics at `/admin/mcp-pool/metrics`
- [ ] Watch for increased tool timeouts or unexpected auth failures
- [ ] Verify correlation IDs in upstream logs (note: per-request headers are stripped from pooled sessions)

---

## 7 - Nginx Reverse Proxy Tuning

When deploying MCP Gateway behind nginx (as in the default `docker-compose.yml`), several optimizations can significantly improve performance under load.

### Admin UI Caching

Admin pages use Jinja2 template rendering which is CPU-intensive under high concurrency. The default nginx configuration enables short-TTL caching with multi-tenant isolation:

| Setting | Value | Purpose |
|---------|-------|---------|
| `proxy_cache_valid` | `5s` | Short TTL keeps data fresh while reducing backend load |
| `Cache-Control` | `private` | Prevents CDNs/proxies from caching user-specific content |
| Cache key | Includes auth tokens | Per-user isolation prevents data leakage |

**Performance impact (4000 concurrent users):**

| Metric | Without Caching | With Caching | Improvement |
|--------|-----------------|--------------|-------------|
| `/admin/` response time | 5414ms | 199ms | 96% |
| Throughput | ~2400 RPS | ~4000 RPS | 67% |

### Multi-Tenant Cache Safety

The cache key includes all authentication credentials to ensure user isolation:

```nginx
proxy_cache_key "$scheme$request_method$host$request_uri$is_args$args$http_authorization$cookie_jwt_token$cookie_access_token";
```

This ensures:

- **Bearer token auth** (`$http_authorization`): API clients get isolated caches
- **Primary session cookie** (`$cookie_jwt_token`): Browser users get isolated caches
- **Alternative auth cookie** (`$cookie_access_token`): Fallback auth method also isolated

### Verifying Cache Behavior

Check the `X-Cache-Status` header to verify caching is working:

```bash
curl -I http://localhost:8080/admin/ -b "jwt_token=..." | grep X-Cache
# X-Cache-Status: MISS  (first request)
# X-Cache-Status: HIT   (subsequent requests within 5s)
# X-Cache-Status: STALE (background refresh in progress)
```

### Disabling Admin Caching

If you need real-time admin data or have concerns about caching, modify `infra/nginx/nginx.conf`:

```nginx
location /admin {
    proxy_cache off;
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    # ... rest of config
}
```

---

## 8 - High-Concurrency Production Tuning

This section covers comprehensive tuning for deployments handling **1000+ concurrent users**. These settings have been tested under load with 6500 concurrent users.

### 8.1 Database Connection Pool (SQLAlchemy)

The gateway's internal connection pool manages connections between the application and PgBouncer (or PostgreSQL directly).

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `DB_POOL_CLASS` | `auto` | `queue` | Pool implementation. Use `queue` with PgBouncer, `null` for safest option |
| `DB_POOL_PRE_PING` | `false` | `true` | Validate connections before use (SELECT 1). Prevents stale connection errors |
| `DB_POOL_SIZE` | `5` | `20` | Persistent connections per worker. Formula: `(concurrent_users / workers) × 0.5` |
| `DB_MAX_OVERFLOW` | `10` | `10` | Extra connections allowed during spikes |
| `DB_POOL_TIMEOUT` | `30` | `60` | Seconds to wait for available connection before error |
| `DB_POOL_RECYCLE` | `3600` | `60` | Recycle connections after N seconds. **Must be less than PgBouncer CLIENT_IDLE_TIMEOUT** |

**Example high-concurrency configuration:**

```bash
# With PgBouncer (recommended)
DB_POOL_CLASS=queue
DB_POOL_PRE_PING=true
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=60
DB_POOL_RECYCLE=60    # Half of PgBouncer CLIENT_IDLE_TIMEOUT (120s)
```

**Common errors and solutions:**

| Error | Cause | Solution |
|-------|-------|----------|
| `QueuePool limit reached, connection timed out` | Pool too small for load | Increase `DB_POOL_SIZE` (e.g., 5→20) |
| `idle transaction timeout` | Transactions not committed | Ensure all endpoints call `db.commit()` |
| `connection reset by peer` | PgBouncer recycled stale connection | Set `DB_POOL_RECYCLE` < `CLIENT_IDLE_TIMEOUT` |

---

### 8.2 PgBouncer Connection Pooler

PgBouncer multiplexes many application connections into fewer PostgreSQL connections, dramatically reducing database overhead.

#### Client-Side Settings (from gateway workers)

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `MAX_CLIENT_CONN` | `1000` | `5000-15000` | Max connections from all gateway workers. Formula: `replicas × workers × pool_size × 2` |
| `DEFAULT_POOL_SIZE` | `20` | `600` | Shared connections to PostgreSQL per database |
| `MIN_POOL_SIZE` | `0` | `100` | Pre-warmed connections for instant response |
| `RESERVE_POOL_SIZE` | `0` | `150` | Emergency pool for burst traffic |
| `RESERVE_POOL_TIMEOUT` | `5` | `2` | Seconds before tapping reserve pool |

#### Server-Side Settings (to PostgreSQL)

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `MAX_DB_CONNECTIONS` | `100` | `700` | Max connections to PostgreSQL. **Must be < PostgreSQL max_connections** |
| `MAX_USER_CONNECTIONS` | `100` | `700` | Per-user limit, typically equals `MAX_DB_CONNECTIONS` |
| `SERVER_LIFETIME` | `3600` | `1800-3600` | Recycle server connections after N seconds |
| `SERVER_IDLE_TIMEOUT` | `600` | `600` | Close unused server connections after N seconds |

#### Timeout Settings

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `QUERY_WAIT_TIMEOUT` | `120` | `60` | Max wait for available connection |
| `CLIENT_IDLE_TIMEOUT` | `0` | `120-300` | Close idle client connections. **Gateway DB_POOL_RECYCLE must be less than this** |
| `SERVER_CONNECT_TIMEOUT` | `15` | `5` | Timeout for new PostgreSQL connections |
| `IDLE_TRANSACTION_TIMEOUT` | `0` | `60-300` | Kill transactions idle > N seconds. **Critical for preventing connection starvation** |

#### Transaction Reset Settings

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `SERVER_RESET_QUERY` | `DISCARD ALL` | `DISCARD ALL` | Reset connection state when returned to pool |
| `SERVER_RESET_QUERY_ALWAYS` | `0` | `1` | Always run reset query even after clean transactions |
| `POOL_MODE` | `session` | `transaction` | Connection returned after each transaction (required for web apps) |

**Example PgBouncer configuration (docker-compose.yml):**

```yaml
pgbouncer:
  image: edoburu/pgbouncer:latest
  environment:
    - DATABASE_URL=postgres://postgres:password@postgres:5432/mcp
    - POOL_MODE=transaction
    # Client limits
    - MAX_CLIENT_CONN=5000
    - DEFAULT_POOL_SIZE=600
    - MIN_POOL_SIZE=100
    - RESERVE_POOL_SIZE=150
    # Server limits
    - MAX_DB_CONNECTIONS=700
    - SERVER_LIFETIME=1800
    - SERVER_IDLE_TIMEOUT=600
    # Timeouts
    - QUERY_WAIT_TIMEOUT=60
    - CLIENT_IDLE_TIMEOUT=120
    - IDLE_TRANSACTION_TIMEOUT=60
    # Reset
    - SERVER_RESET_QUERY=DISCARD ALL
    - SERVER_RESET_QUERY_ALWAYS=1
  ulimits:
    nofile:
      soft: 65536
      hard: 65536
```

---

### 8.3 Container File Descriptor Limits (ulimits)

Each network connection requires a file descriptor. Containers default to 1024 soft limit, which is insufficient for high concurrency.

| Container | Recommended `nofile` | Rationale |
|-----------|---------------------|-----------|
| **PgBouncer** | `65536` | `MAX_CLIENT_CONN + MAX_DB_CONNECTIONS + overhead` |
| **PostgreSQL** | `8192` | `max_connections + internal FDs` |
| **Redis** | `65536` | `maxclients + overhead` |
| **Gateway** | `65536` | `HTTP connections + DB connections + MCP sessions` |
| **Nginx** | `65535` | `worker_connections × workers` |

**docker-compose.yml example:**

```yaml
services:
  pgbouncer:
    ulimits:
      nofile:
        soft: 65536
        hard: 65536

  postgres:
    ulimits:
      nofile:
        soft: 8192
        hard: 8192

  redis:
    ulimits:
      nofile:
        soft: 65536
        hard: 65536

  gateway:
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
```

**Verification:**

```bash
# Check container limits
docker exec <container> cat /proc/1/limits | grep "open files"

# Count current open FDs
docker exec <container> ls /proc/1/fd | wc -l
```

**Common error:** `accept() failed: No file descriptors available` - Increase `ulimits.nofile`.

---

### 8.4 Host System Tuning (sysctl)

The Docker host kernel settings affect all containers. These must be set on the host, not in containers.

| Setting | Default | High-Concurrency | Description |
|---------|---------|------------------|-------------|
| `net.core.somaxconn` | `128` | `65535` | Max socket listen backlog |
| `net.core.netdev_max_backlog` | `1000` | `65535` | Max packets queued before processing |
| `net.ipv4.tcp_max_syn_backlog` | `128` | `65535` | Max SYN packets pending connection |
| `net.ipv4.tcp_fin_timeout` | `60` | `15` | Faster TIME_WAIT cleanup |
| `net.ipv4.tcp_tw_reuse` | `0` | `1` | Reuse TIME_WAIT sockets |
| `net.ipv4.ip_local_port_range` | `32768 60999` | `1024 65535` | More ephemeral ports |
| `fs.file-max` | varies | `2097152` | System-wide file descriptor limit |

**Apply temporarily:**

```bash
sudo sysctl -w \
  net.core.somaxconn=65535 \
  net.core.netdev_max_backlog=65535 \
  net.ipv4.tcp_max_syn_backlog=65535 \
  net.ipv4.tcp_fin_timeout=15 \
  net.ipv4.tcp_tw_reuse=1 \
  net.ipv4.ip_local_port_range="1024 65535"
```

**Apply permanently** (`/etc/sysctl.d/99-mcp-loadtest.conf`):

```ini
# High-concurrency TCP tuning for MCP Gateway load testing
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
fs.file-max = 2097152
```

Then apply: `sudo sysctl -p /etc/sysctl.d/99-mcp-loadtest.conf`

---

### 8.5 HTTPX Client Pool (Outbound HTTP)

The gateway uses a shared HTTPX client pool for all outbound requests (federation, health checks, A2A, MCP tool calls).

| Variable | Default | High-Concurrency | Description |
|----------|---------|------------------|-------------|
| `HTTPX_MAX_CONNECTIONS` | `100` | `200` | Total connections in pool |
| `HTTPX_MAX_KEEPALIVE_CONNECTIONS` | `20` | `100` | Persistent keepalive connections |
| `HTTPX_KEEPALIVE_EXPIRY` | `5.0` | `30.0` | Idle connection expiry (seconds) |
| `HTTPX_CONNECT_TIMEOUT` | `5.0` | `5.0` | TCP connection timeout |
| `HTTPX_READ_TIMEOUT` | `30.0` | `120.0` | Response read timeout (increase for slow tools) |
| `HTTPX_POOL_TIMEOUT` | `5.0` | `10.0` | Wait for available connection |

**Example:**

```bash
HTTPX_MAX_CONNECTIONS=200
HTTPX_MAX_KEEPALIVE_CONNECTIONS=100
HTTPX_KEEPALIVE_EXPIRY=30.0
HTTPX_READ_TIMEOUT=120.0
HTTPX_POOL_TIMEOUT=10.0
```

---

### 8.6 Complete High-Concurrency Configuration

Here's a complete configuration for 3000-6500 concurrent users:

```yaml
# docker-compose.yml gateway environment
environment:
  # Database pool (via PgBouncer)
  - DATABASE_URL=postgresql+psycopg://postgres:password@pgbouncer:6432/mcp
  - DB_POOL_CLASS=queue
  - DB_POOL_PRE_PING=true
  - DB_POOL_SIZE=20
  - DB_MAX_OVERFLOW=10
  - DB_POOL_TIMEOUT=60
  - DB_POOL_RECYCLE=60

  # MCP Session Pool
  - MCP_SESSION_POOL_ENABLED=true
  - MCP_SESSION_POOL_MAX_PER_KEY=200
  - MCP_SESSION_POOL_ACQUIRE_TIMEOUT=60

  # HTTPX Client Pool
  - HTTPX_MAX_CONNECTIONS=200
  - HTTPX_MAX_KEEPALIVE_CONNECTIONS=100
  - HTTPX_READ_TIMEOUT=120.0

  # Redis
  - REDIS_MAX_CONNECTIONS=150

  # Performance
  - LOG_LEVEL=ERROR
  - DISABLE_ACCESS_LOG=true
  - AUDIT_TRAIL_ENABLED=false
```

---

## 9 - Security tips while tuning

* Never commit real `JWT_SECRET_KEY`, DB passwords, or tokens-use `.env.example` as a template.
* Prefer platform secrets (K8s Secrets, Code Engine secrets) over baking creds into the image.
* If you enable `gevent`/`eventlet`, pin their versions and run **bandit** or **trivy** scans.

---
