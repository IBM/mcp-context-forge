# Rust MCP Runtime Status

Last updated: March 11, 2026

Status focus in this update:

- Rust session-core is now running on the compose-built image with a real
  Redis-backed session metadata store:
  - `EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED=true`
  - `MCP_RUST_SESSION_CORE_ENABLED=true`
- Rust resumable event-store semantics are now implemented in the sidecar and
  wired into the Python `SessionManagerWrapper` behind separate flags:
  - `EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED=true`
  - `MCP_RUST_EVENT_STORE_ENABLED=true`
  - `MCP_RUST_REDIS_URL=redis://redis:6379/0`
- the Rust runtime now exposes internal event-store endpoints:
  - `POST /_internal/event-store/store`
  - `POST /_internal/event-store/replay`
- Rust session metadata is shared across runtime instances through Redis, and
  Rust event replay works across runtime instances through Redis
- live compose validation is now complete for this slice:
  - rebuilt image with:
    - `ENABLE_RUST_BUILD=true`
    - `ENABLE_RUST_MCP_RMCP_BUILD=true`
  - running stack with:
    - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
    - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
    - `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock`
    - `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
    - `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true`
    - `USE_STATEFUL_SESSIONS=true`
    - `MCP_RUST_LOG=warn`
    - `GUNICORN_WORKERS=32`
- live runtime proof on the rebuilt stack:
  - `/health` returns:
    - `x-contextforge-mcp-runtime-mode: rust-managed`
    - `x-contextforge-mcp-session-core-mode: rust`
    - `x-contextforge-mcp-event-store-mode: rust`
  - raw `POST /servers/<id>/mcp initialize` returns:
    - `x-contextforge-mcp-runtime: rust`
    - `x-contextforge-mcp-session-core: rust`
  - Redis contains Rust session metadata keys at:
    - `mcpgw:rust:mcp:session:<session-id>`
- the live delete/teardown gap is fixed:
  - previously, server-scoped `DELETE /servers/<id>/mcp` still returned `405`
    because Rust was proxying delete through the generic Python transport path
  - Rust now uses a dedicated trusted Python cleanup route:
    - `DELETE /_internal/mcp/session`
  - that route removes session-registry state and cleans session-affinity owner
    state when enabled
  - verified live on the rebuilt stack:
    - `DELETE /servers/<id>/mcp` -> `204 No Content`
    - `x-contextforge-mcp-runtime: rust`
    - Rust Redis session metadata key removed immediately after delete
- image-level validation for this milestone passed:
  - `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
    -> `35 passed`
  - targeted Python unit coverage passed for:
    - internal MCP session delete handler
    - internal MCP initialize handler
    - Rust event-store transport wrapper selection
    - runtime config defaults
  - `make test-mcp-cli` -> `23 passed`
  - `make test-mcp-rbac` -> `40 passed`
  - `uv run pytest -q --with-integration tests/integration/test_streamable_http_redis.py`
    -> `7 passed`
- live container-level proof that the Rust event-store works across gateway
  replicas:
  - event stored through the Rust sidecar inside `gateway-1`
  - replayed through the Rust sidecar inside `gateway-2`
  - response returned the later event from the shared Redis-backed stream
- important nuance on public-flow coverage:
  - the standard `mcp-cli`, RBAC, and load-test flows still do not create
    `mcpgw:eventstore*` keys in Redis
  - they validate the Rust transport/session path, but not the replay/resume
    branch
  - replay/resume itself is currently validated by:
    - Rust runtime tests
    - Python unit tests
    - `tests/integration/test_streamable_http_redis.py`
    - the live cross-replica container proof above
- current compose-built performance on this rebuilt session-core/event-store image:
  - mixed MCP:
    - `120 users` -> `979.51 RPS`, `19.91 ms` avg, `35 ms` p95, `82 ms` p99
    - `150 users` -> `1053.20 RPS`, `38.70 ms` avg, `69 ms` p95, `120 ms` p99
  - tools-only:
    - `125 users` -> `1146.97 RPS` overall
    - `MCP tools/call [rapid]` -> `1090.9 RPS`
    - `51.23 ms` avg, `67 ms` p95, `95 ms` p99
- current boundary after this slice:
  - public MCP transport is Rust-fronted
  - Rust owns session metadata, delete teardown orchestration, and Redis-backed
    event store/replay primitives
  - Python still owns the underlying `StreamableHTTPSessionManager` request
    execution and the public replay/resume behavior that sits on top of the
    event store

- the optional `rmcp` integration spike is now wired through the container
  build and compose runtime
- compose image builds now support:
  - `ENABLE_RUST=true`
  - `ENABLE_RUST_MCP_RMCP=true`
- runtime activation is separately gated by:
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
  - `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true`
- the managed Rust sidecar is running over UDS in the validated compose stack:
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock`
  - `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
- the compose-built live stack now proves all of the following at runtime:
  - `/health` returns:
    - `x-contextforge-mcp-runtime-mode: rust-managed`
    - `x-contextforge-mcp-transport-mounted: rust`
    - `x-contextforge-rust-build-included: true`
  - live `tools/call` responses return:
    - `x-contextforge-mcp-runtime: rust`
    - `x-contextforge-mcp-upstream-client: rmcp`
- `docker compose build gateway` succeeded with the classic builder path:
  - `DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build gateway`
- note on host behavior:
  - the default BuildKit/Bake compose build path on this host failed with a
    Docker cgroup/systemd builder error
  - the repo code and image build are valid; the compose build succeeds with
    the legacy builder mode above
- compose-built image validation on the live stack passed:
  - `make test-mcp-cli` -> `23 passed`
  - `make test-mcp-rbac` -> `40 passed`
- full `make test-ui-headless` was run against the same compose-built Rust
  stack and completed:
  - `761 passed`
  - `83 skipped`
  - `3 failed`
  - `5 errors`
  - total runtime about `41m55s`
- important UI-suite quality note:
  - the exact `8` failed/error cases from the full headless run were rerun
    individually against the same live stack and all `8` passed
  - current evidence points to suite-order or shared-state Playwright flake,
    not a deterministic Rust MCP regression
- current compose-built performance on the live `Fast Time Server` target:
  - mixed MCP:
    - `100 users` -> `880.72 RPS`, `15.88 ms` avg, `25 ms` p95, `59 ms` p99
    - `120 users` -> `1007.35 RPS`, `21.65 ms` avg, `37 ms` p95, `79 ms` p99
    - `150 users` -> `1033.01 RPS`, `47.18 ms` avg, `83 ms` p95, `130 ms` p99
    - `175 users` -> `1008.24 RPS`, `77.57 ms` avg, `130 ms` p95, `220 ms` p99
  - tools-only:
    - `125 users` -> `1126.96 RPS` overall
    - `MCP tools/call [rapid]` -> `1068.5 RPS`
    - `58.32 ms` avg, `72 ms` p95, `100 ms` p99
- comparison point:
  - earlier Python mixed baseline peaked at `759 RPS` at `100` users
  - the current compose-built Rust stack now exceeds `1000 RPS` on the mixed
    workload and exceeds `1100 RPS` on the tools-only hot path
- current quality summary:
  - MCP transport/runtime path is working correctly on the compose-built image
  - core MCP protocol parity suites are green
  - full UI coverage is mostly healthy but not yet fully stable end-to-end
  - historical implementation notes continue below
- `resources/subscribe`, `resources/unsubscribe`, and `roots/list` are no
  longer routed through the generic Python `/_internal/mcp/rpc` switch
- dedicated trusted internal Python routes now handle:
  - `/_internal/mcp/resources/subscribe`
  - `/_internal/mcp/resources/unsubscribe`
  - `/_internal/mcp/roots/list`
- `completion/complete`, `sampling/createMessage`, and `logging/setLevel` are
  now routed through dedicated trusted internal Python routes instead of the
  generic `/_internal/mcp/rpc` switch
- dedicated trusted internal Python routes now handle:
  - `/_internal/mcp/completion/complete`
  - `/_internal/mcp/sampling/createMessage`
  - `/_internal/mcp/logging/setLevel`
- unexpected backend failures on those specialized internal routes now return
  JSON payloads instead of plain 500 responses, so Rust preserves the actual
  MCP application error rather than masking it as a decode-failure `502`
- unsupported MCP catch-all methods are now handled locally in Rust without a
  Python dispatcher round trip:
  - `notifications/*` except the explicitly implemented notification methods
  - `sampling/*` except `sampling/createMessage`
  - `completion/*` except `completion/complete`
  - `logging/*` except `logging/setLevel`
  - `elicitation/*` except `elicitation/create`
- live proof on the rebuilt Rust-enabled stack:
  - `resources/subscribe` -> `200` with `x-contextforge-mcp-runtime: rust`
  - `resources/unsubscribe` -> `200` with `x-contextforge-mcp-runtime: rust`
  - `roots/list` -> `200` with `x-contextforge-mcp-runtime: rust`
  - `logging/setLevel` -> `200` with `x-contextforge-mcp-runtime: rust`
  - `sampling/createMessage` -> `500` with `x-contextforge-mcp-runtime: rust`
    and a structured JSON-RPC error payload instead of a Rust-side `502`
  - `completion/complete` -> `500` with `x-contextforge-mcp-runtime: rust`
    and a structured JSON-RPC error payload instead of a Rust-side `502`
  - `notifications/unknown` -> `202` with `x-contextforge-mcp-runtime: rust`
  - `sampling/unknown` -> `200` with JSON-RPC `result: {}`
  - `completion/unknown` -> `200` with JSON-RPC `result: {}`
  - `logging/other` -> `200` with JSON-RPC `result: {}`
  - `elicitation/other` -> `200` with JSON-RPC `result: {}`
- focused Python unit coverage now includes internal error-shape regression
  tests for the new `completion/complete` and `sampling/createMessage` routes
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  now passes with `32` runtime tests
- targeted internal-handler Python coverage passed for:
  - `handle_internal_mcp_resources_subscribe`
  - `handle_internal_mcp_resources_unsubscribe`
  - `handle_internal_mcp_roots_list`
  - `handle_internal_mcp_completion_complete`
  - `handle_internal_mcp_sampling_create_message`
  - `handle_internal_mcp_logging_set_level`
- rebuilt-stack validation passed again:
  - `make test-mcp-cli`: `23 passed`
  - `make test-mcp-rbac`: `40 passed`
- note on test execution: `test-mcp-cli` and `test-mcp-rbac` should be run
  sequentially against the same live compose stack; when I ran them in parallel,
  one RBAC API test flaked with a transient `401`, and the isolated plus
  sequential reruns were clean
- explicit operator-facing runtime visibility for Rust vs Python MCP mounting
- `docker-entrypoint.sh` now prints `MCP runtime mode: ...` on startup
- `/health` and `/ready` now expose `mcp_runtime` status plus runtime-mode headers
- Python-mounted MCP transport now stamps `x-contextforge-mcp-runtime: python`
- importing the Python app now warns loudly when Rust artifacts are present but
  `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED` is not set
- live proof that rebuilt Rust-enabled compose stack reports:
  - `x-contextforge-mcp-runtime-mode: rust-managed`
  - `x-contextforge-mcp-transport-mounted: rust`
  - `x-contextforge-rust-build-included: true`
- live proof that raw `POST /mcp initialize` still returns
  `x-contextforge-mcp-runtime: rust`
- `notifications/initialized` is no longer routed through the generic Python
  `/_internal/mcp/rpc` switch
- a dedicated trusted internal Python
  `/_internal/mcp/notifications/initialized` route now preserves the existing
  initialize-notification side effects while shrinking the dispatcher seam
- Rust now forwards MCP `notifications/initialized` directly to that specialized
  internal route as `backend-notifications-initialized-direct`
- `notifications/message` is no longer routed through the generic Python
  `/_internal/mcp/rpc` switch
- a dedicated trusted internal Python
  `/_internal/mcp/notifications/message` route now preserves existing logging
  side effects while shrinking the dispatcher seam
- Rust now forwards MCP `notifications/message` directly to that specialized
  internal route as `backend-notifications-message-direct`
- `notifications/cancelled` is no longer routed through the generic Python
  `/_internal/mcp/rpc` switch
- a dedicated trusted internal Python
  `/_internal/mcp/notifications/cancelled` route now preserves cancellation
  authorization and cancellation-service side effects while shrinking the
  dispatcher seam
- Rust now forwards MCP `notifications/cancelled` directly to that specialized
  internal route as `backend-notifications-cancelled-direct`
- `initialize` is no longer routed through the generic Python `/_internal/mcp/rpc` switch
- a dedicated trusted internal Python `/_internal/mcp/initialize` route now preserves initialize session ownership and session-affinity semantics
- Rust now forwards MCP `initialize` directly to that specialized internal route as `backend-initialize-direct`
- `resources/list`, `resources/read`, and `resources/templates/list` are now
  routed through dedicated trusted internal Python routes instead of the generic
  `/_internal/mcp/rpc` switch
- `prompts/list` and `prompts/get` are now routed through dedicated trusted
  internal Python routes instead of the generic `/_internal/mcp/rpc` switch
- Rust now forwards those read-only MCP methods as:
  - `backend-resources-list-direct`
  - `backend-resources-read-direct`
  - `backend-resource-templates-list-direct`
  - `backend-prompts-list-direct`
  - `backend-prompts-get-direct`
- focused Python unit coverage and Rust runtime coverage now include the newly
  specialized `resources/read`, `resources/templates/list`, and `prompts/get`
  paths
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  now passes with `24` runtime tests
- targeted internal-handler Python coverage passed for the new routes
- full live MCP validation on the rebuilt Rust-enabled image passed again:
  - `make test-mcp-cli`: `23 passed`
  - `make test-mcp-rbac`: `40 passed`
- raw live `POST /servers/<id>/mcp` calls for:
  - `resources/templates/list`
  - `prompts/get`
  - `resources/read`
  all returned `x-contextforge-mcp-runtime: rust`
- live validation was rerun on an explicitly Rust-enabled compose stack after rebuilding the image and reapplying the runtime env flags
- raw `POST /mcp initialize` now again proves `x-contextforge-mcp-runtime: rust` on the rebuilt live stack
- `make test-mcp-cli` and `make test-mcp-rbac` were rerun on the actual Rust-enabled stack, not just a Rust-built image
- first transport/session parity increment for the Rust MCP edge
- Rust now fronts outer `GET /mcp`, `POST /mcp`, and `DELETE /mcp`
- a trusted internal Python transport bridge at `/_internal/mcp/transport`
- preserved server-scoped Streamable HTTP semantics across the Rust -> Python transport seam
- focused Python and Rust regression coverage for server-scoped `GET`/`DELETE` MCP transport requests
- direct live raw-HTTP proof that `POST /mcp` and `DELETE /mcp` are traversing Rust on the rebuilt Rust-enabled stack
- multi-server Locust MCP protocol benchmarking via `MCP_SERVER_IDS`
- quieter benchmark runs via `LOCUST_LOG_LEVEL` and cleaner multiprocess summaries
- additional scaling investigation with both `Fast Time Server` and `Fast Test Server`
- confirmation that single-process Locust and `--processes=-1` are effectively equivalent at the current gateway knee
- confirmation that the public gateway tier, not Redis or the upstream test servers, is still the main saturation point
- confirmation that adding a second fast MCP server does not improve the current mixed-workload ceiling
- refreshed best-case hot-path number: `1094.59 RPS` on `MCPToolCallerUser` against `fast_time`
- runtime/process tuning knobs for the Rust-enabled compose stack
- verified `>1000 RPS` on the rebuilt Rust-enabled mixed MCP benchmark
- `MCP_RUST_LOG=warn` and `GUNICORN_WORKERS=32` as the first clearly effective mixed-workload tuning levers
- new Rust client/pool/cache TTL configurables exposed through compose
- confirmation that `HTTP_SERVER=granian` underperformed on this workload
- backend JSON-RPC error propagation for direct `tools/call` resolve failures
- fresh compose rebuild validation on the latest Rust-enabled gateway image
- verified `make test-mcp-cli` and `make test-mcp-rbac` on the rebuilt stack
- a full mixed MCP benchmark curve on the comparable `Fast Time Server` target
- Unix domain socket handoff between Python and the managed Rust sidecar
- a narrower trusted internal dispatcher route at `/_internal/mcp/rpc`
- a specialized trusted internal `tools/call` route at `/_internal/mcp/tools/call`
- forwarded MCP auth context instead of recomputing auth on the internal hop
- the first Rust-owned read-only DB path for server-scoped `tools/list`
- parity hardening for scoped-token `initialize` and nonexistent-tool `tools/call`
- clean server-scoped `MCPToolCallerUser` benchmark results for the real hot path
- direct Rust handling of upstream MCP SSE-framed responses for `initialize` and `tools/call`
- verified `>1000 RPS` on the pinned tools-only benchmark after the SSE fix

## Latest Narrowing Update

The current validated MCP JSON-RPC boundary on the live Rust-enabled stack is:

- Rust-fronted and specialized through dedicated Python internal routes:
  - `initialize`
  - `notifications/initialized`
  - `notifications/message`
  - `notifications/cancelled`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `resources/read`
  - `resources/subscribe`
  - `resources/unsubscribe`
  - `resources/templates/list`
  - `prompts/list`
  - `prompts/get`
  - `roots/list`
  - `completion/complete`
  - `sampling/createMessage`
  - `logging/setLevel`
- Rust-local catch-all handling:
  - unsupported `notifications/*`
  - unsupported `sampling/*`
  - unsupported `completion/*`
  - unsupported `logging/*`
  - unsupported `elicitation/*` other than `elicitation/create`

This means the generic Python `/_internal/mcp/rpc` dispatcher is now mostly a
fallback for:

- `elicitation/create`
- long-tail legacy compatibility methods such as `list_tools`, `list_gateways`,
  and `list_roots`
- backward-compatible direct tool invocation where `method=<tool_name>`
- any remaining non-specialized compatibility branches

The big remaining MCP-core gap is not ordinary JSON-RPC method dispatch
anymore. It is the transport/session subsystem behind:

- `/_internal/mcp/transport`
- `mcpgateway/transports/streamablehttp_transport.py`
- `mcpgateway/cache/session_registry.py`
- `mcpgateway/transports/redis_event_store.py`

## Latest Load-Test Harness Update

## Latest Dispatcher Narrowing Increment

The most recent correctness-focused Rust MCP increment moved more of the
read-only JSON-RPC surface off the generic Python `/_internal/mcp/rpc`
dispatcher and onto explicit trusted internal routes.

### Newly specialized methods

- `notifications/message`
- `notifications/cancelled`
- `resources/list`
- `resources/read`
- `resources/templates/list`
- `prompts/list`
- `prompts/get`

### Current transport and execution shape

For those methods, the live path is now:

- `client -> public /mcp -> Python auth/RBAC gate -> Rust runtime ->
  specialized internal Python MCP route`

That is still not the final fully Rust-owned execution core, but it removes
more of the generic JSON-RPC switch and makes the remaining Python boundary
much narrower and easier to replace method by method.

### Live validation on the rebuilt Rust-enabled stack

Validation rerun after rebuilding the image with Rust enabled:

- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  `24 passed`
- targeted internal handler tests for:
  - `notifications/message`
  - `notifications/cancelled`
  - `resources/list`
  - `resources/read`
  - `resources/templates/list`
  - `prompts/list`
  - `prompts/get`
- `make test-mcp-cli`: `23 passed`
- `make test-mcp-rbac`: `40 passed`

Raw live proof on `http://localhost:8080`:

- `GET /health` reported:
  - `x-contextforge-mcp-runtime-mode: rust-managed`
  - `x-contextforge-mcp-transport-mounted: rust`
  - `x-contextforge-rust-build-included: true`
- raw server-scoped MCP calls for:
  - `resources/templates/list`
  - `prompts/get`
  - `resources/read`
  all returned `x-contextforge-mcp-runtime: rust`

### What is still left on the generic internal dispatcher

The generic Python `/_internal/mcp/rpc` path is now much smaller. The remaining
notable MCP branches are mainly:

- `resources/subscribe`
- `resources/unsubscribe`
- `roots/list` and other `roots/*`
- elicitation methods
- any remaining long-tail compatibility or non-hot-path JSON-RPC branches

### Recommended next steps

1. Decide whether the remaining non-hot-path MCP methods need full dedicated
   narrowing, or whether the generic Python dispatcher can remain as a control
   plane fallback for those branches.
2. Continue transport-core migration behind `/_internal/mcp/transport`:
   session lifecycle, resumable event storage, and session-affinity ownership.
3. After the Python transport/session core is narrower, decide whether to move
   those remaining read-only methods to direct Rust ownership or leave them as
   narrow Python control-plane calls.

The most recent benchmarking pass was focused on separating:

- real gateway/runtime limits
- Locust load-generator limits
- upstream MCP server limits

The current conclusion is:

- the Rust MCP hot path is already above `1000 RPS`
- the mixed MCP benchmark can exceed `1000 RPS` on the tuned single-server
  fast-time setup, but not every workload shape does
- adding a second fast MCP server did not materially improve the ceiling
- Locust itself is not the limiter at the current peak

### Load-test harness changes

The MCP protocol Locust file now supports:

- `MCP_SERVER_IDS` as a comma-separated list of virtual server IDs
- per-server MCP discovery of tools/resources/prompts
- per-user round-robin assignment to one discovered target server
- `LOCUST_LOG_LEVEL` for quieter benchmark runs
- cleaner `test_stop` handling so multiprocess/distributed runs do not spam
  duplicate worker summaries

These changes live in
[`tests/loadtest/locustfile_mcp_protocol.py`](/home/cmihai/agents2/pr/mcp-context-forge/tests/loadtest/locustfile_mcp_protocol.py).

Practical value:

- the benchmark can now exercise multiple MCP virtual servers in one run
- mixed-workload and tools-only comparisons are easier to reproduce
- it is now straightforward to check whether extra upstream server capacity
  actually helps the Rust MCP path

### Additional benchmark targets used

In addition to the earlier `Fast Time Server`
(`9779b6698cbd4b4995ee04a4fab38737`), I created and exercised a second live
virtual server backed by `fast_test`:

- `Fast Test Server`: `3ac0d72e43f24b2bb3d084a11af0b712`

Both targets were verified on the Rust path using:

- `POST /servers/<id>/mcp`
- response header `x-contextforge-mcp-runtime: rust`

### Locust scaling result

At the current gateway knee, Locust multiprocessing did not materially improve
throughput.

Same stack, same two-server mixed workload, `150` users:

| Mode | RPS | Avg (ms) | p95 | Fails |
|------|----:|---------:|----:|------:|
| single-process Locust | 1014.48 | 54.41 | 94 | 0.00% |
| `--processes=-1` | 1003.26 | 54.17 | 96 | 0.00% |

Interpretation:

- the load generator is not the first ceiling at the current `~1k RPS` range
- more Locust workers are not the next meaningful optimization

### Two-server mixed-workload sweep

Mixed MCP benchmark using both:

- `Fast Time Server`
- `Fast Test Server`

Results:

| Users | RPS | Avg (ms) | p50 | p95 | p99 | Fails |
|------:|----:|---------:|----:|----:|----:|------:|
| 100 | 692.98 | 36.06 | 26 | 73 | 120 | 0.00% |
| 120 | 923.84 | 35.53 | 25 | 72 | 150 | 0.00% |
| 130 | 910.18 | 48.90 | 40 | 94 | 140 | 0.00% |
| 140 | 853.95 | 71.49 | 65 | 130 | 220 | 0.00% |
| 150 | 908.62 | 73.37 | 66 | 140 | 220 | 0.00% |
| 175 | 980.83 | 88.66 | 80 | 140 | 240 | 0.00% |
| 200 | 949.03 | 122.60 | 110 | 220 | 380 | 0.00% |
| 250 | 876.71 | 207.96 | 190 | 370 | 560 | 0.00% |
| 300 | 948.67 | 241.73 | 220 | 440 | 640 | 0.00% |

Interpretation:

- two-server mixed traffic did not improve on the earlier tuned single-server
  mixed peak
- the best observed two-server mixed point was `980.83 RPS` at `175` users
- the extra fast-test target increases variety, but it does not reduce the main
  gateway-side cost enough to raise the ceiling

### Two-server tools-only sweep

`MCPToolCallerUser`, both fast servers in rotation:

| Users | RPS | Avg (ms) | p50 | p95 | p99 | Fails |
|------:|----:|---------:|----:|----:|----:|------:|
| 100 | 1084.28 | 41.17 | 31 | 79 | 95 | 0.00% |
| 125 | 1018.10 | 74.76 | 67 | 120 | 150 | 0.00% |
| 150 | 1019.89 | 101.19 | 95 | 150 | 180 | 0.00% |
| 175 | 862.56 | 162.63 | 160 | 230 | 300 | 0.00% |
| 200 | 1011.46 | 157.33 | 150 | 200 | 310 | 0.00% |
| 250 | 1032.58 | 205.54 | 200 | 290 | 470 | 0.00% |
| 300 | 885.79 | 273.44 | 280 | 390 | 590 | 0.00% |

Interpretation:

- the Rust hot path still exceeds `1000 RPS`
- however, adding the second server does not improve the best tools-only
  result beyond the single-server fast-time path

### Single-server comparison

`MCPToolCallerUser`, `100` users:

| Target | RPS | Avg (ms) | p50 | p95 | p99 | Fails |
|--------|----:|---------:|----:|----:|----:|------:|
| `Fast Time Server` | 1074.09 | 42.61 | 41 | 58 | 88 | 0.00% |
| `Fast Test Server` | 982.49 | 52.22 | 56 | 65 | 78 | 0.00% |
| two-server rotation | 1084.28 | 41.17 | 31 | 79 | 95 | 0.00% |

And a tighter `fast_time`-only tools sweep:

| Users | RPS | Avg (ms) | p50 | p95 | p99 | Fails |
|------:|----:|---------:|----:|----:|----:|------:|
| 100 | 1094.59 | 40.57 | 39 | 56 | 77 | 0.00% |
| 125 | 1065.65 | 69.40 | 68 | 85 | 110 | 0.00% |
| 150 | 1041.42 | 98.57 | 96 | 120 | 150 | 0.00% |
| 175 | 1028.12 | 127.56 | 120 | 150 | 210 | 0.00% |

Current best-case statement:

- the cleanest current `>1000 RPS` claim is the Rust `tools/call` hot path
  against `Fast Time Server`
- the strongest measured number in this pass is `1094.59 RPS` at `100` users
  with `0.00%` failures

## Latest Transport/Session Parity Increment

The newest implementation step was not another throughput tweak. It was the
first real transport-parity increment toward a fuller Rust-owned MCP runtime.

What changed:

- Rust now fronts the outer `GET /mcp`, `POST /mcp`, and `DELETE /mcp` paths
- Rust forwards `GET` and `DELETE` to a trusted internal Python transport bridge
  at `/_internal/mcp/transport`
- that bridge reconstructs the mounted MCP path semantics for both global and
  server-scoped routes by restoring:
  - `path=/mcp/`
  - `modified_path=/mcp/` or `/servers/<id>/mcp`
- the internal hop reuses the forwarded MCP auth context instead of re-running
  public auth middleware logic
- query strings and `mcp-session-id` survive the Rust -> Python transport hop
- response headers still prove Rust ownership with
  `x-contextforge-mcp-runtime: rust`

What did not change:

- Python still owns the underlying `StreamableHTTPSessionManager`
- Python still owns resumable event storage, session registry, and multi-worker
  session-affinity logic
- this is transport-fronting parity, not a full Rust replacement of session
  state machinery

Focused validation for this increment:

- `uv run pytest -q tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py`
  - `6 passed`
- `uv run pytest -q tests/unit/mcpgateway/test_main_extended.py -k 'InternalTrustedMcpTransportBridge'`
  - `2 passed`
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  - Rust runtime crate tests passed, including new GET/DELETE transport coverage
- `make test-mcp-cli`
  - `23 passed`
- `make test-mcp-rbac`
  - `40 passed`

Additional live proof on the rebuilt Rust-enabled compose stack:

- raw `POST /mcp/` `initialize` returned `x-contextforge-mcp-runtime: rust`
- raw `DELETE /mcp/` returned `405 Method Not Allowed` with
  `x-contextforge-mcp-runtime: rust`
- this is now covered by
  [`tests/e2e/test_mcp_cli_protocol.py`](/home/cmihai/agents2/pr/mcp-context-forge/tests/e2e/test_mcp_cli_protocol.py)

Important current nuance:

- simple black-box `GET /mcp/` validation is still awkward because the stream is
  long-lived and does not behave like a bounded request/response probe
- the Rust `GET` forwarding path is currently proven by focused Python unit
  tests plus Rust crate tests, while the live E2E proof is currently strongest
  for `POST` and `DELETE`

Why this matters:

- the mounted MCP transport boundary is now simpler and more consistent:
  external MCP clients always hit Rust first
- future session-manager work can now be moved incrementally behind the same
  transport seam instead of changing the public mount shape again

## Latest Dispatcher Narrowing Increment

The next MCP-core steps after outer transport parity were to stop treating
`initialize` and `notifications/initialized` as generic backend JSON-RPC
methods.

What changed:

- Python now exposes a dedicated trusted internal route at
  `/_internal/mcp/initialize`
- Python now also exposes a dedicated trusted internal route at
  `/_internal/mcp/notifications/initialized`
- the existing initialize ownership and affinity behavior was factored into one
  shared helper so both the generic dispatcher and the internal Rust route use
  the same logic
- Rust now forwards `initialize` to the specialized internal route instead of
  `/_internal/mcp/rpc`
- Rust now forwards `notifications/initialized` to the specialized internal
  route instead of `/_internal/mcp/rpc`
- Rust request mode classification now records initialize as
  `backend-initialize-direct`
- Rust request mode classification now records initialized notifications as
  `backend-notifications-initialized-direct`

What did not change:

- Python still owns the real initialize side effects:
  - session ownership claims
  - capability storage
  - optional session-affinity registration
- Python still owns the initialized-notification side effect through
  `logging_service.notify`
- this removes generic dispatcher coupling for initialize, but it does not yet
  move initialize state deeper into Rust
- this removes one more generic dispatcher branch, but notification lifecycle
  handling is not fully Rust-owned yet

Focused validation for this increment:

- `uv run pytest -q tests/unit/mcpgateway/test_main_extended.py -k 'handle_internal_mcp_initialize or handle_rpc_initialize'`
  - `6 passed`
- `uv run pytest -q tests/unit/mcpgateway/test_main_extended.py -k 'handle_internal_mcp_initialize or handle_internal_mcp_notifications_initialized'`
  - `4 passed`
- `uv run pytest -q tests/unit/mcpgateway/test_main_extended.py -k 'InternalTrustedMcpTransportBridge or handle_internal_mcp_initialize or handle_rpc_initialize'`
  - `8 passed`
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  - `19 passed`
- rebuilt compose stack with:
  - `ENABLE_RUST_BUILD=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock`
  - `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
  - `MCP_RUST_LOG=warn`
  - `GUNICORN_WORKERS=32`
- live raw initialize proof on the rebuilt stack:
  - `POST /mcp/` returned `x-contextforge-mcp-runtime: rust`
- live runtime visibility proof on the rebuilt stack:
  - `GET /health` returned:
    - `x-contextforge-mcp-runtime-mode: rust-managed`
    - `x-contextforge-mcp-transport-mounted: rust`
    - `x-contextforge-rust-build-included: true`
- `make test-mcp-cli`
  - `23 passed`
- `make test-mcp-rbac`
  - `40 passed`

Operational note:

- building the image with `ENABLE_RUST_BUILD=true` is not sufficient by itself
- the runtime flags must also be set when the compose stack is started, or the
  gateway falls back to the Python MCP path
- that fallback is no longer silent:
  - container startup now logs `MCP runtime mode: ...`
  - Python app startup now logs the mounted MCP transport mode
  - `/health` and `/ready` now return `mcp_runtime` details
  - `/health` and `/ready` now set:
    - `x-contextforge-mcp-runtime-mode`
    - `x-contextforge-mcp-transport-mounted`
    - `x-contextforge-rust-build-included`
  - Python-mounted `/mcp` responses now include
    `x-contextforge-mcp-runtime: python`
- the safest proof check before trusting a benchmark or protocol run is now:
  - `/health` reports `mcp_runtime.mode`
  - MCP responses carry `x-contextforge-mcp-runtime`

## Latest Runtime Visibility Update

The newest operator-facing fix was not about raw throughput. It was about
making it obvious which MCP runtime is actually serving traffic.

Problem that existed before this update:

- a Rust-built image could still serve the Python MCP path if the runtime env
  flags were not set when the container started
- protocol tests could still pass in that state
- without checking headers or logs carefully, it was too easy to think Rust was
  active when it was not

What changed:

- `docker-entrypoint.sh` now prints the active MCP runtime mode at container
  startup
- the Python app now logs a loud warning when Rust artifacts are present but
  the Rust runtime is disabled
- `/health` and `/ready` now expose a structured `mcp_runtime` object
- `/health` and `/ready` now set:
  - `x-contextforge-mcp-runtime-mode`
  - `x-contextforge-mcp-transport-mounted`
  - `x-contextforge-rust-build-included`
- the Python MCP transport wrapper now stamps
  `x-contextforge-mcp-runtime: python`
- the Rust MCP transport still stamps
  `x-contextforge-mcp-runtime: rust`

Example live `/health` response on the rebuilt Rust-enabled compose stack:

```json
{
  "status": "healthy",
  "mcp_runtime": {
    "mode": "rust-managed",
    "mounted": "rust",
    "rust_build_included": true,
    "rust_runtime_enabled": true,
    "rust_runtime_managed": true,
    "sidecar_transport": "uds",
    "sidecar_target": "/tmp/contextforge-mcp-rust.sock"
  }
}
```

Example live `/health` headers on the same stack:

- `x-contextforge-mcp-runtime-mode: rust-managed`
- `x-contextforge-mcp-transport-mounted: rust`
- `x-contextforge-rust-build-included: true`

Current recommended proof checks:

1. Check container startup logs for `MCP runtime mode: ...`
2. Check `GET /health` for the `mcp_runtime` payload and headers
3. Check a real MCP response for `x-contextforge-mcp-runtime: rust` or
   `x-contextforge-mcp-runtime: python`

This removes the earlier “silent fallback” failure mode. The system can still
run on Python if the Rust runtime is not enabled, but it is now much harder to
miss.

### Infrastructure saturation snapshot

Tools-only run at `1040.74 RPS` (`100` users, two-server setup):

- `gateway-1`: `339.33%` CPU
- `gateway-2`: `333.00%` CPU
- `gateway-3`: `342.96%` CPU
- `postgres`: `88.35%` CPU
- `pgbouncer`: `56.34%` CPU
- `redis`: `0.30%` CPU
- `fast_test_server`: `10.89%` CPU
- `fast_time_server`: `18.37%` CPU

Mixed run at `833.76 RPS` (`175` users, two-server setup):

- `gateway-1`: `375.09%` CPU
- `gateway-2`: `354.11%` CPU
- `gateway-3`: `340.31%` CPU
- `postgres`: `104.48%` CPU
- `pgbouncer`: `89.32%` CPU
- `redis`: `1.01%` CPU

Interpretation:

- Redis is not the current steady-state bottleneck
- the upstream fast MCP servers are not saturated
- the main ceiling is still the public gateway tier plus DB mediation on the
  mixed path

### What this changes about next steps

This benchmarking pass sharpened the roadmap:

- do not spend time scaling Locust first
- do not assume that adding more fast MCP upstreams will improve the current
  ceiling
- the next real mixed-workload gain still comes from shrinking the remaining
  Python ingress/auth/RBAC/DB work, not from more benchmark harness changes

## Latest Tuning Results

The most important March 10, 2026 result is that the mixed MCP workload can now
exceed `1000 RPS` on the rebuilt Rust-enabled image without moving additional DB
reads into Rust.

The effective benchmarked runtime configuration was:

- `ENABLE_RUST_BUILD=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock`
- `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
- `MCP_RUST_LOG=warn`
- `HTTP_SERVER=gunicorn`
- `GUNICORN_WORKERS=32`

Key findings:

- `MCP_RUST_LOG=warn` was a real throughput win compared with per-request Rust
  `info` logging
- `GUNICORN_WORKERS=32` was the first process-level tuning change that clearly
  pushed the mixed benchmark over `1000 RPS`
- `HTTP_SERVER=granian` was materially worse on this workload and is not the
  recommended front door for the current Rust MCP path
- the rebuilt stack still passed the main protocol and RBAC suites while using
  the tuned settings

### Tuned mixed-workload sweep

Mixed MCP benchmark, same `Fast Time Server`
(`9779b6698cbd4b4995ee04a4fab38737`), tuned Rust-enabled stack:

| Users | RPS | Avg (ms) | p95 | p99 | Fails |
|------:|----:|---------:|----:|----:|------:|
| 110 | 984.02 | 22.49 | 39 | 88 | 0.00% |
| 120 | 1027.37 | 27.15 | 48 | 83 | 0.00% |
| 125 | 1013.27 | 33.80 | 60 | 100 | 0.00% |
| 130 | 1021.22 | 37.92 | 67 | 110 | 0.00% |
| 140 | 1008.10 | 49.69 | 84 | 140 | 0.00% |
| 150 | 1011.66 | 59.88 | 110 | 170 | 0.00% |

Interpretation:

- the Rust-enabled stack is no longer merely "close" to `1000 RPS` on the mixed
  benchmark
- the current practical operating knee for the tuned mixed workload is roughly
  `120` to `150` users
- adding far more concurrency than that still degrades throughput into queueing,
  as seen in the earlier `1000`-user run

### Rebuilt-image verification

After rebuilding the gateway image with `ENABLE_RUST_BUILD=true` and
restarting the Rust-enabled compose stack with the tuned runtime flags:

- `120` users: `1003.82 RPS`, `29.51 ms` avg, `53 ms` p95
- warm rerun at `120` users: `1015.44 RPS`, `28.83 ms` avg, `51 ms` p95

Important nuance:

- both rebuilt-image warm runs showed a single isolated `502` on `tools/call`
  out of roughly `27k` requests, so Locust exited nonzero even though the
  failure rate rounded to `0.00%`
- this looks like a rare hot-path instability rather than a broad Rust parity
  regression, because the rebuilt stack simultaneously passed:
  - `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  - `make test-mcp-cli`
  - `make test-mcp-rbac`

### New runtime knobs now exposed

The Rust runtime now supports explicit tuning for:

- `MCP_RUST_CLIENT_CONNECT_TIMEOUT_MS`
- `MCP_RUST_CLIENT_POOL_IDLE_TIMEOUT_SECONDS`
- `MCP_RUST_CLIENT_POOL_MAX_IDLE_PER_HOST`
- `MCP_RUST_CLIENT_TCP_KEEPALIVE_SECONDS`
- `MCP_RUST_TOOLS_CALL_PLAN_TTL_SECONDS`
- `MCP_RUST_UPSTREAM_SESSION_TTL_SECONDS`

Compose now also allows easy override of:

- `HTTP_SERVER`
- `GUNICORN_WORKERS`
- `GUNICORN_TIMEOUT`
- `GUNICORN_GRACEFUL_TIMEOUT`
- `GUNICORN_KEEP_ALIVE`
- `GUNICORN_MAX_REQUESTS`
- `GUNICORN_MAX_REQUESTS_JITTER`
- `GUNICORN_BACKLOG`
- `GRANIAN_WORKERS`
- `GRANIAN_BACKLOG`
- `GRANIAN_BACKPRESSURE`
- `GRANIAN_HTTP1_BUFFER_SIZE`
- `GRANIAN_RESPAWN_FAILED`

One practical gotcha discovered during rebuild validation:

- `docker compose build gateway` will only include the Rust runtime when
  `ENABLE_RUST_BUILD=true` is passed at build time
- restarting the stack without
  `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true` will silently benchmark the
  Python path instead of Rust, so the response header
  `x-contextforge-mcp-runtime: rust` should be checked before trusting any
  benchmark number

## Latest Performance Update

The most important March 10, 2026 finding is that the direct Rust `tools/call`
path was previously underperforming because it was silently falling back to
Python on many requests.

Root cause:

- the fast test MCP server returns `initialize` and `tools/call` responses as
  `text/event-stream` with JSON-RPC payloads inside `data:` frames
- the Rust runtime was decoding those responses as plain JSON
- that caused repeated `upstream initialize decode failed` fallbacks during live
  load

What changed:

- the Rust runtime now decodes upstream MCP responses from either:
  - plain JSON bodies
  - SSE-framed `data:` payloads
- the runtime test suite now includes an SSE upstream regression case

Measured impact on the pinned tools-only benchmark
`MCPToolCallerUser` against `/servers/a5209e5adad04216a54fc92c568ba6e1/mcp`:

| Phase | Users | Overall RPS | `tools/call` RPS | Avg (ms) | Failures |
|------|------:|------------:|-----------------:|---------:|---------:|
| Before SSE fix | 100 | ~698 | ~662 | ~93 | 0% |
| After SSE fix, first clean run | 100 | 828.44 | 783.11 | 70.65 | 0% |
| Warm-cache rerun | 100 | 972.24 | 922.93 | 52.51 | 0% |
| Confirmed `>1000` run | 125 | 1144.95 | 1086.60 | 59.98 | 0% |
| Confirmed rerun | 125 | 1131.96 | 1075.66 | 61.19 | 0% |

What this means:

- the Rust hot path is now genuinely executing direct upstream `tools/call`
  requests instead of bouncing back to Python because of response-shape
  mismatches
- the current implementation can exceed `1000 RPS` on the pinned tools-only
  benchmark without moving DB access for `tools/call` into Rust
- the remaining main bottleneck is still the Python public ingress and auth/RBAC
  seam in front of Rust, not the direct Rust upstream execution itself

### Fresh compose rebuild validation

On March 10, 2026 I rebuilt the gateway image, recreated the Rust-enabled
compose stack, and reran the live protocol suites against `http://localhost:8080`.

Validated:

- `make test-mcp-cli`: `23 passed`
- `make test-mcp-rbac`: `40 passed`
- targeted nonexistent-tool wrapper regression:
  `tests/e2e/test_mcp_cli_protocol.py::TestMcpStdioProtocol::test_tools_call_nonexistent_tool`
  passed after the resolve-path fix

Root cause of that regression:

- the dedicated Python `/_internal/mcp/tools/call/resolve` route let
  `ToolNotFoundError` escape as a `500`
- Rust treated that as a backend transport failure and did not surface the
  JSON-RPC error cleanly to the stdio wrapper path

What changed:

- Python now maps resolve-time `ToolNotFoundError` to a JSON-RPC `-32601`
  response on the internal route
- Rust now detects backend JSON-RPC error payloads coming back from the resolve
  endpoint and returns them directly to the client instead of treating them as a
  fallback transport error

### Fresh mixed-workload benchmark

I reran the full mixed MCP scalability curve from
`todo/performance/reproduce-testing.md` on the rebuilt Rust-enabled stack.

Important comparison detail:

- the comparable mixed benchmark target is the auto-detected rich server,
  currently `Fast Time Server`
  (`9779b6698cbd4b4995ee04a4fab38737`)
- the pinned `rust-perf-fast-test-2` server remains useful for controlled
  `tools/call` experiments, but it is not comparable for the mixed Locust curve
  because it does not expose the same discovery surface

Latest mixed Rust results:

| Users | Rust RPS | Avg (ms) | p50 | p95 | p99 | Fails |
|------:|---------:|---------:|----:|----:|----:|------:|
| 10 | 94.71 | 10.67 | 9 | 15 | 22 | 0.00% |
| 25 | 244.30 | 11.80 | 10 | 16 | 31 | 0.00% |
| 50 | 482.85 | 14.81 | 12 | 23 | 51 | 0.00% |
| 75 | 700.77 | 17.31 | 15 | 28 | 47 | 0.00% |
| 100 | 888.46 | 23.10 | 20 | 39 | 72 | 0.00% |
| 125 | 953.63 | 41.76 | 37 | 76 | 140 | 0.00% |
| 150 | 944.77 | 71.39 | 62 | 120 | 210 | 0.00% |
| 200 | 916.38 | 135.83 | 110 | 250 | 390 | 0.00% |
| 300 | 868.28 | 278.44 | 220 | 560 | 770 | 0.00% |

Compared to the earlier Python mixed baseline from the same benchmark recipe:

- Rust is higher at every measured user count in this rerun
- the most important comparison point is `100` users:
  - Python: `759 RPS`, `38 ms` avg, `62 ms` p95
  - Rust: `888.46 RPS`, `23.10 ms` avg, `39 ms` p95
- current mixed-workload peak is `953.63 RPS` at `125` users with `0%` failures

Current interpretation:

- the Rust transport/runtime work is now delivering a real mixed-workload gain,
  not just better saturation behavior
- the hottest direct `tools/call` path is still the best candidate to push the
  mixed curve past `1000 RPS`
- the current mixed benchmark is close enough to that threshold that the next
  gains should come from more of the `tools/call` ingress/policy seam moving out
  of Python, not from minor transport tweaks

## Executive Summary

The Rust MCP runtime is now a real, integrated stage-1 implementation, not just a throwaway prototype.

Today it successfully owns the public MCP HTTP transport edge for `GET /mcp`,
`POST /mcp`, and `DELETE /mcp` when
`EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`, while Python still owns:

- auth and RBAC
- business execution behind the internal MCP dispatcher
- MCP session-manager internals and resumable stream state

In practice, this means:

- Rust is already on the hot path for public `GET /mcp`, `POST /mcp`, and
  `DELETE /mcp` traffic
- Rust is already on the method path for `ping`, `initialize`, `tools/list`,
  `tools/call`, `resources/list`, `prompts/list`, and similar JSON-RPC MCP
  traffic
- Python no longer reparses and rewrites server-scoped MCP JSON bodies just to inject `server_id`
- the managed Python -> Rust hop can now run over a Unix domain socket instead of loopback TCP
- Python forwards a trusted auth context to the internal dispatcher, so auth and RBAC stay Python-owned without being recomputed on the internal hop
- Python also exposes a trusted internal transport bridge at
  `/_internal/mcp/transport` so Rust can front `GET`/`DELETE` without changing
  the mounted MCP path shape
- Rust now owns the server-scoped `tools/list` read path end-to-end after a Python auth/RBAC subrequest, using direct read-only Postgres queries instead of the generic Python JSON-RPC dispatcher
- Rust now routes `tools/call` to a dedicated Python internal endpoint instead of the generic `/_internal/mcp/rpc` switch
- the trusted internal MCP dispatcher now owns its SQLAlchemy session directly instead of paying FastAPI `Depends(get_db)` overhead on every Rust-backed call
- trusted Rust -> Python MCP dispatch no longer re-runs Pydantic `RPCRequest` validation that Rust already performed
- trusted internal Rust -> Python MCP requests now bypass token-scoping middleware path checks only when they come from loopback with the Rust runtime marker and forwarded auth context
- server-scoped `tools/call` now narrows tool selection by virtual server earlier in Python before upstream execution
- Rust is not yet the full MCP implementation for resumable Streamable HTTP or SSE/session orchestration
- the current cut is viable, testable, containerized, and live behind an experimental flag

### Direct Answer: Is Real MCP JSON-RPC Traffic Going Through Rust?

Yes.

On a Rust-enabled stack, real MCP client traffic hits Rust first at the public
`/mcp` mount.

Current live request shape:

- client `POST /mcp` JSON-RPC request
- Python auth/token-scope/RBAC gate
- Rust MCP runtime
- then one of:
  - Rust handles it locally, for example `ping`
  - Rust handles it directly with its own implementation, currently the
    server-scoped `tools/list` direct-read path
  - Rust forwards it to a narrow trusted Python internal route such as:
    - `/_internal/mcp/rpc`
    - `/_internal/mcp/tools/call`
    - `/_internal/mcp/transport`

So the honest boundary is:

- yes, actual MCP JSON-RPC transport traffic is going through Rust
- no, not all MCP business execution is Rust-owned yet
- the remaining Python-owned pieces are mainly:
  - auth/RBAC policy
  - session manager internals
  - most execution paths other than the current Rust-owned `tools/list` slice

## What Is Implemented

### Runtime crate

Implemented in this crate:

- `GET /health`
- `GET /healthz`
- `GET /mcp`
- `GET /mcp/`
- `DELETE /mcp`
- `DELETE /mcp/`
- `POST /rpc`
- `POST /rpc/`
- `POST /mcp`
- `POST /mcp/`
- MCP protocol-version validation
- support for current compatibility versions:
  - `2025-11-25`
  - `2025-06-18`
  - `2025-03-26`
  - `2024-11-05`
- JSON-RPC parsing and validation
- JSON-RPC batch rejection
- `initialize` parameter validation
- local handling for `ping`
- notification handling with HTTP `202 Accepted`
- forwarding of non-local methods to Python over the configured backend RPC URL
- optional read-only Postgres pool for Rust-owned MCP discovery paths
- direct Rust execution for server-scoped `tools/list` after Python auth/RBAC authorization
- specialized Rust dispatch for `tools/call` to a dedicated internal backend route
- response stamping with `x-contextforge-mcp-runtime: rust`
- stripping of internal-only forwarded headers
- info-level request logging when `MCP_RUST_LOG=info`

### Gateway integration

Integrated in the main application:

- Python mounts a hybrid MCP transport app
- `GET /mcp`, `POST /mcp`, and `DELETE /mcp` are proxied to the Rust runtime
  when enabled
- `/servers/<id>/mcp` requests preserve semantics by carrying `server_id` across the Python -> Rust -> Python seam via `x-contextforge-server-id`
- Python can connect to the managed Rust runtime over `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS`
- the managed Rust runtime can listen on `MCP_RUST_LISTEN_UDS`
- Rust now forwards backend calls to `/_internal/mcp/rpc` instead of the public `/rpc` route
- Rust now forwards `initialize` to `/_internal/mcp/initialize` instead of the
  generic internal JSON-RPC switch
- Rust now forwards transport `GET`/`DELETE` calls to
  `/_internal/mcp/transport` instead of falling straight back to the public
  Python mount
- Rust can call `/_internal/mcp/tools/list/authz` to preserve Python auth/RBAC while keeping the server-scoped `tools/list` query in Rust
- Rust can call `/_internal/mcp/tools/call` to preserve Python execution while bypassing the generic JSON-RPC backend switch for the hottest MCP method
- Python forwards a trusted internal MCP auth blob via `x-contextforge-auth-context`
- the proxy strips forwarded-chain headers like `x-forwarded-for` before the internal Rust -> Python hop so loopback trust stays real
- the internal Rust-backed MCP route now creates its own `SessionLocal()` session instead of using FastAPI `Depends(get_db)`
- trusted internal dispatch now lazily materializes lowered request headers only for branches that actually need them
- token-scoping middleware now explicitly bypasses trusted loopback `/_internal/mcp/*` Rust sidecar hops so scoped tokens do not get re-denied on the private internal path
- the managed sidecar can be launched from `docker-entrypoint.sh`
- the managed sidecar can derive `MCP_RUST_DATABASE_URL` from `DATABASE_URL` for Postgres-backed direct read paths
- `Containerfile.lite` includes the Rust runtime binary when built with `ENABLE_RUST=true`
- `docker-compose.yml` exposes the Rust runtime env vars, including `MCP_RUST_LOG`

### Observability

Current observability features:

- every Rust-owned MCP response includes:
  - `x-contextforge-mcp-runtime: rust`
- the runtime logs handled methods at `info`, for example:
  - `rust_mcp_runtime method=ping mode=local`
  - `rust_mcp_runtime method=tools/list mode=backend-forward`
  - `rust_mcp_runtime method=tools/list mode=db-tools-list-direct`
  - `rust_mcp_runtime method=tools/call mode=backend-tools-call-direct`

This is the cleanest proof that live requests are actually traversing Rust.

## Current Architecture Boundary

### Rust-owned today

- outer HTTP MCP runtime shell for `GET /mcp`, `POST /mcp`, and `DELETE /mcp`
- optional UDS listener for the managed sidecar
- protocol-version compatibility checks
- JSON-RPC envelope validation
- notification response semantics
- local `ping`
- server-scoped `tools/list` authz handoff + direct read-only Postgres query path
- specialized backend dispatch for `tools/call`
- backend proxying to Python `/_internal/mcp/rpc`
- backend proxying to Python `/_internal/mcp/transport` for GET/DELETE session
  manager behavior
- runtime-level response header stamping

### Python-owned today

- authentication and token verification on the public MCP transport
- token scoping normalization
- RBAC decision-making
- creation of the forwarded internal auth context
- business execution behind the internal MCP dispatcher
- underlying `StreamableHTTPSessionManager`
- session registry
- session pool ownership
- Redis-backed caches and eventing
- SSE/resumable stream management internals
- session-affinity routing and ownership
- upstream MCP federation/client logic

### Redis / cache boundary

Redis is still entirely Python-owned today. That is intentional for this phase.

Relevant MCP-path components that still live in Python:

- auth cache in [`mcpgateway/cache/auth_cache.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/auth_cache.py)
- registry cache for tools/resources/prompts in [`mcpgateway/cache/registry_cache.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/registry_cache.py)
- session registry in [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py)
- MCP session pool setup in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
- Redis event store for resumable Streamable HTTP in [`mcpgateway/transports/redis_event_store.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/redis_event_store.py)
- cancellation pub/sub in [`mcpgateway/services/cancellation_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/cancellation_service.py)

Implication:

- the UDS and internal-dispatch optimization preserves existing Redis-assisted behavior
- moving read-only MCP list methods into Rust later will require a deliberate cache strategy instead of accidentally bypassing Python’s Redis caches

Important current nuance for the hot path:

- on the current server-scoped `MCPToolCallerUser` benchmark, Redis is not the main steady-state limiter
- `tools/call` uses Redis only on specific side paths:
  - auth cache / registry cache lookups when L1 is cold
  - cancellation pub/sub when an actual cancellation is published
  - session-affinity ownership and forwarding only if `mcpgateway_session_affinity_enabled=true`
- the MCP session pool itself is local in the current compose benchmark and does not require Redis on the success path
- live `docker stats` during the 100-user tools-only run showed gateway containers busy while Postgres and Redis stayed comparatively quiet

### Important consequence

This is not yet a full Rust rewrite of MCP in ContextForge.

It is now a transport-edge replacement for the outer `GET /mcp`, `POST /mcp`,
and `DELETE /mcp` path, with Python still acting as:

- the session manager / resumable stream core
- the policy and auth authority
- most of the execution core behind trusted internal MCP routes

That is intentional. It gives a low-risk seam that already works while keeping the next migration steps clear.

## Proven Working

The following have been validated successfully against the Rust-enabled path.

### Unit and crate tests

Validated:

- `cargo test --release` in `tools_rust/mcp_runtime`
- unit tests for the Python Rust proxy transport

These currently cover:

- `ping` handled locally
- `GET /mcp` forwarding to the internal transport bridge
- `DELETE /mcp` forwarding to the internal transport bridge
- header propagation
- runtime response header presence
- unsupported protocol version rejection
- notification `202 Accepted`
- `initialize` validation
- batch rejection
- `/mcp` aliasing
- stripping spoofed internal headers

### mcp-cli end-to-end

Validated on March 9, 2026:

- `tests/e2e/test_mcp_cli_protocol.py`
- result: `22 passed`

This exercised the live path:

- `mcp-cli`
- `mcpgateway.wrapper`
- gateway `/mcp`
- Rust runtime
- Python `/rpc`

Validated again after the specialized `tools/call` route and parity fix:

- nonexistent-tool `tools/call` once again returns a JSON-RPC error instead of a `500`
- full result remains `22 passed`

Validated again on March 10, 2026 after the raw HTTP transport parity check was
added:

- raw `POST /mcp/` and `DELETE /mcp/` now have explicit E2E proof under the
  Rust-enabled stack
- full result is now `23 passed`

Validated again on March 10, 2026 after the specialized internal initialize
route was added and the compose stack was explicitly relaunched with the Rust
runtime flags:

- `mcp-cli` initialize now reports `Server: ContextForge v1.0.0-RC-2` on the
  Rust path instead of the previous forwarded server signature
- raw `POST /mcp/` initialize again returned
  `x-contextforge-mcp-runtime: rust`
- full result remained `23 passed`

### Live compose validation

Validated on March 9, 2026:

- rebuilt `Containerfile.lite` image with `ENABLE_RUST=true`
- started compose stack with:
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
- confirmed live response header:
  - `x-contextforge-mcp-runtime: rust`
- confirmed live runtime logs for:
  - `ping`
  - `initialize`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `prompts/list`
- confirmed server-scoped hot-path logs during load:
  - `rust_mcp_runtime method=tools/call mode=backend-tools-call-direct`
  - `rust_mcp_runtime method=tools/list mode=db-tools-list-direct`

### RBAC regression coverage

Validated on March 9, 2026:

- `make test-mcp-rbac`
- result: `40 passed`

## Still Missing

The major missing items are structural, not cosmetic.

### Transport parity gaps

Not yet in Rust:

- direct Rust ownership of Streamable HTTP session lifecycle state
- direct Rust ownership of resumable event-store semantics
- direct Rust ownership of SSE event streaming orchestration
- replacement of Python `StreamableHTTPSessionManager`
- replacement of Python session-affinity and session-owner logic on the
  transport path

### Core execution gaps

Not yet moved into Rust:

- direct Rust ownership of `tools/call`
- direct Rust ownership of `resources/*`
- direct Rust ownership of `prompts/*`
- a narrower internal dispatcher contract than Python `/rpc`

### Security/control-path gaps

Still Python-owned:

- auth enforcement
- token team normalization
- RBAC permission checks
- server-scoped execution policies
- OAuth-related MCP/session policies

These are not accidental omissions. They are part of the current staged migration boundary.

## Known Risks / Open Issues

### 1. Rust fronts the MCP transport, but Python still owns session state

This is the most important current limitation.

External MCP clients now hit Rust for `GET /mcp`, `POST /mcp`, and
`DELETE /mcp`, but the actual session manager and resumable transport state are
still Python-owned behind the internal transport bridge.

That means:

- Rust currently owns the public transport edge
- Python still owns the stateful transport internals
- a fully replaceable Rust MCP transport still requires moving the underlying
  session/event-store machinery out of Python

### 2. `/rpc` is still the real backend contract

Rust no longer needs the public `/rpc` route, but it still forwards most work to Python in a JSON-RPC-shaped backend contract.

That means:

- Rust does not yet reduce Python business-logic coupling much
- the current performance gains are mostly transport-edge and dispatcher-seam gains
- the real modularity win still requires extracting a cleaner dispatcher/core contract than a generic JSON-RPC passthrough

### 3. Performance is still dominated by the seam

The highest-leverage performance work so far has not been inside Rust business logic.

It has been reducing avoidable Python work around the Rust edge:

- Rust backend responses now stream back to the client instead of buffering in Python first
- Python no longer reparses and rewrites JSON request bodies just to attach `server_id` for `/servers/<id>/mcp`
- server scope now crosses the seam in an internal header instead of a body mutation
- the managed sidecar can now use UDS instead of loopback HTTP
- public transport auth is now forwarded as a trusted internal context instead of being recomputed on the internal backend hop
- the trusted internal dispatcher no longer pays `Depends(get_db)` setup/teardown overhead on every Rust-backed call
- trusted internal dispatch no longer revalidates JSON-RPC envelopes that Rust already validated

This matters because the load-test target in `tests/loadtest/locustfile_mcp_protocol.py` is the server-scoped MCP path, so every unnecessary parse/serialize on that path shows up directly in throughput and latency.

### 4. `tools/call` is now the real performance wall

The cleanest current benchmark is the server-scoped tools-only run:

```text
uv run locust -f tests/loadtest/locustfile_mcp_protocol.py \
  --host=http://localhost:8080 \
  --users=100 \
  --spawn-rate=100 \
  --run-time=30s \
  --headless --only-summary \
  MCPToolCallerUser
```

Observed results on March 9, 2026:

- overall: about `715` to `746 RPS`
- `MCP tools/call [rapid]`: about `677` to `707 RPS`
- failures: `0%`

This matters more than the mixed protocol benchmark now:

- it removes most discovery noise
- it proves the remaining ceiling is in the Python `tools/call` executor path
- it makes the next architectural step clear: more Python seam trimming will have diminishing returns compared with moving actual tool execution out of Python

Practical note:

- `--tags toolcall` is **not** a clean measurement for this locustfile because Locust still instantiates the other user classes and they end up with no runnable tasks after tag filtering
- use explicit `MCPToolCallerUser` class selection instead
### 5. Benchmark noise still exists in seeded data

The current compose seed data on the fast-time server includes duplicate resource URIs.

That means `resources/read` is currently a noisy benchmark signal, independent of the Rust seam:

- `resources/list` succeeds through Rust
- manual `resources/read` on the same server returns:
  - `Multiple rows were found when one or none was required`
- Locust records that as JSON-RPC `-32000 Internal error`

This is a correctness issue in the seeded benchmark fixture, not evidence that the UDS/internal-dispatch seam broke `resources/read`.

### 6. Wider regression coverage is mostly back to green

As of March 9, 2026:

- `mcp-cli` E2E is green
- `make test-mcp-rbac` is green again after fixing scoped-token initialize on the internal Rust -> Python hop
- direct live Rust-path checks are green for:
  - `/mcp`
  - `/servers/<id>/mcp initialize`
  - `/servers/<id>/mcp tools/list`
  - `/servers/<id>/mcp tools/call`
- explicit log proof now shows:
  - `rust_mcp_runtime method=tools/list mode=db-tools-list-direct`
- `make test-ui-headless` is still the main broader parity check left to keep exercising externally

So the Rust transport edge plus the first Rust-owned read path are proven on the main MCP CLI and RBAC paths, but broader UI parity is still worth keeping under test.

### 7. Startup noise in compose

The current compose stack still emits pre-existing bootstrap duplicate-key warnings during startup in some seeded environments.

Those warnings did not prevent:

- healthy containers
- Rust-side request handling
- `mcp-cli` success

But they do make debugging noisier than it should be.

## Recommended Next Steps

### Phase 1: continue transport/session parity

Immediate priorities:

- keep the new Rust-fronted `GET`/`DELETE` transport boundary under broader
  suite coverage
- add explicit live validation for server-scoped `GET /servers/<id>/mcp` and
  `DELETE /servers/<id>/mcp`
- move the next transport internals behind the same Rust seam:
  - session-lifecycle state ownership
  - resumable event-store behavior
  - multi-worker session-affinity / owner checks
- keep the public mount shape stable while shrinking Python’s transport-specific
  internals behind `/_internal/mcp/transport`

### Phase 2: remove the remaining generic dispatcher coupling

The next architectural cleanup after transport parity is to stop treating
generic Python JSON-RPC dispatch as the long-term internal contract.

Recommended direction:

1. Keep the existing dedicated internal routes as the baseline:
   - `/_internal/mcp/transport`
   - `/_internal/mcp/initialize`
   - `/_internal/mcp/tools/list`
   - `/_internal/mcp/tools/call`
2. Add more narrow internal contracts instead of expanding `/_internal/mcp/rpc`.
3. Move the remaining generic MCP lifecycle methods off the dispatcher next:
   - `notifications/message`
   - `notifications/cancelled`
   - any remaining session-lifecycle-specific helper paths
4. Keep Python authoritative for auth/RBAC while these seams are being split.

### Phase 3: move the remaining read-only MCP discovery paths

After the transport and dispatcher seams are cleaner, move the remaining
read-only methods into Rust with direct Postgres reads:

- `resources/list`
- `prompts/list`
- `resources/templates/list`
- then `resources/read` and `prompts/get`

### Phase 4: finish the `tools/call` migration

The hottest path still deserves the most care.

Recommended direction:

1. Keep the current `backend-tools-call-direct` seam as the baseline.
2. Keep the Python `tools/call` policy/resolve step narrow and explicit.
3. Move more of session reuse and upstream call execution under Rust ownership.
4. Keep cancellation, metrics, and broader session ownership Python-owned until
   measurements prove they are the next limiter.

### Phase 5: decide the long-term control-plane boundary

At that point there are two viable end states:

- Rust owns transport and MCP execution, while Python remains auth/RBAC and
  policy authority
- or Rust becomes a fully replaceable MCP subsystem and Python is reduced to a
  separate control plane

## Performance Investigation Update

### What was tested on the rebased branch

Using the load-test tooling now on `origin/main`:

- `tests/loadtest/locustfile_mcp_protocol.py`
- direct `locust` runs following `todo/performance/reproduce-testing.md`
- live compose stack built from the rebased image with:
  - `ENABLE_RUST_BUILD=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`

### What profiling showed

A short live `py-spy` sample on a loaded gunicorn worker was noisy, but directionally useful:

- the worker spent most sampled time inside AnyIO / threadpool worker activity rather than in the Rust sidecar
- that pointed at Python request/dependency machinery as the next no-DB optimization target
- the biggest actionable item from that result was removing FastAPI `Depends(get_db)` from the trusted internal MCP route

### Important test hygiene note

The first post-rebase comparison attempt produced invalid results because server-scoped MCP discovery briefly fell back to global discovery after an overly strict backend trust check for the internal `server_id` header.

Symptoms were:

- `tools/list` on `/servers/<id>/mcp` returning global tools/resources/prompts instead of the selected server scope
- `resources/read` failures in Locust because discovery and execution no longer matched

That bug was fixed by making `/rpc` honor `x-contextforge-server-id` whenever the request is marked as coming from the Rust runtime via `x-contextforge-mcp-runtime: rust`.

### Current measured impact of the latest no-DB seam optimization batch

The latest optimization stack is now:

- narrower internal Python dispatcher at `/_internal/mcp/rpc`
- trusted forwarded MCP auth context
- no Python JSON body rewriting for `/servers/<id>/mcp`
- UDS between Python and the managed Rust sidecar
- admin-permission short-circuit after token-scope enforcement
- direct `SessionLocal()` management on the trusted internal Rust -> Python MCP route
- no Pydantic `RPCRequest` validation on trusted internal dispatch
- lazy lower-casing of request headers only when needed
- conversion of several hot-path f-string logs to lazy logging calls
- dedicated internal `/_internal/mcp/tools/list` path for server-scoped discovery
- lean `tool_service.list_server_mcp_tool_definitions(...)` output that skips `ToolRead` conversion
- Rust-side specialized mode logging: `rust_mcp_runtime method=tools/list mode=backend-tools-list-direct`
- container launch hardening so an empty `MCP_RUST_LISTEN_UDS` env no longer breaks the managed sidecar startup

These numbers are from live server-scoped `100 users / 30s` Locust runs following `todo/performance/reproduce-testing.md`.

Repeated pre-batch runs on the same rebuilt Rust-enabled stack settled around:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 671.73 | 51.48   | 84  | 210 | 1.88%
2   | 671.64 | 52.51   | 91  | 200 | 1.95%
```

Post-batch runs on the same stack:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 692.41 | 41.07   | 69  | 190 | 1.88%
2   | 722.22 | 41.05   | 69  | 160 | 1.92%
```

Failure caveat for all of these runs:

- the failures are all `resources/read`
- they trace to duplicate seeded resource URIs on the benchmark server
- they are not specific to the new Rust seam

Interpretation:

- the repeated pre-batch baseline is about `672 RPS`
- the first post-batch run is about `+3.1%` RPS with about `-20%` average latency
- the warmed post-batch rerun is about `+7.5%` RPS with about `-22%` average latency and materially lower `p95` / `p99`
- the warmed best run is still slightly below the earlier one-off `738 RPS` UDS/header-forward peak, so that earlier number should be treated as a high-water mark, not the stable baseline

Conclusion:

- this non-DB optimization batch is worth keeping
- the current stable improvement comes from removing Python internal-dispatch overhead, not from changing Rust transport parsing
- the current bottleneck is still Python-owned execution and data access behind the Rust edge
- there is still headroom, but the remaining big wins are now unlikely to come from more Python-side no-DB micro-optimizations

### Follow-up result: dedicated server-scoped `tools/list` seam

After the generic `/_internal/mcp/rpc` trimming work, one more Python-owned seam optimization was added:

- server-scoped `tools/list` now goes to `/_internal/mcp/tools/list`
- Python still owns auth/RBAC and DB access for that path
- Rust no longer forwards that method through the generic JSON-RPC switch
- Python no longer builds full `ToolRead` models for this path

Live validation on the rebuilt Rust-enabled compose stack:

- public MCP responses still include `x-contextforge-mcp-runtime: rust`
- gateway logs now show:

```text
rust_mcp_runtime method=tools/list mode=backend-tools-list-direct
```

- full `tests/e2e/test_mcp_cli_protocol.py` still passes against the rebuilt image (`22 passed`)

Measured `100 users / 30s` runs after this dedicated `tools/list` cut:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 672.23 | 45.01   | 83  | 180 | 1.94%
2   | 700.04 | 45.94   | 87  | 170 | 1.86%
```

Endpoint-level effect from the warmed second run:

- `MCP tools/list`: `51.87 RPS`, `28.8ms avg`, `130ms p99`
- `MCP tools/list [churn]`: `31.48 RPS`, `28.9ms avg`, `110ms p99`
- `MCP tools/list [rapid]`: `11.34 RPS`, `27.8ms avg`, `80ms p99`

Interpretation:

- this seam is correct, live, and leaner than the generic `/rpc` path
- it improves the `tools/list` slice, but it does **not** materially move the full protocol mix by itself
- that is expected because `tools/call` remains the dominant request class in the load test
- this is the clearest point where further Python-owned no-DB seam work has diminishing returns

### Phase result: Rust-owned server-scoped `tools/list`

This phase moved the first real read-only MCP query into Rust:

- Rust now handles server-scoped `tools/list` as `db-tools-list-direct`
- Python still owns auth/RBAC through `/_internal/mcp/tools/list/authz`
- Rust now queries Postgres directly for the tool list after Python authorizes the request
- if the Rust DB path fails, the runtime falls back to the Python `/_internal/mcp/tools/list` endpoint instead of breaking the request path

One parity bug appeared immediately after this cut:

- scoped tokens with explicit permissions could no longer `initialize` through `mcpgateway.wrapper`
- root cause: token-scoping middleware was re-checking the private `/_internal/mcp/*` Rust -> Python hop and denying the unmatched internal path
- fix: trusted loopback Rust-sidecar requests marked with `x-contextforge-mcp-runtime: rust` and `x-contextforge-auth-context` now bypass token-scoping path checks on the internal hop

Validated after that fix on the rebuilt Rust-enabled compose stack:

- `cargo test --release` in `tools_rust/mcp_runtime`: `12 passed`
- targeted middleware + internal-MCP unit coverage: passed
- `tests/e2e/test_mcp_cli_protocol.py`: `22 passed`
- `make test-mcp-rbac`: `40 passed`
- live server-scoped `tools/list` proof with response header `x-contextforge-mcp-runtime: rust`
- live gateway log proof:

```text
rust_mcp_runtime method=tools/list mode=db-tools-list-direct
```

Pinned `Fast Time Server` load-test samples on the rebuilt stack:

```text
Users | RPS    | Avg(ms) | Failures
50    | 441.76 | 19.04   | 0.00%
100   | 741.01 | 40.37   | 0.00%
```

Compared with the earlier UDS/header-forward baseline recorded in this memo:

- `50 users`: `424.82 -> 441.76` RPS, a small but real improvement
- `100 users`: `738.44 -> 741.01` RPS, effectively flat at peak load

Interpretation:

- this is the expected shape for moving only `tools/list`
- the change is correct, live, and worth keeping
- it does **not** dramatically change the overall protocol ceiling because `tools/call` still dominates the workload mix
- the next meaningful throughput gains now depend on moving more read-heavy discovery methods and, eventually, reducing Python-owned `tools/call`

### Follow-up result: specialized `tools/call` seam

The next tools-focused phase specialized the hottest method without changing its underlying execution model:

- Rust now routes `tools/call` to `/_internal/mcp/tools/call`
- Python still owns actual tool execution
- Python now uses a dedicated helper for the `tools/call` branch instead of going through the full generic `/rpc` method switch
- server-scoped tool lookup now narrows candidates by `server_id` earlier before upstream execution
- the specialized route preserves JSON-RPC parity for nonexistent tools

Validated on the rebuilt compose stack:

- `tests/e2e/test_mcp_cli_protocol.py`: `22 passed`
- `make test-mcp-rbac`: `40 passed`
- live gateway logs during load:

```text
rust_mcp_runtime method=tools/call mode=backend-tools-call-direct
rust_mcp_runtime method=tools/list mode=db-tools-list-direct
```

Clean server-scoped `MCPToolCallerUser` measurements:

```text
Users | Overall RPS | tools/call RPS | Avg(ms) | p95 | p99 | Failures
50    | 600.54      | 570.65         | 26.16   | 38  | 80  | 0.00%
100   | 715.14      | 676.72         | 85.62   | 140 | 240 | 0.00%
100   | 746.25      | 706.95         | 80.02   | 130 | 210 | 0.00%
```

Interpretation:

- this phase is correct and worth keeping
- it proves the live hot path is flowing through Rust exactly where intended
- it does **not** get the stack near `1000 RPS`
- the remaining ceiling is now dominated by Python-owned `tools/call` execution and the Python MCP client/session machinery, not by the outer Rust seam

### Next performance steps in priority order

1. Keep the current tools baseline:
   - `tools/list` in Rust as `db-tools-list-direct`
   - `tools/call` specialized as `backend-tools-call-direct`
2. Move actual `tools/call` execution out of Python with a narrow Python authz/metadata seam.
3. Keep Python authoritative for auth/RBAC during that phase.
4. Keep Redis/session/cancellation ownership in Python during that phase unless measurements prove they are the next limiter.
5. After the hot `tools/call` path is reduced, move the remaining read-heavy methods:
   - `resources/list`
   - `prompts/list`
   - `resources/templates/list`
6. Only then evaluate whether `initialize` or broader session orchestration should move deeper into Rust.

### Phase 2: remove Python `/rpc` coupling

Next architectural step:

- extract a shared internal MCP dispatcher contract from the current Python RPC handler
- point both Python transport and Rust runtime at the same execution contract
- stop treating a generic JSON-RPC passthrough as the long-term internal interface

This is the step that turns the current transport-edge replacement into real modularization.

### Phase 3: move session orchestration

Then:

- move Streamable HTTP session handling into Rust
- implement resumable session behavior in Rust
- replace more of the Python session registry transport path

### Phase 4: move execution primitives

After the dispatcher seam is real and the benchmark fixture is clean:

- keep `tools/list`
- move `tools/call`
- then move `resources/list`
- move `prompts/list`
- move `resources/templates/list`
- move more direct MCP response shaping into Rust

## How To Run

### Local crate only

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/_internal/mcp/rpc \
  --listen-http 127.0.0.1:8787
```

### Docker image

```bash
docker build --build-arg ENABLE_RUST=true -f Containerfile.lite .
```

### Compose stack

```bash
ENABLE_RUST_BUILD=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock \
MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock \
docker compose --profile testing up -d --force-recreate gateway nginx
```

Optional runtime tuning:

```bash
MCP_RUST_LOG=info
MCP_RUST_LISTEN_HTTP=127.0.0.1:8787
MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock
MCP_RUST_BACKEND_RPC_URL=http://127.0.0.1:4444/_internal/mcp/rpc
MCP_RUST_DATABASE_URL=postgresql://contextforge:contextforge@pgbouncer:6432/contextforge
MCP_RUST_DB_POOL_MAX_SIZE=20
```

## How To Verify It Is Going Through Rust

### 1. Check the response header

Any Rust-owned MCP response should include:

```text
x-contextforge-mcp-runtime: rust
```

Example:

```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret my-test-key | tail -n1)

curl -i http://localhost:8080/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H "authorization: Bearer $TOKEN" \
  --data '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
```

For the server-scoped path used by the MCP load test, a stronger verification is:

```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret my-test-key | tail -n1)
SERVER_ID=<server-id>

curl -s -X POST http://localhost:8080/servers/$SERVER_ID/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-protocol-version: 2024-11-05" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("result",{}).get("tools",[])))'
```

If server scoping is correct, this should return the tool count for that specific virtual server, not the global registry.

### 2. Check the logs

```bash
docker compose logs -f gateway | rg "rust_mcp_runtime method="
```

Expected examples:

```text
Starting experimental Rust MCP runtime on unix:///tmp/contextforge-mcp-rust.sock
rust_mcp_runtime method=ping mode=local
rust_mcp_runtime method=initialize mode=backend-initialize-direct
rust_mcp_runtime method=tools/list mode=db-tools-list-direct
rust_mcp_runtime method=tools/call mode=backend-tools-call-direct
```

### 3. Remember the current boundary

Rust now fronts MCP `GET`, `POST`, and `DELETE` traffic at the public mount.

These still remain Python-owned behind the internal transport seam:

- session-management internals
- resumable event-store behavior
- session-affinity / session-owner logic

## Test Commands

### Fast checks

```bash
cd tools_rust/mcp_runtime
cargo test --release
```

```bash
uv run pytest -q tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py
```

```bash
uv run pytest -q \
  tests/unit/mcpgateway/test_main_extended.py -k 'InternalTrustedMcpTransportBridge or internal_mcp_rpc or rust_server_header or tools_list_server'
```

### End-to-end MCP CLI

```bash
MCP_CLI_BASE_URL=http://localhost:8080 \
JWT_SECRET_KEY=my-test-key \
PLATFORM_ADMIN_EMAIL=admin@example.com \
MCP_CLI_TIMEOUT=60 \
uv run pytest tests/e2e/test_mcp_cli_protocol.py -v -s --tb=short
```

### Reproduce the protocol load test directly

```bash
source .venv/bin/activate
MCP_SERVER_ID=<server-id> \
locust -f tests/loadtest/locustfile_mcp_protocol.py \
  --host=http://localhost:8080 \
  --users=100 \
  --spawn-rate=100 \
  --run-time=30s \
  --headless
```

For apples-to-apples comparisons, pin `MCP_SERVER_ID` to the same virtual server across runs instead of relying on auto-detection.

### Reproduce the tools-only hot-path benchmark

```bash
source .venv/bin/activate
locust -f tests/loadtest/locustfile_mcp_protocol.py \
  --host=http://localhost:8080 \
  --users=100 \
  --spawn-rate=100 \
  --run-time=30s \
  --headless \
  --only-summary \
  MCPToolCallerUser
```

Use the explicit `MCPToolCallerUser` class selection for this benchmark.

Do **not** use `--tags toolcall` as a substitute; with this locustfile, Locust will still instantiate the other user classes and they will report noisy "no tasks defined" errors after tag filtering.

### Broader regression suites

Validated on the rebuilt Rust-enabled stack:

```bash
make test-mcp-rbac
```

Still worth keeping in the parity loop:

```bash
make test-ui-headless
```

If the local environment uses the repo-local virtualenv rather than `$(HOME)/.venv/mcpgateway`, make sure the Makefile environment is aligned before drawing conclusions from failures.

## Files That Matter Most

Primary implementation:

- `tools_rust/mcp_runtime/src/lib.rs`
- `tools_rust/mcp_runtime/src/config.rs`
- `tools_rust/mcp_runtime/tests/runtime.rs`

Python integration:

- `mcpgateway/transports/rust_mcp_runtime_proxy.py`
- `mcpgateway/main.py`
- `mcpgateway/config.py`
- `docker-entrypoint.sh`
- `Containerfile.lite`
- `docker-compose.yml`

## Bottom Line

The Rust MCP runtime is already real enough to use as the live public MCP
transport edge for `GET /mcp`, `POST /mcp`, and `DELETE /mcp`.

It now also owns the first real read-only MCP query in production shape: server-scoped `tools/list` with direct Postgres reads behind Python-owned auth/RBAC.

It is not yet the complete MCP implementation for ContextForge.

The remaining work is mostly:

- moving the underlying session-manager and resumable transport internals out of Python
- narrowing and replacing the remaining generic internal dispatcher routes
- moving the remaining read-only discovery queries (`resources/list`, `prompts/list`, `resources/templates/list`) into Rust with direct Postgres reads
- deciding how much of session orchestration and `tools/call` ownership should ultimately live in Rust versus a Python control plane

That is a credible migration path. The current implementation has moved from a
Rust `POST` accelerator into a Rust-fronted MCP transport with the first real
Rust-owned MCP core slice, but it is not yet the final Rust end state.
