# Deprecations

This page is the registry of deprecated interfaces. Each row carries the
deprecation date, the earliest removal, the migration path, and the current
status.

Rows sort by deprecation date, then earliest removal. Rows without dates sort
last.

The lifecycle rules live in the
[deprecation policy](development/deprecation-policy.md).

## Pending deprecations

| Interface | Deprecated | Earliest removal | Migration | Status |
|---|---|---|---|---|
| Legacy MCP HTTP+SSE transport | 2025-03-26 | — | Streamable HTTP for new gateway registrations. | Spec-deprecated. The gateway compatibility path remains via the control plane. No removal date assigned. The dataplane publisher serves only `STREAMABLEHTTP` backends. |
| Rust MCP runtime sidecar | 2026-06-11 | 2026-07-07 | Python MCP transport. Leave `RUST_MCP_MODE=off` and `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=false`. | Past earliest removal. Code remains: `crates/mcp_runtime`, `RUST_MCP_MODE`, `EXPERIMENTAL_RUST_MCP_*`, `MCP_RUST_*`, and the transport proxies. Runtime responses carry `Deprecation` and `Sunset` headers. |
| Rust A2A runtime sidecar | 2026-06-11 | 2026-07-07 | Python A2A invocation path. | Past earliest removal. Code remains. The Python A2A protocol adapter is unaffected. |
| `ValidationMiddleware` | 2026-06-11 | 2026-07-07 | Endpoint-level Pydantic models, `SecurityValidator` helpers, and protocol-specific validation middleware. | Past earliest removal. The middleware remains, mounted when `VALIDATION_MIDDLEWARE_ENABLED=true`. Instantiation emits a `DeprecationWarning`. |
| Legacy unversioned API shim | 2026-06-26 | 2026-09-26 | The `/v1/*` routes. See [terminology](overview/terminology.md). | `legacy_api_enabled` still defaults to `true`. Tools, resources, prompts, teams, and tokens still call legacy paths internally. |
| Makefile formatting and container aliases | 2026-10-20 | 2027-01-18 | `make black CHECK=1`, `make isort CHECK=1`, `make ruff RUFF_MODE=...`, `make container-run ...`. | Pending. Covers `black-check`, `isort-check`, `ruff-check`, `ruff-fix`, `ruff-format`, and the 4 `container-run-*` aliases. Each call site states both dates. |
| Makefile alias `test-mcp-protocol-e2e` | 2026-10-20 | 2027-01-18 | `make test-e2e`. | Pending. |
| gRPC upstream services | 2026-10-20 | 2027-01-18 | None. | Experimental and disabled by default (`MCPGATEWAY_GRPC_ENABLED=false`). The admin routes, reflection discovery, and `grpc` install extra stop at removal. Runtime signals land with the code change. See [gRPC services](using/grpc-services.md). |
| WebSocket upstreams | 2026-10-20 | 2027-01-18 | Streamable HTTP or SSE registrations. | Covers `ws://` and `wss://` URLs and `transport=WEBSOCKET` in gateway and catalog registrations. The client-facing WebSocket endpoint is unaffected. See [catalog registration](manage/catalog.md). |
| Local observability data store | 2026-10-20 | 2027-01-18 | OTel export: `OTEL_ENABLE_OBSERVABILITY=true` and `OTEL_EXPORTER_OTLP_ENDPOINT`. See [OTel observability](architecture/observability-otel.md). | Covers the trace, span, and metric tables and the Admin UI views that read them. Dashboards lose their data source at removal. See [internal observability](manage/observability/internal-observability.md). |
| A2A v0.3 protocol support | — | — | A2A v1.0 wire format. | Gradual deprecation planned in a future release ([ADR 048](architecture/adr/048-a2a-v1-protocol-migration.md)). |
| Flat `_meta["ui/resourceUri"]` ingest key | — | Before MCP Apps GA | The nested `_meta.ui` object. | Ingest-only compatibility. The gateway rejects the flat value when both shapes are present. |
| `/toggle` endpoints | — | — | `/state`. | Emit `DeprecationWarning`. Covers servers, tools, resources, prompts, gateways, and A2A agents. |
| `rbac.get_db()` | — | — | `get_db()` from `main.py`, or `request.state.db`. | Emits `DeprecationWarning`. |
| `EmailAuthService.get_all_users()` | — | — | `list_users()` with pagination. | Emits `DeprecationWarning` and caps results at 10,000 users. |

The 2026-06-11 deprecations predate the policy. They used a 26-day window.

## Removed

| Interface | Removed | Notes |
|---|---|---|
| stdio wrapper (`mcpgateway/wrapper.py`, `crates/wrapper/`) | Next release | Removed without a deprecation window. Streamable HTTP clients connect to `/servers/<server_id>/mcp/` directly. stdio clients use the FastMCP bridge: `uvx fastmcp-remote <gateway-url>`. See [client configuration](using/clients/index.md). |

## Documentation gaps

- The `deprecated` lifecycle flag on tools (#4829) and LLM models has no
  user-facing documentation.
