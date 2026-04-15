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

### 1a. JSON-RPC plugin violations can still surface non-200 HTTP statuses

Status:
- Deferred Python/MCP protocol-shaping follow-up

Observed behavior:
- The global `PluginViolationError` handler now derives HTTP status from plugin
  metadata / violation-code mappings instead of always returning HTTP `200`.
- That is fine for generic REST endpoints, but it is awkward for JSON-RPC /
  MCP clients that expect HTTP `200` and parse the body-level `error` object.

Why this matters:
- A plugin deny path on MCP/JSON-RPC can look like a transport failure instead
  of a protocol-level error, depending on the client.

Likely area:
- `mcpgateway/main.py`
- global plugin violation exception handling for MCP / JSON-RPC routes

Recommended next step:
- Decide whether MCP / JSON-RPC routes should force HTTP `200` for plugin
  violations while keeping richer HTTP statuses for REST endpoints.

### 1b. Prompt post-hook payload still uses `prompt_id` for a prompt name

Status:
- Deferred Python/plugin contract follow-up

Observed behavior:
- `PromptPosthookPayload.prompt_id` is populated with the MCP prompt name rather
  than the backing database UUID.

Why this matters:
- MCP prompt identity is name-based, so the current behavior may be intentional,
  but the field name and plugin-facing semantics are now misleading.
- Existing or future plugins that treat `prompt_id` as a database UUID could
  break silently.

Likely area:
- `mcpgateway/services/prompt_service.py`
- plugin payload schema / docs for prompt post-fetch hooks

Recommended next step:
- Decide whether to rename the field to reflect MCP name semantics, or restore a
  true UUID field and add a separate prompt-name field for MCP-oriented plugins.

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
- `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Decide whether to formally deprecate the query-parameter fallback, add
  explicit warnings/telemetry, and retire it in a separate compatibility
  cleanup.

### 2a. Client-supplied initialize session ids remain a shared Python/Rust compatibility behavior

Status:
- Deferred product/security semantics follow-up

Observed behavior:
- Both Python and Rust currently accept client-supplied initialize session ids:
  - Python `_execute_rpc_initialize(...)` accepts `session_id` / `sessionId`
    from JSON-RPC params plus `session_id` from the query string.
  - Rust `requested_initialize_session_id(...)` accepts the same logical
    inputs, with the transport header taking precedence when present.
- This is not a Rust-only behavior introduced by this PR.
- On the settled auth-required full-Rust stack, an authenticated second caller
  could not hijack another caller's chosen initialize session id:
  - the first caller initialized successfully
  - the second caller targeting the same id received JSON-RPC `-32003 Access denied`
- The remaining concern is the permissive/public MCP mode:
  - ownerless sessions are intentionally allowed today
  - custom client-chosen session ids are not constrained to UUID format
  - that combination makes public/unauthenticated session semantics easier to
    reason about incorrectly

Why this matters:
- Predictable client-chosen initialize session ids are more sensitive than
  server-emitted opaque ids.
- The behavior is currently a shared MCP transport compatibility choice rather
  than a newly introduced Rust regression.

Likely area:
- `mcpgateway/main.py`
- `mcpgateway/cache/session_registry.py`
- `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Decide whether client-supplied initialize session ids should remain a
  supported compatibility feature.
- If yes:
  - document the authenticated vs unauthenticated semantics explicitly
  - add validation/telemetry for custom initialize session ids
- If no:
  - deprecate and remove the behavior in a coordinated Python + Rust change
    rather than changing only one side in the Rust PR.

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

### 3a. Rust direct tools/call can share upstream MCP sessions when no downstream session exists

Status:
- Deferred Rust-specific correctness/isolation follow-up

Observed behavior:
- `build_upstream_session_key()` uses `shared:{hash}` when `tools/call` runs
  without a downstream MCP session id.
- That means multiple callers that resolve to the same upstream target and auth
  plan can reuse a single upstream MCP session.

Why this matters:
- Stateful upstream MCP servers can leak state or cross-contaminate behavior
  between otherwise unrelated callers on the sessionless direct-execution path.

Likely area:
- `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Decide whether sessionless callers should:
  - never reuse upstream sessions, or
  - use a caller-specific key that still isolates upstream state between users.

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
- However, the default [plugins/config.yaml](../../plugins/config.yaml) keeps built-in plugins such as `PIIFilterPlugin` in `mode: "disabled"`, so the current Rust MCP end-to-end battery does not exercise live plugin enforcement or transformation behavior.
- Manual spot checks with temporary plugin enablement showed:
  - `resource_post_fetch` parity for `resources/read` using `LicenseHeaderInjector`
  - `prompt_pre_fetch` is reached on Rust full mode using `DenyListPlugin`
- So the broad "Rust bypasses plugins" concern is not supported by current evidence.
- Python service implementations invoke plugin hooks for:
  - `tool_pre_invoke` / `tool_post_invoke`
  - `prompt_pre_fetch` / `prompt_post_fetch`
  - `resource_pre_fetch` / `resource_post_fetch`
- In Rust full mode, the direct fast paths in [lib.rs](src/lib.rs) serve several of those methods directly:
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
- [tool_service.py](../../mcpgateway/services/tool_service.py)
- [prompt_service.py](../../mcpgateway/services/prompt_service.py)
- [resource_service.py](../../mcpgateway/services/resource_service.py)
- [lib.rs](src/lib.rs)

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

### 11. Remaining Rust runtime test-hardening lanes from `todo/test-improvement.md`

Status:
- Deferred on purpose from this PR

What is already covered now:
- SSE parser helper edge cases in Rust unit tests
- representative specialized-endpoint success/error JSON-RPC envelope coverage
- explicit `elicitation/create` forwarded-path coverage
- direct `tools/call` upstream-session retry after cached-session failure

Still deferred:
- concurrent direct `tools/call` contention on the shared upstream-session key
- direct public-listener end-to-end coverage against the real Python auth backend
- full resumable GET lifecycle in one end-to-end flow
- multi-worker isolation/load against 2+ Rust runtime instances behind nginx

Why this matters:
- These are still useful confidence layers, but they are either timing-sensitive
  or require broader compose/test-infra changes that would widen this PR.

Recommended next step:
- Take these as the next Rust-runtime test-focused PR once the current branch is
  merged or otherwise stabilized.

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
  `crates/mcp_runtime/src/lib.rs`.
- Affinity-forwarded responses already flow through the same
  `should_forward_response_header(...)` allowlist used for other backend
  responses, so sensitive response headers like `set-cookie` and
  `authorization` are not reflected to clients.
- The protocol-version review finding is stale: the runtime currently checks
  for exact membership in `supported_protocol_versions()` rather than doing a
  lexicographic version comparison.
- The runtime crate now declares `rust-version = "1.85"` in
  `crates/mcp_runtime/Cargo.toml`.

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
- `crates/mcp_runtime/src/lib.rs`
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
- `crates/mcp_runtime/src/lib.rs`
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
- `crates/mcp_runtime/src/lib.rs`
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
- `crates/mcp_runtime/src/lib.rs`
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
- `crates/mcp_runtime/src/lib.rs`

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
- `crates/mcp_runtime/src/lib.rs`
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
- `crates/mcp_runtime/src/lib.rs`

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
- `crates/mcp_runtime/src/lib.rs`
- `mcpgateway/transports/rust_mcp_runtime_proxy.py`

Recommended next step:
- Add explicit shutdown cleanup on the Rust side and a `close()`/shutdown hook
  for the Python proxy's cached UDS client in a separate follow-up.

#### 19. Redis hot-path round-trip and cache single-flight polish

Status:
- Deferred performance polish

Observed behavior:
- Runtime-session refresh in Redis still uses `GET` followed by `EXPIRE`
  instead of a single `GETEX`-style refresh.
- Event-store replay still fetches replay payloads one entry at a time from
  the Redis hash instead of batching those lookups.
- A few in-process caches still use simple double-checked locking rather than
  a stronger single-flight pattern, so duplicate initialization work is still
  possible under contention.

Why this matters:
- These are performance and efficiency opportunities, not current correctness
  regressions.
- They are most visible under heavy load or when many workers race to populate
  the same hot cache entries.

Likely area:
- `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Revisit the Redis/runtime hot paths in a focused performance pass and assess:
  - `GETEX` or equivalent atomic session-touch semantics
  - `HMGET`/pipeline replay fetches for event batches
  - `OnceCell` or another single-flight pattern for expensive cache fills

#### 20. Session-auth reuse still trades freshness for fewer auth round-trips

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
- `crates/mcp_runtime/src/lib.rs`
- session-auth reuse cache invalidation design

Recommended next step:
- Decide whether the current bounded TTL contract is enough, or whether Rust
  should consume a revocation/invalidation signal from Python to drop cached
  auth state immediately.

#### 21. Sustained tools-only load still has a small internal-auth/control-plane failure tail

Status:
- Deferred Rust-specific performance/reliability follow-up

Observed behavior:
- On the normal full-Rust compose stack, sustained distributed tools-only load
  is still not perfectly clean:
  - `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s`
    produced `20` failures in `1,842,181` requests on the richer `fast_time`
    server profile.
- After isolating the upstreams:
  - the simpler `fast_test` server reduced the same class of load to `3`
    failures in `1,042,973` requests, all plain `502`s
  - a controlled `fast_time` run with
    `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=false` removed the `HTTP 0` / ~30s tail
    entirely and reduced the exact `1000 users / 300s` run to `9` failures in
    `1,799,022` requests
- The remaining `9` failures with RMCP explicitly off were all internal
  control-plane `502`s:
  - `8` `tools/call` failures from Rust -> Python
    `/_internal/mcp/authenticate`
  - `1` `tools/list` failure from Rust -> Python
    `/_internal/mcp/tools/list/authz`

Why this matters:
- The current "sustained-load tail" is not one problem:
  - one part is specific to the experimental RMCP upstream client path on the
    richer `fast_time` server profile
  - the other part is a lower-rate internal Rust -> Python auth/authz hop
    reliability issue under heavy distributed load
- This is now a bounded, diagnosable release note rather than a vague generic
  instability concern.

Likely area:
- `crates/mcp_runtime/src/lib.rs`
- Rust internal backend auth/authz client path
- RMCP upstream client path for direct `tools/call`

Recommended next step:
- Keep the sustained tools-only failure tail split into two sub-investigations:
  - internal Rust -> Python auth/authz send failures under heavy load
  - RMCP upstream client instability on the richer `fast_time` benchmark path
- Re-run the same `1000 users / 300s` benchmark after any auth/authz client
  tuning and after any RMCP upstream client fixes, rather than treating all
  remaining failures as one bucket.

#### 22. Docker Compose currently exports an empty RMCP bool env var

Status:
- Deferred configuration/wiring follow-up

Observed behavior:
- The current compose wiring exports
  `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=` into the gateway container even when the
  operator has not set a value.
- In practice, the normal full-Rust compose stack behaved as if the RMCP
  upstream client path was enabled, while an explicit
  `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=false` runtime override materially changed
  the sustained-load results.

Why this matters:
- Empty-string bool env handling is easy to misread operationally.
- The experimental RMCP path should not appear enabled "by accident" through
  ambiguous compose/env wiring.

Likely area:
- `docker-compose.yml`
- Rust runtime bool env parsing / startup visibility

Recommended next step:
- Make the compose behavior unambiguous:
  - either omit the env var entirely when unset
  - or set it explicitly to `true` / `false`
- Add a small startup/logging signal or health detail that makes the effective
  RMCP-upstream-client mode obvious during live testing.

#### 23. Legacy migration suites are still red

Status:
- Deferred broader release/upgrade follow-up

Observed behavior:
- `make migration-test-sqlite` is still not release-clean:
  - `7 failed, 3 passed`
  - failures show post-upgrade data loss across `0.5.0/0.6.0/latest` paths
- `make migration-test-postgres` now gets past the earlier harness issues, but
  still fails on real legacy startup/migration behavior:
  - the `0.5.0` image cannot locate Alembic revision `1fc1795f6983`

Why this matters:
- These are real release-upgrade concerns, but they are not Rust-runtime
  transport regressions.
- They affect broader product upgrade confidence across older versions.

Likely area:
- `tests/migration/*`
- legacy image migration chains
- historical Alembic revision continuity

Recommended next step:
- Treat the migration failures as a separate upgrade-hardening track.
- Decide which historical upgrade paths must be supported for the release, then
  fix the legacy migration/data-retention issues independently of the Rust MCP
  transport PR.

#### 24. PostgreSQL client-certificate authentication is still unsupported

Status:
- Deferred feature-gap follow-up

Observed behavior:
- Live PostgreSQL TLS validation has now been executed locally for:
  - Python with `sslmode=require`
  - Rust with `sslmode=require`
  - Rust with `sslmode=prefer`
  - Rust non-TLS fallback with `sslmode=disable`
- Those paths are all working as expected.
- The remaining gap is PostgreSQL client-certificate authentication on the
  Rust runtime path:
  - `sslcert` / `sslkey` in `MCP_RUST_DATABASE_URL` are not supported
  - the runtime fails fast clearly at startup instead of silently ignoring the
    settings

Why this matters:
- The current behavior is safe and explicit, but environments that require
  mTLS-style PostgreSQL client auth still cannot use the Rust runtime path.

Likely area:
- Rust database URL/config parsing and TLS connector setup in
  `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Add actual `sslcert` / `sslkey` support for the Rust PostgreSQL client path.
- Keep the current fail-fast startup validation until client-cert auth is fully
  implemented and tested end to end.

#### 25. Minikube clean reinstall flow still looks unhealthy

Status:
- Deferred Helm/deployment follow-up

Observed behavior:
- The Minikube validation pass successfully deployed and served traffic.
- However, the explicit empty-namespace reinstall flow was not release-clean:
  - resources were created in the fresh namespace
  - `helm list` remained empty
  - the namespace had to be deleted again to avoid leaving orphaned resources

Why this matters:
- This is a deployment/release-process problem, not a Rust transport bug.
- It affects confidence in Helm reinstall semantics and cleanup behavior.

Likely area:
- Helm release lifecycle around `charts/mcp-stack`
- local Minikube/Helm state handling
- install/upgrade wrapper behavior in the `Makefile`

Recommended next step:
- Reproduce the clean reinstall flow in isolation and determine whether the
  issue is in Helm invocation, namespace lifecycle timing, or local Minikube
  state.

#### 25a. Rust-enabled Minikube / Helm direct gateway path emits Zstandard MCP responses that break current clients

Status:
- Deferred Kubernetes/Rust transport compatibility follow-up

Observed behavior:
- A dedicated Rust-enabled Helm deployment was validated on Minikube with:
  - gateway image override:
    - `mcpgateway/mcpgateway:latest`
  - gateway config override:
    - `RUST_MCP_MODE=full`
  - release:
    - `mcp-stack-rust` in namespace `mcp-private-rust`
- The deployment itself came up healthy and `/health` reported:
  - `mcp_runtime.mode = rust-managed`
- Raw HTTP MCP calls worked when compression was not negotiated.
- When the client advertised `Accept-Encoding: zstd`, the direct Minikube
  gateway service returned `Content-Encoding: zstd` on Rust MCP responses:
  - `/mcp/`
  - `/servers/<id>/mcp/`
- The same probe against the compose full-Rust stack behind nginx returned
  plain JSON with no `Content-Encoding`.
- Client-visible failures on the Rust-enabled Minikube path included:
  - `make test-mcp-cli`:
    - `14 failed`, `9 passed`, `4 rerun`
  - `make test-mcp-access-matrix`:
    - `2 failed`, `3 passed`
  - wrapper `Invalid JSON response`
  - `UnicodeDecodeError` in `response.json()`
- A direct validation of the workaround succeeded:
  - setting `COMPRESSION_ENABLED=false` on the Rust-enabled Helm release and
    restarting the gateway removed `Content-Encoding: zstd` from `/mcp/`
  - `make test-mcp-cli` then passed cleanly against the same Rust-enabled
    Minikube endpoint:
    - `23 passed`
- The current Python compression middleware behavior explains the issue:
  - app-level compression is enabled globally in `mcpgateway/main.py`
  - `SSEAwareCompressMiddleware` only bypasses MCP compression when
    `json_response_enabled=false` (SSE mode)
  - in normal JSON MCP mode, `/mcp` and `/servers/*/mcp` responses are still
    compressed like generic REST JSON responses
- There is no corresponding compression feature gap inside the Rust runtime
  binary itself; this is a gateway-layer response-compression policy issue.

Why this matters:
- The Helm deploy itself is healthy, but the direct k8s Rust public transport
  is not yet compatible with the current wrapper / test clients when Zstandard
  compression is negotiated.
- This is a real gap in claiming Rust-enabled Kubernetes readiness, even though
  the compose full-Rust path remains healthy behind nginx.

Likely area:
- Python gateway response compression middleware around the Rust public MCP
  transport path (not missing compression support inside the Rust runtime
  binary itself)
- response compression middleware / `starlette-compress`
- compression negotiation differences between:
  - direct gateway service
  - nginx-fronted compose deployment
- client compatibility expectations in:
  - `mcpgateway.wrapper`
  - `tests/e2e/test_mcp_cli_protocol.py`
  - `tests/e2e_rust/test_mcp_access_matrix.py`

Recommended next step:
- Change the Python gateway compression policy so MCP endpoints bypass
  app-level compression entirely, not just in SSE mode:
  - `/mcp`
  - `/mcp/`
  - `/servers/*/mcp`
  - `/servers/*/mcp/`
- Decide whether the direct Rust k8s gateway should:
  - disable Zstandard on MCP JSON-RPC responses, or
  - only enable encodings known to work with supported clients, or
  - ensure the wrapper/test/client stack decodes Zstandard reliably
- The strongest validated immediate mitigation is:
  - disable app-level compression for the Rust-enabled direct k8s gateway
    (`COMPRESSION_ENABLED=false`)
- Re-run the Rust-enabled Minikube validation after that change:
  - `/health`
  - `make test-mcp-cli`
  - `make test-mcp-access-matrix`

#### 26. Optional `2025-11-25-report` surface is not release-clean

Status:
- Deferred protocol-surface follow-up

Observed behavior:
- `make 2025-11-25-core` and `make 2025-11-25-auth` are green on the settled
  full-Rust stack.
- The broader optional report target is still red:
  - `9 failed, 44 passed, 2 skipped`
- Remaining failing live methods on the Rust full path were:
  - `completion/complete` -> HTTP `500`
  - `prompts/get` -> HTTP `404`
  - `resources/read` -> HTTP `404`
  - `resources/subscribe` -> HTTP `500`
  - `sampling/createMessage` -> HTTP `500`
  - `tasks/list|get|result|cancel` -> HTTP `200`, but error code `-32000`
- The same targeted calls were replayed against the plain Python stack:
  - `completion/complete` -> HTTP `200`, valid JSON-RPC `result`
  - `prompts/get` -> HTTP `200`, JSON-RPC `error` envelope
  - `resources/read` -> HTTP `200`, JSON-RPC `result`
  - `resources/subscribe` -> HTTP `200`, `-32601`
  - `sampling/createMessage` -> HTTP `200`, `-32602`
  - `tasks/list|get|result|cancel` -> HTTP `200`, `-32601` / `-32602`

Why this matters:
- These failures are mostly Rust-path parity gaps on the broader optional
  report surface, not just generic product limitations.
- They are still not being treated as merge blockers for this PR because:
  - `2025-11-25-core` and `2025-11-25-auth` are green
  - the main live MCP runtime lanes are green
  - this lane is broader optional/report coverage rather than the primary
    release gate for the experimental opt-in Rust MCP runtime

Likely area:
- `crates/mcp_runtime/src/lib.rs`
- Python internal MCP handlers reached via the Rust bridge
- optional MCP method behavior and error-shape expectations
- server-specific sample-data assumptions for prompts/resources/completion

Recommended next step:
- Bring the Rust full path into parity with the Python path for the optional
  report surface, specifically:
  - return JSON-RPC envelopes on `prompts/get` / `resources/read` missing-item
    paths instead of Rust-only `404`s
  - map `resources/subscribe` and `sampling/createMessage` failures to clean
    JSON-RPC method/params errors instead of opaque `500`s
  - align unsupported `tasks/*` methods to `-32601` / `-32602`
  - align `completion/complete` missing-prompt behavior with the Python path

#### 27. Nginx should still strip internal `x-contextforge-*` trust headers as defense in depth

Status:
- Deferred deployment hardening follow-up

Observed behavior:
- The direct trust-boundary bypass is fixed in this PR:
  - trusted `/_internal/mcp/*` requests now require loopback, the Rust runtime
    marker header, and a shared-secret-derived internal auth header
- However, the nginx configs do not currently clear internal
  `x-contextforge-*` trust headers from public requests before proxying them to
  the gateway.

Why this matters:
- This is no longer a direct merge blocker because Python no longer trusts only
  the forwarded header names.
- It is still worthwhile defense in depth:
  - reduces accidental future trust on spoofable public headers
  - reduces confusing logs/debug traces that appear to carry internal headers

Likely area:
- `infra/nginx/nginx-performance.conf`
- `infra/nginx/nginx-tls.conf`
- other nginx variants used for embedded/test deployments

Recommended next step:
- Explicitly clear internal trust headers at the public nginx ingress layers,
  including at least:
  - `x-contextforge-mcp-runtime`
  - `x-contextforge-mcp-runtime-auth`
  - `x-contextforge-auth-context`
  - `x-contextforge-server-id`
  - any session-validation or affinity-only internal headers

#### 28. Edge-mode Rust public listener still defaults to `0.0.0.0:8787`

Status:
- Deferred deployment-hardening follow-up

Observed behavior:
- `docker-entrypoint.sh` currently defaults `MCP_RUST_PUBLIC_LISTEN_HTTP` to
  `0.0.0.0:8787` when:
  - Rust runtime is enabled
  - Rust runtime is managed
  - session-auth reuse is enabled

Why this matters:
- The public Rust listener is meant for nginx-mediated edge/full mode.
- Binding it broadly by default increases the chance of direct sidecar
  exposure in ad-hoc or partially hardened deployments.

Likely area:
- `docker-entrypoint.sh`
- compose/Helm docs around edge/full deployment expectations

Recommended next step:
- Decide whether the safer default should be:
  - loopback-only by default, with explicit opt-in for wider bind addresses, or
  - current broad bind, but with much clearer deployment guidance and warnings
    when nginx or network policy is not constraining exposure.

#### 29. Forwarded internal auth context is still trusted by channel security, not by its own signature

Status:
- Deferred internal-transport hardening follow-up

Observed behavior:
- Internal MCP auth context continues to be forwarded as base64-encoded JSON.
- After the current C1 fix, those forwarded requests are protected by:
  - loopback checks on the Python side
  - the Rust runtime marker header
  - the shared-secret-derived `x-contextforge-mcp-runtime-auth` header
- The auth context payload itself is not separately signed.

Why this matters:
- The current model is acceptable for the local trusted channel the runtime is
  using today.
- If the internal transport model broadens in future, independently signing or
  MACing the auth context may become desirable rather than trusting only the
  channel and outer request authenticator.

Likely area:
- `mcpgateway/main.py`
- `mcpgateway/middleware/token_scoping.py`
- `mcpgateway/transports/rust_mcp_runtime_proxy.py`
- `crates/mcp_runtime/src/lib.rs`

Recommended next step:
- Keep the current channel-authenticated approach for now.
- If the internal hop ever extends beyond tightly local/private channels,
  consider signing or MACing the forwarded auth context itself.

## Not In Scope Here

These items are not currently believed to be blocking the main Rust MCP runtime work:

- core MCP protocol parity
- Rust MCP session isolation correctness
- Rust MCP performance benchmarking

Those are tracked in:

- [`README.md`](./README.md)
- [`STATUS.md`](./STATUS.md)
- [`TESTING-DESIGN.md`](./TESTING-DESIGN.md)
