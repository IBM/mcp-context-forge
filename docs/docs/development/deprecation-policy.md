# Deprecation policy

This page defines the deprecation lifecycle for ContextForge public
interfaces. The registry of deprecated interfaces lives in
[Deprecations](../deprecations.md).

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

## Deprecating an interface

Deprecation requires a pull request that updates the registry and the
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

## Windows

- Allow at least 12 months for interfaces that mirror the MCP specification.
  Track the MCP [deprecated-feature registry](https://modelcontextprotocol.io/specification/draft/deprecated) for mirrored features.
- Allow at least 90 days for other public interfaces. The default
  `LEGACY_API_SUNSET_DATE` follows this rule.
- Shorten a window only for an active security risk: a published advisory or
  documented exploitation without an in-place mitigation. An expedited removal
  still requires 90 days between deprecation and removal. Record the
  maintainer approval in the registry.
- An interface may remain Deprecated past its earliest removal. Maintainers
  decide when to remove it.

## Signals

| Surface | Signal | Source |
|---|---|---|
| HTTP responses | `Deprecation`, `Sunset` (RFC 8594), `Link ...; rel="deprecation"` headers | `DeprecationHeadersMiddleware` |
| Legacy unversioned routes | `X-Deprecated-Endpoint` advisory header | `DeprecationHeadersMiddleware` |
| Python | `DeprecationWarning` on use | Per call site |
| Startup | Log warning when a deprecated path is enabled | `main.py` |
| Makefile targets | Warning naming the replacement and sunset date | `deprecated_target` macro |

Shared dates and header values live in `mcpgateway/deprecations.py`. The
middleware logs an overdue warning at startup once the sunset date passes.

## Removing an interface

- Remove the interface by pull request after its earliest removal date or
  version.
- Record the removal in the CHANGELOG under the `Removed` heading.
- Update the registry entry to the Removed state.
- Extend, shorten, or restore a timeline only through the same approval path
  as the original deprecation.

## Registry and CHANGELOG conventions

- Each registry row carries the interface, the deprecation date, the earliest
  removal, the migration path, and the status.
- CHANGELOG entries use the standing headings `Deprecated` and `Removed`.
