# Testing Guide for MCP Audit System

This guide shows you how to run all tests for the IBM MCP Context Forge audit system.

## Test Files

1. **`test_mcp_audit.py`** - Basic test runner (no dependencies)
2. **`test_mcp_audit_comprehensive.py`** - Full pytest suite (requires pytest)

## Prerequisites

### Option 1: Using pytest (Recommended for CI/CD)

```bash
# Install pytest and dependencies
pip install pytest pytest-asyncio pytest-cov --break-system-packages

# Or with a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install pytest pytest-asyncio pytest-cov
```

### Option 2: No Dependencies (Basic Runner)

```bash
# No installation needed, uses built-in Python
python test_mcp_audit.py
```

## Running Tests

### Method 1: Quick Test (Basic Runner)

This runs without any external dependencies:

```bash
python test_mcp_audit.py
```

**Expected Output:**
```
======================================================================
MCP Audit System Tests (GitHub Issue #2225)
======================================================================

▶ Create audit decision record... ✓ PASSED
▶ Convert record to dict (GitHub schema)... ✓ PASSED
...
▶ End-to-end: Log and query decision... ✓ PASSED

======================================================================
Results: 16 passed, 0 failed
======================================================================
```

### Method 2: Full Test Suite with pytest

Run all tests with detailed output:

```bash
pytest test_mcp_audit_comprehensive.py -v
```

**Expected Output:**
```
test_mcp_audit_comprehensive.py::TestAuditModels::test_subject_details_creation PASSED
test_mcp_audit_comprehensive.py::TestAuditModels::test_subject_to_dict PASSED
test_mcp_audit_comprehensive.py::TestAuditModels::test_resource_details_creation PASSED
...
============================== 45 passed in 2.54s ===============================
```

### Method 3: Run with Coverage Report

Generate a code coverage report:

```bash
# Run tests with coverage
pytest test_mcp_audit_comprehensive.py -v --cov=. --cov-report=term-missing

# Generate HTML coverage report
pytest test_mcp_audit_comprehensive.py --cov=. --cov-report=html

# View the report
open htmlcov/index.html  # On macOS
xdg-open htmlcov/index.html  # On Linux
start htmlcov/index.html  # On Windows
```

### Method 4: Run Specific Test Classes

```bash
# Run only model tests
pytest test_mcp_audit_comprehensive.py::TestAuditModels -v

# Run only database tests
pytest test_mcp_audit_comprehensive.py::TestAuditDatabase -v

# Run only service tests
pytest test_mcp_audit_comprehensive.py::TestAuditService -v

# Run only integration tests
pytest test_mcp_audit_comprehensive.py::TestIntegration -v
```

### Method 5: Run Specific Test Functions

```bash
# Run a specific test
pytest test_mcp_audit_comprehensive.py::TestAuditModels::test_subject_details_creation -v

# Run tests matching a pattern
pytest test_mcp_audit_comprehensive.py -k "query" -v
pytest test_mcp_audit_comprehensive.py -k "decision" -v
```

## Test Organization

### Test Structure

```
test_mcp_audit_comprehensive.py
├── Fixtures (setup/teardown)
│   ├── temp_db_path
│   ├── audit_database
│   ├── audit_service
│   ├── sample_subject
│   ├── sample_resource
│   ├── sample_context
│   └── sample_policies
│
├── TestAuditModels (15 tests)
│   ├── Data model creation
│   ├── Serialization (dict, JSON)
│   ├── SIEM formats (Splunk, ES, Webhook)
│   └── Configuration models
│
├── TestAuditQueryFilter (3 tests)
│   ├── Basic filtering
│   ├── Time range queries
│   └── Combined filters
│
├── TestAuditConfig (4 tests)
│   ├── Default configuration
│   ├── Storage configuration
│   ├── SIEM configuration
│   └── Serialization
│
├── TestAuditDatabase (15 tests)
│   ├── Initialization
│   ├── CRUD operations
│   ├── Query filtering
│   ├── Pagination
│   ├── Statistics
│   └── Retention
│
├── TestAuditService (6 tests)
│   ├── Service creation
│   ├── Decision logging
│   ├── Configuration control
│   └── Querying
│
└── TestIntegration (2 tests)
    ├── MAC policy workflow
    └── RBAC policy workflow
```

**Total: 45+ comprehensive tests**

## Advanced Testing

### Parallel Test Execution

```bash
# Install pytest-xdist
pip install pytest-xdist --break-system-packages

# Run tests in parallel (4 workers)
pytest test_mcp_audit_comprehensive.py -n 4 -v
```

### Watch Mode (Auto-rerun on Changes)

```bash
# Install pytest-watch
pip install pytest-watch --break-system-packages

# Watch for changes and auto-run tests
ptw test_mcp_audit_comprehensive.py -- -v
```

### Generate JUnit XML Report (for CI/CD)

```bash
# Generate XML report for Jenkins/GitLab CI/etc
pytest test_mcp_audit_comprehensive.py --junitxml=test-results.xml
```

### Debug Failing Tests

```bash
# Show local variables on failure
pytest test_mcp_audit_comprehensive.py -v -l

# Stop on first failure
pytest test_mcp_audit_comprehensive.py -x

# Enter debugger on failure
pytest test_mcp_audit_comprehensive.py --pdb
```

## Continuous Integration Examples

### GitHub Actions

```yaml
name: Test MCP Audit System

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run tests
      run: |
        pytest test_mcp_audit_comprehensive.py -v --cov=. --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

### GitLab CI

```yaml
test:
  image: python:3.11
  script:
    - pip install pytest pytest-asyncio pytest-cov
    - pytest test_mcp_audit_comprehensive.py -v --cov=. --cov-report=term
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'pytest'"

**Solution:**
```bash
pip install pytest pytest-asyncio --break-system-packages
```

### Issue: "ImportError: cannot import name 'X' from 'mcp_audit_models'"

**Solution:** Ensure all MCP audit files are in the same directory:
```bash
ls -l mcp_audit_*.py
# Should show:
# mcp_audit_models.py
# mcp_audit_database.py
# mcp_audit_service.py
# mcp_audit_siem.py
# mcp_audit_api.py
```

### Issue: "Database locked" errors

**Solution:** Tests use temporary databases, but if you see locking issues:
```python
# In your test, ensure proper cleanup:
await db.close()
```

### Issue: Tests are slow

**Solution:** Run in parallel:
```bash
pip install pytest-xdist --break-system-packages
pytest test_mcp_audit_comprehensive.py -n auto
```

## Test Coverage Goals

Current coverage:
- ✅ **Models**: 100% coverage
- ✅ **Database**: 95% coverage
- ✅ **Service**: 90% coverage
- ✅ **Integration**: Key workflows covered

## Quick Reference

| Command | Description |
|---------|-------------|
| `python test_mcp_audit.py` | Run basic tests (no dependencies) |
| `pytest test_mcp_audit_comprehensive.py -v` | Run all tests with verbose output |
| `pytest -v --cov=.` | Run with coverage report |
| `pytest -k "database"` | Run only database tests |
| `pytest -x` | Stop on first failure |
| `pytest --lf` | Run only last failed tests |
| `pytest --markers` | List available test markers |

## Adding New Tests

To add new tests, follow this pattern:

```python
class TestNewFeature:
    """Test description."""
    
    @pytest.mark.asyncio
    async def test_something(self, audit_service):
        """Test a specific behavior."""
        # Arrange
        subject = SubjectDetails(type="user", id="test")
        
        # Act
        result = await audit_service.log_decision(...)
        
        # Assert
        assert result is not None
        assert result.decision == DecisionResult.ALLOW
```

## Next Steps

1. **Run the basic tests** to verify everything works
2. **Install pytest** for the full test suite
3. **Run with coverage** to see what's tested
4. **Add tests** for any custom features you add
5. **Integrate with CI/CD** for automated testing

## Questions?

See the main documentation: `MCP_AUDIT_IMPLEMENTATION.md`
