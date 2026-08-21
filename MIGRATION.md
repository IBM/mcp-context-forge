# ContextForge Migration Guide

Step-by-step instructions for upgrading between major versions. For a full list of changes per release see [CHANGELOG.md](./CHANGELOG.md).

---

## Upgrading to v1.0.x (API v1 — versioned routes)

### What changed

Resource-management and business-logic REST routes now live under the `/v1/` prefix. Protocol-level routes (MCP transports, OAuth, health probes, well-known URIs) and diagnostics endpoints intentionally remain unversioned at the root — see the "Routes not versioned" table below. The legacy (unversioned) resource-management paths remain available but respond with `Sunset` and `Deprecation` headers to signal that they will be removed in a future release.

### API path migration table

#### Always-on routes

| Legacy path (deprecated) | v1 path (canonical) |
|--------------------------|---------------------|
| `* /protocol/**` | `* /v1/protocol/**` |
| `GET /tools` | `GET /v1/tools` |
| `POST /tools` | `POST /v1/tools` |
| `GET /tools/{id}` | `GET /v1/tools/{id}` |
| `* /tools/plugin_bindings/**` | `* /v1/tools/plugin_bindings/**` |
| `GET /resources` | `GET /v1/resources` |
| `GET /prompts` | `GET /v1/prompts` |
| `GET /gateways` | `GET /v1/gateways` |
| `POST /gateways` | `POST /v1/gateways` |
| `* /roots/**` | `* /v1/roots/**` |
| `GET /servers` | `GET /v1/servers` |
| `POST /servers` | `POST /v1/servers` |
| `GET /servers/{id}` | `GET /v1/servers/{id}` |
| `GET /metrics` | `GET /v1/metrics` |
| `* /tags/**` | `* /v1/tags/**` |
| `GET /export` | `GET /v1/export` |
| `POST /import` | `POST /v1/import` |

#### Feature-flagged routes

| Legacy path (deprecated) | v1 path (canonical) | Feature flag |
|--------------------------|---------------------|--------------|
| `* /a2a/**` | `* /v1/a2a/**` | `MCPGATEWAY_A2A_ENABLED` |
| `* /observability/**` | `* /v1/observability/**` | `OBSERVABILITY_ENABLED` |
| `* /reverse-proxy/**` | `* /v1/reverse-proxy/**` | `MCPGATEWAY_REVERSE_PROXY_ENABLED` |
| `* /toolops/**` | `* /v1/toolops/**` | `TOOLOPS_ENABLED` |
| `* /cancellation/**` | `* /v1/cancellation/**` | `MCPGATEWAY_TOOL_CANCELLATION_ENABLED` |
| `* /api/metrics/**` | `* /v1/api/metrics/**` | `METRICS_CLEANUP_ENABLED` or `METRICS_ROLLUP_ENABLED` |
| `* /auth/**` | `* /v1/auth/**` | `EMAIL_AUTH_ENABLED` |
| `* /auth/email/**` | `* /v1/auth/email/**` | `EMAIL_AUTH_ENABLED` |
| `* /auth/sso/**` | `* /v1/auth/sso/**` | `EMAIL_AUTH_ENABLED` + `SSO_ENABLED` |
| `* /teams/**` | `* /v1/teams/**` | `EMAIL_AUTH_ENABLED` |
| `* /tokens/**` | `* /v1/tokens/**` | `EMAIL_AUTH_ENABLED` |
| `* /rbac/**` | `* /v1/rbac/**` | `EMAIL_AUTH_ENABLED` |
| `* /llmchat/**` | `* /v1/llmchat/**` | `MCPGATEWAY_LLMCHAT_ENABLED` |
| `* /llm/**` | `* /v1/llm/**` | `MCPGATEWAY_LLMCHAT_ENABLED` |
| `* /compliance/**` | `* /v1/compliance/**` | `MCPGATEWAY_ADMIN_API_ENABLED` |
| `* /admin/**` | `* /v1/admin/**` | `MCPGATEWAY_ADMIN_API_ENABLED` |
| `* /admin/runtime/**` | `* /v1/admin/runtime/**` | `MCPGATEWAY_ADMIN_API_ENABLED` |
| `* /admin/llm/**` | `* /v1/admin/llm/**` | `MCPGATEWAY_ADMIN_API_ENABLED` + `MCPGATEWAY_LLMCHAT_ENABLED` |

#### Routes not versioned (remain at root)

These paths are intentionally kept at the server root with no `/v1` equivalent:

| Path | Reason |
|------|--------|
| `/health`, `/ready`, `/health/security` | Infrastructure liveness — must remain stable for load balancers |
| `/mcp` | MCP protocol spec — path fixed by the specification |
| `/_internal/mcp/transport` | Internal trusted bridge; not a public API |
| `/oauth/**` | Standard protocol location (RFC 6749) |
| `/.well-known/**` | RFC 8615 / RFC 9116 / RFC 9728 — path is standardised |
| `/servers/{id}/.well-known/**` | RFC standard path, must not be prefixed |
| `/static/**` | UI asset serving |
| `/` | Entry point / UI redirect |
| `/favicon.ico` | Browser convention |
| `/api/logs/**` | Internal structured-logging query interface |
| `{LLM_API_PREFIX}` (default `/v1`) | Runtime-configurable LLM proxy — set `LLM_API_PREFIX=/llm/v1` to avoid collision with the gateway `/v1` prefix |

Token scope patterns (`^/tools`, `^/admin`) continue to match both versioned and unversioned paths — **no pattern changes required**.

### Configuration changes

| Setting | Default | Notes |
|---------|---------|-------|
| `LEGACY_API_ENABLED` | `true` | Set `false` to disable unversioned shims after migration |
| `LEGACY_API_SUNSET_DATE` | `Sat, 26 Sep 2026 00:00:00 GMT` | RFC 8594 date sent in `Sunset` response header |
| `LLM_API_PREFIX` | `/v1` | **Action required** — change to `/llm/v1` or similar to avoid collision with the gateway v1 prefix |

### Migration steps

1. Update all client base URLs from `https://host/` to `https://host/v1/`.
2. Update any hardcoded paths in scripts, Helm values, or environment files.
3. Set `LLM_API_PREFIX=/llm/v1` (or another distinct path) in your `.env` if `llmchat_enabled=true`.
4. Validate with smoke tests against the new paths.
5. Once all clients are migrated, set `LEGACY_API_ENABLED=false` to enforce the new paths.

---

## v1.0.1 Breaking Changes

### HTTP Redirect Handling — Security Hardening

**What changed:** ContextForge no longer follows HTTP redirects (301/302/307/308) when calling registered tool URLs, gateway health checks, SSE endpoints, StreamableHTTP endpoints, or A2A agent invocations. This prevents SSRF-via-redirect attacks.

**Impact:** Systems that register redirect-based URLs will see request failures.

**Migration:**
- Register final destination URLs directly (no redirect hops).
- For tools behind a proxy, register the proxy's final URL.
- Full guide: [`docs/docs/operations/ssrf-redirect-protection-migration.md`](docs/docs/operations/ssrf-redirect-protection-migration.md)

### Plugin Framework extracted to CPEX

**What changed:** The internal plugin framework was replaced by the external `cpex` package.

**Migration:**
1. `pip install cpex` (or add to your `requirements.txt`).
2. Update plugin imports from `mcpgateway.plugins.*` to `cpex.*`.
3. See the [CPEX migration guide](https://github.com/IBM/mcp-context-forge/pull/3754) for full details.

### Environment-aware security defaults

**What changed:** Strong secrets are now required in non-development environments. Weak or default values for `JWT_SECRET_KEY`, `BASIC_AUTH_PASSWORD`, and `AUTH_ENCRYPTION_SECRET` cause startup failure.

**Migration:**
```bash
python -m mcpgateway.utils.generate_keys
```
Copy the generated values into your `.env`. Set `REQUIRE_STRONG_SECRETS=false` only for local development (not recommended for production).

---

## v1.0.2 Breaking Changes

### UUID primary keys

**What changed:** Primary keys and foreign keys migrated from integer to UUID format.

**Impact:** Any external system storing raw numeric IDs (e.g., `tool_id=42`) will need to switch to UUID values. UUIDs are returned in all API responses.

**Migration:** Fetch the resource via its name or slug to obtain the new UUID, then update stored references.

### Alembic-only schema management

**What changed:** Database schema creation and updates now use Alembic exclusively. The previous `db.py`-driven `create_all` path is removed.

**Migration:**
```bash
cd mcpgateway && alembic upgrade head
```
Run this before starting the application on any existing database.

---

## Rollback

If you need to roll back to the previous version:

1. Stop the application.
2. `cd mcpgateway && alembic downgrade -1` (repeat as needed).
3. Deploy the previous container image or git tag.
4. Restart.

For Helm-based deployments, use `helm rollback <release>`.

---

## MCP Python SDK v2 Migration Checklist

Source: [MCP Python SDK v1 → v2 migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)

This checklist is the scope boundary for the SDK upgrade. Changes not required by one of these guide items are out of scope.

### Order

- [ ] Update dependency pins and MCP CLI usage.
- [ ] Apply type/import/field renames.
- [ ] Migrate the high-level `MCPServer` surface.
- [ ] Migrate low-level `Server` handlers and result types.
- [ ] Migrate `Client`/`ClientSession` callers.
- [ ] Migrate transports and authentication.
- [ ] Update validation, wire-format assumptions, and tests.
- [ ] Address applicable deprecations.
- [ ] Verify 2026-era connection behavior where used.

### Packaging, dependencies, and CLI

- [ ] Raise dependency floors: `anyio`, `pydantic`, `sse-starlette`, `typing-extensions`, and Windows `pywin32`.
- [ ] Add `opentelemetry-api` and exact-matched `mcp-types` only when the project depends on `mcp-types` directly.
- [ ] Upgrade the `mcp` requirement to v2 and remove the v1 upper-bound pattern.
- [ ] Replace SDK-provided `httpx`/`httpx-sse` usage with `httpx2`; update exception types, fixtures, logging, and instrumentation.
- [ ] Remove the `ws` extra and WebSocket transport usage.
- [ ] Confirm `mcp dev` and `mcp install` use the installed SDK version.

### Types and wire format

- [ ] Keep `mcp.types` as the SDK-backed import surface; use direct `mcp_types` imports only for a project that declares `mcp-types` without `mcp`.
- [ ] Move `mcp.shared.version` imports to `mcp.types.version`.
- [ ] Replace removed aliases/classes: `Content`, `ResourceReference`, `Cursor`, public type variables, `AnyFunction`, old `*Type` unions, and experimental task constants.
- [ ] Replace camelCase Python fields with snake_case; use `model_dump(by_alias=True)` for wire JSON.
- [ ] Audit code that relied on unknown MCP fields being preserved.
- [ ] Treat resource URIs as `str`, not `AnyUrl`.
- [ ] Replace `RootModel` union construction/validation with the supplied `TypeAdapter` instances; remove `.root` access.
- [ ] Replace `RequestParams.Meta` with `RequestParamsMeta` and treat `ctx.meta` as a `TypedDict`.
- [ ] Replace deprecated `SUPPORTED_PROTOCOL_VERSIONS` handshake checks with the appropriate v2 version constants.
- [ ] Rename `McpError` to `MCPError`.
- [ ] Accept nullable `JSONRPCError.id` values and validate JSON-RPC messages with v2 adapters.

### High-level `MCPServer`

- [ ] Rename `FastMCP` to `MCPServer`.
- [ ] Preserve the documented unchanged `MCPServer` surface.
- [ ] Account for the default server name changing to `mcp-server`.
- [ ] Update positional constructor calls for `title`, `description`, and `version`.
- [ ] Set an explicit server version where an empty unversioned version is not acceptable.
- [ ] Remove `mount_path` arguments and settings.
- [ ] Move transport-specific constructor arguments to `run()`/`*_app()` calls.
- [ ] Stop relying on `MCP_*` environment variables or SDK `.env` loading.
- [ ] Check the 4 MiB Streamable HTTP request-body limit.
- [ ] Check lifespan ownership changes in `StreamableHTTPSessionManager`.
- [ ] Remove `MCPServer.get_context()` usage; use injected context.
- [ ] Account for synchronous handlers running on worker threads.
- [ ] Handle `CallToolResult` and possible `InputRequiredResult` returns.
- [ ] Pass context explicitly when directly calling server methods.
- [ ] Ensure resolver-routed requests have the required client capability.
- [ ] Update `MCPError` handler behavior and resource-not-found handling.
- [ ] Remove rejected resource keywords and replace `FileResource.is_binary` with `encoding`.
- [ ] Review RFC 6570 resource-template matching changes.
- [ ] Rename Context logging `message` to `data` and remove `extra`.
- [ ] Remove `Context.client_id` and the removed progress module/context manager.
- [ ] Validate elicitation schemas and avoid `isinstance()` checks against `ElicitationResult`.
- [ ] Register low-level handlers through supported public APIs.

### Low-level `Server`

- [ ] Preserve the documented unchanged low-level serving scaffolding.
- [ ] Replace decorator registration with constructor `on_*` parameters or `add_*_handler()`.
- [ ] Return fully constructed protocol result types; do not rely on automatic wrapping.
- [ ] Reassess exception behavior: ordinary tool exceptions are JSON-RPC errors, not `CallToolResult(is_error=True)`.
- [ ] Make post-name constructor parameters keyword-only and reduce the type parameter count.
- [ ] Remove uses of `request_handlers`/`notification_handlers`, private `_handle_*`, `stateless`, and `request_context`.
- [ ] Update `RequestContext` imports and `ServerSession` assumptions.
- [ ] Rename `requestedSchema` to `requested_schema`.
- [ ] Remove `RequestResponder`/`mcp.shared.session` compatibility assumptions; use typed callbacks or middleware.

### Clients

- [ ] Decide whether `Client(mode="auto")` or `mode="legacy"` is required for each connection.
- [ ] Replace `get_server_capabilities()` with `server_capabilities`, `server_info`, `instructions`, and `protocol_version`.
- [ ] Remove deprecated `cursor` list parameters and use `arguments` instead of `args`.
- [ ] Change timeout values from `timedelta` to float seconds.
- [ ] Update timeout error handling to `MCPError` code `REQUEST_TIMEOUT` (`-32001`).
- [ ] Remove `BaseSession` and old dispatcher/customization assumptions.
- [ ] Remove experimental Tasks client/server usage.

### Transports

- [ ] Replace `streamablehttp_client` with `streamable_http_client`.
- [ ] Remove `get_session_id`; consume the returned two-tuple.
- [ ] Configure headers, timeout, SSE read timeout, and auth on the `httpx2.AsyncClient`.
- [ ] Stop reading `StreamableHTTPTransport.protocol_version`; use session/client negotiated state.
- [ ] Update non-2xx handling to per-request `MCPError` behavior.
- [ ] Remove deprecated Windows termination helpers and account for stdio shutdown/descriptor behavior.
- [ ] Remove WebSocket client/server transport usage.

### OAuth and server auth

- [ ] Confirm unchanged auth surfaces remain unchanged.
- [ ] Remove `RFC7523OAuthClientProvider` and `JWTParameters` usage.
- [ ] Preserve empty OAuth metadata URL paths; do not add trailing slashes.
- [ ] Return `AuthorizationCodeResult` from OAuth callbacks and validate `iss`.
- [ ] Rename provider `scopes=` to `scope=`.
- [ ] Account for `client_secret_post` including `client_id`.
- [ ] Remove the unused OAuth provider `timeout` argument/context value.
- [ ] Handle issuer mismatch rejection and the v2 OAuth scope/credential changes.
- [ ] Set OAuth Dynamic Client Registration `application_type` where needed.
- [ ] Treat `OAuthClientInformationFull` as separate from registration metadata.
- [ ] Review stricter `/token` and `/revoke` client authentication.

### Validation, testing, and deprecations

- [ ] Validate server handler results against the negotiated protocol schema.
- [ ] Validate inbound client traffic against the negotiated schema.
- [ ] Expect unknown methods to return `-32601`.
- [ ] Update raw-wire assertions for the always-present `_meta` envelope and OpenTelemetry propagation.
- [ ] Replace `create_connected_server_and_client_session` with `Client(server)`.
- [ ] Review resource-subscription, Roots, Sampling, Logging, and client-to-server progress deprecations.
- [ ] For 2026-era connections, handle `NoBackChannelError`, request-scoped logging, subscription-only notifications, and `Mcp-Param-*` header validation.

### Branch audit

- [ ] Keep only dependency, import, type, client, transport, handler, test, and documentation changes attributable to the guide.
- [ ] Exclude unrelated secret-baseline regeneration, token-exchange cache isolation, identity-test cleanup, and connect-mode configuration work.
- [ ] Run applicable SDK migration tests and verify the staged diff contains no unrelated files or hunks.
