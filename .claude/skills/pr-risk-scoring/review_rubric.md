# PR Risk Scoring Rubric for ContextForge

## Context

With 50 open PRs spanning trivial UI fixes (+5 lines) to massive security features (+15K lines), the team needs a systematic way to allocate review effort. The goal: spend 2-4 hours on PRs that could break auth, and 5 minutes on CODEOWNERS updates.

## Risk Score: 6 Dimensions, 0-35 Points

### Dimension 1: Zone Score (0-10 pts)

Each file touched maps to a risk zone. Sum the per-file zone scores, cap at 10.

| Zone | Pts/file | Files |
|------|----------|-------|
| **Z4 - Auth core** | 4 | `auth.py`, `middleware/token_scoping.py`, `middleware/rbac.py`, `middleware/auth_middleware.py`, `middleware/http_auth_middleware.py`, `services/permission_service.py`, `routers/auth.py`, `routers/oauth_router.py`, `routers/tokens.py`, `routers/sso.py`, `services/sso_service.py`, `common/oauth.py` |
| **Z3 - Transport/session** | 3 | `transports/*.py`, `services/mcp_session_pool.py`, `cache/session_registry.py`, middleware ordering section of `main.py` |
| **Z3 - Data model / connections** | 3 | `db.py` (ORM models, pool config, `ResilientSession`, `SessionLocal`, engine creation), `schemas.py`, `alembic/versions/*.py` |
| **Z3 - Config/flags** | 3 | `config.py` (includes DB pool sizing, Redis pool limits, worker counts, cache TTLs) |
| **Z3 - Per-request middleware** | 3 | `middleware/rbac.py`, `middleware/token_usage_middleware.py` (both acquire DB sessions on every request) |
| **Z2 - Plugin framework** | 2 | `plugins/framework/**/*.py` |
| **Z2 - Cache / pooling** | 2 | `cache/auth_cache.py` (2-tier L1/L2), `cache/registry_cache.py`, `cache/resource_cache.py`, `cache/tool_lookup_cache.py`, `cache/global_config_cache.py` |
| **Z2 - Business logic** | 2 | Other `services/*.py`, `routers/*.py`, `main.py` (non-middleware) |
| **Z1 - Admin UI** | 1 | `admin.py`, `templates/*.html`, `static/*.js` |
| **Z0 - Docs/CI/meta** | 0 | `docs/`, `.github/`, `README.md`, `Makefile`, `charts/`, `llms/` |
| **Z0 - Tests only** | 0 | `tests/**` (when no prod code changes) |

### Dimension 2: Size Score (0-5 pts)

| Lines changed (add+del) | Files | Score |
|--------------------------|-------|-------|
| <= 50 | <= 3 | 0 |
| 51-200 | <= 6 | 1 |
| 201-500 | <= 10 | 2 |
| 501-1500 | <= 15 | 3 |
| 1501-4000 | <= 30 | 4 |
| > 4000 OR > 30 files | any | 5 |

Use the higher of the two bracket scores.

### Dimension 3: Structural Impact (0-5 pts, additive)

| Condition | Pts |
|-----------|-----|
| New Alembic migration | +2 |
| New/modified DB table in `db.py` | +2 |
| Modifies middleware ordering in `main.py` | +3 |
| Changes `normalize_token_teams()` or `get_current_user()` | +3 |
| Changes security feature flags in `config.py` | +2 |
| Modifies transport endpoint auth logic | +2 |
| Adds new router/endpoint | +1 |
| Pure rename/move refactor (no logic change) | -1 |

### Dimension 4: Security Invariant Impact (0-5 pts, additive)

| Condition | Pts |
|-----------|-----|
| Modifies two-layer model (token scoping + RBAC interaction) | +3 |
| Changes `oauth_enabled` enforcement | +3 |
| New bypass/exception to AUTH_REQUIRED | +3 |
| Token team interpretation outside `normalize_token_teams()` | +4 |
| Auth tokens via URL query parameters | +5 |
| Changes plugin auth hook execution | +2 |
| External contributor touching Z3/Z4 files | +1 |

### Dimension 5: Test Adequacy (0-5 pts, penalty)

| Condition | Pts |
|-----------|-----|
| Zero test files in diff (with prod code changes) | +3 |
| Security code changes without deny-path tests | +2 |
| New endpoints without integration tests | +1 |
| Test-only PR | -5 (floor at 0 total) |

### Dimension 6: Performance Impact (0-5 pts, additive)

**Background:** The application runs behind Gunicorn with up to 16 workers. Each worker holds a SQLAlchemy connection pool (default `pool_size=200`, `max_overflow=10`; SQLite capped at 50). Total possible DB connections = `pool_size * workers` (up to 3,200 for PostgreSQL). Synchronous SQLAlchemy sessions run inside async FastAPI handlers (intentional design). Redis connections are pooled at 50/worker. Per-request middleware (`rbac.py`, `token_usage_middleware.py`) acquires a DB session on every request via `fresh_db_session()`.

| Condition | Pts | What to look for |
|-----------|-----|------------------|
| Adds DB queries to per-request middleware path | +3 | New `fresh_db_session()` or `SessionLocal()` calls in middleware. At 1K req/s with 16 workers, each added query multiplies connection pressure by request volume. |
| Introduces N+1 query pattern (loop with per-iteration DB call) | +3 | `for item in items: db.query(...)` without `selectinload`/`joinedload`. Existing services explicitly annotate N+1 prevention (Issue #1892). |
| Modifies connection pool config or session lifecycle | +3 | Changes to `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` in `db.py` or `config.py`. Changes to `ResilientSession`, `SessionLocal`, `get_db()`, `fresh_db_session()`, or engine event listeners. |
| Bypasses or weakens caching layer | +2 | Removes or reduces TTLs on `auth_cache` (L1/L2), `registry_cache`, `global_config_cache`, or `tool_lookup_cache`. These caches reduce auth queries from 3-4/request to ~0-1/TTL. |
| Adds bulk/unbounded DB operations without batching | +2 | `db.query(Model).all()` without `LIMIT`, or inserts without `bulk_insert`/`executemany`. Existing pattern: `metrics_buffer_service`, `audit_trail_service` batch writes. |
| Modifies Gunicorn worker config or preload behavior | +2 | Changes to `run-gunicorn.sh` (worker count formula, `max_requests`, preload, post-fork hooks). Post-fork hook resets Redis clients per worker; breaking this causes cross-worker connection sharing. |
| Changes Redis connection pooling or fallback behavior | +2 | Modifications to `redis_max_connections`, Redis health check intervals, or the graceful fallback from Redis to in-memory cache. Silent Redis failures could cascade to DB overload. |
| Holds DB session across `await` boundaries | +2 | Sync `SessionLocal()` opened before an `await` and used after. Blocks the connection pool slot for the entire async wait duration. |

## Automatic Overrides

These override the numeric score:

- **Auto Tier 1:** Modifies `normalize_token_teams()`, introduces query-param auth, changes middleware ordering in `main.py`
- **Auto Tier 2 min:** New Alembic migration, or external contributor touching Z3/Z4
- **Auto Tier 2 min:** Changes to `db.py` engine/pool/session creation, `run-gunicorn.sh` worker config, or `ResilientSession`
- **`do-not-merge` label:** Blocks merge regardless of score

## Review Tiers

### Tier 1: Deep Review (20-35 pts) -- Red

**Examples from current PRs:** #3248 (CSRF, 29 files), #3292 (JIT access, new DB table + router)

| Aspect | Requirement |
|--------|-------------|
| **Reviewers** | 2 core maintainers, at least 1 with security expertise |
| **Time budget** | 2-4 hours per reviewer |
| **Activities** | Full line-by-line diff of all prod files |
| | Threat model walkthrough: unauth, wrong-team, expired-token, feature-disabled |
| | Migration verification: single head, idempotent guards |
| | Middleware ordering audit if `main.py` touched |
| | Deny-path test review (401/403 for all new paths) |
| | `normalize_token_teams` consistency check |
| | Config impact: `.env.example` updated, secure defaults |
| | **Connection budget analysis:** Trace new DB session acquisitions per request path. Verify sessions use `fresh_db_session()` context manager (not `Depends(get_db)` in middleware). Estimate worst-case pool pressure = (new queries/request) * (peak RPS) * (avg query duration). |
| | **Cache dependency audit:** If new code bypasses caching, estimate the DB query amplification factor (auth_cache prevents ~3-4 queries/request). |

### Tier 2: Standard Review (11-19 pts) -- Orange

**Examples:** #3344 (protocol hardening), #3449 (rate limiter), #3414 (mgmt-plane isolation), #3432 (streamable-http public access)

| Aspect | Requirement |
|--------|-------------|
| **Reviewers** | 1 core maintainer with domain knowledge |
| **Time budget** | 1-2 hours |
| **Activities** | Line-by-line review of Z3/Z4 files; skim Z0/Z1 |
| | Auth boundary check on new/modified endpoints |
| | Migration review if present |
| | Test adequacy: happy-path + error-path tests present |
| | Cache invalidation review if cache layer touched |
| | **N+1 query check:** Verify new service code uses `selectinload`/`joinedload` for relationship traversals. Look for DB queries inside loops. |
| | **Session lifecycle check:** Confirm DB sessions are scoped to context managers, not held across `await` calls or leaked through early returns. |

### Tier 3: Focused Review (5-10 pts) -- Yellow

**Examples:** #3309 (cache invalidation), #3239 (metrics), #3337 (extract util), #3263 (configurable patterns)

| Aspect | Requirement |
|--------|-------------|
| **Reviewers** | 1 maintainer (any) |
| **Time budget** | 30-60 minutes |
| **Activities** | Targeted review of core change logic |
| | Pattern consistency check (follows existing conventions?) |
| | Test presence check |
| | CI green confirmation |
| | **Spot-check for unbounded queries:** Look for `.all()` without `LIMIT` or bulk operations without batching. |

### Tier 4: Quick Review (0-4 pts) -- Green

**Examples:** #3436 (CODEOWNERS), #3402 (1-file UI fix), #3396 (pagination), #3265 (Ollama defaults), #3330 (UI CRUD)

| Aspect | Requirement |
|--------|-------------|
| **Reviewers** | 1 maintainer (quick approval) |
| **Time budget** | 5-15 minutes |
| **Activities** | Spot check: change matches title, no secrets, no unrelated files |
| | CI green confirmation |

## Quick Heuristic (30-second version)

For a maintainer scanning a new PR without computing the full score:

1. **Does it touch Z4 files (auth, middleware, tokens)?** At least Tier 2. Over 500 lines? Tier 1.
2. **Does it add a migration or new DB table?** At least Tier 2.
3. **Does it touch `db.py` (pool/session), `run-gunicorn.sh`, or per-request middleware?** At least Tier 2.
4. **Only Z0/Z1 files and under 200 lines?** Tier 4.
5. **Everything else?** Tier 3.

## Operational Labels

Add these GitHub labels to PRs after scoring:

- `review:deep` (red) -- Tier 1
- `review:standard` (orange) -- Tier 2
- `review:focused` (yellow) -- Tier 3
- `review:quick` (green) -- Tier 4

## Implementation (optional automation)

This rubric can be partially automated via a GitHub Action that:
1. Reads the file list from the PR diff
2. Maps files to zones
3. Computes Zone + Size scores (dimensions 1 & 2)
4. Detects presence of `alembic/versions/`, `db.py`, `run-gunicorn.sh` for structural/perf flags
5. Applies automatic override rules
6. Applies the appropriate `review:*` label
7. Dimensions 3-6 require human judgment but could be assisted by an LLM reviewing the diff; Dimension 6 (Performance) can be partially automated by grepping for `SessionLocal()`, `fresh_db_session()`, `.all()`, and loop-nested DB access patterns in the diff
