## Release Checklist

Use this file as the pre-release checklist for the Rust MCP runtime.

Rules:

- Leave every item unchecked in git.
- Check items off only in your working copy after the command or manual check
  completes successfully.
- If an item is not applicable for a specific release candidate, add a short
  note rather than silently skipping it.
- If an item fails because of a known unrelated repo issue, note that
  explicitly before continuing.

## 1. Rust Runtime Inner Loop

- [ ] `make -C tools_rust/mcp_runtime fmt-check`
- [ ] `make -C tools_rust/mcp_runtime check`
- [ ] `make -C tools_rust/mcp_runtime check-all-targets`
- [ ] `make -C tools_rust/mcp_runtime clippy`
- [ ] `make -C tools_rust/mcp_runtime clippy-all`
- [ ] `make -C tools_rust/mcp_runtime test`
- [ ] `make -C tools_rust/mcp_runtime test-rmcp`
- [ ] `make -C tools_rust/mcp_runtime doc-test`
- [ ] `make -C tools_rust/mcp_runtime coverage`

## 2. Repo Formatting And Hygiene

- [ ] `make autoflake`
- [ ] `make isort`
- [ ] `make black`
- [ ] `make pre-commit`

## 3. Python / Backend Quality Gates

- [ ] `make doctest`
- [ ] `make test`
- [ ] `make htmlcov`
- [ ] `make flake8`
- [ ] `make bandit`
- [ ] `make interrogate`
- [ ] `make pylint`
- [ ] `make verify`

## 4. Web / Frontend Gates

- [ ] `make test-js-coverage`
- [ ] `make lint-web`
- [ ] `make test-ui-smoke`
- [ ] `make test-ui-headless`
- [ ] `uv run pytest tests/playwright/test_version_page.py -q`

## 5. Python Baseline MCP Validation

- [ ] `make testing-down`
- [ ] `make compose-clean`
- [ ] `make docker-prod DOCKER_BUILD_ARGS="--no-cache"`
- [ ] `make testing-up`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Python MCP mode
- [ ] Confirm admin Overview shows `🐍 Python MCP Core`
- [ ] Confirm Version Info shows the MCP Runtime card in Python mode
- [ ] `make test-mcp-cli`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-up`
- [ ] `MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=python make test-mcp-plugin-parity`
- [ ] Perform one manual `/mcp` tool call and confirm `x-contextforge-mcp-runtime: python`
- [ ] Perform one freshness check against `fast-time-get-system-time`

## 6. Rust Shadow Validation

- [ ] `make testing-rebuild-rust-shadow`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports `rust-managed` runtime with Python transport mounted
- [ ] Confirm admin Overview shows Rust runtime present but Python public transport semantics
- [ ] `make test-mcp-cli`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`

## 7. Rust Edge Validation

- [ ] `make testing-rebuild-rust`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Rust transport mounted
- [ ] Confirm admin Overview shows `🦀 Rust MCP Core`
- [ ] Confirm Version Info shows MCP Runtime card with Rust transport mounted
- [ ] `make test-mcp-cli`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`

## 8. Rust Full Validation

- [ ] `make testing-rebuild-rust-full`
- [ ] `curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'`
- [ ] Confirm `/health` reports Rust transport/session/event-store/resume/live-stream/affinity/auth-reuse mounted as expected
- [ ] Confirm admin Overview shows `🦀 Rust MCP Core`
- [ ] Confirm Version Info shows MCP Runtime card with the expected mounted/core modes
- [ ] `make test-mcp-cli`
- [ ] `make test-mcp-rbac`
- [ ] `make test-mcp-access-matrix`
- [ ] `make test-mcp-session-isolation`
- [ ] `make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s`
- [ ] `PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-rebuild-rust-full`
- [ ] `MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=rust make test-mcp-plugin-parity`
- [ ] `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
- [ ] Perform one manual `/mcp` tool call and confirm `x-contextforge-mcp-runtime: rust`
- [ ] Perform one manual freshness check against `fast-time-get-system-time`
- [ ] Re-run the Rust full validation with a short session-auth reuse TTL for bounded revocation checks:
  `MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full`
- [ ] Re-run `make test-mcp-session-isolation` on the short-TTL stack
- [ ] Re-run `make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s` on the short-TTL stack
- [ ] Re-run `make test-mcp-access-matrix` on the short-TTL stack

## 9. Optional PostgreSQL TLS Validation

These checks are required for any release that claims Rust PostgreSQL TLS
support beyond local non-TLS compose testing.

- [ ] Validate Python runtime against a PostgreSQL deployment that requires TLS (`DATABASE_URL=...?...sslmode=require`)
- [ ] Validate Rust runtime against a PostgreSQL deployment that requires TLS (`MCP_RUST_DATABASE_URL=...?...sslmode=require`)
- [ ] Validate Rust runtime against a PostgreSQL deployment using `sslmode=prefer`
- [ ] Validate Rust runtime against a PostgreSQL deployment using `sslrootcert=/path/to/ca.pem`
- [ ] Confirm the Rust runtime still starts and serves requests against a non-TLS local PostgreSQL deployment
- [ ] Confirm unsupported `sslcert` / `sslkey` inputs fail fast with a clear startup/config error

## 10. MCP Runtime UI Validation

- [ ] Open `http://localhost:8080/admin/`
- [ ] Confirm Overview shows `🐍 Python MCP Core` in Python mode
- [ ] Confirm Overview shows `🦀 Rust MCP Core` in Rust mode
- [ ] Confirm Version Info shows the MCP Runtime card
- [ ] Confirm Version Info reflects mounted transport/core modes correctly
- [ ] Confirm runtime mode badges match `/health`

## 11. Benchmarking

- [ ] `make benchmark-mcp-mixed`
- [ ] `make benchmark-mcp-tools`
- [ ] `make benchmark-mcp-mixed-300`
- [ ] `make benchmark-mcp-tools-300`
- [ ] `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=60s`
- [ ] `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s`
- [ ] Compare results against `tools_rust/mcp_runtime/STATUS.md`
- [ ] Note any regression or unexpected failure count before release
- [ ] Record Python baseline tools-only benchmark numbers for comparison
- [ ] Record Rust full tools-only benchmark numbers for comparison

## 12. Profiling

- [ ] `make -C tools_rust/mcp_runtime setup-profiling`
- [ ] `make -C tools_rust/mcp_runtime flamegraph-test`
- [ ] `make -C tools_rust/mcp_runtime flamegraph-test-rmcp`
- [ ] Review artifacts under `tools_rust/mcp_runtime/profiles/`
- [ ] Confirm any performance-sensitive change has a profiling note or rationale

## 13. Security / Correctness Review

- [ ] Review `todo/code-review.md`
- [ ] Review `todo/findings.md`
- [ ] Review `tools_rust/mcp_runtime/STATUS.md`
- [ ] Confirm remaining open items are documented and acceptable for release
- [ ] Recheck that direct public Rust ingress strips internal-only headers
- [ ] Recheck that session ownership / auth-binding isolation tests still pass
- [ ] Recheck that error responses do not leak internal transport details on the Rust path
- [ ] Review Rust `/health` `runtime_stats` and confirm reuse/fallback/denial counters look sane during the validation run

## 14. Docs And Release Docs

- [ ] Review `tools_rust/mcp_runtime/README.md`
- [ ] Review `tools_rust/mcp_runtime/STATUS.md`
- [ ] Review `tools_rust/mcp_runtime/TESTING-DESIGN.md`
- [ ] Review `tools_rust/mcp_runtime/DEVELOPING.md`
- [ ] Review `docs/docs/architecture/rust-mcp-runtime.md`
- [ ] Review `docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md`
- [ ] Review `docs/docs/testing/index.md`
- [ ] Review `docs/docs/testing/performance.md`
- [ ] Review `docs/docs/development/profiling.md`
- [ ] `cd docs && make build`

## 15. Final Release Notes

- [ ] Record final Python baseline MCP result summary
- [ ] Record final Rust full MCP result summary
- [ ] Record final benchmark summary
- [ ] Record final profiling summary
- [ ] Record any known caveats or follow-up items
- [ ] Confirm this file is left unchecked before commit
