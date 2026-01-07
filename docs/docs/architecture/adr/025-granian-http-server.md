# ADR-0025: Add Granian as Alternative HTTP Server

- *Status:* Accepted
- *Date:* 2025-12-21
- *Deciders:* Core Engineering Team

## Context

MCP Gateway uses Gunicorn with Uvicorn workers as its production HTTP server stack. This provides good performance with the `uvicorn[standard]` extras (ADR-0024) and is battle-tested. However, a Rust-based alternative called Granian offers potential benefits:

- Native HTTP/2 support (without requiring a reverse proxy)
- Native WebSocket support
- Native mTLS support
- Lower memory footprint
- Simpler process model

Granian is a Rust-based HTTP server for Python applications that implements ASGI, RSGI, and WSGI interfaces. It's built on:
- **Hyper**: Rust's HTTP library
- **Tokio**: Async runtime
- **PyO3**: Python bindings

## Decision

We will add **Granian** as an alternative HTTP server option while keeping **Gunicorn + Uvicorn as the default**.

**Key points:**
- Gunicorn + Uvicorn remains the **default** server (stability, maturity)
- Granian is available as an **alternative** for users who need its features
- Both servers are production-ready and fully supported
- Users can switch via the `HTTP_SERVER` environment variable

**Usage:**
```bash
# Using Gunicorn + Uvicorn (default)
make serve

# Using Granian (alternative)
make serve-granian

# Granian with HTTP/2 + TLS
make serve-granian-http2
```

## Granian vs Gunicorn+Uvicorn

| Feature | Gunicorn + Uvicorn | Granian |
|---------|-------------------|---------|
| Language | Python + C (uvloop) | Rust |
| HTTP/2 | Requires reverse proxy | Native |
| WebSocket | Via Uvicorn | Native |
| mTLS | Requires configuration | Native |
| Process Model | Master + Workers | Workers only |
| Hot Reload | Via watchfiles | Built-in |
| Memory | Higher (Python overhead) | Lower |
| Maturity | Very mature | Newer (production-ready) |

### Performance Characteristics

Based on community benchmarks:

| Metric | Gunicorn+Uvicorn | Granian | Notes |
|--------|------------------|---------|-------|
| Simple JSON | Baseline | +20-50% | Varies by workload |
| High concurrency | Good | Better | Less context switching |
| Memory per worker | ~80MB | ~40MB | Rust efficiency |
| Startup time | Slower | Faster | No preload needed |

**Note:** Actual performance varies by workload. Always benchmark with your specific use case.

### Real-World Performance Comparison (Database-Bound Workload)

Profiling under load test with 2500 concurrent users against PostgreSQL backend:

| Metric | Gunicorn+Uvicorn | Granian | Notes |
|--------|------------------|---------|-------|
| **Memory per replica** | ~2.7 GiB | ~4.0 GiB | Gunicorn 32% less |
| **CPU per replica** | ~740% | ~680% | Granian 8% less |
| **Throughput (RPS)** | ~2000 | ~2000 | Same (DB bottleneck) |
| **Backpressure** | ❌ None (queues unbounded) | ✅ Native (rejects excess) | Granian safer under overload |
| **503 under overload** | No (timeouts instead) | Yes (clean rejection) | Granian fails gracefully |

**Key Insight:** When the bottleneck is the database (not HTTP parsing), both servers achieve similar throughput. The difference is in resource usage and overload behavior:

- **Gunicorn** uses less memory but has no admission control—under extreme load it will queue requests indefinitely, potentially causing OOM or cascading timeouts.
- **Granian** uses more memory but provides native backpressure—under extreme load it rejects excess requests with immediate 503, protecting system stability.

**Why Granian Uses More Memory:**
- Multi-threaded Rust runtime (Tokio) overhead
- Larger HTTP buffers (512KB per connection default)
- Backpressure queues holding pending requests
- PyO3 Python-Rust bindings overhead

**Recommendation by Use Case:**

| Scenario | Recommendation |
|----------|----------------|
| Memory-constrained environment | Gunicorn (32% less RAM) |
| Load spike protection needed | Granian (native backpressure) |
| Predictable traffic patterns | Either (similar performance) |
| Unpredictable/bursty traffic | Granian (graceful degradation) |

## Consequences

### Positive

- **Higher throughput potential** - Rust-based server can handle more RPS
- **Native HTTP/2** - No reverse proxy needed for HTTP/2 support
- **Lower memory footprint** - Rust's memory efficiency
- **Simpler deployment** - Single process model, no master/worker complexity
- **Choice** - Users can pick the server that best fits their needs
- **Future-proof** - Rust ecosystem continues to improve

### Negative

- **Newer project** - Less battle-tested than Gunicorn (though production-ready)
- **Binary dependency** - Requires Rust compilation or prebuilt wheels
- **Different tuning** - Different configuration parameters to learn
- **Optional dependency** - Adds ~20MB to container if installed

### Neutral

- **Same application code** - ASGI interface is identical
- **Same configuration** - Environment variables work the same way
- **Coexistence** - Both servers can be installed simultaneously

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GRANIAN_WORKERS` | auto (CPU cores, max 16) | Number of worker processes |
| `GRANIAN_RUNTIME_MODE` | auto (mt if >8 workers, else st) | Runtime mode: mt (multi-threaded), st (single-threaded) |
| `GRANIAN_RUNTIME_THREADS` | 1 | Runtime threads per worker |
| `GRANIAN_BLOCKING_THREADS` | 1 | Blocking threads per worker (must be 1 for ASGI) |
| `GRANIAN_HTTP` | auto | HTTP version: auto, 1, 2 |
| `GRANIAN_LOOP` | uvloop | Event loop: uvloop, asyncio, rloop |
| `GRANIAN_BACKLOG` | 2048 | OS socket backlog for pending connections |
| `GRANIAN_BACKPRESSURE` | 512 | Max concurrent requests per worker before 503 rejection |
| `GRANIAN_HTTP1_BUFFER_SIZE` | 524288 | HTTP/1 buffer size in bytes (512KB) |
| `GRANIAN_RESPAWN_FAILED` | true | Respawn failed workers automatically |
| `GRANIAN_DEV_MODE` | false | Enable hot reload (requires granian[reload]) |
| `GRANIAN_LOG_LEVEL` | info | Log level: debug, info, warning, error |
| `DISABLE_ACCESS_LOG` | true | Disable access logging for performance |

**Backpressure capacity calculation:**

```
Total capacity = GRANIAN_WORKERS × GRANIAN_BACKPRESSURE

Example: 16 workers × 64 backpressure = 1024 concurrent requests
- Requests 1-1024: Processed normally
- Request 1025+: Immediate 503 Service Unavailable (no queuing)
```

For production with high concurrency, use `GRANIAN_BACKPRESSURE=64` with `GRANIAN_WORKERS=16` for 1024 total capacity.

### Docker Compose

```yaml
# docker-compose.yml - set HTTP_SERVER to switch servers
services:
  gateway:
    environment:
      - HTTP_SERVER=granian     # Rust-based with native backpressure
      # - HTTP_SERVER=gunicorn  # Python-based, stable (default)
      # Granian backpressure configuration (16 × 64 = 1024 concurrent)
      - GRANIAN_WORKERS=16
      - GRANIAN_BACKLOG=4096
      - GRANIAN_BACKPRESSURE=64
      # - GRANIAN_WORKERS=8
      # - GRANIAN_HTTP=2        # Enable HTTP/2
```

### Container Targets

```bash
# Run container with Gunicorn (default)
make container-run
make container-run-gunicorn
make container-run-gunicorn-ssl

# Run container with Granian (alternative)
make container-run-granian
make container-run-granian-ssl

# Or pass HTTP_SERVER directly
docker run mcpgateway/mcpgateway                         # Gunicorn (default)
docker run -e HTTP_SERVER=granian mcpgateway/mcpgateway  # Granian
```

## Switching Servers

To switch from Gunicorn to Granian:

1. Install Granian: `pip install "mcpgateway[granian]"`
2. Test locally: `make serve-granian`
3. Benchmark both servers with your workload
4. If Granian performs better, set `HTTP_SERVER=granian` in your deployment

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Added `granian` optional dependency |
| `run-granian.sh` | Startup script with performance optimizations |
| `docker-entrypoint.sh` | Entrypoint that switches between servers |
| `Makefile` | Added `serve`, `container-run-granian`, `container-run-gunicorn` targets |
| `docker-compose.yml` | Added `HTTP_SERVER` environment variable |
| `Containerfile*` | Include both servers, use docker-entrypoint.sh |

## When to Use Each Server

### Use Gunicorn + Uvicorn when:
- You need maximum stability and battle-tested components
- Your team is familiar with Gunicorn configuration
- You're running behind a reverse proxy that handles HTTP/2
- You need gevent/eventlet worker classes

### Use Granian when:
- You want native HTTP/2 without a reverse proxy
- You're optimizing for memory efficiency
- You want the simplest possible deployment
- You're comfortable with newer technology
- Your benchmarks show better performance

## Recommendation

**For most users: Stick with Gunicorn (default)**

Gunicorn + Uvicorn is battle-tested, well-documented, and provides excellent performance for most workloads. The `uvicorn[standard]` extras (ADR-0024) already provide significant optimizations.

**Consider Granian when:**
- You need native HTTP/2 without a reverse proxy
- Memory usage is a primary concern
- Your benchmarks show measurable improvement
- You're comfortable with newer technology

**Note on Python 3.12+:** Granian's Rust task implementation is not available on Python 3.12+, which limits some performance benefits. Both servers use `uvloop` for async I/O, so the main difference is HTTP parsing.

## Status

This decision has been implemented. Both servers are available:
- Gunicorn + Uvicorn: **Default** (`make serve`)
- Granian: **Alternative** (`make serve-granian` or `HTTP_SERVER=granian`)

## References

- GitHub Issue: #1695
- Related ADR: ADR-0024 (uvicorn[standard])
- Granian GitHub: https://github.com/emmett-framework/granian
- Granian Documentation: https://granian.dev/
- Hyper (Rust HTTP): https://hyper.rs/
- Tokio (Rust async): https://tokio.rs/
