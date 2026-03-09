# ContextForge High-Performance Architecture

This diagram showcases the performance-optimized architecture of ContextForge, highlighting Rust-powered components, async patterns, and scaling capabilities.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    KUBERNETES ORCHESTRATION LAYER                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐│
│  │                              Horizontal Pod Autoscaler (HPA)                                        ││
│  │                    ┌──────────────────────────────────────────────────────┐                         ││
│  │                    │  CPU Target: 70%  │  Memory Target: 80%              │                         ││
│  │                    │  Min Replicas: 3  │  Max Replicas: 50                │                         ││
│  │                    └──────────────────────────────────────────────────────┘                         ││
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    │
                                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                        EDGE / PROXY LAYER                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐│
│  │                                    NGINX Caching Proxy                                              ││
│  │  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────┐ ││
│  │  │ Brotli/Gzip/Zstd  │  │  Static Cache 1GB │  │  API Cache 512MB  │  │   Rate Limiting 3000r/s   │ ││
│  │  │   Compression     │  │   30-day TTL      │  │    5-min TTL      │  │   Burst: 3000 requests    │ ││
│  │  │  30-70% savings   │  │   X-Cache-Status  │  │  Schema Cache     │  │   Conn Limit: 3000/IP     │ ││
│  │  └───────────────────┘  └───────────────────┘  └───────────────────┘  └───────────────────────────┘ ││
│  │  ┌───────────────────────────────────────────────────────────────────────────────────────────────┐  ││
│  │  │  worker_processes: auto │ worker_connections: 8192 │ keepalive: 512 │ backlog: 4096           │  ││
│  │  └───────────────────────────────────────────────────────────────────────────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────────────────┐
                    │                               │                               │
                    ▼                               ▼                               ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              GATEWAY APPLICATION LAYER (Replicated Pods)                               │
│                                                                                                        │
│  ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐              │
│  │     Gateway Pod 1        │  │     Gateway Pod 2        │  │     Gateway Pod N        │              │
│  │                          │  │                          │  │                          │              │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │              │
│  │  │  HTTP SERVER LAYER │  │  │  │  HTTP SERVER LAYER │  │  │  │  HTTP SERVER LAYER │  │              │
│  │  │  ╔════════════════╗│  │  │  │  ╔════════════════╗│  │  │  │  ╔════════════════╗│  │              │
│  │  │  ║    GRANIAN     ║│  │  │  │  ║    GRANIAN     ║│  │  │  │  ║    GRANIAN     ║│  │              │
│  │  │  ║  (Rust HTTP)   ║│  │  │  │  ║  (Rust HTTP)   ║│  │  │  │  ║  (Rust HTTP)   ║│  │              │
│  │  │  ║  +20-50% perf  ║│  │  │  │  ║  +20-50% perf  ║│  │  │  │  ║  +20-50% perf  ║│  │              │
│  │  │  ╚════════════════╝│  │  │  │  ╚════════════════╝│  │  │  │  ╚════════════════╝│  │              │
│  │  │  16 workers        │  │  │  │  16 workers        │  │  │  │  16 workers        │  │              │
│  │  │  backlog: 4096     │  │  │  │  backlog: 4096     │  │  │  │  backlog: 4096     │  │              │
│  │  │  backpressure: 64  │  │  │  │  backpressure: 64  │  │  │  │  backpressure: 64  │  │              │
│  │  └────────────────────┘  │  │  └────────────────────┘  │  │  └────────────────────┘  │              │
│  │           │              │  │           │              │  │           │              │              │
│  │           ▼              │  │           ▼              │  │           ▼              │              │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │              │
│  │  │   ASYNC RUNTIME    │  │  │  │   ASYNC RUNTIME    │  │  │  │   ASYNC RUNTIME    │  │              │
│  │  │  ╔════════════════╗│  │  │  │  ╔════════════════╗│  │  │  │  ╔════════════════╗│  │              │
│  │  │  ║    UVLOOP      ║│  │  │  │  ║    UVLOOP      ║│  │  │  │  ║    UVLOOP      ║│  │              │
│  │  │  ║ (Cython/libuv) ║│  │  │  │  ║ (Cython/libuv) ║│  │  │  │  ║ (Cython/libuv) ║│  │              │
│  │  │  ║  2-4x faster   ║│  │  │  │  ║  2-4x faster   ║│  │  │  │  ║  2-4x faster   ║│  │              │
│  │  │  ╚════════════════╝│  │  │  │  ╚════════════════╝│  │  │  │  ╚════════════════╝│  │              │
│  │  │  1000+ concurrent  │  │  │  │  1000+ concurrent  │  │  │  │  1000+ concurrent  │  │              │
│  │  │  requests/worker   │  │  │  │  requests/worker   │  │  │  │  requests/worker   │  │              │
│  │  └────────────────────┘  │  │  └────────────────────┘  │  │  └────────────────────┘  │              │
│  │           │              │  │           │              │  │           │              │              │
│  └───────────┼──────────────┘  └───────────┼──────────────┘  └───────────┼──────────────┘              │
└──────────────┼─────────────────────────────┼─────────────────────────────┼─────────────────────────────┘
               │                             │                             │
               └─────────────────────────────┼─────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    RUST-POWERED COMPONENTS                                              │
│                                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐│
│  │                                      FASTAPI APPLICATION                                            ││
│  │                                                                                                     ││
│  │  ┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐                    ││
│  │  │  ╔═══════════════════╗│  │  ╔═══════════════════╗│  │  ╔═══════════════════╗│                    ││
│  │  │  ║   PYDANTIC V2     ║│  │  ║     ORJSON        ║│  │  ║     HIREDIS       ║│                    ││
│  │  │  ║  (Rust Core)      ║│  │  ║   (Rust JSON)     ║│  │  ║    (C Parser)     ║│                    ││
│  │  │  ╚═══════════════════╝│  │  ╚═══════════════════╝│  │  ╚═══════════════════╝│                    ││
│  │  │  • 5-50x faster       │  │  • 3x faster          │  │  • Up to 83x faster   │                    ││
│  │  │    validation         │  │    serialization      │  │    Redis parsing      │                    ││
│  │  │  • GIL bypass         │  │  • Native types       │  │  • Large response     │                    ││
│  │  │  • 5,463 lines        │  │  • ORJSONResponse     │  │    optimization       │                    ││
│  │  │    of schemas         │  │  • SSE streaming      │  │  • Auto fallback      │                    ││
│  │  └───────────────────────┘  └───────────────────────┘  └───────────────────────┘                    ││
│  │                                                                                                     ││
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────────────┐   ││
│  │  │                              MULTI-LEVEL CACHING (80-95% DB reduction)                       │   ││
│  │  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌─────────────┐ │   ││
│  │  │  │   JWT Cache    │ │  Auth Cache    │ │ Registry Cache │ │  Admin Stats   │ │ GlobalConfig│ │   ││
│  │  │  │  TTL: 30s      │ │  TTL: 120-300s │ │  TTL: 20-300s  │ │   TTL: 30-120s │ │   TTL: 60s  │ │   ││
│  │  │  │  <1ms auth     │ │  0-1 queries   │ │  95%+ hit rate │ │  Dashboard opt │ │  42K→0 qry  │ │   ││
│  │  │  └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘ └─────────────┘ │   ││
│  │  └──────────────────────────────────────────────────────────────────────────────────────────────┘   ││
│  │                                                                                                     ││
│  │  ┌───────────────────────────────────────────────────────────────────────────────────────────────┐  ││
│  │  │                              PERFORMANCE OPTIMIZATIONS                                        │  ││
│  │  │  • Precompiled regex validators       • Lazy f-string logging                                 │  ││
│  │  │  • Cached Jinja templates             • Cached JSONPath parsing                               │  ││
│  │  │  • Cached jq filter compilation       • Cached JSON Schema validators                         │  ││
│  │  │  • has_hooks_for optimization         • Buffered metrics writes                               │  ││
│  │  │  • Bulk UPDATE for token cleanup      • SQL-based metrics aggregation                         │  ││
│  │  └───────────────────────────────────────────────────────────────────────────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────────────────┐
                    │                               │                               │
                    ▼                               ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          DATA LAYER                                                     │
│                                                                                                         │
│  ┌───────────────────────────────────────┐                  ┌─────────────────────────────────────────┐ │
│  │          CONNECTION POOLING           │                  │            DISTRIBUTED CACHE            │ │
│  │                                       │                  │                                         │ │
│  │  ┌────────────────────────────────┐   │                  │  ┌─────────────────────────────────────┐│ │
│  │  │          PGBOUNCER             │   │                  │  │              REDIS                  ││ │
│  │  │     Connection Multiplexer     │   │                  │  │         High-Performance            ││ │
│  │  │  ┌──────────────────────────┐  │   │                  │  │  ┌───────────────────────────────┐  ││ │
│  │  │  │ MAX_CLIENT_CONN: 5000    │  │   │                  │  │  │  ╔═════════════════════════╗  │  ││ │
│  │  │  │ DEFAULT_POOL_SIZE: 450   │  │   │                  │  │  │  ║   HIREDIS C PARSER      ║  │  ││ │
│  │  │  │ MAX_DB_CONNECTIONS: 550  │  │   │                  │  │  │  ║   Up to 83x faster      ║  │  ││ │
│  │  │  │ POOL_MODE: transaction   │  │   │                  │  │  │  ╚═════════════════════════╝  │  ││ │
│  │  │  │ 8x connection reduction  │  │   │                  │  │  │  maxmemory: 1GB               │  ││ │
│  │  │  └──────────────────────────┘  │   │                  │  │  │  maxclients: 10000            │  ││ │
│  │  └────────────────────────────────┘   │                  │  │  │  tcp-backlog: 2048            │  ││ │
│  │                  │                    │                  │  │  │  allkeys-lru eviction         │  ││ │
│  │                  ▼                    │                  │  │  └───────────────────────────────┘  ││ │
│  │  ┌──────────────────────────────────┐ │                  │  │                                     ││ │
│  │  │        POSTGRESQL 18             │ │                  │  │  Session storage: TTL 3600s         ││ │
│  │  │      Production Database         │ │                  │  │  Message cache: TTL 600s            ││ │
│  │  │  ┌───────────────────────────┐   │ │                  │  │  Federation cache                   ││ │
│  │  │  │  ╔═════════════════════╗  │   │ │                  │  │  Leader election                    ││ │
│  │  │  │  ║    PSYCOPG V3       ║  │   │ │                  │  └─────────────────────────────────────┘│ │
│  │  │  │  ║  (Modern Driver)    ║  │   │ │                  └─────────────────────────────────────────┘ │
│  │  │  │  ╚═════════════════════╝  │   │ │                                                              │
│  │  │  │  • Auto-prepared stmts    │   │ │                                                              │
│  │  │  │  • COPY protocol (5-10x)  │   │ │                                                              │
│  │  │  │  • Pipeline mode (2-5x)   │   │ │                                                              │
│  │  │  │  • Native async I/O       │   │ │                                                              │
│  │  │  └───────────────────────────┘   │ │                                                              │
│  │  │  max_connections: 700            │ │                                                              │
│  │  │  shared_buffers: 512MB           │ │                                                              │
│  │  │  effective_cache_size: 1536MB    │ │                                                              │
│  │  │  synchronous_commit: off         │ │                                                              │
│  │  │  idle_in_transaction: 30s        │ │                                                              │
│  │  │  SSD optimized (random_page: 1.1)│ │                                                              │
│  │  └──────────────────────────────────┘ │                                                              │
│  └───────────────────────────────────────┘                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    OBSERVABILITY & MONITORING                                           │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────────┐ │
│  │    Prometheus     │  │     Grafana       │  │       Loki        │  │        Exporters              │ │
│  │  Metrics Store    │  │   Dashboards      │  │   Log Aggregation │  │  PostgreSQL | Redis | Nginx   │ │
│  │  7-day retention  │  │   Visualization   │  │     LogQL         │  │  PgBouncer | cAdvisor         │ │
│  └───────────────────┘  └───────────────────┘  └───────────────────┘  └───────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐│
│  │                              OpenTelemetry Integration                                              ││
│  │   OTEL Traces → OTLP Exporter → Collector │ Service Name: mcp-gateway                               ││
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## MCP Streamable HTTP Request Path

Every MCP request to `/servers/{server_id}/mcp` passes through these layers:

```
Client Request (JSON-RPC over HTTP POST)
    │
    ▼
┌─────────────────────────────────────────────┐
│  NGINX (Edge/Proxy)                         │
│  • least_conn load balancing                │
│  • keepalive 512 per worker                 │
│  • No caching for /mcp (POST requests)      │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  GATEWAY MIDDLEWARE STACK                    │
│  1. SecurityHeaders, CORS                   │
│  2. MCPPathRewrite + Auth                   │
│     • JWT verification (HMAC)               │
│     • Token revocation check (DB/cache)     │
│     • User lookup (DB/cache)                │
│     • Team resolution (DB/cache)            │
│  3. Token scoping (Layer 1 auth)            │
│  4. Request logging                         │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  MCP SDK SessionManager                     │
│  • JSON-RPC envelope parsing                │
│  • Session tracking (stateless by default)  │
│  • Context variable propagation             │
│  • Handler method routing                   │
└─────────────────────────────────────────────┘
    │
    ├── tools/list ─────┐
    ├── tools/call ─────┤
    ├── resources/list ─┤
    ├── prompts/list ───┤
    └── ping ───────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  MCP HANDLER                                │
│  • RBAC permission check (Layer 2 auth)     │
│  • Server/tool lookup (DB query)            │
│  • For tools/call: upstream proxy           │
│    via MCP Session Pool (if enabled)        │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  UPSTREAM MCP SERVER                        │
│  (fast_test_server, fast_time, plugins)     │
│  • Executes tool logic                      │
│  • Returns JSON-RPC result                  │
└─────────────────────────────────────────────┘
```

### Performance Characteristics by Layer

| Layer | Typical Latency | Scaling Bottleneck | Key Tunable |
|-------|----------------|-------------------|-------------|
| nginx | <1ms | Not a bottleneck | `keepalive`, `worker_connections` |
| Middleware + Auth | 5-15ms | Auth DB queries | `AUTH_CACHE_*_TTL`, `AUTH_CACHE_BATCH_QUERIES` |
| MCP SDK SessionManager | 2-5ms | JSON-RPC parsing, context vars | `JSON_RESPONSE_ENABLED` |
| RBAC check | 1-5ms | Permission DB queries | Role cache TTL (5 min internal) |
| tools/list (DB) | 5-10ms | Sequential table scans | `REGISTRY_CACHE_TOOLS_TTL` |
| tools/call (upstream) | 10-200ms | Upstream server + network | `MCP_SESSION_POOL_ENABLED` |

### Feature Flags and Middleware Overhead

Every enabled feature registers middleware, routers, or background tasks that consume resources even when not actively used. ContextForge has ~90 feature flags; each disabled feature removes its middleware and background tasks from the request path.

The most impactful features to disable when not needed are: admin UI, A2A protocol, LLM chat, catalog, observability, audit trail, and database-backed structured logging. See the [disable unused features](../manage/tuning.md#10---disable-unused-features) section in the tuning guide for deployment profiles.

### Key Architectural Insight

The `/rpc` endpoint and the `/servers/{id}/mcp` endpoint serve the same logical operations (tools/list, tools/call) but follow different code paths:

- **`/rpc`**: Uses Redis-backed caching (registry cache, tool lookup cache) for most lookups. Under load, Redis handles the read pressure, keeping PgBouncer/PostgreSQL near idle.
- **`/mcp`**: Routes through the MCP SDK session manager, which executes its own handler functions. These handlers query the database via SQLAlchemy for server resolution, tool lookup, and RBAC checks. The auth cache (Redis-backed, TTL up to 300s) mitigates some of this, but RBAC and server/tool lookups still hit the database.

This means that scaling MCP throughput depends heavily on reducing per-request database queries in the MCP transport handlers.

---

## Component Performance Impact Summary

### Rust-Powered Components (GIL Bypass)

| Component | Technology | Performance Gain | Use Case |
|-----------|------------|------------------|----------|
| **Pydantic v2** | Rust core (`pydantic-core`) | 5-50x faster validation | Request/response schemas (5,463 lines) |
| **orjson** | Rust JSON library | 3x faster serialization | All JSON encoding/decoding |
| **Granian** | Rust HTTP server | +20-50% throughput | HTTP request handling |
| **hiredis** | C-based Redis parser | Up to 83x faster | Large Redis response parsing |
| **uvloop** | Cython/libuv event loop | 2-4x faster async I/O | Async event loop |

### Database Performance

| Optimization | Before | After | Improvement |
|--------------|--------|-------|-------------|
| **psycopg v3** prepared statements | Parsed each query | Auto-prepared | 2-3x faster repeated queries |
| **COPY protocol** | INSERT statements | Binary COPY | 5-10x faster bulk inserts |
| **Pipeline mode** | Sequential queries | Pipelined | 2-5x batch improvements |
| **PgBouncer pooling** | 1600+ connections | 200 connections | 8x connection reduction |

### Caching Performance

| Cache Layer | Hit Rate | TTL (Configurable) | DB Query Reduction |
|-------------|----------|-------------------|---------------------|
| **JWT Cache** | >80% | 30s | Per-request HMAC verification cached |
| **Auth Cache** | >90% | 120-300s (max) | 3-4 → 0-1 queries/request (user, team, role, revocation) |
| **Registry Cache** | 95%+ | 20-300s | 50-200 → 0-1 queries (tools, servers, prompts, resources) |
| **GlobalConfig Cache** | 99%+ | 60s | 42K+ queries eliminated (passthrough header config) |
| **MCP Session Pool** | Varies | 300s pool TTL | 10-20x latency improvement for repeated upstream calls |

### Compression & Bandwidth

| Algorithm | Compression Ratio | Best For |
|-----------|-------------------|----------|
| **Brotli** | 15-25% smaller than Gzip | Production, CDNs |
| **Zstd** | Very good, fastest | High-throughput APIs |
| **Gzip** | Good, universal | Legacy compatibility |

### Scaling Capacity

Capacity varies by workload type. MCP Streamable HTTP requests are more resource-intensive per request than REST API calls due to additional middleware, auth, and upstream proxy overhead.

| Configuration | REST API (`/rpc`) | MCP Streamable HTTP (`/mcp`) |
|---------------|-------------------|------------------------------|
| Single pod (16-24 workers) | ~1,600 RPS | ~250-400 RPS |
| 3 pods (default) | ~4,800 RPS | ~750-800 RPS |
| 10 pods (HPA scaled) | ~16,000 RPS | ~2,500-3,000 RPS |

MCP throughput is lower because each request includes auth/RBAC database queries that the `/rpc` endpoint caches in Redis. With session pool enabled (`MCP_SESSION_POOL_ENABLED=true`), upstream MCP server latency is amortized across pooled connections, providing ~10% throughput improvement.

## Key Performance Features by Issue

| Issue # | Feature | Impact |
|---------|---------|--------|
| #1695 | Granian HTTP server migration | +20-50% throughput |
| #1696, #1692 | orjson throughout codebase | 3x JSON performance |
| #1699 | uvicorn[standard] with uvloop/httptools | 15-30% faster async |
| #1702 | hiredis Redis parser | Up to 83x Redis parsing |
| #1740 | psycopg v3 migration | Auto-prepared, COPY, pipeline |
| #1750, #1753 | PgBouncer connection pooling | 8x connection reduction |
| #1715 | GlobalConfig in-memory cache | 42K queries eliminated |
| #1773 | get_user_teams() caching | Reduced idle-in-transaction |
| #1809-1814 | Schema/template/filter caching | Compilation overhead removed |
| #1816, #1819, #1830 | Precompiled regex patterns | CPU reduction in hot paths |
| #1828, #1837 | SSE/logging micro-optimizations | Reduced allocation overhead |
| #1844 | Monitoring profile | Production observability |
| #2025 | Startup resilience (exponential backoff) | Prevents crash-loop CPU storms |

## Startup Resilience

The gateway implements **exponential backoff with jitter** for database and Redis connection retries at startup. This prevents CPU-intensive crash-respawn loops when dependencies are temporarily unavailable.

### Problem Solved

Without exponential backoff, a dependency outage would cause:
```
Worker starts → Connection fails after 3 attempts (6s) → Worker crashes
    ↓
Granian respawns worker immediately → Worker starts → Connection fails → Crashes
    ↓
Tight crash-respawn loop → 500%+ CPU consumption → System destabilization
```

### Solution: Exponential Backoff with Jitter

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    EXPONENTIAL BACKOFF RETRY PATTERN                        │
│                                                                             │
│   Attempt 1    Attempt 2    Attempt 3    Attempt 4    Attempt 5+            │
│      │            │            │            │            │                  │
│      ▼            ▼            ▼            ▼            ▼                  │
│   ┌─────┐     ┌─────┐     ┌─────┐     ┌──────┐     ┌──────┐                │
│   │ 2s  │     │ 4s  │     │ 8s  │     │ 16s  │     │ 30s  │ (capped)       │
│   └─────┘     └─────┘     └─────┘     └──────┘     └──────┘                │
│      │            │            │            │            │                  │
│      └────────────┴────────────┴────────────┴────────────┘                  │
│                              │                                              │
│                              ▼                                              │
│                    ±25% Random Jitter                                       │
│                 (prevents thundering herd)                                  │
│                                                                             │
│   Formula: sleep = min(base × 2^(attempt-1), 30s) × (1 ± 0.25 × random)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Performance Impact

| Metric | Before | After |
|--------|--------|-------|
| **Retry attempts** | 3 (~6 seconds) | 30 (~5 minutes) |
| **CPU during outage** | ~500% (crash loop) | ~0% (sleeping) |
| **Recovery pattern** | Thundering herd | Staggered with jitter |
| **System stability** | Cascading failures | Graceful degradation |

### Configuration

```bash
# Database Startup Resilience
DB_MAX_RETRIES=30              # Max attempts before worker exits (default: 30)
DB_RETRY_INTERVAL_MS=2000      # Base interval in ms (doubles each attempt)

# Redis Startup Resilience
REDIS_MAX_RETRIES=30           # Max attempts before worker exits (default: 30)
REDIS_RETRY_INTERVAL_MS=2000   # Base interval in ms (doubles each attempt)
```

### Retry Progression Example

With default settings (2s base interval):

| Attempt | Base Delay | With Jitter (±25%) | Cumulative Time |
|---------|------------|---------------------|-----------------|
| 1 | 2s | 1.5s - 2.5s | ~2s |
| 2 | 4s | 3s - 5s | ~6s |
| 3 | 8s | 6s - 10s | ~14s |
| 4 | 16s | 12s - 20s | ~30s |
| 5+ | 30s (cap) | 22.5s - 37.5s | ~60s+ |

After 30 retries: approximately **5 minutes** total wait time before the worker gives up, providing ample time for dependencies to recover during maintenance windows or transient outages.

## Future: Python 3.14 Free-Threading (GIL Removal)

```
Current Architecture (Python 3.11-3.13):
┌─────────────────────────────────────────────────────────────┐
│  16 Worker Processes × 1 GIL each = True Parallelism        │
│  Memory: 256MB base + (16 × 200MB) = ~3.5GB                 │
└─────────────────────────────────────────────────────────────┘

Future Architecture (Python 3.14+):
┌─────────────────────────────────────────────────────────────┐
│  2 Worker Processes × 32 Threads = True Parallelism         │
│  Memory: ~1GB (shared memory, reduced IPC overhead)         │
│  Performance: Near-linear scaling with CPU cores            │
└─────────────────────────────────────────────────────────────┘
```

## See Also

- [Gateway Tuning Guide](../manage/tuning.md) - Environment variables, MCP transport settings, session pool, connection pool tuning
- [Performance Profiling Guide](../development/profiling.md) - py-spy, memray, PostgreSQL profiling, MCP bottleneck triage
- [Database Performance Guide](../development/db-performance.md) - N+1 detection, query logging, DB vs transport bottleneck triage

## Quick Reference Commands

```bash
# Start full performance stack
docker-compose up -d

# Access via caching proxy (production)
curl http://localhost:8080/health

# Start with monitoring
docker-compose --profile monitoring up -d

# View cache hit rates
curl -I http://localhost:8080/tools | grep X-Cache-Status

# Run load test
hey -n 10000 -c 200 -H "Authorization: Bearer $TOKEN" http://localhost:8080/

# Check HPA status (Kubernetes)
kubectl get hpa -n mcp-gateway
```
