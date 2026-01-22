# 🧪 Testing MCP Gateway

This section covers the testing strategy and tools for MCP Gateway.

---

## Testing Pyramid

| Layer | Tool | Location | Status |
|-------|------|----------|--------|
| **Unit tests** | pytest | `tests/unit/` | Implemented |
| **Integration tests** | pytest | `tests/integration/` | Implemented |
| **End-to-end tests** | pytest | `tests/e2e/` | Implemented |
| **UI automation** | Playwright | `tests/playwright/` | Implemented |
| **Load testing** | Locust | `tests/loadtest/` | Implemented |
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

## 🔍 Additional Testing

- [Acceptance Testing](acceptance.md) - formal acceptance criteria
- [Fuzzing](fuzzing.md) - fuzz testing for edge cases

For database performance testing, see [Database Performance](../development/db-performance.md).

## 🔹 Microsoft Entra ID E2E Tests

Use the [Entra ID E2E Testing Guide](entra-id-e2e.md) to validate:

- SSO integration with Microsoft Entra ID (Azure AD)
- Group-based `platform_admin` role assignment
- Dynamic user and group management via Microsoft Graph API
- OIDC discovery and JWKS validation

These tests are fully automated and self-contained, creating and cleaning up Azure resources automatically.

---

For additional scenarios (e.g., completion APIs, multi-hop toolchains), expand the test suite as needed.

