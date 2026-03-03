# Regression Test Suite

This directory contains comprehensive regression tests for admin UI CRUD operations and state persistence.

## Running the Tests

### Run All Regression Tests
```bash
# From project root
pytest tests/playwright/regression/ -v

# With markers
pytest -m regression -v
```

### Run Specific Test Classes
```bash
# Virtual Server CRUD tests
pytest tests/playwright/regression/test_admin_crud_regression.py::TestVirtualServerCRUD -v

# State Persistence tests
pytest tests/playwright/regression/test_admin_crud_regression.py::TestStatePersistence -v

# Error Monitoring tests
pytest tests/playwright/regression/test_admin_crud_regression.py::TestErrorMonitoring -v
```

### Run Individual Tests
```bash
# Test create flow
pytest tests/playwright/regression/test_admin_crud_regression.py::TestVirtualServerCRUD::test_create_virtual_server_flow -v

# Test state persistence
pytest tests/playwright/regression/test_admin_crud_regression.py::TestStatePersistence::test_selected_tab_persists_after_refresh -v

# Test console errors
pytest tests/playwright/regression/test_admin_crud_regression.py::TestErrorMonitoring::test_no_console_errors_on_page_load -v
```

### Run with Headed Browser (Visual Debugging)
```bash
# See the browser in action
pytest tests/playwright/regression/ -v --headed

# With slow motion (500ms between actions)
pytest tests/playwright/regression/ -v --headed --slowmo 500
```

### Run with Screenshots on Failure
```bash
pytest tests/playwright/regression/ -v --screenshot on --video retain-on-failure
```

## Test Coverage

### TestVirtualServerCRUD (3 tests)
- ✅ `test_create_virtual_server_flow` - Create entity succeeds
- ✅ `test_edit_virtual_server_flow` - Edit entity saves correctly
- ✅ `test_delete_virtual_server_flow` - Delete entity succeeds

### TestStatePersistence (3 tests)
- ✅ `test_selected_tab_persists_after_refresh` - Tab state retained
- ✅ `test_team_context_persists_after_refresh` - Team context retained
- ✅ `test_filter_state_persists_after_refresh` - Filter state retained

### TestErrorMonitoring (4 tests)
- ✅ `test_no_console_errors_on_page_load` - No JS errors on load
- ✅ `test_no_failed_api_calls_on_page_load` - No failed API calls
- ✅ `test_no_console_errors_during_tab_navigation` - No errors during navigation
- ✅ `test_data_action_buttons_work_without_errors` - data-action pattern works

## Prerequisites

1. **Server Running**: Start the development server
   ```bash
   make dev
   # or
   python -m mcpgateway.main
   ```

   **Important**: `make dev` runs on port 8000 by default. Set the test base URL to match:
   ```bash
   export TEST_BASE_URL=http://localhost:8000
   ```

   Or if running on a different port:
   ```bash
   export TEST_BASE_URL=http://localhost:YOUR_PORT
   ```

2. **Environment Variables**: Ensure `.env` is configured
   ```bash
   AUTH_REQUIRED=false  # For easier testing
   # or have valid JWT_SECRET_KEY for auth tests
   ```

3. **Database**: Ensure database is initialized
   ```bash
   # SQLite (default)
   # Database will be created automatically

   # PostgreSQL
   # Ensure DATABASE_URL is set and migrations are run
   ```

## Debugging Failed Tests

### View Test Output
```bash
# Verbose output with print statements
pytest tests/playwright/regression/ -v -s

# Show local variables on failure
pytest tests/playwright/regression/ -v -l
```

### Interactive Debugging
```bash
# Drop into debugger on failure
pytest tests/playwright/regression/ -v --pdb

# Use Playwright Inspector
PWDEBUG=1 pytest tests/playwright/regression/ -v
```

### Check Screenshots and Videos
After test failures, check:
- `test-results/` directory for screenshots
- `test-results/` directory for videos (if enabled)

## Common Issues

### Issue: "ERR_CONNECTION_REFUSED" or "Connection refused"
**Solution**: The test is trying to connect to the wrong port. Set the correct base URL:
```bash
export TEST_BASE_URL=http://localhost:8000  # For make dev
# or
export TEST_BASE_URL=http://localhost:4444  # For make serve
```

### Issue: "No servers available to edit/delete"
**Solution**: Tests will skip if no data exists. Create some test data first or run create test first.

### Issue: "Team selector not available"
**Solution**: Tests will skip in single-team deployments. This is expected behavior.

### Issue: "Timeout waiting for element"
**Solution**:
- Increase timeout in test if server is slow
- Check if element selectors match your UI
- Run with `--headed` to see what's happening

### Issue: "Failed API calls detected"
**Solution**: Check if:
- Server is running and accessible
- Database is properly initialized
- Required services (Redis, etc.) are running

## Integration with CI

These tests are marked with `@pytest.mark.regression` and can be run in CI:

```yaml
# .github/workflows/test.yml
- name: Run Regression Tests
  run: pytest -m regression -v --screenshot on
```

## Test Maintenance

When adding new regression tests:
1. Follow the existing test structure
2. Use `error_collector` fixture to monitor errors
3. Add appropriate `@pytest.mark` decorators
4. Document test purpose in docstring
5. Handle edge cases with `pytest.skip()`
