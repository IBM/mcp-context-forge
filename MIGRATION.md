# API v1 Migration Guide

The canonical migration guide is maintained in the project documentation:

**[docs/docs/manage/api-v1-migration.md](docs/docs/manage/api-v1-migration.md)**

It covers versioned and unversioned endpoints, deprecation headers, migration timeline, configuration options, client examples, troubleshooting, and FAQ.

---

## Code Changes (Summary)

| File | Change |
|---|---|
| `mcpgateway/api/v1/__init__.py` | **New** — `build_v1_router()` factory that assembles all versioned routers under `/v1`; feature-flagged routers are conditionally included here |
| `mcpgateway/api/__init__.py` | **New** — namespace package |
| `mcpgateway/main.py` | Router registration refactored; versioned routers delegated to `build_v1_router()`; unversioned routers mounted directly on `app` |
| `mcpgateway/admin.py` | Admin redirect paths updated to `/v1/admin/*` |
| `mcpgateway/middleware/path_filter.py` | Path references updated to `/v1` prefixed patterns |
| `mcpgateway/middleware/rbac.py` | Path references updated to `/v1` prefixed patterns |
| `mcpgateway/middleware/token_scoping.py` | Path references updated; `/v1` prefix stripped for internal pattern matching |
| `mcpgateway/routers/metrics_maintenance.py` | Metrics maintenance endpoints remain mounted at `/api/metrics/**` |
| `tests/` | Python test paths migrated toward `/v1` prefixed resource endpoints |
| `scripts/update_test_paths.py` | **New** — one-time utility for migrating Python test path references under `tests/` |
