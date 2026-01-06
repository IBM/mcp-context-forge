# Testing Guide for MCP Gateway (ContextForge)

This comprehensive guide covers all aspects of testing the MCP Gateway, from unit tests to end-to-end integration testing.

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

```bash
# Complete test suite with coverage
make doctest test htmlcov

# Quick smoke test
make smoketest

# Full quality check pipeline
make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify
```

## Prerequisites

- **Python 3.11+** (3.10 minimum)
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
pytest tests/unit/mcpgateway/test_config.py -v

# Run with coverage
pytest --cov=mcpgateway --cov-report=term-missing tests/unit/
```

### 2. Integration Tests (`tests/integration/`)
Tests for API endpoints and service interactions.

```bash
# Run integration tests
pytest tests/integration/ -v

# Test specific endpoints
pytest tests/integration/test_api.py::test_tools_endpoint -v
```

### 3. End-to-End Tests (`tests/e2e/`)
Complete workflow tests with real services.

```bash
# Run E2E tests
pytest tests/e2e/ -v

# Container-based smoke test
make smoketest
```

### 4. Security Tests (`tests/security/`)
Security validation and vulnerability testing.

```bash
# Security test suite
pytest tests/security/ -v

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

# Run UI tests
make test-ui              # With browser UI
make test-ui-headless     # Headless mode
make test-ui-debug        # Debug mode with inspector
make test-ui-parallel     # Parallel execution

# Generate test report
make test-ui-report
```

### 6. Async Tests (`tests/async/`)
Asynchronous operation and WebSocket testing.

```bash
# Run async tests
pytest tests/async/ -v --async-mode=auto
```

### 7. Fuzz Tests (`tests/fuzz/`)
Property-based and fuzz testing for robustness.

```bash
# Run fuzz tests
pytest tests/fuzz/ -v

# With hypothesis settings
pytest tests/fuzz/ --hypothesis-show-statistics
```

### 8. Migration Tests (`tests/migration/`)
Database migration and upgrade testing.

```bash
# Test migrations
pytest tests/migration/ -v

# Test specific migration
pytest tests/migration/test_v0_7_0_migration.py -v
```

## Running Tests

### Complete Test Pipeline

```bash
# Full test suite (recommended before commits)
make doctest test htmlcov smoketest

# Quick validation
make test

# With code quality checks
make test flake8 pylint
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
pytest -k "test_auth" -v

# Run tests with specific markers
pytest -m "asyncio" -v
pytest -m "not slow" -v

# Run failed tests from last run
pytest --lf -v

# Run tests in parallel
pytest -n auto tests/unit/
```

### Testing Individual Files

```bash
# Test a specific file with coverage
. /home/cmihai/.venv/mcpgateway/bin/activate
pytest --cov-report=annotate tests/unit/mcpgateway/test_translate.py

# Test with detailed output
pytest -vvs tests/unit/mcpgateway/services/test_gateway_service.py

# Test specific class or method
pytest tests/unit/mcpgateway/test_config.py::TestSettings -v
pytest tests/unit/mcpgateway/test_auth.py::test_jwt_creation -v
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
pytest --cov=mcpgateway --cov-report=term-missing tests/

# Coverage for specific modules
pytest --cov=mcpgateway.services --cov-report=term tests/unit/mcpgateway/services/
```

### Coverage Thresholds

```bash
# Enforce minimum coverage (fails if below 80%)
pytest --cov=mcpgateway --cov-fail-under=80 tests/

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
DATABASE_URL=postgresql://user:pass@localhost/test_mcp make test

# MySQL/MariaDB
DATABASE_URL=mysql+pymysql://user:pass@localhost/test_mcp make test
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
pytest --profile tests/unit/

# Generate profile report
python -m cProfile -o profile.stats $(which pytest) tests/
python -m pstats profile.stats
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
    make doctest test htmlcov
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
pytest -vvs tests/unit/

# Show print statements
pytest -s tests/unit/

# Show local variables on failure
pytest -l tests/unit/
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
pytest --pdb tests/unit/

# Run with ipdb (if installed)
pytest --pdbcls=IPython.terminal.debugger:TerminalPdb tests/unit/
```

### Test Logs

```bash
# Capture logs during tests
pytest --log-cli-level=DEBUG tests/unit/

# Save logs to file
pytest --log-file=test.log --log-file-level=DEBUG tests/unit/
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
DATABASE_URL=sqlite:///:memory: pytest tests/unit/
```

#### 3. Async Test Issues
```bash
# Install async test dependencies
pip install pytest-asyncio pytest-aiohttp

# Use proper event loop scope
pytest --asyncio-mode=auto tests/async/
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
# Run tests in random order to detect dependencies
pytest --random-order tests/unit/

# Run each test in a subprocess
pytest --forked tests/unit/

# Clear cache between runs
pytest --cache-clear tests/
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
- [MCP Gateway Contributing Guide](CONTRIBUTING.md)
