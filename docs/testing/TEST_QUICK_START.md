# Quick Start: Running OAuth Token Storage Tests

## Prerequisites

```bash
# Activate virtual environment
source .venv/bin/activate

# Verify pytest is installed
pytest --version
```

## Quick Test Commands

### Run All New Tests
```bash
# Both test files
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       tests/unit/mcpgateway/services/test_vault_token_backend.py -v
```

### Run Specific Test Classes

```bash
# Façade backend selection tests (6 tests)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py::TestTokenStorageServiceBackendSelection -v

# Team ID extraction tests (7 tests)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py::TestTokenStorageServiceTeamIdExtraction -v

# Token storage tests (5 tests)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py::TestTokenStorageServiceStoreTokens -v

# Integration tests (2 tests)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py::TestTokenStorageServiceIntegration -v

# Vault backend initialization tests (4 tests)
pytest tests/unit/mcpgateway/services/test_vault_token_backend.py::TestVaultTokenBackendInit -v

# Vault caching tests (1 test)
pytest tests/unit/mcpgateway/services/test_vault_token_backend.py::TestVaultTokenBackendCaching -v
```

### Run Individual Tests

```bash
# Single test example
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py::TestTokenStorageServiceBackendSelection::test_init_with_database_backend_default -v

# Another example
pytest tests/unit/mcpgateway/services/test_vault_token_backend.py::TestVaultTokenBackendStoreTokens::test_store_tokens_success -v
```

## Test Output Options

### Verbose Output
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -v
```

### Show Print Statements
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -v -s
```

### Stop on First Failure
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -x
```

### Show Failed Tests Summary
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --tb=short
```

### Run Only Failed Tests from Last Run
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --lf
```

## Coverage Reports

### Generate HTML Coverage Report
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       --cov=mcpgateway.services.token_storage_service \
       --cov-report=html

# Open in browser
open htmlcov/index.html
```

### Terminal Coverage Report
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       --cov=mcpgateway.services.token_storage_service \
       --cov-report=term-missing
```

### Vault Backend Coverage
```bash
pytest tests/unit/mcpgateway/services/test_vault_token_backend.py \
       --cov=mcpgateway.services.token_backends.vault_backend \
       --cov-report=html
```

## Parallel Execution

```bash
# Run tests in parallel (4 workers)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -n 4

# Auto-detect number of CPUs
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -n auto
```

## Filter by Test Name Pattern

```bash
# Run all tests with "backend" in the name
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -k "backend" -v

# Run all tests with "team_id" in the name
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -k "team_id" -v

# Run all tests with "vault" in the name
pytest tests/unit/mcpgateway/services/ -k "vault" -v

# Exclude tests with "cache" in the name
pytest tests/unit/mcpgateway/services/ -k "not cache" -v
```

## Test Markers

```bash
# Run only async tests
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -m asyncio -v

# Run all tests EXCEPT async
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -m "not asyncio" -v
```

## Debugging Failed Tests

### Show Full Traceback
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --tb=long
```

### Drop into Debugger on Failure
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --pdb
```

### Show Locals in Traceback
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -l
```

### Increase Verbosity
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -vv
```

## Test Statistics

### Show Test Durations
```bash
# Show slowest 10 tests
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --durations=10
```

### Count Tests Without Running
```bash
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py --collect-only
```

## Common Issues & Fixes

### Issue: "No module named pytest"
```bash
# Install dev dependencies
make install-dev

# Or directly
pip install pytest pytest-asyncio
```

### Issue: "No module named mcpgateway"
```bash
# Install package in development mode
pip install -e .

# Or run from project root
cd /Users/rakhidutta/mcp-context-forge
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -v
```

### Issue: "ImportError: cannot import name 'TokenStorageService'"
```bash
# Verify the module exists
python -c "from mcpgateway.services.token_storage_service import TokenStorageService; print('OK')"

# Check PYTHONPATH
echo $PYTHONPATH
```

### Issue: "RuntimeError: Event loop is closed"
```bash
# This is an asyncio test issue - ensure pytest-asyncio is installed
pip install pytest-asyncio

# Verify asyncio plugin is active
pytest --version
```

## CI/CD Integration

### Makefile Target (add to Makefile)
```makefile
.PHONY: test-token-storage
test-token-storage:
	@echo "Running OAuth token storage tests..."
	pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
	       tests/unit/mcpgateway/services/test_vault_token_backend.py \
	       -v --tb=short --cov=mcpgateway.services.token_storage_service \
	       --cov=mcpgateway.services.token_backends.vault_backend \
	       --cov-report=term-missing
```

### Run via Make
```bash
make test-token-storage
```

## Test Maintenance

### Update Tests After Code Changes
```bash
# Run all token storage tests
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       tests/unit/mcpgateway/services/test_vault_token_backend.py \
       -v --tb=short

# Check coverage
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       --cov=mcpgateway.services.token_storage_service \
       --cov-report=term-missing
```

### Validate Test Quality
```bash
# Check for test naming conventions
pytest --collect-only tests/unit/mcpgateway/services/test_token_storage_facade.py

# Count test cases
pytest --collect-only tests/unit/mcpgateway/services/ | grep "test session starts" -A 100
```

## Quick Test Validation Checklist

Before committing changes:

- [ ] All tests pass: `pytest tests/unit/mcpgateway/services/test_token_storage_facade.py -v`
- [ ] No syntax errors: `python -m py_compile tests/unit/mcpgateway/services/test_token_storage_facade.py`
- [ ] Coverage > 80%: Check coverage report
- [ ] No flaky tests: Run 3 times to verify consistency
- [ ] Tests run in < 5 seconds: Check with `--durations=10`

## Summary

**Total Test Cases:** 42
- Façade Tests: 28
- Vault Backend Tests: 14

**Average Test Time:** ~2-3 seconds for all tests

**Expected Results:**
- ✅ All façade backend selection tests pass
- ✅ All team ID extraction tests pass
- ✅ All delegation tests pass
- ⚠️  One Vault initialization test may need mock adjustment
- ✅ Integration tests verify full lifecycle

## Getting Help

If tests fail:
1. Check the error message and traceback
2. Review `UNIT_TEST_SUMMARY.md` for known issues
3. Verify environment setup: `source .venv/bin/activate`
4. Check imports: `python -c "from mcpgateway.services.token_storage_service import TokenStorageService"`
5. Run with verbose output: `pytest -vv --tb=long`
