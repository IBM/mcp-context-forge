# ADR-055: Scope Tool Lookup Cache Entries

- *Status:* Accepted
- *Date:* 2026-09-24
- *Deciders:* Platform Team
- *Supersedes:* ADR-033

## Context

ADR-033 introduced name-keyed tool lookup caching. A tool name is not globally unique across tenants or virtual servers.

Two tenants can register same-name private or team tools. A name-only cache entry can make the second tenant read the first tenant's metadata.
Authorization fails closed, but resolution stops before the database can select the second tenant's tool.

Negative entries also depend on caller visibility. A shared negative entry can suppress a valid tool for another caller.

Server detach operations create another stale-data risk. Failed cross-worker invalidation can leave a cached association until its TTL expires.

## Decision

Scope positive entries by virtual server when `server_id` is present. Keep global positive entries only for unambiguous public tools.

Scope negative entries by a SHA-256 digest of these visibility inputs:

- Caller email.
- Effective token teams.
- MCP Apps visibility requirement.
- Model visibility requirement.

Include `server_id` in negative keys for virtual-server calls. Do not cache ambiguous same-name database results.

Treat every cache entry as a performance hint. Revalidate caller visibility after each hit.

For server-scoped hits, also query `server_tool_association`. Reject stale entries when the tool is no longer attached.

Use targeted server invalidation for tool mutations. Publish invalidations so other workers clear matching L1 entries.

Track caller-scoped negative entries in an expiry-scored Redis sorted set. Prune expired members during writes and invalidation.

## Cache Key Scheme

`v3` separates this format from legacy name-only entries. New code does not read legacy keys.

```text
{prefix}tool_lookup:v3:{tool_name}
{prefix}tool_lookup:v3:server:{server_id}:{tool_name}
{prefix}tool_lookup:v3:negative:{caller_scope}:{tool_name}
{prefix}tool_lookup:v3:server:{server_id}:negative:{caller_scope}:{tool_name}
```

Redis maintains these invalidation indexes:

```text
{prefix}tool_lookup:gateway:{gateway_id}
{prefix}tool_lookup:server:{server_id}
{prefix}tool_lookup:negative_name:{tool_name}
```

L1 remains worker-local. Redis L2 remains shared across workers.

Redis Pub/Sub distributes gateway, server, and exact-key invalidations to remote L1 caches.

## Performance Contract

| Invocation path | Tool-record query | Membership query |
|---|---:|---:|
| Cache disabled | 1 | Included in scoped tool query |
| Global L1 hit | 0 | 0 |
| Global Redis L2 hit | 0 | 0 |
| Server-scoped L1 hit | 0 | 1 |
| Server-scoped Redis L2 hit | 0 | 1 |

The membership query is required for fail-closed detach behavior. Cache hits still avoid loading full tool and gateway records.

Run the tool lookup benchmark to compare latency percentiles and query counts:

```bash
uv run pytest tests/performance/test_tool_lookup_cache_performance.py -v -s
```

Latency depends on database and Redis deployment characteristics. Store benchmark results with the tested environment and commit identifier.

## Consequences

### Positive

- Same-name tenant tools cannot collide through server-scoped cache keys.
- Negative entries cannot poison another caller's visibility context.
- Detached tools fail closed after cross-worker invalidation failure.
- Expired caller indexes do not grow without bounds.

### Negative

- Server-scoped hits execute one membership query.
- Cache writes maintain more invalidation metadata.
- Keys from ADR-033 expire naturally because `v3` does not read them.

### Neutral

- No API or database schema changes occur.
- Cache disablement remains an operational fallback.
- Existing L1 and Redis L2 configuration variables remain unchanged.

## Alternatives Considered

| Option | Why Not |
|---|---|
| Trust invalidation without membership validation | Failed Pub/Sub delivery leaves detached tools invocable until TTL expiry. |
| Cache every same-name candidate | It increases payload size and keeps authorization-dependent selection in cache code. |
| Disable negative caching | It restores repeated database load for unavailable tools. |
| Use name-only negative entries | One caller can suppress another caller's valid tool. |

## References

- GitHub Issue #6959: Tool lookup cache collides across tenant scopes
- ADR-033: Tool Lookup Cache for `invoke_tool`
- `mcpgateway/cache/tool_lookup_cache.py`
- `mcpgateway/services/tool_service.py`
