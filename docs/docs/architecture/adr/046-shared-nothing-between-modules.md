# ADR-046: Shared-Nothing Between Protocol Modules

- *Status:* Proposed
- *Date:* 2026-03-15
- *Deciders:* Platform Team
- *Related:* [Modular Runtime Architecture](../modular-design.md), [ADR-044](044-module-communication-protocol.md)

## Context

ContextForge supports multiple protocols (MCP, A2A, LLM, REST/gRPC) that sometimes need cross-protocol behavior:

- A2A agents are auto-registered as MCP tools.
- LLM chat integrates MCP tools via LangChain.
- REST/gRPC services can be exposed as MCP tools.

In the current monolithic architecture, this cross-protocol behavior happens via direct Python imports between services. In a modular architecture where modules may be written in different languages and run in separate processes, direct imports are not possible.

## Decision

**Modules cannot import or call each other directly.** All cross-protocol
behavior is mediated by the core platform through core-owned catalogs and
policy-aware routing.

Illustrative example:

1. an MCP module asks the core to invoke a tool
2. the core determines the owning integration type
3. the core routes to the appropriate protocol runtime
4. the result returns through the core to the original module

The exact dispatcher shape may evolve, but the architectural rule does not:
modules remain isolated from one another and the core performs the bridging.

## Consequences

### Positive

- Prevents language-specific coupling between modules (Rust MCP module doesn't import Python A2A code).
- Forces clean API boundaries — all cross-protocol contracts go through the Core SPI.
- Enables independent deployment and scaling of modules.
- Modules can be replaced independently (e.g., Go A2A module replaces Python A2A module) without affecting other modules.

### Negative

- Cross-protocol calls have additional latency (two IPC hops: module → core → module).
- The core becomes a bottleneck for cross-protocol traffic.
- Some operations that are currently a simple function call become multi-hop IPC chains.

### Neutral

- An event bus (future) can provide asynchronous cross-module communication for non-request-path operations (e.g., "agent registered" → "create tool entry").
- The `integration_type` field already exists on tools in the current schema, so the routing mechanism is a formalization of existing behavior.

## References

- [Modular Runtime Architecture](../modular-design.md)
- `mcpgateway/services/tool_service.py` — `_invoke_a2a_tool()` (current cross-protocol call)
