# ADR-004: Experimental Rust Transport Backend (Streamable HTTP)

**Status**  
Proposed

---

## Context

The MCP Gateway currently implements its transport layer (stdio, SSE, WebSocket, and Streamable HTTP) in Python using asyncio. While this provides functional correctness, the transport layer experiences performance and memory limitations under higher concurrency due to Python runtime overhead and GIL constraints.

Issue #1621 proposes evaluating a Rust-based transport backend to improve throughput, latency, and resource efficiency while preserving the existing Transport API and protocol semantics.

Given the scope and risk of rewriting the full transport layer, an incremental and experimental approach is preferred, starting with the Streamable HTTP transport.

---

## Decision

We will introduce an **experimental Rust-based backend** for the **Streamable HTTP transport** with the following constraints:

- The existing Transport API and external behavior must remain unchanged.
- Protocol semantics must be preserved, including:
  - Streamable HTTP behavior
  - SSE keepalive and `session_id`
  - stdio newline-delimited JSON-RPC framing
- Tokio will be used as the async runtime.
- The Rust backend will be exposed to Python via FFI, while retaining the existing Python implementation as a fallback.
- Performance will be benchmarked against the current Python implementation using `make load-test-ui` (Locust).

This Rust backend will initially support only Streamable HTTP. Expansion to other transports will be considered after validating performance assumptions and operational complexity.

---

## Consequences

### Positive
- Potential improvements in throughput and latency under concurrent load.
- Reduced memory overhead via Rust’s async IO and ownership model.
- Stronger guarantees around protocol framing and transport correctness.

### Negative / Trade-offs
- Added complexity from Python–Rust FFI integration.
- Increased debugging complexity in a multi-language stack.
- Experimental design may require multiple iterations or rewrites.

Lessons learned from this implementation will be documented and used to guide future transport rewrites.

---

## Alternatives Considered

- **Optimizing the existing Python asyncio transports:** limited performance headroom.
- **Full gateway rewrite in Rust:** out of scope and higher risk.
