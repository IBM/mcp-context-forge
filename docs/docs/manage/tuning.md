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

## 6 - Security tips while tuning

* Never commit real `JWT_SECRET_KEY`, DB passwords, or tokens-use `.env.example` as a template.
* Prefer platform secrets (K8s Secrets, Code Engine secrets) over baking creds into the image.
* If you enable `gevent`/`eventlet`, pin their versions and run **bandit** or **trivy** scans.

---
