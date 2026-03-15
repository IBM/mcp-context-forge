# Rust MCP Follow-Ups

This file tracks issues discovered while validating the Rust MCP runtime that should be investigated or resolved in a separate PR, or after the core Rust MCP work is finished.

## Recommended Scope

These items are intentionally separated from the main Rust MCP runtime work because they are either:

- broader test-suite stability issues
- admin/UI problems not specific to the Rust MCP path
- brittle test assumptions that should be cleaned up independently

## Current Follow-Ups

### 1. Broader Python MCP error redaction

Status:
- Needs a separate Python-focused hardening pass

Observed behavior:
- The Rust runtime and Rust runtime proxy now redact client-visible transport
  errors, but broader Python MCP handlers still return some raw exception text.

Why this matters:
- Error-shaping parity is still incomplete outside the Rust-specific path.

Likely area:
- `mcpgateway/main.py`
- Python MCP handlers that still return `str(exc)` or equivalent error data

Recommended next step:
- Audit the remaining Python MCP handlers and replace client-visible exception
  text with generic transport-safe messages while keeping detailed logs
  server-side.

### 2. Python `session_id` query-parameter compatibility debt

Status:
- Intentionally not changed in this PR

Observed behavior:
- Both Python and Rust still accept `session_id` via query parameters for MCP
  transport compatibility.

Why this matters:
- This is security-sensitive compatibility debt because session identifiers can
  appear in browser history, reverse-proxy logs, and access logs.
- The current Rust MCP work deliberately documents this behavior instead of
  making a breaking Python change.

Likely area:
- `mcpgateway/main.py`
- `tools_rust/mcp_runtime/src/lib.rs`

Recommended next step:
- Decide whether to formally deprecate the query-parameter fallback, add
  explicit warnings/telemetry, and retire it in a separate compatibility
  cleanup.

### 3. Non-admin scoped `tools.execute` on `/servers/{id}/mcp`

Status:
- Important product/RBAC follow-up

Observed behavior:
- The new Rust access-matrix suite proves that server-scoped non-admin tokens
  can:
  - initialize a team-scoped MCP session
  - list tools, resources, and prompts
  - read resources and fetch prompts with correct data
- However, a non-admin token that explicitly includes `tools.execute` is still
  denied at `tools/call` on `/servers/{id}/mcp`.
- A scoped admin token with the same MCP permissions succeeds.

Why this matters:
- This is easy to misread as a transport bug because the token carries
  `tools.execute`, but the current live behavior still denies execution for the
  non-admin path.
- The new access-matrix coverage now documents and locks in this behavior, but
  the underlying product decision is still unresolved.

Likely area:
- RBAC / MCP permission evaluation for server-scoped execution
- Python auth/RBAC enforcement versus Rust transport parity

Recommended next step:
- Decide whether non-admin scoped tokens with `tools.execute` should be able to
  execute tools on `/servers/{id}/mcp`.
- If yes, change the product behavior and update the access-matrix tests to
  prove the positive path.
- If no, document this restriction more explicitly in the MCP/RBAC docs.

### 4. Python aggregated `/mcp` resource-read ambiguity

Status:
- Needs a Python/product behavior follow-up

Observed behavior:
- Server-scoped MCP resource reads now behave correctly for duplicate resource
  URIs because the lookup is scoped by `server_id`.
- On the plain Python aggregated `/mcp/` path, `resources/read` for a duplicate
  URI can still succeed with an empty payload instead of returning an explicit
  ambiguity error.
- On the Rust path, the same ambiguous generic `/mcp/` request now returns a
  clean client error instructing the caller to use `/servers/{id}/mcp`.

Why this matters:
- The benchmark and server-scoped MCP path are fixed, but Python and Rust still
  differ on how the generic aggregated endpoint handles ambiguous resource URIs.
- This is a product-behavior mismatch, not a core Rust MCP transport failure.

Likely area:
- `mcpgateway/services/resource_service.py`
- generic aggregated `/mcp/` `resources/read` behavior in the Python path

Recommended next step:
- Decide whether the generic aggregated Python `/mcp/` endpoint should match
  the Rust behavior by returning an explicit ambiguity error whenever multiple
  resources share the same URI across servers.

### 5. Playwright admin JWT login instability

Status:
- Needs investigation

Observed behavior:
- In larger Playwright file runs, the admin JWT-cookie login helper can intermittently remain on `/admin/login`.
- Gateway logs show matching `401 Invalid token` errors during some of these failures.

Why this matters:
- This affects admin/UI suite reliability.
- It is not currently proven to be a Rust MCP runtime issue.

Likely area:
- [`tests/playwright/conftest.py`](../../../tests/playwright/conftest.py)
- admin JWT cookie seeding / validation path
- admin auth middleware / login redirect handling

Recommended next step:
- Add targeted instrumentation around `_ensure_admin_logged_in(...)` and capture redirect/response traces when JWT-cookie login falls back to `/admin/login`.

### 5a. Prompt/plugin deny-path parity is still follow-up work

Status:
- Important compatibility follow-up, but no longer a prompt happy-path release
  blocker

Observed behavior:
- The compose testing stack enables the plugin framework with `PLUGINS_ENABLED=true`.
- However, the default [plugins/config.yaml](/home/cmihai/agents2/pr/mcp-context-forge/plugins/config.yaml) keeps built-in plugins such as `PIIFilterPlugin` in `mode: "disabled"`, so the current Rust MCP end-to-end battery does not exercise live plugin enforcement or transformation behavior.
- Manual spot checks with temporary plugin enablement showed:
  - `resource_post_fetch` parity for `resources/read` using `LicenseHeaderInjector`
  - `prompt_pre_fetch` is reached on Rust full mode using `DenyListPlugin`
- So the broad “Rust bypasses plugins” concern is not supported by current evidence.
- Python service implementations invoke plugin hooks for:
  - `tool_pre_invoke` / `tool_post_invoke`
  - `prompt_pre_fetch` / `prompt_post_fetch`
  - `resource_pre_fetch` / `resource_post_fetch`
- In Rust full mode, the direct fast paths in [lib.rs](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/src/lib.rs) serve several of those methods directly:
  - `direct_server_tools_list(...)`
  - `direct_server_resources_list(...)`
  - `direct_server_resource_templates_list(...)`
  - `direct_server_prompts_list(...)`
  - `direct_server_resources_read(...)`
  - `direct_server_prompts_get(...)`
  - `execute_tools_call_direct(...)`
  without an explicit plugin-aware fallback guard.

Why this matters:
- We now have a stable automated parity gate for:
  - `resources/read` + `LicenseHeaderInjector`
  - `tools/call` + `ToolOutputSentinelPlugin`
  - `prompts/get` + `PromptOutputSentinelPlugin`
- We also have a Rust-only regression guard that invalid prompt argument shapes
  return a structured MCP error instead of a Rust-side decode failure.
- The remaining prompt follow-up is the plugin deny-path, not the normal
  `prompts/get` happy path.

Likely area:
- [tool_service.py](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/tool_service.py)
- [prompt_service.py](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/prompt_service.py)
- [resource_service.py](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/resource_service.py)
- [lib.rs](/home/cmihai/agents2/pr/mcp-context-forge/tools_rust/mcp_runtime/src/lib.rs)

Recommended next step:
- Keep `make test-mcp-plugin-parity` green in both Python mode and Rust full mode using `tests/e2e/plugin_parity_config.yaml`.
- Follow-up gates:
  - blocked `prompts/get` parity after the Python-side prompt deny-path response shape is cleaned up
  - additional plugin families if Rust fast paths expand beyond the current resource/tool parity probes

### 6. Circuit breaker unit test timing flake

Status:
- Likely brittle test

Observed behavior:
- [`test_circuit_resets_after_timeout`](../../../tests/unit/mcpgateway/services/test_mcp_session_pool.py) failed in the full suite, but passed in isolation and repeated reruns.

Why this matters:
- Creates noise in `make test`.

Likely cause:
- Fixed `asyncio.sleep(...)` timing in the test versus wall-clock timing in the circuit-breaker implementation.

Recommended next step:
- Rewrite the test to poll until reset rather than relying on a fixed sleep margin.

### 7. Gateway delete Playwright assertion is too strict

Status:
- Likely brittle test

Observed behavior:
- [`test_delete_button_with_confirmation`](../../../tests/playwright/test_gateways.py) waits for a gateway row to exist after deletion.
- That fails if the deleted gateway was the last visible row.

Why this matters:
- Produces false negatives in the UI suite.

Recommended next step:
- Verify deletion by name or empty-state handling instead of requiring at least one remaining row.

### 8. Gateway edit modal file-scope instability

Status:
- Needs investigation

Observed behavior:
- [`test_edit_modal_transport_options`](../../../tests/playwright/entities/test_gateways_extended.py) can fail at file scope with the edit modal not opening, while passing in single-test isolation.

Why this matters:
- Suggests residual UI/file-state coupling.

Recommended next step:
- Reproduce on a fresh stack with focused instrumentation around modal open requests and Alpine/HTMX state changes.

### 9. Prompt/admin page file-scope login failures

Status:
- Needs investigation

Observed behavior:
- Some prompt/admin-oriented Playwright files fail at fixture setup because the admin page remains on `/admin/login`.

Why this matters:
- Same likely root as the admin JWT-cookie instability, but worth tracking explicitly because it impacts multiple UI areas.

Recommended next step:
- Treat as part of the admin login fixture investigation rather than fixing prompt-specific tests first.

### 10. `register_fast_time_sse` sync quirk

Status:
- Needs investigation

Observed behavior:
- On clean startup, `register_fast_time_sse` can still create its SSE virtual server with zero associated tools even though related tooling can later appear reachable.

Why this matters:
- Compose test ergonomics and fixture predictability.

Recommended next step:
- Inspect server sync timing and transport filtering on the SSE registration path separately from the `register_fast_time` auth/startup race that was already fixed.

### 11. `rpc_inner()` dispatch-table refactor

Status:
- Deferred maintainability refactor

Observed behavior:
- `rpc_inner()` still carries most of the runtime's method-selection complexity.
- Adding or changing a method still requires coordinated edits across boolean flag calculation, logging mode selection, and dispatch branches.

Why this matters:
- This is the largest remaining Rust-specific cognitive-complexity hotspot.

Recommended next step:
- Replace the current three-phase method dispatch with a single dispatch table or a more structured `match`-based handler map.

### 12. Generic `send_*_to_backend()` / `forward_*_to_backend()` consolidation

Status:
- Deferred maintainability refactor

Observed behavior:
- The runtime still has many nearly identical `send_*_to_backend()` and JSON-RPC-wrapping `forward_*_to_backend()` helpers.
- This PR reduced some duplication elsewhere, but did not collapse these method families.

Why this matters:
- The repetition increases change surface and makes response-shaping fixes harder to apply uniformly.

Recommended next step:
- Introduce generic backend send/forward helpers and migrate the method-specific wrappers onto them.

### 13. DB visibility/query preamble extraction

Status:
- Deferred maintainability refactor

Observed behavior:
- The direct DB query helpers still repeat the same pool acquisition, admin bypass, and team-scope preamble before table-specific SQL.

Why this matters:
- The logic is correct, but repetitive and easy to drift when visibility rules change.

Recommended next step:
- Extract the shared DB visibility/query setup into a reusable helper and keep only the table-specific SQL in each query function.

## Validated Remaining-Items Review

These notes capture the current status of the Rust-specific items from
`todo/remaining.md` after revalidation on the current branch.

### Already mitigated or not worth tracking further here

- Rust client-visible transport/dispatch/decode errors are already redacted through
  `backend_detail_error_response(...)`, `backend_jsonrpc_error_response(...)`,
  and targeted `CLIENT_ERROR_DETAIL` response shaping in
  `tools_rust/mcp_runtime/src/lib.rs`.
- Affinity-forwarded responses already flow through the same
  `should_forward_response_header(...)` allowlist used for other backend
  responses, so sensitive response headers like `set-cookie` and
  `authorization` are not reflected to clients.
- The protocol-version review finding is stale: the runtime currently checks
  for exact membership in `supported_protocol_versions()` rather than doing a
  lexicographic version comparison.
- The runtime crate now declares `rust-version = "1.85"` in
  `tools_rust/mcp_runtime/Cargo.toml`.

### Deferred Rust-specific follow-ups

#### 11. Redis affinity pub/sub trust model

Status:
- Deferred by design

Observed behavior:
- Affinity forwarding publishes request payloads to Redis channels and accepts
  the first response on the generated response channel without per-message
  authentication or signatures.

Why this matters:
- The current design assumes Redis stays on a trusted private network.
- If Redis trust assumptions change, the affinity control plane will need
  authentication or message signing.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- `forward_transport_request_via_affinity_owner(...)`

Recommended next step:
- Keep the current trusted-network assumption for now, but document it in any
  deployment guidance that places Redis outside a tightly controlled network.

#### 12. Explicit Rust request body size limit

Status:
- Deferred hardening

Observed behavior:
- The Rust runtime does not currently install an explicit body-size limit layer.

Why this matters:
- The runtime relies on default extractor behavior instead of a clear,
  centrally documented request-size ceiling.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- router construction for public and internal listeners

Recommended next step:
- Decide on a runtime-specific request-size limit and apply it explicitly at
  the Axum router layer.

#### 13. Session existence is distinguishable from session denial

Status:
- Deferred product/security tradeoff

Observed behavior:
- Missing sessions return `404 Session not found`.
- Existing sessions owned by another principal return `403 Session access denied`.

Why this matters:
- This can leak whether a guessed session id exists, even though the ids are
  high-entropy UUIDs and not realistically enumerable by brute force.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- `validate_runtime_session_request(...)`

Recommended next step:
- Decide whether parity with the current behavior is sufficient, or whether all
  deny paths should collapse to a single public error.

#### 14. Direct DB list/read pagination parity

Status:
- Deferred feature-parity work

Observed behavior:
- The Rust direct DB paths optimize common discovery/read flows, but they do
  not yet implement broader MCP pagination semantics the way a fully proxied
  backend path could.

Why this matters:
- This is a feature-parity/documentation gap rather than a correctness failure
  for the currently optimized hot paths.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- direct DB query helpers for tools/resources/prompts

Recommended next step:
- Either document the current pagination limitations clearly or extend the Rust
  direct DB paths to support paginated list results.

#### 15. Header helper cleanup and silent header insertion failures

Status:
- Deferred maintainability cleanup

Observed behavior:
- Header insertion and response decoration patterns still appear in many places.
- Some header insertions are best-effort and intentionally skip malformed
  values without logging.

Why this matters:
- The behavior is safe today, but the duplication makes future changes easier
  to get wrong and harder to audit.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`

Recommended next step:
- Extract small helper functions for repeated response-header decoration and
  decide where malformed-header skips should log warnings instead of silently
  continuing.

#### 16. Resume-path duplicate validation

Status:
- Deferred cleanup

Observed behavior:
- Resumable GET handling still re-derives some session/access validation that
  overlaps with the general transport validation flow.

Why this matters:
- This is mostly duplicated logic rather than a proven correctness bug.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- resumable GET `/mcp` flow

Recommended next step:
- Thread the validated session record through the resume path instead of
  reloading and rechecking it.

#### 17. Runtime modularization and low-priority Rust cleanup

Status:
- Deferred refactor

Observed behavior:
- `lib.rs` remains large and contains repeated URL derivation, backend bridge,
  and helper patterns.
- `query_param(...)` still returns raw values without percent-decoding.
- Some in-process cache keys still use `DefaultHasher`.
- Fingerprint comparisons are not constant-time.

Why this matters:
- These are maintainability and polish issues, not active correctness
  regressions in the Rust MCP path.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`

Recommended next step:
- Split transport/session/direct-execution code into modules, then clean up the
  lower-risk helper issues as part of that refactor.

#### 18. Shutdown cleanup

Status:
- Deferred lifecycle cleanup

Observed behavior:
- The Rust runtime does not currently do much explicit shutdown cleanup for its
  in-memory/runtime-owned resources.
- The Python proxy still caches a UDS `httpx.AsyncClient` without an explicit
  close hook.

Why this matters:
- This is mostly a lifecycle hygiene issue during process shutdown and restart,
  not a live-request correctness problem.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- `mcpgateway/transports/rust_mcp_runtime_proxy.py`

Recommended next step:
- Add explicit shutdown cleanup on the Rust side and a `close()`/shutdown hook
  for the Python proxy's cached UDS client in a separate follow-up.

#### 19. Session-auth reuse still trades freshness for fewer auth round-trips

Status:
- Deferred Rust-specific design follow-up

Observed behavior:
- The Rust runtime now has explicit revocation/membership/role-change coverage,
  but the implementation still relies on a bounded reuse TTL rather than
  immediate revocation signals.

Why this matters:
- This is the remaining architectural tradeoff in the fast auth-reuse path:
  fewer Rust -> Python auth round-trips versus immediate freshness after
  revocation.

Likely area:
- `tools_rust/mcp_runtime/src/lib.rs`
- session-auth reuse cache invalidation design

Recommended next step:
- Decide whether the current bounded TTL contract is enough, or whether Rust
  should consume a revocation/invalidation signal from Python to drop cached
  auth state immediately.

## Not In Scope Here

These items are not currently believed to be blocking the main Rust MCP runtime work:

- core MCP protocol parity
- Rust MCP session isolation correctness
- Rust MCP performance benchmarking

Those are tracked in:

- [`README.md`](./README.md)
- [`STATUS.md`](./STATUS.md)
- [`TESTING-DESIGN.md`](./TESTING-DESIGN.md)
