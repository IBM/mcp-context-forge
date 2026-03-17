# A2A Module Profile

This profile defines how a future A2A module should map onto the current
ContextForge A2A surface.

## Current Surface

Today the A2A HTTP surface is embedded in `main.py` and uses the core service
layer directly.

Current live endpoints include:

- `GET /a2a` and `GET /a2a/` for list
- `GET /a2a/{agent_id}` for fetch
- `POST /a2a/{agent_name}/invoke` for invoke

CRUD endpoints also exist today, but they are core-owned admin operations and
should remain there in the modular design.

The persisted A2A record already contains the fields a module will depend on:

- endpoint URL
- protocol version
- capability or config metadata
- auth configuration
- team, owner, and visibility
- associated MCP tool linkage where the agent is exposed cross-protocol

## What the A2A Module Owns

The module should own:

- A2A request parsing and response serialization
- protocol-specific discovery and read surface for agents
- invoke envelope construction and normalization
- outbound A2A transport behavior to target agents
- protocol-specific retries, timeouts, and future streaming or push behavior
- task or runtime state handling where A2A requires it
- protocol-specific metrics and runtime health

## What Stays in Core

The core should continue to own:

- agent CRUD and persistence
- auth and token normalization
- RBAC and visibility filtering
- encrypted auth and OAuth secret storage
- ownership and mutation checks
- cross-protocol exposure of A2A agents as MCP tools

That last point is important: if an A2A agent is exposed as an MCP tool, the
core still mediates that cross-protocol bridge.

## Required Policy Semantics

The A2A module must preserve current product semantics:

- token scoping remains separate from RBAC
- public-only tokens can only see public records
- team visibility uses normalized token team state
- admin bypass semantics come from the core, not from local JWT parsing
- hidden or inaccessible agents may intentionally use not-found semantics
- feature-flagged query-parameter auth remains a core-governed exception, not a
  module-defined bypass

## Required SPI Usage

At minimum, an A2A module needs:

- `AuthPolicyService`
- `CatalogService` for agent discovery and invoke
- `PluginService` for any parity-sensitive A2A hooks
- `ObservabilityService`
- `ConfigSecretsService` for module-scoped transport or timeout settings

## Conformance Additions

An A2A module should additionally prove:

- invoke deny paths for wrong team, wrong owner, and public-only tokens
- correct handling of agent visibility modes
- correct propagation of outbound auth without exposing stored secrets
- correct cross-protocol behavior when an A2A agent is invoked through the MCP
  tool bridge
