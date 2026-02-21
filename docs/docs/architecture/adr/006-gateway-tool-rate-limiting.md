# ADR-0006: Gateway & Tool-Level Rate Limiting

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

The ContextForge may serve hundreds of concurrent clients accessing multiple tools.
Without protection, a single client or misbehaving tool could monopolize resources or overwhelm upstream services.

The configuration includes:

- `TOOL_RATE_LIMIT`: default limit in requests/min per tool/client
- Planned support for Redis-based or database-backed counters

Current implementation is an in-memory token bucket.

## Decision

Implement a **rate limiter at the tool invocation level**, keyed by:

- Tool name
- Authenticated user / client identity (JWT or Basic)
- Time window (per-minute by default)

Backend options:

- **Memory** (default for dev / single instance)
- **Redis** (planned for clustering / shared limits)
- **Database** (eventually consistent fallback)

## Consequences

- ✅ Prevents abuse, controls cost, and provides predictable fairness
- 📉 Failed requests return `429 Too Many Requests` with retry headers
- ❌ Memory backend does not scale across instances; Redis required for HA
- 🔄 Optional override of limits via config/env for testing

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **No rate limiting** | Leaves gateway and tools vulnerable to overload or accidental DoS. |
| **Global rate limit only** | Heavy tools can starve lightweight tools; no fine-grained control. |
| **Proxy-level throttling (e.g. NGINX, Envoy)** | Can't distinguish tools or users inside payload; lacks granularity. |

## Status

Rate limiting is implemented for tool routes, with `TOOL_RATE_LIMIT` as the default policy.
