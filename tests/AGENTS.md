# tests/AGENTS.md

Testing conventions and workflows for AI coding assistants.

## Test Directory Layout

```
tests/
├── unit/               # Fast, isolated unit tests (default target)
│   └── mcpgateway/     # Mirrors source structure
├── integration/        # Cross-module and service integration tests
├── e2e/               # End-to-end flows (slower; may require services)
├── performance/        # Database performance & N+1 detection tests
├── playwright/        # UI automation (requires extra setup)
├── security/          # Security validation tests
├── fuzz/             # Fuzzing & property-based testing
├── helpers/           # Test utilities (query_counter.py, conftest.py)
└── conftest.py        # Shared pytest fixtures
```

## Quick Commands

```bash
# Core testing
make test                         # Run unit tests
make doctest                      # Run doctests in modules
make doctest test                 # Doctests then unit tests
make htmlcov                      # Coverage HTML → docs/docs/coverage/index.html
make coverage                     # Full coverage (md + HTML + XML + badge + annotated)
make smoketest                    # Container build + simple E2E flow

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

# PR readiness
make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify
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
