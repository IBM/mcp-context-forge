# ADR-032: MCP Session Pool for Connection Reuse

- *Status:* **Superseded by the UpstreamSessionRegistry (issue #4205)**
- *Date:* 2025-01-05
- *Superseded:* 2026-04
- *Deciders:* Platform Team

> **Note — superseded.** The identity-keyed pool this ADR describes caused
> cross-downstream-session state leakage against stateful upstream MCP
> servers (see issue #4205). It was replaced by
> `mcpgateway.services.upstream_session_registry.UpstreamSessionRegistry`,
> which binds one upstream session per `(downstream_session_id, gateway_id)`
> and preserves connection reuse within a single downstream session.
>
> The affinity machinery this ADR's tooling shared (Redis-backed
> downstream-session → worker mapping, heartbeat, Lua CAS reclaim,
> cross-worker session-owner forwarding, RPC listener) now lives in
> `mcpgateway.services.session_affinity` (see ADR-038).
>
> The rest of this ADR is retained as historical context for the design
> trade-offs the registry replaces.

## Introduction: Understanding Connection Reuse

### The Connection Overhead Problem

When a client makes an HTTP request, several steps must occur before any application data is exchanged:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    Traditional HTTP Request Flow                            │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Client                                                          Server    │
│    │                                                               │       │
│    │─────────── TCP SYN ─────────────────────────────────────────►│ ①     │
│    │◄────────── TCP SYN-ACK ─────────────────────────────────────│       │
│    │─────────── TCP ACK ─────────────────────────────────────────►│       │
│    │                                                               │       │
│    │─────────── TLS ClientHello ─────────────────────────────────►│ ②     │
│    │◄────────── TLS ServerHello + Certificate ───────────────────│       │
│    │─────────── TLS Key Exchange ────────────────────────────────►│       │
│    │◄────────── TLS Finished ────────────────────────────────────│       │
│    │                                                               │       │
│    │═══════════ HTTP Request ═══════════════════════════════════►│ ③     │
│    │◄══════════ HTTP Response ═══════════════════════════════════│       │
│    │                                                               │       │
│    │─────────── TCP FIN ─────────────────────────────────────────►│ ④     │
│    │                                                               │       │
│                                                                            │
│  ① TCP Handshake:  ~1-3ms (local) to ~50-150ms (cross-region)             │
│  ② TLS Handshake:  ~5-15ms (additional round trips + crypto)              │
│  ③ HTTP Exchange:  ~1-5ms (actual request/response)                       │
│  ④ Connection Close                                                        │
│                                                                            │
│  Total overhead per request: 10-170ms (mostly handshakes!)                │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### HTTP Persistent Connections (Keep-Alive)

[HTTP/1.1 persistent connections](https://en.wikipedia.org/wiki/HTTP_persistent_connection) solve this by reusing TCP connections:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    HTTP Keep-Alive Flow                                     │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Client                                                          Server    │
│    │                                                               │       │
│    │─────────── TCP + TLS Handshakes ────────────────────────────►│ Once  │
│    │                                                               │       │
│    │═══════════ HTTP Request 1 ═════════════════════════════════►│       │
│    │◄══════════ HTTP Response 1 ════════════════════════════════│       │
│    │                                                               │       │
│    │═══════════ HTTP Request 2 ═════════════════════════════════►│ Reuse │
│    │◄══════════ HTTP Response 2 ════════════════════════════════│       │
│    │                                                               │       │
│    │═══════════ HTTP Request 3 ═════════════════════════════════►│ Reuse │
│    │◄══════════ HTTP Response 3 ════════════════════════════════│       │
│    │                                                               │       │
│                                                                            │
│  First request:  10-170ms (includes handshakes)                           │
│  Subsequent:     1-5ms (just HTTP exchange) ← 10-50x faster!              │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### MCP Protocol: An Additional Layer

The Model Context Protocol (MCP) adds its own session initialization on top of HTTP:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    MCP Session Initialization                               │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  MCP Client                                                    MCP Server  │
│    │                                                               │       │
│    │ ┌─────────────────────────────────────────────────────────┐  │       │
│    │ │ TCP + TLS (reused via HTTP Keep-Alive in httpx client)  │  │       │
│    │ └─────────────────────────────────────────────────────────┘  │       │
│    │                                                               │       │
│    │═══════════ initialize (JSON-RPC) ═════════════════════════►│ ①     │
│    │            {                                                  │       │
│    │              "method": "initialize",                          │       │
│    │              "params": {                                      │       │
│    │                "protocolVersion": "2025-03-26",               │       │
│    │                "capabilities": {...},                         │       │
│    │                "clientInfo": {"name": "gateway", ...}         │       │
│    │              }                                                │       │
│    │            }                                                  │       │
│    │                                                               │       │
│    │◄══════════ InitializeResult ══════════════════════════════│ ②     │
│    │            {                                                  │       │
│    │              "protocolVersion": "2025-03-26",                 │       │
│    │              "capabilities": {...},                           │       │
│    │              "serverInfo": {"name": "my-mcp-server", ...}     │       │
│    │            }                                                  │       │
│    │            Header: mcp-session-id: "abc123"                   │       │
│    │                                                               │       │
│    │═══════════ initialized (notification) ════════════════════►│ ③     │
│    │                                                               │       │
│    │ ┌─────────────────────────────────────────────────────────┐  │       │
│    │ │ Session established - can now call tools, read resources │  │       │
│    │ └─────────────────────────────────────────────────────────┘  │       │
│    │                                                               │       │
│    │═══════════ tools/call ════════════════════════════════════►│ ④     │
│    │◄══════════ CallToolResult ════════════════════════════════│       │
│    │                                                               │       │
│                                                                            │
│  ① Client sends initialize with protocol version and capabilities         │
│  ② Server responds with its capabilities and assigns mcp-session-id       │
│  ③ Client confirms with initialized notification                          │
│  ④ Now tool calls, resource reads, etc. can proceed                       │
│                                                                            │
│  MCP initialization overhead: ~10-15ms (2-3 round trips)                  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

The `mcp-session-id` header is critical - it identifies this session for all subsequent requests. The MCP SDK's `ClientSession` class manages this state internally.

### The Full Picture: Why Session Pooling Matters

Without session pooling, every tool call pays the full cost:

```
┌────────────────────────────────────────────────────────────────────────────┐
│              WITHOUT Session Pooling (Current MCP SDK Default)             │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Tool Call 1:                                                              │
│    TCP Handshake ───────────────────────────────── ~2ms                   │
│    TLS Handshake ───────────────────────────────── ~5ms                   │
│    MCP Initialize ──────────────────────────────── ~10ms                  │
│    Tool Execution ──────────────────────────────── ~2ms                   │
│    Close ───────────────────────────────────────── ~1ms                   │
│                                               Total: ~20ms                 │
│                                                                            │
│  Tool Call 2:                                                              │
│    TCP Handshake ───────────────────────────────── ~2ms                   │
│    TLS Handshake ───────────────────────────────── ~5ms                   │
│    MCP Initialize ──────────────────────────────── ~10ms                  │
│    Tool Execution ──────────────────────────────── ~2ms                   │
│    Close ───────────────────────────────────────── ~1ms                   │
│                                               Total: ~20ms                 │
│                                                                            │
│  Tool Call 3:  ~20ms                                                       │
│  Tool Call 4:  ~20ms                                                       │
│  ...                                                                       │
│                                                                            │
│  10 tool calls = 200ms total                                               │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│              WITH Session Pooling (This Implementation)                    │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Tool Call 1 (Pool Miss - creates new session):                           │
│    TCP Handshake ───────────────────────────────── ~2ms                   │
│    TLS Handshake ───────────────────────────────── ~5ms                   │
│    MCP Initialize ──────────────────────────────── ~10ms                  │
│    Tool Execution ──────────────────────────────── ~2ms                   │
│    Return to pool (not closed!) ────────────────── ~0ms                   │
│                                               Total: ~19ms                 │
│                                                                            │
│  Tool Call 2 (Pool Hit - reuses session):                                 │
│    Acquire from pool ───────────────────────────── ~0.1ms                 │
│    Tool Execution ──────────────────────────────── ~2ms                   │
│    Return to pool ──────────────────────────────── ~0.1ms                 │
│                                               Total: ~2ms  ← 10x faster!  │
│                                                                            │
│  Tool Call 3:  ~2ms (pool hit)                                            │
│  Tool Call 4:  ~2ms (pool hit)                                            │
│  ...                                                                       │
│                                                                            │
│  10 tool calls = 19ms + 9×2ms = 37ms total (vs 200ms = 5.4x faster!)      │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Comparison: HTTP Keep-Alive vs MCP Session Pooling

| Layer | What's Reused | Overhead Saved | Who Manages It |
|-------|---------------|----------------|----------------|
| HTTP Keep-Alive | TCP + TLS connection | ~5-15ms | `httpx` client |
| **MCP Session Pool** | TCP + TLS + MCP session | ~15-25ms | This implementation |

HTTP Keep-Alive is already used by the `httpx` client internally. MCP Session Pooling adds **MCP-level session reuse** on top, saving the `initialize` → `initialized` handshake (~10-15ms) on every call.

## Context

Every MCP tool call previously required establishing a new MCP session:

1. Create HTTP/SSE transport (httpx may reuse TCP via keep-alive)
2. Initialize MCP session (protocol handshake with capability negotiation)
3. Execute the tool call
4. Close MCP session

This per-request session overhead added **15-25ms latency** to every tool invocation, which becomes significant under high load or in latency-sensitive applications.

### Problem Statement

- **Latency**: MCP session initialization dominates tool call time for fast operations
- **Resource Usage**: Repeated protocol handshakes increase CPU usage
- **Scalability**: Session churn limits throughput under load
- **State Loss**: Each session starts fresh (no caching of tool lists, etc.)

### Requirements

1. Reduce tool call latency by reusing MCP sessions
2. Maintain session isolation between users/tenants
3. Support different transport types (SSE, StreamableHTTP)
4. Handle session failures gracefully
5. Prevent unbounded resource growth

## Decision

Implement a **session pool** that maintains persistent MCP `ClientSession` objects keyed by `(URL, identity_hash, transport_type)`.

### Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         ContextForge with Session Pool                       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌─────────────┐     ┌─────────────────────────────────────────────────┐  │
│  │   User A    │────►│                                                 │  │
│  │  (token X)  │     │                                                 │  │
│  └─────────────┘     │            ContextForge                          │  │
│                      │                                                 │  │
│  ┌─────────────┐     │   ┌─────────────────────────────────────────┐   │  │
│  │   User B    │────►│   │           Session Pool                  │   │  │
│  │  (token Y)  │     │   │                                         │   │  │
│  └─────────────┘     │   │  Pool Key = (URL, identity_hash, transport) │
│                      │   │                                         │   │  │
│  ┌─────────────┐     │   │  ┌─────────────────────────────────┐   │   │  │
│  │   User C    │────►│   │  │ Key: (mcp-server:8080, sha(X), http) │   │  │
│  │  (token X)  │     │   │  │ Sessions: [S1, S2, S3]          │───┼───┼──┼──► MCP Server A
│  └─────────────┘     │   │  └─────────────────────────────────┘   │   │  │
│                      │   │                                         │   │  │
│                      │   │  ┌─────────────────────────────────┐   │   │  │
│                      │   │  │ Key: (mcp-server:8080, sha(Y), http) │   │  │
│                      │   │  │ Sessions: [S4, S5]              │───┼───┼──┼──► MCP Server A
│                      │   │  └─────────────────────────────────┘   │   │  │
│                      │   │                                         │   │  │
│                      │   │  ┌─────────────────────────────────┐   │   │  │
│                      │   │  │ Key: (other-mcp:9000, sha(X), sse)  │   │  │
│                      │   │  │ Sessions: [S6]                  │───┼───┼──┼──► MCP Server B
│                      │   │  └─────────────────────────────────┘   │   │  │
│                      │   │                                         │   │  │
│                      │   └─────────────────────────────────────────┘   │  │
│                      │                                                 │  │
│                      └─────────────────────────────────────────────────┘  │
│                                                                            │
│  Note: User A and User C have the same token (X), so they share sessions  │
│        User B has different token (Y), so gets isolated sessions          │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

#### 1. Identity-Based Isolation

Sessions are isolated by a composite key:
```python
pool_key = (url, identity_hash, transport_type)
```

Where `identity_hash` is derived from authentication headers:

- `Authorization`
- `X-Tenant-ID`
- `X-User-ID`
- `X-API-Key`
- `Cookie`

This ensures different users/tenants never share sessions, preventing data leakage.

#### 2. Transport Type Isolation

Sessions are also isolated by transport type (SSE vs StreamableHTTP) because:

- Different transports have different connection semantics
- Mixing transports could cause protocol errors
- Allows independent tuning per transport

#### 3. Session Lifecycle

```
┌─────────────┐     acquire()      ┌─────────────┐
│  Pool       │ ─────────────────► │  Active     │
│  (Idle)     │                    │  (In Use)   │
└─────────────┘                    └─────────────┘
       ▲                                  │
       │         release()                │
       └──────────────────────────────────┘
                     │
                     │ (TTL expired or unhealthy)
                     ▼
              ┌─────────────┐
              │  Closed     │
              └─────────────┘
```

#### 4. Health Checking Strategy

Sessions are validated:

- **On acquire**: If idle > `health_check_interval` (default 60s), call `list_tools()` to verify health
- **On release**: If age > TTL, close instead of returning to pool
- **Background**: Stale sessions are reaped during acquire operations

This balances freshness with performance overhead.

#### 5. Circuit Breaker Pattern

Failed endpoints are temporarily blocked:

- After `threshold` consecutive failures (default 5), circuit opens
- Requests fail fast for `reset_seconds` (default 60s)
- Prevents cascade failures when an MCP server is down

#### 6. Timeout Configuration

The pool uses **separate timeouts** for different operations:

| Setting | Default | Purpose |
|---------|---------|---------|
| `health_check_interval` | 60s | Gateway health check frequency |
| `mcp_session_pool_health_check_interval` | 60s | Session staleness threshold |
| `mcp_session_pool_transport_timeout` | 30s | Transport timeout for all HTTP operations |

**Configuration behavior:**

- Pool health check interval uses `min(health_check_interval, mcp_session_pool_health_check_interval)`
- Pool transport timeout uses `mcp_session_pool_transport_timeout` (default 30s to match MCP SDK)

The transport timeout applies to **all** HTTP operations (connect, read, write) on pooled sessions. If your tools require longer execution times, increase this value accordingly.

#### 7. Configurable Health Check Chain

The pool uses a **configurable health check chain** to validate idle sessions. The chain tries methods in order until one succeeds:

```bash
# Default: try lightweight ping, skip if unsupported (for legacy servers)
# Note: Use JSON array format for list values
MCP_SESSION_POOL_HEALTH_CHECK_METHODS=["ping", "skip"]
MCP_SESSION_POOL_HEALTH_CHECK_TIMEOUT=5.0
```

**Available methods:**

- `ping` - MCP protocol ping (fastest, ~5ms, optional per spec)
- `list_tools` - List tools RPC (30-100ms, requires tools capability)
- `list_prompts` - List prompts RPC (30-100ms, requires prompts capability)
- `list_resources` - List resources RPC (30-100ms, requires resources capability)
- `skip` - Skip health check (maximum performance, use with caution)

**Example configurations:**

| Use Case | Configuration |
|----------|---------------|
| Modern servers (recommended) | `["ping", "skip"]` |
| Legacy server support | `["ping", "list_tools", "skip"]` |
| Maximum compatibility | `["ping", "list_tools", "list_prompts", "list_resources", "skip"]` |
| Maximum performance | `["skip"]` |
| Strict (fail if no ping) | `["ping"]` |

**How it works:**

- If a method returns `METHOD_NOT_FOUND` error, the next method is tried
- If a method times out, the next method is tried
- If a method succeeds, the session is considered healthy
- If all methods fail or are unsupported, the session is closed

```python
# mcp_session_pool.py
async def _run_health_check_chain(self, pooled: PooledSession) -> bool:
    for method in self._health_check_methods:
        if method == "ping":
            await pooled.session.send_ping()
            return True
        elif method == "skip":
            return True  # No health check
        # ... other methods
```

**Legacy option (deprecated):**
```bash
# Force explicit RPC even on fresh sessions (deprecated, use health check chain instead)
MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=false
```

### Implementation

**File:** `mcpgateway/services/mcp_session_pool.py`

```python
class MCPSessionPool:
    """Pool of MCP ClientSessions keyed by (URL, identity, transport)."""

    async def acquire(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        transport_type: TransportType = TransportType.STREAMABLE_HTTP,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
        timeout: Optional[float] = None,
    ) -> PooledSession:
        """Acquire a session, creating if needed."""

    async def release(self, pooled: PooledSession) -> None:
        """Return session to pool for reuse."""

    @asynccontextmanager
    async def session(self, url, headers, transport_type, ...) -> AsyncIterator[PooledSession]:
        """Context manager for acquire/release lifecycle."""
```

**Usage in Services:**

```python
# tool_service.py, resource_service.py, gateway_service.py
async with pool.session(
    url=server_url,
    headers=auth_headers,
    transport_type=TransportType.SSE,
    httpx_client_factory=factory,
) as pooled:
    result = await pooled.session.call_tool(tool_name, arguments)
```

## Performance Characteristics

### Latency Improvement

| Scenario | Before (per-call) | After (pooled) | Improvement |
|----------|-------------------|----------------|-------------|
| Pool Hit | 20ms | 1-2ms | **10-20x** |
| Pool Miss | 20ms | 20ms | Same |
| Health Check | N/A | +5ms | Occasional |

### Real-World Metrics Example

From production deployment:
```json
{
    "hits": 2977,
    "misses": 10,
    "hit_rate": 0.9967,
    "pool_key_count": 2,
    "anonymous_identity_count": 2997,
    "circuit_breaker_trips": 0
}
```

**99.67% of requests reused existing sessions** → 10x latency reduction for those calls.

### Resource Usage

- **Memory**: ~1KB per pooled session
- **Connections**: Bounded by `max_per_key × unique_identities × urls`
- **Default**: 10 sessions per (URL, identity, transport)

### Idle Pool Eviction

Empty pool keys are evicted after `idle_pool_eviction_seconds` (default 600s) to prevent unbounded growth with rotating tokens.

## Consequences

### Positive

- **10-20x latency reduction** for repeated tool calls from same user
- **Reduced server load** through connection reuse
- **Improved throughput** under high concurrency
- **Graceful degradation** via circuit breaker
- **Session isolation** prevents cross-user data leakage
- **Configurable** - all parameters tunable via environment variables

### Negative

- **Memory overhead** for maintaining idle sessions
- **Complexity** - more moving parts than per-call connections
- **Stale sessions** possible if health check interval is too long
- **Header pinning** - session reuses original auth headers (by design)

### Neutral

- Requires graceful shutdown to close pool (`close_mcp_session_pool()`)
- Metrics available via `/admin/mcp-pool/metrics` endpoint
- Falls back to per-call sessions when pool unavailable (e.g., in tests)

## Configuration

Environment variables:

```bash
# Enable/disable pool (default: false - enable explicitly after testing)
MCP_SESSION_POOL_ENABLED=true  # Recommended for production

# Max sessions per (URL, identity, transport) - default: 10
MCP_SESSION_POOL_MAX_PER_KEY=10

# Session TTL before forced close - default: 300s
MCP_SESSION_POOL_TTL=300.0

# Idle time before health check - default: 60s
# Auto-aligned with min(HEALTH_CHECK_INTERVAL, MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL)
MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL=60.0

# Transport timeout for all HTTP operations (connect, read, write) - default: 30s
# Increase for deployments with long-running tool calls
MCP_SESSION_POOL_TRANSPORT_TIMEOUT=30.0

# Timeout waiting for session slot - default: 30s
MCP_SESSION_POOL_ACQUIRE_TIMEOUT=30.0

# Timeout creating new session - default: 30s
MCP_SESSION_POOL_CREATE_TIMEOUT=30.0

# Circuit breaker failures threshold - default: 5
MCP_SESSION_POOL_CIRCUIT_BREAKER_THRESHOLD=5

# Circuit breaker reset time - default: 60s
MCP_SESSION_POOL_CIRCUIT_BREAKER_RESET=60.0

# Evict idle pool keys after - default: 600s
MCP_SESSION_POOL_IDLE_EVICTION=600.0

# Force explicit RPC (list_tools) on gateway health checks - default: false
# Off by default for performance; pool's internal staleness check is sufficient.
# Enable for stricter health verification at ~5ms latency cost per check.
MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=false
```

## Design Considerations

### Why Not Share Sessions Across Users?

Security: MCP sessions may contain user-specific state (authentication context, rate limits, permissions). Sharing sessions could leak data between users.

### Why Identity Hash Instead of Full Headers?

1. **Privacy**: Full headers may contain secrets
2. **Efficiency**: Hash comparison is O(1)
3. **Stability**: Irrelevant header changes don't fragment pools

### Why Not Refresh Headers on Reuse?

The MCP protocol establishes auth during `initialize()`. Changing headers mid-session would require protocol renegotiation, defeating the purpose of pooling.

For rotating tokens, use `identity_extractor` to extract stable identity (e.g., user ID from JWT claims), ensuring the same user always gets the same pool.

## Known Limitations

### 1. Request-Scoped Headers Are Pinned

The MCP SDK pins headers at transport creation time. Per-request headers (like `X-Correlation-ID`) passed to pooled sessions become "sticky" and are reused for all subsequent requests on that session.

**Impact**: Distributed tracing may attribute multiple requests to the same correlation ID if they share a pooled session.

**Mitigation**: The gateway strips `X-Correlation-ID` from headers before pooling. If you need per-request headers downstream, use non-pooled sessions or contribute MCP SDK support for per-request headers.

### 2. identity_extractor Requires Code Changes

The `identity_extractor` callback is supported in pool code but cannot be enabled via environment variables. Operators who need custom identity extraction (e.g., extracting user ID from JWT claims) must modify the initialization code in `main.py`.

### 3. Circuit Breaker Is URL-Scoped

The circuit breaker tracks failures per URL, not per identity. If one tenant causes repeated session creation failures, the circuit opens for all tenants accessing that URL.

**Scope**: Only session creation failures (connection refused, SSL errors) trip the circuit. Tool call failures do not affect the circuit breaker.

### 4. TLS Configuration Not in Pool Key

Pool keys do not include TLS/CA context. If the same URL is accessed with different CA bundles (unusual deployment pattern), the first session's TLS configuration may be reused.

## Security Considerations

### Session Isolation Model

Sessions are isolated by a composite key: `(URL, identity_hash, transport_type)`. The identity hash is derived from authentication headers (`Authorization`, `X-Tenant-ID`, `X-User-ID`, `X-API-Key`, `Cookie`).

**Key security properties:**

- Different users with different credentials get different pool keys → different sessions
- Different MCP server URLs always get different sessions
- Identity is validated at the gateway level; upstream MCP servers validate only `mcp-session-id`

### Anonymous Pooling Risk

When no identity headers are present, identity collapses to `"anonymous"`, causing all such requests to share sessions. This is acceptable **only if**:

1. The gateway requires authentication (default), preventing truly anonymous requests
2. Upstream MCP servers are stateless and don't maintain per-session context

If MCP servers maintain per-session state, anonymous pooling can leak data between users.

**Recommended configuration**: Ensure `AUTH_REQUIRED=true` and identity headers are present via passthrough or gateway authentication.

### Shared Credentials Scenario

With shared service credentials (OAuth Client Credentials, static API keys), all users share the same `Authorization` header and therefore the same session. This is intentional for machine-to-machine auth where the MCP server has no per-user concept.

**Risk**: Only if the upstream MCP server maintains per-user state. For truly stateless servers, this is safe and provides maximum connection reuse.

### Token Rotation Handling

With default configuration, `Authorization` is part of the identity hash. Token rotation produces a new pool key and therefore a new session. Stale tokens are not reused.

**Exception**: If `identity_extractor` is enabled (requires code changes) or `Authorization` is removed from identity headers, rotating tokens may reuse sessions with stale credentials until TTL expiration.

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| HTTP/2 multiplexing only | Saves TCP/TLS but not MCP initialize overhead |
| Global session pool | Security risk from cross-user session sharing |
| No pooling | Unacceptable latency for high-throughput use cases |
| Connection-only pool | MCP session state includes more than just connection |

## References

- [HTTP Persistent Connection (Wikipedia)](https://en.wikipedia.org/wiki/HTTP_persistent_connection)
- [MCP Protocol Specification](https://modelcontextprotocol.io/docs/concepts/architecture)
- `mcpgateway/services/mcp_session_pool.py` - Implementation
- `mcpgateway/config.py` - Configuration settings
- `mcpgateway/admin.py` - Metrics endpoint (`/admin/mcp-pool/metrics`)
- `tests/unit/mcpgateway/services/test_mcp_session_pool.py` - Unit tests

## Status

Implemented and **disabled by default** for safety. Enable explicitly after testing:

```bash
MCP_SESSION_POOL_ENABLED=true
```

Provides 10-20x latency improvement for tool calls with session reuse.
