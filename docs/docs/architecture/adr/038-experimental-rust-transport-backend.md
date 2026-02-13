# ADR-038: Experimental Rust Transport Backend (Streamable HTTP)

- *Status:* Proposed
- *Date:* 2025-12-26
- *Deciders:* Platform Team

## Context

The MCP Gateway currently implements its transport layer (stdio, SSE, WebSocket, and Streamable HTTP) in Python using asyncio. While this provides functional correctness, the transport layer experiences performance and memory limitations under higher concurrency due to Python runtime overhead and GIL constraints.

Issue #1621 proposes evaluating a Rust-based transport backend to improve throughput, latency, and resource efficiency while preserving the existing Transport API and protocol semantics.

Given the scope and risk of rewriting the full transport layer, an incremental and experimental approach is preferred, starting with the Streamable HTTP transport.

## Decision

We will introduce an **experimental Rust-based backend** for the **Streamable HTTP transport** with the following constraints:

- The existing Transport API and external behavior must remain unchanged.
- Protocol semantics must be preserved, including:

  - Streamable HTTP behavior
  - SSE keepalive and `session_id`
  - stdio newline-delimited JSON-RPC framing

- Tokio will be used as the async runtime.
- The Rust backend will be exposed to Python via PyO3/FFI, while retaining the existing Python implementation as a fallback.
- Performance will be benchmarked against the current Python implementation using `make load-test-ui` (Locust).

This Rust backend will initially support only Streamable HTTP. Expansion to other transports will be considered after validating performance assumptions and operational complexity.

### Phase Scope (Current Implementation)

**Phase 1** is intentionally limited to:

- Rust-based request context normalization for Streamable HTTP
- Rust-handled `OPTIONS` CORS preflight for `/mcp` paths
- Python fallback as the source of truth for regular Streamable HTTP request handling (`GET`/`POST`)

This means the runtime remains hybrid in this phase, and full Rust request handling semantics are deferred to later phases.

## Consequences

### Positive

- Potential improvements in throughput and latency under concurrent load.
- Reduced memory overhead via Rust's async IO and ownership model.
- Stronger guarantees around protocol framing and transport correctness.

### Negative

- Added complexity from Python–Rust FFI integration (PyO3).
- Increased debugging complexity in a multi-language stack.
- Experimental design may require multiple iterations or rewrites.
- Build complexity increases with native extension compilation.

Lessons learned from this implementation will be documented and used to guide future transport rewrites.

## Lessons Learned

### 1. Rust-Python Integration Requires Proper Build Workflow

Using `cargo build` alone is insufficient for Python integration.

Correct workflow:

``` bash
maturin develop --release
```

This ensures the compiled `.so` module is installed into the active
virtual environment and exports required symbols correctly.

If the compiled extension is not installed or symbols are unavailable at runtime,
the bridge **must** disable Rust handling and fall back to Python with an explicit warning.

------------------------------------------------------------------------

### 2. Explicit Fallback Logging Is Essential

Early integration attempts silently fell back to Python when bridge
symbols were missing.

Clear startup logging is necessary to: - Detect whether Rust transport
is actually active - Prevent false performance conclusions - Aid
debugging in CI and production environments

------------------------------------------------------------------------

### 3. Transport Layer May Not Be the Primary Bottleneck

Under moderate concurrency testing:

-   Rust and Python transport performance were statistically similar.
-   Application logic and database interactions likely dominate latency.

Transport optimization alone does not guarantee system-level performance
gains.

------------------------------------------------------------------------

### 4. Functional Parity Must Include Edge Cases

Basic JSON-RPC and streaming paths were validated.

However, deeper semantic validation should include:

-   Partial reads
-   Slow clients / backpressure
-   Disconnect handling
-   Invalid JSON input
-   Full SSE/session lifecycle validation

Parity validation must extend beyond happy-path testing.

------------------------------------------------------------------------

### 5. Architectural Value Beyond Immediate Performance

Even without immediate throughput improvements, this implementation
establishes:

-   A clean Rust integration boundary
-   Safe feature-flag rollout mechanism
-   Foundation for future transport migration
-   Reduced risk for incremental Rust adoption

This lowers long-term architectural risk while preserving stability.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Optimizing existing Python asyncio transports | Limited performance headroom due to GIL constraints |
| Full gateway rewrite in Rust | Out of scope and higher risk; significant operational complexity |
| Using Cython for hot paths | Moderate gains but still bound by Python runtime |
| Go-based transport layer | Different async model; less ecosystem alignment with MCP tooling |

**Status:** Experimental, safe, feature-flagged, and ready for iterative
refinement.

## References

- GitHub Issue #1621: Rewrite transport layer in Rust
- ADR-003: Expose Multi-Transport Endpoints
- [tokio channels](https://docs.rs/tokio/latest/tokio/sync/index.html)
- [pyo3-asyncio](https://docs.rs/pyo3-asyncio/latest/pyo3_asyncio/)
