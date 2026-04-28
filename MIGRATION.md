# Migration Guide — API v1 Prefix

**PR:** [#4403 feat: API endpoint is served under the `/v1` prefix](https://github.com/IBM/mcp-context-forge/pull/4403)
**Branch:** `API_v1` → `main`
**Type:** Breaking change

---

## Overview

This release introduces API versioning for ContextForge. Most resource management and business-logic endpoints are now served under the `/v1` URL prefix. A new `mcpgateway/api/v1/__init__.py` module centralises router assembly via a `build_v1_router()` factory, keeping `main.py` clean and making future version additions (`/v2`, etc.) straightforward.

Protocol-level routes, infrastructure-compatible routes, and some maintenance APIs intentionally remain unversioned at the root. These either follow external standards, must stay stable for infrastructure compatibility, or are mounted separately from the main versioned router.

---

## Breaking Change

Most previously unversioned resource-management paths are now served under `/v1`. Clients must update their base URLs accordingly.

**Affected paths (previously at root, now under `/v1`):**

`/tools`, `/resources`, `/prompts`, `/gateways`, `/servers`, `/roots`, `/metrics`, `/tags`, `/a2a`, `/admin`, `/auth`, `/teams`, `/tokens`, `/rbac`, `/observability`, `/cancellation`, `/toolops`, `/reverse-proxy`, `/export`, `/import`

**Important exception:** not every metrics-related route becomes `/v1/metrics/**`. Metrics maintenance endpoints remain available at `/api/metrics/**`, and may also be exposed under `/v1/api/metrics/**` when enabled.

---

## Endpoint Classification

### Versioned — now served under `/v1`

| Endpoint Group | Old Path | New Path | Feature Flag |
|---|---|---|---|
| MCP Protocol | `/protocol/**` | `/v1/protocol/**` | always-on |
| Tools | `/tools/**` | `/v1/tools/**` | always-on |
| Resources | `/resources/**` | `/v1/resources/**` | always-on |
| Prompts | `/prompts/**` | `/v1/prompts/**` | always-on |
| Gateways | `/gateways/**` | `/v1/gateways/**` | always-on |
| Roots | `/roots/**` | `/v1/roots/**` | always-on |
| Servers | `/servers/**` | `/v1/servers/**` | always-on |
| Metrics | `/metrics/**` | `/v1/metrics/**` | always-on |
| Tags | `/tags/**` | `/v1/tags/**` | always-on |
| Export / Import | `/export`, `/import` | `/v1/export`, `/v1/import` | always-on |
| Tool Plugin Bindings | `/tools/plugin_bindings/**` | `/v1/tools/plugin_bindings/**` | always-on |
| Admin UI & API | `/admin/**` | `/v1/admin/**` | `MCPGATEWAY_ADMIN_API_ENABLED` |
| Runtime Admin | `/admin/runtime/**` | `/v1/admin/runtime/**` | `MCPGATEWAY_ADMIN_API_ENABLED` |
| LLM Admin | `/admin/llm/**` | `/v1/admin/llm/**` | `MCPGATEWAY_LLMCHAT_ENABLED` |
| A2A | `/a2a/**` | `/v1/a2a/**` | `MCPGATEWAY_A2A_ENABLED` |
| Observability | `/observability/**` | `/v1/observability/**` | `OBSERVABILITY_ENABLED` |
| Reverse Proxy | `/reverse-proxy/**` | `/v1/reverse-proxy/**` | `MCPGATEWAY_REVERSE_PROXY_ENABLED` |
| Tool Cancellation | `/cancellation/**` | `/v1/cancellation/**` | `MCPGATEWAY_TOOL_CANCELLATION_ENABLED` |
| ToolOps | `/toolops/**` | `/v1/toolops/**` | `TOOLOPS_ENABLED` |
| Authentication | `/auth/**` | `/v1/auth/**` | `EMAIL_AUTH_ENABLED` |
| Email Authentication | `/auth/email/**` | `/v1/auth/email/**` | `EMAIL_AUTH_ENABLED` |
| SSO Authentication | `/auth/sso/**` | `/v1/auth/sso/**` | `EMAIL_AUTH_ENABLED` + `SSO_ENABLED` |
| Teams | `/teams/**` | `/v1/teams/**` | `EMAIL_AUTH_ENABLED` |
| JWT Token Catalog | `/tokens/**` | `/v1/tokens/**` | `EMAIL_AUTH_ENABLED` |
| RBAC | `/rbac/**` | `/v1/rbac/**` | `EMAIL_AUTH_ENABLED` |
| LLM Chat | `/llmchat/**` | `/v1/llmchat/**` | `MCPGATEWAY_LLMCHAT_ENABLED` |
| LLM Config | `/llm/**` | `/v1/llm/**` | `MCPGATEWAY_LLMCHAT_ENABLED` |
| Metrics maintenance | `/api/metrics/**` | `/v1/api/metrics/**` | `metrics_cleanup_enabled` or `metrics_rollup_enabled` |

### Not versioned — remain at root (unchanged)

| Endpoint | Path | Reason |
|---|---|---|
| Health probes | `/health`, `/ready`, `/health/security` | Infrastructure / liveness; must remain stable |
| MCP Streamable HTTP transport | `/mcp` | MCP protocol spec — path is fixed by the spec |
| Internal MCP transport bridge | `/_internal/mcp/transport` | Internal trusted bridge; not a public API |
| OAuth 2.0 | `/oauth/**` | Standard protocol location (RFC 6749) |
| Well-known URIs | `/.well-known/**` | RFC 8615 / RFC 9116 / RFC 9728 — path is standardised |
| Per-server well-known | `/servers/{id}/.well-known/**` | RFC standard path; must not be prefixed |
| Version / Diagnostics | `/version` | Diagnostic utility, not a resource API |
| Static assets | `/static/**` | UI asset serving |
| Root redirect | `/` | Entry point / UI redirect |
| Favicon | `/favicon.ico` | Browser convention |
| Log Search | `/api/logs/**` | Internal structured-logging query interface |
| Metrics maintenance | `/api/metrics/**` | Operational maintenance API remains mounted at root |
| LLM Proxy | `{LLM_API_PREFIX}` (default `/v1`) | Prefix is runtime-configurable via `LLM_API_PREFIX`; it is mounted directly on `app`, not nested inside the gateway's own `/v1` router, even when the configured prefix is also `/v1` |

---

## Migration Steps

### 1. Update all client base URLs

Replace any hardcoded unversioned paths in your client code, configuration files, CI scripts, or SDK wrappers:

```diff
- GET /tools
+ GET /v1/tools

- POST /gateways
+ POST /v1/gateways

- GET /servers
+ GET /v1/servers

- GET /admin/
+ GET /v1/admin/

- POST /auth/login
+ POST /v1/auth/login
```

### 2. Update environment variables or base-URL constants

If you configure a base URL such as `MCPGATEWAY_BASE_URL=https://example.com`, ensure downstream consumers append `/v1/` before any resource segment:

```diff
- https://example.com/tools/list
+ https://example.com/v1/tools/list
```

### 3. Update API clients / SDKs

Any SDK or HTTP client wrapper that prepends a path prefix must be updated to use `/v1`:

```python
# Before
client = MCPGatewayClient(base_url="https://example.com")
client.get("/tools")

# After
client = MCPGatewayClient(base_url="https://example.com/v1")
client.get("/tools")
# or
client.get("/v1/tools")
```

### 4. Update reverse-proxy / load-balancer rules

If you have Nginx, HAProxy, or cloud load-balancer rules that route on path prefixes, add `/v1` to resource-path matchers. Health, OAuth, well-known, `/mcp`, `/api/logs/**`, and `/api/metrics/**` paths do not change.

### 5. Migrate test paths (automated helper)

A utility script is provided to migrate Python test file path references automatically:

```bash
python scripts/update_test_paths.py
```

This script rewrites path strings such as `"/tools"` → `"/v1/tools"` across Python test files under `tests/` while skipping paths that are intentionally unversioned (`.well-known`, `/oauth`, `/mcp`, `/health`, `/api/logs`, `/api/metrics`, etc.).

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
| `mcpgateway/routers/metrics_maintenance.py` | Metrics maintenance endpoints remain mounted at `/api/metrics/**` and are also conditionally included under `/v1/api/metrics/**` |
| `tests/` | Python test paths are migrated toward `/v1` prefixed resource endpoints |
| `scripts/update_test_paths.py` | **New** — utility script for migrating Python test path references under `tests/` |
