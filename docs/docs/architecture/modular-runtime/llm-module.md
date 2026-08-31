# LLM Module Profile

This profile defines how a future LLM proxy or chat module should map onto the
current ContextForge LLM surfaces.

## Current Surface

Today there are two main LLM-facing surfaces:

- **OpenAI-compatible proxy**
  - `POST /chat/completions`
  - `GET /models`
- **Session-oriented chat**
  - `/llmchat/connect`
  - `/llmchat/chat`
  - `/llmchat/disconnect`
  - `/llmchat/status/{user_id}`
  - `/llmchat/config/{user_id}`
  - `/llmchat/gateway/models`

Those surfaces are currently implemented through Python routers and services.

The important split is that ContextForge already has both:

- a direct OpenAI-compatible proxy surface
- a higher-level chat surface that coordinates models, servers, and session
  state

## What the LLM Module Owns

A future LLM module should own:

- request parsing for OpenAI-compatible and session-style chat surfaces
- streaming transport behavior
- provider relay runtime behavior
- chat-session orchestration and protocol-local session state
- provider-specific retries, deadlines, and streaming normalization
- protocol-local metrics and runtime health

## What Stays in Core

The core should continue to own:

- provider and model registry CRUD
- provider credentials and secret handling
- auth, RBAC, and token-scope policy
- model visibility and governance
- prompt, tool, and resource catalogs
- plugin policy
- admin UI and provider-management workflows
- any shared governance around which virtual servers or model records are
  exposed to which callers

## Required SPI Usage

A future LLM module will typically require:

- `AuthPolicyService`
- `CatalogService` for model lookup and MCP-facing resource access
- `PluginService` where chat or provider flows become plugin-sensitive
- `ObservabilityService`
- `ConfigSecretsService`
- `SessionEventService` if shared chat-session semantics are extracted

## Cross-Protocol Constraint

If the LLM module can call MCP tools or prompts, it must not call another
module directly. The core still decides:

- what catalog entry is being invoked
- what protocol owns it
- what policy and plugin rules apply

## Conformance Additions

An LLM module should additionally prove:

- non-streaming and streaming parity
- model visibility and deny paths
- provider-auth failure handling without leaking sensitive details
- correct cross-protocol invocation when chat flows reach MCP-backed tools or
  prompts
