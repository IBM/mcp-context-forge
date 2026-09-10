# Product & API Terminology

The React admin UI uses product-facing terms: **MCP server**, **virtual server**, and
**A2A agent**. The API predates those terms and still uses its original vocabulary —
`gateway` and `server` — in routes, models, permission strings, and audit records.

[#6544](https://github.com/IBM/mcp-context-forge/issues/6544) tracks renaming the API to
match. Until that lands, the two vocabularies coexist. This page is the map between them
so you don't have to guess whether a mismatch is a documentation gap or a bug.

## The mapping

| Product term | Where it lives in the API | Notes |
| --- | --- | --- |
| **MCP server** | `/v1/mcp-servers` routes (`/gateways` deprecated), the `Gateway` model and `gateways` table, RBAC permissions `gateways.*`, audit rows with `resource_type="gateway"` | |
| **Virtual server** | `/v1/virtual-servers` routes (`/servers` deprecated), the `Server` model and `servers` table, RBAC permissions `servers.*`, audit rows with `resource_type="server"` | The model's own docstring calls it "ORM model for MCP Servers Catalog" — the same confusion exists inside the backend, not just at the API surface. |
| **A2A agent** | `/a2a` routes | The A2A service logs through the structured logger (`StructuredLogEntry` table), not `AuditTrail`, so A2A actions do not reach the activity/audit feed the way MCP server and virtual server actions do. |

## "Server" is ambiguous — always qualify it

Don't use the bare word "server" in docs or UI copy. It means different things
depending on which side you're standing on:

- In the **API**, `/servers` (and `/v1/virtual-servers`) refers to virtual servers.
- In the **React UI**, `src/api/servers.ts` wraps the `/gateways` endpoint — its own
  header comment says it "exposes as 'servers' API for frontend consistency" — so
  "server" there means an MCP server.

Always write "virtual server" or "MCP server," never just "server."

## Prefer the `/v1` paths

The `/v1/mcp-servers` and `/v1/virtual-servers` paths are canonical
([#4956](https://github.com/IBM/mcp-context-forge/issues/4956), shipped in
[#6257](https://github.com/IBM/mcp-context-forge/pull/6257)) and are what
`build_v1_router` mounts in `mcpgateway/api/v1/__init__.py`. Lead with them.

The unversioned `/gateways` and `/servers` paths are a deprecated compatibility shim
(`build_legacy_router`):

- Gated on `legacy_api_enabled` (default `true`).
- Excluded from the OpenAPI schema — the `/v1` routes are the documented source of
  truth.
- Carry RFC 8594 `Sunset` headers, defaulting to `Sat, 26 Sep 2026`.

[contextforge-web-ui#85](https://github.com/contextforge-org/contextforge-web-ui/issues/85)
tracks moving the React UI itself onto the `/v1` paths, which matters given that sunset
date — the UI currently calls the legacy paths directly.

## What already gets this right

The activity feed renders product terms correctly today. `_RESOURCE_LABELS` in
`mcpgateway/routers/log_search.py` translates wire-format `resource_type` values into
product language server-side, so a `gateway` audit row reaches the UI as "MCP server"
and a `server` row as "virtual server." Treat this as the model for how the two
vocabularies should reconcile elsewhere.

The remaining exposure of raw API terms is in request/response schemas, RBAC
permission strings, and raw audit/log fields — none of which are translated before
they reach a client.

## Status

The API vocabulary itself is unchanged for now. The full rename — schemas, permission
strings, audit `resource_type` values, config names like `GATEWAY_TEST_ALLOWED_HOSTS`,
and the underlying models/tables — is tracked separately in
[#6544](https://github.com/IBM/mcp-context-forge/issues/6544).
