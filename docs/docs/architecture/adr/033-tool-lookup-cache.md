# ADR-033: Tool Lookup Cache for invoke_tool

- *Status:* Accepted
- *Date:* 2025-01-20
- *Deciders:* Platform Team

## Context

Load testing exposed a hot-path bottleneck in `ToolService.invoke_tool`: every tool invocation performs a DB lookup for the tool (and its gateway), even when the same tool is invoked repeatedly. This created:

- High database QPS proportional to tool invocations
- Connection pool saturation during slow upstream calls
- Elevated p95/p99 latency on high-concurrency tests

Existing registry/admin caches do not cover single-tool lookups, and `invoke_tool` cannot reuse registry list caches.

Related issues: #1940 (Tool lookup caching)

## Decision

Introduce a two-tier tool lookup cache keyed by tool name, with:

- L1 in-memory LRU + TTL per worker
- Optional Redis L2 for multi-worker deployments
- Negative caching for missing/inactive/offline tools
- Explicit invalidation on tool and gateway mutations

## Changes Made

1. **New module: `mcpgateway/cache/tool_lookup_cache.py`**
   - L1 LRU + TTL cache with size limit
   - Redis L2 cache with shared keyspace when `CACHE_TYPE=redis`
   - Negative cache entries (`missing`, `inactive`, `offline`)
   - Gateway-scoped invalidation using a Redis set of tool names

2. **Invoke path integration**
   - `ToolService.invoke_tool()` now checks cache before querying the DB
   - Cache payload includes tool + gateway fields needed for invocation
   - Negative cache entries short-circuit missing/inactive/offline tool calls

3. **Cache invalidation**
   - Tool create/update/delete/state invalidates tool lookup cache
   - Gateway update/state/delete invalidates all tools for that gateway

4. **Configuration**

   Tool Lookup Cache:
   - `TOOL_LOOKUP_CACHE_ENABLED` (default: true)
   - `TOOL_LOOKUP_CACHE_TTL_SECONDS` (default: 60)
   - `TOOL_LOOKUP_CACHE_NEGATIVE_TTL_SECONDS` (default: 10)
   - `TOOL_LOOKUP_CACHE_L1_MAXSIZE` (default: 10000)
   - `TOOL_LOOKUP_CACHE_L2_ENABLED` (default: true, only when `CACHE_TYPE=redis`)

## Cache Key Scheme

```
{prefix}tool_lookup:{tool_name}            → tool + gateway payload
{prefix}tool_lookup:gateway:{gateway_id}   → set of tool names (for invalidation)
```

Default prefix: `mcpgw:` → `mcpgw:tool_lookup:my_tool`

## Performance Optimizations

### Before (Baseline)
| Metric | Value |
|--------|-------|
| DB lookups per tool invocation | 1 |
| Invoke latency (cache miss) | DB-bound |

### After (With Caching)
| Metric | Cache Hit | Cache Miss |
|--------|-----------|------------|
| DB lookups per tool invocation | 0 | 1 |
| Invoke latency | ~1-3ms | DB-bound |

**Expected improvement**: 80-95% reduction in DB traffic for repeated tool invocations.

## Consequences

### Positive

- Removes hot-path DB lookups for repeat tool invocations
- Reduces connection pool pressure under high concurrency
- Redis L2 provides cross-worker cache reuse

### Negative

- Cache staleness window (up to TTL) after tool/gateway updates
- Additional memory use in each worker for L1 cache
- Requires careful invalidation on tool/gateway mutations

### Neutral

- L2 is optional and only enabled when `CACHE_TYPE=redis`
- Negative cache TTL is short to avoid long-lived false negatives
- No schema changes required

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Rely on registry list cache | Not usable for single tool lookups |
| Cache at router layer only | Still requires DB lookup per invocation |
| Longer TTLs | Too stale for active tool updates |
| Materialized view | Overkill and DB-specific |

## Compatibility Notes

- Enabled by default, can be disabled via env vars
- Works with existing cache backend configuration
- No API or schema changes required

## References

- GitHub Issue #1940: Tool lookup caching
- ADR-007: Pluggable cache backend
- ADR-029: Registry and Admin Stats Caching
- `mcpgateway/cache/tool_lookup_cache.py` - Implementation
- `mcpgateway/services/tool_service.py` - Integration

## Status

Implemented and enabled by default. Monitor Redis keyspace for `tool_lookup` keys.
