# Deprecations

This page is the registry of deprecated interfaces. Use it to find the
lifecycle rules, the migration path for each deprecation, and the removal
status of every open item.

## Lifecycle

ContextForge follows the [MCP feature lifecycle](https://modelcontextprotocol.io/community/feature-lifecycle),
adapted to repository governance. Pull requests replace SEPs, releases replace
specification revisions, and maintainers replace Core Maintainers.

The lifecycle covers public interfaces: HTTP APIs, environment variables and
their defaults, database schema, Helm values, and MCP or A2A wire behavior.

An interface is in exactly 1 of 3 states.

| State | Meaning | Expectation |
|---|---|---|
| **Active** | Supported without restriction. | Use freely. |
| **Deprecated** | Scheduled for removal. The entry documents the migration path. | Do not adopt in new code. Migrate before earliest removal. |
| **Removed** | Deleted from the codebase. Documented in prior CHANGELOG entries. | Do not depend on it. |

A Deprecated interface may return to Active. The superseding change must
record the new circumstances. A second deprecation restarts the removal
window.

### Deprecating an interface

Deprecation requires a pull request that updates this registry and the
CHANGELOG. The PR must:

1. Identify the interface by name. Link to its definition.
2. State the rationale. The accepted reasons are:
   - A replacement covers the same use cases.
   - The interface carries a security, privacy, or interoperability risk
     without an in-place mitigation.
   - Adoption is negligible relative to maintenance cost.
3. Document the migration path, or state that none is required. A named
   replacement must be Active.
4. Set the removal window and the earliest removal date or version.

Deprecations of MCP or A2A wire behavior also require an ADR. The ADR is the
SEP equivalent for protocol-facing surfaces.

When the PR merges, the interface gains its runtime signals. It becomes
Deprecated when the **first release** carrying those signals ships. Measure
the removal window from that release, not from the merge date.

### Windows

- Allow at least 12 months for interfaces that mirror the MCP specification.
  Track the MCP [deprecated-feature registry](https://modelcontextprotocol.io/specification/draft/deprecated) for mirrored features.
- Allow at least 90 days for other public interfaces. The default
  `LEGACY_API_SUNSET_DATE` follows this rule.
- Shorten a window only for an active security risk: a published advisory or
  documented exploitation without an in-place mitigation. An expedited removal
  still requires 90 days between deprecation and removal. Record the
  maintainer approval in this registry.
- An interface may remain Deprecated past its earliest removal. Maintainers
  decide when to remove it.

### Signals

| Surface | Signal | Source |
|---|---|---|
| HTTP responses | `Deprecation`, `Sunset` (RFC 8594), `Link ...; rel="deprecation"` headers | `DeprecationHeadersMiddleware` |
| Legacy unversioned routes | `X-Deprecated-Endpoint` advisory header | `DeprecationHeadersMiddleware` |
| Python | `DeprecationWarning` on use | Per call site |
| Startup | Log warning when a deprecated path is enabled | `main.py` |
| Makefile targets | Warning naming the replacement and removal version | `deprecated_target` macro |

Shared dates and header values live in `mcpgateway/deprecations.py`. The
middleware logs an overdue warning at startup once the sunset date passes.

### Removing an interface

- Remove the interface by pull request after its earliest removal date or
  version.
- Record the removal in the CHANGELOG under the `Removed` heading.
- Update the registry entry to the Removed state.
- Extend, shorten, or restore a timeline only through the same approval path
  as the original deprecation.

### Registry and CHANGELOG conventions

- Each registry entry carries the deprecation reference, the release that
  deprecated it, the migration path, and the earliest removal.
- CHANGELOG entries use the standing headings `Deprecated` and `Removed`.

!!! warning "Deprecated as of 2026-06-11; sunsets on 2026-07-07"
    The Rust MCP runtime sidecar, Rust A2A runtime sidecar, and
    `ValidationMiddleware` are deprecated. They remain available for existing
    deployments, but new deployments should use the default Python runtime
    paths and endpoint-level validation. They are scheduled for sunset on
    2026-07-07.

## Rust MCP runtime sidecar

Deprecated controls include `RUST_MCP_MODE`, `EXPERIMENTAL_RUST_MCP_*`, and
`MCP_RUST_*` settings that enable or configure the Rust MCP sidecar.

Use the default Python MCP transport path by leaving `RUST_MCP_MODE=off` and
`EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=false`.

Runtime signals:

- Gateway startup logs include a deprecation warning when the Rust MCP runtime
  path is enabled.
- Rust MCP runtime responses include `Deprecation`, `Sunset`, and
  `Link: <...>; rel="deprecation"` headers.

## ValidationMiddleware

`mcpgateway.middleware.validation_middleware.ValidationMiddleware` is
deprecated.

Use endpoint-level Pydantic models, the existing `SecurityValidator` helpers,
and protocol-specific validation middleware instead. Leave
`VALIDATION_MIDDLEWARE_ENABLED=false` unless you need compatibility with an
existing deployment that already depends on this middleware.

Runtime signals:

- Gateway startup logs include a deprecation warning when the middleware is
  enabled.
- Instantiating the middleware emits a Python `DeprecationWarning`.

## Legacy MCP HTTP+SSE transport

The MCP specification deprecated the legacy two-endpoint HTTP+SSE transport in
protocol version 2025-03-26 in favor of Streamable HTTP. This is distinct from
SSE response streams within Streamable HTTP and from the 2026-07-07 ContextForge
component sunset above. ContextForge has not assigned a removal date to its SSE
gateway compatibility path, which remains available through the control plane.

Use Streamable HTTP for new gateway registrations. The experimental dataplane
publisher (`DATAPLANE_PUBLISHER`) publishes only `STREAMABLEHTTP` gateway
backends. If filtering leaves a virtual server with no publishable backends, the
publisher omits that virtual host so a split deployment can use the dataplane's
404 response to fall back to the control plane.

See the MCP [deprecated-feature registry](https://modelcontextprotocol.io/specification/draft/deprecated)
and [transport guidance](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http).

## Backlog

Open deprecations and their removal status, as of 2026-09-25. Entries stay
Deprecated until maintainers remove the code. The 2026-06-11 deprecations
predate this policy. They used a 26-day window.

### Past earliest removal

| Item | Earliest removal | Status |
|---|---|---|
| Rust MCP runtime sidecar | 2026-07-07 | Code remains in the tree: `crates/mcp_runtime`, `RUST_MCP_MODE`, and the Rust transport proxies. |
| Rust A2A runtime sidecar | 2026-07-07 | Code remains. The Python A2A protocol adapter is unaffected. |
| `ValidationMiddleware` | 2026-07-07 | Middleware remains, mounted when `VALIDATION_MIDDLEWARE_ENABLED=true`. |

### Earliest removal approaching

| Item | Earliest removal | Status |
|---|---|---|
| Legacy unversioned API shim | 2026-09-26 | Default `LEGACY_API_SUNSET_DATE`. `legacy_api_enabled` still defaults to `true`. Tools, resources, prompts, teams, and tokens still call legacy paths internally. See [terminology](overview/terminology.md). |

### Makefile aliases

Deprecated as of 2026-09-30. They sunset on 2026-12-29. Each Makefile call
site states both dates.

| Item | Earliest removal | Status |
|---|---|---|
| Makefile aliases `black-check`, `isort-check`, `ruff-check`, `ruff-fix`, `ruff-format`, `container-run-host`, `container-run-ssl`, `container-run-ssl-host`, `container-run-ssl-jwt` | 2026-12-29 | Pending. |
| Makefile alias `test-mcp-protocol-e2e` | 2026-12-29 | Pending. |

### No sunset date assigned

| Item | Status |
|---|---|
| Legacy MCP HTTP+SSE transport | Spec-deprecated 2025-03-26. The gateway compatibility path has no removal date. |
| A2A v0.3 protocol support | ContextForge will deprecate it gradually in a future release ([ADR 048](architecture/adr/048-a2a-v1-protocol-migration.md)). |
| Flat `_meta["ui/resourceUri"]` ingest key | The MCP Apps spec removes this key before GA. Ingest-only compatibility path. |
| `/toggle` endpoints | Emit `DeprecationWarning`. The replacement is `/state`. Affects servers, tools, resources, prompts, gateways, and A2A agents. |
| `rbac.get_db()` | Emits `DeprecationWarning`. Use `get_db()` from `main.py` or `request.state.db`. |
| `EmailAuthService.get_all_users()` | Emits `DeprecationWarning` and caps results at 10,000 users. Use `list_users()` with pagination. |

### Documentation gaps

- The `deprecated` lifecycle flag on tools (#4829) and LLM models has no
  user-facing documentation.
