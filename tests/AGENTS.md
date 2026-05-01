# tests/AGENTS.md

Testing conventions and workflows for AI coding assistants.

## Test Directory Layout

```
tests/
├── unit/               # Fast, isolated unit tests (default target)
│   └── mcpgateway/     # Mirrors source structure
├── integration/        # Cross-module and service integration tests
├── e2e/               # End-to-end flows (slower; may require services)
├── e2e_rust/          # Rust-mode-specific end-to-end flows (requires Rust MCP path)
├── performance/        # Database performance & N+1 detection tests
├── playwright/        # UI automation (requires extra setup)
├── security/          # Security validation tests
├── fuzz/             # Fuzzing & property-based testing
├── load/             # Load testing scenarios
├── loadtest/         # Locust load test configurations
├── jmeter/           # JMeter performance test plans
├── client/           # MCP client testing
├── async/            # Async operation tests
├── migration/        # Database migration tests
├── differential/     # Differential testing
├── manual/           # Manual test scenarios
├── helpers/           # Test utilities (query_counter.py, conftest.py)
├── utils/            # Additional test utilities
└── conftest.py        # Shared pytest fixtures
```

## Quick Commands

```bash
# Core testing
make test                         # Run unit tests
pytest -k "<name>" tests/unit/    # Run only tests matching <name>
make doctest                      # Run doctests in modules
make doctest test                 # Doctests then unit tests
make htmlcov                      # Coverage HTML → docs/docs/coverage/index.html
make coverage                     # Full coverage (md + HTML + XML + badge + annotated)
make smoketest                    # Container build + simple E2E flow
make test-mcp-protocol-e2e        # MCP protocol via FastMCP client (needs live gateway)
make test-mcp-rbac                # MCP RBAC transport E2E (needs live gateway)
make test-mcp-plugin-parity       # MCP plugin parity E2E for the current stack (requires test-specific plugin config)
make test-mcp-access-matrix       # Rust-only MCP role/access matrix with strong sentinels
make test-mcp-session-isolation   # Rust-only MCP session isolation E2E
make test-mcp-session-isolation-load  # Rust-only Locust correctness load test

# Selective runs
pytest -k "fragment"              # By name substring
pytest -m "not slow"              # Exclude slow tests
pytest -m "api"                   # Only API tests
pytest tests/unit/path/test_mod.py::TestClass::test_method  # Single test

# Database performance
make dev-query-log                # Dev server with query logging
make query-log-tail               # Tail query log in another terminal
make query-log-analyze            # Analyze for N+1 patterns
make test-db-perf                 # Run performance tests

# JMeter load testing
make jmeter-rest-baseline         # REST API baseline (1,000 RPS, 10min)
make jmeter-mcp-baseline          # MCP JSON-RPC baseline (1,000 RPS, 15min)
make jmeter-load                  # Production load test (4,000 RPS, 30min)
make jmeter-stress                # Stress test (ramp to 10,000 RPS)
make jmeter-report                # Generate HTML report from JTL file

# PR readiness
make doctest test htmlcov smoketest lint-web bandit interrogate pylint verify
```

## Playwright (Browser E2E) Tests

UI tests live in `tests/playwright/` and use the Page Object pattern (`tests/playwright/pages/`).

### Setup

```bash
make playwright-install             # Install Chromium browser
# or
make playwright-install-all         # Install all browsers (chromium, firefox, webkit)
```

### Running Tests

Playwright tests require a running server. Start one in a separate terminal first:

```bash
uv run mcpgateway --host 0.0.0.0 --port 8080
```

Then run:

```bash
# Headless (CI-friendly)
make test-ui-headless

# With visible browser
make test-ui

# Specific test file
pytest tests/playwright/test_plugins_page.py -v

# Debug with Playwright Inspector
make test-ui-debug

# Smoke subset only
make test-ui-smoke
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TEST_BASE_URL` | `http://localhost:8080` | Server URL for tests |
| `PLATFORM_ADMIN_EMAIL` | `admin@example.com` | Login email |
| `PLATFORM_ADMIN_PASSWORD` | `changeme` | Login password |
| `PLUGINS_ENABLED` | `false` | Must be `true` for plugin page tests |

### Page Object Pattern

Each admin tab has a page object in `tests/playwright/pages/`:
- `admin_page.py` — main admin shell and tab navigation
- `plugins_page.py` — plugins tab (mode filter, badges, detail modal)
- `tools_page.py`, `servers_page.py`, etc.

All extend `BasePage` which provides `SidebarComponent` for tab navigation. Use `click_tab_by_id("tab-<name>", "<name>-panel")` to navigate.

Fixtures in `conftest.py` handle login automatically (JWT cookie injection by default).

### Writing New Playwright Tests

1. Create a page object in `tests/playwright/pages/` extending `BasePage`
2. Add a fixture in `tests/playwright/conftest.py`
3. Create test file in `tests/playwright/test_<feature>.py`
4. Use `pytest.skip()` when prerequisites aren't met (e.g., plugins not enabled)

## JavaScript Unit Tests

Admin UI JS logic is tested with Vitest (jsdom). Tests live in `tests/unit/js/`.

```bash
npx vitest run                              # All JS tests
npx vitest run tests/unit/js/plugins.test.js  # Specific file
```

These test JS functions in isolation (filter logic, modal rendering, DOM manipulation) without a browser. Changes to `mcpgateway/admin_ui/*.js` should have corresponding Vitest tests, and the bundle must be rebuilt after:

```bash
make build-ui
```

## Test Markers

Use markers to categorize tests:
- `slow` - Long-running tests
- `ui` - UI/Playwright tests
- `api` - API endpoint tests
- `smoke` - Smoke tests
- `e2e` - End-to-end tests

Filter with `-m`: `pytest -m "not slow"`, `pytest -m "api and not e2e"`

## Writing Tests

### Naming Conventions
- Files: `test_*.py`
- Classes: `Test*`
- Functions: `test_*`

### Async Tests
```python
import pytest

@pytest.mark.asyncio
async def test_async_operation():
    result = await some_async_function()
    assert result is not None
```

### Parametrization
```python
@pytest.mark.parametrize("input,expected", [
    ("a", 1),
    ("b", 2),
    ("c", 3),
])
def test_multiple_inputs(input, expected):
    assert process(input) == expected
```

### Mocking
```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_with_mock():
    with patch("mcpgateway.services.some_service.external_call", new_callable=AsyncMock) as mock:
        mock.return_value = {"status": "ok"}
        result = await function_under_test()
        assert result["status"] == "ok"
```

## Coverage Workflow

1. Run coverage: `make coverage` or `make htmlcov`
2. Open report: `docs/docs/coverage/index.html`
3. Review annotated files (`.cover` markers)
4. Target uncovered branches: error paths, exceptions, boundary conditions

## Database Safety

Tests must not affect the production database.

```bash
# Use temporary database for tests requiring DB
DATABASE_URL=sqlite:///./mcp-temp.db pytest -k 'your_test'
```

Prefer pure unit tests with mocked persistence layers for speed and determinism.

## N+1 Query Detection

The `tests/performance/` directory contains tests for database query optimization.

```bash
# Enable query logging during development
make dev-query-log

# In another terminal, watch queries
make query-log-tail

# Analyze patterns
make query-log-analyze
```

Key files:
- `tests/helpers/query_counter.py` - Query counting utilities
- `tests/performance/` - N+1 detection tests

## Best Practices

- Keep tests deterministic and isolated
- Avoid network calls and real credentials in unit tests
- Prefer unit tests near logic you modify
- Only add integration/E2E tests where behavior spans components
- Follow strict typing; run formatters before PRs
- Use `@pytest.mark.slow` sparingly; default tests should be fast
