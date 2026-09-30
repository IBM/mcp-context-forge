# ADR-056: Harden Scoped Tool Lookup Resolution and Invalidation

- *Status:* Accepted
- *Date:* 2026-09-25
- *Deciders:* Platform Team
- *Supersedes:* ADR-055

## Context

ADR-055 isolated tool lookup cache entries by virtual server and caller scope. Follow-up review found duplicated Python and Rust resolution logic, incomplete mixed-version invalidation, and an incomplete query-cost description.

The duplicate resolvers already differed on deprecated-tool handling. Legacy workers publish bare `tool_lookup:{name}` messages, while current workers can hold global, server-scoped, and caller-negative `v3` entries for that name.

## Decision

Use `ToolService._resolve_tool_for_invocation()` as the single resolver for Python invocation, preview, and Rust execution-plan preparation. It owns cache lookup, negative lookup, database fallback, cache population, visibility checks, deprecated-tool rejection, and server-membership validation.

Rust plan preparation calls the resolver without arguments. Pre-invoke plugins can therefore modify arguments before Rust execution without premature schema validation.

Keep the ADR-055 `v3` key scheme. Current code never reads pre-v3 Redis payload keys.

Treat bare `tool_lookup:{name}` messages as rolling-deployment compatibility messages. Clear every matching global, server-scoped, and caller-negative L1 entry. Delete matching `v3` Redis entries with incremental `SCAN` operations and do not publish another invalidation message.

Remove the global scoped-entry Redis index. Targeted gateway, server, negative-name, and exact-key indexes remain sufficient for current-format invalidations. Reject calls that combine `server_id` with `affected_server_ids` before any cache mutation.

Session-affinity cache reads remain routing hints. Owner-worker execution performs the shared resolver's Layer 1 visibility checks and Layer 2 RBAC checks before invoking a tool.

## Performance Contract

| Invocation path | Tool-record query | Membership query | Conditional visibility queries |
|---|---:|---:|---:|
| Cache disabled | 1 | Included in scoped tool query | 0-2 |
| Global L1 hit | 0 | 0 | 0-2 |
| Global Redis L2 hit | 0 | 0 | 0-2 |
| Server-scoped L1 hit | 0 | 1 | 0-2 |
| Server-scoped Redis L2 hit | 0 | 1 | 0-2 |

Visibility checks add no query for public tools or callers with explicit token teams. An unrestricted caller can add one admin lookup and one team-membership lookup. Session and auth caches can remove either query.

Performance regression tests assert SQL query counts. Latency percentiles and connection checkout counts remain diagnostic because deployment and pool behavior affect them. Tests assert that measurable checked-out connection counts return to their starting value.

## Consequences

### Positive

- Python and Rust invocation cannot drift on authorization or deprecated-tool behavior.
- Mixed-version invalidation clears current cache variants without a permanent global index.
- Server detach behavior remains fail-closed after cache hits.
- Query costs distinguish mandatory membership checks from conditional visibility lookups.

### Negative

- Legacy invalidation performs bounded incremental Redis scans during rolling deployments.
- Server-scoped hits retain one mandatory membership query.

### Neutral

- No HTTP, MCP, database schema, Redis key-version, or configuration-default change occurs.
- Existing cache TTLs continue to bound stale data after unavailable Redis operations.

## References

- GitHub Issue #6992: Complete tool lookup cache follow-ups from PR #6968
- ADR-033: Tool Lookup Cache for `invoke_tool`
- ADR-055: Scope Tool Lookup Cache Entries
- `mcpgateway/cache/tool_lookup_cache.py`
- `mcpgateway/services/tool_service.py`
