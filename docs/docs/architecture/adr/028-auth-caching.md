# ADR-028: Authentication Data Caching

- *Status:* Accepted
- *Date:* 2025-01-15
- *Deciders:* Platform Team

## Context

Under high-concurrency load testing (1000+ concurrent users), authentication became a significant performance bottleneck. Every authenticated request triggered 3-4 separate database queries via `asyncio.to_thread()`:

1. `_check_token_revoked_sync(jti)` - Check if JWT is revoked
2. `_get_personal_team_sync(user_email)` - Get user's personal team ID
3. `_get_user_by_email_sync(email)` - Fetch user data

Each call:
- Acquired a thread from the thread pool (contention under load)
- Opened a fresh DB connection from the pool
- Executed a single query
- Returned thread and connection to pool

At 1000 RPS with 2 replicas:
- ~6,000 thread pool acquisitions/second across replicas
- ~6,000 fresh DB sessions/second
- Significant CPU overhead from threading context switches

Related issues: #1677 (Cache JWT Token Verification), #1686 (Batch Team Membership Queries)

## Decision

Implement a two-tier authentication caching system with Redis as the primary store and in-memory cache as fallback, combined with query batching.

### Changes Made

1. **New module: `mcpgateway/cache/auth_cache.py`**
   - `CachedAuthContext` dataclass for cached auth data
   - `AuthCache` class with Redis primary + in-memory fallback
   - TTL-based expiration with configurable per-data-type TTLs
   - Cache invalidation on token revocation, password change, team membership change

2. **Query batching in `mcpgateway/auth.py`**
   - New `_get_auth_context_batched_sync()` function combines 3 queries into 1 DB session
   - Modified `get_current_user()` to:
     - Check cache first (fast path)
     - Use batched query on cache miss (single `asyncio.to_thread()` call)
     - Store result in cache for subsequent requests

3. **Cache invalidation hooks in services**
   - `token_catalog_service.py:revoke_token()` - Invalidates revocation cache
   - `email_auth_service.py:change_password()` - Invalidates user cache
   - `team_management_service.py:add_member_to_team/remove_member_from_team()` - Invalidates team cache

4. **Configuration settings**
   - `AUTH_CACHE_ENABLED` (default: true)
   - `AUTH_CACHE_USER_TTL` (default: 60s)
   - `AUTH_CACHE_REVOCATION_TTL` (default: 30s, security-critical)
   - `AUTH_CACHE_TEAM_TTL` (default: 60s)
   - `AUTH_CACHE_BATCH_QUERIES` (default: true)

### Cache Key Scheme

```
{cache_prefix}auth:user:{email}      → User data JSON
{cache_prefix}auth:team:{email}      → Personal team ID
{cache_prefix}auth:revoke:{jti}      → "1" if revoked
{cache_prefix}auth:ctx:{email}:{jti} → Batched context JSON
```

Default prefix: `mcpgw:` → `mcpgw:auth:ctx:admin@example.com:jti-123`

### Security Considerations

- **Short TTL for revocations (30s)**: Limits window where revoked token may still work
- **JWT payloads NOT cached**: JWTs are self-validating; caching would be a security risk
- **Immediate local invalidation**: Revoked tokens are added to in-memory set immediately
- **Cross-worker sync via Redis pub/sub**: Invalidation propagates to all workers
- **Graceful fallback**: If cache unavailable, falls back to DB queries

## Performance Optimizations

### Before (Baseline)
| Metric | Value |
|--------|-------|
| DB queries per auth | 3-4 |
| Thread pool acquisitions | 3 per request |
| Auth latency P50 | ~10ms |
| Auth latency P99 | ~25ms |

### After (With Caching + Batching)
| Metric | Cache Hit | Cache Miss |
|--------|-----------|------------|
| DB queries per auth | 0 | 1 |
| Thread pool acquisitions | 0 | 1 |
| Auth latency P50 (est.) | ~1-2ms | ~3-5ms |
| Auth latency P99 (est.) | ~3ms | ~8ms |

**Expected improvement**: 70-80% reduction in auth overhead

## Consequences

### Positive

- Significant reduction in database load under high concurrency
- Reduced thread pool contention from 3 calls to 0-1
- Better response times for authenticated endpoints
- Improved scalability for multi-replica deployments
- Redis cache enables shared state across workers

### Negative

- Added complexity in cache invalidation
- Slight delay (up to TTL) for changes to propagate:
  - User profile changes: up to 60s
  - Team membership changes: up to 60s
  - Token revocations: up to 30s (security-critical, kept short)
- Additional Redis dependency for distributed caching (fallback to in-memory available)

### Neutral

- In-memory cache remains as fallback when Redis unavailable
- JWT verification still happens every request (intentional for security)
- Configuration is backward-compatible (defaults to enabled)

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Cache JWT payloads | Security risk - JWTs should be re-verified for signature changes |
| Longer TTLs | Security concern for revocation, stale data for user changes |
| Only in-memory cache | Doesn't work for multi-replica deployments |
| Only Redis cache | No fallback when Redis unavailable |

## Compatibility Notes

- Feature is enabled by default (`AUTH_CACHE_ENABLED=true`)
- Can be disabled without code changes via environment variable
- No database schema changes required
- Backward-compatible with existing auth flows

## References

- GitHub Issue #1677: Cache JWT Token Verification Results
- GitHub Issue #1686: Batch Team Membership Queries
- GitHub Issue #1685: Optimize Database Session Creation and Management
- `mcpgateway/cache/auth_cache.py` - Implementation
- `mcpgateway/auth.py` - Integration with get_current_user()

## Status

Implemented and enabled by default. Monitor cache hit rate and auth latency in production.
