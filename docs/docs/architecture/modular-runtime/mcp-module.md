# MCP Module Profile

This profile defines the proposed MCP module boundary and the invariants that
future implementations must preserve.

## Current Status

ContextForge serves MCP through the Python transport. The former Rust sidecar is
removed. See [ADR-058](../adr/058-remove-rust-runtime-and-workspace.md).
This profile describes a target contract, without an active Rust reference
implementation.

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

## Target-State Seam

The proposed core SPI uses gRPC over UDS. The removed sidecar used trusted
internal HTTP on some seams. Future modules must implement the target contract
and validate its security and protocol behavior.

## Required Invariants

Any future MCP module must preserve:

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

An MCP module requires protocol conformance and policy parity with the Python
transport before deployment.

That means:

- live stack-backed protocol tests
- deny-path and isolation tests
- plugin parity tests
- benchmark validation on the intended hot paths
