# ADR-044: Module Communication Protocol

- *Status:* Proposed
- *Date:* 2026-03-15
- *Deciders:* Platform Team
- *Related:* [Modular Runtime Architecture](../modular-design.md), [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md)

## Context

The modular gateway architecture requires protocol modules (MCP, A2A, LLM,
REST/gRPC) to communicate with the core platform over a well-defined boundary.
That boundary must:

- Support modules written in any language (Python, Rust, Go).
- Handle both request/response and server-streaming patterns (e.g., catalog change subscriptions, SSE relay).
- Keep latency low enough that per-request overhead is negligible relative to upstream calls.
- Align with existing patterns in the codebase (the plugin framework already supports gRPC external runtimes).

## Decision

We adopt **gRPC over Unix Domain Socket** as the **target-state default**
module-to-core transport.

- It is language-neutral via protobuf code generation.
- It supports unary and streaming patterns cleanly.
- It fits host-local sidecar communication well.
- It aligns with the existing external plugin gRPC pattern already present in
  the codebase.

We also allow:

- **HTTP/JSON** as a fallback where a gRPC toolchain is undesirable
- **direct in-process calls** for embedded runtimes using the same conceptual
  contract

This is important because the currently implemented Rust MCP precedent still
uses trusted internal HTTP over UDS or loopback. That precedent remains valid
during migration, but it does not redefine the longer-term default boundary.

## Consequences

### Positive

- Single contract definition (protobuf) generates client/server stubs for Python, Rust, Go, and other languages.
- Streaming RPCs natively support catalog change subscriptions and session broadcast patterns.
- UDS avoids TCP overhead and keeps traffic host-local.
- Clean process boundary enables crash isolation and independent scaling of modules.

### Negative

- Adds a protobuf/gRPC toolchain dependency for module developers.
- Serialization overhead is higher than direct in-process calls.
- Module developers must handle connection lifecycle, deadlines, and
  backpressure.

### Neutral

- The SPI schemas must be versioned to allow independent evolution.
- Modules that only need request/response can use HTTP/JSON at the cost of a
  weaker streaming story.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Cap'n Proto** | Better zero-copy performance but significantly less language support and tooling. |
| **Flatbuffers** | No native streaming support; designed for serialization, not RPC. |
| **REST/JSON** | No streaming, higher overhead, no schema enforcement at compile time. |
| **Shared memory** | Too complex, limited to same-host deployment, no language-neutral schema. |
| **PyO3 / CGo (in-process FFI)** | Available as an optimization for embedded modules, but not suitable as the default boundary because it couples module lifecycle to the Python process. |

## References

- [Modular Runtime Architecture](../modular-design.md)
- `mcpgateway/plugins/framework/external/grpc/` — Existing gRPC external plugin runtime
