# ADR-032: MCP Session Pool for Connection Reuse

- *Status:* Accepted
- *Date:* 2025-01-05
- *Deciders:* Platform Team

## Context

Every MCP tool call previously required establishing a new connection to the MCP server:

1. Create HTTP/SSE transport
2. Establish TCP connection (potentially with TLS handshake)
3. Initialize MCP session (protocol handshake)
4. Execute the tool call
5. Close connection

This per-request connection overhead added **15-25ms latency** to every tool invocation, which becomes significant under high load or in latency-sensitive applications.

### Problem Statement

- **Latency**: Connection establishment dominates tool call time for fast operations
- **Resource Usage**: Repeated TLS handshakes increase CPU usage
- **Scalability**: Connection churn limits throughput under load
- **Connection Limits**: Rapid connect/disconnect can hit OS or load balancer limits

### Requirements

1. Reduce tool call latency by reusing MCP sessions
2. Maintain session isolation between users/tenants
3. Support different transport types (SSE, StreamableHTTP)
4. Handle session failures gracefully
5. Prevent unbounded resource growth

## Decision

Implement a **connection pool** that maintains persistent MCP sessions keyed by `(URL, identity_hash, transport_type)`.

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

Timeouts are **automatically aligned** with gateway health check settings for consistency:

| Setting | Default | Purpose |
|---------|---------|---------|
| `health_check_interval` | 60s | Gateway health check frequency |
| `mcp_session_pool_health_check_interval` | 60s | Session staleness threshold |
| `health_check_timeout` | 5s | Per-request timeout (used for pool transport timeout) |

**Auto-alignment behavior:**
- Pool health check interval uses `min(health_check_interval, mcp_session_pool_health_check_interval)`
- Pool transport timeout uses `health_check_timeout` directly (single source of truth)

This ensures pool timeouts never exceed gateway timeouts, preventing health check anomalies.

#### 7. Optional Explicit Health Verification

Gateway health checks can optionally perform **explicit RPC verification** via feature flag:

```bash
# Disabled by default for performance (pool's internal staleness check is sufficient)
MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC=false
```

When enabled, health checks call `list_tools()` even on fresh sessions:

```python
# gateway_service.py
async with pool.session(url, headers, transport_type) as pooled:
    if settings.mcp_session_pool_explicit_health_rpc:
        await asyncio.wait_for(
            pooled.session.list_tools(),
            timeout=settings.health_check_timeout,
        )
```

**Trade-off:**
- **Disabled (default)**: Pool's internal staleness check (idle > health_check_interval) handles health. Best performance (~1-2ms per check).
- **Enabled**: Every health check performs explicit RPC. Stricter verification at ~5ms latency cost per check.

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
# Enable/disable pool (default: true)
MCP_SESSION_POOL_ENABLED=true

# Max sessions per (URL, identity, transport) - default: 10
MCP_SESSION_POOL_MAX_PER_KEY=10

# Session TTL before forced close - default: 300s
MCP_SESSION_POOL_TTL=300.0

# Idle time before health check - default: 60s
# Auto-aligned with min(HEALTH_CHECK_INTERVAL, MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL)
MCP_SESSION_POOL_HEALTH_CHECK_INTERVAL=60.0

# Transport timeout uses HEALTH_CHECK_TIMEOUT directly (no separate setting)
# HEALTH_CHECK_TIMEOUT=5

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

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| HTTP/2 multiplexing | MCP SDK doesn't support it; would require upstream changes |
| Global session pool | Security risk from cross-user session sharing |
| No pooling | Unacceptable latency for high-throughput use cases |
| Connection-only pool | MCP session state includes more than just connection |

## References

- `mcpgateway/services/mcp_session_pool.py` - Implementation
- `mcpgateway/config.py` - Configuration settings
- `mcpgateway/admin.py` - Metrics endpoint (`/admin/mcp-pool/metrics`)
- `tests/unit/mcpgateway/services/test_mcp_session_pool.py` - Unit tests

## Status

Implemented and enabled by default. Provides 10-20x latency improvement for tool calls with session reuse.
