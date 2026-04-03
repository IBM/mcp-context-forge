# Validation Sidecar Design

**Date:** 2026-04-03

**Status:** Approved for planning

## Goal

Replace the current PyO3-based validation accelerator with a proper out-of-process Rust sidecar that validates JSON request bodies over a Unix domain socket, with the sidecar treated as authoritative whenever the feature flag is enabled.

## Scope

This design covers:

- gateway-side integration and configuration
- Rust sidecar process shape and transport protocol
- validation request/response contract
- failure behavior when sidecar mode is enabled
- benchmark and verification strategy for Python, PyO3, and sidecar paths

This design does not cover:

- replacing Python path/query validation with Rust
- adding HTTP transport for the sidecar
- auto-spawning or supervising the sidecar from Python
- dynamic parser auto-selection in production

## Constraints

- The sidecar must be optional and controlled by a feature flag.
- When sidecar mode is enabled, the sidecar is authoritative.
- There must be no fallback to in-process Python validation while sidecar mode is enabled.
- The sidecar must follow the repo's existing Rust sidecar pattern similarly to `tools_rust/mcp_runtime`, but optimized for local latency using Unix domain sockets only.
- The first implementation should optimize for performance first, not lowest implementation risk.

## Architecture

### Runtime Modes

The gateway will have two body-validation modes:

1. **Python mode**
   - Current behavior.
   - Used when the new sidecar flag is disabled.
   - JSON bodies are parsed and validated in the gateway process.

2. **Rust sidecar mode**
   - Enabled by a dedicated feature flag.
   - JSON bodies are sent to a Rust sidecar over UDS using length-prefixed framing.
   - The Rust sidecar parses and validates the request body from raw bytes.
   - If the sidecar is unavailable, unhealthy, times out, or returns an invalid response, the request fails closed.

### Ownership Boundary

Python continues to own:

- path parameter validation
- query parameter validation
- response sanitization
- mapping validation failures to `HTTPException`
- feature-flag and connectivity checks

The sidecar owns:

- request-body JSON parsing
- recursive body traversal
- max-length checks
- dangerous-pattern checks
- maximum nesting-depth enforcement

## Components

### 1. Gateway Adapter

Primary file:

- `mcpgateway/middleware/validation_middleware.py`

Responsibilities:

- add new config-driven sidecar path
- send raw request body bytes to the sidecar in sidecar mode
- decode framed sidecar responses
- map sidecar failures into existing HTTP validation behavior
- fail closed if the sidecar connection or response is invalid

### 2. Gateway Configuration

Primary file:

- `mcpgateway/config.py`

New settings:

- `experimental_rust_validation_sidecar_enabled: bool`
- `experimental_rust_validation_sidecar_uds: Optional[str]`
- `experimental_rust_validation_sidecar_timeout_seconds: int` or millisecond equivalent

Supporting surfaces:

- `.env.example`
- docs config schema artifacts
- Helm values and schema
- validation best-practices docs

### 3. Rust Validation Sidecar

New crate:

- `tools_rust/validation_sidecar`

Responsibilities:

- expose a long-lived binary
- listen on a Unix domain socket
- accept framed validation requests
- parse raw JSON body bytes
- validate data
- return compact structured responses

### 4. Benchmark Harness

Primary file:

- `tests/performance/test_validation_middleware_sidecar_benchmark.py`

Responsibilities:

- compare four modes:
  - Python in-process
  - current PyO3 bridge
  - UDS sidecar using `serde_json`
  - UDS sidecar using `simd-json`
- exercise the real middleware-adjacent path, not just raw internal helpers
- report apples-to-apples timings using stable ordering controls

## Protocol Design

### Transport

- Unix domain stream socket
- persistent connections
- length-prefixed framing

Rationale:

- lower overhead than localhost HTTP
- avoids delimiter scanning and escaping issues
- supports arbitrary payload sizes cleanly
- more production-ready than NDJSON for hot-path use

### Request Envelope

Each request frame carries JSON with:

- raw request-body bytes or body payload encoded for transport
- `max_param_length`
- `dangerous_patterns`
- optional parser selection for benchmark mode only
- optional request id for logging/tracing

Production sidecar mode should use one configured parser implementation, not per-request parser switching. Parser selection exists only for benchmark and development comparisons.

### Response Envelope

Success:

```json
{"ok": true}
```

Failure:

```json
{
  "ok": false,
  "key": "field_name_or_list_item",
  "error_type": "max_length|dangerous_pattern|max_depth|invalid_json",
  "detail": "human-readable detail"
}
```

Protocol failure:

- malformed frame
- decode error
- invalid sidecar response

These are treated by Python as sidecar transport failures and must fail the request when sidecar mode is enabled.

## Parser Strategy

### Production Default

- `simd-json`

Rationale:

- fastest-first matches the purpose of the redesign
- removing PyO3 only matters if the new path can materially outperform the current bridge on realistic payloads

### Comparison Backend

- `serde_json`

Rationale:

- provides a simpler comparison point
- helps separate "IPC overhead" from "parser choice"
- useful for debugging parser-specific compatibility or correctness differences

The implementation should support both for benchmarking, but production should default to `simd-json` unless compatibility testing proves otherwise.

## Data Flow

### Python Mode

1. Request enters middleware.
2. Path and query params are validated in Python.
3. JSON body is parsed and validated in Python.
4. Failures are mapped to existing `HTTPException` behavior.

### Sidecar Mode

1. Request enters middleware.
2. Path and query params are validated in Python.
3. Raw request body bytes are read.
4. Python sends a framed validation request to the sidecar over UDS.
5. Rust parses and validates the JSON body.
6. Rust returns success or structured validation failure.
7. Python maps returned failures into existing `HTTPException` behavior.
8. If the sidecar is unavailable or the protocol exchange fails, the request fails closed.

## Failure Handling

### Flag Off

- Current Python behavior remains unchanged.

### Flag On

- missing sidecar socket => fail request
- sidecar timeout => fail request
- malformed sidecar response => fail request
- sidecar health failure => fail request
- invalid JSON reported by sidecar => preserve controlled validation failure behavior

There is no fallback to Python validation in sidecar mode.

## Testing Strategy

### Unit Tests

Python:

- config and flag behavior
- sidecar unavailable behavior
- timeout behavior
- response mapping behavior

Rust:

- framing encode/decode
- parser parity on representative payloads
- list-item validation
- multibyte character length semantics
- max-depth handling

### Integration Tests

- gateway with sidecar disabled
- gateway with sidecar enabled and sidecar healthy
- gateway with sidecar enabled and sidecar unavailable
- parity checks between Python, PyO3, and sidecar for representative payloads

### Benchmarks

Must compare:

- Python validator
- PyO3 validator
- sidecar + `serde_json`
- sidecar + `simd-json`

Payload sets must include:

- nested safe payloads
- wide/deep payloads
- dangerous-string failures
- list-contained dangerous strings
- multibyte strings near max-length thresholds

## Operational Model

- Operators start the sidecar separately, similar in spirit to the Rust MCP runtime sidecar model.
- The gateway is configured with the UDS path and timeout.
- Enabling sidecar mode without a running sidecar is a configuration error that manifests as request failures.

This is intentional: sidecar mode is authoritative, not best-effort.

## Success Criteria

The redesign is successful when:

- PyO3 is no longer on the request-body validation hot path in sidecar mode
- sidecar mode is explicitly configurable and documented
- sidecar mode fails closed and never silently falls back
- parity holds on the current regression set
- benchmark results clearly compare Python, PyO3, `serde_json`, and `simd-json`
- `simd-json` sidecar is meaningfully better than PyO3 on at least medium/large realistic payloads, or else the benchmark makes the trade-off explicit

## Risks

- IPC overhead may erase wins for small payloads even with fast parsing.
- `simd-json` integration may impose input-buffer or mutability constraints that complicate the request path.
- Production operability becomes stricter because sidecar mode is fail-closed.
- Supporting both `serde_json` and `simd-json` can add maintenance cost if not cleanly isolated.

## Recommendation

Implement the UDS-only sidecar with length-prefixed framing, `simd-json` as the production default, `serde_json` as a benchmark comparison backend, and no fallback to Python when sidecar mode is enabled.
