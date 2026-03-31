# Rate Limiter Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Enforces fixed-window rate limits per user, tenant, and tool across `tool_pre_invoke` and `prompt_pre_fetch` hooks. Supports an in-process memory backend (single-instance) and a Redis backend (shared across all gateway instances).

## Hooks

| Hook | When it runs |
|---|---|
| `tool_pre_invoke` | Before every tool call — checks `by_user`, `by_tenant`, `by_tool` |
| `prompt_pre_fetch` | Before every prompt fetch — checks `by_user`, `by_tenant`, `by_tool` |

If any configured dimension is exceeded, the plugin returns a violation with HTTP 429. All requests include `X-RateLimit-*` headers. The most restrictive active dimension is surfaced (e.g. if both user and tenant limits are active, the one closest to exhaustion is reported).

## Configuration

```yaml
- name: RateLimiterPlugin
  kind: plugins.rate_limiter.rate_limiter.RateLimiterPlugin
  version: "0.1.0"
  author: Mihai Criveti
  hooks:
    - prompt_pre_fetch
    - tool_pre_invoke
  mode: enforce          # enforce | permissive | disabled
  config:
    by_user: "30/m"      # per-user limit across all tools
    by_tenant: "300/m"   # shared limit across all users in a tenant
    by_tool:             # per-tool overrides (applied on top of by_user)
      search: "10/m"
      summarise: "5/m"

    # Backend — choose one
    backend: "memory"    # default: single-process, resets on restart
    # backend: "redis"   # shared across all gateway instances

    # Redis options (required when backend: redis)
    redis_url: "redis://redis:6379/0"
    redis_key_prefix: "rl"
    redis_fallback: true  # fall back to memory if Redis is unavailable
```

### Configuration reference

| Field | Type | Default | Description |
|---|---|---|---|
| `by_user` | string | `null` | Per-user rate limit, e.g. `"60/m"` |
| `by_tenant` | string | `null` | Per-tenant rate limit, e.g. `"600/m"` |
| `by_tool` | dict | `{}` | Per-tool overrides, e.g. `{"search": "10/m"}` |
| `backend` | string | `"memory"` | `"memory"` or `"redis"` |
| `redis_url` | string | `null` | Redis connection URL (required when `backend: redis`) |
| `redis_key_prefix` | string | `"rl"` | Prefix for all Redis keys |
| `redis_fallback` | bool | `true` | Fall back to memory backend if Redis is unavailable |

**Rate string format:** `"<count>/<unit>"` where unit is `s`/`sec`/`second`, `m`/`min`/`minute`, or `h`/`hr`/`hour`. Malformed strings raise `ValueError` at startup.

**Omitting a dimension** (e.g. no `by_tenant`) means that dimension is unlimited — no counter is tracked for it.

## Response headers

Every request (allowed or blocked) includes:

| Header | Description |
|---|---|
| `X-RateLimit-Limit` | Configured limit for the most restrictive active dimension |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | Unix timestamp when the current window resets |
| `Retry-After` | Seconds until the window resets (blocked requests only) |

## Backends

### Memory backend (default)

- Counters are stored in a process-local dict (`_store`)
- An `asyncio.Lock` serialises all counter reads and writes — safe under concurrent asyncio tasks
- A background sweep task evicts expired windows every 0.5s — memory is bounded to active windows only
- **Limitation:** state is not shared across processes or hosts. In a multi-instance deployment (e.g. 3 gateway instances behind nginx), each instance tracks its own counter — the effective limit is `N × configured_limit`

### Redis backend

- Counters are stored in Redis using an atomic Lua `INCR`+`EXPIRE` script — a single Redis call per check with no race condition
- All gateway instances share the same counter — the configured limit is the true cluster-wide limit
- Requires `redis_url` to be set
- If `redis_fallback: true` (default) and Redis is unavailable, the plugin falls back to the in-process `MemoryBackend` automatically — requests are never blocked due to Redis downtime
- If `redis_fallback: false` and Redis is unavailable, the exception is caught and the request is allowed through (fail-open)

**Multi-instance deployment:** use `backend: redis`. The Redis service is already included in the default Docker Compose stack at `redis://redis:6379/0`.

## Examples

### Single-instance (default config)

```yaml
config:
  by_user: "60/m"
  by_tenant: "600/m"
```

### Multi-instance with Redis

```yaml
config:
  backend: "redis"
  redis_url: "redis://redis:6379/0"
  redis_fallback: true
  by_user: "30/m"
  by_tenant: "3000/m"
  by_tool:
    search: "10/m"
```

### Permissive mode (observe without blocking)

```yaml
mode: permissive
config:
  by_user: "60/m"
```

In `permissive` mode the plugin records violations and emits `X-RateLimit-*` headers but does not block requests. Useful for baselining traffic before switching to `enforce`.

## Limitations

| Limitation | Severity | Status |
|---|---|---|
| Memory backend not shared across processes | HIGH | Use Redis backend for multi-instance deployments |
| Fixed window allows up to 2× limit at window boundary | LOW | Deferred — use `by_user` with headroom as a workaround |
| No per-server limits (`server_id` dimension missing) | LOW | Not implemented |
| No config hot-reload — rate string changes require restart | LOW | Not implemented |
| Memory backend not safe under threaded workers (gunicorn `--threads`) | LOW | asyncio.Lock is loop-safe; use async workers (`-k uvicorn`) |
