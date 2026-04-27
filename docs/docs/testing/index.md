# 🧪 Testing ContextForge

This section covers the testing strategy and tools for ContextForge.

---

## Testing Pyramid

| Layer | Tool | Location | Status |
|-------|------|----------|--------|
| **Unit tests** | pytest | `tests/unit/` | Implemented |
| **Integration tests** | pytest | `tests/integration/` | Implemented |
| **End-to-end tests** | pytest | `tests/e2e/`, `tests/e2e_rust/` | Implemented |
| **UI automation** | Playwright | `tests/playwright/` | Implemented |
| **Security / DAST** | Playwright + OWASP ZAP | `tests/playwright/security/` | Implemented |
| **Load testing** | Locust | `tests/loadtest/` | Implemented |
| **Concurrency tests** | Manual (asyncio) | `tests/manual/concurrency/` | Implemented |
| **JS unit tests** | - | - | Not yet implemented |

---

## 🔹 Basic Smoke Test

Use the [Basic Smoke Test](basic.md) to verify:

- JWT token generation and authentication
- Gateway registration
- Tool registration
- Server creation and event streaming
- Tool invocation via JSON-RPC

This test is ideal for validating local development environments or freshly deployed test instances.

---

## 🐍 Python Testing (pytest)

Run the full test suite or specific categories:

```bash
make test                      # full suite
pytest -k "<name>" tests/unit/ # only tests matching <name>
pytest tests/unit/             # unit tests only
pytest tests/integration/      # integration tests
pytest tests/e2e/              # end-to-end scenarios
```

Coverage reporting:

```bash
make coverage                  # run with coverage
make coverage-html             # generate HTML report
```

---

## 🎭 UI Automation (Playwright)

Playwright tests validate the Admin UI interactions:

```bash
# Install Playwright browsers (one-time)
playwright install

# Run UI tests
pytest tests/playwright/

# Run specific admin tests
pytest tests/playwright/ -k admin
```

Tests cover login flows, CRUD operations, and UI state management.

---

## 🦗 Load Testing (Locust)

Locust is used for performance and load testing:

```bash
# Containerized load testing (recommended for docker-compose users)
make testing-up
# Locust UI: http://localhost:8089 (targets http://nginx:80 by default)

# Start Locust web UI
locust -f tests/loadtest/locustfile.py --host=http://localhost:8080

# Headless load test
locust -f tests/loadtest/locustfile.py --host=http://localhost:8080 \
  --headless -u 100 -r 10 -t 60s
```

Access the Locust dashboard at `http://localhost:8089` when running with the web UI.

---

## 🦀 Rust MCP Runtime Validation

For the Rust MCP runtime path, the most important stack-backed checks are:

```bash
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-access-matrix
make test-mcp-session-isolation
make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
```

For live plugin parity, use the test-specific plugin config and run the same
E2E against both Python mode and Rust full mode:

```bash
PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-up
MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=python make test-mcp-plugin-parity

PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml make testing-rebuild-rust-full
MCP_PLUGIN_PARITY_EXPECTED_RUNTIME=rust make test-mcp-plugin-parity
```

This parity gate currently proves live plugin behavior on:
- `resources/read`
- `tools/call`
- `prompts/get`

For revocation and membership/role-drift validation, shorten the reuse TTL so
the bounded-TTL contract completes quickly:

```bash
MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full
make test-mcp-access-matrix
make test-mcp-session-isolation
make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s
```

Use these mode-specific rebuild targets when validating rollout behavior:

```bash
make testing-rebuild-rust-shadow
make testing-rebuild-rust
make testing-rebuild-rust-full
```

These validate, respectively:

- `shadow`: Rust sidecar present while public `/mcp` stays on Python
- `edge`: direct Rust public ingress without the full Rust session/runtime cores
- `full`: direct Rust public ingress plus Rust session/event/resume/live-stream
  and affinity cores

For throughput benchmarks and Locust wrappers, see
[Performance Testing](performance.md).

---

## 🌐 Frontend JavaScript Testing

Frontend JavaScript unit tests are **not yet implemented**. The codebase uses plain JavaScript (not TypeScript) with:

- ESLint + Prettier for linting/formatting
- No test framework (Jest/Vitest/Mocha) currently configured

Linting is available:

```bash
make eslint        # lint JavaScript
make lint-web      # ESLint + HTMLHint + Stylelint
make format-web    # Prettier formatting
```

---

## 🔒 Security Testing (OWASP & DAST)

Two-layer coverage for OWASP A01:2021 – Broken Access Control:

```bash
make test-owasp   # Layer 1: direct Playwright access-control tests (no ZAP needed)
make test-zap     # Layer 2: ZAP DAST scan (requires make testing-zap-up)
```

See [Security Testing](security.md) for the full guide including environment
variables, authentication setup, ZAP target URL configuration, and report
locations.

---

## 🔀 Concurrency Testing

Manual concurrency tests validate data consistency under concurrent access. These require a live ContextForge instance backed by PostgreSQL and Redis — they are **not** part of automated CI.

| Test ID | Makefile Target | What it validates |
|---------|-----------------|-------------------|
| CONC-02 | `make conc-02-gateways` | No 5xx errors, no malformed payloads, and valid final read when concurrent readers and writers hit `GET/PUT /gateways/{id}` |

**Quick start:**

```bash
# Prerequisites: PostgreSQL + Redis + gateway + translator running
# (see tests/manual/README.md for full infrastructure setup)

# Generate token and run
export CONC_TOKEN="$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 120 --secret my-test-key-but-now-longer-than-32-bytes)"
make conc-02-gateways

# Custom parameters
CONC_RW_DURATION_SEC=30 CONC_RW_READERS=10 CONC_RW_WRITERS=2 make conc-02-gateways
```

Full runbook, environment variable reference, and results template: [`tests/manual/concurrency/conc_02_gateways_results.md`](https://github.com/IBM/mcp-context-forge/blob/main/tests/manual/concurrency/conc_02_gateways_results.md).

---

## 🔍 Additional Testing

- [Load Testing Hints](load-testing-hints.md) - environment variables and workflows for containerized load tests
- [Acceptance Testing](acceptance.md) - formal acceptance criteria
- [Fuzzing](fuzzing.md) - fuzz testing for edge cases

For database performance testing, see [Database Performance](../development/db-performance.md).

## 🔹 Microsoft Entra ID E2E Tests

Use the [Entra ID E2E Testing Guide](entra-id-e2e.md) to validate:

- SSO integration with Microsoft Entra ID (Azure AD)
- Group-based `platform_admin` role assignment
- Dynamic user and group management via Microsoft Graph API

These tests are fully automated and self-contained, creating and cleaning up Azure resources automatically.

---

For additional scenarios (e.g., completion APIs, multi-hop toolchains), expand the test suite as needed.
