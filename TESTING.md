# Testing Guide for ContextForge

This comprehensive guide covers all aspects of testing ContextForge, from unit tests to end-to-end integration testing.

## Table of Contents
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Test Categories](#test-categories)
- [Running Tests](#running-tests)
- [Coverage Reports](#coverage-reports)
- [Writing Tests](#writing-tests)
- [Continuous Integration](#continuous-integration)
- [Troubleshooting](#troubleshooting)

## Quick Start

Use `uv run rstest` or the Makefile test targets. `.python-version` selects Python 3.14.
Use `uv run --python 3.12 rstest --python 3.12` to check the minimum supported interpreter.
The runner preserves file order and groups startup-sensitive files before other tests on their worker.
Tests marked `serial` run exclusively after the parallel phase.
Coverage commands generate XML by default. Use `make htmlcov` to request an HTML report.

```bash
# Complete test suite with coverage
make doctest test coverage

# Quick smoke test
make smoketest

# Full quality check pipeline
make doctest test coverage smoketest lint-web bandit interrogate pylint verify
```

## Prerequisites

- **Python 3.14** by default; Python 3.12 and 3.13 remain supported
- **uv** (recommended) or pip/virtualenv
- **Docker/Podman** (for container tests)
- **Make** (for automation)
- **Node.js 18+** (for Playwright UI tests)

### Initial Setup

```bash
# Setup with uv (recommended)
make venv install-dev

# Alternative: traditional pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,test]"
```

## Test Categories

### 1. Unit Tests (`tests/unit/`)
Fast, isolated tests for individual components.

```bash
# Run all unit tests
make test

# Run specific module tests
rstest tests/unit/mcpgateway/test_config.py -v

# Run with coverage
rstest --cov=mcpgateway --cov-report=xml tests/unit/
```

### 2. Integration Tests (`tests/integration/`)
Tests for API endpoints and service interactions.

```bash
# Run integration tests
rstest tests/integration/ -v

# Test specific endpoints
rstest tests/integration/test_api.py::test_tools_endpoint -v
```

### 3. End-to-End Tests (`tests/e2e/`)
Complete workflow tests with real services.

```bash
# Run E2E tests
rstest tests/e2e/ -v

# Container-based smoke test
make smoketest
```

### 4. Security Tests (`tests/security/`)
Security validation and vulnerability testing.

```bash
# Security test suite
rstest tests/security/ -v

# Static security analysis
make bandit

# Dependency vulnerability scan
make security-scan
```

### 5. UI Tests (`tests/playwright/`)
Browser-based Admin UI testing with Playwright.

```bash
# Install Playwright browsers
make playwright-install

# Start the testing stack (docker-compose.yml + nginx on :8080)
make testing-up

# Run UI tests
make test-ui              # With browser UI
make test-ui-headless     # Headless mode
make test-ui-debug        # Debug mode with inspector
make test-ui-parallel     # Parallel execution
make test-ui-screenshots  # Always-on screenshots (headless)
make test-ui-record       # Videos + screenshots (headless)

# Generate test report
make test-ui-report

# Override endpoint if needed
TEST_BASE_URL=http://localhost:8000 make test-ui
```

Playwright artifacts (screenshots/videos/traces) are written to `test-results/` and are gitignored.
Recording quality knobs: `PLAYWRIGHT_VIDEO_SIZE=1920x1080` (default), `PLAYWRIGHT_VIEWPORT_SIZE=1920x1080` (default), `PLAYWRIGHT_SLOWMO=750` (default).

### 6. Async Tests (`tests/async/`)
Asynchronous operation and WebSocket testing.

```bash
# Run async tests
rstest tests/async/ -v --async-mode=auto
```

### 7. Fuzz Tests (`tests/fuzz/`)
Property-based and fuzz testing for robustness.

```bash
# Run fuzz tests
rstest tests/fuzz/ -v

# With hypothesis settings
rstest tests/fuzz/ --hypothesis-show-statistics
```

### 8. Migration Tests (`tests/migration/`)
Database migration and upgrade testing.

```bash
# Test migrations
rstest tests/migration/ -v

# Test specific migration
rstest tests/migration/test_v0_7_0_migration.py -v
```

## Running Tests

### Complete Test Pipeline

```bash
# Full test suite (recommended before commits)
make doctest test coverage smoketest

# Quick validation
make test

# With code quality checks
make test ruff pylint
```

### Doctest Testing

```bash
# Run all doctests
make doctest

# Verbose output
make doctest-verbose

# With coverage
make doctest-coverage

# Check docstring coverage
make interrogate
```

### Specific Test Patterns

```bash
# Activate virtual environment first
source ~/.venv/mcpgateway/bin/activate

# Run tests matching a pattern
rstest -k "test_auth" -v

# Run tests with specific markers
rstest -m "asyncio" -v
rstest -m "not slow" -v

# Run failed tests from last run
rstest --lf -v

# Run tests in parallel
rstest -n auto tests/unit/
```

### Testing Individual Files

```bash
# Test a specific file with coverage
. .venv/bin/activate
rstest --cov-report=xml tests/unit/mcpgateway/test_translate.py

# Test with detailed output
rstest -vvs tests/unit/mcpgateway/services/test_gateway_service.py

# Test specific class or method
rstest tests/unit/mcpgateway/test_config.py::TestSettings -v
rstest tests/unit/mcpgateway/test_auth.py::test_jwt_creation -v
```

## Coverage Reports

### HTML Coverage Report

```bash
# Generate HTML coverage report
make htmlcov

# View report (opens in browser)
open docs/docs/coverage/index.html  # macOS
xdg-open docs/docs/coverage/index.html  # Linux
```

### Terminal Coverage Report

```bash
# Simple coverage summary
make coverage

# Detailed line-by-line coverage
rstest --cov=mcpgateway --cov-report=xml tests/

# Coverage for specific modules
rstest --cov=mcpgateway.services --cov-report=term tests/unit/mcpgateway/services/
```

### Coverage Thresholds

```bash
# Enforce minimum coverage (fails if below 80%)
rstest --cov=mcpgateway --cov-fail-under=80 tests/

# Check coverage trends
coverage report --show-missing
coverage html --directory=htmlcov
```

## Writing Tests

### Test Structure

```python
# tests/unit/mcpgateway/test_example.py
import pytest
from unittest.mock import Mock, patch
from mcpgateway.services import ExampleService

class TestExampleService:
    """Test suite for ExampleService."""

    @pytest.fixture
    def service(self, db_session):
        """Create service instance with mocked dependencies."""
        return ExampleService(db=db_session)

    def test_basic_operation(self, service):
        """Test basic service operation."""
        result = service.do_something("test")
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_async_operation(self, service):
        """Test async service operation."""
        result = await service.async_operation()
        assert result is not None

    @patch('mcpgateway.services.external_api')
    def test_with_mock(self, mock_api, service):
        """Test with mocked external dependency."""
        mock_api.return_value = {"status": "ok"}
        result = service.call_external()
        mock_api.assert_called_once()
```

### Using Fixtures

```python
# Import common fixtures from conftest.py
def test_with_database(db_session):
    """Test using database session fixture."""
    # db_session is automatically provided by conftest.py
    from mcpgateway.common.models import Tool
    tool = Tool(name="test_tool")
    db_session.add(tool)
    db_session.commit()
    assert tool.id is not None

def test_with_client(test_client):
    """Test using FastAPI test client."""
    response = test_client.get("/health")
    assert response.status_code == 200
```

### Testing Async Code

```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_websocket_connection():
    """Test WebSocket connection handling."""
    from mcpgateway.transports import WebSocketTransport
    transport = WebSocketTransport()

    async with transport.connect("ws://localhost:4444/ws") as conn:
        await conn.send_json({"method": "ping"})
        response = await conn.receive_json()
        assert response["result"] == "pong"
```

### Property-Based Testing

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=255))
def test_name_validation(name):
    """Test name validation with random inputs."""
    from mcpgateway.validation import validate_name
    if validate_name(name):
        assert len(name) <= 255
        assert not name.startswith(" ")
```

## Environment-Specific Testing

### Testing with Different Databases

```bash
# SQLite (default)
make test

# PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost/test_mcp make test # pragma: allowlist secret
```

### Testing with Different Configurations

```bash
# Test with production settings
ENVIRONMENT=production AUTH_REQUIRED=true make test

# Test with Redis caching
CACHE_TYPE=redis REDIS_URL=redis://localhost:6379 make test
```

## Performance Testing

### Load Testing

```bash
# Using hey (HTTP load generator)
make test-hey

# Custom load test
hey -n 1000 -c 10 -H "Authorization: Bearer $TOKEN" http://localhost:4444/health
```

### Profiling Tests

```bash
# Run tests with profiling
rstest --doctor tests/unit/

# Generate profile report
rstest --doctor --doctor-json=profile.json tests/
```

## Continuous Integration

### GitHub Actions Workflow

Tests run automatically on:
- Pull requests
- Push to main branch
- Nightly schedule

```yaml
# .github/workflows/test.yml example
- name: Run test suite
  run: |
    make venv install-dev
    make doctest test coverage
    make smoketest
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
make pre-commit-install

# Run manually
make pre-commit

# Skip hooks (emergency only)
git commit --no-verify
```

## Debugging Tests

### Verbose Output

```bash
# Maximum verbosity
rstest -vvs tests/unit/

# Show print statements
rstest -s tests/unit/

# Show local variables on failure
rstest -l tests/unit/
```

### Interactive Debugging

```python
# Add breakpoint in test
def test_complex_logic():
    result = complex_function()
    import pdb; pdb.set_trace()  # Debugger breakpoint
    assert result == expected
```

```bash
# Run with pdb on failure
rstest --pdb tests/unit/

# Run with ipdb (if installed)
rstest --pdbcls=IPython.terminal.debugger:TerminalPdb tests/unit/
```

### Test Logs

```bash
# Capture logs during tests
rstest --log-cli-level=DEBUG tests/unit/

# Save logs to file
rstest --log-file=test.log --log-file-level=DEBUG tests/unit/
```

## Troubleshooting

### Common Issues

#### 1. Import Errors
```bash
# Ensure package is installed in editable mode
pip install -e .

# Verify Python path
python -c "import sys; print(sys.path)"
```

#### 2. Database Errors
```bash
# Reset test database
rm -f test_mcp.db
alembic upgrade head

# Use in-memory database for tests
DATABASE_URL=sqlite:///:memory: rstest tests/unit/
```

#### 3. Async Test Issues
```bash
# Install async test dependencies
pip install pytest-asyncio pytest-aiohttp

# Use proper event loop scope
rstest --asyncio-mode=auto tests/async/
```

#### 4. Coverage Not Updating
```bash
# Clear coverage data
coverage erase

# Regenerate coverage
make htmlcov
```

#### 5. Playwright Browser Issues
```bash
# Reinstall browsers
npx playwright install --with-deps

# Use specific browser
BROWSER=firefox make test-ui
```

### Test Isolation

```bash
# Run selected files sequentially when debugging shared state
rstest -n 0 tests/unit/

# Clear cache between runs
rstest --cache-clear tests/
```

## Best Practices

1. **Keep tests fast**: Unit tests should run in < 1 second
2. **Use fixtures**: Leverage conftest.py for common setup
3. **Mock external dependencies**: Don't rely on network services
4. **Test edge cases**: Include boundary and error conditions
5. **Maintain test coverage**: Aim for > 80% coverage
6. **Write descriptive test names**: `test_auth_fails_with_invalid_token`
7. **Group related tests**: Use test classes for organization
8. **Clean up resources**: Use fixtures with proper teardown
9. **Document complex tests**: Add docstrings explaining the test purpose
10. **Run tests before committing**: Use pre-commit hooks

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Playwright Documentation](https://playwright.dev/python/)
- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [ContextForge Contributing Guide](CONTRIBUTING.md)
