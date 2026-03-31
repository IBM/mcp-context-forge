# MCP Module Profile

This profile maps the implemented Rust MCP module onto the modular runtime
specification and defines what future MCP implementations should preserve.

## Current Status

MCP is the first implemented protocol module in ContextForge.

The current implementation is the
[Rust MCP Runtime](../rust-mcp-runtime.md), which already proves:

- sidecar deployment
- direct public ingress in `edge` and `full` mode
- core-owned auth, token scoping, and RBAC
- plugin parity on validated flows
- rollback through mode-based rollout

## What the MCP Module Owns

The MCP module owns:

- MCP wire parsing and serialization
- transport behavior for streamable HTTP and related protocol edge behavior
- session lifecycle and capability negotiation
- replay, resume, and live-stream runtime behavior where enabled
- protocol-specific upstream MCP client behavior
- protocol-specific health and stats

## What Stays in Core

The core continues to own:

- authentication and token normalization
- RBAC and visibility filtering
- core-owned catalogs for tools, resources, prompts, servers, and gateways
- plugin configuration and policy
- admin UI and platform observability
- cross-protocol mediation

## Current Implemented Seam vs Target-State Seam

The current Rust MCP module is the reference implementation, but it is still a
transition architecture in one important respect:

- implemented today:
  - trusted internal HTTP over UDS or loopback on some seams
- target-state default:
  - gRPC over UDS for the core SPI

That difference is acceptable. The current module proves the boundary; the
target-state SPI documents how future modules should converge.

## Required Invariants

Any MCP module, including the existing Rust one, must preserve:

- core-owned auth and RBAC authority
- session ownership and isolation
- plugin parity on plugin-sensitive flows
- rollback and degraded-mode safety
- no direct module-to-module calls for cross-protocol behavior

## Required SPI Usage

An MCP module requires:

- `AuthPolicyService`
- `CatalogService`
- `PluginService`
- `SessionEventService`
- `ObservabilityService`
- `ConfigSecretsService`

## Release Expectations

An MCP module should be held to the strongest conformance bar because it is the
first extracted runtime and the precedent for later modules.

That means:

- live stack-backed protocol tests
- deny-path and isolation tests
- plugin parity tests
- benchmark validation on the intended hot paths
