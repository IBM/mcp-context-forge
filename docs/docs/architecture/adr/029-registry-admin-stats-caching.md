# ADR-029: Registry and Admin Stats Caching

- *Status:* Accepted
- *Date:* 2025-01-15
- *Deciders:* Platform Team

## Context

Under high-concurrency load testing, two additional performance bottlenecks were identified beyond authentication (addressed in ADR-028):

1. **Registry List Endpoints**: Tools, prompts, resources, agents, servers, and gateways list endpoints each query the database on every request. With pagination, filtering, and team-based access control, these queries became expensive under load.

2. **Admin Dashboard Stats**: The admin dashboard aggregates statistics from multiple tables (tools, prompts, resources, servers, users, teams) with expensive COUNT queries executed on every page load.

At 1000+ concurrent users:
- Registry list endpoints: ~50-100ms per request due to complex JOIN queries
- Admin stats: ~200-500ms per request aggregating across tables
- N+1 query patterns in team name resolution

Related issues: #1680 (Distributed Registry & Admin Stats Caching)

## Decision

Implement distributed caching for registry list endpoints and admin dashboard statistics, following the same hybrid Redis + in-memory pattern established in ADR-028.

### Changes Made

1. **New module: `mcpgateway/cache/registry_cache.py`**
   - `RegistryCache` class with Redis primary + in-memory fallback
   - Per-entity-type TTL configuration (tools, prompts, resources, agents, servers, gateways)
   - Filter-aware cache keys (tags, include_inactive, pagination cursor)
   - Automatic invalidation on CRUD operations

2. **New module: `mcpgateway/cache/admin_stats_cache.py`**
   - `AdminStatsCache` class with Redis primary + in-memory fallback
   - Separate TTLs for system stats, observability, users, and teams
   - Cached versions of expensive aggregate queries

3. **N+1 Query Fixes**
   - `prompt_service.py:list_prompts()` - Batch team name fetching
   - `resource_service.py:list_resources()` - Batch team name fetching
   - Single query fetches all team names for a page of results

4. **Cache Integration in Services**
   - `tool_service.py:list_tools()` - Cache first page results
   - `prompt_service.py:list_prompts()` - Cache first page results
   - `resource_service.py:list_resources()` - Cache first page results
   - `a2a_service.py:list_agents()` - Cache agent listings
   - `server_service.py:list_servers()` - Cache server listings
   - `gateway_service.py:list_gateway_peers()` - Cache gateway listings
   - `system_stats_service.py:get_comprehensive_stats_cached()` - Cached stats

5. **Cache Invalidation Hooks**
   - Tool create/update/delete triggers `cache.invalidate_tools()`
   - Prompt create/update/delete triggers `cache.invalidate_prompts()`
   - Resource create/update/delete triggers `cache.invalidate_resources()`
   - Similar patterns for agents, servers, gateways

6. **Configuration Settings**

   Registry Cache:
   - `REGISTRY_CACHE_ENABLED` (default: true)
   - `REGISTRY_CACHE_TOOLS_TTL` (default: 20s)
   - `REGISTRY_CACHE_PROMPTS_TTL` (default: 15s)
   - `REGISTRY_CACHE_RESOURCES_TTL` (default: 15s)
   - `REGISTRY_CACHE_AGENTS_TTL` (default: 20s)
   - `REGISTRY_CACHE_SERVERS_TTL` (default: 20s)
   - `REGISTRY_CACHE_GATEWAYS_TTL` (default: 20s)

   Admin Stats Cache:
   - `ADMIN_STATS_CACHE_ENABLED` (default: true)
   - `ADMIN_STATS_CACHE_SYSTEM_TTL` (default: 60s)
   - `ADMIN_STATS_CACHE_OBSERVABILITY_TTL` (default: 30s)

### Cache Key Scheme

Registry cache keys include filter hashes for cache differentiation:

```
{prefix}registry:tools:{filters_hash}        → Serialized tools list + cursor
{prefix}registry:prompts:{filters_hash}      → Serialized prompts list + cursor
{prefix}registry:resources:{filters_hash}    → Serialized resources list + cursor
{prefix}registry:agents:{filters_hash}       → Serialized agents list + cursor
{prefix}registry:servers:{filters_hash}      → Serialized servers list + cursor
{prefix}registry:gateways:{filters_hash}     → Serialized gateways list + cursor
```

Admin stats cache keys:

```
{prefix}stats:system         → System stats JSON
{prefix}stats:observability  → Observability metrics JSON
{prefix}stats:users          → Users list JSON
{prefix}stats:teams          → Teams list JSON
```

Default prefix: `mcpgw:` → `mcpgw:registry:tools:abc123`

### Caching Strategy

- **First page only**: Only the first page (cursor=None) of results is cached to maximize hit rate
- **Filter-aware**: Different filter combinations get different cache entries
- **Automatic invalidation**: CRUD operations invalidate entire entity type cache
- **Graceful fallback**: Database queries still work if cache unavailable

## Performance Optimizations

### Before (Baseline)
| Metric | Value |
|--------|-------|
| List tools latency P50 | ~50ms |
| Admin dashboard load | ~300ms |
| N+1 queries per list | 10-50 (one per result) |

### After (With Caching)
| Metric | Cache Hit | Cache Miss |
|--------|-----------|------------|
| List tools latency P50 | ~2-5ms | ~50ms |
| Admin dashboard load | ~5-10ms | ~300ms |
| N+1 queries per list | 0 | 1 (batch fetch) |

**Expected improvement**: 80-95% reduction for cached requests

## Consequences

### Positive

- Significant reduction in database load for read-heavy workloads
- Faster admin dashboard rendering
- Eliminated N+1 query patterns
- Better user experience for browsing registry
- Redis cache enables shared state across workers

### Negative

- Cache staleness window (up to TTL) after modifications:
  - Registry changes: up to 15-20s
  - Stats changes: up to 30-60s
- Additional memory usage for in-memory fallback cache
- Complexity in cache key management for filtered queries

### Neutral

- Only first page cached (pagination beyond first page always hits DB)
- TTL values are configurable if defaults don't fit use case
- Feature is backward-compatible (defaults to enabled)

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Cache all pages | Low hit rate, high memory usage |
| Longer TTLs | Too stale for active registries |
| Query result caching at DB level | Less control, doesn't help N+1 |
| Materialized views | PostgreSQL-specific, complex maintenance |

## Compatibility Notes

- Features are enabled by default
- Can be disabled without code changes via environment variables
- No database schema changes required
- Works with existing pagination patterns

## References

- GitHub Issue #1680: Distributed Registry & Admin Stats Caching
- ADR-028: Authentication Data Caching (establishes pattern)
- `mcpgateway/cache/registry_cache.py` - Registry cache implementation
- `mcpgateway/cache/admin_stats_cache.py` - Admin stats cache implementation
- `mcpgateway/services/*_service.py` - Integration points

## Status

Implemented and enabled by default. Monitor cache hit rates via stats endpoint.
