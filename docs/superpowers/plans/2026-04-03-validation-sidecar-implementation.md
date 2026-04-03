# Validation Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the PyO3-backed request-body validation accelerator with a UDS-only Rust sidecar, while preserving the existing Python validator as the default path and keeping the legacy PyO3 path available for transition benchmarking.

**Architecture:** The existing validation middleware remains the activation point behind `validation_middleware_enabled` and `experimental_validate_io`. A new Rust sidecar binary under `tools_rust/validation_sidecar` becomes the authoritative body-validation backend when `experimental_rust_validation_sidecar_enabled` is set. Python sends framed requests over a Unix domain socket, maps validation responses to existing `422` behavior, and returns `503` for sidecar transport/readiness failures.

**Tech Stack:** FastAPI/Starlette middleware, Python `socket` or `asyncio` UDS client code, Rust sidecar binary, `simd-json`, `serde_json`, `tokio`, repo config/docs/Helm surfaces, pytest, cargo test.

---

## File Structure

### Gateway integration

- Modify: `mcpgateway/config.py`
- Modify: `mcpgateway/middleware/validation_middleware.py`
- Create: `mcpgateway/services/validation_sidecar_client.py`
- Test: `tests/unit/mcpgateway/middleware/test_validation_middleware.py`
- Test: `tests/unit/mcpgateway/services/test_validation_sidecar_client.py`

### Rust sidecar

- Create: `tools_rust/validation_sidecar/Cargo.toml`
- Create: `tools_rust/validation_sidecar/src/main.rs`
- Create: `tools_rust/validation_sidecar/src/lib.rs`
- Create: `tools_rust/validation_sidecar/src/protocol.rs`
- Create: `tools_rust/validation_sidecar/src/validator.rs`
- Create: `tools_rust/validation_sidecar/tests/runtime.rs`

### Tooling and docs

- Modify: `Makefile`
- Modify: `.env.example`
- Modify: `docs/config.schema.json`
- Modify: `docs/docs/config.schema.json`
- Modify: `docs/docs/best-practices/input-validation.md`
- Modify: `charts/mcp-stack/values.yaml`
- Modify: `charts/mcp-stack/values.schema.json`

### Benchmarks

- Modify: `tests/performance/test_validation_middleware_sidecar_benchmark.py`

---

### Task 1: Add Gateway Config And Sidecar Client

**Files:**
- Create: `mcpgateway/services/validation_sidecar_client.py`
- Modify: `mcpgateway/config.py`
- Test: `tests/unit/mcpgateway/services/test_validation_sidecar_client.py`

- [ ] **Step 1: Write the failing client tests**

Add tests in `tests/unit/mcpgateway/services/test_validation_sidecar_client.py` for:
- 4-byte big-endian frame encoding/decoding
- base64 request-body encoding inside the JSON envelope
- `503`-class error conversion for socket unavailable, timeout, and malformed response cases
- parser-selection support for benchmark/dev mode only

- [ ] **Step 2: Run the new client tests to verify they fail**

Run: `uv run --active pytest tests/unit/mcpgateway/services/test_validation_sidecar_client.py -v`
Expected: FAIL because the client module does not exist yet.

- [ ] **Step 3: Add new validation sidecar settings**

Modify `mcpgateway/config.py` to add:
- `experimental_rust_validation_sidecar_enabled`
- `experimental_rust_validation_sidecar_uds`
- `experimental_rust_validation_sidecar_timeout_seconds`

Also add validation for:
- absolute UDS path
- mandatory UDS path whenever `experimental_rust_validation_sidecar_enabled=true`
- existing parent directory
- positive timeout

- [ ] **Step 4: Implement the sidecar client module**

Create `mcpgateway/services/validation_sidecar_client.py` with:
- request/response typed helpers
- 4-byte big-endian framing helpers
- base64 request-body encoding
- a small pool of persistent UDS connections
- single-flight use per connection
- explicit timeout handling on read/write operations
- benchmark/dev parser selector parameter kept off the production middleware path

Implementation note:
- do not create one socket per request
- use a small reusable pool, for example 2-4 persistent connections, so the sidecar path actually benefits from lower steady-state transport overhead

- [ ] **Step 5: Run the client tests again**

Run: `uv run --active pytest tests/unit/mcpgateway/services/test_validation_sidecar_client.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/config.py mcpgateway/services/validation_sidecar_client.py tests/unit/mcpgateway/services/test_validation_sidecar_client.py
git commit -s -m "feat: add validation sidecar client"
```

### Task 2: Switch Middleware To Sidecar Backend

**Files:**
- Modify: `mcpgateway/middleware/validation_middleware.py`
- Test: `tests/unit/mcpgateway/middleware/test_validation_middleware.py`

- [ ] **Step 1: Write the failing middleware tests**

Extend `tests/unit/mcpgateway/middleware/test_validation_middleware.py` with cases for:
- sidecar mode only activates when `validation_middleware_enabled` and `experimental_validate_io` are both true
- sidecar flag takes precedence over the legacy PyO3 flag
- sidecar validation failures still honor warn-only behavior in development/staging
- sidecar transport/readiness failures return `503`
- sidecar invalid JSON verdict maps to `422`
- legacy PyO3 mode still works when sidecar is disabled

- [ ] **Step 2: Run the focused middleware tests to verify they fail**

Run: `uv run --active pytest tests/unit/mcpgateway/middleware/test_validation_middleware.py -k 'sidecar or pyo3 or invalid_json' -v`
Expected: FAIL on missing sidecar integration paths.

- [ ] **Step 3: Refactor middleware backend selection**

Modify `mcpgateway/middleware/validation_middleware.py` so that:
- existing middleware gates remain authoritative
- sidecar mode routes request-body validation through `validation_sidecar_client`
- legacy PyO3 mode remains behind `experimental_rust_validation_middleware_enabled`
- Python mode remains the default when both Rust flags are off

- [ ] **Step 4: Implement exact error mapping**

Preserve:
- `422` for normal validation verdicts
- `503` for sidecar transport/readiness failures
- warn-only logging for ordinary validation verdicts when `validation_strict=false` in development/staging
- no fallback to Python when sidecar mode is enabled and the sidecar is unavailable

- [ ] **Step 5: Run the full middleware test file**

Run: `uv run --active pytest tests/unit/mcpgateway/middleware/test_validation_middleware.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mcpgateway/middleware/validation_middleware.py tests/unit/mcpgateway/middleware/test_validation_middleware.py
git commit -s -m "feat: route validation middleware through sidecar backend"
```

### Task 3: Build The Rust UDS Sidecar

**Files:**
- Create: `tools_rust/validation_sidecar/Cargo.toml`
- Create: `tools_rust/validation_sidecar/src/main.rs`
- Create: `tools_rust/validation_sidecar/src/lib.rs`
- Create: `tools_rust/validation_sidecar/src/protocol.rs`
- Create: `tools_rust/validation_sidecar/src/validator.rs`
- Create: `tools_rust/validation_sidecar/tests/runtime.rs`

- [ ] **Step 1: Write the failing Rust tests**

Add Rust tests covering:
- frame decode/encode
- base64 request-body handling
- `simd-json` parser path
- `serde_json` parser path
- Unicode length parity with Python semantics
- list-item string validation
- default dangerous-pattern-set parity
- non-string scalar leaves ignored
- max-depth enforcement
- incompatible regex rejection during startup/config load

- [ ] **Step 2: Run the Rust tests to verify they fail**

Run: `cargo test --manifest-path tools_rust/validation_sidecar/Cargo.toml`
Expected: FAIL because the crate does not exist yet.

- [ ] **Step 3: Create the sidecar crate and protocol module**

Define:
- request/response structs
- 4-byte big-endian framing
- single-flight connection handling
- max raw body size enforcement at 1 MiB before base64 expansion

- [ ] **Step 4: Implement validator backends**

In `src/validator.rs`:
- make `simd-json` the production default backend
- keep `serde_json` as a benchmark/dev comparison backend
- preserve parity for string-only leaf validation
- reject incompatible regex patterns during startup/config load

- [ ] **Step 4a: Add explicit parser selection for benchmark/dev runs**

Implement one explicit startup-time parser switch for the sidecar, for example:
- `--parser simd-json|serde-json`

Requirements:
- default to `simd-json`
- expose the same switch through the benchmark bootstrap so Python, PyO3, sidecar+`serde_json`, and sidecar+`simd-json` are mechanically reproducible
- keep parser choice out of normal production request envelopes

- [ ] **Step 5: Implement the runtime binary**

In `src/main.rs` and `src/lib.rs`:
- bind the configured UDS path
- accept framed requests
- decode, validate, and respond
- expose a simple readiness exchange sufficient for Python-side health/use checks

- [ ] **Step 6: Run the Rust tests**

Run: `cargo test --manifest-path tools_rust/validation_sidecar/Cargo.toml`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tools_rust/validation_sidecar
git commit -s -m "feat: add rust validation sidecar"
```

### Task 4: Wire Tooling, Docs, And Benchmarks

**Files:**
- Modify: `Makefile`
- Modify: `.env.example`
- Modify: `docs/config.schema.json`
- Modify: `docs/docs/config.schema.json`
- Modify: `docs/docs/best-practices/input-validation.md`
- Modify: `charts/mcp-stack/values.yaml`
- Modify: `charts/mcp-stack/values.schema.json`
- Modify: `tests/performance/test_validation_middleware_sidecar_benchmark.py`

- [ ] **Step 1: Write the failing benchmark/doc expectations**

Add or update tests/checks for:
- benchmark can compare Python, PyO3, sidecar+`serde_json`, sidecar+`simd-json`
- docs/config surfaces include the new sidecar settings
- Makefile has install/test/run targets for the sidecar

- [ ] **Step 2: Run the targeted checks to verify they fail**

Run:
- `uv run --active python tests/performance/test_validation_middleware_sidecar_benchmark.py`
- `rg "EXPERIMENTAL_RUST_VALIDATION_SIDECAR" .env.example docs charts Makefile`

Expected: FAIL or missing references before wiring is complete.

- [ ] **Step 3: Update the benchmark harness**

Modify `tests/performance/test_validation_middleware_sidecar_benchmark.py` to:
- keep Python and legacy PyO3 comparisons
- add UDS sidecar benchmark mode
- add both parser backends
- run both execution orders
- print all four result groups clearly

- [ ] **Step 4: Update Makefile and operator surfaces**

Add:
- distinct UDS sidecar build/install/test/run targets in `Makefile`, using names that do not collide with the existing legacy PyO3 targets, for example:
  - `validation-sidecar-build`
  - `validation-sidecar-run`
  - `validation-sidecar-test`
  - `validation-sidecar-bench-setup`
- `.env.example` entries
- config schema updates
- Helm values/schema updates
- validation doc updates

- [ ] **Step 4a: Define benchmark bootstrap explicitly**

Update the benchmark harness and related tooling so that:
- the UDS sidecar is launched as a real subprocess or Make target before timing starts
- the subprocess or target is started once with `--parser serde-json` and once with `--parser simd-json`
- the harness uses a deterministic UDS path under a temp directory
- the harness waits for readiness with a framed health/readiness exchange before timing
- the harness tears the sidecar down after each run

- [ ] **Step 5: Run end-to-end verification**

Run:
- `uv run --active pytest tests/unit/mcpgateway/services/test_validation_sidecar_client.py -v`
- `uv run --active pytest tests/unit/mcpgateway/middleware/test_validation_middleware.py -v`
- `cargo test --manifest-path tools_rust/validation_sidecar/Cargo.toml`
- `cargo test --manifest-path tools_rust/validation_middleware_sidecar/Cargo.toml`
- `make validation-sidecar-test`
- `make validation-sidecar-run` or the equivalent benchmark bootstrap target in dry-run/setup mode
- `uv run --active python tests/performance/test_validation_middleware_sidecar_benchmark.py`

Expected:
- unit tests pass
- both Rust crates pass
- sidecar tooling succeeds with the new non-colliding target names
- benchmark prints Python/PyO3/serde-sidecar/simd-sidecar comparisons

- [ ] **Step 6: Commit**

```bash
git add Makefile .env.example docs/config.schema.json docs/docs/config.schema.json docs/docs/best-practices/input-validation.md charts/mcp-stack/values.yaml charts/mcp-stack/values.schema.json tests/performance/test_validation_middleware_sidecar_benchmark.py
git commit -s -m "chore: wire validation sidecar docs and benchmarks"
```

### Task 5: Final Integration Validation

**Files:**
- Modify: any touched files from earlier tasks as needed
- Test: add or update a real integration test covering the gateway-to-sidecar UDS path

- [ ] **Step 1: Run the minimum serious repo-wide validation**

Run:
- `make doctest test`
- `make flake8 bandit interrogate pylint`
- `make rust-check`

Expected: PASS, or document any pre-existing failures before proceeding.

- [ ] **Step 2: Re-run the focused sidecar verification**

Run:
- `uv run --active pytest tests/unit/mcpgateway/services/test_validation_sidecar_client.py -v`
- `uv run --active pytest tests/unit/mcpgateway/middleware/test_validation_middleware.py -v`
- `uv run --active pytest tests/integration/test_validation_sidecar_integration.py -v`
- `cargo test --manifest-path tools_rust/validation_sidecar/Cargo.toml`
- `make validation-sidecar-test`
- `uv run --active python tests/performance/test_validation_middleware_sidecar_benchmark.py`

Expected: PASS with current benchmark output recorded.

- [ ] **Step 2a: Add the real UDS integration test if missing**

Create or extend `tests/integration/test_validation_sidecar_integration.py` so it:
- boots the Rust sidecar on a temp UDS path
- exercises a real request through `ValidationMiddleware`
- verifies a healthy sidecar returns the expected validation verdict
- verifies an unavailable sidecar returns the expected `503` path
- verifies incompatible dangerous-pattern regex configuration causes sidecar startup/readiness failure and surfaces as `503` at the gateway boundary

- [ ] **Step 3: Commit final fixes if needed**

```bash
git add <any final touched files>
git commit -s -m "fix: finalize validation sidecar integration"
```

- [ ] **Step 4: Run detailed code review before asking for PR readiness**

Run the standard detailed review workflow on the final diff before pushing for review, per repo instructions.
