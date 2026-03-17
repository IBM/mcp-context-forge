# REST/gRPC Module Profile

This profile defines how a future REST or gRPC module should map onto the
current virtualized service surfaces.

## Current Surface

Today ContextForge can:

- expose REST-backed tools and virtual servers
- register and manage gRPC services
- use OpenAPI import or reflection-style discovery to create gateway-managed
  records

This is still largely core-owned today.

That means a future REST/gRPC module is more likely to be a runtime extraction
than a greenfield subsystem. The registration and governance model already
exists in the core.

## What the REST/gRPC Module Owns

A future REST/gRPC module should own:

- protocol-specific outbound transport behavior
- reflection or discovery runtime behavior where enabled
- protocol-specific request and response normalization
- streaming semantics where the underlying protocol supports them
- runtime metrics, health, and deadlines

## What Stays in Core

The core should continue to own:

- service registration and persistence
- visibility, ownership, and governance policy
- generated tool, prompt, or resource catalog records
- auth, RBAC, and token scoping
- secret storage and TLS material governance
- cross-protocol exposure into MCP or other front-door protocols

In other words, the module owns protocol behavior, not the registry of record.

## Required SPI Usage

At minimum, a REST/gRPC module will usually require:

- `AuthPolicyService`
- `CatalogService`
- `ObservabilityService`
- `ConfigSecretsService`
- optionally `PluginService` if response mutation or policy hooks are required

## Conformance Additions

A REST/gRPC module should additionally prove:

- SSRF and target-validation rules remain enforced
- TLS and metadata handling preserve the current trust model
- reflection or OpenAPI-derived surfaces do not bypass core visibility or
  ownership rules
- virtualized service behavior remains consistent when surfaced through MCP or
  another protocol
