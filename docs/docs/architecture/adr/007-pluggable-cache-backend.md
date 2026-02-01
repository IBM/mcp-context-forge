# ADR-0007: Pluggable Cache Backend (memory / Redis / database)

- *Status:* Accepted
- *Date:* 2025-02-21
- *Deciders:* Core Engineering Team

## Context

The MCP Gateway uses short-lived caching for:

- Tool responses and resource lookups
- Peer discovery metadata
- Temporary session state and rate-limiting

Different deployments require different caching characteristics:

- Dev mode: no external services (in-memory only)
- Production: clustered and persistent (Redis)
- Air-gapped: embedded fallback (database table)

The config exposes `CACHE_TYPE=memory|redis|database`.

## Decision

Abstract the caching system via a `CacheBackend` interface and support the following pluggable backends:

- `MemoryCacheBackend`: simple `dict` with TTL, for dev and unit tests
- `RedisCacheBackend`: shared, centralized cache for multi-node clusters
- `DatabaseCacheBackend`: uses SQLAlchemy ORM to persist TTL-based records

Selection is driven by the `CACHE_TYPE` environment variable. Code paths use a consistent interface regardless of backend.

For multi-regional deployments, we support **Redis Cluster** for distributed caching across geographic regions. This enables:

- Cross-region cache replication
- Automatic sharding and failover
- High availability with Sentinel mode
- Shared state for federation across clusters

## Consequences

- 🔄 Easy to switch cache backend per environment or load profile
- 🚀 Redis allows horizontal scaling and persistent shared state
- 🌍 Redis Cluster enables multi-regional deployments with federation
- ❌ Memory cache does not survive restarts or share state
- 🐢 Database cache is slower, but useful in restricted networks

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Hardcoded Redis** | Adds operational overhead and single point of failure for dev. |
| **Memory-only cache** | Incompatible with horizontal scale or restart resilience. |
| **External CDN or HTTP cache** | Doesn't address in-process sessions, discovery, or tool state. |
| **Disk-based cache (e.g., shelve, pickle)** | Complex invalidation and concurrency issues; not cloud-ready. |

## Status

All three cache backends are implemented and the gateway selects one dynamically based on configuration.
