# Developing The Rust MCP Runtime

This guide is the practical command checklist for developing
[`crates/mcp_runtime`](.) and the Python integration around it.

Use it together with:

- [README.md](README.md) for runtime architecture, modes, and operator workflows
- [STATUS.md](STATUS.md) for the current branch-local validation and benchmark snapshot
- [TESTING-DESIGN.md](TESTING-DESIGN.md) for the session/auth isolation threat model

## Scope

Changes in the Rust MCP runtime often affect more than the crate itself. A
single feature can touch:

- the Rust runtime crate
- Python integration in `mcpgateway/`
- Docker/compose startup wiring
- MCP end-to-end tests
- admin UI pages such as Overview and Version Info
- load-test and benchmark behavior

That means a complete development loop is usually layered:

1. fast Rust-local checks
2. broader Python/backend checks
3. live compose-backed MCP validation
4. UI validation when relevant
5. benchmark and profiling work when performance-sensitive paths changed

## Command Matrix

Use the smallest set that matches your change.

| Change type | Minimum checks |
| --- | --- |
| Pure Rust refactor in `src/` or `tests/` | `make -C crates/mcp_runtime fmt-check clippy-all test test-rmcp` |
| Rust + Python integration change | Rust-local checks plus `make doctest test htmlcov` |
| MCP protocol, auth, session, or transport behavior | Rebuild stack and run `make test-mcp-protocol-e2e test-mcp-rbac`; add `make test-mcp-plugin-parity` with `PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml` for live plugin parity, `make test-mcp-access-matrix` for detailed role/output verification, `make test-mcp-session-isolation` for Rust public path work, and `make test-mcp-session-isolation-load` for correctness-under-load changes |
| Overview / Version Info / templates / JS / CSS | `make test-js-coverage lint-web bandit interrogate pylint`, plus `make test-ui-smoke` and targeted Playwright tests |
| Packaging / release readiness | `make verify` |
| Performance-sensitive hot path | relevant tests plus benchmark and profiling targets |

## Fast Inner Loop

For day-to-day Rust work, stay in the crate until the code shape is stable.

```bash
make -C crates/mcp_runtime fmt-check
make -C crates/mcp_runtime check
make -C crates/mcp_runtime clippy
make -C crates/mcp_runtime clippy-all
make -C crates/mcp_runtime test
make -C crates/mcp_runtime test-rmcp
```

What these cover:

- `fmt-check`: formatting drift
- `check`: compile/type issues without full test cost
- `clippy`: default all-target lint pass
- `clippy-all`: all-targets, all-features lint pass
- `test`: default Rust tests
- `test-rmcp`: upstream RMCP client feature coverage

Use these when:

- editing `src/lib.rs`, `src/config.rs`, `src/main.rs`
- changing request routing, auth/session logic, direct DB paths, or helpers
- touching the optional RMCP path

## Repo-Wide Hygiene

These are the standard root-level formatting and linting commands the repo
expects before a serious validation pass.

```bash
make autoflake isort black pre-commit
make test-js-coverage lint-web bandit interrogate pylint verify
make doctest test htmlcov
```

Notes:

- `make autoflake isort black pre-commit`
  - use after broader edits, especially mixed Python/template/doc changes
- `make test-js-coverage lint-web bandit interrogate pylint verify`
  - this is the wider hygiene gate for Python, docs, web assets, and package
    metadata
- `make doctest test htmlcov`
  - this is the main broad backend confidence pass

Important behavior:

- `make test` is a broad Python test run against the `tests/` tree with
  selected ignores
  - it does **not** run Playwright
  - it does **not** run performance/compliance suites
  - it now ignores `tests/e2e_rust/`, so Rust-mode-only live tests do not pollute
    the default backend test run
- `make doctest` runs doctests against `mcpgateway/`
- `make htmlcov` builds an HTML coverage report from `.coverage`
- `make verify` builds the Python package and runs metadata/manifest checks

## Recommended Root-Level Validation

For most MCP runtime PR work, this is the minimum serious root-level gate:

```bash
make doctest test htmlcov
make bandit interrogate pylint
```

Add these when you touched UI/templates/static files:

```bash
make test-js-coverage
make lint-web
make test-ui-smoke
```

Add this when the change is close to shipping:

```bash
make verify
```

## GET /mcp Stream Relay (ADR-052)

The Rust live-stream branch in `forward_transport_request` (`src/lib.rs`)
relays Python's `GET /mcp` SSE stream byte-for-byte after parsing it back
into typed `Event` frames. As of ADR-052, Python serves a spec-conformant
SSE stream backed by a per-session event bus (Redis Pub/Sub + ring buffer in
multi-node, in-process deque + `asyncio.Event` in single-node). The relay
itself did not need code changes — it inherited the new behavior the moment
Python stopped returning 405.

What this means for development:

- The `session_id.is_none()` 405 in the live-stream branch is spec-mandated
  (GET requires a session id) and stays. Tests that assert on this 405 are
  still valid.
- For the GET-with-session path, the relay opens an upstream GET to Python's
  `/mcp`, parses the resulting SSE byte stream, and re-emits each frame.
  No Rust event-bus machinery needed; Python is the source of truth.
- The Pub/Sub channel (`mcp:session:{sid}:events`) and event-store keys
  (`mcpgw:eventstore:{sid}:*`) are owned by Python. Rust does not write to
  them in v1. A future iteration could have Rust subscribe directly to skip
  the Python hop, but the current relay is the simpler design and keeps the
  fanout policy in one place.
- `live_stream_core_enabled()` continues to gate this path; deployments
  that want Python to serve the stream end-to-end (no Rust relay) leave
  this disabled and let the request fall through to the Python proxy.

When debugging GET-stream failures, check Python first — `make logs` for
`ServerEventBus` lines reveals the chosen backend and any publish errors.

## Compose-Backed MCP Validation

Rust-local tests are not enough for this runtime. You also need live validation
against the compose-backed gateway.

### Python Baseline

Use this when you want to confirm the non-Rust public MCP path still behaves
correctly.

```bash
make testing-down
make compose-clean
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
make testing-up
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-up
MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=python make test-mcp-plugin-parity
```

Expected outcome:

- `/health` reports Python MCP mode
- `make test-mcp-protocol-e2e` passes, with the Rust-only raw-header assertion skipped
- `make test-mcp-rbac` passes
- `make test-mcp-access-matrix` passes and verifies scoped-user access with
  strong tool/resource/prompt sentinels
- `make test-mcp-plugin-parity` passes with the Python runtime header and proves
  active `resource_post_fetch`, `tool_post_invoke`, and `prompt_post_fetch`
  behavior on the public MCP path

### Rust Shadow

Use this when validating that Rust can be present without owning the public MCP
path.

```bash
make testing-rebuild-rust-shadow
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
```

Expected outcome:

- public `/mcp` still behaves like Python mode
- `/health` shows Rust present internally but Python mounted publicly

### Rust Edge

Use this when validating the Rust public transport edge without the full Rust
session/event-store stack.

```bash
make testing-rebuild-rust
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
```

### Rust Full

Use this when validating the fullest Rust path and any session/replay/live
stream/auth reuse changes.

```bash
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
make test-mcp-session-isolation
make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-rebuild-rust-full
MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=rust make test-mcp-plugin-parity
```

Expected outcome:

- `/health` reports Rust-managed runtime and Rust-mounted public transport
- `make test-mcp-protocol-e2e` passes
- `make test-mcp-rbac` passes
- `make test-mcp-access-matrix` passes on the Rust path
- `make test-mcp-session-isolation` passes on the Rust path
- `make test-mcp-session-isolation-load` validates owner traffic and hijack
  denial under concurrent Locust load
- `make test-mcp-plugin-parity` passes with the Rust runtime header and proves
  the live plugin hooks still affect public MCP `resources/read`,
  `tools/call`, and `prompts/get`
- release Rust tests pass

For revocation and membership/role-drift changes, validate with a short reuse
TTL so the bounded-TTL contract completes quickly:

```bash
MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full
make test-mcp-session-isolation
make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s
make test-mcp-access-matrix
```

## Verify What Is Actually Running

Do not assume the stack is in the mode you intended. Check it.

```bash
curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'
```

What to look for:

- Python baseline:
  - `x-contextforge-mcp-runtime-mode: python`
  - `x-contextforge-mcp-transport-mounted: python`
- Rust shadow:
  - `x-contextforge-mcp-runtime-mode: rust-managed`
  - `x-contextforge-mcp-transport-mounted: python`
- Rust edge/full:
  - `x-contextforge-mcp-runtime-mode: rust-managed`
  - `x-contextforge-mcp-transport-mounted: rust`

If you changed the admin UI runtime display, also verify:

- Overview page shows `🐍 Python MCP Core` or `🦀 Rust MCP Core`
- Version Info page shows the MCP runtime card with the correct mounted/core
  modes

## UI And Web Checks

You do not need these for every pure Rust refactor. You do need them when the
change touches:

- `mcpgateway/templates/`
- `mcpgateway/static/`
- `mcpgateway/admin.py`
- `mcpgateway/version.py`
- Overview / Version Info runtime display

Recommended UI/web checks:

```bash
make test-js-coverage
make lint-web
make test-ui-smoke
uv run pytest tests/playwright/test_version_page.py -q
```

Broader UI pass:

```bash
make test-ui-headless
```

Note:

- `make test-ui-headless` exercises broad repo UI behavior and can expose
  unrelated flaky admin flows
- use targeted Playwright files first when you only changed one page

## Coverage Workflows

For Python coverage:

```bash
make coverage
make htmlcov
make doctest-coverage
make diff-cover
```

For Rust coverage:

```bash
make -C crates/mcp_runtime coverage
```

Coverage guidance:

- use `make htmlcov` for a fast local report once `.coverage` already exists
- use `make coverage` when you need to regenerate the full Python coverage set
- use `make diff-cover` when you need changed-line coverage against the main
  branch
- use runtime-local `coverage` when you are explicitly improving Rust crate
  coverage

## Benchmarking

Benchmark from the repository root against a compose-backed testing stack.

Quick benchmarks:

```bash
make benchmark-mcp-mixed
make benchmark-mcp-tools
```

Higher-concurrency distributed benchmarks:

```bash
make benchmark-mcp-mixed-300
make benchmark-mcp-tools-300
```

Useful overrides:

```bash
make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=60s
make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s
make benchmark-mcp-mixed-300 MCP_BENCHMARK_HIGH_USERS=300 MCP_BENCHMARK_HIGH_RUN_TIME=60s
```

How to read the results:

- `benchmark-mcp-tools*`
  - cleanest signal for the Rust hot path
  - use this when evaluating transport/runtime improvements
- `benchmark-mcp-mixed*`
  - exercises broader seeded data and fixture behavior
  - useful, but noisier than tools-only numbers

Expected outcomes:

- Rust `edge|full` should materially outperform the pure Python path on the
  tools-only workload
- `shadow` should behave like the Python public path, not like the Rust public
  path
- compare current results against the latest snapshot in [STATUS.md](STATUS.md)
  rather than treating one hardcoded number as a release threshold

## Profiling

For Rust-local profiling:

```bash
make -C crates/mcp_runtime setup-profiling
make -C crates/mcp_runtime flamegraph-test
make -C crates/mcp_runtime flamegraph-test-rmcp
```

Artifacts are written under:

```text
crates/mcp_runtime/profiles/
```

When to use profiling:

- after a benchmark regression
- after a change to direct `tools/call`, session handling, event store, or RMCP
  client reuse
- when you need proof that a suspected Rust hotspot is real

Interpretation guidance:

- one-shot flamegraphs are often setup-heavy
- steady-state compose benchmarks are still the primary signal for end-to-end
  throughput
- if a benchmark regresses but the crate-local flamegraph does not show a Rust
  hotspot, the issue may be in Python, upstream MCP servers, networking, Redis,
  or compose/container behavior

## Suggested Workflows

### 1. Pure Rust Refactor

```bash
make -C crates/mcp_runtime fmt-check
make -C crates/mcp_runtime clippy-all
make -C crates/mcp_runtime test-rmcp
```

### 2. Rust + Python MCP Integration Change

```bash
make -C crates/mcp_runtime fmt-check clippy-all test-rmcp
make doctest test htmlcov
make bandit interrogate pylint
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
make test-mcp-session-isolation
```

### 3. Runtime UI / Admin Page Change

```bash
make autoflake isort black pre-commit
make test-js-coverage lint-web bandit interrogate pylint
make doctest test htmlcov
make test-ui-smoke
uv run pytest tests/playwright/test_version_page.py -q
```

### 4. Performance-Sensitive Change

```bash
make -C crates/mcp_runtime fmt-check clippy-all test-rmcp
make testing-rebuild-rust-full
make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=60s
make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s
make -C crates/mcp_runtime flamegraph-test
```

### 5. Pre-Push / Pre-Merge Gate

```bash
make autoflake isort black pre-commit
make test-js-coverage lint-web bandit interrogate pylint verify
make doctest test htmlcov
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
make test-mcp-session-isolation
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
```

If the change affects fallback behavior or public MCP mounting:

```bash
make testing-up
make test-mcp-protocol-e2e
make test-mcp-rbac
```

## What "Good" Looks Like

Before calling a Rust MCP runtime change ready, the following should be true
for the scopes you touched:

- Rust-local lint/test passes
- repo-wide Python/backend lint/test passes
- live compose-backed MCP tests pass in the relevant runtime mode
- Python baseline still works if you changed shared transport or fallback logic
- benchmark results are not materially worse than the current branch snapshot in
  [STATUS.md](STATUS.md) without a clear explanation
- UI pages render the correct runtime mode if you touched admin/status surfaces

If you are unsure which commands to run, default to the broader workflow:

```bash
make autoflake isort black pre-commit
make test-js-coverage lint-web bandit interrogate pylint verify
make doctest test htmlcov
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
make test-mcp-session-isolation
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
```
