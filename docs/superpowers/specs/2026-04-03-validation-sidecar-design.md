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

### Flag Compatibility And Migration

The existing `experimental_rust_validation_middleware_enabled` flag controls the current PyO3 path. The sidecar redesign should not overload that flag.

Migration rules:

- `experimental_rust_validation_middleware_enabled` remains the legacy PyO3 flag during transition.
- `experimental_rust_validation_sidecar_enabled` is the new authoritative flag for the UDS sidecar.
- If both are disabled, the gateway uses Python mode.
- If the PyO3 flag is enabled and the sidecar flag is disabled, the gateway uses the legacy PyO3 path.
- If the sidecar flag is enabled, the gateway uses sidecar mode and it takes precedence over the PyO3 flag.

This keeps rollout explicit and allows benchmarks to compare Python, PyO3, and sidecar modes during transition without ambiguous behavior.

### Integration Contract With Existing Middleware Gates

The sidecar is not a separate activation path. It is a backend for the existing validation middleware.

Activation rules:

- `validation_middleware_enabled=false` means the middleware is not mounted, regardless of any Rust flags
- `experimental_validate_io=false` means body validation is effectively disabled, regardless of any Rust flags
- `validation_middleware_enabled=true` and `experimental_validate_io=true` are required before any body-validation backend is used
- once those gates are satisfied:
  - sidecar flag on => sidecar backend
  - sidecar flag off + PyO3 flag on => legacy PyO3 backend
  - both Rust flags off => Python backend

This keeps the existing middleware mount/enable semantics intact and swaps only the body-validation backend.

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

Behavioral parity requirements:

- max-length semantics must match current Python `len()` behavior on decoded Unicode strings, not UTF-8 byte length and not grapheme-cluster length
- only JSON string values are validated for length and dangerous-pattern matches
- non-string scalar leaves such as numbers, booleans, and null are ignored for these checks

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

Legacy artifact handling:

- the existing `tools_rust/validation_middleware_sidecar` crate remains the legacy PyO3 implementation during transition
- the new out-of-process binary lives in a separate crate, `tools_rust/validation_sidecar`
- benchmarks must target both artifacts during transition:
  - legacy PyO3 crate for the in-process Rust comparison
  - new `validation_sidecar` binary for the UDS sidecar comparison
- the implementation plan should treat retirement of the PyO3 crate as follow-up work, not part of the first sidecar delivery

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

Wire format:

| Field | Value |
| --- | --- |
| Length prefix | 4-byte unsigned integer |
| Byte order | big-endian |
| Payload | one JSON document per frame |
| Max raw request-body size | 1 MiB initially |
| Connection model | single-flight per connection |
| Multiplexing | none in v1 |

Python may maintain a small pool of persistent single-flight connections, but each individual connection handles one request at a time.

The 1 MiB limit applies to the raw request-body bytes before base64 encoding. The framed JSON envelope will be larger because of base64 expansion and envelope metadata.

### Request Envelope

Each request frame carries JSON with:

- request-body bytes encoded as base64 within the JSON envelope
- `max_param_length`
- `dangerous_patterns`
- optional parser selection for benchmark mode only
- optional request id for logging/tracing

Production sidecar mode should use one configured parser implementation, not per-request parser switching. Parser selection exists only for benchmark and development comparisons.

Although the transport uses length-prefixed binary framing, the frame payload itself is a JSON document. The request body must therefore be base64-encoded inside that JSON envelope to make the wire format deterministic.

Benchmark/dev parser selection should be exposed as an internal benchmark harness choice, not as a production request parameter.

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

### Regex Compatibility Rule

The sidecar must preserve current configured behavior for the repo's default dangerous-pattern set. Because Python `re` and Rust regex engines are not fully equivalent, the sidecar design should treat regex compatibility as explicit policy:

- the default dangerous-pattern set must remain sidecar-compatible
- sidecar mode is only supported for patterns accepted by the Rust regex engine used in the implementation
- incompatible patterns must be rejected during sidecar startup or configuration load, not deferred to first request
- startup/config incompatibility should surface as a sidecar-readiness failure and therefore map to `503` on affected requests while sidecar mode is enabled

The implementation plan must include parity coverage for the default patterns and explicit failure coverage for incompatible custom patterns.

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

### Strict Vs Warn-Only Behavior

When the sidecar returns a normal validation failure (`max_length`, `dangerous_pattern`, `max_depth`, `invalid_json`), the gateway should preserve the existing strict vs warn-only behavior:

- production or strict mode => return `422`
- development/staging with `validation_strict=false` => log and allow the request, consistent with current middleware behavior

Fail-closed sidecar behavior applies to sidecar transport/readiness failures, not to ordinary validation verdicts. A healthy sidecar returning a validation failure is still part of the normal validation path.

### HTTP Error Mapping

| Failure class | HTTP status | Behavior |
| --- | --- | --- |
| validation failure reported by sidecar | `422` | preserve existing validation-style error response |
| invalid JSON reported by sidecar | `422` | controlled request failure, not transport failure |
| sidecar unavailable | `503` | fail closed with sidecar-unavailable detail |
| sidecar timeout | `503` | fail closed with timeout detail |
| malformed sidecar response | `503` | fail closed with protocol error detail |
| sidecar startup/health failure in enabled mode | `503` on affected requests until resolved | operational failure, not validation failure |

The implementation plan should preserve existing `422` behavior for validation failures and reserve `503` for sidecar transport/readiness failures.

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

The benchmark remains a standalone performance script and should stay outside the default test run, similar to the current `tests/performance/` treatment.

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
- Health/readiness for the sidecar is defined as: socket reachable, framed request/response exchange succeeds, and the sidecar returns a valid protocol response.

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
